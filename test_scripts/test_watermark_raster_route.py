from __future__ import annotations

import json

import fitz
import pytest

from model.color_profile import safe_to_fitz_colorspace
from model.page_raster import rasterize_page, rasterize_thumbnail
from model.pdf_model import PDFModel


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
@pytest.mark.parametrize('profile', ['srgb', 'gray', 'cmyk'])
@pytest.mark.parametrize('thumbnail', [False, True])
@pytest.mark.parametrize('userunit', [1.0, 2.0])
def test_frozen_watermark_raster_matches_model_view_without_mutation(tmp_path, rotation, profile, thumbnail, userunit):
    path = tmp_path / 'overlay.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=310, height=420)
        page.insert_text((40, 90), 'Original content')
        page.add_rect_annot(fitz.Rect(45, 100, 160, 180)).update()
        page.set_cropbox(fitz.Rect(10, 15, 290, 390))
        page.set_rotation(rotation)
        doc.xref_set_key(page.xref, 'UserUnit', str(userunit))
        doc.new_page(width=200, height=200).insert_text((20, 50), 'Uncovered page')
        doc.save(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.tools.watermark.add_watermark(
            pages=[1], text='水印\nOverlay', angle=32.5, opacity=0.43,
            font_size=19.75, offset_x=6.25, offset_y=-8.5,
        )
        recipe = json.dumps(model.get_print_watermarks(), ensure_ascii=False).encode('utf-8')
        snapshot = model.capture_worker_snapshot_bytes()
        expected = (model.get_thumbnail(1, colorspace=safe_to_fitz_colorspace(profile)) if thumbnail else
                    model.get_page_pixmap(1, scale=1.25, colorspace=safe_to_fitz_colorspace(profile)))
        if expected.colorspace.n in {1, 4}:
            expected = fitz.Pixmap(fitz.csRGB, expected)
        with fitz.open(stream=snapshot, filetype='pdf') as worker_doc:
            before = worker_doc.tobytes(no_new_id=True)
            if thumbnail:
                actual = rasterize_thumbnail(worker_doc, 0, profile, watermarks_json=recipe)
            else:
                actual = rasterize_page(worker_doc, 0, 1.25, profile, watermarks_json=recipe)
            assert (actual.width, actual.height, actual.stride) == (expected.width, expected.height, expected.stride)
            assert actual.samples == expected.samples
            assert worker_doc.tobytes(no_new_id=True) == before
            plain = rasterize_page(worker_doc, 1, 1.25, profile)
            uncovered = rasterize_page(worker_doc, 1, 1.25, profile, watermarks_json=recipe)
            assert uncovered == plain
    finally:
        model.close()


@pytest.mark.parametrize('invalid', [b'null', b'{}', b'[123]', b'\xff', b'[' * 1000,
                                    b'[]' + b' ' * (48 * 1024), bytearray(b'[]')],
                         ids=['null', 'object', 'entry', 'encoding', 'nesting', 'oversize', 'mutable'])
def test_malformed_frozen_recipe_never_becomes_empty_success(invalid):
    from model.watermark_raster import decode_watermark_recipe

    with pytest.raises(ValueError, match='invalid watermark recipe'):
        decode_watermark_recipe(invalid)


@pytest.mark.parametrize('dirty', [False, True])
def test_overlay_clone_reuses_clean_bytes_but_keeps_live_edits(monkeypatch, dirty):
    from test_scripts.test_watermark_worker_route import recipe

    with fitz.open() as original:
        original.new_page(width=200, height=250).insert_text((20, 40), 'Before')
        data = original.tobytes()
    with fitz.open(stream=data, filetype='pdf') as document:
        if dirty:
            document[0].insert_text((20, 100), 'Unsaved edit')
        live_bytes = document.tobytes(no_new_id=True)
        original_serialize = fitz.Document.tobytes
        serialized = []

        def record_serialize(self, *args, **kwargs):
            if self is document:
                serialized.append(True)
            return original_serialize(self, *args, **kwargs)

        monkeypatch.setattr(fitz.Document, 'tobytes', record_serialize)
        actual = rasterize_page(document, 0, 1.25, 'srgb', watermarks_json=recipe().encode())
        assert len(serialized) == int(dirty)
        with fitz.open(stream=live_bytes, filetype='pdf') as oracle:
            expected = rasterize_page(oracle, 0, 1.25, 'srgb', watermarks_json=recipe().encode())
        assert actual == expected


@pytest.mark.parametrize('field,value', [('opacity', True), ('angle', float('nan')),
                                       ('pages', [True]), ('unknown', 'discard me')])
def test_recipe_rejects_coercion_instead_of_changing_frozen_ink(field, value):
    from model.watermark_raster import decode_watermark_recipe
    from test_scripts.test_watermark_worker_route import recipe

    values = json.loads(recipe())
    values[0][field] = value
    with pytest.raises(ValueError, match='invalid watermark recipe'):
        decode_watermark_recipe(json.dumps(values).encode())


@pytest.mark.parametrize('thumbnail', [False, True])
def test_saved_reopened_overlay_is_stamped_exactly_once_across_two_saves(tmp_path, thumbnail):
    path = tmp_path / 'original.pdf'
    with fitz.open() as document:
        document.new_page(width=300, height=400).insert_text((30, 90), 'Persistent content')
        document.save(path)
    model = PDFModel()
    try:
        model.open_pdf(str(path))
        model.tools.watermark.add_watermark(pages=[1], text='Overlay', angle=32.5,
                                           opacity=.43, font_size=21.75)
        baseline = model.get_thumbnail(1) if thumbnail else model.get_page_pixmap(1, scale=1.25)
        for generation in range(2):
            saved = tmp_path / f'saved-{generation}.pdf'
            model.save_as(str(saved))
            model.close()
            model = PDFModel()
            model.open_pdf(str(saved))
            recipe = json.dumps(model.get_print_watermarks(), ensure_ascii=False).encode()
            assert recipe != b'[]'
            with fitz.open(stream=model.capture_worker_snapshot_bytes(), filetype='pdf') as worker:
                before = worker.tobytes(no_new_id=True)
                actual = (rasterize_thumbnail(worker, 0, 'srgb', watermarks_json=recipe) if thumbnail else
                          rasterize_page(worker, 0, 1.25, 'srgb', watermarks_json=recipe))
                assert actual.samples == baseline.samples
                assert worker.tobytes(no_new_id=True) == before
    finally:
        model.close()
