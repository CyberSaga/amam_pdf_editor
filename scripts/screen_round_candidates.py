#!/usr/bin/env python3
"""Product-probe screen for the Grok round lists (round 10 on): which public files REACH a frontier class.

Why this exists.  The round-8 list (brief v12 section 3.9) was built from census buckets plus a hand locate that
checked the font's encoding bucket and the operator shape and nothing else; the audit (brief v13 section 3.10) dropped
13 of its 25 rows because the production classifier refused every show of them (``untracked_advance``,
``trm_non_uniform_scale``, the widget gate, source-side ``encoding_failed``, non-printable bytes) or because the
class had been judged by the encoding bucket instead of by the font (``emb`` dropped: four rows were non-embedded).
An instrument that mirrors a gate goes stale the day the gate moves (``scripts/measure_tier_funnel.py``), so this
screen calls the gate: every verdict column is ``plan.prepare_plan`` at ``max_tier`` 0 and 1 with the show's own
page-space origin, run on a scratch copy, and the hand filters are cost pre-filters only.

What a file must show, per class (brief v13 sections 3.1 and 3.3):

* the class is decided by the FONT (:func:`classify_f30_font`): F30B = embedded simple font without /Encoding, and
  only an embedded TrueType (FontFile2) has an independent glyph leg, so an embedded Type1/CFF is bucketed
  ``F30B_no_leg``; F30W = embedded with /WinAnsiEncoding, /MacRomanEncoding or /StandardEncoding (a /Differences
  font is already ``font_custom_differences``); F30N = non-embedded Standard 14 (base font minus the subset prefix),
  non-symbolic (an absent FontDescriptor counts as non-symbolic), /Encoding absent or one of the three names;
  a non-embedded font outside the Standard 14 belongs to no F30 class;
* the F2K shape is the TJ items (:func:`f2k_trailing_kern`): exactly one string followed by one kern; a zero kern
  is the shape, the product reaches the fence on it, so it is probed and flagged ``zero_kern`` but is never
  ``reach_clean`` (it cannot show compensation of a non-zero border kern);
* per show: ``Tr 0``, outside marked content, ``origin_reliable`` (``untracked_advance`` otherwise), on a page the
  widget gate admits, a printable-ASCII target of two or more bytes without the quote operators, and not a
  palindrome (the F30 probe is the reversed target: equal advance by construction, so Tier 0);
* the verdict: F30 reaches when the reversed target PREPARES at Tier 0; F2K reaches when the grown target (one more
  glyph the font already draws) meets the Tier 1 fence ``tj_kern_in_tier1_range`` (``plan.py`` ~2495-2508), which is
  the code the F2K experiments are built around; ``reach_clean`` adds the independent glyph leg (F30B, F30N) or a
  blank growth strip (F2K, counted with the product's ``count_growth_zone_glyphs`` on the product's grown box).

Cost.  ``prepare_plan`` is 1-15 ms per show; probing every show of the public trees would take hours, so every file
is capped (``--page-cap`` evenly spaced pages for the F30 shapes, ``--probe-cap`` probes and ``--reach-cap`` reaches
per class).  The locate pass (replay + capability) is cheap, so the rare F2K shape is read on EVERY page (the
15-page sample hid issue20722, whose five reaching shows all sat on skipped pages).  Measured 2026-10-30 over the
four public trees: 4,397 files, 26,467 pages replayed, six shards, about four minutes.

What the refuters changed (three Opus refuters re-ran the probes on 2026-10-30, scratchpad ``r10/refute_*``): a
zero trailing kern is probed and flagged, not skipped, because the product reaches the fence on it (issue17784
6/6); the independent leg decides ``reach_clean`` for F30W too, because an F30W positive on a Type1/CFF font is
quarantined at rederive on ``oracle_assert_glyph_identity`` (issue1729, issue1685, issue2881 looked clean before);
a font the product rejects is counted under ``font_rejected`` instead of vanishing; and a family is "new" only when
its product SERIES (:data:`SERIES_ALIASES`) has no registered file in any class, since section 3.0 counts producer
families (a Distiller 10 file is not a new family while Distiller 8 and 9 are registered under other classes).

Privacy.  A record holds sha8, the tree-relative path, page and show numbers, reason codes, counts and a producer
token normalised from ``/Producer`` alone (``/Creator`` often carries a company name and never enters a tracked
file); never document text, never an absolute path.  The summary marks the files already in the tracked sha table so
the list shows NEW producer families, which is what section 3.0 ``single_family`` is gated on.

usage (from the repo root; the trees are read-only, every probe runs on a scratch copy)::

    .venv\\Scripts\\python.exe scripts/screen_round_candidates.py --out <records.jsonl> [--summary <summary.md>]
        [--root <checkout with test_files>] [--tree mozilla-pdf ...] [--page-cap 15] [--probe-cap 12] [--reach-cap 4]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from model.text_commit.cid_fonts import CidCapabilityFailure  # noqa: E402
from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.fonts import _BASE14_ALIASES, DocumentFontRegistry, FontCapability, _is_symbolic  # noqa: E402
from model.text_commit.glyph_boxes import TjItem, tj_items  # noqa: E402
from model.text_commit.inspect import _origin_in_page_space, page_has_widgets_or_signatures, read_page_streams  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit, _advance, _grown_verify_bbox, prepare_plan  # noqa: E402
from model.text_commit.replay import DEFAULT_MAX_REPLAY_BYTES, replay_page_streams  # noqa: E402
from model.text_commit.transforms import map_text_quad_to_visual, page_visual_frame  # noqa: E402
from model.text_commit.verify import count_growth_zone_glyphs  # noqa: E402
from test_scripts.true_text_acceptance_helpers import IndependentLegUnavailable, _glyph_leg  # noqa: E402

PUBLIC_TREES = ("sample-files-main", "veraPDF-corpus-staging", "Test-PDF-Files-master", "mozilla-pdf")
SHA_TABLE = ROOT / "test_scripts" / "fixtures" / "public_corpus_sha256.json"
_STANDARD_14_LATIN = frozenset(name for name in _BASE14_ALIASES if name not in ("Symbol", "ZapfDingbats"))
_NAMED_SIMPLE_ENCODINGS = ("WinAnsiEncoding", "MacRomanEncoding", "StandardEncoding")
_QUOTE_OPERATORS = (0x27, 0x60)
CLASSES = ("F2K", "F30B", "F30W", "F30N")


# ---------------------------------------------------------------------------------------------------------------------
# pure pieces (pinned by test_screen_round_candidates.py)
# ---------------------------------------------------------------------------------------------------------------------
def classify_f30_font(cap: FontCapability, *, symbolic: bool) -> str | None:
    """``"F30B"``, ``"F30B_no_leg"``, ``"F30W"``, ``"F30N"`` or ``None`` for one font, by the font itself."""
    if cap.tier0_reject_reason is not None or cap.cid is not None or cap.subtype not in ("Type1", "TrueType"):
        return None
    if cap.embedded:
        if cap.encoding == "":
            return "F30B" if cap.subtype == "TrueType" else "F30B_no_leg"
        return "F30W" if cap.encoding in _NAMED_SIMPLE_ENCODINGS else None
    if symbolic or cap.basefont.split("+", 1)[-1] not in _STANDARD_14_LATIN:
        return None
    return "F30N" if cap.encoding in ("", *_NAMED_SIMPLE_ENCODINGS) else None


def f2k_trailing_kern(items: Sequence[TjItem] | None) -> float | None:
    """The kern of a ``[(string) K] TJ`` array (exactly one string then one kern); ``None`` for any other shape."""
    if not items or len(items) != 2 or items[0].kind != "string" or items[1].kind != "kern":
        return None
    return float(items[1].value)


def printable_target(data: bytes, *, min_len: int = 2) -> bool:
    """``min_len`` or more printable ASCII bytes, none of them a quote operator (``'`` and `````)."""
    return len(data) >= min_len and all(0x20 <= c <= 0x7E and c not in _QUOTE_OPERATORS for c in data)


def family_token(metadata: Mapping[str, object] | None) -> str:
    """A producer-family token from ``/Producer`` ALONE: letters only, lower case, the first two words."""
    producer = (metadata or {}).get("producer") or ""
    words = re.sub(r"[^A-Za-z]+", " ", str(producer)).lower().split()
    return "-".join(words[:2]) if words else "<none>"


# Producer SERIES (brief v12 (bi): a lineage is a product series, not a version string).  A family token whose first
# word or whole token is listed here belongs to that series; everything else is its own series.  The owner can
# overrule a series call at registration; the table only keeps the summary from calling a Distiller 10 file a new
# family while Distiller 8 and 9 are registered.
SERIES_ALIASES: dict[str, str] = {
    "acrobat": "adobe", "adobe": "adobe", "adep": "adobe",
    "itext": "itext-prawn", "itextsharp": "itext-prawn", "prawn": "itext-prawn",
    "gpl": "ghostscript", "gnu": "ghostscript", "ghostscript": "ghostscript", "pdfcreator": "ghostscript",
    "cairo": "cairo", "firefox": "cairo",
    "mac": "quartz", "quartz": "quartz",
    "pdftex": "tex", "xetex": "tex", "luatex": "tex", "dvips": "tex",
    "yeslogic": "prince", "prince": "prince",
    "pdflib": "pdflib",
}


def series_of(family: str) -> str:
    """The product series a producer-family token belongs to (the token itself when no alias applies)."""
    head = family.split("-", 1)[0]
    return SERIES_ALIASES.get(family, SERIES_ALIASES.get(head, family))


def registry_lineages(table: Mapping[str, object]) -> dict[str, str]:
    """``sha8 -> lineage_id`` from the tracked public sha table."""
    return {str(row["sha256"])[:8]: str(row["lineage_id"]) for row in table.get("files", ())}  # type: ignore[union-attr]


def file_record(screened: Mapping[str, object], *, sha256: str, relative_path: str, size: int) -> dict:
    """The per-file JSONL record: identity fields (sha8, tree-relative path, size) plus the screen result."""
    return {"sha8": sha256[:8], "path": relative_path.replace("\\", "/"), "size": size, **screened}


# ---------------------------------------------------------------------------------------------------------------------
# the screen of one document
# ---------------------------------------------------------------------------------------------------------------------
def _class_bucket() -> dict:
    return {"qualifying": 0, "probed": 0, "reach": 0, "reach_clean": 0, "skipped": Counter(), "examples": []}


def _even_pages(page_count: int, cap: int) -> list[int]:
    if page_count <= cap:
        return list(range(page_count))
    if cap <= 1:
        return [0]
    return sorted({round(i * (page_count - 1) / (cap - 1)) for i in range(cap)})


def _code(result: PreparedEdit | PlanRejection | object) -> str:
    if isinstance(result, PreparedEdit):
        return "PREPARED"
    return str(result.reason) if isinstance(result, PlanRejection) else type(result).__name__


def _probe(doc, page, registry, text: str, replacement: str, origin, tier: int):
    return prepare_plan(doc, page, target_text=text, replacement_text=replacement, expected_origin=origin,
                        target_bbox=None, registry=registry, max_tier=tier)


def _leg_check(doc, cap: FontCapability, replacement: str, cache: dict) -> tuple[str, bool | None]:
    """``(leg name or unavailable/error, every replacement char walks to a glyph the leg claims)``."""
    key = cap.font_xref
    if key not in cache:
        try:
            cache[key] = _glyph_leg(doc, key, cap, "simple")
        except IndependentLegUnavailable:
            cache[key] = ("unavailable",)
        except Exception as exc:  # noqa: BLE001 - a leg that cannot be built is reported, not raised
            cache[key] = ("error:" + type(exc).__name__,)
    leg = cache[key]
    if len(leg) == 1:
        return leg[0], None
    name, view, walk, claim, uses_outline, _agrees = leg
    for ch in replacement:
        if ch.isspace():
            continue
        code = ord(ch)
        try:
            gid = walk(code)
            ok = gid is not None and gid != 0 and (not uses_outline or view is None or view.has_outline(gid)) and claim(code, gid, ch)
        except IndependentLegUnavailable:
            ok = False
        if not ok:
            return name, False
    return name, True


def _growth_strip_glyphs(page, show, cap: FontCapability, old: str, new: str, frame) -> int | None:
    """Glyphs already inside the product's grown verify box for ``old -> new`` on this show (``None`` = unmeasurable)."""
    th = show.hscale / 100.0
    if cap.cid is not None:
        old_codes, new_codes = cap.cid.encode_strict(old), cap.cid.encode_strict(new)
        if isinstance(old_codes, CidCapabilityFailure) or isinstance(new_codes, CidCapabilityFailure):
            return None
        adv_old = cap.cid.advance_points(old_codes, show.font_size, show.char_spacing)
        adv_new = cap.cid.advance_points(new_codes, show.font_size, show.char_spacing)
    else:
        adv_old = _advance(cap, old, show.font_size, show.char_spacing, show.word_spacing)
        adv_new = _advance(cap, new, show.font_size, show.char_spacing, show.word_spacing)
    target = map_text_quad_to_visual(page, show.tm, show.ctm, (0.0, -0.35 * show.font_size, adv_old * th, show.font_size), frame=frame)
    grown = _grown_verify_bbox(page, show, target, max(0.0, adv_new - adv_old) * th, frame=frame)
    return count_growth_zone_glyphs(page, target_bbox=target, verify_bbox=grown)


def screen_document(doc: fitz.Document, *, page_cap: int, probe_cap: int, reach_cap: int,
                    max_decoded_bytes: int | None = DEFAULT_MAX_REPLAY_BYTES, f2k_all_pages: bool = True) -> dict:
    """Locate, pre-filter and probe one open document; counts and examples only (no text).

    F30 shapes are read on ``page_cap`` evenly spaced pages.  The F2K shape is rare (nine files on the sampled pages
    of the public trees, and one file whose five reaching shows all sat on skipped pages), so with ``f2k_all_pages``
    every page is replayed and the F2K shape is read everywhere; F30 shapes on an unsampled page are not counted.
    """
    registry = DocumentFontRegistry(doc)
    classes: dict[str, dict] = {}
    pages = Counter()
    font_rejected = Counter()
    leg_cache: dict = {}
    t_probe = 0.0
    n_probe = 0

    def bucket(name: str) -> dict:
        return classes.setdefault(name, _class_bucket())

    sample = set(_even_pages(doc.page_count, page_cap))
    for pi in range(doc.page_count) if f2k_all_pages else sorted(sample):
        in_sample = pi in sample
        page = doc[pi]
        pages["sampled" if in_sample else "f2k_only"] += 1
        if page_has_widgets_or_signatures(doc, page):
            pages["widget"] += 1
            continue
        streams = read_page_streams(doc, page)
        stream_bytes = dict(streams)
        replay = replay_page_streams(streams, max_decoded_bytes=max_decoded_bytes)
        if replay.refusal_reason is not None:
            pages["replay_refused"] += 1
            continue
        if replay.malformed:
            pages["replay_malformed"] += 1
            continue
        frame = None
        drawn: dict[str, set[int]] = {}
        for show in replay.shows:
            if show.font_resource is not None:
                drawn.setdefault(show.font_resource, set()).update(show.decoded_bytes)
        caps: dict[str, FontCapability | None] = {}
        f30_class: dict[str, str | None] = {}
        for show in replay.shows:
            if show.font_resource is None or show.operator not in ("Tj", "TJ"):
                continue
            items = tj_items(stream_bytes.get(show.stream_xref, b""), show) if show.operator == "TJ" else None
            kern = f2k_trailing_kern(items) if show.operator == "TJ" else None
            is_f30_shape = in_sample and (
                show.operator == "Tj" or (items is not None and len(items) == 1 and items[0].kind == "string"))
            if kern is None and not is_f30_shape:
                continue
            if show.font_resource not in caps:
                cap = registry.capability(page, show.font_resource)
                caps[show.font_resource] = cap
                f30_class[show.font_resource] = None if cap is None else classify_f30_font(
                    cap, symbolic=_is_symbolic(doc, cap.font_xref) if not cap.embedded else False)
            cap = caps[show.font_resource]
            if cap is None or cap.tier0_reject_reason is not None:
                # the product refuses the font before any show gate; counted so a file dead at the I8 gate (Differences)
                # or the Type0 chain is visible in the record instead of vanishing
                font_rejected[("F2K" if kern is not None else "F30") + "|" + (cap.tier0_reject_reason if cap else "no_capability")] += 1
                continue
            klass = "F2K" if kern is not None else f30_class[show.font_resource]
            if klass is None:
                continue
            b = bucket(klass)
            if klass == "F30B_no_leg":
                b["qualifying"] += 1  # counted so the owner sees them; never probed (quarantined until I1)
                continue
            if show.render_mode or show.mc_depth:
                b["skipped"]["render_mode_or_marked_content"] += 1
                continue
            if not show.origin_reliable:
                b["skipped"]["untracked_advance"] += 1
                continue
            data = show.decoded_bytes
            if klass == "F2K" and cap.cid is not None:
                decoded = cap.cid.decode_show_bytes(data)
                if isinstance(decoded, CidCapabilityFailure) or not decoded:
                    b["skipped"]["type0_undecodable"] += 1
                    continue
                text, grow = decoded, decoded + decoded[0]
            else:
                # brief v13 section 3.3 admits a one-glyph F2K target (gs871-dvips, bloomberg-nx); the F30 probe needs two
                # bytes because its replacement is the reversed target
                if not printable_target(data, min_len=1 if klass == "F2K" else 2):
                    b["skipped"]["short_or_unprintable"] += 1
                    continue
                text = data.decode("latin-1")
                extra = sorted(c for c in drawn[show.font_resource] if 0x21 <= c <= 0x7E and c not in _QUOTE_OPERATORS)
                grow = text + chr(extra[0]) if extra else None
            if klass == "F2K":
                # a zero trailing kern is still the shape and the product still reaches the fence on it (issue17784,
                # 6/6); it is probed and flagged, never clean, because it can show no compensation of a border kern
                if grow is None:
                    b["skipped"]["font_draws_no_ascii"] += 1
                    continue
                replacement = grow
            else:
                replacement = text[::-1]
                if replacement == text:
                    b["skipped"]["palindrome"] += 1
                    continue
            b["qualifying"] += 1
            if b["probed"] >= probe_cap or b["reach"] >= reach_cap:
                continue
            b["probed"] += 1
            origin = _origin_in_page_space(page, show)
            t = time.perf_counter()
            t0 = _code(_probe(doc, page, registry, text, replacement, origin, 0))
            example = {"page": pi, "seq": show.seq, "n": len(text), "t0": t0}
            if klass == "F2K":
                t1 = _code(_probe(doc, page, registry, text, replacement, origin, 1))
                t_probe += time.perf_counter() - t
                n_probe += 2
                reach = t1 == RejectReason.TJ_KERN_IN_TIER1_RANGE
                example.update(t1=t1, kern=kern,
                               kern_pt=round(-kern / 1000.0 * show.font_size * show.hscale / 100.0, 3))
                if kern == 0.0:
                    example["zero_kern"] = True
                if reach:
                    if frame is None:
                        frame = page_visual_frame(page)
                    try:
                        gz = _growth_strip_glyphs(page, show, cap, text, replacement, frame)
                    except Exception as exc:  # noqa: BLE001 - reported per show, never fatal for the file
                        gz = None
                        example["gz_error"] = type(exc).__name__
                    example["gz_glyphs"] = gz
                clean = reach and kern != 0.0 and example.get("gz_glyphs") == 0
            else:
                t_probe += time.perf_counter() - t
                n_probe += 1
                reach = t0 == "PREPARED"
                # every F30 class: a positive without an independent glyph leg is quarantined at rederive on
                # oracle_assert_glyph_identity (F30W Type1/CFF positives in every batch since I1 opened), so the leg
                # decides reach_clean for F30W too, not only for F30B and F30N
                leg, leg_ok = _leg_check(doc, cap, replacement, leg_cache)
                example.update(leg=leg, leg_ok=leg_ok)
                clean = reach and leg_ok is True
            if reach:
                if b["reach"] == 0:
                    b["examples"] = []  # the refusals kept so far only mattered while the file looked dead
                b["reach"] += 1
                if clean:
                    b["reach_clean"] += 1
                if len(b["examples"]) < 6:
                    b["examples"].append(example)
            elif len(b["examples"]) < 6 and b["reach"] == 0:
                b["examples"].append(example)  # the first refusals, so a dead file shows its code
    for b in classes.values():
        b["skipped"] = dict(b["skipped"])
    return {
        "pages_total": doc.page_count,
        "pages": dict(pages),
        "family": family_token(doc.metadata),
        "classes": classes,
        "font_rejected": dict(font_rejected),
        "probe_ms": round(1000.0 * t_probe / n_probe, 1) if n_probe else None,
    }


# ---------------------------------------------------------------------------------------------------------------------
# the corpus walk and the summary
# ---------------------------------------------------------------------------------------------------------------------
def iter_public_pdfs(root: Path, trees: Iterable[str]) -> Iterable[tuple[Path, str]]:
    for tree in trees:
        base = root / "test_files" / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.pdf")):
            if path.is_file():
                yield path, path.relative_to(root).as_posix()


def screen_file(path: Path, relative_path: str, scratch: Path, **limits) -> dict:
    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    copy = scratch / "w.pdf"
    shutil.copyfile(path, copy)
    try:
        doc = fitz.open(str(copy))
        try:
            screened = screen_document(doc, **limits)
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001 - one unreadable file must not end the sweep
        screened = {"error": type(exc).__name__, "classes": {}, "family": "<none>"}
    return file_record(screened, sha256=sha256, relative_path=relative_path, size=len(data))


def summarise(records: Iterable[Mapping[str, object]], registry: Mapping[str, str]) -> dict:
    """Per class: the reaching files grouped by producer family, which of them are registered, the new families.

    A family is NEW when its product series (:func:`series_of`) is represented by no registered file at all, in any
    class: section 3.0 ``single_family`` counts producer families, and a Distiller 10 file is not a new family while
    Distiller 8 and 9 are registered under other classes.
    """
    records = list(records)
    # a file without /Producer belongs to no family at all (section 3.0 counts producer families), so ``<none>`` is
    # neither a registered series nor a new one; summary_text marks it "(no producer)"
    registered_series = {series_of(str(r["family"])) for r in records if str(r["sha8"]) in registry} - {"<none>"}
    out: dict[str, dict] = {}
    for rec in records:
        classes = rec.get("classes") or {}
        for klass in CLASSES:
            b = classes.get(klass)  # type: ignore[union-attr]
            if not b or not b.get("reach"):
                continue
            entry = out.setdefault(klass, {"families": {}, "registered": {}, "new_families": []})
            entry["families"].setdefault(str(rec["family"]), []).append(str(rec["sha8"]))
            if str(rec["sha8"]) in registry:
                entry["registered"][str(rec["sha8"])] = registry[str(rec["sha8"])]
    for entry in out.values():
        entry["new_families"] = sorted(
            fam for fam in entry["families"] if fam != "<none>" and series_of(fam) not in registered_series)
    return out


def summary_text(summary: Mapping[str, dict], records: Iterable[Mapping[str, object]]) -> str:
    by_sha = {str(r["sha8"]): r for r in records}
    lines = ["# Product-probe screen summary", ""]
    for klass in CLASSES:
        entry = summary.get(klass)
        if not entry:
            lines += [f"## {klass}: no reaching file", ""]
            continue
        lines += [f"## {klass}: {sum(len(v) for v in entry['families'].values())} reaching files in "
                  f"{len(entry['families'])} producer families "
                  f"({len({series_of(f) for f in entry['new_families']})} series with no registered file)", ""]
        lines.append("| family | sha8 | path | registered lineage | qualifying | probed | reach | reach_clean | examples |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for fam in sorted(entry["families"], key=lambda f: (f in entry["new_families"], f), reverse=True):
            shas = sorted(entry["families"][fam], key=lambda s: -int(by_sha[s]["classes"][klass]["reach_clean"]))  # type: ignore[index]
            for sha in shas:
                rec = by_sha[sha]
                b = rec["classes"][klass]  # type: ignore[index]
                ex = "; ".join(
                    f"p{e['page']} s{e['seq']} n={e['n']}" + (f" K={e['kern']}" if "kern" in e else "")
                    + (f" gz={e['gz_glyphs']}" if "gz_glyphs" in e else "")
                    + (f" leg={e['leg']}{'' if e.get('leg_ok') else '!'}" if "leg" in e else "")
                    for e in b["examples"] if (e.get("t1") == RejectReason.TJ_KERN_IN_TIER1_RANGE) or e.get("t0") == "PREPARED")
                tag = " (no producer)" if fam == "<none>" else " (new series)" if fam in entry["new_families"] else ""
                lines.append(f"| {fam}{tag} | {sha} | {rec['path']} | "
                             f"{entry['registered'].get(sha, '-')} | {b['qualifying']} | {b['probed']} | {b['reach']} | "
                             f"{b['reach_clean']} | {ex} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--root", default=str(ROOT), help="checkout that holds test_files/ (default: this repo)")
    parser.add_argument("--tree", action="append", default=None, help="public tree under test_files/ (repeatable)")
    parser.add_argument("--out", required=True, help="per-file JSONL records (appended)")
    parser.add_argument("--summary", default=None, help="markdown summary path")
    parser.add_argument("--registry", default=str(SHA_TABLE), help="tracked public sha table")
    parser.add_argument("--page-cap", type=int, default=15)
    parser.add_argument("--probe-cap", type=int, default=12)
    parser.add_argument("--reach-cap", type=int, default=4)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--nshards", type=int, default=1)
    args = parser.parse_args(argv)
    root = Path(args.root)
    files = list(iter_public_pdfs(root, args.tree or PUBLIC_TREES))[args.shard::args.nshards]
    registry = registry_lineages(json.loads(Path(args.registry).read_text(encoding="utf-8")))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp, out_path.open("a", encoding="utf-8") as out:
        for i, (path, rel) in enumerate(files, 1):
            rec = screen_file(path, rel, Path(tmp), page_cap=args.page_cap, probe_cap=args.probe_cap, reach_cap=args.reach_cap)
            records.append(rec)
            out.write(json.dumps(rec, ensure_ascii=True) + "\n")
            out.flush()
            if i % 50 == 0:
                print(f"{i}/{len(files)} files, {time.perf_counter() - started:.0f}s", flush=True)
    summary = summarise(records, registry)
    text = summary_text(summary, records)
    if args.summary:
        Path(args.summary).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
