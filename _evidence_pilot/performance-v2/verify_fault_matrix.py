from __future__ import annotations

# ruff: noqa: E402 -- diagnostic configuration precedes the public entry.
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ['PDF_EDITOR_RENDER_WORKER'] = 'process'
from PySide6.QtTest import QTest
from test_scripts.test_text_commit_finalize_by_result import _author
import main

path = _author(Path(__file__).parent / 'fault-matrix.pdf', pages=3)
state = main.run(argv=[str(path)], start_event_loop=False)
app, view, model, controller = (state[key] for key in ('app', 'view', 'model', 'controller'))
pool = state['render_client']
notices = []
controller._show_notice_feedback = notices.append


def wait(predicate, label, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            print('OK', label, flush=True)
            return
        QTest.qWait(5)
    raise AssertionError(label)


def quality(page):
    return controller._page_quality_map(model.get_active_session_id()).get(page)


def current_page_job(child):
    active = controller._page_render_coordinator._active
    return bool(active is not None and controller._page_render_coordinator._is_current(active.identity)
                and child._active is not None and child._active.job_id == active.identity.token)


view.show()
wait(lambda: quality(0) == 'high', 'initial high')
model.tools.watermark.add_watermark(pages=[1, 2, 3], text='Fault', opacity=.4)
controller._invalidate_active_render_state()
view.continuous_pages = False
controller.show_page(0)
wait(lambda: quality(0) == 'high' and not controller._page_render_coordinator.has_active_job, 'single high with watermark')
child = pool.children[0]
controller.show_page(1)
wait(lambda: current_page_job(child), 'page 2 job in flight')
child._process.kill()
wait(lambda: bool(notices), 'user is told about the lost page')
print('NOTICE', notices[0], flush=True)
assert controller._raster_quarantined(model.get_active_session_id(), 1)
controller.show_page(2)
wait(lambda: quality(2) == 'high', 'next page renders after crash')
view.grab().save(str(Path(__file__).parent / 'fault-matrix.png'))
controller.show_page(0)
wait(lambda: quality(0) == 'high', 'first page still usable')
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox


def discard_unsaved():
    for widget in app.topLevelWidgets():
        if isinstance(widget, QMessageBox) and widget.isVisible():
            print('MODAL', widget.text()[:60], flush=True)
            for button in widget.buttons():
                if 'iscard' in button.text() or '不儲存' in button.text() or '放棄' in button.text():
                    button.click()
                    return
            widget.reject()


watch = QTimer()
watch.timeout.connect(discard_unsaved)
watch.start(100)
QTimer.singleShot(0, view.close)
app.exec()
model.close()
assert pool._process is None and not pool.has_live_processes, 'child must be reaped'
print('VERIFIED child reaped', flush=True)
