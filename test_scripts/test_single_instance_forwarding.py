from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import fitz  # noqa: E402
import pytest  # noqa: E402
from PySide6.QtNetwork import QLocalServer  # noqa: E402

import main as main_module  # noqa: E402
from utils import single_instance as single_instance_module  # noqa: E402


def _pump_until(qapp, predicate, timeout_ms: int = 1000) -> bool:
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    qapp.processEvents()
    return predicate()


def _make_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((36, 72), text)
    doc.save(path)
    doc.close()


def _cleanup_server(server: QLocalServer | None, server_name: str) -> None:
    if server is not None:
        lock = getattr(server, "_single_instance_lock", None)
        server.close()
        server.deleteLater()
        if lock is not None:
            lock.unlock()
    QLocalServer.removeServer(server_name)


def _cleanup_startup(startup: dict) -> None:
    server = startup.get("single_instance_server")
    if server is not None:
        lock = getattr(server, "_single_instance_lock", None)
        server.close()
        server.deleteLater()
        if lock is not None:
            lock.unlock()
    startup["view"].close()
    model = startup.get("model")
    if model is not None:
        model.close()
    startup["app"].quit()


def test_single_instance_server_receives_forwarded_argv(qapp) -> None:
    received: list[list[str]] = []
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    server = single_instance_module.try_become_server(received.append, server_name=server_name)
    try:
        assert server is not None
        assert single_instance_module.send_to_running_instance(["x.pdf"], server_name=server_name)
        expected = [[str(Path("x.pdf").resolve())]]
        assert _pump_until(qapp, lambda: received == expected)
    finally:
        _cleanup_server(server, server_name)


def test_try_become_server_returns_none_when_server_alive() -> None:
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    server = single_instance_module.try_become_server(lambda _argv: None, server_name=server_name)
    second = None
    try:
        assert server is not None
        second = single_instance_module.try_become_server(lambda _argv: None, server_name=server_name)
        assert second is None
    finally:
        _cleanup_server(second, server_name)
        _cleanup_server(server, server_name)


def test_try_become_server_cleans_stale_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    removed: list[str] = []
    listen_attempts = {"count": 0}
    acquire_attempts = {"count": 0}

    class _FakeLock:
        def removeStaleLockFile(self) -> None:
            removed.append(f"{server_name}:lock")

        def unlock(self) -> None:
            return None

    def fake_probe(_name: str, timeout_ms: int = 500) -> bool:
        return False

    def fake_remove(name: str) -> None:
        removed.append(name)

    def fake_listen(name: str):
        listen_attempts["count"] += 1
        if listen_attempts["count"] == 1:
            return None
        server = QLocalServer()
        assert server.listen(name)
        return server

    def fake_make_lock(_name: str):
        return _FakeLock()

    def fake_try_acquire_lock(_lock) -> bool:
        acquire_attempts["count"] += 1
        return acquire_attempts["count"] > 1

    monkeypatch.setattr(single_instance_module, "_probe_live_server", fake_probe)
    monkeypatch.setattr(single_instance_module, "_remove_server", fake_remove)
    monkeypatch.setattr(single_instance_module, "_listen_server", fake_listen)
    monkeypatch.setattr(single_instance_module, "_make_lock", fake_make_lock)
    monkeypatch.setattr(single_instance_module, "_try_acquire_lock", fake_try_acquire_lock)

    server = single_instance_module.try_become_server(lambda _argv: None, server_name=server_name)
    try:
        assert server is not None
        assert removed == [f"{server_name}:lock", server_name]
        assert listen_attempts["count"] == 2
    finally:
        _cleanup_server(server, server_name)


def test_controller_handle_forwarded_cli_opens_forwarded_files(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
    tmp_path: Path,
) -> None:
    opened: list[str] = []
    initial = tmp_path / "initial.pdf"
    first = tmp_path / "forward-a.pdf"
    second = tmp_path / "forward-b.pdf"
    _make_pdf(initial, "initial")
    _make_pdf(first, "first")
    _make_pdf(second, "second")

    from controller.pdf_controller import PDFController

    def fake_open_pdf(self, path: str) -> None:
        opened.append(path)

    monkeypatch.setattr(PDFController, "open_pdf", fake_open_pdf)

    startup = main_module.run(argv=[str(initial)], start_event_loop=False)
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    server = None
    try:
        controller = startup["controller"]
        assert controller is not None
        server = single_instance_module.try_become_server(controller.handle_forwarded_cli, server_name=server_name)
        assert server is not None
        assert single_instance_module.send_to_running_instance([str(first), str(second)], server_name=server_name)
        expected = [str(first.resolve()), str(second.resolve())]
        assert _pump_until(qapp, lambda: opened[-2:] == expected)
    finally:
        _cleanup_server(server, server_name)
        _cleanup_startup(startup)


def test_primary_close_promotes_secondary_for_forwarding(
    monkeypatch: pytest.MonkeyPatch,
    qapp,
    tmp_path: Path,
) -> None:
    """After the primary window closes, forwarded paths must reach a
    promoted secondary window instead of the dead primary."""
    initial = tmp_path / "primary.pdf"
    forward = tmp_path / "forward.pdf"
    _make_pdf(initial, "primary")
    _make_pdf(forward, "forward")

    from controller.pdf_controller import PDFController

    opened_by: list[tuple[int, str]] = []

    def tracking_open(self, path: str) -> None:
        opened_by.append((id(self), path))

    monkeypatch.setattr(PDFController, "open_pdf", tracking_open)

    startup = main_module.run(argv=[str(initial)], start_event_loop=False)
    primary_controller = startup["controller"]
    primary_view = startup["view"]
    assert primary_controller is not None

    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView

    sec_view = PDFView()
    sec_view.apply_initial_theme()
    sec_model = PDFModel()
    sec_controller = PDFController(sec_model, sec_view)
    sec_view.controller = sec_controller
    sec_controller.activate()
    sec_context = {
        "model": sec_model,
        "view": sec_view,
        "controller": sec_controller,
    }
    startup["secondary_windows"].append(sec_context)
    sec_view.show()
    qapp.processEvents()

    primary_view.close()
    qapp.processEvents()

    assert startup["controller"] is sec_controller
    assert startup["view"] is sec_view
    assert startup["model"] is sec_model
    assert sec_context not in startup["secondary_windows"]

    sec_view.close()
    sec_model.close()
    startup.get("model") and startup["model"].close()
    qapp.processEvents()


def test_allow_running_instance_foreground_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    class _User32:
        def AllowSetForegroundWindow(self, process_id: int) -> int:
            calls.append(process_id)
            return 1

    fake_ctypes = type("FakeCtypes", (), {"windll": type("Windll", (), {"user32": _User32()})()})()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", fake_ctypes)

    single_instance_module._allow_running_instance_foreground()

    assert calls == [-1]


# --- F11-2: a primary whose GUI thread is busy must not lose the hand-off ---

_BUSY_SERVER_SCRIPT = """
import json, sys, time
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QCoreApplication
from utils.single_instance import try_become_server

app = QCoreApplication([])
got = []
srv = try_become_server(got.append, server_name=sys.argv[2])
print("ready" if srv is not None else "failed", flush=True)
# Like a synchronous model.save_as / open_pdf on the GUI thread: no event pumping.
time.sleep(float(sys.argv[3]))
end = time.monotonic() + float(sys.argv[4])
while time.monotonic() < end and not got:
    app.processEvents()
    time.sleep(0.01)
print(json.dumps(got), flush=True)
lock = getattr(srv, "_single_instance_lock", None)
srv.close()
if lock is not None:
    lock.unlock()
"""


def _start_busy_primary(tmp_path: Path, server_name: str, busy_s: float, pump_s: float = 8.0):
    import subprocess

    script = tmp_path / "busy_primary.py"
    script.write_text(_BUSY_SERVER_SCRIPT, encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(script), str(REPO_ROOT), server_name, str(busy_s), str(pump_s)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "ready"
    return proc


def test_forward_to_busy_primary_is_not_lost(qapp, tmp_path: Path) -> None:
    """A second launch while the running instance's GUI thread is blocked for
    longer than the connect timeout (save joining a worker, startup open loop)
    must still deliver the open request once the primary pumps events again."""
    import json

    target = tmp_path / "busy-target.pdf"
    _make_pdf(target, "busy")
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    busy_s = 3.5  # longer than the sender's 2 s connect timeout
    proc = _start_busy_primary(tmp_path, server_name, busy_s)
    try:
        forwarded = single_instance_module.send_to_running_instance([str(target)], server_name=server_name)
        out, _ = proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert forwarded is True
    assert json.loads(out.strip().splitlines()[-1]) == [[str(target.resolve())]]


def test_forward_to_unresponsive_primary_is_bounded(qapp, tmp_path: Path) -> None:
    """The longer response budget stays a bound: a primary that never answers
    within it makes the sender give up (False) instead of hanging forever."""
    target = tmp_path / "hung-target.pdf"
    _make_pdf(target, "hung")
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    proc = _start_busy_primary(tmp_path, server_name, busy_s=3.0, pump_s=0.1)
    try:
        t0 = time.monotonic()
        forwarded = single_instance_module.send_to_running_instance(
            [str(target)], server_name=server_name, response_timeout_ms=500
        )
        elapsed = time.monotonic() - t0
        proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert forwarded is False
    assert elapsed < 2.5


def test_default_response_budget_outlasts_a_busy_save() -> None:
    """The response budget must exceed the longest GUI-thread block the app
    itself documents (save joining the thumbnail worker, 5 s) with margin."""
    assert single_instance_module.RESPONSE_TIMEOUT_MS >= 30000
    assert single_instance_module.RESPONSE_TIMEOUT_MS > single_instance_module.CONNECT_TIMEOUT_MS


# --- F11-3-B: the launcher forwards the valid tokens and names the rejected ones ---


def _cli_fixture(tmp_path: Path) -> tuple[str, str, str, str]:
    """(good.pdf, second good.PDF, missing moved.pdf, real file without a .pdf suffix)."""
    good = tmp_path / "good.pdf"
    other = tmp_path / "other.PDF"
    missing = tmp_path / "moved.pdf"
    noext = tmp_path / "scan_no_extension"
    _make_pdf(good, "good")
    _make_pdf(other, "other")
    noext.write_bytes(good.read_bytes())
    return str(good), str(other), str(missing), str(noext)


def test_token_predicate_is_the_one_the_receiver_uses(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Drift guard: the receiver's whole-message filter is built from the same
    per-token predicate the launcher uses, so the two can never disagree."""
    good, other, missing, noext = _cli_fixture(tmp_path)
    predicate = single_instance_module.forwarded_token_is_acceptable
    assert predicate(good) is True
    assert predicate(other) is True  # suffix check is case-insensitive
    assert predicate(missing) is False
    assert predicate(noext) is False
    assert predicate(str(tmp_path / "sub" / ".." / "good.pdf")) is True  # resolved like the receiver

    seen: list[str] = []

    def spy(item: str) -> bool:
        seen.append(item)
        return True

    monkeypatch.setattr(single_instance_module, "forwarded_token_is_acceptable", spy)
    assert single_instance_module._forwarded_argv_is_acceptable([good, missing]) is True
    assert seen == [good, missing]


def test_token_predicate_rejects_unresolvable_tokens(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    good, *_ = _cli_fixture(tmp_path)

    def boom(self, *args, **kwargs):
        raise OSError(53, "network path not found")

    monkeypatch.setattr(Path, "resolve", boom)
    assert single_instance_module.forwarded_token_is_acceptable(good) is False
    assert single_instance_module._forwarded_argv_is_acceptable([good]) is False


def test_partition_splits_valid_and_rejected_tokens_in_order(tmp_path: Path) -> None:
    good, other, missing, noext = _cli_fixture(tmp_path)
    valid, rejected = single_instance_module.partition_forwardable_argv([missing, good, noext, other])
    assert valid == [good, other]
    assert rejected == [missing, noext]
    assert single_instance_module.partition_forwardable_argv([]) == ([], [])


def test_receiver_still_rejects_a_mixed_message(qapp, tmp_path: Path) -> None:
    """The receiver's whole-message fail-closed filter is unchanged."""
    good, _other, missing, _noext = _cli_fixture(tmp_path)
    received: list[list[str]] = []
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    server = single_instance_module.try_become_server(received.append, server_name=server_name)
    try:
        assert server is not None
        # Bypass the in-process shortcut so the real socket + receiver filter run.
        active = single_instance_module._ACTIVE_SERVERS.pop(server_name)
        try:
            assert single_instance_module.send_to_running_instance([good, missing], server_name=server_name) is False
        finally:
            single_instance_module._ACTIVE_SERVERS[server_name] = active
        qapp.processEvents()
        assert received == []
    finally:
        _cleanup_server(server, server_name)


class _LauncherHarness:
    """Drives main.run() down the 'a primary instance already runs' branch."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, forward_result: bool = True) -> None:
        self.forwarded: list[list[str]] = []
        self.dialogs: list[list[str]] = []

        def fake_send(argv, **_kwargs):
            self.forwarded.append(list(argv))
            return forward_result

        monkeypatch.setattr(single_instance_module, "try_become_server", lambda *_a, **_k: None)
        monkeypatch.setattr(single_instance_module, "send_to_running_instance", fake_send)
        monkeypatch.setattr(
            main_module, "_show_rejected_cli_files_dialog", lambda rejected: self.dialogs.append(list(rejected))
        )


def test_launcher_forwards_valid_tokens_and_names_the_rejected_ones(
    monkeypatch: pytest.MonkeyPatch, qapp, tmp_path: Path
) -> None:
    good, other, missing, noext = _cli_fixture(tmp_path)
    harness = _LauncherHarness(monkeypatch)
    assert main_module.run(argv=[good, missing, other, noext]) == 0
    assert harness.forwarded == [[good, other]]  # one message, valid tokens only
    assert harness.dialogs == [[missing, noext]]


def test_launcher_with_no_valid_token_shows_the_dialog_and_does_not_forward(
    monkeypatch: pytest.MonkeyPatch, qapp, tmp_path: Path
) -> None:
    _good, _other, missing, noext = _cli_fixture(tmp_path)
    harness = _LauncherHarness(monkeypatch)
    assert main_module.run(argv=[missing, noext]) == 1
    assert harness.forwarded == []
    assert harness.dialogs == [[missing, noext]]


def test_launcher_with_only_valid_tokens_shows_no_dialog(
    monkeypatch: pytest.MonkeyPatch, qapp, tmp_path: Path
) -> None:
    good, other, _missing, _noext = _cli_fixture(tmp_path)
    harness = _LauncherHarness(monkeypatch)
    assert main_module.run(argv=[good, other]) == 0
    assert harness.forwarded == [[good, other]]
    assert harness.dialogs == []


def test_launcher_without_arguments_still_forwards_the_empty_message(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    """A bare second launch just raises the running window (unchanged)."""
    harness = _LauncherHarness(monkeypatch)
    assert main_module.run(argv=[]) == 0
    assert harness.forwarded == [[]]
    assert harness.dialogs == []


def test_launcher_names_the_rejected_tokens_even_when_the_hand_off_fails(
    monkeypatch: pytest.MonkeyPatch, qapp, tmp_path: Path
) -> None:
    good, _other, missing, _noext = _cli_fixture(tmp_path)
    harness = _LauncherHarness(monkeypatch, forward_result=False)
    assert main_module.run(argv=[good, missing]) == 1
    assert harness.forwarded == [[good]]
    assert harness.dialogs == [[missing]]


def test_launcher_end_to_end_opens_the_valid_file_in_the_running_instance(
    monkeypatch: pytest.MonkeyPatch, qapp, tmp_path: Path
) -> None:
    good, _other, missing, _noext = _cli_fixture(tmp_path)
    server_name = f"pdf_editor_test_{uuid.uuid4().hex}"
    monkeypatch.setattr(single_instance_module, "_build_server_name", lambda: server_name)
    monkeypatch.setattr(single_instance_module, "_build_legacy_server_name", lambda: server_name + "_legacy")
    received: list[list[str]] = []
    dialogs: list[list[str]] = []
    monkeypatch.setattr(main_module, "_show_rejected_cli_files_dialog", lambda rejected: dialogs.append(list(rejected)))
    server = single_instance_module.try_become_server(received.append, server_name=server_name)
    try:
        assert server is not None
        assert main_module.run(argv=[good, missing]) == 0
        assert _pump_until(qapp, lambda: received == [[str(Path(good).resolve())]])
        assert dialogs == [[missing]]
    finally:
        _cleanup_server(server, server_name)


def test_rejected_cli_files_message_is_traditional_chinese_and_names_every_file() -> None:
    names = ["moved.pdf", "scan_no_extension"]
    text = main_module._rejected_cli_files_message(names)
    for name in names:
        assert name in text
    assert any("一" <= ch <= "鿿" for ch in text)


def test_rejected_cli_files_message_caps_a_long_list() -> None:
    names = [f"missing-{index}.pdf" for index in range(40)]
    text = main_module._rejected_cli_files_message(names)
    assert "missing-0.pdf" in text
    assert "missing-39.pdf" not in text  # capped
    assert text.count("\n") < 30


def test_show_rejected_cli_files_dialog_uses_a_warning_box(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    from PySide6.QtWidgets import QMessageBox

    calls: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **_k: calls.append(args))
    main_module._show_rejected_cli_files_dialog(["moved.pdf"])
    assert len(calls) == 1
    assert "moved.pdf" in calls[0][2]
