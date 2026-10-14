from __future__ import annotations

import getpass
import json
import logging
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from utils.app_identity import IPC_LEGACY_SERVER_PREFIX, IPC_SERVER_PREFIX

logger = logging.getLogger(__name__)

_ACTIVE_SERVERS: dict[str, QLocalServer] = {}

# Liveness check: connecting to a pipe/socket whose owner is alive is instant,
# even when that owner's GUI thread is blocked, so this stays short.
CONNECT_TIMEOUT_MS = 2000
# Responsiveness budget for the hand-off itself (payload write completion plus
# the ack). The running instance only services the socket from its event loop,
# which a synchronous save (joins the thumbnail worker for up to 5 s, then
# writes the file) or the startup open loop blocks. Giving up after the short
# connect timeout aborts the socket, and an aborted hand-off is never delivered:
# the requested open is lost with no dialog (F11-2). On Windows the write itself
# does not complete until the primary reads, so this budget must cover the
# write wait as well as the ack wait.
RESPONSE_TIMEOUT_MS = 60000


def _allow_running_instance_foreground() -> None:
    """Grant the receiving Windows process foreground rights for this hand-off."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)
    except (AttributeError, OSError) as exc:  # pragma: no cover - platform API failure
        logger.debug("Unable to grant foreground permission to running instance: %s", exc)


def _safe_username() -> str:
    user = getpass.getuser().strip() or "default"
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in user)


def _build_server_name() -> str:
    return f"{IPC_SERVER_PREFIX}{_safe_username()}"


def _build_legacy_server_name() -> str:
    return f"{IPC_LEGACY_SERVER_PREFIX}{_safe_username()}"


def _remove_server(name: str) -> None:
    QLocalServer.removeServer(name)


def _listen_server(name: str) -> QLocalServer | None:
    server = QLocalServer()
    # Restrict the named pipe / unix socket to the current user so peers in
    # other sessions cannot connect and forward open requests (CWE-306/CWE-668).
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if server.listen(name):
        return server
    server.deleteLater()
    return None


def _probe_live_server(name: str, timeout_ms: int = 500) -> bool:
    socket = QLocalSocket()
    try:
        socket.connectToServer(name)
        return socket.waitForConnected(timeout_ms)
    finally:
        socket.abort()
        socket.deleteLater()


def _make_lock(name: str) -> QLockFile:
    lock = QLockFile(str(Path(tempfile.gettempdir()) / f"{name}.lock"))
    lock.setStaleLockTime(5000)
    return lock


def _try_acquire_lock(lock: QLockFile) -> bool:
    return lock.tryLock(0)


def _process_events() -> None:
    app = QCoreApplication.instance()
    if app is not None:
        app.processEvents()


def _wait_for_ready_read(socket: QLocalSocket, timeout_ms: int) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        if socket.bytesAvailable() > 0:
            return True
        _process_events()
        if socket.waitForReadyRead(25):
            return True
    return socket.bytesAvailable() > 0


def _service_local_server(name: str) -> None:
    server = _ACTIVE_SERVERS.get(name)
    if server is None:
        return
    server.waitForNewConnection(0)
    accept_pending = getattr(server, "_single_instance_accept_pending", None)
    if callable(accept_pending):
        accept_pending()
    on_message = getattr(server, "_single_instance_on_message", None)
    sockets = list(getattr(server, "_single_instance_sockets", []))
    if callable(on_message):
        for socket in sockets:
            socket.waitForReadyRead(100)
            if socket.bytesAvailable() > 0:
                _handle_socket_message(socket, on_message)
    _process_events()


def _normalize_forwarded_argv(argv: list[str]) -> list[str] | None:
    """Canonicalize every token, or reject the whole hand-off (fail closed).

    Returns ``None`` if any token cannot be resolved (e.g. an unreachable UNC
    path raising WinError 53 under Py3.10). Per the IPC argv contract an
    unresolvable token is NEVER silently skipped or passed through — that would
    let a stale/crafted path slip past the receiver's filter — so the entire
    forwarded argv is rejected."""
    normalized: list[str] = []
    for item in argv:
        try:
            normalized.append(str(Path(item).resolve()))
        except OSError:
            return None
    return normalized


def forwarded_token_is_acceptable(item: str) -> bool:
    """The per-token acceptance rule: ``item`` resolves to an existing ``.pdf``.

    This is the ONE predicate both sides of the hand-off use. The receiver
    (``_forwarded_argv_is_acceptable``) applies it to every token of a message
    and rejects the whole message if any token fails (fail closed); the
    launcher (``partition_forwardable_argv``) applies it to each command-line
    token before sending so the valid ones still open (F11-3). A token that
    cannot be resolved (e.g. an unreachable UNC path, WinError 53 under
    Py3.10, an embedded NUL) is REJECTED, never skipped or passed through."""
    try:
        path = Path(item).resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    return path.exists() and path.suffix.lower() == ".pdf"


def partition_forwardable_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split ``argv`` into ``(valid, rejected)`` tokens, keeping their order.

    Launcher-side helper: ``valid`` is what the running instance's filter will
    accept (same predicate), ``rejected`` is what the user must be told about."""
    valid: list[str] = []
    rejected: list[str] = []
    for item in argv:
        (valid if forwarded_token_is_acceptable(item) else rejected).append(item)
    return valid, rejected


def _forwarded_argv_is_acceptable(argv: list[str]) -> bool:
    """Reject a forwarded message unless EVERY token is acceptable.

    The untrusted socket peer is not bound by the sender-side normalization in
    ``_normalize_forwarded_argv`` or by the launcher's partitioning, so every
    token is resolved and validated here too with ``forwarded_token_is_acceptable``
    -- skipping a token would let a crafted peer smuggle arbitrary paths past
    the filter. One bad token rejects the whole message; no flags are expected
    or skipped."""
    # The caller (_handle_socket_message) guarantees every item is a str.
    return all(forwarded_token_is_acceptable(item) for item in argv)


def _handle_socket_message(
    socket: QLocalSocket,
    on_message: Callable[[list[str]], None],
) -> None:
    raw_buffer = socket.property("payload_buffer")
    if isinstance(raw_buffer, bytes):
        buffer = raw_buffer
    else:
        buffer = b""
    # PySide6's stub for QByteArray omits the buffer-protocol/__bytes__ overload
    # bytes() actually accepts at runtime; tests double `readAll()` with a plain
    # `bytes` return too, so this must stay a `bytes(...)` conversion (not
    # `.data()`, which plain `bytes` objects don't have).
    buffer += bytes(socket.readAll())  # type: ignore[call-overload]
    if b"\n" not in buffer:
        socket.setProperty("payload_buffer", buffer)
        return

    line, remainder = buffer.split(b"\n", 1)
    socket.setProperty("payload_buffer", remainder)
    ok = False
    try:
        payload = json.loads(line.decode("utf-8"))
        argv = payload.get("argv")
        if (
            isinstance(argv, list)
            and all(isinstance(item, str) for item in argv)
            and _forwarded_argv_is_acceptable(argv)
        ):
            on_message(list(argv))
            ok = True
    except Exception:
        ok = False

    socket.write(b"1\n" if ok else b"0\n")
    socket.flush()
    socket.waitForBytesWritten(1000)
    socket.disconnectFromServer()


def try_become_server(
    on_message: Callable[[list[str]], None],
    *,
    server_name: str | None = None,
) -> QLocalServer | None:
    name = server_name or _build_server_name()
    if server_name is None and _probe_live_server(_build_legacy_server_name()):
        return None
    lock = _make_lock(name)
    if not _try_acquire_lock(lock):
        if hasattr(lock, "removeStaleLockFile") and not _probe_live_server(name):
            lock.removeStaleLockFile()
            if not _try_acquire_lock(lock):
                return None
        else:
            return None

    server = _listen_server(name)
    if server is None and not _probe_live_server(name):
        _remove_server(name)
        server = _listen_server(name)
    if server is None:
        lock.unlock()
        return None

    setattr(server, "_single_instance_on_message", on_message)
    setattr(server, "_single_instance_sockets", [])

    def _accept_pending() -> None:
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            if socket is None:
                continue
            socket.setParent(server)
            getattr(server, "_single_instance_sockets").append(socket)
            socket.readyRead.connect(lambda socket=socket: _handle_socket_message(socket, on_message))
            socket.disconnected.connect(
                lambda socket=socket: getattr(server, "_single_instance_sockets").remove(socket)
                if socket in getattr(server, "_single_instance_sockets")
                else None
            )
            socket.disconnected.connect(socket.deleteLater)

    server.newConnection.connect(_accept_pending)
    setattr(server, "_single_instance_accept_pending", _accept_pending)
    _ACTIVE_SERVERS[name] = server
    server.destroyed.connect(lambda *_args, server_name=name: _ACTIVE_SERVERS.pop(server_name, None))
    server.destroyed.connect(lambda *_args: lock.unlock())
    setattr(server, "_single_instance_lock", lock)
    return server


def send_to_running_instance(
    argv: list[str],
    *,
    server_name: str | None = None,
    timeout_ms: int = CONNECT_TIMEOUT_MS,
    response_timeout_ms: int = RESPONSE_TIMEOUT_MS,
) -> bool:
    """Forward ``argv`` to the running instance; ``True`` once it acked.

    ``timeout_ms`` only bounds the liveness check (connect). A live but busy
    primary accepts the connection instantly and answers only when its event
    loop runs again, so the write and ack waits share the much longer
    ``response_timeout_ms`` budget instead of the connect timeout."""
    name = server_name or _build_server_name()
    normalized_argv = _normalize_forwarded_argv(argv)
    if normalized_argv is None:
        # A token could not be canonicalized — reject the hand-off (fail closed)
        # rather than crashing the forwarding instance on an unreachable path.
        return False
    _allow_running_instance_foreground()
    local_server = _ACTIVE_SERVERS.get(name)
    if local_server is not None:
        on_message = getattr(local_server, "_single_instance_on_message", None)
        if callable(on_message):
            on_message(normalized_argv)
            return True

    socket = QLocalSocket()
    try:
        socket.connectToServer(name)
        if not socket.waitForConnected(timeout_ms):
            if server_name is None:
                legacy = _build_legacy_server_name()
                socket.abort()
                socket.connectToServer(legacy)
                if not socket.waitForConnected(timeout_ms):
                    return False
            else:
                return False
        _service_local_server(name)
        payload = json.dumps({"argv": normalized_argv}, ensure_ascii=False).encode("utf-8") + b"\n"
        deadline = time.monotonic() + (response_timeout_ms / 1000.0)
        socket.write(payload)
        socket.flush()
        if not socket.waitForBytesWritten(response_timeout_ms):
            logger.warning("Running instance did not accept the forwarded open within %d ms", response_timeout_ms)
            return False
        _service_local_server(name)
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        if not _wait_for_ready_read(socket, remaining_ms):
            logger.warning("Running instance did not acknowledge the forwarded open within %d ms", response_timeout_ms)
            return False
        ack = bytes(socket.readAll()).strip()  # type: ignore[call-overload]
        return ack.startswith(b"1")
    finally:
        socket.abort()
        socket.deleteLater()
