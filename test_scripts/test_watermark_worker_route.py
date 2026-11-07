from __future__ import annotations

import hashlib
import json

import fitz
import pytest

from model.page_raster import rasterize_page, rasterize_thumbnail
from src.render_worker.protocol import ProtocolError, validate_header
from test_scripts.test_render_worker_child import _pdf, _run


def recipe():
    return json.dumps([dict(id='wm', pages=[1], text='Worker watermark', font='helv',
                           font_size=20.5, angle=32.5, opacity=0.43, color=[0.3, 0.4, 0.5],
                           offset_x=0.0, offset_y=0.0, line_spacing=1.3)])


@pytest.mark.parametrize('kind', ['page', 'thumb'])
def test_child_renders_frozen_overlay_and_echoes_recipe_identity(kind):
    data = _pdf()
    overlay = recipe()
    commands = [({'type': 'load_bytes', 'doc_key': 'frozen', 'watermarks_json': overlay,
                  'overlay_schema': 1}, data),
                (dict(type='render', job='r', doc_key='frozen', page=0, scale=1.25,
                      profile='srgb', kind=kind, retain_display_lists=True), b''),
                ({'type': 'quit'}, b'')]
    frames, stderr = _run(commands)
    ack = next(frame.header for frame in frames if frame.header['type'] == 'doc_ready')
    assert ack.get('overlay_sha256') == hashlib.sha256(overlay.encode()).hexdigest()
    image = next(frame for frame in frames if frame.header['type'] == 'image')
    with fitz.open(stream=data, filetype='pdf') as doc:
        expected = (rasterize_thumbnail(doc, 0, 'srgb', watermarks_json=overlay.encode()) if kind == 'thumb'
                    else rasterize_page(doc, 0, 1.25, 'srgb', watermarks_json=overlay.encode()))
    assert bytes(image.body) == expected.samples
    assert image.header['raster_path'] == 'overlay'
    assert b'Traceback' not in stderr


@pytest.mark.parametrize('overlay,version', [('not-json', 1), ('{}', 1), ('[]', 2), (123, 1)])
def test_bad_overlay_wire_is_rejected_instead_of_omitted(overlay, version):
    with pytest.raises(ProtocolError):
        validate_header(dict(type='load_bytes', doc_key='d', watermarks_json=overlay,
                             overlay_schema=version), 1)


def test_path_source_cannot_load_overlay_recipe():
    with pytest.raises(ProtocolError):
        validate_header(dict(type='load_path', doc_key='d', path='unused', size=1, mtime_ns=1,
                             watermarks_json=recipe(), overlay_schema=1), 0)
