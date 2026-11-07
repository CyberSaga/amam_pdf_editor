from __future__ import annotations

import io

import fitz
import pytest

from model.page_raster import rasterize_thumbnail
from src.render_worker.protocol import FrameDecoder, ProtocolError, validate_header
from src.render_worker.worker_main import Worker


def header(**changes):
    return dict(type='render', job='j', doc_key='d', page=0, scale=1.,
                profile='srgb', kind='thumb', **changes)


def test_optional_thumbnail_trim_keeps_pixels_and_document(monkeypatch):
    output = io.BytesIO()
    worker = Worker(output)
    worker.doc = fitz.open()
    worker.doc.new_page(width=240, height=240).insert_text((20, 30), 'same pixels')
    worker.key = 'd'
    expected = rasterize_thumbnail(worker.doc, 0, 'srgb')
    trims = []
    monkeypatch.setattr(fitz.TOOLS, 'store_shrink', trims.append)
    try:
        worker.render(header(trim_store=True))
        frames = FrameDecoder().feed(output.getvalue())
        assert bytes(frames[0].body) == expected.samples
        assert trims == [100]
        assert len(worker.doc) == 1 and worker.key == 'd'
        worker.render(header())
        assert trims == [100], 'single-worker control must retain its old cache policy'
    finally:
        worker.drop()


@pytest.mark.parametrize('value', [1, 'yes', None, [], {}])
def test_trim_policy_rejects_non_boolean_wire_values(value):
    with pytest.raises(ProtocolError):
        validate_header(header(trim_store=value), 0)


@pytest.mark.parametrize('value', [True, 0, -1, 17, 1.5, '4', None])
def test_trim_interval_is_a_bounded_integer(value):
    with pytest.raises(ProtocolError):
        validate_header(header(trim_store=True, trim_store_interval=value), 0)


def test_batch_trim_retains_between_pages_and_resets_on_document_drop(monkeypatch):
    worker = Worker(io.BytesIO())
    worker.doc = fitz.open()
    worker.doc.new_page(width=80, height=80)
    worker.key = 'd'
    trims = []
    monkeypatch.setattr(fitz.TOOLS, 'store_shrink', trims.append)
    try:
        for _ in range(3):
            worker.render(header(trim_store=True, trim_store_interval=4))
        assert trims == []
        worker.render(header(trim_store=True, trim_store_interval=4))
        assert trims == [100]
        worker.render(header(trim_store=True, trim_store_interval=4))
        worker.drop()
        trims.clear()
        worker.doc = fitz.open()
        worker.doc.new_page(width=80, height=80)
        worker.key = 'd'
        for _ in range(3):
            worker.render(header(trim_store=True, trim_store_interval=4))
        assert trims == []
    finally:
        worker.drop()


def test_batch_trim_releases_store_on_render_failure(monkeypatch):
    worker = Worker(io.BytesIO())
    worker.doc = fitz.open()
    worker.doc.new_page(width=80, height=80)
    worker.key = 'd'
    trims = []
    monkeypatch.setattr(fitz.TOOLS, 'store_shrink', trims.append)
    try:
        worker.render({**header(trim_store=True, trim_store_interval=4), 'page': 99})
        assert trims == [100]
    finally:
        worker.drop()
