from __future__ import annotations

import json
import logging

from PySide6.QtCore import QObject, QProcess, QTimer, Signal, Slot
from utils.native_handle_inheritance import prepare_owned_qprocess_start

logger = logging.getLogger(__name__)


class RecentFileProbe(QObject):
    """One App-wide, deadline-bounded metadata child, never a GUI filesystem call.

    A replacement batch waits for the cancelled child to exit. Unknown/timeout
    results stay unknown; they are not evidence that a network file is missing.
    """

    result = Signal(str, bool)
    stopped = Signal()

    def __init__(self, parent=None, *, ledger=None):
        super().__init__(parent)
        # Optional App-wide ledger: the helper is charged from launch until its
        # confirmed exit, so a cancelled child still counts while it dies.
        self._ledger = ledger
        self._lease = None
        self._process = None
        self._paths = ()
        self._pending = None
        self._cancelled = False
        self._closing = False
        self._buffer = bytearray()
        self._cache = {}
        self._answered = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timeout)

    @property
    def idle(self):
        return self._process is None and self._pending is None

    @classmethod
    def for_app(cls, app, *, ledger=None):
        probe = getattr(app, '_pdf_recent_probe', None)
        if probe is None or probe._closing:
            probe = cls(app, ledger=ledger)
            app._pdf_recent_probe = probe
        elif ledger is not None and probe._ledger is None:
            probe._ledger = ledger
        return probe

    def _release_lease(self):
        lease, self._lease = self._lease, None
        if lease is not None:
            self._ledger.retire_process(lease)
            self._ledger.process_exited(lease)

    def request(self, paths):
        if self._closing:
            return
        paths = tuple(paths[:10])
        if paths == self._paths and self._process is not None and not self._cancelled:
            return
        self._pending = paths
        if self._process is not None:
            self._cancelled = True
            self._process.kill()
        else:
            self._launch()

    def _launch(self):
        if self._pending is None or self._closing:
            return
        self._paths, self._pending = self._pending, None
        self._cancelled = False
        self._answered.clear()
        if not self._paths:
            return
        self._buffer.clear()
        if self._ledger is not None:
            from src.render_worker.admission import PROBE_CHARGE

            # Required: a 12 MiB, deadline-bounded helper with no compute slot. Refusing it by
            # bytes would leave the history unverified for the rest of the session (the
            # renderers fill the budget by design, and non-Windows has no OS reading).
            # The overcommit is counted in the ledger stats instead.
            self._lease = self._ledger.try_reserve('recent-probe', 'process', PROBE_CHARGE, required=True)
            if self._lease is None:
                logger.info('Metadata helper deferred: resource ledger refused the charge')
                return
        process = QProcess(self)
        self._process = process
        # The helper is standard-library-only; argv (interpreter script, or the frozen app exe
        # re-run with --recent-probe) comes from the one shared launch helper.
        from src.render_worker.launch import child_launch

        program, args = child_launch('recent-probe')
        process.setProgram(program)
        process.setArguments(args)
        process.started.connect(self._started)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._error)
        try:
            prepare_owned_qprocess_start()
        except (OSError, RuntimeError):
            logger.warning('Metadata helper not started: native reader inheritance guard failed', exc_info=True)
            self._process = None
            self._release_lease()
            process.deleteLater()
            return
        process.start()
        self._timer.start(1500)

    @Slot()
    def _started(self):
        if self._process is not None:
            self._process.write(json.dumps(self._paths).encode('utf-8') + b'\n')
            self._process.closeWriteChannel()

    @Slot()
    def _read(self):
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput())
        if self._cancelled:
            return
        self._buffer.extend(data)
        if len(self._buffer) > 4096:
            self._timeout()
            return
        while b'\n' in self._buffer and not self._cancelled:
            line, _, rest = self._buffer.partition(b'\n')
            self._buffer = bytearray(rest)
            try:
                index, available = json.loads(line)
                if (type(index) is not int or not 0 <= index < len(self._paths)
                        or type(available) is not bool):
                    raise ValueError('invalid probe result')
            except (ValueError, TypeError):
                self._timeout()
                return
            path = self._paths[index]
            self._answered.add(index)
            self._cache[path] = available
            self.result.emit(path, available)

    @Slot()
    def _timeout(self):
        if not self._cancelled and not self._closing and self._pending is None:
            # The helper checks in order. Keep the stalled entry unknown and
            # continue with later entries, after the old child has been reaped.
            remaining = [path for i, path in enumerate(self._paths) if i not in self._answered]
            if len(remaining) > 1:
                self._pending = tuple(remaining[1:])
        self._cancelled = True
        if self._process is not None:
            self._process.kill()

    @Slot()
    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._finished()

    @Slot()
    def _finished(self, *_args):
        self._read()
        self._timer.stop()
        process, self._process = self._process, None
        if process is not None:
            self._release_lease()
            process.deleteLater()
        if self._closing:
            self.stopped.emit()
        elif self._pending is not None:
            self._launch()

    @Slot()
    def shutdown(self):
        self._closing = True
        self._pending = None
        self._timer.stop()
        self._timeout()
        if self._process is None:
            self.stopped.emit()
