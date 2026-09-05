#!/usr/bin/env python3
"""Read-only corpus funnel for ``parse_tounicode_strict`` (Task 16 T16-3).

Answers ONE question per document: how many of its distinct Type0 fonts
carry a ``/ToUnicode`` CMap the strict parser accepts?  That is the
acceptance measurement for widening the v1 grammar to the
array-destination ``bfrange`` form (PDF 32000-1 §9.10.3) — run it before
and after the parser change and compare.

Data policy (plan §10): documents are positional (``doc_0``…), fonts are
counted and never named, and the only per-failure output is the parser's
own code-only ``detail`` string slugified into a stable key.  No document
text, font name, or file path is ever printed.

Buckets are disjoint by construction::

    type0_fonts       distinct Type0 font xrefs across all pages
    tounicode_present those carrying a readable /ToUnicode stream
    parse_ok          those whose stream parse_tounicode_strict accepts

so a ``no_tounicode`` or ``unreadable_stream`` loss can never be mistaken
for a parser refusal.

Usage::

    python scripts/scan_tounicode_parse.py <pdf> [more...] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.cid_fonts import (  # noqa: E402
    CidCapabilityFailure,
    parse_tounicode_strict,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(detail: str) -> str:
    """A stable histogram key from the parser's code-only detail string."""
    return _SLUG_RE.sub("_", detail.strip().lower()).strip("_") or "unspecified"


def _type0_font_xrefs(doc: fitz.Document) -> list[int]:
    """Distinct Type0 font xrefs, deduped GLOBALLY across every page."""
    seen: list[int] = []
    known: set[int] = set()
    for page in doc:
        for entry in page.get_fonts(full=True):
            xref, _ext, font_type = entry[0], entry[1], entry[2]
            if font_type != "Type0" or xref in known:
                continue
            known.add(xref)
            seen.append(xref)
    return seen


def _tounicode_bytes(doc: fitz.Document, font_xref: int) -> bytes | None:
    """The DECOMPRESSED /ToUnicode stream of one font, else None."""
    kind, value = doc.xref_get_key(font_xref, "ToUnicode")
    if kind != "xref":
        return None
    try:
        stream_xref = int(value.split()[0])
    except (ValueError, IndexError):
        return None
    try:
        return doc.xref_stream(stream_xref)
    except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase):
        return None


def scan_document(path: Path) -> dict[str, object]:
    """Per-document counts plus a histogram of refusal detail slugs."""
    histogram: Counter[str] = Counter()
    doc = fitz.open(path)
    try:
        font_xrefs = _type0_font_xrefs(doc)
        present = 0
        parse_ok = 0
        for font_xref in font_xrefs:
            data = _tounicode_bytes(doc, font_xref)
            if data is None:
                histogram["no_tounicode"] += 1
                continue
            present += 1
            result = parse_tounicode_strict(data)
            if isinstance(result, CidCapabilityFailure):
                histogram[_slug(result.detail)] += 1
                continue
            parse_ok += 1
    finally:
        doc.close()
    return {
        "type0_fonts": len(font_xrefs),
        "tounicode_present": present,
        "parse_ok": parse_ok,
        "failures": dict(sorted(histogram.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Count Type0 fonts whose /ToUnicode CMap parse_tounicode_strict "
            "accepts (code-only output)."
        )
    )
    parser.add_argument("paths", nargs="+", type=Path, help="PDF files to scan")
    parser.add_argument(
        "--json", action="store_true", help="emit one JSON object instead"
    )
    args = parser.parse_args(argv)

    report: dict[str, object] = {}
    for index, path in enumerate(args.paths):
        key = f"doc_{index}"
        try:
            report[key] = scan_document(path)
        except (RuntimeError, ValueError, fitz.mupdf.FzErrorBase) as exc:
            report[key] = {"error": type(exc).__name__}

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    for key, entry in report.items():
        assert isinstance(entry, dict)
        if "error" in entry:
            print(f"{key}: unreadable ({entry['error']})")
            continue
        print(
            f"{key}: type0_fonts={entry['type0_fonts']} "
            f"tounicode_present={entry['tounicode_present']} "
            f"parse_ok={entry['parse_ok']}"
        )
        failures = entry["failures"]
        assert isinstance(failures, dict)
        for slug, count in failures.items():
            print(f"    {slug}={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
