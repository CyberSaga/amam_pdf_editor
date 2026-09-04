#!/usr/bin/env python3
"""P4-B2 perf: cost of the exact painter geometry admission (Stage F, §3.5).

Times ``prepare_plan`` (``model/text_commit/plan.py``) with the exact-first
duplicate-painter arm engaged, on two synthetic corpora built by
``type0_fixture_builder`` / ``test_text_commit_duplicate_painter_gate``:

- the two-painter fixture (``_build_second_show_doc``) -- one target, one
  disjoint twin, the shape every P4-B2 admission test runs on;
- a dense same-bytes bucket -- one target plus 275 disjoint twins of the
  SAME decoded bytes, the O(twins) shape the per-glyph overlap loop pays
  for on a page where a word repeats often.

Each is timed cold (a fresh ``DocumentFontRegistry`` per call: the glyph-box
cache starts empty) and warm (one registry reused: the cache is populated
after the first call).  Also timed: the raw glyph-box parse cost per 1,000
gids on the fixture program, and the production preview keystroke path
(``PlanPreviewRenderer.render``, warm) on P3-C's own corpus, reusing
``benchmark_p3c_postprepare_latency.run_gate_and_latency`` unchanged so the
numbers are directly comparable to its own recorded baseline.

Output is aggregate-only: nearest-rank percentiles in milliseconds, sample
counts, and pass/fail counts.  Nothing textual, no filenames.  Raw JSON goes
to the gitignored ``benchmarks/``.

Usage::

    python scripts/benchmark_p4b2_admission.py [--repeat N] [--json]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from model.text_commit.cid_fonts import (  # noqa: E402
    parse_truetype_glyph_program,
    read_embedded_font_program,
)
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.glyph_boxes import glyph_unit_box  # noqa: E402
from model.text_commit.plan import PreparedEdit, prepare_plan  # noqa: E402
from scripts.benchmark_p3c_postprepare_latency import (  # noqa: E402
    UpdateStreamCounter,
    run_gate_and_latency,
)
from test_scripts.test_text_commit_duplicate_painter_gate import (  # noqa: E402
    FONTSIZE,
    SOURCE,
    SOURCE_WIDTH,
    _build_second_show_doc,
)
from test_scripts.type0_fixture_builder import (  # noqa: E402
    build_identity_h_fixture,
    encode_cids,
)

DENSE_TWIN_COUNT = 275
REPEAT_TWO_PAINTER = 30
REPEAT_DENSE = 10
GLYPH_PARSE_REPEAT = 5

# Recorded P3-C baseline (``benchmarks/p3c-acceptance-2026-08-23.json``,
# gitignored -- read locally, not committed): no plan file named
# ``plans/task13-p3c-preview-postprepare-latency.md`` exists in this repo.
P3C_BASELINE_WARM_P50_MS = 267.346
P3C_BASELINE_WARM_P95_MS = 315.638


def _percentiles(samples_ms: list[float]) -> dict[str, float | int]:
    """Nearest-rank percentiles (``benchmark_p3c_postprepare_latency``
    precedent: ``ceil`` never lands one order statistic low)."""
    ordered = sorted(samples_ms)
    n = len(ordered)
    if n == 0:
        return {"n": 0}

    def rank(fraction: float) -> float:
        return ordered[min(n - 1, max(0, math.ceil(n * fraction) - 1))]

    return {
        "n": n,
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(rank(0.95), 3),
        "p99_ms": round(rank(0.99), 3),
        "min_ms": round(ordered[0], 3),
        "max_ms": round(ordered[-1], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


def _build_dense_twin_bytes(count: int = DENSE_TWIN_COUNT) -> bytes:
    """One page: the target show plus ``count`` twins of the SAME decoded
    bytes, laid out on a grid wide enough apart that every pair is
    provably disjoint (the admission the timed calls must reach, not a
    refusal)."""
    fixture = build_identity_h_fixture(text=SOURCE, fontsize=FONTSIZE)
    try:
        stream = fixture.content_bytes()
        body = encode_cids(SOURCE).hex().upper()
        cols = 20
        dx = FONTSIZE * len(SOURCE) + 10.0
        dy = FONTSIZE + 10.0
        parts = [stream]
        for i in range(count):
            col, row = i % cols, i // cols
            x = fixture.origin[0] + dx * (col + 1)
            y = fixture.origin[1] - dy * (row + 1)
            parts.append(
                (
                    f"BT /{fixture.resource_name} {FONTSIZE:g} Tf "
                    f"1 0 0 1 {x:g} {y:g} Tm <{body}> Tj ET"
                ).encode("ascii")
            )
        fixture.doc.update_stream(fixture.content_xref, b"\n".join(parts))
        return fixture.doc.tobytes()
    finally:
        fixture.doc.close()


def _benchmark_prepare(
    doc_bytes: bytes,
    *,
    target_text: str,
    replacement_text: str,
    origin: tuple[float, float],
    repeat: int,
) -> dict[str, object]:
    cold: list[float] = []
    cold_admitted = 0
    for _ in range(repeat):
        doc = fitz.open("pdf", doc_bytes)
        try:
            registry = DocumentFontRegistry(doc)
            page = doc[0]
            start = time.perf_counter()
            result = prepare_plan(
                doc, page,
                target_text=target_text, replacement_text=replacement_text,
                expected_origin=origin, target_bbox=None, registry=registry,
                max_tier=1,
            )
            cold.append((time.perf_counter() - start) * 1e3)
            if isinstance(result, PreparedEdit):
                cold_admitted += 1
        finally:
            doc.close()

    doc = fitz.open("pdf", doc_bytes)
    try:
        registry = DocumentFontRegistry(doc)
        page = doc[0]
        warm: list[float] = []
        warm_admitted = 0
        for _ in range(repeat):
            start = time.perf_counter()
            result = prepare_plan(
                doc, page,
                target_text=target_text, replacement_text=replacement_text,
                expected_origin=origin, target_bbox=None, registry=registry,
                max_tier=1,
            )
            warm.append((time.perf_counter() - start) * 1e3)
            if isinstance(result, PreparedEdit):
                warm_admitted += 1
        glyph_boxes_cached = registry.glyph_boxes.cached_count
    finally:
        doc.close()

    return {
        "repeat": repeat,
        "cold": _percentiles(cold),
        "cold_admitted": cold_admitted,
        "warm": _percentiles(warm),
        "warm_admitted": warm_admitted,
        "warm_glyph_boxes_cached": glyph_boxes_cached,
    }


def _benchmark_glyph_box_parse(fixture, *, repeat: int = GLYPH_PARSE_REPEAT) -> dict[str, object]:
    program = read_embedded_font_program(fixture.doc, fixture.font_xref)
    assert program is not None
    parsed = parse_truetype_glyph_program(program)
    assert parsed is not None
    gids = list(range(min(parsed.num_glyphs, 2000)))
    start = time.perf_counter()
    for _ in range(repeat):
        for gid in gids:
            glyph_unit_box(program, parsed, gid)
    elapsed_ms = (time.perf_counter() - start) * 1e3
    total_gids = repeat * len(gids)
    return {
        "gids": len(gids),
        "repeat": repeat,
        "total_ms": round(elapsed_ms, 3),
        "ms_per_1000_gids": round(elapsed_ms / total_gids * 1000.0, 3) if total_gids else 0.0,
    }


def _first_origin(page: fitz.Page, probe: str) -> tuple[float, float]:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                text = "".join(ch["c"] for ch in span["chars"])
                if probe in text:
                    return tuple(float(v) for v in span["chars"][0]["origin"])
    raise AssertionError("probe span not found")


def run(*, repeat_two_painter: int, repeat_dense: int) -> dict[str, object]:
    two_painter, expected_origin = _build_second_show_doc(offset=SOURCE_WIDTH)
    try:
        two_painter_bytes = two_painter.doc.tobytes()
    finally:
        two_painter.doc.close()
    two_painter_report = _benchmark_prepare(
        two_painter_bytes,
        target_text=SOURCE,
        replacement_text="再",  # a single admissible CJK replacement char
        origin=expected_origin,
        repeat=repeat_two_painter,
    )

    dense_bytes = _build_dense_twin_bytes()
    dense_doc = fitz.open("pdf", dense_bytes)
    try:
        dense_origin = _first_origin(dense_doc[0], SOURCE)
    finally:
        dense_doc.close()
    dense_report = _benchmark_prepare(
        dense_bytes,
        target_text=SOURCE,
        replacement_text="再",
        origin=dense_origin,
        repeat=repeat_dense,
    )

    glyph_parse_fixture = build_identity_h_fixture(text=SOURCE, fontsize=FONTSIZE)
    try:
        glyph_parse_report = _benchmark_glyph_box_parse(glyph_parse_fixture)
    finally:
        glyph_parse_fixture.doc.close()

    counter = UpdateStreamCounter()
    counter.install()
    try:
        preview_report, preview_failures = run_gate_and_latency(counter)
    finally:
        counter.uninstall()
    preview_warm_p50 = preview_report["warm_renders"]["p50_ms"]
    preview_warm_p95 = preview_report["warm_renders"]["p95_ms"]
    preview_comparison = {
        "baseline_source": "benchmarks/p3c-acceptance-2026-08-23.json (gitignored; "
        "plans/task13-p3c-preview-postprepare-latency.md does not exist)",
        "baseline_warm_p50_ms": P3C_BASELINE_WARM_P50_MS,
        "baseline_warm_p95_ms": P3C_BASELINE_WARM_P95_MS,
        "current_warm_p50_ms": preview_warm_p50,
        "current_warm_p95_ms": preview_warm_p95,
        "p50_ratio": round(preview_warm_p50 / P3C_BASELINE_WARM_P50_MS, 3),
        "p95_ratio": round(preview_warm_p95 / P3C_BASELINE_WARM_P95_MS, 3),
        "acceptance_failures": preview_failures,
    }

    return {
        "harness": "p4b2-admission-benchmark",
        "corpus": "synthetic-deterministic (this script)",
        "two_painter_fixture": two_painter_report,
        "dense_same_bytes_bucket": {"twins": DENSE_TWIN_COUNT, **dense_report},
        "glyph_box_parse": glyph_parse_report,
        "preview_keystroke_path": {
            "gate_and_latency": preview_report,
            "comparison_to_p3c_baseline": preview_comparison,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=REPEAT_TWO_PAINTER)
    parser.add_argument("--dense-repeat", type=int, default=REPEAT_DENSE)
    parser.add_argument("--json", action="store_true", help="compact JSON")
    parser.add_argument(
        "--json-out",
        type=Path,
        default=ROOT / "benchmarks" / "p4b2-admission-2026-09-04.json",
        help="aggregate-only report path (gitignored benchmarks/ by default)",
    )
    args = parser.parse_args(argv)
    fitz.TOOLS.mupdf_display_errors(False)
    report = run(repeat_two_painter=args.repeat, repeat_dense=args.dense_repeat)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=None if args.json else 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
