from __future__ import annotations

import io

import fitz
import pytest

from model.page_raster import HotPageRaster, rasterize_page, rasterize_thumbnail
from src.render_worker.protocol import FrameDecoder, ProtocolError, validate_header
from src.render_worker.worker_main import Worker


def document():
    doc = fitz.open()
    for number in range(10):
        page = doc.new_page(width=260, height=320)
        page.insert_text((30, 50), f'Page {number}')
        page.add_rect_annot(fitz.Rect(40, 90, 120, 140)).update()
        page.set_cropbox(fitz.Rect(10, 20, 240, 300))
        page.set_rotation((number % 4) * 90)
    return doc


@pytest.mark.parametrize('profile', ['srgb', 'gray', 'cmyk'])
@pytest.mark.parametrize('number', [0, 1, 2, 3])
def test_promotion_pixels_and_geometry_match_page_path(profile, number):
    with document() as doc:
        cache = HotPageRaster(doc)
        for scale, expected_state in [(1.125, 'page'), (1.25, 'build'), (1.375, 'hit')]:
            actual = cache.render(number, scale, profile, retain=True)
            assert actual == rasterize_page(doc, number, scale, profile)
            assert cache.last_path == expected_state
        assert cache.render(number, 1, profile, thumbnail=True, retain=True) == rasterize_thumbnail(doc, number, profile)
        assert cache.last_path == 'hit'


def test_default_does_not_retain_and_thumbnails_do_not_promote():
    with document() as doc:
        cache = HotPageRaster(doc)
        for _ in range(3):
            cache.render(0, 1, 'srgb')
            cache.render(1, 1, 'srgb', thumbnail=True, retain=True)
        assert not cache.retained_pages and not cache.seen_pages
        cache.render(0, 1, 'srgb', retain=True)
        cache.render(0, 1, 'srgb', retain=True)
        assert cache.retained_pages == (0,)
        cache.render(0, 1, 'srgb')
        assert not cache.retained_pages and not cache.seen_pages


def test_cache_bounds_and_lru():
    with document() as doc:
        cache = HotPageRaster(doc)
        for number in range(10):
            cache.render(number, 1, 'srgb', retain=True)
        assert len(cache.seen_pages) == 8
        for number in [7, 8, 7, 9]:
            cache.render(number, 1, 'srgb', retain=True)
        assert cache.retained_pages == (9,)
        cache.clear()
        assert not cache.retained_pages and not cache.seen_pages


def test_low_high_of_same_viewport_intent_does_not_promote():
    with document() as doc:
        cache = HotPageRaster(doc)
        cache.render(0, .5, 'srgb', retain=True, intent='open:1')
        cache.render(0, 1., 'srgb', retain=True, intent='open:1')
        assert not cache.retained_pages
        cache.render(0, 1.25, 'srgb', retain=True, intent='zoom:2')
        assert cache.retained_pages == (0,)


def test_prefetch_and_low_quality_do_not_establish_foreground_demand():
    with document() as doc:
        cache = HotPageRaster(doc)
        for intent in ['prefetch:1', 'prefetch:2']:
            cache.render(0, .5, 'srgb', retain=True, intent=intent, promotion_allowed=False)
        assert not cache.seen_pages and not cache.retained_pages
        cache.render(0, 1., 'srgb', retain=True, intent='visible:3')
        assert not cache.retained_pages
        cache.render(0, 1.25, 'srgb', retain=True, intent='visible:4')
        assert cache.retained_pages == (0,)
        cache.render(0, .5, 'srgb', retain=True, intent='prefetch:5', promotion_allowed=False)
        assert cache.last_path == 'hit', 'ineligible promotion may still reuse immutable content'


@pytest.mark.parametrize('value', [1, None, 'yes', [], {}])
def test_promotion_policy_requires_boolean(value):
    with pytest.raises(ProtocolError):
        validate_header(render_header(promotion_allowed=value), 0)


@pytest.mark.parametrize('value', [1, None, '', 'x' * 129, [], {}])
def test_invalid_foreground_intent_is_rejected(value):
    with pytest.raises(ProtocolError):
        validate_header(render_header(foreground_intent=value), 0)


def test_failed_build_is_not_published(monkeypatch):
    with document() as doc:
        cache = HotPageRaster(doc)
        cache.render(0, 1, 'srgb', retain=True)
        original = fitz.Page.get_displaylist

        def fail(page, **kwargs):
            raise RuntimeError('injected list build failure')

        monkeypatch.setattr(fitz.Page, 'get_displaylist', fail)
        with pytest.raises(RuntimeError):
            cache.render(0, 1, 'srgb', retain=True)
        assert not cache.retained_pages
        monkeypatch.setattr(fitz.Page, 'get_displaylist', original)
        assert cache.render(0, 1, 'srgb', retain=True) == rasterize_page(doc, 0, 1, 'srgb')


@pytest.mark.parametrize('promoted', [False, True])
def test_failed_samples_cannot_leave_retained_entry(monkeypatch, promoted):
    import model.page_raster as module
    with document() as doc:
        cache = HotPageRaster(doc)
        cache.render(0, 1, 'srgb', retain=True)
        if promoted:
            cache.render(0, 1.25, 'srgb', retain=True)

        def fail(pix):
            raise RuntimeError('injected sample ownership failure')

        monkeypatch.setattr(module, '_samples', fail)
        with pytest.raises(RuntimeError):
            cache.render(0, 1.5, 'srgb', retain=True)
        assert not cache.retained_pages


def test_scale_clamp_is_identical_on_retained_and_page_paths(monkeypatch):
    import utils.render_limits as limits
    monkeypatch.setattr(limits, '_MAX_PIXMAP_PX', 1000)
    with document() as doc:
        cache = HotPageRaster(doc)
        cache.render(0, 5, 'srgb', retain=True)
        assert cache.render(0, 10, 'srgb', retain=True) == rasterize_page(doc, 0, 10, 'srgb')


@pytest.mark.parametrize('visible', [True, False])
def test_immutable_optional_content_matches_loaded_document(visible):
    with fitz.open() as source:
        page = source.new_page(width=180, height=180)
        layer = source.add_ocg('immutable layer', on=visible)
        page.insert_text((20, 30), 'LAYER CONTENT', oc=layer)
        data = source.tobytes()
    with fitz.open(stream=data, filetype='pdf') as doc:
        cache = HotPageRaster(doc)
        cache.render(0, 1, 'srgb', retain=True)
        assert cache.render(0, 1.25, 'srgb', retain=True) == rasterize_page(doc, 0, 1.25, 'srgb')
        assert cache.last_path == 'build'
        assert cache.render(0, 1.5, 'srgb', retain=True) == rasterize_page(doc, 0, 1.5, 'srgb')
        assert cache.last_path == 'hit'
        # Prove the fixture's OFF variant really excludes its optional text.
        white = rasterize_page(doc, 0, 1, 'srgb')
        assert (set(white.samples) == {255}) is (not visible)


def render_header(**changes):
    result = dict(type='render', job='j', doc_key='d', page=0, scale=1., profile='srgb', kind='page')
    result.update(changes)
    return result


@pytest.mark.parametrize('value', [1, 'yes', None, [], {}])
def test_retention_wire_policy_is_boolean(value):
    with pytest.raises(ProtocolError):
        validate_header(render_header(retain_display_lists=value), 0)


def test_worker_releases_cache_before_closing_document(monkeypatch):
    output = io.BytesIO()
    worker = Worker(output)
    worker.doc = document()
    worker.key = 'd'
    worker.render(render_header(retain_display_lists=True))
    worker.render(render_header(retain_display_lists=True))
    assert worker.raster_cache.retained_pages == (0,)
    cache = worker.raster_cache
    original = fitz.Document.close

    def checked_close(doc):
        assert not cache.retained_pages and not cache.seen_pages
        original(doc)

    monkeypatch.setattr(fitz.Document, 'close', checked_close)
    worker.drop()
    assert worker.raster_cache is None
    worker.doc = document()
    worker.key = 'd'
    worker.render(render_header(retain_display_lists=True))
    frames = FrameDecoder().feed(output.getvalue())
    assert [frame.header['raster_path'] for frame in frames] == ['page', 'build', 'page']
    worker.drop()
