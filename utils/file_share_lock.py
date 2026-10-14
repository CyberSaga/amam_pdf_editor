"""Deny-write share lock on the files open sessions own (Windows; no-op elsewhere).

MuPDF opens a PDF with a share mode that lets any other program rewrite it in
place (``copy /y``, Explorer copy-overwrite, ``open('r+b')``): a file-backed
live document then lazily reads the foreign bytes and the unsaved edits vanish
before any save (F10-FS-1, RAM half).  The owner's decision (OD-FS1-LOCK) is a
second handle, held for the whole session, opened with ``FILE_SHARE_READ``
only: other processes may still READ the file, but every open that asks for
write or delete access (in-place rewrite, ``os.replace`` / ``MoveFileEx`` over
it, rename, delete) fails with a sharing violation.  Readers that also allow
writes - MuPDF's own reopen, Python ``open('rb')``, pikepdf - keep working, so
the lock never blocks this process from reading.

The app's own writes to a locked path must release it first:
``suspended(path)`` closes the OS handle for the duration and re-opens it on
whatever file then sits at the path (the freshly installed one).

One OS handle per path for the whole process, shared by every holder
(``acquire`` hands out ``FileShareLock`` tokens, reference counted): two
windows or a detached tab on the same file never fight each other, and a
suspension releases the path for every in-process writer (today's behaviour
between this process's own windows).

Never raises and never refuses an open: when the handle cannot be taken (a
network share that does not support it, another program already holds the
file for writing, the file is gone) the token is *degraded* - it logs once
and protects nothing, exactly the behaviour before the lock existed; the
F10-FS-1 on-disk fingerprint gate stays the defence then.  Off Windows every
call is a no-op.

Qt-free on purpose (``utils/`` may not import QtWidgets).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import weakref
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def platform_supported() -> bool:
    """True where the lock does anything (Windows).  Read at call time (patchable)."""
    return sys.platform == "win32"


def path_key(path: str | os.PathLike[str]) -> str:
    """Process-wide identity of ``path``: absolute, symlinks resolved, case-folded.

    The ``\\\\?\\`` extended-length prefix (staging targets use it) is removed
    so a long-path spelling and the plain one of the same file share a key;
    ``realpath`` keeps it on a path too long for the legacy API, so it is
    stripped again afterwards.
    """
    from utils.path_staging import strip_extended_prefix  # lazy: path_staging imports this module

    text = strip_extended_prefix(path)
    try:
        text = os.path.realpath(text)
    except (OSError, ValueError):
        text = os.path.abspath(text)
    return os.path.normcase(strip_extended_prefix(text))


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _GENERIC_READ = 0x80000000
    _FILE_SHARE_READ = 0x00000001
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    def _os_open(path: str) -> int:
        """Open ``path`` for reading, sharing READ only (deny write + delete).

        ``GENERIC_READ`` matters: a handle without data access does not take
        part in sharing checks and would block nobody.  Not inheritable (no
        security attributes), so child processes never carry the lock.
        """
        from utils.path_staging import extended_length_path

        handle = _CreateFileW(
            extended_length_path(path),
            _GENERIC_READ,
            _FILE_SHARE_READ,
            None,
            _OPEN_EXISTING,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if handle is None or handle == _INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            raise OSError(err, ctypes.FormatError(err).strip(), path)
        return int(handle)

    def _os_close(handle: int) -> None:
        _CloseHandle(wintypes.HANDLE(handle))

else:

    def _os_open(path: str) -> int:
        raise OSError("deny-write share lock is only available on Windows")

    def _os_close(handle: int) -> None:
        return None


class _Entry:
    __slots__ = ("path", "handle", "holders", "suspends")

    def __init__(self, path: str) -> None:
        self.path = path
        self.handle: int | None = None
        self.holders = 0
        self.suspends = 0


_registry: dict[str, _Entry] = {}
_mutex = threading.RLock()
# Claims dropped by the garbage collector while another thread held ``_mutex``.
# A ``weakref.finalize`` callback runs in whichever thread triggered the
# collection - possibly one holding a logging or Qt lock - so it never blocks
# on ``_mutex``; the next registry call applies the drop.
_pending_drops: deque[str] = deque()


def _drain_pending_drops() -> None:
    """Apply GC-time drops (caller holds ``_mutex``; only mutex holders pop)."""
    while _pending_drops:
        _drop_holder_locked(_pending_drops.popleft())


def _try_open(entry: _Entry) -> OSError | None:
    """Take the OS handle for ``entry`` unless it is held already or the platform
    has no lock (caller holds ``_mutex``).

    Returns the refusal instead of logging it: nothing that can take another
    lock (logging handlers) runs while ``_mutex`` is held.
    """
    if entry.handle is not None or not platform_supported():
        return None
    try:
        entry.handle = _os_open(entry.path)
    except OSError as exc:
        return exc
    return None


def _log_refusal(path: str, exc: OSError | None) -> None:
    if exc is None:
        return
    if os.path.exists(path):
        logger.warning("無法以拒絕寫入模式鎖定檔案，維持未鎖定（其他程式可覆寫）: %s (%s)", path, exc)
    else:
        logger.info("檔案不存在，未鎖定: %s", path)


def _close(entry: _Entry) -> None:
    handle = entry.handle
    entry.handle = None
    if handle is not None:
        try:
            _os_close(handle)
        except Exception:  # pragma: no cover - CloseHandle on a valid handle
            pass


def _drop_holder_locked(key: str) -> None:
    entry = _registry.get(key)
    if entry is None:
        return
    entry.holders = max(0, entry.holders - 1)
    if entry.holders == 0:
        _close(entry)
        if entry.suspends == 0:
            _registry.pop(key, None)


def _finalize_holder(key: str, explicit: bool) -> None:
    """Drop one claim on ``key``: an explicit ``release`` waits for the mutex, a
    garbage-collection drop (the ``weakref.finalize`` callback) never does (it is
    queued when the mutex is busy)."""
    if not _mutex.acquire(blocking=explicit):
        _pending_drops.append(key)
        return
    try:
        _drain_pending_drops()
        _drop_holder_locked(key)
    finally:
        _mutex.release()


def _handle_open(key: str) -> bool:
    """True while the OS handle for ``key`` is open (queued GC drops applied first)."""
    with _mutex:
        _drain_pending_drops()
        entry = _registry.get(key)
        return entry is not None and entry.handle is not None


class FileShareLock:
    """One holder's claim on the process-wide deny-write lock of a path.

    ``release`` is idempotent; a token that is garbage collected without it
    releases its claim (safety net - sessions release explicitly).
    """

    def __init__(self, path: str, key: str) -> None:
        self.path = path
        self.key = key
        self._finalizer = weakref.finalize(self, _finalize_holder, key, False)

    @property
    def released(self) -> bool:
        return not self._finalizer.alive

    @property
    def held(self) -> bool:
        """True while the OS handle is open (False: degraded, suspended, released, non-Windows)."""
        return not self.released and _handle_open(self.key)

    def covers(self, path: str | os.PathLike[str]) -> bool:
        return not self.released and path_key(path) == self.key

    def ensure(self) -> bool:
        """Retry a degraded claim (not while suspended); returns ``held``."""
        if self.released:
            return False
        with _mutex:
            _drain_pending_drops()
            entry = _registry.get(self.key)
            if entry is None or entry.suspends > 0:
                return False
            refusal = _try_open(entry)
            held = entry.handle is not None
        _log_refusal(self.path, refusal)
        return held

    def release(self) -> None:
        if self._finalizer.detach() is not None:  # still alive: this call drops the claim
            _finalize_holder(self.key, True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "released" if self.released else ("held" if self.held else "degraded")
        return f"FileShareLock({self.path!r}, {state})"


def acquire(path: str | os.PathLike[str]) -> FileShareLock:
    """Claim the deny-write lock on ``path``; never raises.

    The returned token is ``held`` when other programs can no longer write,
    rename or delete the file, and degraded (logged) when the lock could not
    be taken - the open goes on either way.
    """
    text = os.fspath(path)
    key = path_key(text)
    refusal: OSError | None = None
    with _mutex:
        _drain_pending_drops()
        entry = _registry.get(key)
        if entry is None:
            entry = _registry[key] = _Entry(text)
        entry.holders += 1
        if entry.suspends == 0:
            refusal = _try_open(entry)
        token = FileShareLock(text, key)
    _log_refusal(text, refusal)
    return token


@contextmanager
def suspended(path: str | os.PathLike[str]) -> Iterator[None]:
    """Release the lock on ``path`` for this process's own write; re-take it after.

    Re-entrant (counted).  On exit the handle is re-opened on whatever file is
    at the path then (an ``os.replace`` installed a new one) as long as a
    holder remains; a failed re-open is logged and leaves the claim degraded.
    A path nobody holds costs one dictionary lookup.
    """
    key = path_key(path)
    with _mutex:
        _drain_pending_drops()
        entry = _registry.get(key)
        if entry is not None:
            entry.suspends += 1
            _close(entry)
    try:
        yield
    finally:
        if entry is not None:
            refusal: OSError | None = None
            with _mutex:
                entry.suspends = max(0, entry.suspends - 1)
                if entry.suspends == 0:
                    if entry.holders == 0:
                        _registry.pop(key, None)
                    else:
                        refusal = _try_open(entry)
            _log_refusal(entry.path, refusal)


def is_locked(path: str | os.PathLike[str]) -> bool:
    """True while this process holds the OS deny-write handle on ``path``."""
    return _handle_open(path_key(path))


__all__ = [
    "FileShareLock",
    "acquire",
    "is_locked",
    "path_key",
    "platform_supported",
    "suspended",
]
