"""Read-only show-shape census for glyph-coverage expansion.

Counts per show: operator x string kind x item count x kern class x render mode x
text-state flags x font capability class x font dict shape. Never emits document
text or file names.

Complements scripts/measure_type0_funnel.py (Type0-only funnel) and
scripts/measure_tier_funnel.py (edit-level funnel). The census covers every font
kind and every operator shape the corpus exhibits.

Kern numbers are read via the production TJ re-lexer
``model.text_commit.glyph_boxes.tj_items`` rather than a private lexer copy.
``tj_items`` returns ``None`` when a ``TJ`` array's own byte range does not
reproduce the recorded operand (an integrity failure, not a document
property); that case is counted in ``text_state_flags["tj_relex_failed"]``
and the show is treated as kernless rather than raising into the census.

Output is always JSON on stdout (there is no ``--json`` flag to toggle).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from model.text_commit.cid_fonts import resolve_descendant  # noqa: E402
from model.text_commit.fonts import (  # noqa: E402
    DocumentFontRegistry,
    FontCapability,
    has_custom_differences,
)
from model.text_commit.glyph_boxes import tj_items  # noqa: E402
from model.text_commit.inspect import read_page_streams  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402


def _type0_shape(doc: fitz.Document, font_xref: int) -> str:
    """Summarize Type0 font structure.

    The descendant is read through the production resolver
    (``cid_fonts.resolve_descendant``), which understands every corpus
    spelling of ``/DescendantFonts`` -- ``[N 0 R]``, an indirect array and
    the inline ``[<<...>>]`` form that is the dominant one (256/262 corpus
    fonts). A hand parser here once recognised only the first and reported
    ``desc=?`` for the rest.
    """
    try:
        _enc_kind, enc = doc.xref_get_key(font_xref, "Encoding")
        _desc_xref, desc = resolve_descendant(doc, font_xref)
        sub = "?"
        c2g = "?"
        if desc is not None:
            sub_value = desc.get("Subtype")
            sub = sub_value if isinstance(sub_value, str) else "?"
            c2g = "absent" if "CIDToGIDMap" not in desc else (
                "name" if isinstance(desc["CIDToGIDMap"], str) else "stream"
            )
        return f"enc={enc}|desc={sub}|c2g={c2g}"
    except Exception as exc:  # noqa: BLE001
        return f"unreadable:{type(exc).__name__}"


def _simple_shape(doc: fitz.Document, font_xref: int) -> str:
    """Summarize simple font (Type1/TrueType) structure.

    The ``/Differences`` verdict is the production gate's own
    (``fonts.has_custom_differences``, fail-closed on an unreadable
    encoding), never a second detector that could drift from it.
    """
    try:
        enc_kind, _enc = doc.xref_get_key(font_xref, "Encoding")
        diffs = "diff" if has_custom_differences(doc, font_xref) else (
            "encdict" if enc_kind in ("dict", "xref") else "nodiff"
        )
        fd_kind, fd = doc.xref_get_key(font_xref, "FontDescriptor")
        flags = "?"
        if fd_kind == "xref":
            fx = int(fd.split()[0])
            flags = doc.xref_get_key(fx, "Flags")[1]
        return f"encmode={enc_kind}|{diffs}|flags={flags}"
    except Exception as exc:  # noqa: BLE001
        return f"unreadable:{type(exc).__name__}"


def census(
    path: str,
    page_cap: int | None,
    include_fonts: bool,
    *,
    max_decoded_bytes: int | None = None,
) -> dict:
    """Census a single PDF document.

    ``max_decoded_bytes`` is the replay's decoded-byte budget. The default
    ``None`` is the diagnostic-unbounded path every existing caller relies
    on; an unattended whole-corpus sweep passes the product's own budget so
    one huge page cannot run away with memory. A page the replay refuses has
    no shows, which is not the same as a page without text, so refused and
    malformed pages are counted (``pages_replay_refused`` /
    ``pages_replay_malformed``) instead of passing as empty.
    """
    doc = fitz.open(path)
    try:
        registry = DocumentFontRegistry(doc) if include_fonts else None
        n = doc.page_count
        # ``page_cap`` of 0 or 1 cannot feed the even-spacing formula below
        # (it divides by ``page_cap - 1``, so 1 is a zero divisor and 0
        # would otherwise sample nothing): both collapse to the document's
        # first page -- unless the document itself has zero pages, in
        # which case there is no first page to collapse to and ``doc[0]``
        # would raise ``IndexError``, so the sample stays empty instead.
        if page_cap is not None and page_cap <= 1:
            idxs = [0] if n else []
        elif page_cap is not None and n > page_cap:
            idxs = sorted(
                {round(i * (n - 1) / (page_cap - 1)) for i in range(page_cap)}
            )
        else:
            idxs = list(range(n))
        shape = Counter()
        fonts = Counter()
        kern_class = Counter()
        kern_items = Counter()
        state = Counter()
        modes = Counter()
        font_shapes = Counter()
        # Font xrefs are document-global, so the shape string is derived once
        # per font, not once per show (3-5 dictionary reads each).
        shape_by_font_xref: dict[int, str] = {}
        shows_total = 0
        pages_refused = 0
        pages_malformed = 0
        for pi in idxs:
            page = doc[pi]
            streams = read_page_streams(doc, page)
            replay = replay_page_streams(streams, max_decoded_bytes=max_decoded_bytes)
            if replay.refusal_reason is not None:
                pages_refused += 1
            if replay.malformed:
                pages_malformed += 1
            sd = dict(streams)
            # One capability resolution per distinct resource, not per
            # show (model/text_commit/inspect.py's ``_cid_show_candidates``
            # pattern): a Type0 lookup re-verifies the evidence digest (a
            # full font-program hash) on EVERY call, cache hit or miss, so
            # a resource shared by hundreds of shows on one page must be
            # resolved once, not once per show.
            font_capabilities: dict[str, FontCapability | None] = {}
            for show in replay.shows:
                shows_total += 1
                stream = sd.get(show.stream_xref, b"")
                kerns: list[float] = []
                if show.operator == "TJ":
                    relexed = tj_items(stream, show)
                    if relexed is None:
                        state["tj_relex_failed"] += 1
                    else:
                        kerns = [
                            float(item.value)
                            for item in relexed
                            if item.kind == "kern"
                        ]
                has_kern = bool(kerns)
                array_item_count = show.array_item_count
                # ``0`` is a kern-only array (``[-500] TJ``: a cursor move
                # with no string item); it must not inflate the multi-item
                # kerned bucket the S4/S5 ordering is read from.
                if array_item_count <= 1:
                    item_class = str(array_item_count)
                elif array_item_count <= 3:
                    item_class = "2-3"
                else:
                    item_class = "4+"
                shape[
                    f"{show.operator}|{show.string_kind}|items={item_class}|"
                    f"kern={'y' if has_kern else 'n'}|Tr={show.render_mode}"
                ] += 1
                modes[show.render_mode] += 1
                if has_kern:
                    for k in kerns:
                        a = abs(k)
                        if a >= 200:
                            kern_class["word_gap(>=0.2em)"] += 1
                        elif a >= 50:
                            kern_class["mid(0.05-0.2em)"] += 1
                        else:
                            kern_class["micro(<0.05em)"] += 1
                    kern_items[f"items={item_class}"] += 1
                if show.rise != 0.0:
                    state["rise!=0"] += 1
                if show.hscale != 100.0:
                    state["Tz!=100"] += 1
                if show.mc_depth:
                    state["mc_depth>0"] += 1
                if not show.in_bt:
                    state["outside_BT"] += 1
                if not show.origin_reliable:
                    state["origin_unreliable"] += 1
                if not show.trm_uniform_scaled:
                    state["trm_not_uniform"] += 1
                if show.char_spacing:
                    state["Tc!=0"] += 1
                if show.word_spacing:
                    state["Tw!=0"] += 1
                if registry is not None:
                    cap = None
                    if show.font_resource is not None:
                        if show.font_resource not in font_capabilities:
                            font_capabilities[show.font_resource] = (
                                registry.capability(page, show.font_resource)
                            )
                        cap = font_capabilities[show.font_resource]
                    if cap is None:
                        fonts["<unresolved>"] += 1
                        continue  # the font block is the loop body's tail
                    key = (
                        f"{cap.subtype}|enc={cap.encoding or '-'}|"
                        f"emb={'y' if cap.embedded else 'n'}|"
                        f"reject={cap.tier0_reject_reason or 'ok'}"
                    )
                    fonts[key] += 1
                    if cap.font_xref not in shape_by_font_xref:
                        if cap.subtype == "Type0":
                            shape_by_font_xref[cap.font_xref] = (
                                f"Type0|{_type0_shape(doc, cap.font_xref)}"
                            )
                        elif cap.subtype in ("Type1", "TrueType", "MMType1"):
                            shape_by_font_xref[cap.font_xref] = (
                                f"{cap.subtype}|{_simple_shape(doc, cap.font_xref)}"
                            )
                        else:
                            shape_by_font_xref[cap.font_xref] = cap.subtype
                    font_shapes[shape_by_font_xref[cap.font_xref]] += 1
        result = {
            "pages_total": n,
            "pages_sampled": len(idxs),
            "pages_replay_refused": pages_refused,
            "pages_replay_malformed": pages_malformed,
            "shows_total": shows_total,
            "shape": dict(shape.most_common()),
            "render_modes": {str(k): v for k, v in modes.items()},
            "kern_numbers_by_class": dict(kern_class),
            "kerned_shows_by_item_class": dict(kern_items),
            "text_state_flags": dict(state),
        }
        if include_fonts:
            result["fonts_by_capability"] = dict(fonts.most_common())
            result["font_dict_shapes"] = dict(font_shapes.most_common())
        return result
    finally:
        doc.close()


def _positive_page_count(value: str) -> int:
    """argparse type for ``--pages``: reject anything less than 1."""
    ivalue = int(value)
    if ivalue < 1:
        raise argparse.ArgumentTypeError(
            f"--pages must be >= 1, got {value!r}"
        )
    return ivalue


def main(argv: list[str] | None = None) -> int:
    """Main entry point. Returns 1 if any document recorded an error, else 0."""
    parser = argparse.ArgumentParser(
        description="Census show shapes in PDF documents. Always emits JSON to stdout."
    )
    parser.add_argument(
        "pdfs",
        nargs="+",
        type=str,
        help="PDF file paths to analyze",
    )
    parser.add_argument(
        "--pages",
        type=_positive_page_count,
        default=None,
        help="Sample evenly spaced pages when document has more than N pages (default: all)",
    )
    parser.add_argument(
        "--no-fonts",
        action="store_true",
        help="Skip registry-backed font classification",
    )
    args = parser.parse_args(argv)

    out = {}
    had_error = False
    for doc_index, pdf_path in enumerate(args.pdfs):
        try:
            out[str(doc_index)] = census(
                pdf_path, args.pages, include_fonts=not args.no_fonts
            )
            print(f"done doc {doc_index} shows={out[str(doc_index)]['shows_total']}", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001
            # Never str(exc): an open failure's message carries the file
            # path, which this module's privacy contract forbids emitting.
            out[str(doc_index)] = {"error": type(exc).__name__}
            had_error = True
            print(f"FAIL doc {doc_index}: {type(exc).__name__}", file=sys.stderr, flush=True)

    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
