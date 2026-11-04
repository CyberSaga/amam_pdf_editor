#!/usr/bin/env python3
"""Corpus scanner for the two sfnt readers (``simple_font_programs`` R1 and ``cid_fonts`` R2).

Why this exists.  Two readers walk the same TrueType table directory (see ``plans/archive/sfnt-directory.md``).  Any change
to either reader must be proven against every embedded TrueType program the corpus holds, not against the handful of
synthetic fixtures.  This tool finds every ``/FontFile2`` (and any ``/FontFile3`` that is really a TrueType) program
under a corpus directory, and runs the REAL product readers over each distinct program (by sha256):

``--scan [--json OUT]``
    Incidence report: how many programs repeat a table tag, carry a ``head`` shorter than 54 bytes, are ``ttcf``
    containers or have a table past the end of the program; the ``head`` length histogram; where R1 and R2 disagree
    TODAY and why.  The raw directory facts come from this tool's own walk, not from either reader.

``--fingerprint OUT``
    One JSON line per distinct program: R1 ``program_kind``, ``num_glyphs`` and ``present`` / ``proves`` for codes
    0..255 against ``chr(code)`` (called through the facade ``builtin_glyph_proof``; an exception is recorded, never
    raised), and every ``GlyphProgram`` field R2 returns (``None`` when it refuses).  A ``loca`` tuple is recorded as
    its length and a sha256 of its values, so a changed loca shows up in a diff without a 20 000-entry list.  R1
    refusal TEXT is not recorded (the facade collapses it to ``unproven:unreadable``).

``--diff BASE OUT``
    Compare two fingerprint files (run ``--fingerprint`` before and after a reader change) and print every program
    whose fingerprint changed, with the change and where it lives.  Exit status 1 when anything differs.

Paths are arguments (default corpus: ``<repo>/test_files``); nothing machine-specific is written.  Run it with the
project venv (``.venv\\Scripts\\python.exe scripts\\sfnt_corpus_scan.py ...``): another Python carries another PyMuPDF.
The fingerprint is deterministic (PDFs sorted, keys sorted, no timestamps), so two runs on one tree are byte-equal.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import struct
import sys
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from model.text_commit import cid_fonts, simple_font_programs  # noqa: E402

SFNT_TAGS = (b"\x00\x01\x00\x00", b"true")
HEAD_MIN = 54
MAX_REFS_KEPT = 3  # provenance samples per distinct program in a fingerprint line


# ---------------------------------------------------------------------------------------------- corpus walking


def list_pdfs(corpus: Path) -> list[Path]:
    return sorted(path for path in corpus.rglob("*") if path.is_file() and path.suffix.lower() == ".pdf")


def _ref_xref(value: tuple[str, str]) -> int | None:
    kind, text = value
    if kind != "xref":
        return None
    try:
        return int(text.split()[0])
    except (ValueError, IndexError):
        return None


def iter_programs(pdf: Path) -> Iterator[tuple[int, bytes]]:
    """``(stream xref, bytes)`` of every distinct sfnt-looking font program in ``pdf`` (none when it cannot be opened)."""
    try:
        doc = fitz.open(str(pdf))
    except Exception:  # noqa: BLE001 - a corrupt corpus file is data, not a crash
        return
    try:
        if doc.needs_pass:
            return
        seen: set[int] = set()
        for xref in range(1, doc.xref_length()):
            try:
                keys = doc.xref_get_keys(xref)
            except Exception:  # noqa: BLE001
                continue
            for key in ("FontFile2", "FontFile3"):
                if key not in keys:
                    continue
                try:
                    stream_xref = _ref_xref(doc.xref_get_key(xref, key))
                    if stream_xref is None or stream_xref in seen:
                        continue
                    data = doc.xref_stream(stream_xref)
                except Exception:  # noqa: BLE001
                    continue
                if not data:
                    continue
                seen.add(stream_xref)
                if key == "FontFile3" and data[:4] not in (*SFNT_TAGS, b"ttcf"):
                    continue  # CFF / OpenType-CFF: neither reader reads it
                yield stream_xref, data
    finally:
        doc.close()


def collect(corpus: Path) -> tuple[dict[str, dict], dict[str, int]]:
    """``sha -> {"data": bytes, "refs": [(relative pdf, xref)...], "count": n}`` and the totals.

    Every distinct program is kept in memory once (the corpus is a few hundred MB at most)."""
    programs: dict[str, dict] = {}
    pdfs = list_pdfs(corpus)
    with_programs = 0
    total = 0
    for pdf in pdfs:
        rel = pdf.relative_to(corpus).as_posix()
        found = 0
        for xref, data in iter_programs(pdf):
            found += 1
            total += 1
            sha = hashlib.sha256(data).hexdigest()
            entry = programs.get(sha)
            if entry is None:
                programs[sha] = entry = {"data": data, "refs": [], "count": 0}
            entry["count"] += 1
            entry["refs"].append((rel, xref))
        with_programs += bool(found)
    return programs, {
        "pdfs_found": len(pdfs),
        "pdfs_with_programs": with_programs,
        "programs": total,
        "distinct_programs": len(programs),
    }


# ---------------------------------------------------------------------------------------------- fingerprint


def _loca_digest(values: tuple[int, ...]) -> dict[str, object]:
    packed = struct.pack(f">{len(values)}Q", *values) if values else b""
    return {"len": len(values), "sha256": hashlib.sha256(packed).hexdigest()}


def r2_fingerprint(data: bytes) -> dict[str, object] | None:
    try:
        program = cid_fonts.parse_truetype_glyph_program(data)
    except Exception as exc:  # noqa: BLE001 - a crash is a fingerprint too
        return {"raised": type(exc).__name__}
    if program is None:
        return None
    out: dict[str, object] = {}
    for field in dataclasses.fields(program):
        value = getattr(program, field.name)
        out[field.name] = _loca_digest(value) if isinstance(value, tuple) else value
    return out


def r1_fingerprint(data: bytes) -> dict[str, object]:
    try:
        proof = simple_font_programs.builtin_glyph_proof(data, "FontFile2")
    except Exception as exc:  # noqa: BLE001
        return {"raised": type(exc).__name__}
    present: list[str] = []
    proves: list[str] = []
    errors: Counter[str] = Counter()
    for code in range(256):
        for out, call in ((present, lambda: proof.present(code)), (proves, lambda: proof.proves(code, chr(code)))):
            try:
                out.append("1" if call() else "0")
            except Exception as exc:  # noqa: BLE001
                out.append("E")
                errors[type(exc).__name__] += 1
    return {
        "program_kind": proof.program_kind,
        "num_glyphs": proof.num_glyphs,
        "present": "".join(present),
        "proves": "".join(proves),
        "errors": dict(sorted(errors.items())),
    }


def fingerprint_lines(programs: dict[str, dict], totals: dict[str, int]) -> list[str]:
    lines = [json.dumps({"meta": totals}, sort_keys=True)]
    for sha in sorted(programs):
        entry = programs[sha]
        data = entry["data"]
        record = {
            "sha": sha,
            "size": len(data),
            "count": entry["count"],
            "refs": [list(ref) for ref in entry["refs"][:MAX_REFS_KEPT]],
            "r1": r1_fingerprint(data),
            "r2": r2_fingerprint(data),
        }
        lines.append(json.dumps(record, sort_keys=True))
    return lines


def load_fingerprint(path: Path) -> tuple[dict, dict[str, dict]]:
    meta: dict = {}
    records: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if "meta" in record:
            meta = record["meta"]
        else:
            records[record["sha"]] = record
    return meta, records


def _bitmap_changes(old: str, new: str) -> str:
    changed = [code for code in range(min(len(old), len(new))) if old[code] != new[code]]
    shown = ", ".join(f"{code}:{old[code]}>{new[code]}" for code in changed[:12])
    return f"{len(changed)} codes ({shown}{', ...' if len(changed) > 12 else ''})"


def describe_change(old: dict, new: dict) -> list[str]:
    out: list[str] = []
    for side in ("r1", "r2"):
        before, after = old[side], new[side]
        if before == after:
            continue
        if before is None or after is None or "raised" in (before or {}) or "raised" in (after or {}):
            out.append(f"{side}: {_short(before)} -> {_short(after)}")
            continue
        for key in sorted(set(before) | set(after)):
            if before.get(key) == after.get(key):
                continue
            if key in ("present", "proves"):
                out.append(f"{side}.{key}: {_bitmap_changes(before[key], after[key])}")
            else:
                out.append(f"{side}.{key}: {before.get(key)!r} -> {after.get(key)!r}")
    return out


def _short(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, dict) and "program_kind" in value:
        return f"{value['program_kind']} ({value['num_glyphs']} glyphs)"
    return json.dumps(value, sort_keys=True)[:160]


def run_diff(base: Path, other: Path) -> int:
    base_meta, base_records = load_fingerprint(base)
    meta, records = load_fingerprint(other)
    changed = 0
    for sha in sorted(set(base_records) | set(records)):
        old, new = base_records.get(sha), records.get(sha)
        if old is None or new is None:
            side = "only in the new fingerprint" if old is None else "only in the base fingerprint"
            record = new or old
            assert record is not None
            print(f"{sha[:16]}  {side}  refs={record['refs']}")
            changed += 1
            continue
        lines = describe_change(old, new)
        if lines:
            changed += 1
            print(f"{sha[:16]}  size={new['size']}  count={new['count']}  refs={new['refs']}")
            for line in lines:
                print(f"    {line}")
    print(f"base meta: {base_meta}")
    print(f"new  meta: {meta}")
    print(f"{changed} of {len(set(base_records) | set(records))} distinct programs differ")
    return 1 if changed else 0


# ---------------------------------------------------------------------------------------------- scan report


def read_raw_directory(data: bytes) -> dict[str, object]:
    """This tool's own reading of the table directory (neither product reader is trusted to report on itself)."""
    info: dict[str, object] = {"tag4": data[:4].hex(), "ttcf": data[:4] == b"ttcf", "entries": None}
    view = data
    if data[:4] == b"ttcf":
        offset = int.from_bytes(data[12:16], "big") if len(data) >= 16 else 0
        info["ttcf_members"] = int.from_bytes(data[8:12], "big") if len(data) >= 12 else None
        view = data[offset:] if 0 < offset and offset + 12 <= len(data) else b""
    if len(view) < 12 or view[:4] not in SFNT_TAGS:
        return info
    count = int.from_bytes(view[4:6], "big")
    if 12 + 16 * count > len(view):
        return info
    info["entries"] = [
        (
            view[12 + 16 * i : 16 + 16 * i],
            int.from_bytes(view[20 + 16 * i : 24 + 16 * i], "big"),
            int.from_bytes(view[24 + 16 * i : 28 + 16 * i], "big"),
        )
        for i in range(count)
    ]
    info["view_size"] = len(view)
    return info


def _r1_outcome(data: bytes) -> str:
    try:
        simple_font_programs._TrueTypeProgram(data)
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {getattr(exc, 'reason', None) or exc}"
    return "ok"


def run_scan(programs: dict[str, dict], totals: dict[str, int]) -> dict[str, object]:
    head_lengths: Counter[tuple[int | None, int | None]] = Counter()
    dup_programs: list[str] = []
    short_head: list[str] = []
    ttcf_programs: list[dict] = []
    oor_programs: list[dict] = []
    no_directory = 0
    r1_counts: Counter[str] = Counter()
    r2_counts: Counter[str] = Counter()
    disagree: Counter[str] = Counter()
    for sha, entry in programs.items():
        data = entry["data"]
        raw = read_raw_directory(data)
        ref = entry["refs"][0]
        if raw["ttcf"]:
            ttcf_programs.append({"sha": sha[:16], "members": raw.get("ttcf_members"), "size": len(data), "ref": list(ref)})
        entries = raw["entries"]
        if entries is None:
            no_directory += 1
        else:
            by_tag: dict[bytes, list[tuple[int, int]]] = {}
            view_size = int(raw["view_size"])  # type: ignore[arg-type]
            oor_tags = []
            for tag, offset, length in entries:
                by_tag.setdefault(tag, []).append((offset, length))
                if offset + length > view_size:
                    oor_tags.append(tag.decode("latin-1"))
            if any(len(v) > 1 for v in by_tag.values()):
                dup_programs.append(sha[:16])
            heads = by_tag.get(b"head", [])
            head_lengths[(heads[0][1] if heads else None, heads[-1][1] if heads else None)] += 1
            if any(length < HEAD_MIN for _o, length in heads):
                short_head.append(sha[:16])
            if oor_tags:
                oor_programs.append({"sha": sha[:16], "tags": sorted(set(oor_tags)), "ref": list(ref)})
        r1 = _r1_outcome(data)
        r1_counts[r1] += 1
        try:
            r2_ok = cid_fonts.parse_truetype_glyph_program(data) is not None
        except Exception:  # noqa: BLE001
            r2_ok = False
        r2_counts["ok" if r2_ok else "refused"] += 1
        if (r1 == "ok") != r2_ok:
            disagree[f"R1 {r1} / R2 {'readable' if r2_ok else 'refused'}"] += 1
    return {
        "totals": totals,
        "no_readable_directory": no_directory,
        "head_length_first_last": {f"{k[0]},{k[1]}": v for k, v in sorted(head_lengths.items(), key=str)},
        "repeated_tag_programs": len(dup_programs),
        "head_shorter_than_54_programs": len(short_head),
        "ttcf_programs": ttcf_programs,
        "out_of_range_programs": oor_programs,
        "r1_outcomes": dict(r1_counts.most_common()),
        "r2_outcomes": dict(r2_counts.most_common()),
        "r1_r2_disagree": dict(disagree.most_common()),
    }


def print_scan(report: dict[str, object]) -> None:
    print(f"totals: {report['totals']}")
    print(f"programs with no readable directory: {report['no_readable_directory']}")
    print(f"head length (first entry, last entry) -> distinct programs: {report['head_length_first_last']}")
    print(f"programs with a repeated tag: {report['repeated_tag_programs']}")
    print(f"programs with a head entry shorter than {HEAD_MIN}: {report['head_shorter_than_54_programs']}")
    print(f"ttcf containers: {len(report['ttcf_programs'])}")  # type: ignore[arg-type]
    for item in report["ttcf_programs"]:  # type: ignore[attr-defined]
        print(f"    {item}")
    print(f"programs with a table past the end: {len(report['out_of_range_programs'])}")  # type: ignore[arg-type]
    for item in report["out_of_range_programs"]:  # type: ignore[attr-defined]
        print(f"    {item}")
    print(f"R1 outcomes: {report['r1_outcomes']}")
    print(f"R2 outcomes: {report['r2_outcomes']}")
    print(f"R1/R2 disagree: {report['r1_r2_disagree']}")


# ---------------------------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scan", action="store_true", help="print the incidence report")
    mode.add_argument("--fingerprint", metavar="OUT", type=Path, help="write one fingerprint line per distinct program")
    mode.add_argument("--diff", nargs=2, metavar=("BASE", "OUT"), type=Path, help="compare two fingerprint files")
    parser.add_argument("--corpus", type=Path, default=ROOT / "test_files", help="directory of PDFs (default: <repo>/test_files)")
    parser.add_argument("--json", type=Path, default=None, metavar="OUT", help="with --scan: also write the report as JSON")
    args = parser.parse_args(argv)

    if args.diff:
        return run_diff(args.diff[0], args.diff[1])
    fitz.TOOLS.mupdf_display_errors(False)
    programs, totals = collect(args.corpus)
    if args.fingerprint:
        args.fingerprint.write_text("\n".join(fingerprint_lines(programs, totals)) + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {len(programs)} fingerprints: {totals}")
        return 0
    report = run_scan(programs, totals)
    print_scan(report)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
