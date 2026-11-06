from __future__ import annotations

import time

import fitz
from PySide6.QtCore import QTimer

from src.render_worker.process_client import DocSource, RenderJob, RenderProcessClient
from model.page_raster import rasterize_page


def wait(qapp, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.001)
    assert predicate()


def test_live_process_pixels_responsiveness_and_shutdown(qapp):
    with fitz.open() as doc:
        page = doc.new_page(width=240, height=240)
        # Build a 200k-segment stream directly, avoiding quadratic Python
        # string assembly in Shape.draw_line while preserving real MuPDF work.
        segments = b'\n'.join(f'10 {i / 10} m 220 {i / 10 + .01} l'.encode()
                              for i in range(2000))
        xref = doc.get_new_xref()
        doc.update_object(xref, '<<>>')
        doc.update_stream(xref, b'q .1 w\n' + (segments + b'\n') * 100 + b'S Q')
        page.set_contents(xref)
        data = doc.tobytes()
        expected = rasterize_page(doc, 0, 4., 'srgb')
    client = RenderProcessClient()
    results = []
    client.job_done.connect(lambda key, outcome: results.append(outcome))
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    try:
        client.start()
        wait(qapp, lambda: client.ready)
        assert client._worker_pid == client._process.processId(), 'QProcess must own the raster, not a venv launcher'
        pid = client.pid
        timer.start()
        client.submit(RenderJob('live', client.register_owner(), 'page',
                                DocSource('live@0', None, lambda: data), 0, 4., 'srgb'))
        wait(qapp, lambda: bool(results), timeout=30)
        assert results[0].status == 'image'
        image = results[0].image
        assert bytes(image.constBits()) == expected.samples
        assert len(ticks) > 2
        assert max(b - a for a, b in zip(ticks, ticks[1:])) < .1
        assert client.metrics['images'] == 1 and pid > 0
    finally:
        timer.stop()
        process = client._process
        client.shutdown()
        assert process.state().value == 0
