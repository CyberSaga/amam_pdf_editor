from __future__ import annotations

import time

import fitz
import pytest
from PySide6.QtCore import QTimer

from src.render_worker.process_client import DocSource, RenderJob, RenderProcessClient
from src.render_worker.resource_ledger import ResourceLedger
from model.page_raster import rasterize_page


def wait(qapp, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.001)
    assert predicate()


@pytest.mark.parametrize('with_ledger', [False, True])
def test_live_process_pixels_responsiveness_and_shutdown(qapp, with_ledger):
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
    # Synthetic accounting amount exercises lease lifetime, not native sizing.
    ledger = ResourceLedger(byte_limit=1234, slot_limit=1) if with_ledger else None
    client = RenderProcessClient(resource_ledger=ledger, process_reservation_bytes=1234)
    results = []
    client.job_done.connect(lambda key, outcome: results.append(outcome))
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
    try:
        client.start()
        wait(qapp, lambda: client.ready)
        if ledger is not None:
            assert ledger.reserved_bytes == 1234 and ledger.compute_slots == 1
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
        client.shutdown()
        wait(qapp, lambda: client._process is None)
        # QProcess may already have been deleted after its finished signal.
        assert client.pid == 0
        if ledger is not None:
            assert ledger.reserved_bytes == 0 and ledger.compute_slots == 0
