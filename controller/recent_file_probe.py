from __future__ import annotations

import json
import logging
from pathlib import Path
import sys

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

    def __init__(self, parent=None):
        super().__init__(parent)
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
    def for_app(cls, app):
        probe = getattr(app, '_pdf_recent_probe', None)
        if probe is None or probe._closing:
            probe = cls(app)
            app._pdf_recent_probe = probe
        return probe

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
        process = QProcess(self)
        self._process = process
        process.setProgram(getattr(sys, '_base_executable', sys.executable))
        # The helper is standard-library-only. Launch the actual interpreter,
        # not the Windows venv redirector whose grandchild cannot be reaped.
        process.setArguments(['-I', '-S', '-u', str(
            Path(__file__).resolve().parents[1] / 'utils' / 'recent_file_worker.py')])
        process.started.connect(self._started)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._error)
        try:
            prepare_owned_qprocess_start()
        except (OSError, RuntimeError):
            logger.warning('Metadata helper not started: native reader inheritance guard failed', exc_info=True)
            self._process = None
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
