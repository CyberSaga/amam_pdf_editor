"""Red-light tests for the Phase 2 conftest leak guards (``scripts/pytest_leak_guards.py``).

Governing plan: ``plans/test-suite-never-hangs.md`` ("Phase 2").  The guards are three function-scoped
autouse fixtures that make the LEAKER (not an innocent later test) red:

* ``gui``    -- a visible top-level ``PDFView`` / inline editor outlived the test;
* ``thread`` -- a ``QThread`` started during the test is still running;
* ``modal``  -- a modal dialog call (``QMessageBox.*`` / ``QDialog.exec``) was not patched or marked
  ``real_modal``.

Every test that creates Qt objects runs its inner test file through ``runpytest_subprocess``: an in-process
inner run would leak into THIS test's own guards and into the outer ``QApplication``.  The plugin is imported
lazily (inside helpers) so a missing plugin turns each test red on its own instead of one collection error.
"""

from __future__ import annotations

import ast
import json
import os
import re
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest_plugins = ("pytester",)

ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = ROOT / "test_scripts"
PLUGIN = "scripts.pytest_leak_guards"
SUBPROCESS_TIMEOUT_S = 120


def _guards():
    """The plugin module; imported lazily so its absence fails the test, not the collection."""
    import importlib

    return importlib.import_module(PLUGIN)


# --------------------------------------------------------------------------- inner-run helpers

_PRELUDE = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
sys.path.insert(0, {str(TEST_DIR)!r})

import pytest
from PySide6.QtWidgets import QApplication

# Created at import time: the gui guard stands down for a test that starts without a QApplication.
_APP = QApplication.instance() or QApplication([])
"""

# A real modal that slips through (guard absent / broken) would block an offscreen run forever.  This timer
# rejects any modal widget it finds in a nested event loop, so the failure is an assertion, not a hang.  It is
# (re)started by an autouse fixture at the setup of each test, never at import: no event loop runs between
# collection and the test body, so a timer armed at import would already be overdue when a slow guard setup
# lets the first loop iteration run, and would reject the genuine dialog before the test's own 50 ms accept.
_MODAL_WATCHDOG = """
from PySide6.QtCore import QTimer



def _reject_stray_modal():
    modal = QApplication.activeModalWidget()
    if modal is not None:
        modal.reject()


_WATCHDOG = QTimer(_APP)
_WATCHDOG.setInterval(5000)
_WATCHDOG.timeout.connect(_reject_stray_modal)


@pytest.fixture(autouse=True)
def _arm_modal_watchdog():
    _WATCHDOG.start()
    yield
    _WATCHDOG.stop()
"""


def _source(body: str, *, modal_watchdog: bool = False) -> str:
    parts = [_PRELUDE, _MODAL_WATCHDOG if modal_watchdog else "", textwrap.dedent(body)]
    return "\n".join(textwrap.dedent(p) for p in parts)


def _inner_env(monkeypatch) -> None:
    pythonpath = os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH", "")]))
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # An outer record-mode / heartbeat run must not leak into the inner runs under test.
    monkeypatch.delenv("PDF_EDITOR_LEAK_GUARD_REPORT", raising=False)
    monkeypatch.delenv("PDF_EDITOR_TEST_HEARTBEAT", raising=False)


def _run_inner(pytester, monkeypatch, *extra: str):
    _inner_env(monkeypatch)
    return pytester.runpytest_subprocess(
        "-p", PLUGIN, "-p", "no:cacheprovider", "--strict-markers", *extra, timeout=SUBPROCESS_TIMEOUT_S
    )


_GUI_LEAKER = """
from view.pdf_view import PDFView

_KEEP = []


def test_leaks_view():
    view = PDFView()
    view.show()
    _KEEP.append(view)  # never disposed: the visible window outlives the test


def test_second_is_clean():
    assert True
"""

_GUI_CLEAN = """
import qt_teardown
from view.pdf_view import PDFView


def test_disposes_its_view():
    view = PDFView()
    view.show()
    qt_teardown.dispose_pdf_view(view)
"""

# Threads that end by themselves after ~1 s: the interpreter must not exit with a running QThread.
_THREAD_HEAD = """
import time

from PySide6.QtCore import QThread


class SlowThread(QThread):
    def run(self):
        time.sleep(1.0)
"""

_THREAD_LEAKER = _THREAD_HEAD + """
_KEPT = []


@pytest.fixture(scope="module", autouse=True)
def _join_everything_at_module_end():
    yield
    for thread in _KEPT:
        assert thread.wait(10000)


def test_leaks_thread():
    thread = SlowThread()
    thread.setObjectName("slow-leaker")
    _KEPT.append(thread)
    thread.start()  # returns at once; the thread is still running when the test ends


def test_joins_its_thread():
    thread = SlowThread()
    _KEPT.append(thread)
    thread.start()
    assert thread.wait(10000)
"""

_THREAD_PRESTARTED = _THREAD_HEAD + """
@pytest.fixture(scope="module")
def prestarted():
    thread = SlowThread()
    thread.start()  # module scope: started before the function-scoped guard sets up
    yield thread
    assert thread.wait(10000)


def test_sees_a_thread_it_did_not_start(prestarted):
    assert prestarted.isRunning()


def test_still_nothing_to_report(prestarted):
    assert prestarted is not None
"""

_GUI_CURSOR_LEAKER = """
from PySide6.QtCore import Qt


def test_leaves_an_override_cursor():
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)  # never restored


def test_next_is_clean():
    assert QApplication.overrideCursor() is None
"""

# Ends by itself ~0.1 s after the test body returned: a worker that is still exiting, not a leak.
_THREAD_ENDS_SOON = """
import time

from PySide6.QtCore import QThread

_KEPT = []


class ShortThread(QThread):
    def run(self):
        time.sleep(0.1)


@pytest.fixture(scope="module", autouse=True)
def _join_everything_at_module_end():
    yield
    for thread in _KEPT:
        assert thread.wait(10000)


def test_starts_a_thread_that_ends_on_its_own():
    thread = ShortThread()
    _KEPT.append(thread)
    thread.start()  # not waited for: the guard's bounded settle window sees it finish
"""


# --------------------------------------------------------------------------- 1. public surface


def test_plugin_public_names() -> None:
    guards = _guards()
    assert guards.REPORT_ENV == "PDF_EDITOR_LEAK_GUARD_REPORT"
    assert issubclass(guards.UnexpectedModalDialog, RuntimeError)
    assert issubclass(guards.LeakGuardWarning, UserWarning)
    for name in ("_KNOWN_GUI_LEAKERS", "_KNOWN_THREAD_LEAKERS"):
        value = getattr(guards, name)
        assert isinstance(value, frozenset), name
        for entry in value:  # emptiness is no longer part of the contract; the gate test checks existence
            assert re.fullmatch(r"test_[A-Za-z0-9_]+\.py", entry), f"{name} entry {entry!r} is not a test file name"
    assert guards.GUARDED_MODAL_CALLS == (
        ("QMessageBox", "exec"),
        ("QMessageBox", "information"),
        ("QMessageBox", "warning"),
        ("QMessageBox", "critical"),
        ("QMessageBox", "question"),
        ("QDialog", "exec"),
    )
    assert callable(guards.module_key)
    assert callable(guards.report_finding)
    assert callable(guards.pytest_configure)


# --------------------------------------------------------------------------- 2. module_key / report_finding


def _fake_item(file_name: str = "test_x.py") -> SimpleNamespace:
    return SimpleNamespace(path=Path("some") / "dir" / file_name, nodeid=f"some/dir/{file_name}::test_a")


def test_module_key_is_the_file_name() -> None:
    guards = _guards()
    assert guards.module_key(_fake_item("test_x.py")) == "test_x.py"
    assert guards.module_key(_fake_item("test_other_file.py")) == "test_other_file.py"


def test_report_finding_record_mode_writes_json_and_warns(monkeypatch, tmp_path) -> None:
    guards = _guards()
    target = tmp_path / "nested" / "report.jsonl"
    target.parent.mkdir()
    monkeypatch.setenv(guards.REPORT_ENV, str(target))
    item = _fake_item("test_rec.py")

    with pytest.warns(guards.LeakGuardWarning, match="record me"):
        guards.report_finding("gui", item, "record me", allowlist=frozenset())
    # Record mode wins over the allowlist and never fails.
    with pytest.warns(guards.LeakGuardWarning):
        guards.report_finding("thread", item, "and me", allowlist=frozenset({"test_rec.py"}))

    lines = target.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first, second = (json.loads(line) for line in lines)
    assert set(first) == {"guard", "nodeid", "module", "detail", "pid"}
    assert first == {
        "guard": "gui",
        "nodeid": "some/dir/test_rec.py::test_a",
        "module": "test_rec.py",
        "detail": "record me",
        "pid": os.getpid(),
    }
    assert (second["guard"], second["detail"]) == ("thread", "and me")


def test_report_finding_allowlisted_module_only_warns(monkeypatch) -> None:
    guards = _guards()
    monkeypatch.delenv(guards.REPORT_ENV, raising=False)
    with pytest.warns(guards.LeakGuardWarning, match="excused"):
        guards.report_finding("gui", _fake_item("test_listed.py"), "excused", allowlist=frozenset({"test_listed.py"}))


def test_report_finding_unlisted_module_fails(monkeypatch) -> None:
    guards = _guards()
    monkeypatch.delenv(guards.REPORT_ENV, raising=False)
    with pytest.raises(pytest.fail.Exception, match="the leak detail"):
        guards.report_finding(
            "gui", _fake_item("test_unlisted.py"), "the leak detail", allowlist=frozenset({"test_listed.py"})
        )


# --------------------------------------------------------------------------- 4/5. gui guard


def test_gui_guard_fails_the_leaker_once_and_hides_the_leak(pytester, monkeypatch) -> None:
    pytester.makepyfile(test_gui_leak=_source(_GUI_LEAKER))
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=2, errors=1)  # the leaker's body passes, its teardown errors; test 2 is clean
    out = result.stdout.str()
    assert "leak guard [gui]" in out
    assert "test_gui_leak.py::test_leaks_view" in out
    assert "visible top-level PDFView" in out
    assert "ERROR test_gui_leak.py::test_second_is_clean" not in out


def test_gui_guard_is_silent_for_a_test_that_disposes_its_view(pytester, monkeypatch) -> None:
    pytester.makepyfile(test_gui_clean=_source(_GUI_CLEAN))
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=1)
    assert "leak guard" not in result.stdout.str()
    assert "LeakGuardWarning" not in result.stdout.str()


def test_gui_guard_allowlisted_module_only_warns(pytester, monkeypatch) -> None:
    pytester.makeconftest(
        """
        import scripts.pytest_leak_guards as guards

        guards._KNOWN_GUI_LEAKERS = frozenset({"test_gui_leak_allowed.py"})
        """
    )
    pytester.makepyfile(test_gui_leak_allowed=_source(_GUI_LEAKER))
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=2)
    assert "LeakGuardWarning" in result.stdout.str()
    assert "leak guard [gui]" in result.stdout.str()


def test_gui_guard_reports_an_override_cursor_left_behind(pytester, monkeypatch) -> None:
    pytester.makepyfile(test_gui_cursor=_source(_GUI_CURSOR_LEAKER))
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=2, errors=1)  # no window involved: only the cursor branch can find this
    out = result.stdout.str()
    assert "leak guard [gui]" in out
    assert "an application override cursor outlived the test" in out
    assert "test_gui_cursor.py::test_leaves_an_override_cursor" in out


# --------------------------------------------------------------------------- 6. thread guard


def test_thread_guard_fails_the_test_that_leaves_a_running_thread(pytester, monkeypatch) -> None:
    pytester.makepyfile(test_thread_leak=_source(_THREAD_LEAKER))
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=2, errors=1)  # only test_leaks_thread errors; the joining sibling is clean
    out = result.stdout.str()
    assert "leak guard [thread]" in out
    assert "slow-leaker" in out
    assert "test_thread_leak.py::test_leaks_thread" in out
    assert "ERROR test_thread_leak.py::test_joins_its_thread" not in out


def test_thread_guard_allowlisted_module_only_warns(pytester, monkeypatch) -> None:
    pytester.makeconftest(
        """
        import scripts.pytest_leak_guards as guards

        guards._KNOWN_THREAD_LEAKERS = frozenset({"test_thread_leak_allowed.py"})
        """
    )
    pytester.makepyfile(test_thread_leak_allowed=_source(_THREAD_LEAKER))
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=2)
    assert "LeakGuardWarning" in result.stdout.str()
    assert "leak guard [thread]" in result.stdout.str()


def test_thread_guard_gives_a_finishing_worker_a_bounded_moment_to_exit(pytester, monkeypatch) -> None:
    pytester.makepyfile(test_thread_ends_soon=_source(_THREAD_ENDS_SOON))
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=1)  # it ends on its own ~0.1 s later: not a leak
    assert "leak guard" not in result.stdout.str()


def test_thread_guard_ignores_a_thread_started_before_the_test(pytester, monkeypatch) -> None:
    pytester.makepyfile(test_thread_prestarted=_source(_THREAD_PRESTARTED))
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=2)
    assert "leak guard" not in result.stdout.str()


# --------------------------------------------------------------------------- 7. modal guard


def test_modal_direct_call_fails_the_test_once(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_direct=_source(
            """
            from PySide6.QtWidgets import QMessageBox


            def test_calls_information():
                QMessageBox.information(None, "t", "m")
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(failed=1)  # failed, and NO extra teardown error for the same attempt
    out = result.stdout.str()
    assert "UnexpectedModalDialog" in out
    assert "QMessageBox.information" in out
    assert "test_modal_direct.py::test_calls_information" in out


def test_modal_call_swallowed_by_a_qt_slot_is_reported_at_teardown(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_swallowed=_source(
            """
            from PySide6.QtCore import QEventLoop, QTimer
            from PySide6.QtWidgets import QMessageBox


            def test_slot_raises_inside_qt():
                # Inside a running event loop PySide6 prints and swallows a slot's exception (a bare
                # processEvents() re-raises it into the caller on PySide6 6.10, so it cannot model the swallow).
                loop = QEventLoop()
                QTimer.singleShot(0, lambda: QMessageBox.warning(None, "t", "m"))
                QTimer.singleShot(100, loop.quit)
                loop.exec()
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=1, errors=1)  # PySide6 swallows the raise; the recorded attempt errors the test
    out = result.stdout.str()
    assert "leak guard [modal]" in out
    assert "QMessageBox.warning" in out
    assert "test_modal_swallowed.py::test_slot_raises_inside_qt" in out


def test_modal_call_the_test_patched_itself_passes(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_patched=_source(
            """
            from PySide6.QtWidgets import QMessageBox


            def test_patches_information(monkeypatch):
                calls = []
                monkeypatch.setattr(
                    QMessageBox,
                    "information",
                    staticmethod(lambda *a, **k: calls.append(a) or QMessageBox.StandardButton.Ok),
                )
                QMessageBox.information(None, "t", "m")
                assert len(calls) == 1
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=1)
    assert "leak guard" not in result.stdout.str()


def test_modal_real_modal_marker_lets_a_genuine_exec_run(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_real=_source(
            """
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QDialog


            @pytest.mark.real_modal
            def test_runs_a_real_exec():
                dialog = QDialog(None)
                accepted = []
                dialog.accepted.connect(lambda: accepted.append(True))
                QTimer.singleShot(50, dialog.accept)
                dialog.exec()
                assert accepted == [True]
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)  # --strict-markers: the plugin must register real_modal itself
    result.assert_outcomes(passed=1)
    assert "leak guard" not in result.stdout.str()


def test_modal_exec_without_the_marker_fails(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_exec=_source(
            """
            from PySide6.QtWidgets import QDialog, QMessageBox


            class MyDialog(QDialog):
                pass


            def test_dialog_subclass_exec():
                MyDialog(None).exec()  # the guard raises synchronously; the watchdog only covers a broken guard


            def test_message_box_instance_exec():
                QMessageBox(None).exec()
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(failed=2)
    out = result.stdout.str()
    assert "UnexpectedModalDialog" in out
    assert "QDialog.exec" in out
    assert "QMessageBox.exec" in out


def test_modal_swallowed_attempt_is_not_hidden_by_an_unrelated_failure(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_swallowed_failing=_source(
            """
            from PySide6.QtCore import QEventLoop, QTimer
            from PySide6.QtWidgets import QMessageBox


            def test_slot_raises_then_an_assertion_fails():
                loop = QEventLoop()
                QTimer.singleShot(0, lambda: QMessageBox.warning(None, "t", "m"))
                QTimer.singleShot(100, loop.quit)
                loop.exec()
                assert False, "unrelated failure"
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)
    # The call fails on the assertion (the raise itself was swallowed in the slot), and the swallowed modal
    # attempt must still be reported: fixing the assertion alone would otherwise flip the test to a teardown ERROR.
    result.assert_outcomes(failed=1, errors=1)
    assert "modal dialog call(s) attempted and swallowed inside Qt" in result.stdout.str()


def test_modal_attempt_in_a_later_fixture_is_one_error_not_two(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_fixture=_source(
            """
            from PySide6.QtWidgets import QMessageBox


            @pytest.fixture
            def asks():
                QMessageBox.information(None, "t", "m")  # raises in setup, after the guard armed


            def test_uses_the_fixture(asks):
                pass
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(errors=1)  # the setup ERROR; the teardown must not report the same attempt again


def test_modal_attempt_in_an_xfail_test_is_not_double_counted(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_xfail=_source(
            """
            from PySide6.QtWidgets import QMessageBox


            @pytest.mark.xfail(reason="expected to hit the dialog")
            def test_xfail_calls_information():
                QMessageBox.information(None, "t", "m")
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(xfailed=1)


def test_modal_leaker_orphaned_zero_delay_timer_fires_inside_the_leaker(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_orphan=_source(
            """
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QMessageBox

            _FIRED = []


            def test_leaker_arms_a_timer_then_asks():
                QTimer.singleShot(0, lambda: _FIRED.append("fired"))
                QMessageBox.information(None, "t", "m")  # raises; the timer stays queued


            def test_next_sees_the_orphan_already_gone():
                # No event pumping here: the orphan must have run in the leaker's own teardown, not in this test.
                assert _FIRED == ["fired"]
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(failed=1, passed=1)  # only the leaker is red
    out = result.stdout.str()
    assert "FAILED test_modal_orphan.py::test_leaker_arms_a_timer_then_asks" in out
    assert "FAILED test_modal_orphan.py::test_next_sees_the_orphan_already_gone" not in out


def test_modal_guard_restores_the_real_methods_after_a_guarded_test(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_restore=_source(
            """
            from PySide6 import QtWidgets
            from scripts import pytest_leak_guards as guards

            _REAL = {(c, n): vars(getattr(QtWidgets, c)).get(n) for c, n in guards.GUARDED_MODAL_CALLS}


            def test_guarded_test_sees_every_call_replaced():
                for (cls_name, name), real in _REAL.items():
                    assert vars(getattr(QtWidgets, cls_name)).get(name) is not real, (cls_name, name)


            @pytest.mark.real_modal
            def test_marked_test_after_it_sees_the_real_methods():
                for (cls_name, name), real in _REAL.items():
                    assert vars(getattr(QtWidgets, cls_name)).get(name) is real, (cls_name, name)
            """
        )
    )
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=2)


def test_modal_guard_loses_to_a_unittest_mock_patch_inside_the_test(pytester, monkeypatch) -> None:
    pytester.makepyfile(
        test_modal_mock_patch=_source(
            """
            from unittest import mock

            from PySide6.QtWidgets import QMessageBox


            def test_patch_object_wins_during_the_with_block():
                with mock.patch.object(QMessageBox, "information", staticmethod(lambda *a, **k: "patched")):
                    assert QMessageBox.information(None, "t", "m") == "patched"
                assert QMessageBox.information.__name__ == "blocked"  # the guard's patch is back, not the real call
            """,
            modal_watchdog=True,
        )
    )
    result = _run_inner(pytester, monkeypatch)
    result.assert_outcomes(passed=1)
    assert "leak guard" not in result.stdout.str()


# --------------------------------------------------------------------------- 8. record mode end to end


def test_record_mode_records_a_direct_modal_call(pytester, monkeypatch, tmp_path) -> None:
    report = tmp_path / "report" / "modal.jsonl"
    pytester.makepyfile(
        test_modal_rec=_source(
            """
            from PySide6.QtWidgets import QMessageBox


            def test_calls_information():
                QMessageBox.information(None, "t", "m")
            """,
            modal_watchdog=True,
        )
    )
    _inner_env(monkeypatch)
    monkeypatch.setenv("PDF_EDITOR_LEAK_GUARD_REPORT", str(report))
    result = pytester.runpytest_subprocess(
        "-p", PLUGIN, "-p", "no:cacheprovider", "--strict-markers", timeout=SUBPROCESS_TIMEOUT_S
    )
    # Record mode never ADDS a failure; the direct call still raises (calling through would block), so the test
    # fails once and the attempt is nevertheless written down.
    result.assert_outcomes(failed=1)
    lines = report.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, lines
    entry = json.loads(lines[0])
    assert entry["guard"] == "modal"
    assert entry["module"] == "test_modal_rec.py"
    assert entry["nodeid"].endswith("test_modal_rec.py::test_calls_information")
    assert "QMessageBox.information" in entry["detail"]


def test_record_mode_reports_the_gui_leaker_without_failing(pytester, monkeypatch, tmp_path) -> None:
    report = tmp_path / "report" / "leaks.jsonl"
    pytester.makepyfile(test_gui_leak=_source(_GUI_LEAKER))
    _inner_env(monkeypatch)
    monkeypatch.setenv("PDF_EDITOR_LEAK_GUARD_REPORT", str(report))
    result = pytester.runpytest_subprocess(
        "-p", PLUGIN, "-p", "no:cacheprovider", "--strict-markers", timeout=SUBPROCESS_TIMEOUT_S
    )
    result.assert_outcomes(passed=2)  # record mode never fails a test
    lines = report.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, lines
    entry = json.loads(lines[0])
    assert set(entry) == {"guard", "nodeid", "module", "detail", "pid"}
    assert entry["guard"] == "gui"
    assert entry["module"] == "test_gui_leak.py"
    assert entry["nodeid"].endswith("test_gui_leak.py::test_leaks_view")
    assert "PDFView" in entry["detail"]
    assert isinstance(entry["pid"], int) and entry["pid"] != os.getpid()  # written by the inner process


# --------------------------------------------------------------------------- 9. gate tests (plain)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _has_real_modal(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for deco in func.decorator_list:
        node = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(node, ast.Attribute) and node.attr == "real_modal":
            if isinstance(node.value, ast.Attribute) and node.value.attr == "mark":
                return True
    return False


def _test_functions_calling(tree: ast.Module, predicate) -> list[ast.FunctionDef]:
    found: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            if any(isinstance(sub, ast.Call) and predicate(sub) for sub in ast.walk(node)):
                found.append(node)
    return found


def test_allowlists_name_existing_test_modules_only() -> None:
    guards = _guards()
    listed = guards._KNOWN_GUI_LEAKERS | guards._KNOWN_THREAD_LEAKERS
    for name in sorted(listed):
        assert re.fullmatch(r"test_[A-Za-z0-9_]+\.py", name), f"{name!r} is not a test module file name"
        assert (TEST_DIR / name).is_file(), f"allowlisted {name!r} does not exist under test_scripts/"


def test_pyproject_registers_the_real_modal_marker() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^markers\s*=\s*\[(.*?)^\]", text, re.DOTALL | re.MULTILINE)
    assert block is not None, "pyproject.toml has no markers list"
    assert re.search(r'^\s*"real_modal:', block.group(1), re.MULTILINE), "real_modal is not a registered marker"


def test_test_scripts_conftest_loads_the_leak_guard_plugin() -> None:
    tree = _parse(TEST_DIR / "conftest.py")
    plugins: tuple[str, ...] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytest_plugins" for t in node.targets):
            plugins = tuple(ast.literal_eval(node.value))
    assert plugins is not None, "test_scripts/conftest.py defines no pytest_plugins"
    assert "scripts.pytest_leak_guards" in plugins
    assert "scripts.pytest_heartbeat" in plugins  # Phase 1 plugin stays


def test_the_four_real_exec_tests_carry_the_real_modal_marker() -> None:
    forwarded = _parse(TEST_DIR / "test_m3_forwarded_cli_focus.py")
    via_run_modal = _test_functions_calling(
        forwarded, lambda call: isinstance(call.func, ast.Name) and call.func.id == "_run_modal"
    )
    assert len(via_run_modal) == 2, [f.name for f in via_run_modal]

    optimize = _parse(TEST_DIR / "test_pdf_optimize_workflow.py")
    builds_dialog = _test_functions_calling(
        optimize, lambda call: isinstance(call.func, ast.Name) and call.func.id == "QDialog"
    )
    with_exec = [
        f
        for f in builds_dialog
        if any(
            isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "exec"
            for sub in ast.walk(f)
        )
    ]
    assert len(with_exec) == 1, [f.name for f in with_exec]

    # The fourth site reaches QMessageBox.exec through view.ask_merge_encryption_choice, so no heuristic on the
    # test body finds it: it is pinned by name.
    merge = _parse(TEST_DIR / "test_pdf_merge_workflow.py")
    named = [
        node
        for node in ast.walk(merge)
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_view_merge_encryption_question_maps_the_three_buttons"
    ]
    assert len(named) == 1, [f.name for f in named]

    unmarked = [f.name for f in via_run_modal + with_exec + named if not _has_real_modal(f)]
    assert not unmarked, f"genuine modal exec() tests without @pytest.mark.real_modal: {unmarked}"


# --------------------------------------------------------------------------- 10. idempotent QThread.start wrap


def test_pytest_configure_wraps_qthread_start_exactly_once(request) -> None:
    from PySide6.QtCore import QThread

    guards = _guards()

    class QuickThread(QThread):
        ran = False

        def run(self) -> None:
            type(self).ran = True

    guards.pytest_configure(request.config)
    first = QThread.start
    guards.pytest_configure(request.config)
    second = QThread.start
    assert second is first, "a second pytest_configure must not wrap QThread.start again"

    thread = QuickThread()
    thread.start()
    try:
        assert thread.wait(5000)
    finally:
        thread.wait(5000)
    assert QuickThread.ran, "the wrapper must still call the original start()"
    registered = [t for t in guards._alive_started() if t is thread]
    assert len(registered) == 1, "a started thread is registered exactly once (no double wrap)"


def test_original_start_is_the_unwrapped_qthread_start() -> None:
    from PySide6.QtCore import QThread

    guards = _guards()

    class QuickThread(QThread):
        def run(self) -> None:
            pass

    original = guards._original_start
    assert original is not None
    assert QThread.start is not original, "QThread.start must be the wrapper, the original stays reachable"

    thread = QuickThread()
    original(thread)  # the unwrapped call must start the thread without registering it
    try:
        assert thread.wait(5000)
    finally:
        thread.wait(5000)
    assert [t for t in guards._alive_started() if t is thread] == []
