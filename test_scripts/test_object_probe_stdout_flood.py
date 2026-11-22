"""H23 finding 10: malformed child stdout under the byte cap costs the GUI thread a bounded amount.

500,000 lines of ``x`` are about 1 MB, under every cap.  Parsing one JSON document and logging one
warning per line stalls the GUI thread; the runner must stop at a bounded number of rejected lines,
log a bounded number of records, and end in exactly one terminal outcome.
"""
from __future__ import annotations

import json
import logging
import time

import pytest
from PySide6.QtCore import QProcess

from test_scripts.test_object_probe_runner import OK_MEMORY, FakeProcess

LINES = 500_000


@pytest.fixture(autouse=True)
def _runner_env(monkeypatch):
    FakeProcess.instances = []
    monkeypatch.setattr("controller.object_probe_runner.read_system_memory", lambda: OK_MEMORY)
    monkeypatch.setattr("utils.object_probe_platform.contained_probe_supported", lambda: True)
    yield
    FakeProcess.instances = []


def _feed(qapp, kind: str, raw: bytes) -> tuple[list[str], float]:
    from controller.object_probe_runner import ObjectProbeRunner

    runner = ObjectProbeRunner(qapp, process_factory=FakeProcess)
    outcomes: list[str] = []
    runner.finished.connect(lambda _j, answer: outcomes.append(f"finished:{answer.get('status')}"))
    runner.failed.connect(lambda _j: outcomes.append("failed"))
    runner.submit(object(), kind, (b"pdf",))
    runner.submit(object(), kind, (b"pdf",))  # the queued second job must start
    proc = FakeProcess.instances[0]
    proc.started.emit()
    proc.out = raw
    t0 = time.perf_counter()
    proc.readyReadStandardOutput.emit()
    proc.finished.emit(0, QProcess.ExitStatus.NormalExit)
    elapsed = time.perf_counter() - t0
    assert len(FakeProcess.instances) == 2, "the queued job did not start"
    return outcomes, elapsed


@pytest.mark.parametrize("kind", ["tables", "text", "scan"])
def test_a_flood_of_invalid_lines_is_one_failure_with_few_log_records(qapp, caplog, kind):
    caplog.set_level(logging.DEBUG)
    outcomes, elapsed = _feed(qapp, kind, b"x\n" * LINES)
    assert outcomes == ["failed"]
    records = [r for r in caplog.records if r.name.startswith("controller.object_probe_runner")]
    assert len(records) <= 5, f"{len(records)} log records for one bad answer"
    assert elapsed < 2.0


def test_a_flood_of_non_object_json_lines_is_bounded_too(qapp, caplog):
    caplog.set_level(logging.DEBUG)
    outcomes, elapsed = _feed(qapp, "tables", b"[]\n" * LINES)
    assert outcomes == ["failed"]
    assert elapsed < 2.0


def test_a_few_advisory_lines_before_and_after_a_real_answer_still_work(qapp):
    answer = json.dumps({"v": 2, "status": "complete", "rects": []}).encode()
    raw = b"advisory 1\nadvisory 2\n" + answer + b"\ntrailing noise\n"
    outcomes, _elapsed = _feed(qapp, "tables", raw)
    assert outcomes == ["finished:complete"]
