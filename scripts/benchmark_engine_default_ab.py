#!/usr/bin/env python3
"""Same-session A/B of interactive edit latency: ``engine="legacy"`` vs
``engine="tiered"`` (Task 16 T16-3).

Why this script exists: ``TODOS.md`` T16-3 acceptance item 4 requires the
default-flip latency evidence to be measured *before/after in the same
session on the same machine*, because prior benchmark comparisons of
identical code swung 1.8x-3x across sessions and are not admissible
evidence. So both engines are timed in ONE process, alternating which one
goes first on each iteration to cancel any monotonic drift (thermal, page
cache, allocator growth).

What is measured: one ``PDFModel.edit_text()`` call -- the whole
interactive commit transaction, which under ``engine="tiered"`` includes
the new ``page_has_widgets_or_signatures`` probe plus the tiered
``prepare``/plan attempt on top of whatever work the legacy engine does.
Every iteration runs on a FRESH copy of the fixture with a FRESH
``PDFModel``, so every sample is a cold first-edit-on-this-page -- the
worst case for tiered and the one a user actually feels.

**Read the outcome distribution before reading the ratio.** On real
disk-loaded fixtures the tiered engine very often rejects at the plan
stage and falls back to the legacy engine (see
``scripts/benchmark_text_commit_baseline.py`` corpus notes). When it
does, the tiered timing is "legacy work + rejected tiered attempt", NOT
"a successful Tier 0 commit" -- a bare ratio would misreport what was
measured. This script therefore reports, per engine per fixture, the
``EditTextResult`` counts and the ``CommitOutcome`` status /
``fallback_chain`` / ``degraded_reason`` counts alongside the timings.
All of those are reason codes; no document text is ever emitted.

Model layer only -- no Qt import, matching the layer rule that the
commit engine stays reachable headlessly.

Usage::

    .venv/Scripts/python.exe scripts/benchmark_engine_default_ab.py [-n 20]
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import shutil
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import TextCommitSettings  # noqa: E402

logger = logging.getLogger(__name__)

ENGINES = ("legacy", "tiered")
#: Ratio above which the flip is a visible interactive regression and must
#: be reported prominently (TODOS.md T16-3 acceptance item 4).
RATIO_ALARM = 2.0


def _fixtures() -> list[tuple[str, Path]]:
    """The two fixtures named by the task: a small Latin document and the
    dense CJK HVAC drawing. The HVAC filename is globbed rather than
    hardcoded so this script carries no CJK literal."""
    found: list[tuple[str, Path]] = []
    simple = ROOT / "test_files" / "1.pdf"
    if simple.is_file():
        found.append(("simple", simple))
    hvac = sorted((ROOT / "test_files").glob("hvac-dwg*.pdf"))
    if hvac:
        found.append(("hvac", hvac[0]))
    return found


def _percentiles(samples: list[float]) -> dict[str, Any]:
    if not samples:
        return {
            "n": 0,
            "median": None,
            "p95": None,
            "mean": None,
            "min": None,
            "max": None,
        }
    ordered = sorted(samples)

    def _pct(p: float) -> float:
        # Nearest-rank, same convention as benchmark_text_commit_baseline.
        idx = int(round(p / 100.0 * len(ordered))) - 1
        return ordered[min(len(ordered) - 1, max(0, idx))]

    return {
        "n": len(ordered),
        "median": statistics.median(ordered),
        "p95": _pct(95.0),
        "mean": statistics.fmean(ordered),
        "min": ordered[0],
        "max": ordered[-1],
    }


def _pick_target(model: PDFModel) -> tuple[fitz.Rect, str, str] | None:
    """Pick a deterministic, engine-independent edit target on page 1.

    Returns ``(rect, original_text, new_text)``. ``new_text`` is the
    original with its characters rotated by one, so the replacement uses
    exactly the same glyph inventory as the original (no font-fallback
    asymmetry between the two engines) while still being a real change --
    ``edit_text`` short-circuits to ``NO_CHANGE`` on an identical string.
    Neither string is ever printed.
    """
    for block in model.block_manager.get_blocks(0):
        text = (block.text or "").strip()
        if len(text) < 2 or "\n" in text:
            continue
        rotated = text[1:] + text[0]
        if rotated == text:
            continue
        return fitz.Rect(block.layout_rect), block.text, rotated
    return None


def _outcome_codes(model: PDFModel) -> dict[str, str]:
    outcome = model.last_commit_outcome
    if outcome is None:
        return {"status": "none", "chain": "", "reason": ""}
    return {
        "status": outcome.status.value,
        "chain": "->".join(outcome.fallback_chain),
        "reason": outcome.degraded_reason or "",
    }


def _one_edit(src: Path, engine: str, workdir: Path, seq: int) -> dict[str, Any]:
    """Copy the fixture, open it fresh, time exactly one ``edit_text``."""
    scratch = workdir / f"{engine}_{seq}{src.suffix}"
    shutil.copyfile(src, scratch)
    model = PDFModel(text_commit_settings=TextCommitSettings(engine=engine))
    try:
        model.open_pdf(str(scratch))
        model.ensure_page_index_built(1)
        picked = _pick_target(model)
        if picked is None:
            return {"seconds": None, "result": "no_target", **_outcome_codes(model)}
        rect, original_text, new_text = picked
        t0 = time.perf_counter()
        result = model.edit_text(1, rect, new_text, original_text=original_text)
        seconds = time.perf_counter() - t0
        return {"seconds": seconds, "result": result.value, **_outcome_codes(model)}
    finally:
        model.close()
        scratch.unlink(missing_ok=True)


def _measure(src: Path, iterations: int, workdir: Path) -> dict[str, Any]:
    samples: dict[str, list[float]] = {e: [] for e in ENGINES}
    results: dict[str, Counter] = {e: Counter() for e in ENGINES}
    outcomes: dict[str, Counter] = {e: Counter() for e in ENGINES}

    for i in range(iterations):
        # Alternate which engine runs first so neither systematically
        # inherits a warmer (or a more fragmented) process.
        order = ENGINES if i % 2 == 0 else tuple(reversed(ENGINES))
        for engine in order:
            sample = _one_edit(src, engine, workdir, i)
            results[engine][sample["result"]] += 1
            key = "{}|{}|{}".format(sample["status"], sample["chain"], sample["reason"])
            outcomes[engine][key] += 1
            if sample["seconds"] is not None:
                samples[engine].append(sample["seconds"])

    report: dict[str, Any] = {"engines": {}}
    for engine in ENGINES:
        report["engines"][engine] = {
            "seconds": _percentiles(samples[engine]),
            "edit_text_results": dict(results[engine]),
            "commit_outcomes_status_chain_reason": dict(outcomes[engine]),
        }
    legacy_median = report["engines"]["legacy"]["seconds"]["median"]
    tiered_median = report["engines"]["tiered"]["seconds"]["median"]
    if legacy_median and tiered_median:
        ratio = tiered_median / legacy_median
        report["tiered_over_legacy_median_ratio"] = ratio
        report["exceeds_2x_alarm"] = ratio > RATIO_ALARM
    else:
        report["tiered_over_legacy_median_ratio"] = None
        report["exceeds_2x_alarm"] = None
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T16-3 engine latency A/B")
    parser.add_argument("-n", "--iterations", type=int, default=20)
    args = parser.parse_args(argv)

    fixtures = _fixtures()
    if not fixtures:
        logger.error("no fixtures found under test_files/")
        return 1

    report: dict[str, Any] = {
        "task": "T16-3 engine default flip latency A/B",
        "iterations_per_engine": args.iterations,
        "same_session": True,
        "machine": {
            "python": platform.python_version(),
            "pymupdf": getattr(fitz, "VersionBind", "?"),
            "platform": platform.platform(),
        },
        "caveat": (
            "Single machine, single session, no other load control. Numbers "
            "are comparable to EACH OTHER only; they are not a cross-session "
            "or cross-machine baseline. Every sample is a cold first edit on "
            "a fresh copy."
        ),
        "fixtures": {},
    }
    with tempfile.TemporaryDirectory(prefix="engine_ab_") as tmp:
        workdir = Path(tmp)
        for label, path in fixtures:
            report["fixtures"][label] = _measure(path, args.iterations, workdir)

    report["alarm_fixtures_over_2x"] = [
        label
        for label, data in report["fixtures"].items()
        if data.get("exceeds_2x_alarm")
    ]
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
