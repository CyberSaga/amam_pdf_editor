"""Env-gated startup timeline (``PDF_EDITOR_TIMELINE=<file>``) for measuring the frozen exe.

One JSON line per event: process_start, view_built, shown, open_pdf_begin, first_low_paint,
first_sharp_paint. Unset, the helper does nothing and creates nothing.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import fitz
import pytest

import main as main_module

ENV = "PDF_EDITOR_TIMELINE"


@pytest.fixture
def timeline():
    from utils import timeline as module

    yield module
    module.start({})  # leave the process-wide helper disabled for later tests


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_unset_environment_writes_nothing_and_creates_no_file(timeline, tmp_path) -> None:
    candidate = tmp_path / "timeline.jsonl"
    timeline.start({"SOMETHING_ELSE": str(candidate)})
    for name in ("view_built", "shown", "first_sharp_paint"):
        timeline.mark(name)
    assert timeline.enabled() is False
    assert not candidate.exists()
    assert list(tmp_path.iterdir()) == []


def test_empty_value_counts_as_unset(timeline, tmp_path) -> None:
    timeline.start({ENV: ""})
    timeline.mark("view_built")
    assert timeline.enabled() is False


def test_events_are_json_lines_with_a_monotonic_millisecond_clock(timeline, tmp_path) -> None:
    path = tmp_path / "timeline.jsonl"
    timeline.start({ENV: str(path)})
    assert timeline.enabled() is True
    timeline.mark("view_built")
    time.sleep(0.01)
    timeline.mark("shown")
    events = _events(path)
    assert [event["event"] for event in events] == ["process_start", "view_built", "shown"]
    start = events[0]
    assert start["t_ms"] == 0.0
    assert isinstance(start["wall"], float) and start["wall"] > 1_000_000_000
    assert isinstance(start["pid"], int)
    clock = [event["t_ms"] for event in events]
    assert clock == sorted(clock) and clock[2] - clock[1] >= 5.0


def test_each_event_is_recorded_once_per_start(timeline, tmp_path) -> None:
    path = tmp_path / "timeline.jsonl"
    timeline.start({ENV: str(path)})
    timeline.mark("first_sharp_paint")
    timeline.mark("first_sharp_paint")
    assert [event["event"] for event in _events(path)] == ["process_start", "first_sharp_paint"]
    timeline.start({ENV: str(path)})  # a new run in the same process measures again
    timeline.mark("first_sharp_paint")
    assert [event["event"] for event in _events(path)].count("first_sharp_paint") == 2


def test_unwritable_target_disables_the_timeline_without_raising(timeline, tmp_path) -> None:
    timeline.start({ENV: str(tmp_path)})  # a directory cannot be appended to
    timeline.mark("view_built")
    assert timeline.enabled() is False


def _make_pdf(path: Path) -> Path:
    with fitz.open() as doc:
        doc.new_page(width=300, height=300).insert_text((36, 72), "timeline", fontsize=12)
        doc.save(str(path))
    return path


def test_cold_open_records_the_six_events_in_order(timeline, qapp, tmp_path, monkeypatch) -> None:
    import utils.preferences as preferences

    class Store:
        def __init__(self) -> None:
            self.data: dict = {}

        def value(self, key, default=None, type=None):  # noqa: A002 - QSettings signature
            return self.data.get(key, default)

        def setValue(self, key, value) -> None:
            self.data[key] = value

        def remove(self, key) -> None:
            self.data.pop(key, None)

        def contains(self, key) -> bool:
            return key in self.data

        def sync(self) -> None:
            return None

    store = Store()
    monkeypatch.setattr(preferences, "_make_default_store", lambda: store)
    path = tmp_path / "timeline.jsonl"
    pdf = _make_pdf(tmp_path / "doc.pdf")
    timeline.start({ENV: str(path)})
    startup = main_module.run(argv=[str(pdf)], start_event_loop=False)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            qapp.processEvents()
            if path.exists() and any(event["event"] == "first_sharp_paint" for event in _events(path)):
                break
            time.sleep(0.01)
        events = _events(path)
        names = [event["event"] for event in events]
        assert names == [
            "process_start", "view_built", "shown", "open_pdf_begin", "first_low_paint", "first_sharp_paint",
        ]
        clock = [event["t_ms"] for event in events]
        assert clock == sorted(clock)
    finally:
        startup["view"].close()
        if startup.get("model") is not None:
            startup["model"].close()
        startup["app"].setStyleSheet("")


_POOL_SCRIPT = """
import os, sys
from concurrent.futures import ProcessPoolExecutor

repo = sys.argv[1]
sys.path.insert(0, repo)
if __name__ == "__main__":
    import main  # parent: records its own process_start
    sys.modules["__main__"].__file__ = os.path.join(repo, "main.py")
    with ProcessPoolExecutor(max_workers=2) as ex:
        list(ex.map(abs, [-1, -2, -3, -4]))
"""


def test_spawned_pool_workers_do_not_write_process_start(tmp_path) -> None:
    import subprocess
    import sys

    script = tmp_path / "pool_probe.py"
    script.write_text(_POOL_SCRIPT, encoding="utf-8")
    out = tmp_path / "timeline.jsonl"
    env = {**__import__("os").environ, ENV: str(out)}
    repo = str(Path(__file__).resolve().parent.parent)
    result = subprocess.run(
        [sys.executable, str(script), repo], env=env, capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    starts = [event for event in _events(out) if event["event"] == "process_start"]
    assert len(starts) == 1
