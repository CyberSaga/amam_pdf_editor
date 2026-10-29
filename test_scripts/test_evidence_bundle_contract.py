"""Contract tests for ``scripts/evidence_bundle.py`` (I0c, SPEC A).

The validator is the arithmetic cross-check half of the Grok-round ingest
(``plans/true-text-frontier-loop.md`` section 2 step 4).  Every honest base
record below is built with this file's own arithmetic, never with the
functions of the module under test, so a base that validates is evidence and
not a tautology.  Every forged shape self-reports ``pass`` and has an honest
twin reporting ``fail`` that validates.  Fixture-bound rules (re-lex against
the original file, frame conversion, ParentTree walk) belong to the rederive
tests.

Machine-path samples are built at run time so the device guard never sees a
literal.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import evidence_bundle as eb  # noqa: E402

STAMP = "20261023_1200_r2"
BRIEF = ROOT / "plans" / "grok-briefs" / "brief-v2.md"
BRIEF_V3 = ROOT / "plans" / "grok-briefs" / "brief-v3.md"
SCHEMA_DIR = ROOT / "scripts" / "evidence_schemas"
PHASES = (
    "probe",
    "structure",
    "growth_zone",
    "render_mupdf",
    "render_poppler",
    "neighbours",
    "glyph_identity",
    "extraction",
    "save_reopen",
)
STATUS_KEYS = (
    "probe_rejected",
    "splice_pass",
    "save_reopen_pass",
    "insufficient_evidence",
    "blocked",
    "out_of_scope_vector",
)
_DEL = object()


# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
def _h(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


def _pdf(slug: str) -> bytes:
    return b"%PDF-1.7\n% fixture " + slug.encode("ascii") + b"\n"


def _cid(class_id: str, slug: str, page: int, show: int, variant: str, k: int = 1) -> str:
    return f"r2-{class_id}-{_h(_pdf(slug))[:8]}-p{page}-s{show}-{variant}{k}"


def _unescape(tok: str) -> str:
    return tok.replace("~1", "/").replace("~0", "~")


def _set(obj, pointer: str, value):
    """Set (or delete, with ``_DEL``) one JSON-pointer location in place."""
    toks = [_unescape(t) for t in pointer.split("/")[1:]]
    cur = obj
    for tok in toks[:-1]:
        cur = cur[int(tok)] if isinstance(cur, list) else cur[tok]
    last = toks[-1]
    if isinstance(cur, list):
        if value is _DEL:
            cur.pop(int(last))
        else:
            cur[int(last)] = value
    elif value is _DEL:
        del cur[last]
    else:
        cur[last] = value


def _patch(case: dict, *edits):
    out = copy.deepcopy(case)
    for pointer, value in edits:
        _set(out, pointer, value)
    return out


def _phase(result: str = "pass", detail: str = "all thresholds met") -> dict:
    return {"result": result, "detail": detail, "evidence": []}


def _union(a, b):
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _ts(*, resource="C2_0", size=132.01, tm=(0.0, -0.06, 0.06, 0.0, 500.0, 100.0), tz=79.9805, wrappers=()):
    return {
        "Tf": {"resource": resource, "size": size},
        "Tm": list(tm),
        "CTM": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        "det_sign": "+",
        "Tz": tz,
        "Tc": 0.0,
        "Tw": 0.0,
        "Ts": 0.0,
        "TL": 0.0,
        "Tr": 0,
        "fill_colour_op": {"op": "g", "operands_raw": "0", "is_pattern": False},
        "stroke_colour_op": {"op": "G", "operands_raw": "0", "is_pattern": False},
        "line_width": None,
        "extgstate_names": [],
        "wrapper_stack": list(wrappers),
        "q_depth": 1,
        "in_bt": True,
        "origin_user": [500.0, 100.0],
        "origin_reliable": True,
    }


def _tm(trm: float, rotation: int) -> tuple:
    if rotation == 270:
        return (0.0, -trm, trm, 0.0, 500.0, 100.0)
    return (trm, 0.0, 0.0, trm, 100.0, 688.0)


def _wrapper(**over) -> dict:
    base = {
        "kind": "BDC",
        "tag": "OC",
        "class_slug": "oc_layer_visible_default",
        "props_kind": "name",
        "props_name": "MC0",
        "props_keys": [],
        "structelem_keys": None,
        "stream_xref": 120,
        "start": 4900,
        "end": 5100,
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------
# neighbours records and summary (test-side arithmetic)
# --------------------------------------------------------------------------
def _glyph_box(k: int) -> list[float]:
    return [100.0 + 10.0 * k, 10.0, 108.0 + 10.0 * k, 22.0]


def _untouched(idx_before, idx_after, x: float) -> dict:
    box = [x, 10.0, x + 8.0, 22.0]
    return {
        "trace_index_before": idx_before,
        "trace_index_after": idx_after,
        "show_index": 1,
        "char_index_before": 0,
        "char_index_after": 0,
        "gid_before": 5,
        "gid_after": 5,
        "origin_before": [x, 20.0],
        "origin_after": [x, 20.0],
        "bbox_before": list(box),
        "bbox_after": list(box),
        "origin_delta_pt": 0.0,
        "role": "untouched",
        "is_space": False,
        "ink_checked": True,
        "ink_changed_px_6x": 0,
        "overlap": False,
        "halo_shadowed": False,
        "ink_after_px_6x": None,
    }


def _target_rec(k: int, n_old: int, n_new: int, replacement: str) -> dict:
    i = 2
    has_b, has_a = k < n_old, k < n_new
    box = _glyph_box(k)
    org = [100.0 + 10.0 * k, 20.0]
    space = replacement[k].isspace() if has_a else False
    return {
        "trace_index_before": i + k if has_b else None,
        "trace_index_after": i + k if has_a else None,
        "show_index": 0,
        "char_index_before": k if has_b else None,
        "char_index_after": k if has_a else None,
        "gid_before": 100 + k if has_b else None,
        "gid_after": 200 + k if has_a else None,
        "origin_before": list(org) if has_b else None,
        "origin_after": list(org) if has_a else None,
        "bbox_before": list(box) if has_b else None,
        "bbox_after": list(box) if has_a else None,
        "origin_delta_pt": 0.0 if (has_a and has_b) else None,
        "role": "target",
        "is_space": space,
        "ink_checked": False,
        "ink_changed_px_6x": None,
        "overlap": False,
        "halo_shadowed": False,
        "ink_after_px_6x": 40 if (has_a and not space) else None,
    }


def _records(n_old: int, n_new: int, replacement: str) -> list[dict]:
    recs = [_untouched(0, 0, 20.0), _untouched(1, 1, 40.0)]
    recs += [_target_rec(k, n_old, n_new, replacement) for k in range(max(n_old, n_new))]
    shift = n_new - n_old
    recs.append(_untouched(2 + n_old, 2 + n_old + shift, 400.0))
    recs.append(_untouched(3 + n_old, 3 + n_old + shift, 420.0))
    return recs


def _summary(recs: list[dict], n_old: int, n_new: int, cid: str) -> dict:
    other = [r for r in recs if r["role"] != "target"]
    tgt = [r for r in recs if r["role"] == "target"]
    inshow = [r["origin_delta_pt"] for r in other if r["role"] == "inshow_successor"]
    untouched = [r["origin_delta_pt"] for r in other if r["role"] == "untouched"]
    first = min((r for r in tgt if r["trace_index_before"] is not None), key=lambda r: r["trace_index_before"])
    return {
        "pairing_rule": "texttrace_order_origin_match/v1",
        "glyphs_total": len(other),
        "glyphs_checked": sum(1 for r in other if r["ink_checked"] or r["halo_shadowed"] or r["overlap"]),
        "unpaired_glyphs": 0,
        "target_glyphs_before": n_old,
        "target_glyphs_after": n_new,
        "target_origin_delta_pt": first["origin_delta_pt"],
        "untouched_max_origin_delta_pt": max(untouched) if untouched else None,
        "inshow_successor_max_origin_delta_pt": max(inshow) if inshow else None,
        "gid_mismatches": sum(1 for r in other if r["gid_before"] != r["gid_after"]),
        "ink_mismatches": sum(1 for r in other if r["ink_checked"] and (r["ink_changed_px_6x"] or 0) > 0),
        "overlap_glyphs": sum(1 for r in other if r["overlap"] and not r["is_space"]),
        "halo_shadowed_glyphs": sum(1 for r in other if r["halo_shadowed"]),
        "records_file": f"cases/{cid}/neighbours.json",
    }


# --------------------------------------------------------------------------
# glyph identity, probe, growth, render, save blocks
# --------------------------------------------------------------------------
def _glyphs(replacement: str, font_kind: str, *, leg: str, selected_by: str) -> list[dict]:
    out = []
    for i, ch in enumerate(replacement):
        code = f"{0x100 + i:04X}" if font_kind == "type0" else f"{ord(ch):02X}"
        gid = 200 + i
        out.append(
            {
                "index": i,
                "char": ch,
                "is_space": ch.isspace(),
                "code_bytes_hex": code,
                "gid_after": gid,
                "has_outline": not ch.isspace(),
                "consistency": {"show_seq": 3, "char_index": i, "gid": gid, "selected_by": selected_by},
                "gid_equals_consistency": True,
                "independent_leg": {"kind": leg, "value": ch, "equals_char": True, "gid": gid, "gid_equals_after": True},
            }
        )
    return out


def _codes(glyphs: list[dict]) -> str:
    return "".join(g["code_bytes_hex"] for g in glyphs)


def _prepared(*, rep_start, rep_end, op_start, op_end, adv_old, adv_new, kern, verify, background, stream_xref=120):
    return {
        "stream_xref": stream_xref,
        "replacement_start": rep_start,
        "replacement_end": rep_end,
        "binding_op_start": op_start,
        "binding_op_end": op_end,
        "font_xref": 77,
        "source_advance": adv_old,
        "replacement_advance": adv_new,
        "kern_adjustment": kern,
        "verify_bbox_page": verify,
        "background_bbox_page": background,
    }


def _probe_result(result="prepared", tier=1, reason=None, detail=None, prepared=None) -> dict:
    return {"result": result, "tier": tier, "reason": reason, "detail": detail, "exception_type": None, "prepared": prepared}


def _growth_off() -> dict:
    return {
        "applicable": False,
        "direction": None,
        "region_visual": None,
        "region_dict": None,
        "background_bbox_visual": None,
        "background_rgb": None,
        "probe_regions_px_96dpi": None,
        "probe_regions_failed": None,
        "raster_proof": None,
        "gate_detail": None,
        "before_glyph_bboxes_intersecting": None,
        "before_drawings_intersecting_bbox": None,
        "before_drawings_not_provably_clear": None,
        "stroke_proof": None,
        "before_images_intersecting": None,
        "sh_operator_present": None,
        "files": [],
    }


def _growth_on(target, verify, background, *, drawings=1, files=("render-growthstrip-before-6x.png",)) -> dict:
    strip = [target[2], min(target[1], verify[1]), verify[2], max(target[3], verify[3])]
    return {
        "applicable": True,
        "direction": "right",
        "region_visual": strip,
        "region_dict": list(strip),
        "background_bbox_visual": list(background),
        "background_rgb": [1.0, 1.0, 1.0],
        "probe_regions_px_96dpi": [[10, 10, 20, 20]],
        "probe_regions_failed": 0,
        "raster_proof": "pass",
        "gate_detail": None,
        "before_glyph_bboxes_intersecting": 0,
        "before_drawings_intersecting_bbox": drawings,
        "before_drawings_not_provably_clear": 0,
        "stroke_proof": "clear" if drawings else "not_needed",
        "before_images_intersecting": 0,
        "sh_operator_present": False,
        "files": list(files),
    }


def _renderer(version: str, prefix: str) -> dict:
    return {
        "status": "pass",
        "version": version,
        "crop_zoom": 6.0,
        "target_changed_px": 120,
        "fullpage_zoom": 2.0,
        "nontarget_changed_px": 0,
        "control_rerender_changed_px": 0,
        "files": [f"render-{prefix}-before-6x.png", f"render-{prefix}-after-6x.png"],
    }


def _halo(target, after) -> float:
    u = _union(target, after)
    return (u[2] - u[0] + 6.0) * (u[3] - u[1] + 6.0)


def _save_ok() -> dict:
    return {
        "method": "saveIncr then fresh handle",
        "page_count_equal": True,
        "new_objects_subset_xref": True,
        "reopened_text_at_target_equals_replacement": True,
        "text_state_equal": True,
        "glyph_identity_equal": True,
        "source_sha256_unchanged": True,
    }


def _advance(*, adv_old, adv_new, tfs, tz, source, function, trm, uu, char_old, char_new, spaces, k_written, k_sum=0.0, tol=None, dropped=()):
    th = tz / 100.0
    disp = adv_old - adv_new
    hand = 1000.0 * (adv_new - adv_old) / tfs
    eng = -1000.0 * disp / tfs
    if tol is None:
        tol = max(1e-9 * tfs, 1e-9) if source != "face" else max(1e-3 * tfs, 1e-4)
    has_k = k_written is not None
    return {
        "K_written": k_written,
        "K_sum": k_sum if has_k else None,
        "K_disp_engine": eng if has_k else None,
        "K_disp_hand": hand if has_k else None,
        "abs_diff_written_vs_sum_engine": abs(k_written - (k_sum + eng)) if has_k else None,
        "abs_diff_engine_hand": abs(eng - hand) if has_k else None,
        "displacement": disp,
        "adv_old_text_space": adv_old,
        "adv_new_text_space": adv_new,
        "growth_pt": max(0.0, adv_new - adv_old) * th * trm * uu,
        "advance_tolerance": tol,
        "Tfs": tfs,
        "Th": th,
        "Tc": 0.0,
        "Tw": 0.0,
        "char_count_old": char_old,
        "char_count_new": char_new,
        "space_count": spaces,
        "advance_source": source,
        "advance_function": function,
        "internal_kerns_dropped": list(dropped),
        "border_kerns_byte_identical": None,
    }


def _mutation(*, path, method_id, splice_kind, new_text: bytes, old: bytes | None, start, end_old, advance, variable="replacement operand"):
    return {
        "path": path,
        "method_id": method_id,
        "variable_changed": variable,
        "splice_kind": splice_kind,
        "changes": [
            {
                "stream_xref": 120,
                "start": start,
                "end_old": end_old,
                "end_new": start + len(new_text),
                "token_aligned": True,
                "old_operand_bytes_hex": old.hex().upper() if old is not None else None,
                "old_operand_sha256": _h(old if old is not None else b"old operand"),
                "new_operand_bytes_hex": new_text.hex().upper(),
                "new_operand_token_kinds": ["STRING"],
                "old_stream_sha256": _h("old stream"),
                "new_stream_sha256": _h("new stream"),
            }
        ],
        "advance": advance,
        "other_xrefs_changed_live": [],
        "other_xrefs_changed_semantic": [],
        "other_xrefs_reserialized": [],
        "wrapper_bytes_unchanged": None,
        "new_objects_after_save": [],
        "new_objects_all_xref": True,
        "saved_with": "saveIncr",
        "output_sha256": _h("output"),
    }


# --------------------------------------------------------------------------
# case assembly
# --------------------------------------------------------------------------
SYN_BUILDER = {
    "callable": "test_scripts.type0_fixture_builder.build_identity_h_fixture",
    "kwargs": {"text": "你好世界", "rotate": 270, "tail_text": "後綴"},
}
CALIBRATION_ORIG_T0 = "空調冰水管線系統圖(1)"
CALIBRATION_REPL_T0 = "空調冰水管線系統圖(4)"
CALIBRATION_NEG = "空調冰水管路系統圖(1)"


def _source(slug, provenance, *, rel=None, lineage=None, rotation=270, builder=None, producer="[PLACEHOLDER_1]", creator="[PLACEHOLDER_2]"):
    sha = _h(_pdf(slug))
    return {
        "slug": slug,
        "relative_path": rel,
        "provenance": provenance,
        "sha256": sha,
        "sha256_after_run": sha,
        "before_pdf_sha256": sha,
        "lineage_id": lineage or slug,
        "lineage_reason": "single document",
        "producer_family": "fixture-family",
        "single_producer_family": True,
        "producer": producer,
        "creator": creator,
        "page_count": 23,
        "page_rotation": rotation,
        "synthetic_builder": copy.deepcopy(builder),
    }


def _corpus(page, show, orig, repl, *, public, font_resource, basefont, font_kind, outcome, reason, tier, tj):
    return {
        "page_index": page,
        "show_seq": show,
        "original": orig if public else None,
        "original_sha256": _h(orig),
        "replacement": repl,
        "replacement_sha256": _h(repl),
        "font_resource": font_resource,
        "basefont": basefont,
        "font_kind": font_kind,
        "expected_outcome": outcome,
        "expected_reason": reason,
        "expected_tier": tier,
        "expected_tj_compensation": tj,
    }


def _target(*, op_start, op_end, operator, string_kind, array_count, font_kind, T, A, V, trm, uu, decode, raw_after, stream_xref=120):
    type0 = font_kind == "type0"
    return {
        "stream_xref": stream_xref,
        "op_start": op_start,
        "op_end": op_end,
        "operator": operator,
        "string_kind": string_kind,
        "array_item_count": array_count,
        "item_range": None,
        "byte_range_in_item": None,
        "font_xref": 77,
        "basefont_raw": "ArialMT" if type0 else "Helvetica",
        "font_subtype": "Type0" if type0 else "TrueType",
        "font_embedding": "FontFile2",
        "font_file3_subtype": None,
        "encoding": "Identity-H" if type0 else "WinAnsiEncoding",
        "has_differences": False,
        "tounicode": "present",
        "symbolic_flag": None if type0 else False,
        "descendant_subtype": "CIDFontType2" if type0 else None,
        "origin_recipe": "texttrace_chars0_x_quarter_turn/v1",
        "expected_origin_visual": [100.0, 312.0],
        "target_bbox_visual": T,
        "target_bbox_raw": [100.0, 10.0, 218.0, 22.0],
        "after_bbox_visual": A,
        "after_bbox_raw": raw_after,
        "verify_bbox_visual": V,
        "trm_scale": trm,
        "user_unit": uu,
        "no_source_match_subclass": None,
        "replacement_provenance": "chars_already_drawn_by_font",
        "source_decode": decode,
    }


def _tail(cid: str, renders: list[str]) -> dict:
    files = [f"cases/{cid}/{n}" for n in ("case_record.json", "neighbours.json", "text_state.json", "mutation.json")]
    files += [f"cases/{cid}/{r}" for r in renders]
    files.append(f"candidates/{cid}/before.pdf")
    return {
        "observation": "Recorded as measured on the isolated copy.",
        "hypotheses": [],
        "next_check": "none",
        "attempts": [],
        "peel_chain": [],
        "code_revision": {"git_head": "a1d9a22" + "0" * 33, "tracked_diff_empty": True, "dirty": True, "dirty_diff_id": "b" * 64},
        "tool_versions": {
            "python": "3.11.9",
            "pymupdf": "1.27.1",
            "mupdf": "1.27.0",
            "numpy": "2.0.0",
            "pillow": "11.0.0",
            "fonttools": "4.55.0",
            "pdftoppm": "pdftoppm 25.07.0",
        },
        "command": ".venv\\Scripts\\python.exe -B _evidence_pilot\\" + STAMP + "\\run_pilot.py --plan-sha x --phase all",
        "timestamp": "2026-10-23T12:00:00+08:00",
        "artifacts": {"dir": f"cases/{cid}/", "files": files},
        "limits": [],
        "redaction": {
            "applied": True,
            "entries": [{"json_pointer": "/source/producer", "placeholder": "[PLACEHOLDER_1]", "sha256_utf8": _h("producer")}],
            "scan": {"client_strings_left": 0, "machine_paths_left": 0, "language_warnings": 0},
        },
    }


def _wrap_up(cid, *, class_id, kind, variant_slug, status, calibration_ref, pre_registered, parts, renders):
    case = {
        "schema_version": "true-text-case/2",
        "brief_revision": 2,
        "case_id": cid,
        "join_key": variant_slug,
        "class_id": class_id,
        "subclass": None,
        "kind": kind,
        "status": status,
        "product_success": False,
        "accepted_for_code": False,
        "calibration_ref": calibration_ref,
        "methods_plan_sha256": "0" * 64,
        "pre_registered": pre_registered,
    }
    case.update(parts)
    case.update(_tail(cid, renders))
    return case


RENDERS_FULL = [
    "render-mupdf-before-6x.png",
    "render-mupdf-after-6x.png",
    "render-poppler-before-6x.png",
    "render-poppler-after-6x.png",
]


def _mut_case(
    *,
    class_id,
    kind,
    variant,
    slug,
    page,
    show,
    provenance,
    rel,
    orig,
    repl,
    font_kind,
    font_resource,
    basefont,
    path,
    method_id,
    splice_kind,
    operator,
    new_op: bytes,
    old_op: bytes | None,
    op_start,
    op_end,
    change_end_old,
    adv_old,
    adv_new,
    tfs,
    tz,
    trm,
    uu,
    rotation,
    source_kind,
    k_written,
    tier,
    T,
    A,
    V,
    BG,
    wrappers=(),
    status="save_reopen_pass",
    calibration_ref="not_applicable",
    outcome="commit_tier1",
    tj=None,
    builder=None,
    lineage=None,
    leg="cid_tounicode",
    selected_by="cid_tounicode",
    probe_t1=None,
    probe_t0=None,
    commit=None,
    decode=None,
    expected_reason=None,
):
    cid = _cid(class_id, slug, page, show, variant)
    public = provenance in ("public", "synthetic")
    glyphs = _glyphs(repl, font_kind, leg=leg, selected_by=selected_by)
    n_old, n_new = len(orig), len(repl)
    recs = _records(n_old, n_new, repl)
    nb = _summary(recs, n_old, n_new, cid)
    raw_after = [100.0, 10.0, 108.0 + 10.0 * (n_new - 1), 22.0]
    advance = _advance(
        adv_old=adv_old,
        adv_new=adv_new,
        tfs=tfs,
        tz=tz,
        source=source_kind,
        function=("IdentityHCidCapability.advance_points" if font_kind == "type0" else "plan._advance/FontCapability.string_width"),
        trm=trm,
        uu=uu,
        char_old=n_old,
        char_new=n_new,
        spaces=sum(1 for ch in repl if ch.isspace()),
        k_written=k_written,
    )
    mutation = _mutation(
        path=path,
        method_id=method_id,
        splice_kind=splice_kind,
        new_text=new_op,
        old=old_op,
        start=op_start,
        end_old=change_end_old,
        advance=advance,
    )
    if wrappers:
        mutation["wrapper_bytes_unchanged"] = True  # brief 5.2: true is a structure pass condition (null is only vacuous without wrappers)
    applicable = (tier == 1 and adv_new > adv_old) if path == "product_commit" else (adv_new - adv_old > advance["advance_tolerance"])
    growth = _growth_on(T, V, BG) if applicable else _growth_off()
    if probe_t1 is None:
        prep = _prepared(
            rep_start=op_start,
            rep_end=change_end_old,
            op_start=op_start,
            op_end=op_end,
            adv_old=adv_old,
            adv_new=adv_new,
            kern=k_written,
            verify=V if (tier == 1 and applicable) else None,
            background=BG if (tier == 1 and applicable) else None,
        )
        probe_t1 = _probe_result("prepared", tier, prepared=prep)
        probe_t0 = _probe_result("prepared", 0, prepared=prep) if tier == 0 else _probe_result(
            "rejected", None, "advance_mismatch", "replacement advance differs from the source advance"
        )
        commit = {"attempted": True, "status": "committed", "tier": tier, "font_actions": []}
    parts = {
        "source": _source(slug, provenance, rel=rel, lineage=lineage, rotation=rotation, builder=builder),
        "corpus_case": _corpus(
            page, show, orig, repl, public=public, font_resource=font_resource, basefont=basefont, font_kind=font_kind,
            outcome=outcome, reason=expected_reason, tier=tier if path == "product_commit" else None, tj=tj,
        ),
        "target": _target(
            op_start=op_start, op_end=op_end, operator=operator, string_kind="hex" if font_kind == "type0" else "literal",
            array_count=1, font_kind=font_kind, T=T, A=A, V=V if applicable else None, trm=trm, uu=uu, decode=decode, raw_after=raw_after,
        ),
        "probe": {
            "engine": "TieredCommitEngine",
            "handle": "fresh_no_texttrace",
            "max_tier_1": probe_t1,
            "max_tier_0": probe_t0,
            "binding_matches_target": True if probe_t1["prepared"] else None,
            "commit": commit,
        },
        "text_state": {
            "before": _ts(size=tfs, tz=tz, wrappers=wrappers, tm=_tm(trm, rotation)),
            "after": _ts(size=tfs, tz=tz, wrappers=wrappers, tm=_tm(trm, rotation)),
            "target_equal": True,
            "nontarget_shows_equal": True,
            "show_count_before": 300,
            "show_count_after": 300,
            "operator_count_before": 5000,
            "operator_count_after": 5000,
        },
        "mutation": mutation,
        "growth_zone": growth,
        "neighbours": nb,
        "glyph_identity": glyphs,
        "extraction": {"after_text_at_target": repl, "equals_replacement": True, "old_text_remains_at_target": False, "nontarget_text_changes": 0},
        "render": {
            "mask_rule": "union(target_bbox_visual, after_bbox_visual) +-3pt, compared at 2x",
            "halo_area_pt2": _halo(T, A),
            "mupdf": _renderer("MuPDF 1.27.0", "mupdf"),
            "poppler": _renderer("pdftoppm 25.07.0", "poppler"),
            "live_vs_reopened_changed_px": 0,
        },
        "save_reopen": _save_ok(),
        "phases": {name: _phase() for name in PHASES},
    }
    # the raw before box is the union of the role=target records' bbox_before (it used to be a fixed, inconsistent [100,10,218,22])
    parts["target"]["target_bbox_raw"] = _bbox_union_of([r["bbox_before"] for r in recs if r["role"] == "target" and r["bbox_before"]])
    parts["phases"]["growth_zone"] = _phase("pass", "no ink growth" if not applicable else "all three gates clear")
    renders = list(RENDERS_FULL) + (["render-growthstrip-before-6x.png"] if applicable else [])
    case = _wrap_up(
        cid, class_id=class_id, kind=kind, variant_slug=f"{slug}/p{page}/show{show}", status=status,
        calibration_ref=calibration_ref, pre_registered=True, parts=parts, renders=renders,
    )
    case["_records"] = recs
    return case


def _ctrl_pos_t1() -> dict:
    tfs, tz, trm = 132.01, 79.9805, 0.06
    adv_old = 625.0
    adv_new = adv_old + 333.0 * tfs / 1000.0
    g = (adv_new - adv_old) * (tz / 100.0) * trm
    T = [100.0, 300.0, 130.0, 312.0]
    A = [100.0, 300.0, 130.0 + g, 312.0]
    V = [100.0, 300.0, 130.0 + g + 2e-5, 312.0]
    BG = [100.0, 299.0, 130.0, 313.0]
    glyphs = _glyphs("Drawing Title", "type0", leg="cid_tounicode", selected_by="cid_tounicode")
    new_op = ("[<" + _codes(glyphs) + "> 333.000000] TJ").encode("ascii")
    return _mut_case(
        class_id="CTRL_POS_T1", kind="control", variant="ctrl", slug="hvac", page=4, show=26, provenance="proprietary", rel=None,
        orig="Drawing List", repl="Drawing Title", font_kind="type0", font_resource="C2_0", basefont="ArialMT",
        path="product_commit", method_id="M2_COMMIT", splice_kind="whole_operator", operator="Tj", new_op=new_op, old_op=None,
        op_start=5000, op_end=5053, change_end_old=5053, adv_old=adv_old, adv_new=adv_new, tfs=tfs, tz=tz, trm=trm, uu=1.0,
        rotation=270, source_kind="W", k_written=333.0, tier=1, T=T, A=A, V=V, BG=BG, outcome="commit_tier1", tj=333.0,
        decode={"latin1": None, "latin1_sha256": _h("Drawing List"), "independent": None, "independent_sha256": _h("Drawing List"), "leg": "cid_tounicode", "agrees": True},
    )


def _tier0_hvac() -> dict:
    glyphs = _glyphs(CALIBRATION_REPL_T0, "type0", leg="cid_tounicode", selected_by="cid_tounicode")
    new_op = ("<" + _codes(glyphs) + ">").encode("ascii")
    T = [100.0, 300.0, 130.0, 312.0]
    return _mut_case(
        class_id="CTRL_POS_T0", kind="control", variant="ctrl", slug="hvac", page=4, show=11, provenance="proprietary", rel=None,
        orig=CALIBRATION_ORIG_T0, repl=CALIBRATION_REPL_T0, font_kind="type0", font_resource="C2_1", basefont="PMingLiU",
        path="product_commit", method_id="M2_COMMIT", splice_kind="string_token", operator="Tj", new_op=new_op, old_op=None,
        op_start=5000, op_end=5053, change_end_old=5050, adv_old=500.0, adv_new=500.0, tfs=100.0, tz=100.0, trm=0.06, uu=1.0,
        rotation=270, source_kind="W", k_written=None, tier=0, T=T, A=list(T), V=None, BG=None, outcome="commit_tier0",
        wrappers=[_wrapper()],
        decode={"latin1": None, "latin1_sha256": _h(CALIBRATION_ORIG_T0), "independent": None, "independent_sha256": _h(CALIBRATION_ORIG_T0), "leg": "cid_tounicode", "agrees": True},
    )


def _null_case(*, class_id, kind, variant, slug, page, show, provenance, orig, repl, status, calibration_ref, probe_t1, probe_t0, builder=None, rel=None, expected_reason=None, rotation=270):
    cid = _cid(class_id, slug, page, show, variant)
    public = provenance in ("public", "synthetic")
    nb = _summary_null(cid)
    parts = {
        "source": _source(slug, provenance, rel=rel, rotation=rotation, builder=builder),
        "corpus_case": _corpus(
            page, show, orig, repl, public=public, font_resource="C2_1", basefont="PMingLiU", font_kind="type0",
            outcome="refuse", reason=expected_reason, tier=None, tj=None,
        ),
        "target": _target(
            op_start=5000, op_end=5053, operator="Tj", string_kind="hex", array_count=1, font_kind="type0",
            T=[100.0, 300.0, 130.0, 312.0], A=None, V=None, trm=0.06, uu=1.0,
            decode={"latin1": None, "latin1_sha256": _h(orig), "independent": None, "independent_sha256": _h(orig), "leg": "cid_tounicode", "agrees": True},
            raw_after=None,
        ),
        "probe": {
            "engine": "TieredCommitEngine",
            "handle": "fresh_no_texttrace",
            "max_tier_1": probe_t1,
            "max_tier_0": probe_t0,
            "binding_matches_target": None,
            "commit": {"attempted": False, "status": None, "tier": None, "font_actions": []},
        },
        "text_state": {
            "before": _ts(size=100.0, tz=100.0),
            "after": None,
            "target_equal": None,
            "nontarget_shows_equal": None,
            "show_count_before": 300,
            "show_count_after": None,
            "operator_count_before": 5000,
            "operator_count_after": None,
        },
        "mutation": None,
        "growth_zone": _growth_off(),
        "neighbours": nb,
        "glyph_identity": [],
        "extraction": {"after_text_at_target": None, "equals_replacement": None, "old_text_remains_at_target": None, "nontarget_text_changes": None},
        "render": {
            "mask_rule": "union(target_bbox_visual, after_bbox_visual) +-3pt, compared at 2x",
            "halo_area_pt2": None,
            "mupdf": _renderer_null(),
            "poppler": _renderer_null(),
            "live_vs_reopened_changed_px": None,
        },
        "save_reopen": {
            "method": "not_run",
            "page_count_equal": None,
            "new_objects_subset_xref": None,
            "reopened_text_at_target_equals_replacement": None,
            "text_state_equal": None,
            "glyph_identity_equal": None,
            "source_sha256_unchanged": True,
        },
        "phases": {name: _phase("not_run", "no mutation") for name in PHASES},
    }
    parts["phases"]["probe"] = _phase("pass", "both probes rejected with a reason and a detail")
    return _wrap_up(
        cid, class_id=class_id, kind=kind, variant_slug=f"{slug}/p{page}/show{show}", status=status,
        calibration_ref=calibration_ref, pre_registered=True, parts=parts, renders=[],
    )


def _summary_null(cid: str) -> dict:
    return {
        "pairing_rule": "texttrace_order_origin_match/v1",
        "glyphs_total": 0,
        "glyphs_checked": 0,
        "unpaired_glyphs": 0,
        "target_glyphs_before": 0,
        "target_glyphs_after": None,
        "target_origin_delta_pt": None,
        "untouched_max_origin_delta_pt": None,
        "inshow_successor_max_origin_delta_pt": None,
        "gid_mismatches": 0,
        "ink_mismatches": 0,
        "overlap_glyphs": 0,
        "halo_shadowed_glyphs": 0,
        "records_file": f"cases/{cid}/neighbours.json",
    }


def _renderer_null() -> dict:
    return {
        "status": "not_run",
        "version": None,
        "crop_zoom": 6.0,
        "target_changed_px": None,
        "fullpage_zoom": 2.0,
        "nontarget_changed_px": None,
        "control_rerender_changed_px": None,
        "files": [],
    }


def _ctrl_neg() -> dict:
    rej = "no CID maps to a replacement character"
    return _null_case(
        class_id="CTRL_NEG", kind="control", variant="ctrl", slug="hvac", page=4, show=11, provenance="proprietary",
        orig=CALIBRATION_ORIG_T0, repl=CALIBRATION_NEG, status="probe_rejected", calibration_ref="not_applicable",
        probe_t1=_probe_result("rejected", None, "type0_unicode_unmapped", rej),
        probe_t0=_probe_result("rejected", None, "type0_unicode_unmapped", rej),
        expected_reason="type0_unicode_unmapped",
    )


def _ekern_experiment() -> dict:
    T = [100.0, 688.0, 111.0, 700.0]
    A = [100.0, 688.0, 117.0, 700.0]
    BG = [100.0, 683.8, 111.0, 700.0]
    return _mut_case(
        class_id="F30B", kind="positive", variant="grow", slug="multicolumn", page=0, show=3, provenance="public",
        rel="test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf", orig="ab", repl="abc", font_kind="simple",
        font_resource="F1", basefont="CMR10", path="experiment", method_id="E_KERN", splice_kind="whole_operator",
        operator="Tj", new_op=b"[(abc) 500.000000] TJ", old_op=b"(ab) Tj", op_start=5000, op_end=5007, change_end_old=5007,
        adv_old=11.0, adv_new=17.0, tfs=12.0, tz=100.0, trm=1.0, uu=1.0, rotation=0, source_kind="Widths", k_written=500.0,
        tier=1, T=T, A=A, V=list(A), BG=BG, outcome="refuse", calibration_ref="pass", leg="glyph_name_agl", selected_by="glyph_name",
        probe_t1=_probe_result("rejected", None, "font_face_unavailable", "embedded face could not be loaded"),
        probe_t0=_probe_result("rejected", None, "advance_mismatch", "replacement advance differs from the source advance"),
        commit={"attempted": False, "status": None, "tier": None, "font_actions": []},
        decode={"latin1": "ab", "latin1_sha256": _h("ab"), "independent": "ab", "independent_sha256": _h("ab"), "leg": "glyph_name_agl", "agrees": True},
        lineage="multicolumn",
    )


def _canary_growth_hvac() -> dict:
    tfs, tz, trm = 97.023, 100.0, 0.06
    adv_old = 400.0
    adv_new = adv_old + tfs
    g = (adv_new - adv_old) * (tz / 100.0) * trm
    T = [100.0, 300.0, 130.0, 312.0]
    A = [100.0, 300.0, 130.0 + g, 312.0]
    glyphs = _glyphs("ABCDE", "type0", leg="cid_tounicode", selected_by="cid_tounicode")
    new_op = ("[<" + _codes(glyphs) + "> 1000.000000] TJ").encode("ascii")
    case = _mut_case(
        class_id="CANARY_GROWTH", kind="canary", variant="can", slug="hvac", page=4, show=161, provenance="proprietary", rel=None,
        orig="ABCD", repl="ABCDE", font_kind="type0", font_resource="C2_2", basefont="ArialMT", path="canary", method_id="CANARY",
        splice_kind="canary", operator="Tj", new_op=new_op, old_op=None, op_start=5000, op_end=5030, change_end_old=5030,
        adv_old=adv_old, adv_new=adv_new, tfs=tfs, tz=tz, trm=trm, uu=1.0, rotation=270, source_kind="W", k_written=1000.0,
        tier=1, T=T, A=A, V=list(A), BG=[100.0, 299.0, 130.0, 313.0], status="probe_rejected",
        probe_t1=_probe_result("rejected", None, "growth_region_not_blank", "glyphs: 1 character(s) already occupy the growth zone"),
        probe_t0=_probe_result("rejected", None, "advance_mismatch", "replacement advance differs from the source advance"),
        commit={"attempted": False, "status": None, "tier": None, "font_actions": []},
        decode={"latin1": None, "latin1_sha256": _h("ABCD"), "independent": None, "independent_sha256": _h("ABCD"), "leg": "cid_tounicode", "agrees": True},
    )
    recs = case.pop("_records")
    # the first successor glyph sits inside the grown run
    recs[-2] = _untouched(2 + 4, 2 + 5, 144.0)
    recs[-2]["overlap"] = True
    recs[-2]["ink_checked"] = False
    recs[-2]["ink_changed_px_6x"] = None
    case["_records"] = recs
    case["neighbours"] = _summary(recs, 4, 5, case["case_id"])
    case["growth_zone"].update(
        {
            "raster_proof": "fail",
            "probe_regions_failed": 1,
            "gate_detail": "glyphs: 1 character(s) already occupy the growth zone",
            "before_glyph_bboxes_intersecting": 1,
        }
    )
    case["phases"]["growth_zone"] = _phase("fail", "a non-blank glyph occupies the growth zone")
    case["phases"]["neighbours"] = _phase("fail", "one neighbouring glyph is covered by the new run")
    return case


def _retarget(case: dict, *, slug=None, page=None, show=None, class_id=None, kind=None, variant=None, k=1) -> dict:
    old_cid = case["case_id"]
    old_sha = case["source"]["sha256"]
    slug = slug or case["source"]["slug"]
    page = case["corpus_case"]["page_index"] if page is None else page
    show = case["corpus_case"]["show_seq"] if show is None else show
    class_id = class_id or case["class_id"]
    variant = variant or old_cid.rsplit("-", 1)[1].rstrip("0123456789")
    new_sha = _h(_pdf(slug))
    new_cid = _cid(class_id, slug, page, show, variant, k)
    text = json.dumps(case, ensure_ascii=False).replace(old_cid, new_cid).replace(old_sha, new_sha)
    out = json.loads(text)
    out["case_id"] = new_cid
    out["join_key"] = f"{slug}/p{page}/show{show}"
    out["class_id"] = class_id
    out["source"]["slug"] = slug
    out["corpus_case"]["page_index"] = page
    out["corpus_case"]["show_seq"] = show
    if kind:
        out["kind"] = kind
    return out


# --------------------------------------------------------------------------
# more bases: synthetic controls, F3 splits, negatives, unsaved canary
# --------------------------------------------------------------------------
def _ctrl_syn_t0() -> dict:
    repl = "世界你好"
    glyphs = _glyphs(repl, "type0", leg="cid_tounicode", selected_by="cid_tounicode")
    new_op = ("<" + _codes(glyphs) + ">").encode("ascii")
    T = [100.0, 300.0, 124.0, 312.0]
    return _mut_case(
        class_id="CTRL_SYN_T0", kind="control", variant="ctrl", slug="ctrl-syn", page=0, show=0, provenance="synthetic", rel=None,
        orig="你好世界", repl=repl, font_kind="type0", font_resource="F1", basefont="Fixture",
        path="product_commit", method_id="M2_COMMIT", splice_kind="string_token", operator="Tj", new_op=new_op, old_op=None,
        op_start=5000, op_end=5015, change_end_old=5012, adv_old=48.0, adv_new=48.0, tfs=12.0, tz=100.0, trm=1.0, uu=1.0,
        rotation=270, source_kind="W", k_written=None, tier=0, T=T, A=list(T), V=None, BG=None, outcome="commit_tier0",
        builder=SYN_BUILDER,
        decode={"latin1": None, "latin1_sha256": _h("x"), "independent": None, "independent_sha256": _h("x"), "leg": "cid_tounicode", "agrees": True},
    )


def _ctrl_syn_t1() -> dict:
    return _null_case(
        class_id="CTRL_SYN_T1", kind="control", variant="ctrl", slug="ctrl-syn", page=0, show=1, provenance="synthetic",
        orig="你好世界", repl="你好世界吧", status="probe_rejected", calibration_ref="not_applicable",
        probe_t1=_probe_result("rejected", None, "growth_region_not_blank", "glyphs: 1 character(s) already occupy the growth zone"),
        probe_t0=_probe_result("rejected", None, "advance_mismatch", "replacement advance differs from the source advance"),
        builder=SYN_BUILDER, expected_reason="growth_region_not_blank",
    )


def _canary_growth_syn() -> dict:
    case = _retarget(_canary_growth_hvac(), slug="ctrl-syn", page=0, show=0, variant="can")
    case["source"].update(
        {"provenance": "synthetic", "relative_path": None, "synthetic_builder": copy.deepcopy(SYN_BUILDER), "page_rotation": 270}
    )
    case["corpus_case"]["original"] = "ABCD"
    return case


def _canary_growth_uncaught() -> dict:
    """The hvac growth canary after its glyph neighbour moved away: nothing fails."""
    case = _canary_growth_hvac()
    recs = case["_records"]
    recs[-2] = _untouched(2 + 4, 2 + 5, 400.0)
    case["neighbours"] = _summary(recs, 4, 5, case["case_id"])
    case["growth_zone"].update(
        {"raster_proof": "pass", "probe_regions_failed": 0, "gate_detail": None, "before_glyph_bboxes_intersecting": 0}
    )
    for name in ("growth_zone", "neighbours"):
        case["phases"][name] = _phase()
    case["status"] = "save_reopen_pass"
    return case


def _canary_unsaved() -> dict:
    case = _retarget(_tier0_hvac(), class_id="CANARY_UNSAVED", kind="canary", variant="can")
    case["mutation"].update({"path": "canary", "method_id": "CANARY", "splice_kind": "canary"})
    case["extraction"] = {
        "after_text_at_target": CALIBRATION_ORIG_T0,
        "equals_replacement": False,
        "old_text_remains_at_target": True,
        "nontarget_text_changes": 0,
    }
    case["save_reopen"]["reopened_text_at_target_equals_replacement"] = False
    case["phases"]["extraction"] = _phase("fail", "the target still reads as the original text")
    case["phases"]["save_reopen"] = _phase("fail", "the reopened file lacks the commit")
    case["status"] = "insufficient_evidence"
    return case


def _negative_annots() -> dict:
    return _null_case(
        class_id="F30B", kind="negative", variant="neg", slug="annotated-pdf", page=0, show=0, provenance="public",
        rel="test_files/sample-files-main/annotated_pdf.pdf", orig="ab", repl="abc", status="probe_rejected",
        calibration_ref="pass",
        probe_t1=_probe_result("rejected", None, "annotations_not_indirect", "3 of 3 listed /Annots entries are inline dictionaries (no xref)"),
        probe_t0=_probe_result("rejected", None, "annotations_not_indirect", "3 of 3 listed /Annots entries are inline dictionaries (no xref)"),
        expected_reason="annotations_not_indirect", rotation=0,
    )


def _census_f1() -> dict:
    case = _retarget(_ctrl_neg(), slug="office-report", page=2, show=7, class_id="F1", kind="census", variant="cen")
    case["calibration_ref"] = "pass"
    return case


def _fragment(inarray: bool) -> dict:
    """F3 public experiment: replace bytes [1, 3) of the item ``abcd`` by ``XY``."""
    T = [100.0, 688.0, 114.0, 700.0]
    if inarray:
        old, new, operator, kind, count = b"(abcd)", b"(a)(XY)(d)", "TJ", "array", 1
    else:
        old, new, operator, kind, count = b"(abcd) Tj", b"[(a) (XY) (d)] TJ", "Tj", "literal", 1
    case = _mut_case(
        class_id="F3", kind="positive", variant="eq", slug="minimal-document", page=0, show=7, provenance="public",
        rel="test_files/sample-files-main/001-trivial/minimal-document.pdf", orig="bc", repl="XY", font_kind="simple",
        font_resource="F1", basefont="CMR10", path="experiment", method_id="E_F3S", splice_kind="fragment_split",
        operator=operator, new_op=new, old_op=old, op_start=5000, op_end=5000 + len(old) + (3 if inarray else 0),
        change_end_old=5000 + len(old), adv_old=14.0, adv_new=14.0, tfs=12.0, tz=100.0, trm=1.0, uu=1.0, rotation=0,
        source_kind="Widths", k_written=None, tier=1, T=T, A=list(T), V=None, BG=None, outcome="refuse", calibration_ref="pass",
        leg="glyph_name_agl", selected_by="glyph_name",
        probe_t1=_probe_result("rejected", None, "no_source_match", "target text is a substring of one string item"),
        probe_t0=_probe_result("rejected", None, "no_source_match", "target text is a substring of one string item"),
        commit={"attempted": False, "status": None, "tier": None, "font_actions": []},
        decode={"latin1": "bc", "latin1_sha256": _h("bc"), "independent": "bc", "independent_sha256": _h("bc"), "leg": "glyph_name_agl", "agrees": True},
    )
    case["target"]["operator"] = operator
    case["target"]["string_kind"] = kind
    case["target"]["array_item_count"] = count
    case["target"]["byte_range_in_item"] = [1, 3]
    if inarray:
        case["mutation"]["advance"]["border_kerns_byte_identical"] = True
    return case


# --------------------------------------------------------------------------
# the R0 pack: the six controls and every brief 2.2 canary (completeness is a rule since fix round 1)
# --------------------------------------------------------------------------
def _as_canary(case: dict, class_id: str) -> dict:
    out = _retarget(case, class_id=class_id, kind="canary", variant="can")
    out["mutation"].update({"path": "canary", "method_id": "CANARY", "splice_kind": "canary"})
    out["status"] = "insufficient_evidence"
    return out


def _ctrl_det() -> dict:
    return _retarget(_tier0_hvac(), class_id="CTRL_DET", kind="control", variant="ctrl")


def _canary_ksign() -> dict:
    case = _as_canary(_ctrl_pos_t1(), "CANARY_KSIGN")
    change = case["mutation"]["changes"][0]
    flipped = bytes.fromhex(change["new_operand_bytes_hex"]).replace(b"333.000000", b"-333.000000")
    change["new_operand_bytes_hex"] = flipped.hex().upper()
    change["end_new"] = change["start"] + len(flipped)
    adv = case["mutation"]["advance"]
    adv["K_written"] = -333.0
    adv["abs_diff_written_vs_sum_engine"] = abs(-333.0 - (adv["K_sum"] + adv["K_disp_engine"]))
    case["phases"]["structure"] = _phase("fail", "K_written differs from K_sum + K_disp_engine")
    return case


def _canary_tc() -> dict:
    case = _as_canary(_tier0_hvac(), "CANARY_TC")
    case["text_state"]["operator_count_after"] = 5002
    case["phases"]["structure"] = _phase("fail", "the operator count changed")
    return case


def _wrong_gid(case: dict) -> None:
    leg = case["glyph_identity"][0]["independent_leg"]
    leg["gid"] = 999
    leg["gid_equals_after"] = False
    case["phases"]["glyph_identity"] = _phase("fail", "the independent leg names another glyph")


def _canary_font() -> dict:
    case = _as_canary(_tier0_hvac(), "CANARY_FONT")
    case["text_state"]["operator_count_after"] = 5002
    case["phases"]["structure"] = _phase("fail", "the operator count changed")
    _wrong_gid(case)
    return case


def _canary_wrongglyph() -> dict:
    case = _as_canary(_tier0_hvac(), "CANARY_WRONGGLYPH")
    _wrong_gid(case)
    case["extraction"].update({"after_text_at_target": CALIBRATION_ORIG_T0, "equals_replacement": False})
    case["phases"]["extraction"] = _phase("fail", "the target reads another character")
    return case


def _canary_ink() -> dict:
    case = _as_canary(_tier0_hvac(), "CANARY_INK")
    case["text_state"]["operator_count_after"] = 5001
    case["phases"]["structure"] = _phase("fail", "the operator count changed")
    for name in ("mupdf", "poppler"):
        case["render"][name]["nontarget_changed_px"] = 7
        case["render"][name]["status"] = "fail"
        case["phases"][f"render_{name}"] = _phase("fail", "pixels changed outside the target")
    case["_records"][2]["ink_after_px_6x"] = 0
    case["phases"]["neighbours"] = _phase("fail", "the target shows no ink after the edit")
    return case


BASES = {
    "t1": _ctrl_pos_t1,
    "t0": _tier0_hvac,
    "neg": _ctrl_neg,
    "ek": _ekern_experiment,
    "gh": _canary_growth_hvac,
    "gs": _canary_growth_syn,
    "st0": _ctrl_syn_t0,
    "st1": _ctrl_syn_t1,
    "unsaved": _canary_unsaved,
    "annots": _negative_annots,
    "f1": _census_f1,
    "split": lambda: _fragment(False),
    "inarr": lambda: _fragment(True),
    "uncaught": _canary_growth_uncaught,
    "det": _ctrl_det,
    "ksign": _canary_ksign,
    "tc": _canary_tc,
    "font": _canary_font,
    "wrong": _canary_wrongglyph,
    "ink": _canary_ink,
}

R0_KEYS = ["t1", "t0", "neg", "det", "st0", "st1", "ksign", "tc", "font", "unsaved", "wrong", "ink", "gh", "gs"]


def _nonpublic(case: dict) -> dict:
    """Turn a public base into a proprietary row (redaction nulls applied)."""
    out = _patch(
        case,
        ("/source/provenance", "proprietary"),
        ("/source/relative_path", None),
        ("/corpus_case/original", None),
        ("/target/source_decode/latin1", None),
        ("/target/source_decode/independent", None),
    )
    for change in out["mutation"]["changes"] if out["mutation"] else []:
        change["old_operand_bytes_hex"] = None
    return out


# --------------------------------------------------------------------------
# batch machinery: plan, hand-written parent, writer
# --------------------------------------------------------------------------
MUST_FAIL = {
    "CANARY_KSIGN": ["structure"],
    "CANARY_TC": ["structure"],
    "CANARY_FONT": ["structure", "glyph_identity"],
    "CANARY_UNSAVED": ["save_reopen", "extraction"],
    "CANARY_WRONGGLYPH": ["glyph_identity", "extraction"],
    "CANARY_INK": ["render_mupdf", "render_poppler", "neighbours"],
    "CANARY_GROWTH": ["growth_zone", "neighbours"],
}


def _variant(case: dict) -> str:
    return re.sub(r"[0-9]+$", "", case["case_id"].rsplit("-", 1)[1])


def _plan_object(cases: list[dict]) -> dict:
    return {
        "pre_registration": "true-text-plan/2",
        "cases": [
            {
                "class_id": c["class_id"],
                "slug": c["source"]["slug"],
                "page_index": c["corpus_case"]["page_index"],
                "show_seq": c["corpus_case"]["show_seq"],
                "variant": _variant(c),
                "method_id": c["mutation"]["method_id"] if c["mutation"] else None,
                "expected_reason": c["corpus_case"]["expected_reason"],
                "hypotheses": [],
            }
            for c in cases
        ],
    }


def _plan_text(plan: dict) -> str:
    return "# Plan\n\nPre-registered before any copy was touched.\n\n```json\n" + json.dumps(plan, indent=1) + "\n```\n"


def _default_calibration(cases: list[dict], status: str = "pass") -> dict:
    controls, canaries, sites = {}, {}, []
    for c in cases:
        if c["kind"] == "control":
            controls[c["class_id"]] = {"expected": "brief 2.1 row", "observed": "recorded row", "ok": True}
        elif c["kind"] == "canary":
            same = [d for d in cases if d["class_id"] == c["class_id"]]
            key = c["class_id"] if len(same) == 1 else f"{c['class_id']}@{c['join_key']}"
            growth = c["class_id"] == "CANARY_GROWTH"
            canaries[key] = {
                "site": c["join_key"],
                "must_fail_phases": list(MUST_FAIL.get(c["class_id"], [])),
                "failed_phases": [p for p in PHASES if c["phases"][p]["result"] == "fail"],
                "caught": True,
                "legs": {
                    "geometry_overlap": True if growth else None,
                    "growth_zone_glyph": True if growth else None,
                    "growth_zone_raster": True if growth else None,
                    "neighbours_overlap": True if growth else None,
                },
                "missed_legs": [],
            }
            if growth:
                sites.append({"site": c["join_key"], "page_rotation": c["source"]["page_rotation"], "show_seq": c["corpus_case"]["show_seq"]})
    return {"status": status, "attempts": 1, "controls": controls, "canaries": canaries, "growth_canary_sites": sites}


def _tier_of(c: dict) -> int:
    if c["mutation"]["path"] == "product_commit":
        return c["probe"]["commit"]["tier"]
    adv = c["mutation"]["advance"]
    adv = adv[0] if isinstance(adv, list) else adv
    return 1 if adv is not None and adv["K_written"] is not None else 0


def _parent_literal(cases: list[dict], plan_sha: str, calibration: dict, name: str = STAMP) -> dict:
    """The parent summary a faithful run would write (test-side arithmetic)."""
    by = dict.fromkeys(STATUS_KEYS, 0)
    per: dict[str, dict] = {}
    for c in cases:
        if c["status"] in by:
            by[c["status"]] += 1
        if c["kind"] not in ("positive", "negative", "census"):
            continue
        e = per.setdefault(
            c["class_id"],
            {"cases": 0, "positives": 0, "negatives": 0, "lin": set(), "fam": set(), "t0": 0, "t1": 0, "by": dict.fromkeys(STATUS_KEYS, 0)},
        )
        e["cases"] += 1
        e["positives"] += c["kind"] == "positive"
        e["negatives"] += c["kind"] == "negative"
        if c["source"]["provenance"] != "synthetic":
            e["lin"].add(c["source"]["lineage_id"])
            e["fam"].add(c["source"]["producer_family"])
        if c["status"] in e["by"]:
            e["by"][c["status"]] += 1
        if c["kind"] == "positive" and c["status"] == "save_reopen_pass":
            e["t1" if _tier_of(c) == 1 else "t0"] += 1
    per_class = {
        cls: {
            "cases": e["cases"],
            "positives": e["positives"],
            "negatives": e["negatives"],
            "distinct_lineages": len(e["lin"]),
            "distinct_producer_families": len(e["fam"]),
            "tier0_positive_pass": e["t0"],
            "tier1_positive_pass": e["t1"],
            "by_status": e["by"],
            "class_state_proposal": "needs_second_case" if (e["t0"] + e["t1"]) else "open",
            "remeasure_pending": True,
        }
        for cls, e in per.items()
    }
    first = cases[0]
    return {
        "schema": "true-text-parent/2",
        "stamp": name,
        "brief_revision": max(c["brief_revision"] for c in cases),  # the newest row; a mixed batch is a mismatch
        "code_revision": copy.deepcopy(first["code_revision"]),
        "tool_versions": copy.deepcopy(first["tool_versions"]),
        "methods_plan_sha256": plan_sha,
        "calibration": calibration,
        "cases_total": len(cases),
        "by_status": by,
        "per_class": per_class,
        "product_findings": [],
        "counts_derived_from": "cases.json",
        "product_source_changes": 0,
        "pytest_runs": 0,
        "originals_untouched": True,
    }


def _op(fn):
    """Edit value: rewrite the first change's operand text with ``fn``."""

    def make(case: dict) -> str:
        text = bytes.fromhex(case["mutation"]["changes"][0]["new_operand_bytes_hex"]).decode("latin-1")
        return fn(text).encode("latin-1").hex().upper()

    return make


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _with_r0(cases: list[dict]) -> list[dict]:
    """A batch that carries a counted (frontier) row also carries the whole R0 pack: calibration comes first."""
    if not any(c["kind"] in ("positive", "negative", "census") for c in cases):
        return cases
    have = {c["case_id"] for c in cases}
    return cases + [c for c in (BASES[k]() for k in R0_KEYS) if c["case_id"] not in have]


def _make_batch(
    tmp_path: Path,
    bases: list[dict],
    *,
    edits=(),
    parent_edits=(),
    plan_edits=(),
    files=None,
    delete=(),
    done_edit=None,
    calibration=None,
    name=STAMP,
    r0=True,
    late_edits=(),
) -> Path:
    cases = _with_r0(copy.deepcopy(bases)) if r0 else copy.deepcopy(bases)
    records_by_index = []
    for case in cases:
        records_by_index.append(case.pop("_records", None))
    plan = _plan_object(cases)
    for pointer, value in plan_edits:
        _set(plan, pointer, value)
    plan_text = _plan_text(plan)
    plan_sha = _h(plan_text.encode("utf-8"))
    for case in cases:
        case["methods_plan_sha256"] = plan_sha
    for entry in edits:
        idx, pointer, value = entry if len(entry) == 3 else (0, *entry)
        if pointer.startswith("@records"):
            rest = pointer[len("@records"):]
            if rest == "":
                records_by_index[idx] = value(records_by_index[idx]) if callable(value) else value
            else:
                _set(records_by_index[idx], rest, value)
        else:
            _set(cases[idx], pointer, value(cases[idx]) if callable(value) else value)
    root = tmp_path / name
    root.mkdir(parents=True)
    calib = calibration if calibration is not None else _default_calibration(cases)
    parent = _parent_literal(cases, plan_sha, calib, name)
    for pointer, value in parent_edits:
        _set(parent, pointer, value)
    names = [(c["case_id"], c["source"]["slug"]) for c in cases]  # the writer below needs the honest names
    for idx, pointer, value in late_edits:  # malformed shapes the test-side parent arithmetic could not digest
        _set(cases[idx], pointer, value)
    first_id = cases[0]["case_id"]
    (root / "METHODS_AND_EVIDENCE_PLAN.md").write_bytes(plan_text.encode("utf-8"))
    (root / "run_pilot.py").write_bytes(b"print('pilot')\n")  # bytes, not write_text: Windows would write CRLF and the v5 runner sha is of the bytes
    (root / "INVENTORY.md").write_text("# Inventory\n\nNumbers only.\n", encoding="utf-8")
    (root / "README.md").write_text("# Batch\n\nStatus counts only.\n", encoding="utf-8")
    _write_json(root / "CROSS_BATCH_DELTA.json", {"classes": {}})
    _write_json(root / "REDACTION.json", {"entries": []})
    _write_json(root / "VALIDATION.self.json", {"validator": "absent"})
    _write_json(root / "cases.json", cases)
    for case, recs, (case_name, slug_name) in zip(cases, records_by_index, names, strict=True):
        cdir = root / "cases" / case_name
        _write_json(cdir / "case_record.json", case)
        _write_json(cdir / "neighbours.json", recs if recs is not None else [])
        _write_json(cdir / "text_state.json", case["text_state"])
        _write_json(cdir / "mutation.json", case["mutation"])
        pdf_dir = root / "candidates" / case_name
        pdf_dir.mkdir(parents=True, exist_ok=True)
        (pdf_dir / "before.pdf").write_bytes(_pdf(slug_name))
        for rel in case["artifacts"]["files"]:
            if rel.endswith(".png"):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes(b"\x89PNG\r\n\x1a\nfake")
    _write_json(root / "PARENT_SUMMARY.json", parent)
    parent_bytes = (root / "PARENT_SUMMARY.json").read_bytes()
    done = {"stamp": name, "case_count": parent["cases_total"], "parent_summary_sha256": _h(parent_bytes)}
    if done_edit:
        for pointer, value in done_edit:
            _set(done, pointer, value)
    _write_json(root / "DONE.json", done)
    for rel, data in (files or {}).items():
        target = root / rel.replace("{cid}", first_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    for rel in delete:
        (root / rel.replace("{cid}", first_id)).unlink()
    return root


def _validate(tmp_path: Path, bases: list[dict], *, denylist=None, **kw) -> dict:
    root = _make_batch(tmp_path, bases, **kw)
    return eb.validate_batch(root, denylist=denylist)


def _hits(report: dict) -> set[tuple[str, str]]:
    return {(v["code"], v["pointer"]) for v in report["violations"]}


def _show(report: dict) -> str:
    return "\n".join(f"{v['code']} {v['file']} {v['pointer']} {v['detail']}" for v in report["violations"])


# --------------------------------------------------------------------------
# guards (written first): honest bases validate, helpers match the product
# --------------------------------------------------------------------------
def _resolve(key):
    return BASES[key]() if isinstance(key, str) else key()


def _expand(keys) -> list[dict]:
    out: list[dict] = []
    for key in keys:
        got = _resolve(key)
        out.extend(got if isinstance(got, list) else [got])
    return out


GUARD_SETS = {
    "t1": ["t1"],
    "t0": ["t0"],
    "neg": ["neg"],
    "ek": ["ek"],
    "st0": ["st0"],
    "st1": ["st1"],
    "unsaved": ["unsaved"],
    "annots": ["annots"],
    "f1_census": ["f1"],
    "fragment_split_tj": ["split"],
    "fragment_split_in_array": ["inarr"],
    "growth_canaries": ["gh", "gs"],
    "full_batch": ["t1", "t0", "neg", "ek"],
    "r0_pack": R0_KEYS,
    "r0_pack_with_a_frontier_row": [*R0_KEYS, "ek"],
}


@pytest.mark.parametrize("name", sorted(GUARD_SETS))
def test_honest_base_validates(tmp_path, name):
    report = _validate(tmp_path, _expand(GUARD_SETS[name]))
    assert report["violations"] == [], _show(report)
    assert report["ok"] is True


def test_full_batch_parent_matches_the_hand_written_literal(tmp_path):
    cases = [_resolve(k) for k in GUARD_SETS["full_batch"]]
    for case in cases:
        case.pop("_records", None)
    statuses = {c["case_id"]: c["status"] for c in cases}
    got = eb.recompute_parent_summary(cases, statuses)
    assert got["cases_total"] == 4
    assert got["by_status"] == {
        "probe_rejected": 1,
        "splice_pass": 0,
        "save_reopen_pass": 3,
        "insufficient_evidence": 0,
        "blocked": 0,
        "out_of_scope_vector": 0,
    }
    assert got["per_class"] == {
        "F30B": {
            "cases": 1,
            "positives": 1,
            "negatives": 0,
            "distinct_lineages": 1,
            "distinct_producer_families": 1,
            "tier0_positive_pass": 0,
            "tier1_positive_pass": 1,
            "by_status": {
                "probe_rejected": 0,
                "splice_pass": 0,
                "save_reopen_pass": 1,
                "insufficient_evidence": 0,
                "blocked": 0,
                "out_of_scope_vector": 0,
            },
            "class_state_proposal": "needs_second_case",
            "remeasure_pending": True,
        }
    }
    assert got["product_findings"] == []


def test_unverifiable_never_fails_the_batch(tmp_path):
    report = _validate(tmp_path, [_resolve("t1")])
    assert report["ok"] is True
    assert report["unverifiable"], "fixture-bound rules must be listed, never passed silently"
    assert {u["code"] for u in report["unverifiable"]} >= {"region_dict", "background_bbox"}


def test_case_schema_is_the_brief_block_verbatim():
    """The shared case schema is the CURRENT brief's section 5.1 block (contract true-text-case/2, brief_revision 2 to 8).

    Older briefs stay untouched as history; ``test_v12_the_case_schema_is_the_brief_v4_block_and_v3_is_the_schema_before_v4``
    and ``test_v5_the_case_schema_is_the_brief_v5_block_and_v4_is_the_schema_before_v5`` pin each older block to the
    schema minus the later additions.
    """
    schema = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    assert _case_block(ROOT / "plans" / "grok-briefs" / "brief-v8.md") == schema


def test_every_schema_file_loads_inside_the_subset():
    for name in ("case", "plan", "parent"):
        schema = eb.load_schema(SCHEMA_DIR / f"true_text_{name}.v2.schema.json")
        assert schema["type"] == "object"


def test_module_imports_without_fitz():
    code = "import scripts.evidence_bundle, sys; assert 'fitz' not in sys.modules, sorted(m for m in sys.modules if 'fitz' in m)"
    done = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_growth_strip_matches_product():
    pytest.importorskip("fitz")
    from model.text_commit import verify

    boxes = [
        ((0.0, 0.0, 10.0, 10.0), (0.0, 0.0, 15.0, 10.0)),
        ((0.0, 0.0, 10.0, 10.0), (0.0, 0.0, 10.0, 10.0)),
        ((5.0, 5.0, 10.0, 10.0), (0.0, 5.0, 10.0, 16.0)),
        ((0.0, 0.0, 10.0, 10.0), (0.0, -4.0, 10.0, 10.0)),
        ((0.0, 0.0, 10.0, 10.0), (-3.0, 0.0, 10.0, 10.0)),
        ((0.0, 0.0, 10.0, 10.0), (1.0, 1.0, 9.0, 9.0)),
    ]
    for target, other in boxes:
        theirs = verify._growth_zone_rect(target, other)
        ours = eb._growth_strip(target, other)
        if theirs is None:
            assert ours is None, (target, other)
        else:
            assert ours == pytest.approx(tuple(theirs)), (target, other)


def test_wrapper_slugs_match_marked_content():
    pytest.importorskip("fitz")
    from model.text_commit import marked_content

    live = {v for k, v in vars(marked_content).items() if k.startswith("CLASS_") and isinstance(v, str)}
    assert live == set(eb.WRAPPER_SLUGS)


def test_calibration_strings_are_the_loaders():
    """The validator's whitelist IS the loader's tuple (acc no longer carries the originals, so there is no source
    text to grep).  The loader's own tests pin the five against the manifest digests."""
    from test_scripts import true_text_corpus

    assert eb.CALIBRATION_STRINGS is true_text_corpus.CALIBRATION_STRINGS
    assert len(eb.CALIBRATION_STRINGS) == 5 and all(isinstance(s, str) and s for s in eb.CALIBRATION_STRINGS)


def test_reject_reason_values_are_importable_stdlib_side():
    assert "type0_unicode_unmapped" in eb.REJECT_REASON_VALUES
    assert "growth_region_not_blank" in eb.REJECT_REASON_VALUES


# --------------------------------------------------------------------------
# schema subset validator
# --------------------------------------------------------------------------
def _vcodes(violations) -> set[tuple[str, str]]:
    return {(v.code, v.pointer) for v in violations}


def test_subset_const_is_type_aware():
    schema = {"type": "object", "properties": {"a": {"const": False}}}
    assert eb.validate_instance({"a": False}, schema) == []
    assert ("schema_const", "/a") in _vcodes(eb.validate_instance({"a": 0}, schema))
    assert ("schema_const", "/a") in _vcodes(eb.validate_instance({"a": True}, schema))


def test_subset_enum_distinguishes_true_from_one():
    schema = {"type": "object", "properties": {"a": {"enum": [0, 1, None]}}}
    assert eb.validate_instance({"a": 1}, schema) == []
    assert eb.validate_instance({"a": None}, schema) == []
    assert ("schema_enum", "/a") in _vcodes(eb.validate_instance({"a": True}, schema))


def test_subset_bool_is_never_a_number():
    assert ("schema_type", "") in _vcodes(eb.validate_instance(True, {"type": "integer"}))
    assert ("schema_type", "") in _vcodes(eb.validate_instance(True, {"type": "number"}))
    assert eb.validate_instance(1, {"type": "number"}) == []


def test_subset_ref_miss_is_reported():
    schema = {"type": "object", "properties": {"a": {"$ref": "#/$defs/nope"}}, "$defs": {}}
    assert ("schema_ref_unresolved", "/a") in _vcodes(eb.validate_instance({"a": 1}, schema))


def test_subset_unknown_keyword_is_a_load_error(tmp_path):
    path = tmp_path / "bad.schema.json"
    path.write_text(json.dumps({"type": "object", "oneOf": [{"type": "string"}]}), encoding="utf-8")
    with pytest.raises(eb.SchemaSubsetError):
        eb.load_schema(path)


def test_subset_anyof_descends_into_the_one_branch_that_admits_the_type():
    case = _resolve("ek")
    case.pop("_records")
    case["mutation"]["changes"][0]["start"] = "x"
    schema = eb.load_schema(SCHEMA_DIR / "true_text_case.v2.schema.json")
    assert ("schema_type", "/mutation/changes/0/start") in _vcodes(eb.validate_instance(case, schema))


def test_legacy_v1_record_shape_is_rejected():
    legacy_keys = [
        "case_id", "status", "source_sha256", "page_index", "text_object_fingerprint", "text_class", "original_text",
        "replacement_text", "mutation_type", "hypothesis", "proposed_edit_method", "preconditions", "changed_objects",
        "evidence_refs", "failed_alternatives", "unverified_items", "next_job", "signature_expected", "seq",
    ]
    assert len(legacy_keys) == 19
    record = dict.fromkeys(legacy_keys, "x")
    schema = eb.load_schema(SCHEMA_DIR / "true_text_case.v2.schema.json")
    hits = _vcodes(eb.validate_instance(record, schema))
    assert ("schema_required", "/schema_version") in hits
    assert ("schema_additional", "/" + eb._esc("seq")) in hits


# --------------------------------------------------------------------------
# must-reject table.  Each row self-reports pass where the numbers say fail
# (the validator recomputes) or breaks a cross-field rule.  Expected entries
# are (code, pointer) or (code, pointer, file-suffix); pointer None = any.
# --------------------------------------------------------------------------
def _none_k() -> list:
    return [
        ("/mutation/advance/K_written", None),
        ("/mutation/advance/K_sum", None),
        ("/mutation/advance/K_disp_engine", None),
        ("/mutation/advance/K_disp_hand", None),
        ("/mutation/advance/abs_diff_written_vs_sum_engine", None),
        ("/mutation/advance/abs_diff_engine_hand", None),
    ]


def _equal_width_edits() -> list:
    return [
        ("/mutation/advance/adv_new_text_space", 11.0),
        ("/mutation/advance/displacement", 0.0),
        ("/mutation/advance/growth_pt", 0.0),
        *_none_k(),
        ("/growth_zone", _growth_off()),
    ]


def _poppler_blocked() -> list:
    return [
        ("/phases/render_poppler/result", "blocked"),
        ("/render/poppler/status", "blocked"),
        ("/render/poppler/version", None),
        ("/render/poppler/target_changed_px", None),
        ("/render/poppler/nontarget_changed_px", None),
        ("/render/poppler/control_rerender_changed_px", None),
    ]


def _winpath() -> str:
    return "see " + "C:" + "\\" + "Users" + "\\" + "x" + "\\" + "f"


def _geotopo_pair() -> list:
    a = _patch(_retarget(_ekern_experiment(), slug="geotopo"), ("/source/lineage_id", "geotopo"))
    b = _patch(_retarget(_ekern_experiment(), slug="geotopo-komprimiert"), ("/source/lineage_id", "geotopo-own"))
    return [a, b]


def _s26_growth() -> list:
    return [_retarget(_canary_growth_hvac(), show=26), _canary_growth_syn()]


def _s185_growth() -> list:
    return [_retarget(_canary_growth_hvac(), show=185), _canary_growth_syn()]


def _nonpublic_ek() -> list:
    return [_nonpublic(_ekern_experiment())]


TJ_SPLIT = "[(a) (XY) (d)] TJ"
OP = "/mutation/changes/0/new_operand_bytes_hex"
K = "/mutation/advance/K_written"
LEG0 = "/glyph_identity/0/independent_leg"
NULL_CONS0 = [("/glyph_identity/0/consistency", None), ("/glyph_identity/0/gid_equals_consistency", None)]

# (id, bases, edits, expected, extra kwargs)
REJECTS = [
    # V9 (brief change (m)): a null consistency recomputes glyph_identity from (a) and the leg, so a recorded not_run is a lie
    ("null_consistency_recorded_not_run", ["st0"], [*NULL_CONS0, ("/phases/glyph_identity/result", "not_run")], [("phase_result_mismatch", "/phases/glyph_identity/result")], {}),
    ("null_consistency_note_lies", [lambda: _rev3(_ctrl_syn_t0())], [("/glyph_identity/0/consistency", None), ("/glyph_identity/0/gid_equals_consistency", True)], [("glyph_note_mismatch", "/glyph_identity/0/gid_equals_consistency")], {}),
    ("rev3_leg_note_lies", [lambda: _rev3(_ctrl_syn_t0())], [*NULL_CONS0, (LEG0 + "/value", "1"), (LEG0 + "/equals_char", True)], [("glyph_note_mismatch", LEG0 + "/equals_char"), ("phase_result_mismatch", "/phases/glyph_identity/result")], {}),
    ("rev3_glyph_char_drift", [lambda: _rev3(_ctrl_syn_t0())], [("/glyph_identity/0/char", "再"), (LEG0 + "/value", "再")], [("glyph_identity_char", "/glyph_identity/0/char")], {}),
    ("poppler_blocked_but_status_pass", ["ek"], _poppler_blocked(), [("status_mismatch", "/status")], {}),
    ("save_reopen_result_not_run", ["ek"], [("/phases/save_reopen/result", "not_run")], [("phase_result_mismatch", "/phases/save_reopen/result")], {}),
    ("gid_mismatches_self_pass", ["ek"], [("/neighbours/gid_mismatches", 2)], [("phase_result_mismatch", "/phases/neighbours/result"), ("neighbours_summary_mismatch", "/neighbours/gid_mismatches")], {}),
    ("positive_overlap_self_pass", ["ek"], [("/neighbours/overlap_glyphs", 1)], [("phase_result_mismatch", "/phases/neighbours/result")], {}),
    ("canary_overlap_self_pass", ["gh", "gs"], [(0, "/phases/neighbours/result", "pass")], [("phase_result_mismatch", "/phases/neighbours/result")], {}),
    ("operator_under_string_token", ["t0"], [(OP, _op(lambda t: "(abc) Tj q 1 g 0 0 5 5 re f Q"))], [("operand_grammar", OP)], {}),
    ("positive_with_canary_splice", ["ek"], [("/mutation/splice_kind", "canary"), (OP, _op(lambda t: "q 1 g 0 0 5 5 re f Q"))], [("canary_marker_mismatch", "/mutation/splice_kind")], {}),
    ("two_changes_string_token", ["t0"], [("/mutation/changes", lambda c: [c["mutation"]["changes"][0], copy.deepcopy(c["mutation"]["changes"][0])])], [("changes_count", "/mutation/changes")], {}),
    ("string_bytes_not_glyph_codes", ["t0"], [(OP, _op(lambda t: t.replace("0100", "0777", 1)))], [("operand_binding", OP)], {}),
    ("show_count_changed", ["ek"], [("/text_state/show_count_after", 301)], [("phase_result_mismatch", "/phases/structure/result")], {}),
    ("record_key_unicode", ["ek"], [("@records/0/unicode", "x")], [("neighbours_record_key", "/0/" + eb._esc("unicode"), "neighbours.json")], {}),
    ("untouched_origin_delta", ["ek"], [("@records/0/origin_delta_pt", 0.01), ("/neighbours/untouched_max_origin_delta_pt", 0.01)], [("phase_result_mismatch", "/phases/neighbours/result")], {}),
    ("halo_area_above_bound", ["ek"], [("/render/halo_area_pt2", lambda c: c["render"]["halo_area_pt2"] + 50.0)], [("halo_area_mismatch", "/render/halo_area_pt2")], {}),
    ("control_growth_declared_off", ["t1"], [("/growth_zone/applicable", False)], [("growth_applicable_mismatch", "/growth_zone/applicable")], {}),
    ("shrink_row_declared_on", ["ek"], [("/mutation/advance/adv_new_text_space", 9.0)], [("growth_applicable_mismatch", "/growth_zone/applicable")], {}),
    ("stroke_failed_self_pass", ["t1"], [("/growth_zone/stroke_proof", "failed"), ("/growth_zone/before_drawings_not_provably_clear", 1)], [("phase_result_mismatch", "/phases/growth_zone/result")], {}),
    ("k_arithmetic_self_pass", ["ek"], [(K, 501.0)], [("phase_result_mismatch", "/phases/structure/result")], {}),
    ("simple_font_cid_tounicode", ["ek"], [("/glyph_identity/0/consistency/selected_by", "cid_tounicode")], [("phase_result_mismatch", "/phases/glyph_identity/result")], {}),
    ("proprietary_old_operand", ["t1"], [("/mutation/changes/0/old_operand_bytes_hex", "3031")], [("redaction_null_required", "/mutation/changes/0/old_operand_bytes_hex")], {}),
    ("proprietary_latin1", ["t1"], [("/target/source_decode/latin1", "x")], [("redaction_null_required", "/target/source_decode/latin1")], {}),
    ("proprietary_original", ["t1"], [("/corpus_case/original", "Drawing List")], [("redaction_null_required", "/corpus_case/original")], {}),
    ("case_absent_from_plan", ["ek"], [], [("pre_registered_mismatch", "/pre_registered")], {"plan_edits": [("/cases/0", _DEL)]}),
    ("expected_reason_changed", ["t0"], [], [("pre_registered_mismatch", "/pre_registered")], {"plan_edits": [("/cases/0/expected_reason", "some_reason")]}),
    ("png_without_render_prefix", ["ek"], [], [("png_name", "", eb._digest("foo.png"))], {"files": {"cases/{cid}/foo.png": b"x"}}),
    ("machine_path_in_observation", ["ek"], [("/observation", _winpath())], [("machine_path", "/observation")], {}),
    ("client_cjk_in_glyph_char", ["t0"], [("/glyph_identity/3/char", "客")], [("client_string", "/glyph_identity/3/char")], {}),
    ("type0_extra_cid", ["t0"], [(OP, _op(lambda t: t[:-1] + "0777>"))], [("operand_binding", OP)], {}),
    ("product_success_true", ["ek"], [("/product_success", True)], [("schema_const", "/product_success")], {}),
    ("parent_by_status_off_by_one", ["ek"], [], [("parent_summary_mismatch", "/by_status/blocked", "PARENT_SUMMARY.json")], {"parent_edits": [("/by_status/blocked", 1)]}),
    ("uncaught_canary_claimed_caught", ["uncaught"], [], [("calibration_mismatch", "/calibration/canaries/CANARY_GROWTH/caught", "PARENT_SUMMARY.json")], {}),
    ("growth_canary_unrotated", ["gh", "gs"], [(0, "/source/page_rotation", 0)], [("growth_canary_site", "/source/page_rotation")], {}),
    ("growth_canary_show_26", [_s26_growth], [], [("growth_canary_site", "/corpus_case/show_seq")], {}),
    ("growth_canary_show_185", [_s185_growth], [], [("growth_canary_site", "/corpus_case/show_seq")], {}),
    ("lineage_split", [_geotopo_pair], [], [("lineage_mismatch", "/source/lineage_id")], {}),
    ("ctrl_neg_status_lie", ["neg"], [("/status", "insufficient_evidence")], [("status_mismatch", "/status")], {}),
    ("tracked_diff_not_empty", ["ek"], [("/code_revision/tracked_diff_empty", False)], [("schema_const", "/code_revision/tracked_diff_empty"), ("tracked_diff_not_empty", "/code_revision/tracked_diff_empty")], {}),
    ("before_pdf_tampered", ["ek"], [], [("before_pdf_sha_mismatch", "")], {"files": {"candidates/{cid}/before.pdf": b"%PDF tampered"}}),
    ("k_null_wider_after_not_applicable", ["ek"], _equal_width_edits(), [("growth_after_exceeds_target", "/target/after_bbox_visual")], {}),
    ("fragment_prefix_off_by_one", ["split"], [(OP, _op(lambda t: t.replace("(a)", "(Q)", 1)))], [("fragment_prefix_mismatch", OP)], {}),
    ("fragment_suffix_off_by_one", ["split"], [(OP, _op(lambda t: t.replace("(d)", "(Q)", 1)))], [("fragment_suffix_mismatch", OP)], {}),
    ("denylist_word_in_observation", ["ek"], [("/observation", "supplier AcmeCorp ships")], [("denylist_hit", "/observation")], {"denylist": ["acmecorp"]}),
    ("canary_with_f_class", ["gh", "gs"], [(0, "/class_id", "F30B")], [("kind_class_mismatch", "/class_id")], {}),
    ("leg_gid_differs", ["ek"], [("/glyph_identity/0/independent_leg/gid", 999)], [("phase_result_mismatch", "/phases/glyph_identity/result")], {}),
    ("k_token_differs", ["ek"], [(K, 500.5)], [("k_token_mismatch", K)], {}),
    ("overlap_counts_space_record", ["ek"], [("@records/0/is_space", True), ("@records/0/overlap", True), ("/neighbours/overlap_glyphs", 1)], [("neighbours_summary_mismatch", "/neighbours/overlap_glyphs")], {}),
    ("syn_t1_applicable_without_mutation", ["st1"], [("/growth_zone/applicable", True)], [("mutation_null_fields_not_null", "/growth_zone/applicable")], {}),
    ("syn_t1_wrong_reason", ["st1"], [("/probe/max_tier_1/reason", "other_reason")], [("calibration_mismatch", "/calibration/controls/CTRL_SYN_T1/ok", "PARENT_SUMMARY.json")], {}),
    ("syn_t1_detail_prefix", ["st1"], [("/probe/max_tier_1/detail", "region: 1 character(s) occupy it")], [("calibration_mismatch", "/calibration/controls/CTRL_SYN_T1/ok", "PARENT_SUMMARY.json")], {}),
    ("syn_t1_attempted", ["st1"], [("/probe/commit/attempted", True)], [("calibration_mismatch", "/calibration/controls/CTRL_SYN_T1/ok", "PARENT_SUMMARY.json")], {}),
    ("tier0_with_tj_operator", ["t0"], [(OP, _op(lambda t: t + " Tj"))], [("operand_grammar", OP)], {}),
    ("latin1_word_off_allowlist", [_nonpublic_ek], [(OP, _op(lambda t: "[(zzzz) 500.000000] TJ"))], [("client_string", OP)], {}),
    ("probe_detail_not_ascii", ["t1"], [("/probe/max_tier_0/detail", "café")], [("detail_not_ascii", "/probe/max_tier_0/detail")], {}),
    ("verify_off_by_2e_minus_3", ["ek"], [("/target/verify_bbox_visual/2", 117.002)], [("verify_bbox_mismatch", "/target/verify_bbox_visual")], {}),
    ("user_unit_factor_missing", ["ek"], [("/target/user_unit", 2.0)], [("growth_pt_mismatch", "/mutation/advance/growth_pt")], {}),
    ("experiment_k_null_with_growth", ["ek"], _none_k(), [("k_null_rule", K)], {}),
    ("is_space_on_non_space", ["ek"], [("/glyph_identity/0/is_space", True)], [("glyph_identity_is_space", "/glyph_identity/0/is_space")], {}),
    ("glyph_identity_short", ["ek"], [("/glyph_identity", lambda c: c["glyph_identity"][:2])], [("glyph_identity_length", "/glyph_identity")], {}),
    ("save_full_with_pass", ["ek"], [("/mutation/saved_with", "save_full")], [("saved_with_save_reopen", "/mutation/saved_with")], {}),
    ("synthetic_without_builder", ["st0"], [("/source/synthetic_builder", None)], [("synthetic_builder_mismatch", "/source/synthetic_builder")], {}),
    ("synthetic_foreign_callable", ["st0"], [("/source/synthetic_builder/callable", "test_scripts.other_module.build_fixture")], [("synthetic_builder_not_allowlisted", "/source/synthetic_builder/callable")], {}),
    ("synthetic_non_scalar_kwarg", ["st0"], [("/source/synthetic_builder/kwargs/text", ["a"])], [("synthetic_kwargs_not_scalar", "/source/synthetic_builder/kwargs/text")], {}),
    ("synthetic_pin_changed", ["st0"], [("/source/synthetic_builder/kwargs/rotate", 90)], [("synthetic_pin_mismatch", "/source/synthetic_builder/kwargs")], {}),
    ("target_ink_after_zero", ["ek"], [("@records/2/ink_after_px_6x", 0)], [("phase_result_mismatch", "/phases/neighbours/result")], {}),
    ("mutation_null_phase_run", ["neg"], [("/phases/extraction/result", "pass")], [("mutation_null_phase_not_run", "/phases/extraction/result")], {}),
    ("trm_scale_frobenius", ["t1"], [("/target/trm_scale", 0.0849)], [("trm_scale_mismatch", "/target/trm_scale")], {}),
    ("growth_pt_frobenius", ["t1"], [("/mutation/advance/growth_pt", 2.983)], [("growth_pt_mismatch", "/mutation/advance/growth_pt")], {}),
    ("props_keys_not_inline_keys", ["t0"], [("/text_state/before/wrapper_stack/0/props_keys", ["Type", "Name", "Usage"])], [("client_string", None)], {}),
    ("calibration_text_with_client_word", ["t0"], [("/extraction/after_text_at_target", CALIBRATION_REPL_T0 + " ACME")], [("client_string", "/extraction/after_text_at_target")], {}),
    ("type0_advance_source_widths", ["t1"], [("/mutation/advance/advance_source", "Widths")], [("advance_source_font_kind", "/mutation/advance/advance_source")], {}),
    ("after_runs_past_verify", ["ek"], [("/target/after_bbox_visual/2", 118.0)], [("growth_after_exceeds_verify", "/target/after_bbox_visual")], {}),
    ("structelem_full_key_set", ["t0"], [("/text_state/before/wrapper_stack/0/structelem_keys", ["S", "P", "K", "Pg"])], [("structelem_keys_vocabulary", "/text_state/before/wrapper_stack/0/structelem_keys"), ("client_string", None)], {}),
    ("positive_synthetic", ["ek"], [("/source/provenance", "synthetic"), ("/source/synthetic_builder", SYN_BUILDER), ("/source/relative_path", None)], [("synthetic_kind", "/kind")], {}),
    ("done_sha_mismatch", ["ek"], [], [("done_sha_mismatch", "/parent_summary_sha256", "DONE.json")], {"done_edit": [("/parent_summary_sha256", "0" * 64)]}),
    ("done_missing", ["ek"], [], [("done_missing", "", "DONE.json")], {"delete": ["DONE.json"]}),
    ("in_array_split_rewrites_operator", ["inarr"], [(OP, _op(lambda t: TJ_SPLIT))], [("operand_grammar", OP)], {}),
    ("in_array_split_nested_bracket", ["inarr"], [(OP, _op(lambda t: "(a)[(XY)](d)"))], [("operand_grammar", OP)], {}),
    ("required_key_missing", ["ek"], [("/observation", _DEL)], [("schema_required", "/observation")], {}),
    ("plan_sha_differs", ["ek"], [("/methods_plan_sha256", "1" * 64)], [("methods_plan_sha_mismatch", "/methods_plan_sha256")], {}),
    ("artifact_listed_but_absent", ["ek"], [], [("artifact_missing", None)], {"delete": ["cases/{cid}/render-mupdf-after-6x.png"]}),
    ("join_key_wrong", ["ek"], [("/join_key", "multicolumn/p0/show4")], [("join_key_mismatch", "/join_key")], {}),
    ("tc_changed", ["ek"], [("/mutation/advance/Tc", 0.25)], [("tc_tw_mismatch", "/mutation/advance/Tc")], {}),
    ("tfs_differs_from_tf_operand", ["ek"], [("/mutation/advance/Tfs", 11.0)], [("tfs_mismatch", "/mutation/advance/Tfs")], {}),
    ("prepared_verify_differs", ["t1"], [("/probe/max_tier_1/prepared/verify_bbox_page", [100.0, 300.0, 200.0, 312.0])], [("prepared_bbox_mismatch", "/target/verify_bbox_visual")], {}),
    ("prepared_advance_differs", ["t1"], [("/probe/max_tier_1/prepared/source_advance", 600.0)], [("product_advance_mismatch", "/mutation/advance/adv_old_text_space")], {}),
    ("displacement_sign", ["ek"], [("/mutation/advance/displacement", 6.0)], [("displacement_mismatch", "/mutation/advance/displacement")], {}),
    ("char_count_new_wrong", ["ek"], [("/mutation/advance/char_count_new", 9)], [("char_count_mismatch", "/mutation/advance/char_count_new")], {}),
    ("mutation_null_target_equal_set", ["neg"], [("/text_state/target_equal", True)], [("mutation_null_fields_not_null", "/text_state/target_equal")], {}),
    ("before_pdf_sha_field_differs", ["ek"], [("/source/before_pdf_sha256", "1" * 64)], [("before_pdf_sha_field", "/source/before_pdf_sha256")], {}),
    ("extraction_flag_lies", ["ek"], [("/extraction/equals_replacement", False)], [("extraction_self_inconsistent", "/extraction/equals_replacement")], {}),
    ("stroke_count_contradicts_proof", ["t1"], [("/growth_zone/before_drawings_intersecting_bbox", 0)], [("stroke_proof_inconsistent", "/growth_zone/stroke_proof")], {}),
    ("region_visual_differs", ["ek"], [("/growth_zone/region_visual/2", 120.0)], [("region_visual_mismatch", "/growth_zone/region_visual")], {}),
    ("direction_differs", ["ek"], [("/growth_zone/direction", "left")], [("direction_mismatch", "/growth_zone/direction")], {}),
    ("internal_kerns_not_reproduced", ["ek"], [("/mutation/advance/K_sum", 3.0)], [("k_sum_mismatch", "/mutation/advance/K_sum")], {}),
    ("canary_marker_on_path", ["ek"], [("/mutation/path", "canary")], [("canary_marker_mismatch", "/mutation/path")], {}),
    ("advance_array_without_tj_run", ["ek"], [("/mutation/advance", lambda c: [c["mutation"]["advance"]])], [("advance_array_not_tj_run", "/mutation/advance")], {}),
    ("relative_path_on_proprietary", ["t1"], [("/source/relative_path", "test_files/x.pdf")], [("relative_path_must_be_null", "/source/relative_path")], {}),
    ("glyph_note_lies", ["ek"], [("/glyph_identity/0/gid_equals_consistency", False)], [("glyph_note_mismatch", "/glyph_identity/0/gid_equals_consistency")], {}),
    ("code_revision_split", ["ek", "t1"], [(1, "/code_revision/git_head", "c" * 40)], [("code_revision_inconsistent", "/code_revision/git_head")], {}),
    ("advance_function_wrong", ["ek"], [("/mutation/advance/advance_function", "IdentityHCidCapability.advance_points")], [("advance_function_mismatch", "/mutation/advance/advance_function")], {}),
    ("tolerance_not_recomputed", ["ek"], [("/mutation/advance/advance_tolerance", 0.5)], [("advance_tolerance_mismatch", "/mutation/advance/advance_tolerance")], {}),
    ("mutation_null_but_glyphs", ["neg"], [("/glyph_identity", [{"index": 0}])], [("glyph_identity_not_empty", "/glyph_identity")], {}),
]


REJECTS += [
    ("pairing_map_broken", ["ek"], [("@records/5/trace_index_after", 99)], [("pairing_map", "/5/trace_index_after", "neighbours.json")], {}),
    ("pairing_delta_wrong", ["ek"], [("/mutation/advance/char_count_old", 1)], [("pairing_delta_mismatch", "/neighbours/target_glyphs_after")], {}),
    ("after_bbox_raw_wrong", ["ek"], [("/target/after_bbox_raw/2", 500.0)], [("after_bbox_raw_mismatch", "/target/after_bbox_raw")], {}),
    ("halo_shadowed_but_checked", ["ek"], [("@records/0/halo_shadowed", True)], [("halo_shadowed_checked", "/0/ink_checked", "neighbours.json")], {}),
    ("ink_after_on_untouched", ["ek"], [("@records/0/ink_after_px_6x", 5)], [("ink_after_field", "/0/ink_after_px_6x", "neighbours.json")], {}),
    ("overlap_flag_against_geometry", ["ek"], [("@records/0/overlap", True)], [("neighbours_overlap_flag", "/0/overlap", "neighbours.json")], {}),
    ("fragment_range_missing", ["split"], [("/target/byte_range_in_item", None)], [("fragment_range_missing", "/target/byte_range_in_item")], {}),
    ("k_without_number_token", ["ek"], [(OP, _op(lambda t: "[(abc)] TJ"))], [("k_present_without_number", K)], {}),
    ("advance_missing", ["ek"], [("/mutation/advance", None)], [("advance_missing", "/mutation/advance")], {}),
    ("case_id_wrong_sha", ["ek"], [("/case_id", "r2-F30B-00000000-p0-s3-grow1")], [("case_id_mismatch", "/case_id")], {}),
    ("artifact_dir_wrong", ["ek"], [("/artifacts/dir", "cases/elsewhere/")], [("artifact_path_mismatch", "/artifacts/dir")], {}),
    ("unexpected_extension", ["ek"], [], [("unexpected_file", "", eb._digest("notes.txt"))], {"files": {"notes.txt": b"x"}}),
    ("pdf_outside_candidates", ["ek"], [], [("pdf_location", "", eb._digest("stray.pdf"))], {"files": {"cases/{cid}/stray.pdf": b"%PDF"}}),
    ("denylist_cjk_substring", ["ek"], [("/observation", "vendor 客戶 supplied it")], [("denylist_hit", "/observation")], {"denylist": ["客戶"]}),
    ("machine_path_in_readme", ["ek"], [], [("machine_path", "", "README.md")], {"files": {"README.md": (_winpath() + "\n").encode()}}),
    ("parent_unknown_class", ["ek"], [], [("parent_class_key", "/per_class/" + eb._esc("BOGUS"), "PARENT_SUMMARY.json")], {"parent_edits": [("/per_class/BOGUS", {"cases": 0, "positives": 0, "negatives": 0, "distinct_lineages": 0, "distinct_producer_families": 0, "tier0_positive_pass": 0, "tier1_positive_pass": 0, "by_status": dict.fromkeys(STATUS_KEYS, 0), "class_state_proposal": "open", "remeasure_pending": True})]}),
    ("parent_stamp_differs", ["ek"], [], [("parent_invariant", "/stamp", "PARENT_SUMMARY.json")], {"parent_edits": [("/stamp", "20261023_1201_r2")]}),
    ("calibration_attempts_over_three", ["ek"], [], [("parent_invariant", "/calibration/attempts", "PARENT_SUMMARY.json")], {"parent_edits": [("/calibration/attempts", 4)]}),
    ("class_state_overclaim", ["ek"], [], [("class_state_overclaim", "/per_class/F30B/class_state_proposal", "PARENT_SUMMARY.json")], {"parent_edits": [("/per_class/F30B/class_state_proposal", "method_reproducible")]}),
    ("calibration_ref_differs", ["ek"], [("/calibration_ref", "synthetic_only")], [("calibration_ref_mismatch", "/calibration_ref")], {}),
    ("case_record_differs_from_cases_json", ["ek"], [], [("cases_json_mismatch", "", "case_record.json")], {"files": {"cases/{cid}/case_record.json": b'{"case_id": "x"}'}}),
    ("neighbours_file_unparseable", ["ek"], [], [("json_unparseable", "", "neighbours.json")], {"files": {"cases/{cid}/neighbours.json": b"{not json"}}),
    ("plan_without_json_block", ["ek"], [], [("plan_block_missing", "", "METHODS_AND_EVIDENCE_PLAN.md")], {"files": {"METHODS_AND_EVIDENCE_PLAN.md": b"# no block here\n"}}),
    ("probe_exception_without_finding", ["ek"], [("/probe/max_tier_1/result", "exception"), ("/probe/max_tier_1/exception_type", "ValueError"), ("/phases/probe/result", "fail"), ("/status", "blocked")], [("parent_summary_mismatch", "/product_findings", "PARENT_SUMMARY.json")], {}),
]


def _without(*drop: str) -> list[str]:
    return [k for k in R0_KEYS if k not in drop]


def _zero_k(case: dict) -> list:
    return [("/mutation/advance/K_sum", None), ("/mutation/advance/K_disp_engine", None), ("/mutation/advance/K_disp_hand", None)]


def _bogus_k_edits() -> list:
    return [
        (K, 900.0),
        (OP, _op(lambda t: t.replace("500.000000", "900.000000"))),
        ("/mutation/advance/K_sum", None),
        ("/mutation/advance/K_disp_engine", None),
        ("/mutation/advance/K_disp_hand", None),
        ("/mutation/advance/abs_diff_written_vs_sum_engine", None),
        ("/mutation/advance/abs_diff_engine_hand", None),
    ]


def _name_token(text: str):
    return _op(lambda t: t + " " + text)


# fix round 1: forgeries that validated, each is a must-reject row (code, pointer) written red first
REJECTS += [
    ("r0_absent_frontier_row_claims_pass", ["ek"], [], [("calibration_incomplete", "/calibration", "PARENT_SUMMARY.json")], {"r0": False}),
    ("r0_missing_ctrl_det", [*_without("det"), "ek"], [], [("calibration_incomplete", "/calibration", "PARENT_SUMMARY.json")], {"r0": False}),
    ("r0_missing_canary_ink", [*_without("ink"), "ek"], [], [("calibration_incomplete", "/calibration", "PARENT_SUMMARY.json")], {"r0": False}),
    ("r0_missing_hvac_growth_site_under_pass", [*_without("gh"), "ek"], [], [("calibration_incomplete", "/calibration", "PARENT_SUMMARY.json")], {"r0": False}),
    ("r0_missing_synthetic_growth_site", [*_without("gs"), "ek"], [], [("calibration_incomplete", "/calibration", "PARENT_SUMMARY.json")], {"r0": False}),
    ("k_components_null_with_honest_k", ["ek"], _none_k()[1:] + [(K, 500.0)], [("k_null_rule", "/mutation/advance/K_sum"), ("k_null_rule", "/mutation/advance/K_disp_engine"), ("k_null_rule", "/mutation/advance/K_disp_hand")], {}),
    ("k_components_null_with_bogus_k", ["ek"], _bogus_k_edits(), [("k_null_rule", "/mutation/advance/K_sum"), ("k_null_rule", "/mutation/advance/K_disp_engine")], {}),
    ("tier0_product_row_grows_beyond_tolerance", ["t0"], [("/mutation/advance/adv_new_text_space", lambda c: c["mutation"]["advance"]["adv_old_text_space"] + 5.0)], [("product_advance_mismatch", "/mutation/advance/adv_new_text_space")], {}),
    ("sha_after_run_contradicts_the_unchanged_flag", ["ek"], [("/source/sha256_after_run", "f" * 64)], [("source_sha_after_mismatch", "/source/sha256_after_run")], {}),
    ("unchanged_flag_false_but_sha_equal", ["ek"], [("/save_reopen/source_sha256_unchanged", False)], [("source_sha_after_mismatch", "/source/sha256_after_run")], {}),
    ("replacement_sha_is_not_the_replacements", ["ek"], [("/corpus_case/replacement_sha256", "1" * 64)], [("replacement_sha_mismatch", "/corpus_case/replacement_sha256")], {}),
    ("canary_operand_hides_a_comment", ["gh", "gs"], [(0, OP, _name_token("% a confidential note"))], [("operand_grammar", OP)], {}),
    ("canary_operand_hides_a_dict", ["gh", "gs"], [(0, OP, _name_token("<< /Note (x) >>"))], [("operand_grammar", OP)], {}),
    ("canary_operand_bare_word_is_not_a_pdf_operator", ["gh", "gs"], [(0, OP, _name_token("ACMECorp"))], [("operand_grammar", OP)], {}),
    ("canary_operand_name_token_is_client_text", ["gh", "gs"], [(0, OP, _name_token("/ACMECorp"))], [("client_string", OP)], {}),
    ("canary_operand_name_token_hits_the_denylist", ["gh", "gs"], [(0, OP, _name_token("/ACMECorp"))], [("denylist_hit", OP)], {"denylist": ["acmecorp"]}),
    # the 14 stable codes that were emitted but never asserted
    ("schema_pattern_replacement_newline", ["ek"], [("/corpus_case/replacement", "a" + chr(10) + "b")], [("schema_pattern", "/corpus_case/replacement")], {}),
    ("schema_min_length_variable", ["ek"], [("/mutation/variable_changed", "")], [("schema_min_length", "/mutation/variable_changed")], {}),
    ("schema_minimum_page_index", ["ek"], [("/corpus_case/page_index", -1)], [("schema_minimum", "/corpus_case/page_index")], {}),
    ("schema_min_items_changes", ["ek"], [("/mutation/changes", [])], [("schema_min_items", "/mutation/changes")], {}),
    ("schema_max_items_item_range", ["ek"], [("/target/item_range", [1, 2, 3])], [("schema_max_items", "/target/item_range")], {}),
    ("schema_any_of_after_bbox", ["ek"], [("/target/after_bbox_visual", "wide")], [("schema_any_of", "/target/after_bbox_visual")], {}),
    ("th_differs_from_tz", ["ek"], [("/mutation/advance/Th", 0.5)], [("th_mismatch", "/mutation/advance/Th")], {}),
    ("type0_fragment_odd_offset", ["t0"], [("/mutation/splice_kind", "string_fragment"), ("/target/byte_range_in_item", [1, 5])], [("fragment_odd_offset", "/target/byte_range_in_item")], {}),
    ("fragment_without_prefix_or_suffix", ["t0"], [("/mutation/splice_kind", "string_fragment"), ("/target/byte_range_in_item", [0, 4])], [("fragment_not_f3", OP)], {}),
    ("abs_diff_written_vs_sum_engine_lies", ["ek"], [("/mutation/advance/abs_diff_written_vs_sum_engine", 7.0)], [("k_abs_diff_mismatch", "/mutation/advance/abs_diff_written_vs_sum_engine")], {}),
    ("abs_diff_engine_hand_lies", ["ek"], [("/mutation/advance/abs_diff_engine_hand", 7.0)], [("k_abs_diff_mismatch", "/mutation/advance/abs_diff_engine_hand")], {}),
    ("growth_field_set_on_a_non_growth_row", ["t0"], [("/growth_zone/direction", "right")], [("growth_fields_not_null", "/growth_zone/direction")], {}),
    ("done_stamp_differs_from_the_directory", ["ek"], [], [("done_stamp_mismatch", "/stamp", "DONE.json")], {"done_edit": [("/stamp", "20261023_1201_r2")]}),
    ("done_case_count_differs", ["ek"], [], [("done_case_count_mismatch", "/case_count", "DONE.json")], {"done_edit": [("/case_count", 99)]}),
    ("props_name_carries_cjk", ["t0"], [("/text_state/before/wrapper_stack/0/props_name", "客戶")], [("props_name_not_ascii", "/text_state/before/wrapper_stack/0/props_name")], {}),
]


def _synthetic(case: dict) -> dict:
    out = _retarget(case, slug="ctrl-syn", page=0, show=0)
    out["source"].update({"provenance": "synthetic", "relative_path": None, "synthetic_builder": copy.deepcopy(SYN_BUILDER), "page_rotation": 270})
    out["calibration_ref"] = "synthetic_only"
    return out


def _synthetic_only_keys() -> list:
    return [*(_resolve(k) for k in ("st0", "st1")), *(_synthetic(_resolve(k)) for k in ("ksign", "tc", "unsaved", "wrong", "ink")), _resolve("gs")]


# --------------------------------------------------------------------------
# fix round 2: forgeries that validated (reviewer probes P1-P16 and the duplicate-control blocker).
# Each row is a must-reject written red first; the honest twins stay in GUARD_SETS.
# --------------------------------------------------------------------------
def _bad_neg_row() -> dict:
    """A second CTRL_NEG at hvac p4 s12 whose honest reason is annotations_not_indirect, so the brief 2.1 control FAILS."""
    case = _retarget(_ctrl_neg(), show=12)
    for name in ("max_tier_1", "max_tier_0"):
        case["probe"][name].update(reason="annotations_not_indirect", detail="3 of 3 listed /Annots entries are inline dictionaries (no xref)")
    case["corpus_case"]["expected_reason"] = "annotations_not_indirect"
    return case


def _t0_off_site() -> dict:
    return _retarget(_tier0_hvac(), show=12)


def _t1_off_site() -> dict:
    return _retarget(_ctrl_pos_t1(), show=27)


def _halo_forged_edits() -> list:
    """Every untouched neighbour of ek is flagged halo_shadowed (and so not ink-checked) although none sits near the target."""
    edits: list = []
    for i in (0, 1, 5, 6):
        edits += [(f"@records/{i}/halo_shadowed", True), (f"@records/{i}/ink_checked", False)]
    edits += [("@records/5/ink_changed_px_6x", 50), ("/neighbours/halo_shadowed_glyphs", 4)]
    return edits


def _bbox_union_of(boxes: list) -> list:
    out = list(boxes[0])
    for b in boxes[1:]:
        out = _union(out, b)
    return out


def _swallowed_successor_edits() -> list:
    """The first successor glyph is relabelled role=target: the target run grows by one glyph and the glyph drops out of every untouched check."""

    def forged() -> list:
        recs = _records(2, 3, "abc")
        recs[5]["role"] = "target"
        return recs

    def summary(case):
        return _summary(forged(), 3, 4, case["case_id"])

    def raw_after(_case):
        return _bbox_union_of([r["bbox_after"] for r in forged() if r["role"] == "target" and r["bbox_after"]])

    return [("@records", lambda _recs: forged()), ("/neighbours", summary), ("/target/after_bbox_raw", raw_after)]


def _after_equals_target_edits() -> list:
    """ek claims growth, but after_bbox_visual is kept equal to the target and the growth side is moved to 'up'."""
    t = [100.0, 688.0, 111.0, 700.0]
    return [
        ("/target/after_bbox_visual", list(t)),
        ("/growth_zone/direction", "up"),
        ("/target/verify_bbox_visual", [100.0, 682.0, 111.0, 700.0]),
        ("/growth_zone/region_visual", [100.0, 682.0, 111.0, 688.0]),
        ("/render/halo_area_pt2", (11.0 + 6.0) * (12.0 + 6.0)),
    ]


def _frame_unlinked_edits() -> list:
    """Equal-width row whose visual boxes do not grow while the raw boxes (neighbours.json target records) are 10 pt wider."""
    return [
        *_equal_width_edits(),
        ("/mutation/splice_kind", "string_token"),
        (OP, _op(lambda t: "(abc)")),
        ("/target/after_bbox_visual", [100.0, 688.0, 111.0, 700.0]),
        ("/render/halo_area_pt2", 17.0 * 18.0),
    ]


def _syn_keys() -> list:
    return _synthetic_only_keys()


_N_SYN = len(_synthetic_only_keys())

REJECTS += [
    # blocker: a second row of one control class hides a failed R0 control (order independent)
    (
        "duplicate_control_bad_row_first",
        [_bad_neg_row, *R0_KEYS, "ek"],
        [],
        [
            ("control_duplicate", "/class_id"),
            ("calibration_mismatch", "/calibration/controls/CTRL_NEG/ok", "PARENT_SUMMARY.json"),
            ("calibration_mismatch", "/calibration/status", "PARENT_SUMMARY.json"),
        ],
        {"r0": False},
    ),
    (
        "duplicate_control_bad_row_last",
        [*R0_KEYS, "ek", _bad_neg_row],
        [],
        [
            ("control_duplicate", "/class_id"),
            ("calibration_mismatch", "/calibration/controls/CTRL_NEG/ok", "PARENT_SUMMARY.json"),
            ("calibration_mismatch", "/calibration/status", "PARENT_SUMMARY.json"),
        ],
        {"r0": False},
    ),
    ("duplicate_control_site_is_pinned", [_bad_neg_row, *R0_KEYS, "ek"], [], [("control_site", "/corpus_case/show_seq")], {"r0": False}),
    ("ctrl_pos_t0_off_its_site", [*_without("t0"), _t0_off_site, "ek"], [], [("control_site", "/corpus_case/show_seq")], {"r0": False}),
    ("ctrl_pos_t1_off_its_site", [*_without("t1"), _t1_off_site, "ek"], [], [("control_site", "/corpus_case/show_seq")], {"r0": False}),
    # crash safety: an unhashable class_id / kind / status is a schema defect, not a traceback
    ("class_id_is_a_list", ["ek"], [], [("schema_enum", "/class_id")], {"late_edits": [(0, "/class_id", ["F30B"])]}),
    ("kind_is_a_list", ["ek"], [], [("schema_enum", "/kind")], {"late_edits": [(0, "/kind", ["positive"])]}),
    ("status_is_a_dict", ["ek"], [], [("schema_enum", "/status")], {"late_edits": [(0, "/status", {"x": 1})]}),
    # P1-P3: neighbours records are recomputed, not trusted
    ("halo_shadowed_forged_on_every_neighbour", ["ek"], _halo_forged_edits(), [("halo_shadowed_flag", "/0/halo_shadowed", "neighbours.json")], {}),
    ("ink_checked_dropped_without_a_reason", ["ek"], [("@records/0/ink_checked", False)], [("ink_checked_flag", "/0/ink_checked", "neighbours.json")], {}),
    ("successor_glyph_swallowed_into_the_target_run", ["ek"], _swallowed_successor_edits(), [("target_run_size_mismatch", "/neighbours/target_glyphs_before")], {}),
    (
        "target_records_claim_to_be_spaces",
        ["ek"],
        [(f"@records/{i}/{key}", value) for i in (2, 3, 4) for key, value in (("is_space", True), ("ink_after_px_6x", None))],
        [("target_is_space_mismatch", "/2/is_space", "neighbours.json")],
        {},
    ),
    (
        "null_mutation_row_with_a_target_record",
        ["annots"],
        [("@records", lambda recs: [_target_rec(0, 1, 1, "a")])],
        [("null_mutation_record", "/0/role", "neighbours.json")],
        {},
    ),
    # P4, P5, P6: structure and growth fields that a self-report could leave undecided or unlinked
    (
        "wrapper_bytes_unchanged_null_under_a_wrapper",
        ["t0"],
        [("/mutation/wrapper_bytes_unchanged", None)],
        [("phase_result_mismatch", "/phases/structure/result"), ("status_mismatch", "/status")],
        {},
    ),
    ("growth_applicable_but_after_equals_target", ["ek"], _after_equals_target_edits(), [("growth_after_not_grown", "/target/after_bbox_visual")], {}),
    ("raw_after_box_grows_while_the_visual_box_does_not", ["ek"], _frame_unlinked_edits(), [("after_bbox_frame_mismatch", "/target/after_bbox_raw")], {}),
    # P7, P10, P16: probe results and the prepared object agree, and a product commit really committed
    (
        "probe_rejected_but_prepared_present",
        ["t1"],
        [
            ("/probe/max_tier_1/result", "rejected"),
            ("/probe/max_tier_1/reason", "advance_mismatch"),
            ("/probe/max_tier_1/detail", "replacement advance differs from the source advance"),
        ],
        [("probe_prepared_mismatch", "/probe/max_tier_1/result")],
        {},
    ),
    (
        "probe_prepared_without_a_prepared_object",
        ["ek"],
        [("/probe/max_tier_1/result", "prepared"), ("/probe/binding_matches_target", True)],
        [("probe_prepared_mismatch", "/probe/max_tier_1/result")],
        {},
    ),
    (
        "product_commit_status_failed_under_nine_passes",
        ["t1"],
        [("/probe/commit/status", "failed")],
        [("phase_result_mismatch", "/phases/probe/result"), ("status_mismatch", "/status")],
        {},
    ),
    # P8: the datum behind extraction.equals_replacement
    ("extraction_text_null_with_flags_set", ["ek"], [("/extraction/after_text_at_target", None)], [("phase_result_mismatch", "/phases/extraction/result")], {}),
    # P9: synthetic_only is for a missing hvac file only
    (
        "synthetic_only_while_an_hvac_control_passes",
        [_syn_keys, "t0", "ek"],
        [(_N_SYN + 1, "/calibration_ref", "synthetic_only")],
        [("synthetic_only_with_hvac_present", "/calibration/status", "PARENT_SUMMARY.json")],
        {"r0": False, "parent_edits": [("/calibration/status", "synthetic_only")]},
    ),
    (
        "synthetic_only_while_an_hvac_census_row_is_measured",
        [_syn_keys, lambda: _retarget(_census_f1(), slug="hvac"), "ek"],
        [(_N_SYN + 1, "/calibration_ref", "synthetic_only"), (_N_SYN, "/calibration_ref", "synthetic_only")],
        [("synthetic_only_with_hvac_present", "/calibration/status", "PARENT_SUMMARY.json")],
        {"r0": False, "parent_edits": [("/calibration/status", "synthetic_only")]},
    ),
    # P13: a non-public F3 row is admitted for Type0 CIDs only (letters of a simple font are not CID-bound)
    (
        "nonpublic_f3_on_a_simple_font",
        [lambda: _nonpublic(_fragment(False))],
        [(OP, _op(lambda t: "[(h) (XY) (p)] TJ"))],
        [("nonpublic_f3_not_type0", "/corpus_case/font_kind")],
        {},
    ),
]


def test_an_f3_tail_split_with_a_kern_token_is_a_brief_grammar_shape():
    """Brief 5.2: fragment_split takes 2 or 3 strings and at most one number; ``(prefix)(middle) K`` is two strings and a number."""
    case = _patch(
        _fragment(False),
        (OP, b"[(ab) (XY) 500.000000] TJ".hex().upper()),
        ("/mutation/changes/0/old_operand_bytes_hex", b"(abcd) Tj".hex().upper()),
        ("/target/byte_range_in_item", [2, 4]),
        (K, 500.0),
    )
    bad = [
        v
        for v in eb.check_operand_grammar(case).violations
        if v.code in ("operand_grammar", "operand_binding", "fragment_prefix_mismatch", "fragment_suffix_mismatch")
    ]
    assert bad == [], bad


def test_a_list_class_id_still_writes_the_validation_report(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")], late_edits=[(0, "/class_id", ["F30B"])])
    out = tmp_path / "out" / "VALIDATION.json"
    rc = eb.main(["validate", str(root), "--out", str(out), "--denylist", str(tmp_path / "none.txt")])
    assert rc == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert ("schema_enum", "/class_id") in _hits(report)


def test_the_report_says_when_fixture_bound_checks_are_still_pending(tmp_path):
    report = _validate(tmp_path, [_resolve("ek")])
    assert report["ok"] is True
    assert report["pending_rederive"] is True
    assert report["unverifiable"]


MALFORMED_KEY_FIELDS = [
    ("/class_id", ["F30B"]),
    ("/kind", ["positive"]),
    ("/status", {"x": 1}),
    ("/case_id", ["x"]),
    ("/join_key", ["x"]),
    ("/source/slug", ["x"]),
    ("/source/provenance", {"x": 1}),
    ("/source/lineage_id", ["x"]),
    ("/source/producer_family", ["x"]),
    ("/source/sha256", ["x"]),
    ("/corpus_case/page_index", [4]),
    ("/corpus_case/show_seq", {"x": 1}),
    ("/corpus_case/expected_reason", ["x"]),
]


@pytest.mark.parametrize("edit", MALFORMED_KEY_FIELDS, ids=[e[0] for e in MALFORMED_KEY_FIELDS])
def test_a_malformed_key_field_is_a_schema_defect_not_a_check_error(tmp_path, edit):
    """A list or dict where a batch-level check keys a dict or set must not stop that check (spec A 2.1 items 2 and 18)."""
    report = eb.validate_batch(_make_batch(tmp_path, [_resolve("ek")], late_edits=[(0, *edit)]))
    assert report["ok"] is False
    assert "check_error" not in {v["code"] for v in report["violations"]}, _show(report)


def test_the_last_line_filter_withholds_long_non_ascii_and_machine_path_text():
    """``_scrub_text`` is the chokepoint behind every detail; the upstream layers never hand it these, so it is pinned directly."""
    keep = eb._scrub_text("a plain rule sentence", [])
    assert keep == "a plain rule sentence"
    assert eb._scrub_text("x" * 401, []) == "[detail withheld]"
    assert eb._scrub_text("caf\u00e9", []) == "[detail withheld]"
    assert eb._scrub_text("see " + _winpath(), []) == "[detail withheld]"
    assert eb._scrub_text("acmecorp widget", eb._deny_matchers(["acmecorp"])) == "[detail withheld]"


def test_the_report_names_the_cases_json_it_judged(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")])
    report = eb.validate_batch(root)
    assert report["cases_json_sha256"] == _h((root / "cases.json").read_bytes())
    (root / "cases.json").unlink()
    assert eb.validate_batch(root)["cases_json_sha256"] is None


def test_the_hvac_sha_constant_is_the_acceptance_files_sha():
    from test_scripts import true_text_corpus

    manifest = true_text_corpus.load_manifest()
    assert eb.HVAC_SHA256 == manifest.spec_by_slug("hvac").sha256
    assert {c.slug: c.provenance for c in manifest.corpora}["hvac"] == "proprietary"
    assert eb.HVAC_SHA256 in BRIEF.read_text(encoding="utf-8")


def test_a_probe_exception_is_blocked_and_needs_a_product_finding(tmp_path):
    case = _resolve("ek")
    cid = case["case_id"]
    finding = {"case_id": cid, "kind": "engine_exception", "detail": "max_tier_1 raised ValueError"}
    edits = [
        ("/probe/max_tier_1/result", "exception"),
        ("/probe/max_tier_1/exception_type", "ValueError"),
        ("/probe/max_tier_1/reason", None),
        ("/probe/max_tier_1/detail", None),
        ("/phases/probe/result", "fail"),
        ("/status", "blocked"),
    ]
    parent = [
        *_by_status_edits("ek", "blocked"),
        ("/per_class/F30B/by_status/save_reopen_pass", 0),
        ("/per_class/F30B/by_status/blocked", 1),
        ("/per_class/F30B/tier1_positive_pass", 0),
        ("/per_class/F30B/class_state_proposal", "open"),
        ("/product_findings", [finding]),
    ]
    report = _validate(tmp_path, [case], edits=edits, parent_edits=parent)
    assert report["violations"] == [], _show(report)


def test_out_of_scope_vector_needs_no_mutation_and_an_observation(tmp_path):
    case = _resolve("f1")
    not_run = _probe_result("not_run", None)
    edits = [
        ("/probe/max_tier_1", not_run),
        ("/probe/max_tier_0", copy.deepcopy(not_run)),
        ("/phases/probe/result", "not_run"),
        ("/status", "out_of_scope_vector"),
        ("/observation", "Only a vector path is drawn at this position."),
    ]
    parent = [
        *_by_status_edits("f1", "out_of_scope_vector"),
        ("/per_class/F1/by_status/probe_rejected", 0),
        ("/per_class/F1/by_status/out_of_scope_vector", 1),
    ]
    report = _validate(tmp_path, [case], edits=edits, parent_edits=parent)
    assert report["violations"] == [], _show(report)
    lying = _validate(tmp_path / "again", [case], edits=[*edits, ("/observation", "")], parent_edits=parent)
    assert ("status_mismatch", "/status") in _hits(lying)


def test_find_show_lists_the_matching_show(tmp_path, capsys):
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Hello needle")
    page.insert_text((72, 140), "Other words")
    pdf = tmp_path / "one.pdf"
    doc.save(str(pdf))
    doc.close()
    assert eb.main(["find-show", "--pdf", str(pdf), "--page", "0", "--text", "needle"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert any(r["match"] and r["operator"] in ("Tj", "TJ") for r in rows)
    assert any(not r["match"] for r in rows), rows  # a show without the text is not a match
    assert all(("needle" in r["decoded"]) == r["match"] for r in rows)
    assert set(rows[0]) == {"show_seq", "operator", "op_start", "op_end", "font_resource", "decoded", "match"}


REJECTS += [
    # V5: an integer-valued JSON float is flagged and still feeds the integer-gated rules
    (
        "char_count_old_float_still_checks_the_target_run",
        ["ek"],
        [*_swallowed_successor_edits(), ("/mutation/advance/char_count_old", lambda c: float(c["mutation"]["advance"]["char_count_old"]))],
        [("integer_expected", "/mutation/advance/char_count_old"), ("target_run_size_mismatch", "/neighbours/target_glyphs_before")],
        {},
    ),
    (
        "char_count_old_float_still_checks_the_pairing_delta",
        ["ek"],
        [("/mutation/advance/char_count_old", 1.0)],
        [("integer_expected", "/mutation/advance/char_count_old"), ("pairing_delta_mismatch", "/neighbours/target_glyphs_after")],
        {},
    ),
]


def test_as_int_is_strict_and_coerces_integer_valued_floats():
    acc = eb._Acc({"case_id": None})
    assert eb._as_int(7, acc, "/a") == 7
    assert eb._as_int(None, acc, "/n") is None
    assert acc.res.violations == []
    assert eb._as_int(12.0, acc, "/f") == 12
    assert isinstance(eb._as_int(12.0, acc, "/f"), int)
    assert eb._as_int(True, acc, "/b") is None
    assert eb._as_int(12.5, acc, "/h") is None
    assert eb._as_int("3", acc, "/s") is None
    got = [(v.code, v.pointer) for v in acc.res.violations]
    assert got == [("integer_expected", p) for p in ("/f", "/b", "/h", "/s")]  # one entry per pointer


def _check_expected(report, expected):
    for item in expected:
        code, pointer = item[0], item[1]
        suffix = item[2] if len(item) > 2 else None
        found = [
            v
            for v in report["violations"]
            if v["code"] == code
            and (pointer is None or v["pointer"] == pointer)
            and (suffix is None or v["file"].endswith(suffix))
        ]
        assert found, f"missing {item}\nGOT:\n{_show(report)}"


@pytest.mark.parametrize("row", REJECTS, ids=[r[0] for r in REJECTS])
def test_forged_or_broken_shape_is_rejected(tmp_path, row):
    _, keys, edits, expected, kw = row
    report = _validate(tmp_path, _expand(keys), edits=edits, **kw)
    assert report["ok"] is False
    _check_expected(report, expected)


# --------------------------------------------------------------------------
# honest twins: the same lie told truthfully validates
# --------------------------------------------------------------------------
def _by_status_edits(key: str, status: str) -> list:
    """``/by_status`` edits when frontier base ``key`` reports ``status`` and the R0 pack keeps its own statuses."""
    mine = _resolve(key)["case_id"]
    by = dict.fromkeys(STATUS_KEYS, 0)
    for c in _with_r0(_expand([key])):
        by[status if c["case_id"] == mine else c["status"]] += 1
    return [(f"/by_status/{name}", count) for name, count in by.items()]


def _demoted_parent(status: str) -> list:
    return [
        *_by_status_edits("ek", status),
        ("/per_class/F30B/by_status/save_reopen_pass", 0),
        (f"/per_class/F30B/by_status/{status}", 1),
        ("/per_class/F30B/tier1_positive_pass", 0),
        ("/per_class/F30B/class_state_proposal", "open"),
    ]


TWINS = [
    (
        "neighbours_gid_mismatch_reported",
        [
            ("@records/0/gid_after", 9),
            ("@records/1/gid_after", 9),
            ("/neighbours/gid_mismatches", 2),
            ("/phases/neighbours/result", "fail"),
            ("/status", "probe_rejected"),
        ],
    ),
    (
        "k_arithmetic_reported",
        [
            (K, 501.0),
            ("/mutation/advance/abs_diff_written_vs_sum_engine", 1.0),
            (OP, _op(lambda t: t.replace("500.000000", "501.000000"))),
            ("/phases/structure/result", "fail"),
            ("/status", "probe_rejected"),
        ],
    ),
    (
        "leg_gid_differs_reported",
        [
            ("/glyph_identity/0/independent_leg/gid", 999),
            ("/glyph_identity/0/independent_leg/gid_equals_after", False),
            ("/phases/glyph_identity/result", "fail"),
            ("/status", "probe_rejected"),
        ],
    ),
    (
        "target_ink_zero_reported",
        [
            ("@records/2/ink_after_px_6x", 0),
            ("/phases/neighbours/result", "fail"),
            ("/status", "probe_rejected"),
        ],
    ),
    (
        "show_count_changed_reported",
        [
            ("/text_state/show_count_after", 301),
            ("/phases/structure/result", "fail"),
            ("/status", "probe_rejected"),
        ],
    ),
    (
        "save_full_reported",
        [
            ("/mutation/saved_with", "save_full"),
            ("/phases/save_reopen/result", "fail"),
            ("/status", "splice_pass"),
        ],
    ),
]


@pytest.mark.parametrize("twin", TWINS, ids=[t[0] for t in TWINS])
def test_the_honest_twin_of_a_forged_pass_validates(tmp_path, twin):
    _, edits = twin
    status = [v for p, v in edits if p == "/status"][0]
    parent = _demoted_parent(status)
    report = _validate(tmp_path, [_resolve("ek")], edits=edits, parent_edits=parent)
    assert report["violations"] == [], _show(report)


# --------------------------------------------------------------------------
# must-validate extras
# --------------------------------------------------------------------------
def test_tier0_with_a_sub_tolerance_difference_validates_without_k(tmp_path):
    def tweak(c):
        return c["mutation"]["advance"]["adv_old_text_space"] + 1e-8

    edits = [
        ("/mutation/advance/adv_new_text_space", tweak),
        ("/mutation/advance/displacement", lambda c: -1e-8),
        ("/mutation/advance/growth_pt", lambda c: 1e-8 * (100.0 / 100.0) * 0.06),
        ("/probe/max_tier_1/prepared/replacement_advance", lambda c: 500.0 + 1e-8),
        ("/probe/max_tier_0/prepared/replacement_advance", lambda c: 500.0 + 1e-8),
    ]
    report = _validate(tmp_path, [_resolve("t0")], edits=edits)
    assert report["violations"] == [], _show(report)


def test_chinese_observation_on_a_proprietary_row_is_a_warning_not_a_violation(tmp_path):
    report = _validate(tmp_path, [_resolve("t0")], edits=[("/observation", "備註說明")])
    assert report["violations"] == [], _show(report)
    assert report["ok"] is True
    assert len(report["language_warnings"]) == 1


def test_structelem_lang_only_validates(tmp_path):
    report = _validate(tmp_path, [_resolve("t0")], edits=[("/text_state/before/wrapper_stack/0/structelem_keys", ["Lang"])])
    assert report["violations"] == [], _show(report)


# R7-2: wrapper tags are PDF names (standard structure types the old allowlist missed, role-mapped producer tags),
# checked by shape, not against a fixed table of structure types
TAG_PATH = "/text_state/before/wrapper_stack/0/tag"


@pytest.mark.parametrize("tag", ["TOCI", "BlockQuote", "Caption", "THead", "Warichu", "RT", "Normal.Para_2-x"])
def test_standard_or_role_mapped_wrapper_tag_on_a_proprietary_row_validates(tmp_path, tag):
    report = _validate(tmp_path, [_resolve("t0")], edits=[(TAG_PATH, tag)])
    assert report["violations"] == [], _show(report)


@pytest.mark.parametrize("tag", ["目錄", "Table TR", "P/x", "TOCé", "", "A" * 128])
def test_wrapper_tag_outside_the_ascii_name_rule_is_a_client_string(tmp_path, tag):
    report = _validate(tmp_path, [_resolve("t0")], edits=[(TAG_PATH, tag)])
    assert report["ok"] is False
    assert ("client_string", TAG_PATH) in _hits(report), _show(report)


def test_ascii_name_tag_rule_bounds():
    assert eb._is_ascii_name("A" * 127) is True
    assert eb._is_ascii_name("A" * 128) is False
    assert eb._is_ascii_name("") is False
    assert eb._is_ascii_name(None) is False


def test_matching_unsaved_canary_text_is_calibration_exempt(tmp_path):
    case = _resolve("unsaved")
    assert case["extraction"]["after_text_at_target"] == CALIBRATION_ORIG_T0
    report = _validate(tmp_path, [case])
    assert report["violations"] == [], _show(report)


def test_calibration_literal_in_a_non_calibration_class_is_a_client_string(tmp_path):
    case = _retarget(_resolve("t0"), class_id="F1", kind="census", variant="cen")
    case["status"] = "insufficient_evidence"
    case["extraction"]["after_text_at_target"] = CALIBRATION_NEG
    report = _validate(tmp_path, [case])
    assert ("client_string", "/extraction/after_text_at_target") in _hits(report), _show(report)


def test_validation_report_never_echoes_the_matched_text(tmp_path):
    report = _validate(
        tmp_path,
        [_resolve("ek")],
        edits=[("/observation", _winpath() + " supplier AcmeCorp")],
        denylist=["acmecorp"],
    )
    blob = json.dumps(report).lower()
    assert "acmecorp" not in blob
    assert ("C:" + "\\" + "Users").lower() not in blob
    assert str(tmp_path).lower() not in blob
    assert report["batch"] == STAMP


# V1: scan_redaction must not fail open on files it cannot parse or decode
def _redaction_hits(report: dict, rel: str) -> set[str]:
    return {v["code"] for v in report["violations"] if v["file"] == rel}


def test_unparseable_json_is_reported_and_still_scanned_raw(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")], files={"REDACTION.json": b'{"entries": ["supplier AcmeCorp" '})
    report = eb.validate_batch(root, denylist=["acmecorp"])
    codes = _redaction_hits(report, "REDACTION.json")
    assert "json_unparseable" in codes, _show(report)
    assert "denylist_hit" in codes, _show(report)
    assert "acmecorp" not in json.dumps(report).lower()


def test_utf16_readme_is_reported_and_still_scanned(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")], files={"README.md": "# Batch\n\nsupplier AcmeCorp\n".encode("utf-16")})
    report = eb.validate_batch(root, denylist=["acmecorp"])
    codes = _redaction_hits(report, "README.md")
    assert "file_not_utf8" in codes, _show(report)
    assert "denylist_hit" in codes, _show(report)


def test_duplicate_json_key_first_value_is_still_scanned(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")], files={"REDACTION.json": b'{"entries": ["supplier AcmeCorp"], "entries": []}'})
    report = eb.validate_batch(root, denylist=["acmecorp"])
    codes = _redaction_hits(report, "REDACTION.json")
    assert "json_duplicate_key" in codes, _show(report)
    assert "denylist_hit" in codes, _show(report)
    assert "acmecorp" not in json.dumps(report).lower()


def test_an_unknown_key_is_reported_by_digest_not_by_text(tmp_path):
    rogue = _winpath()
    report = _validate(tmp_path, [_resolve("ek")], edits=[("/" + rogue, 1)])
    assert any(v["code"] == "schema_additional" and v["pointer"].startswith("/#") for v in report["violations"]), _show(report)
    blob = json.dumps(report)
    assert "Users" not in blob and "see " not in blob


def test_planted_text_never_reaches_the_report_or_stderr(tmp_path, capsys):
    sentinel = "Zq" + "Acme" + "9f3"
    finding_case = _patch(_resolve("ek"), ("/probe/max_tier_1/result", "exception"), ("/probe/max_tier_1/exception_type", sentinel))
    control = _patch(_resolve("st1"), ("/probe/max_tier_1/reason", sentinel), ("/status", sentinel))
    root = _make_batch(
        tmp_path,
        [finding_case, control],
        edits=[(0, "/class_id", sentinel)],
        files={f"cases/{sentinel}/note.json": b"{}", f"{sentinel}.txt": b"x"},
    )
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out)]) == 1
    blob = out.read_text(encoding="utf-8") + capsys.readouterr().err
    assert sentinel.lower() not in blob.lower()
    assert json.loads(out.read_text(encoding="utf-8"))["violations"], "the planted values must still be rejected"


def test_report_paths_are_batch_relative(tmp_path):
    report = _validate(tmp_path, [_resolve("ek")], edits=[(K, 501.0)])
    for entry in report["violations"] + report["unverifiable"]:
        assert not entry["file"].startswith(("/", "\\")) and ":" not in entry["file"], entry["file"]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def test_cli_exits_one_and_lists_every_defect(tmp_path, capsys):
    root = _make_batch(
        tmp_path,
        [_resolve("ek")],
        edits=[("/observation", _winpath()), ("/product_success", True), ("/neighbours/gid_mismatches", 2)],
    )
    out = tmp_path / "VALIDATION.json"
    code = eb.main(["validate", str(root), "--out", str(out)])
    assert code == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    codes = {v["code"] for v in written["violations"]}
    assert {"machine_path", "schema_const", "neighbours_summary_mismatch"} <= codes
    err = capsys.readouterr().err
    for needed in ("machine_path", "schema_const", "neighbours_summary_mismatch"):
        assert needed in err


def test_cli_exits_zero_on_a_clean_batch(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")])
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is True


def test_cli_run_as_a_script_from_the_repo_root(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")])
    out = tmp_path / "VALIDATION.json"
    done = subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts" / "evidence_bundle.py"), "validate", str(root), "--out", str(out)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr


def test_missing_batch_files_are_all_reported_at_once(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")], delete=["README.md", "INVENTORY.md", "REDACTION.json"])
    report = eb.validate_batch(root)
    missing = {v["file"] for v in report["violations"] if v["code"] == "file_missing"}
    assert {"README.md", "INVENTORY.md", "REDACTION.json"} <= missing


def test_a_legacy_v1_batch_directory_is_rejected(tmp_path):
    legacy = tmp_path / "20260924_1431"
    (legacy / "case-1").mkdir(parents=True)
    (legacy / "cases.json").write_text(json.dumps([{"case_id": "case-1", "status": "x", "seq": 1}]), encoding="utf-8")
    (legacy / "case-1" / "case_record.json").write_text(json.dumps({"case_id": "case-1", "seq": 1}), encoding="utf-8")
    report = eb.validate_batch(legacy)
    assert report["ok"] is False
    codes = {v["code"] for v in report["violations"]}
    assert {"file_missing", "done_missing"} <= codes


def test_tier0_product_row_with_the_products_zero_prepared_advances_validates(tmp_path):
    """A Tier 0 PreparedEdit leaves source_advance and replacement_advance at their 0.0 default (only Tier 1 sets
    them), so "the advance object equals the prepared advance" is a Tier 1 rule.  An honest Tier 0 product row (the
    mandatory CTRL_POS_T0 control) carries the real advance only in the advance object, which rederive re-measures."""
    zero = [
        (f"/probe/max_tier_{n}/prepared/{key}", 0.0)
        for n in (0, 1)
        for key in ("source_advance", "replacement_advance")
    ]
    case = _patch(_resolve("t0"), *zero)
    assert case["mutation"]["advance"]["adv_old_text_space"] == 500.0
    report = eb.validate_batch(_make_batch(tmp_path, [case]))
    assert "product_advance_mismatch" not in {v["code"] for v in report["violations"]}
    # the Tier 1 rule is unchanged: a prepared advance that differs from the record still rejects
    t1 = _patch(_resolve("t1"), ("/probe/max_tier_1/prepared/source_advance", 600.0))
    report = eb.validate_batch(_make_batch(tmp_path / "t1", [t1]))
    assert "product_advance_mismatch" in {v["code"] for v in report["violations"]}


# --------------------------------------------------------------------------
# fix round 1: lineage by sha, honest canary operands, the synthetic_only R0 subset
# --------------------------------------------------------------------------
def _same_file_other_slug(case: dict, slug: str, page: int, show: int) -> dict:
    """``case`` moved to another page of the SAME file (same sha256) under another slug label."""
    old_sha = case["source"]["sha256"]
    moved = _retarget(case, slug=slug, page=page, show=show)
    new_sha = moved["source"]["sha256"]
    text = json.dumps(moved, ensure_ascii=False).replace(new_sha, old_sha).replace(new_sha[:8], old_sha[:8])
    return json.loads(text)


def test_one_sha256_under_two_slugs_is_one_lineage(tmp_path):
    first = _resolve("ek")
    second = _same_file_other_slug(first, "multicolumn-copy", 1, 4)
    second["source"]["lineage_id"] = "multicolumn-copy"
    second["source"]["producer_family"] = "family-b"
    assert second["source"]["sha256"] == first["source"]["sha256"]
    root = _make_batch(
        tmp_path,
        [first, second, _resolve("annots")],
        files={f"candidates/{second['case_id']}/before.pdf": _pdf("multicolumn")},
        parent_edits=[("/per_class/F30B/class_state_proposal", "method_reproducible")],
    )
    report = eb.validate_batch(root)
    assert ("lineage_mismatch", "/source/slug") in _hits(report), _show(report)
    assert ("lineage_mismatch", "/source/lineage_id") in _hits(report), _show(report)
    assert ("lineage_mismatch", "/source/producer_family") in _hits(report), _show(report)


def test_one_sha256_with_one_label_set_on_two_pages_is_one_lineage_and_validates(tmp_path):
    first = _resolve("ek")
    second = _retarget(first, page=1, show=4)
    assert second["source"]["sha256"] == first["source"]["sha256"]
    report = _validate(tmp_path, [first, second])
    assert not [v for v in report["violations"] if v["code"] == "lineage_mismatch"], _show(report)


def test_an_honest_canary_operand_may_carry_a_font_and_a_tc_operator(tmp_path):
    """Brief 2.2: CANARY_FONT inserts ``/C2_0 <size> Tf`` and CANARY_TC ``0.25 Tc``; numbers outside a TJ array are not K tokens."""
    edits = [(0, OP, _name_token("0.25 Tc /C2_0 97.023 Tf"))]
    report = _validate(tmp_path, [_resolve("gh"), _resolve("gs")], edits=edits)
    assert report["violations"] == [], _show(report)


def test_a_tc_canary_with_a_number_and_no_k_validates(tmp_path):
    case = _resolve("tc")
    change = case["mutation"]["changes"][0]
    change["new_operand_bytes_hex"] = (bytes.fromhex(change["new_operand_bytes_hex"]) + b" 0.25 Tc").hex().upper()
    report = _validate(tmp_path, [case])
    assert report["violations"] == [], _show(report)


def test_a_synthetic_only_batch_needs_only_the_synthetic_r0_subset(tmp_path):
    """Brief 2.3: without hvac the controls and canaries run on CTRL_SYN_T0/T1; CANARY_FONT is not_run, the hvac growth site is blocked."""
    cases = [*_synthetic_only_keys(), _resolve("ek")]
    root = _make_batch(
        tmp_path,
        cases,
        edits=[(len(cases) - 1, "/calibration_ref", "synthetic_only")],
        parent_edits=[("/calibration/status", "synthetic_only")],
        r0=False,
    )
    report = eb.validate_batch(root)
    assert report["violations"] == [], _show(report)


def test_a_synthetic_only_batch_still_needs_ctrl_syn_t1(tmp_path):
    cases = [c for c in _synthetic_only_keys() if c["class_id"] != "CTRL_SYN_T1"] + [_resolve("ek")]
    root = _make_batch(
        tmp_path,
        cases,
        edits=[(len(cases) - 1, "/calibration_ref", "synthetic_only")],
        parent_edits=[("/calibration/status", "synthetic_only")],
        r0=False,
    )
    report = eb.validate_batch(root)
    assert ("calibration_incomplete", "/calibration") in _hits(report), _show(report)


def test_a_batch_without_frontier_rows_needs_no_r0_pack(tmp_path):
    """A calibration-fail batch (brief 2.3) runs no frontier case, so nothing demands a complete R0."""
    report = _validate(tmp_path, [_resolve("t1")])
    assert "calibration_incomplete" not in {v["code"] for v in report["violations"]}


def _blocked_hvac_control() -> dict:
    """Brief 2.3: without hvac the CTRL_POS rows are recorded as blocked (probe never ran)."""
    case = _retarget(_ctrl_neg(), class_id="CTRL_POS_T1", show=26)
    not_run = _probe_result("not_run", None)
    case["probe"].update({"max_tier_1": not_run, "max_tier_0": copy.deepcopy(not_run), "binding_matches_target": None})
    case["phases"]["probe"] = _phase("blocked", "the hvac file is absent on this machine")
    case["status"] = "blocked"
    return case


def test_a_control_recorded_as_blocked_does_not_fail_a_synthetic_only_calibration(tmp_path):
    cases = [*_synthetic_only_keys(), _blocked_hvac_control(), _resolve("ek")]
    root = _make_batch(
        tmp_path,
        cases,
        edits=[(len(cases) - 1, "/calibration_ref", "synthetic_only")],
        parent_edits=[("/calibration/status", "synthetic_only"), ("/calibration/controls/CTRL_POS_T1/ok", False)],
        r0=False,
    )
    report = eb.validate_batch(root)
    assert report["violations"] == [], _show(report)
    assert report["recomputed"]["calibration"]["status"] == "synthetic_only"


def test_the_same_blocked_control_fails_a_calibration_that_claims_pass(tmp_path):
    cases = [*(_resolve(k) for k in _without("t1")), _blocked_hvac_control(), _resolve("ek")]
    root = _make_batch(tmp_path, cases, parent_edits=[("/calibration/controls/CTRL_POS_T1/ok", False)], r0=False)
    report = eb.validate_batch(root)
    assert ("calibration_mismatch", "/calibration/status") in _hits(report), _show(report)


# --------------------------------------------------------------------------
# V6: a missing denylist is never silent
# --------------------------------------------------------------------------
def _rev3(case: dict) -> dict:
    """The same row written under brief v3 (brief_revision enum [2, 3]), with the v3-required honest displacement_ink."""
    out = _patch(case, ("/brief_revision", 3))
    advs = eb._g(out, "mutation", "advance")
    for adv in advs if isinstance(advs, list) else [advs] if isinstance(advs, dict) else []:
        k_sum = adv.get("K_sum") if eb._g(out, "mutation", "splice_kind") == "tj_run" else 0.0
        adv["displacement_ink"] = adv["adv_new_text_space"] - adv["adv_old_text_space"] + (k_sum or 0.0) * adv["Tfs"] / 1000.0
    return out


def test_a_proprietary_row_without_a_denylist_is_rejected(tmp_path):
    report = eb.validate_batch(_make_batch(tmp_path, [_rev3(_nonpublic(_resolve("ek")))]))
    assert "denylist_missing" in {v["code"] for v in report["violations"]}, _show(report)
    assert report["ok"] is False
    assert report["redaction_scan"]["denylist_present"] is False
    assert report["redaction_scan"]["denylist_entries"] == 0
    assert all(v["case_id"] is None for v in report["violations"] if v["code"] == "denylist_missing")


def _public_only_batch(tmp_path: Path) -> Path:
    """A clean batch whose rows are all public or synthetic (hvac absent, calibration synthetic_only)."""
    cases = [*_synthetic_only_keys(), _resolve("ek")]
    return _make_batch(
        tmp_path,
        cases,
        edits=[(len(cases) - 1, "/calibration_ref", "synthetic_only")],
        parent_edits=[("/calibration/status", "synthetic_only")],
        r0=False,
    )


def test_a_public_only_batch_without_a_denylist_only_gets_a_note(tmp_path):
    report = eb.validate_batch(_public_only_batch(tmp_path))
    assert {c["source"]["provenance"] for c in json.loads((tmp_path / STAMP / "cases.json").read_text(encoding="utf-8"))} <= {"public", "synthetic"}
    assert "denylist_missing" not in {v["code"] for v in report["violations"]}, _show(report)
    assert report["ok"] is True, _show(report)
    assert report["redaction_scan"]["denylist_present"] is False
    assert report["redaction_scan"]["denylist_entries"] == 0


def test_a_supplied_denylist_is_counted(tmp_path):
    report = eb.validate_batch(_make_batch(tmp_path, [_nonpublic(_resolve("ek"))]), denylist=["acmecorp", "", "# c", "beta"])
    assert "denylist_missing" not in {v["code"] for v in report["violations"]}, _show(report)
    assert report["redaction_scan"]["denylist_present"] is True
    assert report["redaction_scan"]["denylist_entries"] == 2


def test_a_missing_provenance_counts_as_non_public(tmp_path):
    case = _rev3(_resolve("ek"))
    case["source"]["provenance"] = None
    report = eb.validate_batch(_make_batch(tmp_path, [case]))
    assert "denylist_missing" in {v["code"] for v in report["violations"]}, _show(report)


def test_cli_without_the_default_denylist_rejects_a_proprietary_row(tmp_path, monkeypatch):
    monkeypatch.setattr(eb, "DEFAULT_DENYLIST", tmp_path / "absent.txt")
    root = _make_batch(tmp_path, [_rev3(_nonpublic(_resolve("ek")))])
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out)]) == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    assert "denylist_missing" in {v["code"] for v in written["violations"]}
    assert written["redaction_scan"]["denylist_present"] is False


def test_cli_without_the_default_denylist_passes_a_public_only_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(eb, "DEFAULT_DENYLIST", tmp_path / "absent.txt")
    root = _public_only_batch(tmp_path)
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert "denylist_missing" not in {v["code"] for v in written["violations"]}
    assert written["redaction_scan"]["denylist_present"] is False
    assert written["notes"], "a public-only batch still says the denylist layer scanned nothing"


def test_cli_with_the_default_denylist_reads_it(tmp_path, monkeypatch):
    deny = tmp_path / "deny.txt"
    deny.write_text("acmecorp\n\n# comment\n", encoding="utf-8")
    monkeypatch.setattr(eb, "DEFAULT_DENYLIST", deny)
    root = _make_batch(tmp_path, [_nonpublic(_resolve("ek"))])
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["redaction_scan"]["denylist_present"] is True
    assert written["redaction_scan"]["denylist_entries"] == 1


def test_cli_explicit_denylist_that_is_missing_is_an_error_even_for_public_rows(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek"), *_synthetic_only_keys()], r0=False)
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out), "--denylist", str(tmp_path / "none.txt")]) == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    assert "denylist_missing" in {v["code"] for v in written["violations"]}
    assert written["redaction_scan"]["denylist_present"] is False


def test_a_rev2_proprietary_row_without_a_denylist_keeps_the_v2_behaviour(tmp_path):
    """denylist_missing is a v3 rule: the brief_revision 2 batches (1114 pilot) validate unchanged."""
    report = eb.validate_batch(_make_batch(tmp_path, [_nonpublic(_resolve("ek"))]))
    assert "denylist_missing" not in {v["code"] for v in report["violations"]}, _show(report)
    assert report["ok"] is True, _show(report)
    assert report["redaction_scan"]["denylist_present"] is False
    assert report["redaction_scan"]["denylist_entries"] == 0


def test_cli_rev2_proprietary_row_without_the_default_denylist_gets_only_a_note(tmp_path, monkeypatch):
    monkeypatch.setattr(eb, "DEFAULT_DENYLIST", tmp_path / "absent.txt")
    root = _make_batch(tmp_path, [_nonpublic(_resolve("ek"))])
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["violations"] == []
    assert written["redaction_scan"]["denylist_present"] is False
    assert written["notes"], "the absent denylist is still reported"


def test_a_rev3_row_among_rev2_rows_still_needs_the_denylist(tmp_path):
    report = eb.validate_batch(_make_batch(tmp_path, [_nonpublic(_resolve("ek")), _rev3(_nonpublic(_resolve("ek")))]))
    assert "denylist_missing" in {v["code"] for v in report["violations"]}, _show(report)



# --------------------------------------------------------------------------
# V7: the v3 null form of a row without mutation
# --------------------------------------------------------------------------
NULL_FORM_COUNTERS = (
    "glyphs_checked",
    "unpaired_glyphs",
    "target_glyphs_after",
    "target_origin_delta_pt",
    "untouched_max_origin_delta_pt",
    "inshow_successor_max_origin_delta_pt",
    "gid_mismatches",
    "ink_mismatches",
    "overlap_glyphs",
    "halo_shadowed_glyphs",
)
UNMAPPABLE = ("/target/replacement_provenance", "unmappable")
SIMPLE_GLYPH_SET = "replacement contains characters outside the verified simple encoding or the font's glyph set"


def _null_counters(case: dict) -> dict:
    return _patch(case, *((f"/neighbours/{k}", None) for k in NULL_FORM_COUNTERS))


def _v3_ctrl_neg() -> dict:
    """The honest brief v3 CTRL_NEG: ten post-mutation counters null, provenance unmappable."""
    return _patch(_null_counters(_rev3(_ctrl_neg())), UNMAPPABLE)


def _xcodes(case: dict) -> set[tuple[str, str]]:
    return {(v.code, v.pointer) for v in eb.check_cross_field(case).violations}


def test_the_honest_v3_null_form_validates(tmp_path):
    report = _validate(tmp_path, [_v3_ctrl_neg()], denylist=["acmecorp"])
    assert report["violations"] == [], _show(report)
    assert report["ok"] is True


def test_a_v3_ctrl_neg_writing_zero_counters_is_rejected():
    case = _patch(_rev3(_ctrl_neg()), UNMAPPABLE)  # the v2 shape: zeros for checks that never ran
    assert ("neighbours_null_form", "/neighbours/glyphs_checked") in _xcodes(case)


@pytest.mark.parametrize("counter", NULL_FORM_COUNTERS)
def test_a_v3_null_form_names_the_first_non_null_counter(counter):
    case = _patch(_v3_ctrl_neg(), (f"/neighbours/{counter}", 0))
    hits = {p for c, p in _xcodes(case) if c == "neighbours_null_form"}
    assert hits == {f"/neighbours/{counter}"}


def test_a_v3_ctrl_neg_claiming_drawn_chars_is_rejected():
    case = _patch(_v3_ctrl_neg(), ("/target/replacement_provenance", "chars_already_drawn_by_font"))
    assert ("replacement_provenance_unmappable", "/target/replacement_provenance") in _xcodes(case)


def test_the_identical_v2_ctrl_neg_gets_no_v3_violation():
    codes = {c for c, _p in _xcodes(_ctrl_neg())}
    assert not codes & {"neighbours_null_form", "replacement_provenance_unmappable"}


def test_a_v3_mutated_row_with_a_null_counter_is_rejected_without_a_check_error(tmp_path):
    case = _patch(_rev3(_resolve("ek")), ("/neighbours/gid_mismatches", None))
    assert ("neighbours_null_form", "/neighbours/gid_mismatches") in _xcodes(case)
    report = _validate(tmp_path, [case])
    codes = {v["code"] for v in report["violations"]}
    assert "neighbours_null_form" in codes, _show(report)
    assert "check_error" not in codes, _show(report)


@pytest.mark.parametrize("counter", ["glyphs_checked", "target_glyphs_after", "halo_shadowed_glyphs"])
def test_a_v3_mutated_row_names_its_null_count(counter):
    case = _patch(_rev3(_resolve("ek")), (f"/neighbours/{counter}", None))
    assert {p for c, p in _xcodes(case) if c == "neighbours_null_form"} == {f"/neighbours/{counter}"}


def test_the_honest_v3_mutated_row_has_no_null_form_violation():
    """An origin maximum over an empty role set stays null on a mutated row (the recompute governs it)."""
    assert _rev3(_resolve("ek"))["neighbours"]["inshow_successor_max_origin_delta_pt"] is None
    assert not {c for c, _p in _xcodes(_rev3(_resolve("ek")))} & {"neighbours_null_form", "replacement_provenance_unmappable"}


def test_unmappable_on_a_v3_positive_row_is_rejected():
    case = _patch(_rev3(_resolve("ek")), UNMAPPABLE)
    assert ("replacement_provenance_unmappable", "/target/replacement_provenance") in _xcodes(case)


def test_a_v3_census_row_with_an_unmapped_probe_can_say_unmappable():
    """Census rows never mutate and often stop at type0_unicode_unmapped: unmappable is their honest label."""
    case = _patch(_null_counters(_rev3(_census_f1())), UNMAPPABLE)
    assert case["kind"] == "census" and case["mutation"] is None
    assert case["probe"]["max_tier_1"]["reason"] == "type0_unicode_unmapped"
    assert not {c for c, _p in _xcodes(case)} & {"neighbours_null_form", "replacement_provenance_unmappable"}


def test_a_v3_census_row_with_an_unmapped_probe_still_needs_unmappable():
    case = _null_counters(_rev3(_census_f1()))
    assert ("replacement_provenance_unmappable", "/target/replacement_provenance") in _xcodes(case)


def test_a_v3_positive_row_rejected_as_unmapped_is_refused_either_way():
    """Brief 3.0 + 5.1 (f): a positive row claims drawn chars, an unmapped probe refutes the claim, and unmappable is
    never a positive label, so the row is refused whichever provenance it writes."""
    case = _patch(_null_counters(_rev3(_census_f1())), ("/kind", "positive"))
    assert ("replacement_provenance_unmappable", "/target/replacement_provenance") in _xcodes(case)
    case = _patch(case, UNMAPPABLE)
    assert ("replacement_provenance_unmappable", "/target/replacement_provenance") in _xcodes(case)


def _v3_rejected(reason: str, detail: str, provenance: str) -> dict:
    rej = _probe_result("rejected", None, reason, detail)
    return _patch(
        _v3_ctrl_neg(),
        ("/probe/max_tier_1", rej),
        ("/probe/max_tier_0", copy.deepcopy(rej)),
        ("/target/replacement_provenance", provenance),
    )


@pytest.mark.parametrize(
    ("reason", "detail"),
    [
        ("encoding_failed", SIMPLE_GLYPH_SET),
        ("type0_glyph_missing", "the embedded subset carries no outline for a required glyph"),
        ("type0_cid_out_of_map_range", "a required CID lies beyond the CIDToGIDMap table"),
        ("type0_gid_zero", "the CIDToGIDMap resolves a required CID to .notdef"),
        ("type0_gid_beyond_glyph_count", "a resolved GID lies beyond the embedded glyph count"),
        ("type0_unicode_unmapped", "no CID maps to a replacement character"),
    ],
)
def test_an_unmapped_family_reason_needs_unmappable(reason, detail):
    case = _v3_rejected(reason, detail, "chars_already_drawn_by_font")
    assert ("replacement_provenance_unmappable", "/target/replacement_provenance") in _xcodes(case)


@pytest.mark.parametrize(
    ("reason", "detail"),
    [
        ("encoding_failed", "reverse encoder does not reproduce the source string bytes"),
        ("type0_glyph_missing", "embedded program's glyph tables are unreadable; no glyph can be proven present"),
        ("growth_region_not_blank", "glyphs: 1 drawing intersects the growth strip"),
        ("type0_unicode_unmapped", "a source code has no ToUnicode mapping"),
        ("type0_unicode_unmapped", "no CID maps to a character of the bound source text"),
    ],
)
def test_a_reason_outside_the_unmapped_family_does_not_need_unmappable(reason, detail):
    case = _v3_rejected(reason, detail, "chars_already_drawn_by_font")
    assert "replacement_provenance_unmappable" not in {c for c, _p in _xcodes(case)}


def test_one_unmapped_probe_is_enough():
    case = _v3_rejected("growth_region_not_blank", "glyphs: 1 drawing intersects the growth strip", "chars_already_drawn_by_font")
    case["probe"]["max_tier_0"] = _probe_result("rejected", None, "type0_unicode_unmapped", "no CID maps to a replacement character")
    assert ("replacement_provenance_unmappable", "/target/replacement_provenance") in _xcodes(case)


def test_a_v2_row_still_rejects_null_counters_and_unmappable(tmp_path):
    """The widened schema must not relax brief_revision 2: null counters and unmappable stay schema defects there."""
    case = _patch(_null_counters(_ctrl_neg()), UNMAPPABLE)
    report = _validate(tmp_path, [case])
    hits = _hits(report)
    for key in ("glyphs_checked", "unpaired_glyphs", "gid_mismatches", "ink_mismatches", "overlap_glyphs", "halo_shadowed_glyphs"):
        assert ("schema_type", f"/neighbours/{key}") in hits, _show(report)
    assert ("schema_enum", "/target/replacement_provenance") in hits, _show(report)
    assert not {c for c, _p in hits} & {"neighbours_null_form", "replacement_provenance_unmappable"}
    assert report["ok"] is False


@pytest.mark.parametrize(
    ("reason", "detail"),
    [
        ("growth_region_not_blank", "glyphs: 1 drawing intersects the growth strip"),
        ("encoding_failed", "reverse encoder does not reproduce the source string bytes"),
        ("type0_glyph_missing", "embedded program's glyph tables are unreadable; no glyph can be proven present"),
        ("type0_unicode_unmapped", "a source code has no ToUnicode mapping"),
    ],
)
def test_unmappable_without_an_unmapped_probe_is_rejected(reason, detail):
    """unmappable says the replacement cannot be drawn; without a probe reason that says so it is an unsupported claim."""
    case = _v3_rejected(reason, detail, "unmappable")
    assert ("replacement_provenance_unmappable", "/target/replacement_provenance") in _xcodes(case)


def test_a_v3_census_row_saying_unmappable_without_an_unmapped_probe_is_rejected():
    rej = _probe_result("rejected", None, "growth_region_not_blank", "glyphs: 1 drawing intersects the growth strip")
    case = _patch(_null_counters(_rev3(_census_f1())), UNMAPPABLE, ("/probe/max_tier_1", rej), ("/probe/max_tier_0", copy.deepcopy(rej)))
    assert ("replacement_provenance_unmappable", "/target/replacement_provenance") in _xcodes(case)


# --------------------------------------------------------------------------
# V7: every row of a batch is written under the parent's brief revision
# --------------------------------------------------------------------------
def test_a_rev2_row_in_a_rev3_batch_cannot_opt_out_of_the_v3_rules(tmp_path):
    """A brief-v3 batch with one CTRL_NEG at brief_revision 2 (zeros, drawn chars) would skip every v3 rule."""
    case = _ctrl_neg()
    assert case["brief_revision"] == 2 and case["target"]["replacement_provenance"] == "chars_already_drawn_by_font"
    report = _validate(tmp_path, [case], denylist=["acmecorp"], parent_edits=[("/brief_revision", 3)])
    hits = [v for v in report["violations"] if v["code"] == "brief_revision_mismatch"]
    assert [(v["pointer"], v["case_id"]) for v in hits] == [("/brief_revision", case["case_id"])], _show(report)
    assert hits[0]["file"] == f"cases/{case['case_id']}/case_record.json"
    assert report["ok"] is False


def test_a_rev3_row_in_a_rev2_batch_is_a_mismatch_too(tmp_path):
    case = _v3_ctrl_neg()
    report = _validate(tmp_path, [case], denylist=["acmecorp"], parent_edits=[("/brief_revision", 2)])
    assert ("brief_revision_mismatch", "/brief_revision") in _hits(report), _show(report)
    assert report["ok"] is False


def test_a_mixed_revision_batch_flags_only_the_odd_rows(tmp_path):
    cases = [_rev3(_resolve("ek"))]  # R0 rows arrive at brief_revision 2, the parent follows the newest row
    report = _validate(tmp_path, cases, denylist=["acmecorp"])
    parent = json.loads((tmp_path / STAMP / "PARENT_SUMMARY.json").read_text(encoding="utf-8"))
    assert parent["brief_revision"] == 3
    flagged = {v["case_id"] for v in report["violations"] if v["code"] == "brief_revision_mismatch"}
    written = json.loads((tmp_path / STAMP / "cases.json").read_text(encoding="utf-8"))
    assert flagged == {c["case_id"] for c in written if c["brief_revision"] == 2}
    assert flagged and cases[0]["case_id"] not in flagged


def test_a_uniform_rev2_batch_has_no_revision_mismatch(tmp_path):
    report = _validate(tmp_path, [_resolve("ek")], denylist=["acmecorp"])
    assert "brief_revision_mismatch" not in {v["code"] for v in report["violations"]}, _show(report)


def test_an_honest_uniform_v3_pilot_validates(tmp_path):
    """Regression guard: the brief v3 pilot shape (three R0 controls, all brief_revision 3) passes every new rule."""
    cases = [_rev3(_resolve("t1")), _rev3(_resolve("t0")), _v3_ctrl_neg()]
    report = _validate(tmp_path, cases, denylist=["acmecorp"])
    assert json.loads((tmp_path / STAMP / "PARENT_SUMMARY.json").read_text(encoding="utf-8"))["brief_revision"] == 3
    assert report["violations"] == [], _show(report)
    assert report["ok"] is True


# --------------------------------------------------------------------------
# V8: validate --self-check (Grok's own run, before VALIDATION.self.json and DONE.json exist)
# --------------------------------------------------------------------------
def test_self_check_skips_only_the_done_and_self_validation_presence_rules(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")], delete=["DONE.json", "VALIDATION.self.json"])
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out), "--self-check"]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["self_check"] is True
    assert written["violations"] == [], written["violations"]
    assert written["ok"] is True


def test_without_self_check_a_missing_done_is_still_done_missing(tmp_path):
    root = _make_batch(tmp_path, [_resolve("ek")], delete=["DONE.json", "VALIDATION.self.json"])
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out)]) == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["self_check"] is False
    hits = {(v["code"], v["file"]) for v in written["violations"]}
    assert {("done_missing", "DONE.json"), ("file_missing", "DONE.json"), ("file_missing", "VALIDATION.self.json")} <= hits
    assert written["ok"] is False


def test_self_check_keeps_every_other_rule(tmp_path):
    root = _make_batch(
        tmp_path, [_resolve("ek")], delete=["VALIDATION.self.json", "README.md"], done_edit=[("/stamp", "20250101_0000_r2")]
    )
    out = tmp_path / "VALIDATION.json"
    assert eb.main(["validate", str(root), "--out", str(out), "--self-check"]) == 1
    written = json.loads(out.read_text(encoding="utf-8"))
    hits = {(v["code"], v["file"]) for v in written["violations"]}
    assert ("file_missing", "README.md") in hits
    assert ("done_stamp_mismatch", "DONE.json") in hits  # a DONE.json that is present is still checked
    assert ("file_missing", "VALIDATION.self.json") not in hits
    assert written["self_check"] is True


def test_validate_batch_always_reports_self_check(tmp_path):
    report = _validate(tmp_path, [_resolve("ek")])
    assert report["self_check"] is False


# --------------------------------------------------------------------------
# R7-1: a tj_run's growth strip is sized by the INK displacement (brief v3)
# --------------------------------------------------------------------------
# Sign convention (TJ): a positive kern moves the next glyph LEFT, so the internal kerns a tj_run drops made the
# old ink K_sum * Tfs / 1000 narrower than adv_old; the new ink therefore outgrows the target box by
# displacement_ink = (adv_new - adv_old) + K_sum * Tfs / 1000 text-space units, not by the advance delta alone.
F2G_TFS = 24.0
F2G_ADV_OLD, F2G_ADV_NEW = 18.0, 24.0
F2G_T_RIGHT = 117.28


def _f2g_tj_run(
    kern: float = 30.0,
    *,
    strip: str = "ink",
    rev: int = 3,
    adv_new: float = F2G_ADV_NEW,
    class_id: str = "F2G",
    variant: str = "grow",
    repl: str = "abcd",
) -> dict:
    """An honest brief-v3 F2G experiment: ``(ab) <kern> (c)`` inside a TJ array becomes ``(<repl>) K`` at Tf 24.

    Under rev 3 the row carries ``advance.displacement_ink`` and the ink-sized ``growth_pt`` (brief 3.3 R7-1) and its
    applicability is ``displacement_ink > advance_tolerance``; under rev 2 it is the old delta-sized row.
    """
    delta = adv_new - F2G_ADV_OLD
    ink = delta + kern * F2G_TFS / 1000.0
    T = [100.0, 688.0, F2G_T_RIGHT, 700.0]
    A = [100.0, 688.0, F2G_T_RIGHT + ink, 700.0]
    V = [100.0, 688.0, F2G_T_RIGHT + (ink if strip == "ink" else delta), 700.0]
    BG = [100.0, 683.8, F2G_T_RIGHT, 700.0]
    k_eng = 1000.0 * delta / F2G_TFS
    k_written = kern + k_eng
    old = f"(ab) {kern:g} (c)".encode("ascii")
    new = f"({repl}) ".encode("ascii") + f"{k_written:.6f}".encode("ascii")
    case = _mut_case(
        class_id=class_id, kind="positive", variant=variant, slug="multicolumn", page=0, show=3, provenance="public",
        rel="test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf", orig="abc", repl=repl, font_kind="simple",
        font_resource="F1", basefont="CMR10", path="experiment", method_id=f"E_{class_id}", splice_kind="tj_run",
        operator="TJ", new_op=new, old_op=old, op_start=5000, op_end=5000 + len(old) + 5, change_end_old=5000 + len(old),
        adv_old=F2G_ADV_OLD, adv_new=adv_new, tfs=F2G_TFS, tz=100.0, trm=1.0, uu=1.0, rotation=0, source_kind="Widths",
        k_written=k_written, tier=1, T=T, A=A, V=V, BG=BG, outcome="refuse", calibration_ref="pass",
        leg="glyph_name_agl", selected_by="glyph_name",
        probe_t1=_probe_result("rejected", None, "tj_multi_item_array", "target spans several TJ items"),
        probe_t0=_probe_result("rejected", None, "tj_multi_item_array", "target spans several TJ items"),
        commit={"attempted": False, "status": None, "tier": None, "font_actions": []},
        decode={"latin1": "abc", "latin1_sha256": _h("abc"), "independent": "abc", "independent_sha256": _h("abc"), "leg": "glyph_name_agl", "agrees": True},
        lineage="multicolumn",
    )
    adv = case["mutation"]["advance"]
    adv["K_sum"] = kern
    adv["internal_kerns_dropped"] = [kern]
    adv["abs_diff_written_vs_sum_engine"] = abs(k_written - (kern + k_eng))
    case["target"]["string_kind"] = "array"
    case["target"]["array_item_count"] = 3
    if rev == 3:
        adv["displacement_ink"] = ink
        adv["growth_pt"] = max(0.0, ink)  # Th = trm_scale = user_unit = 1
        case["growth_zone"] = _growth_on(T, V, BG) if ink > adv["advance_tolerance"] else _growth_off()
        case["target"]["verify_bbox_visual"] = V
    return _patch(case, ("/brief_revision", rev))


def _growth_codes(case: dict) -> set[str]:
    return {v.code for v in eb.check_growth_zone(case).violations}


def _all_static(case: dict) -> list:
    out = []
    for fn in (eb.check_growth_zone, eb.check_advance, eb.check_operand_grammar, eb.check_cross_field):
        res = fn(case)
        out += [(v.code, v.pointer) for v in res.violations]
        out += [("fail", phase, tuple(r)) for phase, r in res.fails.items()]
        out += [("not_run", phase, tuple(r)) for phase, r in res.not_run.items()]
    return out


def test_an_honest_v3_tj_run_with_tightening_kerns_validates():
    """+30 kerns at Tf 24: the ink outgrows the advance delta by 0.72 pt, past the 0.5 pt own-char tolerance."""
    assert _all_static(_f2g_tj_run(30.0)) == []


def test_a_v3_tj_run_with_loosening_kerns_is_sized_by_the_smaller_ink_growth():
    """-30 kerns: the old ink was 0.72 pt WIDER than adv_old, so the strip shrinks by that much (the sign is tested)."""
    assert _all_static(_f2g_tj_run(-30.0)) == []
    assert "verify_bbox_mismatch" in _growth_codes(_f2g_tj_run(-30.0, strip="delta"))


def test_a_v3_tj_run_strip_sized_by_the_delta_alone_is_rejected():
    """The wrong strip is a bundle defect; the ink past it is the growth_zone phase fail (V10), not a second violation."""
    res = eb.check_growth_zone(_f2g_tj_run(30.0, strip="delta"))
    codes = {v.code for v in res.violations}
    assert "verify_bbox_mismatch" in codes and "growth_after_exceeds_verify" not in codes
    assert res.fails == {"growth_zone": ["after_exceeds_verify"]}


def test_the_same_tj_run_at_rev2_keeps_the_delta_sized_strip():
    """The v3 sizing is gated on the row's own brief_revision: a rev2 row is judged exactly as before."""
    assert "verify_bbox_mismatch" in _growth_codes(_f2g_tj_run(30.0, rev=2))
    assert _growth_codes(_f2g_tj_run(30.0, strip="delta", rev=2)) == {"growth_after_exceeds_verify"}


def test_a_non_public_v3_tj_run_sizes_its_strip_by_the_recorded_k_sum():
    """Brief 5.4 nulls old_operand_bytes_hex on a non-public row; the recorded K_sum (rederive checks it) stands in."""
    case = _patch(_f2g_tj_run(30.0), ("/mutation/changes/0/old_operand_bytes_hex", None))
    res = eb.check_growth_zone(case)
    assert res.violations == [] and res.fails == {} and res.not_run == {}


def test_a_v3_tj_run_without_any_kern_source_is_undecided_not_guessed():
    case = _patch(
        _f2g_tj_run(30.0), ("/mutation/changes/0/old_operand_bytes_hex", None), ("/mutation/advance/K_sum", None)
    )
    res = eb.check_growth_zone(case)
    assert res.not_run.get("growth_zone") == ["ink_kerns_unknown"]
    assert "verify_bbox_mismatch" not in {v.code for v in res.violations}


def test_the_bytes_win_over_a_forged_k_sum_when_sizing_the_strip():
    """A public row's old operand says 30; a recorded K_sum of 300 may not widen the strip it is judged against."""
    case = _patch(_f2g_tj_run(30.0), ("/mutation/advance/K_sum", 300.0))
    assert "verify_bbox_mismatch" not in _growth_codes(case)


def test_a_v3_tj_item_never_reads_a_recorded_k_sum_into_its_strip():
    """A tj_item drops no kern, so its ink grows by the delta alone whatever K_sum claims."""
    case = _patch(_f2g_tj_run(30.0), ("/mutation/splice_kind", "tj_item"))
    assert "verify_bbox_mismatch" in _growth_codes(case)
    honest = _patch(_f2g_tj_run(30.0, strip="delta"), ("/mutation/splice_kind", "tj_item"), ("/target/after_bbox_visual/2", F2G_T_RIGHT + 6.0))
    assert "verify_bbox_mismatch" not in _growth_codes(honest)


def test_the_ink_displacement_helper_follows_the_tj_sign():
    assert eb._ink_displacement(6.0, 30.0, 24.0) == pytest.approx(6.72)
    assert eb._ink_displacement(6.0, -30.0, 24.0) == pytest.approx(5.28)
    assert eb._ink_displacement(6.0, 0.0, 24.0) == 6.0


def _advance_codes(case: dict) -> set[str]:
    return {v.code for v in eb.check_advance(case).violations}


def _schema_hits(case: dict) -> list[tuple[str, str]]:
    schema = eb.load_schema(SCHEMA_DIR / "true_text_case.v2.schema.json")
    row = {k: v for k, v in case.items() if k != "_records"}  # the fixture's neighbour records ride along off-schema
    found = eb.validate_instance(row, schema) + eb.check_revision_schema(row)
    return [(v.code, v.pointer) for v in found]


def test_the_brief_v3_honest_f2g_row_passes_the_case_schema():
    """Brief 5.1 lists advance.displacement_ink: a v3 row that carries it is not a schema_additional."""
    case = _f2g_tj_run(30.0)
    assert case["mutation"]["advance"]["displacement_ink"] == pytest.approx(6.72)
    assert _schema_hits(case) == []


def test_a_rev2_row_carrying_displacement_ink_keeps_the_v2_schema_violation():
    case = _patch(_f2g_tj_run(30.0, rev=2), ("/mutation/advance/displacement_ink", 6.72))
    assert ("schema_additional", "/mutation/advance/displacement_ink") in _schema_hits(case)
    assert _schema_hits(_f2g_tj_run(30.0, rev=2)) == []


def test_a_v3_mutation_without_displacement_ink_is_rejected():
    case = _f2g_tj_run(30.0)
    del case["mutation"]["advance"]["displacement_ink"]
    assert "displacement_ink_missing" in _advance_codes(case)


def test_a_v3_displacement_ink_that_differs_from_delta_plus_kerns_is_rejected():
    assert "displacement_ink_mismatch" in _advance_codes(_patch(_f2g_tj_run(30.0), ("/mutation/advance/displacement_ink", 6.0)))
    # the bytes win over a forged K_sum here too: the old operand says 30
    forged = _patch(_f2g_tj_run(30.0), ("/mutation/advance/K_sum", 300.0), ("/mutation/advance/displacement_ink", 13.2))
    assert "displacement_ink_mismatch" in _advance_codes(forged)


def test_a_v3_tj_run_growth_pt_sized_by_the_delta_alone_is_rejected():
    case = _patch(_f2g_tj_run(30.0), ("/mutation/advance/growth_pt", F2G_ADV_NEW - F2G_ADV_OLD))
    assert "growth_pt_mismatch" in _advance_codes(case)
    assert "growth_pt_mismatch" not in _advance_codes(_f2g_tj_run(30.0, rev=2))


def test_an_f2r_shaped_v3_row_with_tightening_kerns_is_applicable_and_validates():
    """Equal advances, +30 kern at Tf 24: the ink still grows 0.72 pt, so the row is applicable and its strip is 0.72 pt."""
    case = _f2g_tj_run(30.0, adv_new=F2G_ADV_OLD, class_id="F2R", variant="eq", repl="acb")
    assert case["growth_zone"]["applicable"] is True
    assert _all_static(case) == []
    declared_off = _patch(case, ("/growth_zone", _growth_off()))
    assert "growth_applicable_mismatch" in _growth_codes(declared_off)


def test_a_v3_row_whose_loosening_kerns_cancel_the_delta_is_not_applicable():
    """delta 0.5 > tol but -30 kern at Tf 24 gives displacement_ink -0.22: no ink growth, so applicable is false."""
    case = _f2g_tj_run(-30.0, adv_new=F2G_ADV_OLD + 0.5)
    assert case["growth_zone"]["applicable"] is False
    assert _all_static(case) == []
    # rev 2 keeps the delta rule, under which this honest row is applicable and its after box never grows
    assert "growth_after_not_grown" in _growth_codes(_f2g_tj_run(-30.0, adv_new=F2G_ADV_OLD + 0.5, rev=2))


def test_a_non_public_v3_tj_run_marks_its_k_sum_unverified_for_rederive():
    case = _patch(_f2g_tj_run(30.0), ("/mutation/changes/0/old_operand_bytes_hex", None))
    res = eb.check_advance(case)
    assert res.violations == []
    assert "k_sum_unverified" in {u.code for u in res.unverifiable}
    assert "k_sum_unverified" in _rd_recomputed_codes()
    assert "k_sum_unverified" not in {u.code for u in eb.check_advance(_f2g_tj_run(30.0)).unverifiable}


def _rd_recomputed_codes() -> tuple[str, ...]:
    pytest.importorskip("fitz")
    from scripts import evidence_rederive as rd

    return rd.RECOMPUTED_CODES


# --------------------------------------------------------------------------
# V9 (brief change (m)): a null consistency (no non-target occurrence in the same font xref) is not a not_run
# --------------------------------------------------------------------------
def _null_consistency(case: dict) -> dict:
    """The CTRL_SYN_T0 shape of 20261024_1803_r2: the replacement occurs only in the target show, so (b) has nothing to compare."""
    out = copy.deepcopy(case)
    for g in out["glyph_identity"]:
        g["consistency"] = None
        g["gid_equals_consistency"] = None
    return out


def _gi(case: dict) -> eb.PhaseCheck:
    res = eb.check_glyph_identity(case)
    return eb._combine(res.fails.get("glyph_identity", []), res.not_run.get("glyph_identity", []), None)


def _gi_codes(case: dict) -> set[tuple[str, str]]:
    return {(v.code, v.pointer) for v in eb.check_glyph_identity(case).violations}


def _st0(rev: int) -> dict:
    return _ctrl_syn_t0() if rev == 2 else _rev3(_ctrl_syn_t0())


@pytest.mark.parametrize("rev", [2, 3])
def test_a_null_consistency_with_an_honest_leg_recomputes_glyph_identity_pass(rev):
    """(b) applies only when a non-target occurrence exists; (a) and the independent leg decide, in both brief revisions."""
    case = _null_consistency(_st0(rev))
    assert _gi(case) == eb.PhaseCheck("pass")
    assert _gi_codes(case) == set()


def test_ctrl_syn_t0_with_null_consistency_satisfies_a_full_r0_calibration(tmp_path):
    """The pinned fixture (tail 後綴) offers no non-target 再/見, so the synthetic control must still be able to pass nine phases."""
    report = _validate(tmp_path, [_null_consistency(_ctrl_syn_t0()), _resolve("ek")])
    assert report["violations"] == [], _show(report)
    assert report["recomputed"]["calibration"]["controls"]["CTRL_SYN_T0"]["ok"] is True
    assert report["recomputed"]["calibration"]["status"] == "pass"


def test_a_rev3_ctrl_syn_t0_with_null_consistency_validates(tmp_path):
    report = _validate(tmp_path, [_null_consistency(_rev3(_ctrl_syn_t0()))])
    assert report["violations"] == [], _show(report)
    assert report["recomputed"]["calibration"]["controls"]["CTRL_SYN_T0"]["ok"] is True


def test_a_rev3_leg_whose_value_is_another_character_fails_despite_equals_char_true():
    """Tightening t1: equals_char is recomputed from value == char (the 1803 CANARY_WRONGGLYPH shape with a lying note)."""
    case = _patch(_null_consistency(_st0(3)), (LEG0 + "/value", "1"), (LEG0 + "/equals_char", True))
    assert _gi(case) == eb.PhaseCheck("fail", ("leg_char_differs",))
    assert ("glyph_note_mismatch", LEG0 + "/equals_char") in _gi_codes(case)


def test_a_rev3_leg_without_a_value_cannot_claim_equals_char():
    case = _patch(_null_consistency(_st0(3)), (LEG0 + "/value", None), (LEG0 + "/equals_char", True))
    assert _gi(case) == eb.PhaseCheck("fail", ("leg_char_differs",))


def test_a_rev3_leg_lie_fails_with_a_dict_consistency_too():
    """The real 1803 CANARY_WRONGGLYPH keyed consistency on the written CID (gid equal), so (b) passed; the leg still catches it."""
    case = _patch(_st0(3), (LEG0 + "/value", "1"), (LEG0 + "/equals_char", True))
    assert _gi(case) == eb.PhaseCheck("fail", ("leg_char_differs",))


@pytest.mark.parametrize("rev", [2, 3])
def test_an_1803_shaped_wrong_glyph_record_with_an_honest_note_stays_caught(rev):
    case = _patch(_st0(rev), (LEG0 + "/value", "1"), (LEG0 + "/equals_char", False))
    assert _gi(case) == eb.PhaseCheck("fail", ("leg_char_differs",))
    assert _gi_codes(case) == set()
    assert _gi(_null_consistency(case)) == eb.PhaseCheck("fail", ("leg_char_differs",))


def test_a_rev3_glyph_char_must_be_the_replacement_character():
    """Tightening t2: char is bound to replacement[index]; without it, recomputing equals_char against char means nothing."""
    case = _patch(_null_consistency(_st0(3)), ("/glyph_identity/0/char", "再"), (LEG0 + "/value", "再"))
    assert ("glyph_identity_char", "/glyph_identity/0/char") in _xcodes(case)
    assert ("glyph_identity_char", "/glyph_identity/1/char") not in _xcodes(case)


def test_a_rev3_null_consistency_needs_a_null_self_note():
    """Tightening t3: with no occurrence no comparison ran, so gid_equals_consistency cannot be a boolean."""
    case = _patch(_null_consistency(_st0(3)), ("/glyph_identity/0/gid_equals_consistency", False))
    assert ("glyph_note_mismatch", "/glyph_identity/0/gid_equals_consistency") in _gi_codes(case)
    assert _gi(case) == eb.PhaseCheck("pass")  # a note defect is a violation, never a phase verdict


def test_the_three_tightenings_are_gated_on_brief_revision_3():
    """A revision-2 row keeps today's behaviour exactly: the note is trusted, char is unbound, no null-note rule."""
    lie = _patch(_null_consistency(_st0(2)), (LEG0 + "/value", "1"), (LEG0 + "/equals_char", True))
    assert _gi(lie) == eb.PhaseCheck("pass")
    assert _gi_codes(lie) == set()
    drift = _patch(_null_consistency(_st0(2)), ("/glyph_identity/0/char", "再"))
    assert ("glyph_identity_char", "/glyph_identity/0/char") not in _xcodes(drift)
    note = _patch(_null_consistency(_st0(2)), ("/glyph_identity/0/gid_equals_consistency", True))
    assert _gi_codes(note) == set()


@pytest.mark.parametrize(
    ("edits", "expected"),
    [
        ([(LEG0 + "/gid", 999)], eb.PhaseCheck("fail", ("leg_gid_differs",))),
        ([(LEG0 + "/kind", "none")], eb.PhaseCheck("not_run", ("no_independent_leg",))),
        ([(LEG0 + "/kind", "glyph_name_agl")], eb.PhaseCheck("not_run", ("no_independent_leg",))),
        ([("/glyph_identity/0/gid_after", 0), (LEG0 + "/gid", 0)], eb.PhaseCheck("fail", ("gid_zero_or_missing", "leg_gid_differs"))),
        ([("/glyph_identity/0/has_outline", None)], eb.PhaseCheck("fail", ("no_outline",))),
    ],
    ids=["leg_gid", "leg_none", "leg_wrong_kind", "gid_zero", "no_outline"],
)
@pytest.mark.parametrize("rev", [2, 3])
def test_a_null_consistency_leaves_every_other_glyph_rule_in_force(rev, edits, expected):
    assert _gi(_patch(_null_consistency(_st0(rev)), *edits)) == expected


@pytest.mark.parametrize("value", [5, "x", True, _DEL], ids=["int", "str", "bool", "missing"])
def test_a_malformed_consistency_stays_undecided(value):
    """A non-null non-dict or a missing key is no evidence either way: undecided (the schema rejects the row as well)."""
    case = _patch(_null_consistency(_st0(3)), ("/glyph_identity/0/consistency", value))
    assert _gi(case) == eb.PhaseCheck("not_run", ("consistency_malformed",))


def test_canaries_with_null_consistency_stay_caught(tmp_path):
    """CANARY_FONT and CANARY_WRONGGLYPH are caught by leg_gid_differs, so (b) having nothing to compare changes nothing."""
    report = _validate(tmp_path, [_null_consistency(_resolve("font")), _null_consistency(_resolve("wrong")), _resolve("ek")])
    assert report["violations"] == [], _show(report)
    canaries = report["recomputed"]["calibration"]["canaries"]
    assert canaries["CANARY_FONT"]["caught"] is True
    assert canaries["CANARY_WRONGGLYPH"]["caught"] is True
    # the retired code never comes back as a reason for the old (null consistency) shape
    res = eb.check_glyph_identity(_null_consistency(_resolve("font")))
    assert "no_consistency_occurrence" not in {r for reasons in (*res.not_run.values(), *res.fails.values()) for r in reasons}


def test_a_rev3_glyph_with_a_null_is_space_and_a_drifted_char_raises_both_cross_field_codes():
    """V9 nit (n2): the char binding fires whenever is_space is not True; a null is_space cannot hide a drifted char."""
    case = _patch(_null_consistency(_st0(3)), ("/glyph_identity/0/is_space", None), ("/glyph_identity/0/char", "再"))
    codes = _xcodes(case)
    assert ("glyph_identity_is_space", "/glyph_identity/0/is_space") in codes
    assert ("glyph_identity_char", "/glyph_identity/0/char") in codes
    spaced = _patch(_null_consistency(_st0(3)), ("/glyph_identity/0/is_space", True), ("/glyph_identity/0/char", "再"))
    assert ("glyph_identity_char", "/glyph_identity/0/char") not in _xcodes(spaced)  # a space glyph is skipped by (a)-(c)


# --------------------------------------------------------------------------
# V10: under brief v3 a geometry spill is a growth_zone phase fail, never a bundle rejection
# --------------------------------------------------------------------------
def _apply(case: dict, *edits) -> dict:
    """``_patch`` that also resolves callable edit values (the ``_make_batch`` convention) against the case itself."""
    for pointer, value in edits:
        case = _patch(case, (pointer, value(case) if callable(value) else value))
    return case


SPILL_DETAIL = "not applicable, but the after bbox grew 6.00000 pt on the main edge"


def _equal_width_spill(rev: int, *, recorded: str = "fail") -> dict:
    """ek written honestly as an equal-width ``string_token`` splice whose after box is 6 pt wider than the target box.

    The CANARY_FONT shape of 20261024_1803_r2: the advance measured with the target font's /W is equal (displacement_ink
    0), nothing in the record contradicts itself, but the texttrace after box spills past the target box.  The equal-width
    edits come BEFORE ``_rev3`` so displacement_ink is derived from the equal advances.  The raw after box keeps ek's
    wider union of the target records (``after_bbox_frame`` is one-directional: raw growing while visual does not).
    """
    detail = SPILL_DETAIL if recorded == "fail" else "no ink growth"
    status = "probe_rejected" if recorded == "fail" else "insufficient_evidence"
    case = _apply(
        _resolve("ek"), *_equal_width_edits(), ("/mutation/splice_kind", "string_token"), (OP, _op(lambda s: "(abc)")),
        ("/phases/growth_zone", _phase(recorded, detail)), ("/status", status),
    )
    return _rev3(case) if rev == 3 else case


def _rev3_pack(row: dict, *, font: dict | None = None) -> list[dict]:
    """``row`` plus the R0 pack rewritten under brief v3 (null-mutation rows take the v3 null form)."""
    out = []
    for c in _with_r0([row]):
        if c is row:
            out.append(c)
        elif c["class_id"] == "CTRL_NEG":
            out.append(_v3_ctrl_neg())
        elif c["class_id"] == "CANARY_FONT" and font is not None:
            out.append(font)
        elif c["mutation"] is None:
            out.append(_null_counters(_rev3(c)))
        else:
            out.append(_rev3(c))
    return out


def _gz(case: dict) -> tuple[set[str], dict, dict]:
    res = eb.check_growth_zone(case)
    return {v.code for v in res.violations}, dict(res.fails), dict(res.not_run)


def test_a_rev3_equal_width_row_whose_after_box_spills_is_a_growth_zone_fail_not_a_rejection(tmp_path):
    """The honest record (growth_zone fail with the extent in detail) validates with an EMPTY violation set."""
    row = _equal_width_spill(3)
    assert _gz(row) == (set(), {"growth_zone": ["after_exceeds_target"]}, {})
    report = _validate(tmp_path, _rev3_pack(row), denylist=["acmecorp"], r0=False)
    assert report["violations"] == [], _show(report)
    assert report["recomputed"]["statuses"][row["case_id"]] == "probe_rejected"  # rule 7: a fail blocks rules 5/6


def test_the_rev3_twin_that_records_growth_zone_pass_over_a_spill_is_exactly_a_phase_mismatch(tmp_path):
    row = _equal_width_spill(3, recorded="pass")
    report = _validate(tmp_path, _rev3_pack(row), denylist=["acmecorp"], r0=False)
    assert {(v["code"], v["pointer"]) for v in report["violations"]} == {("phase_result_mismatch", "/phases/growth_zone/result")}, _show(report)


def test_the_same_spill_under_brief_v2_keeps_the_bundle_violation_and_recomputes_pass(tmp_path):
    """brief_revision 2 behaves byte for byte as before: a violation, no phase verdict."""
    row = _equal_width_spill(2, recorded="pass")
    assert _gz(row) == ({"growth_after_exceeds_target"}, {}, {})
    report = _validate(tmp_path, [_patch(row, ("/status", "save_reopen_pass"))])
    assert {(v["code"], v["pointer"]) for v in report["violations"]} == {("growth_after_exceeds_target", "/target/after_bbox_visual")}, _show(report)
    assert report["recomputed"]["statuses"][row["case_id"]] == "save_reopen_pass"


@pytest.mark.parametrize("rev", [2, 3])
def test_the_half_point_spill_threshold_is_strict_at_float_exact_coordinates(rev):
    """Built from the coordinates PyMuPDF wrote for hvac p4 s11, so float64 rounding cannot flip the strict '>'."""
    x1 = 451.96392822265625
    T = [383.820068359375, 213.4339599609375, x1, 220.1832275390625]

    def outcome(extent: float):
        A = [T[0], T[1], x1 + extent, T[3]]
        case = _patch(_equal_width_spill(rev), ("/target/target_bbox_visual", T), ("/target/after_bbox_visual", A), ("/render/halo_area_pt2", _halo(T, A)))
        codes, fails, not_run = _gz(case)
        assert not_run == {}
        return codes, fails

    assert outcome(0.0) == (set(), {})
    assert outcome(0.5 - 1e-6) == (set(), {})
    assert outcome(0.5) == (set(), {})
    assert outcome(0.5 + 1e-3) == ((set(), {"growth_zone": ["after_exceeds_target"]}) if rev == 3 else ({"growth_after_exceeds_target"}, {}))
    assert outcome(6.09808) == outcome(0.5 + 1e-3)


@pytest.mark.parametrize("rev", [2, 3])
def test_an_applicable_after_box_that_did_not_grow_is_a_phase_fail_and_a_violation_only_under_v2(rev):
    case = _apply(_resolve("ek"), *_after_equals_target_edits())
    case = _rev3(case) if rev == 3 else case
    codes, fails, not_run = _gz(case)
    assert (fails, not_run) == ({"growth_zone": ["after_not_grown"]}, {})
    assert codes == ({"growth_after_not_grown"} if rev == 2 else set())


@pytest.mark.parametrize("rev", [2, 3])
def test_an_applicable_after_box_past_the_verify_box_is_a_phase_fail_and_a_violation_only_under_v2(rev):
    base = _rev3(_resolve("ek")) if rev == 3 else _resolve("ek")
    T, A = base["target"]["target_bbox_visual"], [100.0, 688.0, 118.0, 700.0]
    case = _patch(base, ("/target/after_bbox_visual", A), ("/render/halo_area_pt2", _halo(T, A)))
    codes, fails, not_run = _gz(case)
    assert (fails, not_run) == ({"growth_zone": ["after_exceeds_verify"]}, {})
    assert codes == ({"growth_after_exceeds_verify"} if rev == 2 else set())


def _font_canary_spill(rev: int) -> dict:
    """CANARY_FONT as 20261024_1803_r2 recorded it: equal advance under the wrong font, after box 6.09808 pt wider."""
    case = _resolve("font")
    T = case["target"]["target_bbox_visual"]
    A = [T[0], T[1], T[2] + 6.09808, T[3]]
    case = _patch(
        case, ("/target/after_bbox_visual", A), ("/render/halo_area_pt2", _halo(T, A)),
        ("/phases/growth_zone", _phase("fail", "not applicable, but the after bbox grew 6.09808 pt on the main edge")),
    )
    return _rev3(case) if rev == 3 else case


def test_a_rev3_canary_font_that_spills_is_caught_with_growth_zone_among_its_failed_phases(tmp_path):
    """The deterministic hvac spill: recorded failed_phases including growth_zone match the recomputation, caught stays true."""
    canary = _font_canary_spill(3)
    report = _validate(tmp_path, [canary], denylist=["acmecorp"])
    assert report["violations"] == [], _show(report)
    row = report["recomputed"]["calibration"]["canaries"]["CANARY_FONT"]
    assert row["caught"] is True
    assert row["failed_phases"] == ["structure", "growth_zone", "glyph_identity"]


def test_a_full_rev3_r0_run_with_the_spilling_canary_font_calibrates(tmp_path):
    """Every full rev-3 R0 run on hvac carries this canary, so the whole pack must stay green around it."""
    report = _validate(tmp_path, _rev3_pack(_rev3(_resolve("ek")), font=_font_canary_spill(3)), denylist=["acmecorp"], r0=False)
    assert report["violations"] == [], _show(report)
    assert report["recomputed"]["calibration"]["status"] == "pass"
    assert report["recomputed"]["calibration"]["canaries"]["CANARY_FONT"]["caught"] is True


def test_a_rev2_canary_font_that_spills_is_still_a_bundle_rejection(tmp_path):
    report = _validate(tmp_path, [_font_canary_spill(2)])
    assert ("growth_after_exceeds_target", "/target/after_bbox_visual") in _hits(report), _show(report)
    assert ("phase_result_mismatch", "/phases/growth_zone/result") in _hits(report)


def test_a_rev3_tier0_product_commit_whose_after_box_spills_lands_at_insufficient_evidence():
    """A product row (Tier 0: the verify box IS the target box, plan._grown_verify_bbox) that spills is rule 8, never a pass."""
    case = _rev3(_resolve("t0"))
    T = case["target"]["target_bbox_visual"]
    A = [T[0], T[1], T[2] + 6.0, T[3]]
    case = _patch(case, ("/target/after_bbox_visual", A), ("/render/halo_area_pt2", _halo(T, A)), ("/phases/growth_zone", _phase("fail", SPILL_DETAIL)))
    records = case.pop("_records")
    phases, res = eb.recompute_phase_results(case, records)
    assert [v.code for v in res.violations] == []
    assert phases["growth_zone"] == eb.PhaseCheck("fail", ("after_exceeds_target",))
    for calibration in ("pass", "fail"):
        status = eb.recompute_status(case, phases, calibration_status=calibration, pre_registered=True, case_violations=res.violations)
        assert status == "insufficient_evidence"


# --------------------------------------------------------------------------
# V11: a plan row that fails the plan schema rejects the cases citing it, never the batch
# --------------------------------------------------------------------------
PLAN_FILE = "METHODS_AND_EVIDENCE_PLAN.md"


def _ek_batch(tmp_path: Path, rev: int, plan_edits) -> dict:
    """The honest ek row plus its R0 pack under brief revision ``rev``; row 0 of the plan block is ek."""
    if rev == 3:
        return _validate(tmp_path, _rev3_pack(_rev3(_resolve("ek")), font=_font_canary_spill(3)), denylist=["acmecorp"], r0=False, plan_edits=plan_edits)
    return _validate(tmp_path, _expand(["ek"]), plan_edits=plan_edits)


def _plan_rows() -> list[dict]:
    return _plan_object(_with_r0(_expand(["ek"])))["cases"]


def _plan_entries(report: dict, key: str) -> list[dict]:
    return [v for v in report[key] if v["file"] == PLAN_FILE]


@pytest.mark.parametrize("rev", [2, 3])
@pytest.mark.parametrize(
    ("pointer", "value", "code", "detail"),
    [
        ("/cases/0/hypotheses", ["a", "b", "c", "d"], "schema_max_items", "array longer than allowed"),
        ("/cases/0/method_id", "E_BOGUS", "schema_enum", "value is outside the allowed vocabulary"),
    ],
)
def test_a_plan_row_violation_is_attributed_to_the_case_that_cites_the_row(tmp_path, rev, pointer, value, code, detail):
    """Brief 6.1 scopes registration per case: the row still registers, the violation names the citing case."""
    ek_id = _resolve("ek")["case_id"]
    honest = _ek_batch(tmp_path / "honest", rev, [])
    assert honest["violations"] == [], _show(honest)
    report = _ek_batch(tmp_path / "row", rev, [(pointer, value)])
    assert report["violations"] == [{"code": code, "file": PLAN_FILE, "pointer": pointer, "detail": detail, "case_id": ek_id}], _show(report)
    assert report["ok"] is False
    assert _plan_entries(report, "unverifiable") == []
    # no artificial pre_registered_mismatch: the registration flag and every status are those of the honest batch
    assert report["recomputed"]["statuses"] == honest["recomputed"]["statuses"]


def test_a_row_violation_is_attributed_to_every_case_sharing_the_row_key(tmp_path):
    """<variant>1 and <variant>2 register under the same variant, so one bad row names both (fail closed, one entry each)."""
    ek = _resolve("ek")
    twin = _patch(ek, ("/case_id", re.sub(r"1$", "2", ek["case_id"])))
    assert twin["case_id"] != ek["case_id"] and eb._variant_of(twin["case_id"]) == eb._variant_of(ek["case_id"])
    report = _validate(tmp_path, [ek, twin], plan_edits=[("/cases/0/hypotheses", ["a", "b", "c", "d"]), ("/cases/1", _DEL)])
    plan = _plan_entries(report, "violations")
    assert [(v["pointer"], v["case_id"]) for v in plan] == [("/cases/0/hypotheses", ek["case_id"]), ("/cases/0/hypotheses", twin["case_id"])], _show(report)
    assert all(v["case_id"] is not None for v in report["violations"]), _show(report)


def test_a_malformed_plan_row_that_no_case_cites_is_unverifiable_plan_row_invalid(tmp_path):
    """A registered-but-never-run row with a dotted slug taints nothing: the batch validates ok, the row is listed."""
    rows = _plan_rows()
    bad = dict(rows[0], slug="ua2-8.2.5.20-x")
    report = _validate(tmp_path, _expand(["ek"]), plan_edits=[("/cases", rows + [bad])])
    assert report["violations"] == [], _show(report)
    assert report["ok"] is True
    assert report["pending_rederive"] is True
    items = _plan_entries(report, "unverifiable")
    assert [(u["code"], u["pointer"], u["case_id"]) for u in items] == [("plan_row_invalid", f"/cases/{len(rows)}/slug", None)]
    assert "schema_pattern" in items[0]["detail"] and str(len(rows)) in items[0]["detail"]


def test_a_plan_level_violation_outside_a_row_stays_batch_level(tmp_path):
    """The same batch: the /pre_registration const is nobody's, the row defect is ek's."""
    ek_id = _resolve("ek")["case_id"]
    report = _validate(tmp_path, _expand(["ek"]), plan_edits=[("/pre_registration", "x"), ("/cases/0/hypotheses", ["a", "b", "c", "d"])])
    assert {(v["code"], v["pointer"], v["case_id"]) for v in report["violations"]} == {
        ("schema_const", "/pre_registration", None),
        ("schema_max_items", "/cases/0/hypotheses", ek_id),
    }, _show(report)
    assert _plan_entries(report, "unverifiable") == []


def test_a_plan_row_with_an_unhashable_key_field_is_a_row_defect_not_a_check_error(tmp_path):
    """Same bug class: a list in a key field used to raise TypeError inside the registered dict (check_error, batch blocked)."""
    ek_id = _resolve("ek")["case_id"]
    report = _validate(tmp_path, _expand(["ek"]), plan_edits=[("/cases/0/slug", ["x"])])
    codes = {(v["code"], v["case_id"]) for v in report["violations"]}
    assert not any(code == "check_error" for code, _ in codes), _show(report)
    assert ("pre_registered_mismatch", ek_id) in codes, _show(report)  # the row cannot register anyone, so ek is unregistered
    assert all(v["file"] != PLAN_FILE for v in report["violations"]), _show(report)
    items = _plan_entries(report, "unverifiable")
    assert [(u["code"], u["pointer"], u["case_id"]) for u in items] == [("plan_row_invalid", "/cases/0/slug", None)]


def test_a_plan_row_that_is_not_an_object_stays_batch_level_without_a_check_error(tmp_path):
    """Lock (green before V11): no class can be read from a non-object row, so it is not provably a frontier row: fail closed, nobody's."""
    ek_id = _resolve("ek")["case_id"]
    report = _validate(tmp_path, _expand(["ek"]), plan_edits=[("/cases/0", 7)])
    entries = {(v["code"], v["pointer"], v["case_id"]) for v in report["violations"]}
    assert not any(code == "check_error" for code, _, _ in entries), _show(report)
    assert ("schema_type", "/cases/0", None) in entries, _show(report)
    assert ("pre_registered_mismatch", "/pre_registered", ek_id) in entries, _show(report)
    assert _plan_entries(report, "unverifiable") == []


def test_a_plan_row_with_a_list_class_id_stays_batch_level_without_a_check_error(tmp_path):
    """A non-scalar class_id is not a frontier class: the row is nobody's, and the class lookup must not raise (unhashable)."""
    ek_id = _resolve("ek")["case_id"]
    report = _validate(tmp_path, _expand(["ek"]), plan_edits=[("/cases/0/class_id", ["F30B"])])
    entries = {(v["code"], v["pointer"], v["case_id"]) for v in report["violations"]}
    assert not any(code == "check_error" for code, _, _ in entries), _show(report)
    assert ("schema_enum", "/cases/0/class_id", None) in entries, _show(report)
    assert ("pre_registered_mismatch", "/pre_registered", ek_id) in entries, _show(report)
    assert _plan_entries(report, "unverifiable") == []


@pytest.mark.parametrize("prefix", ["CTRL_", "CANARY_"])
def test_an_r0_plan_row_violation_stays_batch_level_while_the_frontier_row_is_attributed(tmp_path, prefix):
    """R0 is a batch-level premise (brief 2.3): a malformed control or canary row is nobody's and still refuses the batch."""
    ek_id = _resolve("ek")["case_id"]
    rows = _plan_rows()
    k = next(i for i, row in enumerate(rows) if row["class_id"].startswith(prefix))
    report = _validate(tmp_path, _expand(["ek"]), plan_edits=[("/cases/0/hypotheses", ["a", "b", "c", "d"]), (f"/cases/{k}/hypotheses", ["a", "b", "c", "d"])])
    assert {(v["pointer"], v["case_id"]) for v in _plan_entries(report, "violations")} == {("/cases/0/hypotheses", ek_id), (f"/cases/{k}/hypotheses", None)}, _show(report)
    assert _plan_entries(report, "unverifiable") == []


def test_an_r0_plan_row_that_no_case_cites_is_not_demoted(tmp_path):
    """Lock (green before V11): an R0-class row is never demoted to ``plan_row_invalid``."""
    rows = _plan_rows()
    k = next(i for i, row in enumerate(rows) if row["class_id"].startswith("CTRL_"))
    bad = dict(rows[k], slug="hvac.copy")
    report = _validate(tmp_path, _expand(["ek"]), plan_edits=[("/cases", rows + [bad])])
    assert [(v["code"], v["pointer"], v["case_id"]) for v in report["violations"]] == [("schema_pattern", f"/cases/{len(rows)}/slug", None)], _show(report)
    assert _plan_entries(report, "unverifiable") == []


def test_a_frontier_row_cited_by_a_control_kind_case_stays_batch_level(tmp_path):
    """Lock (green before V11). Condition (ii): attribution needs every matched case to be a counted kind; a control citing the row keeps it batch-level."""
    ek = _patch(_resolve("ek"), ("/kind", "control"))
    report = _validate(tmp_path, [ek], plan_edits=[("/cases/0/hypotheses", ["a", "b", "c", "d"])])
    plan = _plan_entries(report, "violations")
    assert [(v["pointer"], v["case_id"]) for v in plan] == [("/cases/0/hypotheses", None)], _show(report)
    assert _plan_entries(report, "unverifiable") == []


# --------------------------------------------------------------------------
# V12 (brief_revision 4): target granularity -- item_range indices, show_text_sha256, the revision gate
# --------------------------------------------------------------------------
BRIEF_V4 = ROOT / "plans" / "grok-briefs" / "brief-v4.md"
V12_CODES = {"item_range_bounds", "item_range_span", "show_text_sha256_required", "show_text_sha256_mismatch", "whole_show_view_required"}


def _case_block(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    head = text.index("### 5.1")
    start = text.index("```json", head) + len("```json")
    return json.loads(text[start : text.index("```", start)])


def _v12_codes(case: dict) -> set[str]:
    return {v.code for v in eb.check_cross_field(case).violations} & V12_CODES


def _v4_fragment() -> dict:
    """The F3-in-a-TJ row written under brief v4: ``original`` is the slice, the decode and ``show_text_sha256`` are the whole show."""
    case = _patch(_fragment(True), ("/brief_revision", 4))
    show = "abcd"
    case["corpus_case"]["show_text_sha256"] = _h(show)
    case["target"]["source_decode"].update({"latin1": show, "latin1_sha256": _h(show), "independent": show, "independent_sha256": _h(show)})
    case["target"]["item_range"] = [0, 1]
    case["probe"]["whole_show_max_tier_1"] = copy.deepcopy(case["probe"]["max_tier_1"])  # the whole-show second view of a slice
    return case


def _v4_run(old: bytes, item_range: list[int], count: int = 3) -> dict:
    """A tj_run row whose old operand is ``old`` and whose target is the items ``item_range`` of a ``count``-item array."""
    case = _v4_fragment()
    case["mutation"]["splice_kind"] = "tj_run"
    case["mutation"]["changes"][0]["old_operand_bytes_hex"] = old.hex().upper()
    case["target"].update({"byte_range_in_item": None, "item_range": item_range, "array_item_count": count})
    return case


def _schema_before_v5(schema: dict) -> dict:
    """The case schema as brief v4 shipped it: no brief_revision 5, no code_revision.runner_sha256."""
    before = copy.deepcopy(schema)
    before["properties"]["brief_revision"] = {"enum": [2, 3, 4]}
    del before["properties"]["code_revision"]["properties"]["runner_sha256"]
    return before


def test_v12_the_schemas_admit_brief_revision_4():
    case = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    parent = json.loads((SCHEMA_DIR / "true_text_parent.v2.schema.json").read_text(encoding="utf-8"))
    assert case["properties"]["brief_revision"] == {"enum": [2, 3, 4, 5, 6, 7, 8]}  # v5 to v8 widened it; their tests pin that
    assert parent["properties"]["brief_revision"] == {"enum": [2, 3, 4, 5, 6, 7, 8]}
    assert "show_text_sha256" in case["properties"]["corpus_case"]["properties"]
    assert "show_text_sha256" not in case["properties"]["corpus_case"]["required"]  # rev 2 and 3 rows have none
    assert "whole_show_max_tier_1" in case["properties"]["probe"]["properties"]


def test_v12_the_case_schema_is_the_brief_v4_block_and_v3_is_the_schema_before_v4():
    schema = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    schema = _schema_before_v5(schema)  # the v5 additions (brief_revision 5, runner_sha256) are pinned by the v5 test
    assert _case_block(BRIEF_V4) == schema
    before = copy.deepcopy(schema)
    before["properties"]["brief_revision"] = {"enum": [2, 3]}
    del before["properties"]["corpus_case"]["properties"]["show_text_sha256"]
    del before["properties"]["probe"]["properties"]["whole_show_max_tier_1"]
    # V13: the three target geometry fields are nullable from brief v4 on (rev 2 and 3 rows keep them required, non-null)
    for key, ref in (("expected_origin_visual", "num2"), ("target_bbox_visual", "num4"), ("target_bbox_raw", "num4")):
        before["properties"]["target"]["properties"][key] = {"$ref": f"#/$defs/{ref}"}
    assert _case_block(BRIEF_V3) == before


def test_v12_a_rev4_row_gets_every_rev3_rule():
    """Rev 4 inherits the v3 rules: the helper, not a literal 3, decides."""
    assert eb._rev({"brief_revision": 4}) == 4 and eb._rev({"brief_revision": True}) == 0 and eb._rev(None) == 0
    assert eb._ink_sized({"brief_revision": 4, "mutation": {"splice_kind": "tj_run"}}) is True
    assert eb._ink_sized({"brief_revision": 2, "mutation": {"splice_kind": "tj_run"}}) is False
    assert eb.check_revision_schema(_v4_fragment()) == []  # rev 4 is not held to the rev 2 schema shape


def test_v12_rev3_rows_cannot_carry_the_rev4_only_keys():
    case = _patch(_v4_fragment(), ("/brief_revision", 3))
    keys = {(v.code, v.pointer) for v in eb.check_revision_schema(case)}
    assert ("schema_additional", "/corpus_case/show_text_sha256") in keys
    probe = _patch(_v4_fragment(), ("/probe/whole_show_max_tier_1", None))
    assert eb.check_revision_schema(probe) == []


def test_v12_an_honest_rev4_fragment_row_has_no_v12_violation():
    """Lock (green before V12): the honest base the forged rows below are patched from."""
    assert _v12_codes(_v4_fragment()) == set()


@pytest.mark.parametrize(
    ("edits", "label"),
    [
        ([("/target/item_range", [0, 2])], "i1 past array_item_count"),
        ([("/target/item_range", [1, 1])], "i0 == i1"),
        ([("/target/item_range", [-1, 1])], "negative i0"),
        ([("/target/item_range", [0, 2]), ("/target/array_item_count", 3)], "F3 spanning two items"),
        ([("/target/item_range", None)], "F3 in a TJ without its item"),
        ([("/target/operator", "Tj"), ("/target/string_kind", "literal")], "item_range on a Tj"),
    ],
)
def test_v12_item_range_bounds(edits, label):
    assert "item_range_bounds" in _v12_codes(_patch(_v4_fragment(), *edits)), label


def test_v12_item_range_bounds_also_run_on_rev3_but_not_on_rev2():
    bad = [("/target/item_range", [0, 2])]
    assert "item_range_bounds" in _v12_codes(_patch(_v4_fragment(), ("/brief_revision", 3), *bad))
    assert "item_range_bounds" not in _v12_codes(_patch(_v4_fragment(), ("/brief_revision", 2), *bad))


def test_v12_show_text_sha256_is_required_from_rev4_and_binds_the_whole_show_decode():
    missing = _patch(_v4_fragment(), ("/corpus_case/show_text_sha256", _DEL))
    assert "show_text_sha256_required" in _v12_codes(missing)
    assert "show_text_sha256_required" not in _v12_codes(_patch(missing, ("/brief_revision", 3)))
    assert "show_text_sha256_required" in _v12_codes(_patch(_v4_fragment(), ("/corpus_case/show_text_sha256", "nothex")))
    wrong = _patch(_v4_fragment(), ("/corpus_case/show_text_sha256", _h("something else")))
    assert "show_text_sha256_mismatch" in _v12_codes(wrong)
    whole = _patch(_v4_fragment(), ("/target/item_range", None), ("/target/byte_range_in_item", None), ("/corpus_case/original_sha256", _h("zzzz")))
    assert "show_text_sha256_mismatch" in _v12_codes(whole)  # a whole-show target IS the show text


def test_v12_a_slice_row_needs_the_whole_show_second_view_from_rev4():
    """Brief v4 M1: a slice target also gets a whole-show probe; omitting it (or writing null) is a rejection."""
    assert "whole_show_view_required" not in _v12_codes(_v4_fragment())
    missing = _patch(_v4_fragment(), ("/probe/whole_show_max_tier_1", _DEL))
    assert "whole_show_view_required" in _v12_codes(missing)
    assert "whole_show_view_required" in _v12_codes(_patch(_v4_fragment(), ("/probe/whole_show_max_tier_1", None)))
    by_range = _patch(_v4_run(b"(ab) -30 (cd)", [0, 2]), ("/probe/whole_show_max_tier_1", None))
    assert "whole_show_view_required" in _v12_codes(by_range)
    # a whole-show target has no second view; rev 3 rows may not carry the key at all
    whole = _patch(_v4_fragment(), ("/target/item_range", None), ("/target/byte_range_in_item", None), ("/probe/whole_show_max_tier_1", None))
    assert "whole_show_view_required" not in _v12_codes(whole)
    assert "whole_show_view_required" not in _v12_codes(_patch(missing, ("/brief_revision", 3)))


def test_v12_item_range_span_counts_the_string_items_of_the_old_operand():
    run = b"(ab) -30 (cd)"
    assert "item_range_span" not in _v12_codes(_v4_run(run, [0, 2]))
    assert "item_range_span" in _v12_codes(_v4_run(run, [0, 3]))
    assert "item_range_span" in _v12_codes(_v4_run(b"-30 (ab) -30 (cd)", [0, 2]))  # a border kern is not part of the run
    assert "item_range_span" in _v12_codes(_v4_run(b"(ab) -30 (cd) 12", [0, 2]))
    assert "item_range_span" not in _v12_codes(_patch(_v4_run(run, [0, 3]), ("/brief_revision", 3)))  # rev 4 only


def test_v12_a_non_public_item_range_span_is_listed_unverifiable():
    case = _v4_run(b"(ab) -30 (cd)", [0, 2])
    case["mutation"]["changes"][0]["old_operand_bytes_hex"] = None
    res = eb.check_cross_field(case)
    assert "item_range_span" in {u.code for u in res.unverifiable}
    honest = eb.check_cross_field(_v4_run(b"(ab) -30 (cd)", [0, 2]))
    assert "item_range_span" not in {u.code for u in honest.unverifiable}


# --------------------------------------------------------------------------
# V13 (brief_revision 4): nullable target geometry under an untracked origin
# --------------------------------------------------------------------------
V13_CODES = {
    "geometry_on_untracked_origin",
    "geometry_null_on_tracked_origin",
    "geometry_partly_null",
    "geometry_null_without_limit",
}
V13_GEOMETRY = ("expected_origin_visual", "target_bbox_visual", "target_bbox_raw")
V13_LIMIT = "Untracked origin (origin_reliable false): the three target geometry fields are null, the probe ran with expected_origin=None."


def _v13_codes(case: dict) -> set[str]:
    return {v.code for v in eb.check_cross_field(case).violations} & V13_CODES


def _v13_census(*, reliable: bool = False, null_geometry: bool = True, limit: bool = True, rev: int = 4) -> dict:
    """A census row written under brief v4: the honest F17 shape (untracked origin, null geometry, a limits entry)."""
    case = _patch(_null_counters(_rev3(_census_f1())), UNMAPPABLE, ("/brief_revision", rev))
    if rev >= 4:
        case["corpus_case"]["show_text_sha256"] = case["target"]["source_decode"]["latin1_sha256"]
    case["text_state"]["before"]["origin_reliable"] = reliable
    if null_geometry:
        for key in V13_GEOMETRY:
            case["target"][key] = None
    if limit:
        case["limits"] = [V13_LIMIT]
    return case


def test_v13_the_schema_admits_null_geometry_and_the_brief_v4_block_says_so():
    schema = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]["target"]["properties"]
    for key in V13_GEOMETRY:
        assert {"type": "null"} in props[key]["anyOf"], key
    assert _case_block(BRIEF_V4) == _schema_before_v5(schema)


def test_v13_an_honest_untracked_origin_row_validates_clean(tmp_path):
    """Nothing downstream may raise on a null box: no case-level violation and no check_error for the row."""
    row = _v13_census()
    assert _v13_codes(row) == set()
    report = _validate(tmp_path, [row], denylist=["acmecorp"], r0=False)
    mine = [v for v in report["violations"] if v["case_id"] == row["case_id"]]
    assert mine == [], _show(report)
    assert not [v for v in report["violations"] if v["code"] == "check_error"], _show(report)


def test_v13_geometry_on_an_untracked_origin_is_a_violation_from_rev4():
    row = _v13_census(null_geometry=False)
    assert "geometry_on_untracked_origin" in _v13_codes(row)
    one = _patch(_v13_census(), ("/target/target_bbox_raw", [1.0, 2.0, 3.0, 4.0]))
    assert "geometry_on_untracked_origin" in _v13_codes(one)  # one non-null field is enough
    assert _v13_codes(_patch(row, ("/brief_revision", 3))) == set()  # gated: rev 3 rows keep the old schema and rules


def test_v13_null_geometry_on_a_tracked_origin_is_a_violation():
    """Otherwise nullable would be a way to skip the M1 locate everywhere."""
    row = _v13_census(reliable=True)
    assert "geometry_null_on_tracked_origin" in _v13_codes(row)


def test_v13_partly_null_geometry_is_a_violation():
    row = _patch(_v13_census(), ("/target/target_bbox_raw", [1.0, 2.0, 3.0, 4.0]), ("/target/target_bbox_visual", [1.0, 2.0, 3.0, 4.0]))
    assert "geometry_partly_null" in _v13_codes(row)
    assert "geometry_partly_null" in _v13_codes(_patch(_v13_census(reliable=True), ("/target/target_bbox_raw", [1.0, 2.0, 3.0, 4.0])))


def test_v13_null_geometry_needs_a_limits_entry():
    assert "geometry_null_without_limit" in _v13_codes(_v13_census(limit=False))
    assert "geometry_null_without_limit" in _v13_codes(_patch(_v13_census(), ("/limits", [""])))
    assert "geometry_null_without_limit" not in _v13_codes(_v13_census())


@pytest.mark.parametrize("rev", [2, 3])
def test_v13_null_geometry_stays_a_schema_error_below_rev4(rev):
    row = _v13_census(rev=rev)
    keys = {(v.code, v.pointer) for v in eb.check_revision_schema(row)}
    for key in V13_GEOMETRY:
        assert ("schema_type", f"/target/{key}") in keys, key
    assert eb.check_revision_schema(_v13_census()) == []


def test_v13_brief_v4_carries_the_contract_text():
    text = BRIEF_V4.read_text(encoding="utf-8")
    for marker in (
        "target_unlocatable",
        "geometry_on_untracked_origin",
        "geometry_null_on_tracked_origin",
        "locate_method",
        "expected_origin=None",
        "/Subtype",
    ):
        assert marker in text, marker


# --------------------------------------------------------------------------
# V16: provenance and registration (relative_path_required, slug_not_derived)
# --------------------------------------------------------------------------
V16_CODES = {"relative_path_required", "slug_not_derived"}
V16_VERA_REL = "test_files/veraPDF-corpus-staging/ISO 32000-1/veraPDF test suite 6-8-3-3-t01-fail-a.pdf"


def _v16_codes(case: dict) -> set[str]:
    return {v.code for v in eb.check_cross_field(case).violations} & V16_CODES


def _v16_row(*, provenance: str = "public", slug: str = "minimal-document", rel: str | None = "test_files/sample-files-main/001-trivial/minimal-document.pdf", rev: int = 4) -> dict:
    """The F3-in-a-TJ public row, re-labelled: only the three source fields V16 reads are changed."""
    return _patch(_v4_fragment(), ("/brief_revision", rev), ("/source/provenance", provenance), ("/source/slug", slug), ("/source/relative_path", rel))


def test_v16_the_honest_rev4_public_and_local_unrecorded_rows_have_no_v16_violation():
    assert _v16_codes(_v16_row()) == set()
    local = _v16_row(provenance="local_unrecorded", slug="test-colored-background", rel="test_files/test-colored-background.pdf")
    assert _v16_codes(local) == set()


@pytest.mark.parametrize("provenance", ["public", "local_unrecorded"])
def test_v16_a_null_relative_path_is_required_from_rev4(provenance):
    row = _v16_row(provenance=provenance, rel=None)
    assert _v16_codes(row) == {"relative_path_required"}  # a null path has no stem, so it is not also a slug violation


@pytest.mark.parametrize("provenance", ["proprietary", "synthetic"])
def test_v16_proprietary_and_synthetic_rows_keep_a_null_path_and_no_slug_rule(provenance):
    row = _v16_row(provenance=provenance, slug="hvac", rel=None)
    assert _v16_codes(row) == set()


def test_v16_the_vera_slug_of_batch_2116_is_not_derived():
    """Row #23 of the 2116 triage: the file is veraPDF test suite 6-8-3-3-t01-fail-a.pdf, the record wrote vera-6-8-3-3-t01-fail-a."""
    bad = _v16_row(slug="vera-6-8-3-3-t01-fail-a", rel=V16_VERA_REL)
    assert _v16_codes(bad) == {"slug_not_derived"}
    good = _v16_row(slug="verapdf-test-suite-6-8-3-3-t01-fail-a", rel=V16_VERA_REL)
    assert _v16_codes(good) == set()


@pytest.mark.parametrize(
    "slug, rel",
    [
        ("ua1-7.2-t30-pass-b", "test_files/veraPDF-corpus-staging/PDF_UA-1/7.2 Text/7.2-t30-pass-b.pdf"),
        ("isartor-manual", "test_files/veraPDF-corpus-staging/Isartor test files/doc/Isartor test suite manual.pdf"),
        ("annotated_pdf", "test_files/sample-files-main/024-annotations/annotated_pdf.pdf"),
        ("Minimal-Document", "test_files/sample-files-main/001-trivial/minimal-document.pdf"),
    ],
)
def test_v16_a_slug_that_is_not_the_slugified_stem_is_rejected(slug, rel):
    assert _v16_codes(_v16_row(slug=slug, rel=rel)) == {"slug_not_derived"}


def test_v16_a_local_unrecorded_slug_is_checked_like_a_public_one():
    row = _v16_row(provenance="local_unrecorded", slug="colored-background", rel="test_files/test-colored-background.pdf")
    assert _v16_codes(row) == {"slug_not_derived"}


@pytest.mark.parametrize("rev", [2, 3])
def test_v16_both_rules_are_gated_on_brief_revision_4(rev):
    """Rev 2 (1114) and rev 3 (2116: null local_unrecorded paths, the vera slug) keep validating exactly as before."""
    assert _v16_codes(_v16_row(rel=None, rev=rev)) == set()
    assert _v16_codes(_v16_row(slug="vera-6-8-3-3-t01-fail-a", rel=V16_VERA_REL, rev=rev)) == set()


def test_v16_the_shared_slugify_is_the_one_rederive_uses():
    assert eb._slugify("veraPDF test suite 6-8-3-3-t01-fail-a") == "verapdf-test-suite-6-8-3-3-t01-fail-a"
    assert eb._slugify("annotated_pdf") == "annotated-pdf"
    assert eb._slugify("7.2-t30-pass-b") == "7-2-t30-pass-b"
    assert eb._slugify("__") == ""
    from scripts import evidence_rederive as rd

    assert rd._slugify is eb._slugify


def test_v16_brief_v4_carries_the_contract_text():
    text = BRIEF_V4.read_text(encoding="utf-8")
    for marker in (
        "relative_path_required",
        "slug_not_derived",
        "verapdf-test-suite-6-8-3-3-t01-fail-a",
        "vera-6-8-3-3-t01-fail-a",
        "provenance_unverified",
        "before_pdf_mismatch",
    ):
        assert marker in text, marker
    assert "V16 (relative_path, slug) adds its contract text here" not in text  # the header no longer promises it


# --------------------------------------------------------------------------
# Q12: the in-show successor limit scales with the integerised /Widths residual (brief_revision >= 4)
# --------------------------------------------------------------------------
def _q12_row(delta: float, *, rev: int = 4, edits=()) -> tuple[dict, list[dict]]:
    """The honest 2 -> 3 glyph ``ek`` row, written under ``rev``, whose first in-show successor sits ``delta`` pt off.

    The advance keeps its char counts 2 + 3 and gets Tfs 10.9091 (the f723638d row of batch 1824), Th 1 and trm_scale 1,
    so the rev-4 bound is (2 + 3) * 10.9091 / 1000 + 1e-6 = 0.0545 pt.
    """
    case = _resolve("ek")
    recs = case.pop("_records")
    succ = recs[-2]
    succ["role"] = "inshow_successor"
    succ["show_index"] = 0
    succ["origin_after"] = [succ["origin_before"][0] + delta, succ["origin_before"][1]]
    succ["origin_delta_pt"] = delta
    case["neighbours"] = _summary(recs, 2, 3, case["case_id"])
    case = _patch(
        case,
        ("/brief_revision", rev),
        ("/mutation/advance/Tfs", 10.9091),
        ("/mutation/advance/Th", 1.0),
        ("/target/trm_scale", 1.0),
        *edits,
    )
    return case, recs


def _q12_fails(delta: float, **kw) -> list[str]:
    case, recs = _q12_row(delta, **kw)
    res = eb.check_pairing(case, recs)
    assert res.violations == [], res.violations
    return [r for r in res.fails.get("neighbours", []) if "inshow" in r]


Q12_BOTH = ["reported_inshow_moved", "recomputed_inshow_moved"]


def test_q12_a_rev4_row_within_the_integerised_width_residual_is_not_an_inshow_move():
    """0.00109 pt is 0.1 unit of /Widths at Tfs 10.9091: well inside (2 + 3) glyphs x Tfs / 1000 = 0.0545 pt."""
    assert _q12_fails(0.00109) == []


def test_q12_a_rev4_row_past_the_bound_is_still_an_inshow_move():
    assert _q12_fails(0.1) == Q12_BOTH


def test_q12_the_same_numbers_at_rev3_keep_the_plain_1e_6_limit():
    assert _q12_fails(0.00109, rev=3) == Q12_BOTH
    assert _q12_fails(0.00109, rev=2) == Q12_BOTH


def test_q12_a_rev4_row_missing_a_bound_input_fails_closed_at_1e_6():
    assert _q12_fails(0.00109, edits=[("/mutation/advance/char_count_new", _DEL)]) == Q12_BOTH
    assert _q12_fails(0.00109, edits=[("/mutation/advance/Th", _DEL)]) == Q12_BOTH
    assert _q12_fails(5e-7, edits=[("/mutation/advance/Th", _DEL)]) == []  # 1e-6 itself still passes


def test_q12_the_bound_is_not_a_blanket_waiver():
    """Just inside the limit passes, a hair past it fails (kills a mutant that widens the bound by a constant)."""
    limit = 5 * 10.9091 / 1000 + 1e-6
    assert _q12_fails(limit - 1e-6) == []
    assert _q12_fails(limit + 1e-6) == Q12_BOTH


def test_q12_the_horizontal_scale_widens_the_bound():
    """Th 2 doubles the bound to 0.109 pt: 0.08 passes there and fails at Th 1 (kills a mutant that drops Th)."""
    assert _q12_fails(0.08, edits=[("/mutation/advance/Th", 2.0)]) == []
    assert _q12_fails(0.08, edits=[("/mutation/advance/Th", 1.0)]) == Q12_BOTH


def test_q12_the_trm_scale_shrinks_the_bound():
    """scale 0.375 gives 0.0205 pt: 0.03 fails there and passes at scale 1.0 (kills a mutant that drops trm_scale)."""
    assert _q12_fails(0.03, edits=[("/target/trm_scale", 0.375)]) == Q12_BOTH
    assert _q12_fails(0.03, edits=[("/target/trm_scale", 1.0)]) == []


def test_q12_both_char_counts_enter_the_bound():
    """(count_old + count_new) * Tfs * Th * scale / 1000 + 1e-6, each term read from the first advance."""
    case, _ = _q12_row(0.0)
    assert eb._inshow_successor_bound(case) == pytest.approx(5 * 10.9091 / 1000 + 1e-6)
    case, _ = _q12_row(0.0, edits=[("/mutation/advance/char_count_new", 0)])
    assert eb._inshow_successor_bound(case) == pytest.approx(2 * 10.9091 / 1000 + 1e-6)
    case, _ = _q12_row(0.0, edits=[("/mutation/advance/char_count_old", 0)])
    assert eb._inshow_successor_bound(case) == pytest.approx(3 * 10.9091 / 1000 + 1e-6)


@pytest.mark.parametrize(
    "edits",
    [
        [("/mutation/advance/char_count_old", True)],
        [("/mutation/advance/char_count_old", -1)],
        [("/mutation/advance/char_count_old", 2.0)],
        [("/mutation/advance/char_count_new", None)],
        [("/mutation/advance/Tfs", 0.0)],
        [("/mutation/advance/Tfs", "10.9")],
        [("/mutation/advance/Th", None)],
        [("/mutation/advance/Th", 0.0)],
        [("/mutation/advance/Th", True)],
        [("/mutation/advance", None)],
        [("/mutation/advance", [])],
    ],
)
def test_q12_every_invalid_bound_input_returns_the_plain_limit(edits):
    case, _ = _q12_row(0.0, edits=edits)
    assert eb._inshow_successor_bound(case) == 1e-6


def test_q12_an_absent_or_invalid_trm_scale_reads_as_one_and_the_first_advance_wins():
    base = 5 * 10.9091 / 1000 + 1e-6
    case, _ = _q12_row(0.0, edits=[("/target/trm_scale", _DEL)])
    assert eb._inshow_successor_bound(case) == pytest.approx(base)
    case, _ = _q12_row(0.0, edits=[("/target/trm_scale", 0.0)])
    assert eb._inshow_successor_bound(case) == pytest.approx(base)
    case, _ = _q12_row(0.0)
    first = copy.deepcopy(case["mutation"]["advance"])
    second = {**first, "Tfs": 99.0, "char_count_old": 7, "char_count_new": 1}
    case["mutation"]["advance"] = [first, second]
    assert eb._inshow_successor_bound(case) == pytest.approx(base)
    case["mutation"]["advance"] = [second, first]
    assert eb._inshow_successor_bound(case) == pytest.approx(8 * 99.0 / 1000 + 1e-6)


def test_q12_mupdf_integerises_fractional_widths():
    """The empirical basis of the bound: MuPDF stores simple-font /Widths as integers (round to nearest).

    /Widths [600.7 600.4 600.5] at 10 pt: exact widths would give 6.007 / 6.004 pt advances; the texttrace gives 6.01
    (601 units) and 6.00 (600 units). A truncating reader would give 6.00 / 6.00, an exact one 6.007 / 6.004.
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "ABC", fontname="helv", fontsize=10)
    xref = page.get_fonts()[0][0]
    doc.xref_set_key(xref, "FirstChar", "65")
    doc.xref_set_key(xref, "LastChar", "67")
    doc.xref_set_key(xref, "Widths", "[600.7 600.4 600.5]")
    reopened = fitz.open("pdf", doc.tobytes())
    xs = [ch[2][0] for span in reopened[0].get_texttrace() for ch in span["chars"]]
    assert len(xs) == 3
    assert xs[1] - xs[0] == pytest.approx(6.01, abs=1e-3)
    assert xs[2] - xs[1] == pytest.approx(6.00, abs=1e-3)
    # the integerisation error is below one unit (here 0.3 and 0.4), which is what the (old + new) glyph budget covers
    assert abs((xs[1] - xs[0]) - 6.007) < 1.0 * 10 / 1000


# --------------------------------------------------------------------------
# brief v5 (red first, 2026-10-26): single_family counts positives only; the schemas admit brief_revision 5
# --------------------------------------------------------------------------
BRIEF_V5 = ROOT / "plans" / "grok-briefs" / "brief-v5.md"
BRIEF_V6 = ROOT / "plans" / "grok-briefs" / "brief-v6.md"
BRIEF_V7 = ROOT / "plans" / "grok-briefs" / "brief-v7.md"
BRIEF_V8 = ROOT / "plans" / "grok-briefs" / "brief-v8.md"
V5_RUNNER_CODES = {"runner_sha_missing", "runner_sha_mixed", "runner_sha_disk_mismatch", "runs_missing", "runs_malformed", "runner_partial_rerun"}
_PILOT_SHA = hashlib.sha256(b"print('pilot')\n").hexdigest()  # what _make_batch writes as run_pilot.py


def _v5_row(class_id: str, kind: str, lineage: str, family: str, k: int, rev: int = 5) -> dict:
    """The fields ``recompute_parent_summary`` reads, nothing else: a positive or negative with a lineage and a producer family."""
    return {
        "case_id": f"r2-{class_id}-{lineage}-p0-s{k}-{'eq' if kind == 'positive' else 'neg'}1",
        "brief_revision": rev,
        "class_id": class_id,
        "kind": kind,
        "source": {"provenance": "public", "lineage_id": lineage, "producer_family": family},
        "probe": {},
        "mutation": None,
    }


def _v5_family_cases(rev: int) -> tuple[list[dict], dict[str, str]]:
    """Two save_reopen_pass positives on two lineages, one producer family; the negative sibling from a second family."""
    cases = [
        _v5_row("F30B", "positive", "aaaaaaaa", "fam-a", 1, rev),
        _v5_row("F30B", "positive", "bbbbbbbb", "fam-a", 2, rev),
        _v5_row("F30B", "negative", "cccccccc", "fam-b", 3, rev),
    ]
    statuses = {cases[0]["case_id"]: "save_reopen_pass", cases[1]["case_id"]: "save_reopen_pass", cases[2]["case_id"]: "probe_rejected"}
    return cases, statuses


def test_v5_single_family_is_decided_by_the_positives_producer_family():
    """Brief 3.0 / v5 (w2): at brief_revision >= 5 ``distinct_producer_families`` and the proposal count the
    save_reopen_pass positives only, so a negative sibling from a second family cannot lift the class to
    method_reproducible (20261026_0032_r2 F30B/F2I: Grok wrote single_family, the recompute said method_reproducible,
    and _diff skips the proposal so nothing fired). ``distinct_lineages`` keeps counting every row.
    """
    got = eb.recompute_parent_summary(*_v5_family_cases(5))["per_class"]["F30B"]
    assert got["positives"] == 2 and got["negatives"] == 1 and got["distinct_lineages"] == 2  # the negative's third lineage no longer counts
    assert got["distinct_producer_families"] == 1
    assert got["class_state_proposal"] == "method_reproducible_single_family"


def test_v5_rev4_rows_keep_the_all_row_family_count():
    """The rev-4 recompute is unchanged, so 20261024_2116_r2 / 20261026_0032_r2 validate byte-identically."""
    got = eb.recompute_parent_summary(*_v5_family_cases(4))["per_class"]["F30B"]
    assert got["distinct_lineages"] == 3
    assert got["distinct_producer_families"] == 2
    assert got["class_state_proposal"] == "method_reproducible"


def test_v5_a_negative_lineage_does_not_clear_the_second_lineage_bar():
    """Brief 3.0 at rev >= 5 counts save_reopen_pass positives for lineages too: two passing positives on ONE
    lineage plus a negative on a second lineage is still needs_second_case (the rev-4 twin counts every row)."""

    def build(rev: int) -> tuple[list[dict], dict[str, str]]:
        cases = [
            _v5_row("F30B", "positive", "aaaaaaaa", "fam-a", 1, rev),
            _v5_row("F30B", "positive", "aaaaaaaa", "fam-a", 2, rev),
            _v5_row("F30B", "negative", "cccccccc", "fam-b", 3, rev),
        ]
        ids = [c["case_id"] for c in cases]
        return cases, {ids[0]: "save_reopen_pass", ids[1]: "save_reopen_pass", ids[2]: "probe_rejected"}

    got = eb.recompute_parent_summary(*build(5))["per_class"]["F30B"]
    assert got["distinct_lineages"] == 1
    assert got["class_state_proposal"] == "needs_second_case"
    twin = eb.recompute_parent_summary(*build(4))["per_class"]["F30B"]
    assert twin["distinct_lineages"] == 2
    assert twin["class_state_proposal"] == "method_reproducible"
    assert eb.recompute_parent_summary(*build(4), v5=True)["per_class"]["F30B"]["class_state_proposal"] == "needs_second_case"


def test_v5_the_schemas_admit_brief_revision_5(tmp_path):
    case = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    parent = json.loads((SCHEMA_DIR / "true_text_parent.v2.schema.json").read_text(encoding="utf-8"))
    assert case["properties"]["brief_revision"] == {"enum": [2, 3, 4, 5, 6, 7, 8]}  # v6 to v8 widened it; their tests pin that
    assert parent["properties"]["brief_revision"] == {"enum": [2, 3, 4, 5, 6, 7, 8]}
    for schema in (case, parent):
        assert schema["properties"]["code_revision"]["properties"]["runner_sha256"] == {"type": "string", "pattern": "^[0-9a-f]{64}$"}
        assert "runner_sha256" not in schema["properties"]["code_revision"]["required"]  # rev 2-4 records must not carry it: check_revision_schema refuses it
    report = _validate(tmp_path, [_v5_case()], r0=False, **_v5_parent(_PILOT_SHA), files=_runs(_PILOT_SHA))
    assert ("schema_enum", "/brief_revision") not in _hits(report), _show(report)


def test_v6_the_schemas_admit_brief_revision_6():
    """Brief v6 (round 3, 2026-10-28) on the validator side: the enum admits 6, no rule is rev-6 gated, and the rev <= 5
    batches validate byte-identically (the old-batch sha pins in the gate).  The one rule change v6 needed, CANARY_KSIGN in
    SYNTHETIC_CLASSES for the (ac) second site, is an unconditional loosening (test_v6_a_synthetic_ksign_canary_...)."""
    case = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    parent = json.loads((SCHEMA_DIR / "true_text_parent.v2.schema.json").read_text(encoding="utf-8"))
    assert 6 in case["properties"]["brief_revision"]["enum"]
    assert 6 in parent["properties"]["brief_revision"]["enum"]
    assert case["properties"]["brief_revision"]["enum"] == sorted(case["properties"]["brief_revision"]["enum"])
    assert all(type(m) is int for m in case["properties"]["brief_revision"]["enum"])  # int members, never a string look-alike


def _schema_before_v6(schema: dict) -> dict:
    """The case schema as brief v5 shipped it: no brief_revision 6 (v6 changed the schema enum and one allowlist, no schema key)."""
    before = copy.deepcopy(schema)
    before["properties"]["brief_revision"] = {"enum": [2, 3, 4, 5]}
    return before


def test_v5_the_case_schema_is_the_brief_v5_block_and_v4_is_the_schema_before_v5():
    schema = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    v5 = _schema_before_v6(schema)
    assert _case_block(BRIEF_V5) == v5
    before = copy.deepcopy(v5)
    before["properties"]["brief_revision"] = {"enum": [2, 3, 4]}
    del before["properties"]["code_revision"]["properties"]["runner_sha256"]
    assert _case_block(BRIEF_V4) == before


def test_v6_the_case_schema_is_the_brief_v6_block_and_v5_is_the_schema_before_v6():
    """Brief v6 (round 3): its block gains only enum member 6 over v5's; v7 (test_v7_*) added 7 to the current schema."""
    schema = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    v6 = copy.deepcopy(schema)
    v6["properties"]["brief_revision"] = {"enum": [2, 3, 4, 5, 6]}
    assert _case_block(BRIEF_V6) == v6
    assert _case_block(BRIEF_V5) == _schema_before_v6(schema)
    assert _case_block(BRIEF_V6) != _case_block(BRIEF_V5)


def test_v7_the_schemas_admit_brief_revision_7():
    """Brief v7 (round 4, 2026-10-28) is schema-only in the brief: the enum admits 7; the only rev-7 gated rules are the two
    KSIGN tightenings added after it (eb.KSIGN_SECOND_SITE_REV, test_v7_*ksign*); the rev <= 6 batches validate
    byte-identically (the old-batch sha pins in the gate)."""
    case = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    parent = json.loads((SCHEMA_DIR / "true_text_parent.v2.schema.json").read_text(encoding="utf-8"))
    assert case["properties"]["brief_revision"] == {"enum": [2, 3, 4, 5, 6, 7, 8]}  # v8 widened it; test_v8_* pins that
    assert parent["properties"]["brief_revision"] == {"enum": [2, 3, 4, 5, 6, 7, 8]}
    assert eb.KSIGN_SECOND_SITE_REV == 7


def test_v7_the_case_schema_is_the_brief_v7_block_and_v6_is_the_schema_before_v7():
    """Brief v7: its block gains only enum member 7 over v6's; v8 (test_v8_*) added 8 to the current schema."""
    schema = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    v7 = copy.deepcopy(schema)
    v7["properties"]["brief_revision"] = {"enum": [2, 3, 4, 5, 6, 7]}
    assert _case_block(BRIEF_V7) == v7
    before = copy.deepcopy(schema)
    before["properties"]["brief_revision"] = {"enum": [2, 3, 4, 5, 6]}
    assert _case_block(BRIEF_V6) == before
    assert _case_block(BRIEF_V7) != _case_block(BRIEF_V6)


def test_v8_the_schemas_admit_brief_revision_8():
    """Brief v8 (round 5, 2026-10-29) is schema-only in the brief: the enum admits 8 and no new rule is gated on it.  The two
    KSIGN tightenings stay on eb.KSIGN_SECOND_SITE_REV (7), so a rev-8 batch is held to them as a rev-7 batch is; the rev <= 7
    batches validate byte-identically (the old-batch sha pins in the gate)."""
    case = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    parent = json.loads((SCHEMA_DIR / "true_text_parent.v2.schema.json").read_text(encoding="utf-8"))
    assert case["properties"]["brief_revision"] == {"enum": [2, 3, 4, 5, 6, 7, 8]}
    assert parent["properties"]["brief_revision"] == {"enum": [2, 3, 4, 5, 6, 7, 8]}
    assert eb.KSIGN_SECOND_SITE_REV == 7  # the gate did not move with the brief; the owner may still raise it to 8


def test_v8_the_case_schema_is_the_brief_v8_block_and_v7_is_the_schema_before_v8():
    """Brief v8: the current block gains only enum member 8; v7's block is the schema minus it."""
    schema = json.loads((SCHEMA_DIR / "true_text_case.v2.schema.json").read_text(encoding="utf-8"))
    assert _case_block(BRIEF_V8) == schema
    before = copy.deepcopy(schema)
    before["properties"]["brief_revision"] = {"enum": [2, 3, 4, 5, 6, 7]}
    assert _case_block(BRIEF_V7) == before
    assert _case_block(BRIEF_V8) != _case_block(BRIEF_V7)


def _v5_case(runner_sha: str | None = _PILOT_SHA) -> dict:
    case = _patch(_v4_fragment(), ("/brief_revision", 5))
    if runner_sha is not None:
        case["code_revision"]["runner_sha256"] = runner_sha
    return case


def _v5_parent(runner_sha: str | None) -> dict:
    edits = [("/brief_revision", 5)]
    if runner_sha is not None:
        edits.append(("/code_revision/runner_sha256", runner_sha))
    return {"parent_edits": edits}


def _runs(*shas: str, last_phase: str = "all") -> dict:
    entries = [{"phase": "all", "runner_sha256": s, "started_utc": f"2026-10-26T0{i}:00:00Z"} for i, s in enumerate(shas)]
    entries[-1]["phase"] = last_phase
    return {"RUNS.json": json.dumps(entries).encode("utf-8")}


def _runner_hits(report: dict) -> set[tuple[str, str]]:
    return {(v["code"], v["pointer"]) for v in report["violations"] if v["code"] in V5_RUNNER_CODES}


def test_v5_one_runner_text_per_batch_validates(tmp_path):
    """Brief v5 (w): rows, PARENT_SUMMARY, the last RUNS.json entry and run_pilot.py on disk all carry one runner sha."""
    report = _validate(tmp_path, [_v5_case()], r0=False, **_v5_parent(_PILOT_SHA), files=_runs("f" * 64, _PILOT_SHA))
    assert _runner_hits(report) == set(), _show(report)


def test_v5_a_parent_runner_sha_that_differs_from_the_rows_is_mixed(tmp_path):
    case = _v5_case()
    report = _validate(tmp_path, [case], r0=False, **_v5_parent("a" * 64), files=_runs(_PILOT_SHA))
    assert ("runner_sha_mixed", "/code_revision/runner_sha256") in _runner_hits(report), _show(report)
    # the parent is the reference, so the row that disagrees with it is the one flagged
    assert {v["case_id"] for v in report["violations"] if v["code"] == "runner_sha_mixed"} == {case["case_id"]}, _show(report)


def test_v5_the_parent_sha_is_the_reference(tmp_path):
    first = _v5_case("b" * 64)
    second = _retarget(_v5_case(), show=9)
    report = _validate(tmp_path, [first, second], r0=False, **_v5_parent(_PILOT_SHA), files=_runs(_PILOT_SHA))
    mixed = [v for v in report["violations"] if v["code"] == "runner_sha_mixed"]
    assert {v["case_id"] for v in mixed} == {first["case_id"]} and len(mixed) == 1, _show(report)
    codes = {v["code"] for v in report["violations"]}
    assert "runner_sha_disk_mismatch" not in codes and "runner_partial_rerun" not in codes, _show(report)


def test_v5_rows_from_two_runner_texts_are_mixed(tmp_path):
    second = _retarget(_v5_case("b" * 64), show=9)
    report = _validate(tmp_path, [_v5_case(), second], r0=False, **_v5_parent(_PILOT_SHA), files=_runs(_PILOT_SHA))
    hits = {v["case_id"] for v in report["violations"] if v["code"] == "runner_sha_mixed"}
    assert hits == {second["case_id"]}, _show(report)


def test_v5_an_agreed_runner_sha_must_be_the_file_on_disk(tmp_path):
    report = _validate(tmp_path, [_v5_case("c" * 64)], r0=False, **_v5_parent("c" * 64), files=_runs("c" * 64))
    assert ("runner_sha_disk_mismatch", "/code_revision/runner_sha256") in _runner_hits(report), _show(report)


def test_v5_a_rev5_row_without_a_runner_sha_is_missing(tmp_path):
    report = _validate(tmp_path, [_v5_case(None)], r0=False, **_v5_parent(None), files=_runs(_PILOT_SHA))
    codes = {(v["code"], v["file"]) for v in report["violations"] if v["code"] == "runner_sha_missing"}
    assert codes == {("runner_sha_missing", f"cases/{_v5_case()['case_id']}/case_record.json"), ("runner_sha_missing", "PARENT_SUMMARY.json")}, _show(report)


def test_v5_runs_json_is_required_and_must_end_in_a_full_run(tmp_path):
    report = _validate(tmp_path, [_v5_case()], r0=False, **_v5_parent(_PILOT_SHA))
    assert ("runs_missing", "") in _runner_hits(report), _show(report)
    assert all(v["case_id"] is None for v in report["violations"] if v["code"] == "runs_missing")
    report_missing = report
    report = _validate(tmp_path / "b", [_v5_case()], r0=False, **_v5_parent(_PILOT_SHA), files=_runs("f" * 64, _PILOT_SHA, last_phase="cases"))
    assert ("runner_partial_rerun", "/-1/phase") in _runner_hits(report), _show(report)
    report_phase = report
    report = _validate(tmp_path / "c", [_v5_case()], r0=False, **_v5_parent(_PILOT_SHA), files=_runs(_PILOT_SHA, "e" * 64))
    assert ("runner_partial_rerun", "/-1/runner_sha256") in _runner_hits(report), _show(report)
    for rep in (report_missing, report_phase, report):
        runs_hits = [v for v in rep["violations"] if v["code"] in ("runs_missing", "runner_partial_rerun")]
        assert runs_hits and all(v["file"] == "RUNS.json" for v in runs_hits), _show(rep)


def test_v5_runs_json_shape_is_fail_closed(tmp_path):
    """Every RUNS.json entry must be well formed; only the last entry's phase and sha are rule-checked."""
    good = {"phase": "all", "runner_sha256": _PILOT_SHA, "started_utc": "2026-10-26T00:00:00Z"}
    no_started = {"phase": "all", "runner_sha256": _PILOT_SHA}
    shapes = {
        "object": {"phase": "all"},
        "empty": [],
        "no_started_utc": [no_started],
        "bad_earlier_entry": [{**good, "runner_sha256": None}, good],
    }
    for name, value in shapes.items():
        report = _validate(
            tmp_path / name, [_v5_case()], r0=False, **_v5_parent(_PILOT_SHA), files={"RUNS.json": json.dumps(value).encode("utf-8")}
        )
        hits = [v for v in report["violations"] if v["code"] in V5_RUNNER_CODES]
        assert [(v["code"], v["pointer"], v["file"], v["case_id"]) for v in hits] == [("runs_malformed", "", "RUNS.json", None)], f"{name}: {_show(report)}"


def test_v5_runner_sha_is_a_schema_defect_on_older_rows(tmp_path):
    """The shared schemas admit runner_sha256 for rev 5; a rev < 5 row or parent that carries it is refused like a v4-only key on rev < 4."""
    row = _patch(_v4_fragment(), ("/code_revision/runner_sha256", _PILOT_SHA))
    report = _validate(tmp_path, [row], r0=False, parent_edits=[("/brief_revision", 4)])
    hits = [v for v in report["violations"] if v["code"] == "schema_additional" and v["pointer"] == "/code_revision/runner_sha256"]
    # the test parent copies the first row's code_revision, so it carries the key too; the row's own hit is the one asserted here
    assert (f"cases/{row['case_id']}/case_record.json", row["case_id"]) in [(v["file"], v["case_id"]) for v in hits], _show(report)
    report = _validate(tmp_path / "parent", [_v4_fragment()], r0=False, parent_edits=[("/brief_revision", 4), ("/code_revision/runner_sha256", _PILOT_SHA)])
    hits = [v for v in report["violations"] if v["code"] == "schema_additional" and v["pointer"] == "/code_revision/runner_sha256"]
    assert [(v["file"], v["case_id"]) for v in hits] == [("PARENT_SUMMARY.json", None)], _show(report)


def test_v5_runner_rules_do_not_touch_rev4_records(tmp_path):
    """No runner_sha256 and no RUNS.json on a rev-4 row is exactly what 0015/0032 look like: nothing fires."""
    report = _validate(tmp_path, [_v4_fragment()], r0=False, parent_edits=[("/brief_revision", 4)])
    assert _runner_hits(report) == set(), _show(report)


# --------------------------------------------------------------------------
# brief v6 (ac), red first 2026-10-28: the synthetic CANARY_KSIGN second site validates beside the hvac site.
# Round 3's full batch (20261028_0442_r2) carried exactly one violation, synthetic_kind on that row: the brief asked
# for it, the validator's synthetic allowlist did not know it.  Admission is unconditional (a loosening only; the
# rev <= 5 batches never carried a synthetic KSIGN row, so their reports are byte-identical, pinned by the gate).
# --------------------------------------------------------------------------
def _synthetic_ksign() -> dict:
    """The second KSIGN site: the hvac KSIGN row moved onto the CTRL_SYN_T1 page while hvac is present, so its
    calibration_ref is not_applicable (as the 0442 row wrote it), never synthetic_only."""
    case = _synthetic(_resolve("ksign"))
    case["calibration_ref"] = "not_applicable"
    return case


def test_v6_a_synthetic_ksign_canary_is_admitted_beside_the_hvac_site(tmp_path):
    cases = [*(_resolve(k) for k in R0_KEYS), _synthetic_ksign(), _resolve("ek")]
    report = _validate(tmp_path, cases)
    assert report["violations"] == [], _show(report)
    assert report["ok"] is True


@pytest.mark.parametrize("key", ["tc", "font", "unsaved", "wrong", "ink"])
def test_v6_a_synthetic_canary_of_another_class_still_needs_synthetic_only(tmp_path, key):
    """Guard (green before and after): the brief 2.3 fallback is the only door for the other canary classes."""
    case = _synthetic(_resolve(key))
    case["calibration_ref"] = "not_applicable"
    report = _validate(tmp_path, [case], r0=False)
    assert ("synthetic_kind", "/kind") in _hits(report), _show(report)


# --------------------------------------------------------------------------
# brief v7 follow-ups, red first 2026-10-28 (round-4 lane stage A, owner-approved): the two KSIGN tightenings the v6
# admission left open.  Both are gated on eb.KSIGN_SECOND_SITE_REV (7): (1) a synthetic CANARY_KSIGN row pins
# synthetic_builder.kwargs to CTRL_SYN_KWARGS (brief 2.2: the site is CTRL_SYN_T1's before.pdf), fail closed on a
# missing or non-dict kwargs; (2) the synthetic KSIGN site is R0-required beside the hvac one, mirroring the two
# CANARY_GROWTH sites.  Brief v7 (ak) told Grok neither is checked yet; rev <= 6 batches stay byte-identical (gate).
# --------------------------------------------------------------------------
KSIGN_PIN = ("synthetic_pin_mismatch", "/source/synthetic_builder/kwargs")
CAL_INCOMPLETE = ("calibration_incomplete", "/calibration")
_ABSENT = object()


def _ksign_pin_hits(case: dict) -> list[tuple[str, str]]:
    """Every synthetic_pin_mismatch the cross-field rules give ``case`` (a list, so a double report shows)."""
    return [(v.code, v.pointer) for v in eb.check_cross_field(case).violations if v.code == "synthetic_pin_mismatch"]


def _synthetic_ksign_at(rev: int, **kwargs_edits) -> dict:
    case = _synthetic_ksign()
    case["brief_revision"] = rev
    case["source"]["synthetic_builder"]["kwargs"].update(kwargs_edits)
    return case


def _ksign_r0_report(
    tmp_path: Path, rev: int, *, with_synthetic: bool, counted: bool = True, row_rev: int | None = None, with_hvac: bool = True
) -> dict:
    """The R0 pack (hvac KSIGN site included unless ``with_hvac`` is False; the other hvac rows stay) at parent revision
    ``rev``, with or without the synthetic KSIGN site, with or without a counted row; ``row_rev`` sets the counted row's
    own brief_revision (the per-row arm of the gate)."""
    cases = [_resolve(k) for k in R0_KEYS if with_hvac or k != "ksign"]
    if with_synthetic:
        cases.append(_synthetic_ksign())
    if counted:
        cases.append(_resolve("ek"))
        if row_rev is not None:
            cases[-1]["brief_revision"] = row_rev
    return _validate(tmp_path, cases, r0=False, parent_edits=[("/brief_revision", rev)])


def _absent_count(item: dict) -> int:
    return int(item["detail"].split(" ", 1)[0])


def test_v7_a_synthetic_ksign_row_with_other_kwargs_is_a_pin_mismatch(tmp_path):
    assert _ksign_pin_hits(_synthetic_ksign_at(7, rotate=90)) == [KSIGN_PIN]
    assert _ksign_pin_hits(_synthetic_ksign_at(7, tail_text="尾")) == [KSIGN_PIN]
    # end to end: the row's own file carries it in the batch report
    case = _synthetic_ksign_at(7, rotate=90)
    report = _validate(tmp_path, [case], r0=False)
    hits = [(v["file"], v["case_id"]) for v in report["violations"] if (v["code"], v["pointer"]) == KSIGN_PIN]
    assert hits == [(f"cases/{case['case_id']}/case_record.json", case["case_id"])], _show(report)


@pytest.mark.parametrize("kwargs", [_ABSENT, None, "你好世界", [], {}], ids=["absent", "null", "string", "list", "empty"])
def test_v7_a_synthetic_ksign_row_without_the_pinned_kwargs_fails_closed(kwargs):
    case = _synthetic_ksign_at(7)
    builder = case["source"]["synthetic_builder"]
    if kwargs is _ABSENT:
        del builder["kwargs"]
    else:
        builder["kwargs"] = kwargs
    assert _ksign_pin_hits(case) == [KSIGN_PIN]


def test_v7_a_synthetic_ksign_row_with_the_ctrl_syn_kwargs_passes_the_pin():
    """Guard (green before and after): the (ac) row as brief 2.2 asks for it, and the hvac KSIGN row (no builder)."""
    assert _ksign_pin_hits(_synthetic_ksign_at(7)) == []
    hvac = _resolve("ksign")
    hvac["brief_revision"] = 7
    assert _ksign_pin_hits(hvac) == []


def test_v7_the_ksign_pin_does_not_touch_rev6_rows():
    """Guard (green before and after): brief v6 and older told Grok nothing about the kwargs, so nothing fires."""
    assert _ksign_pin_hits(_synthetic_ksign_at(6, rotate=90)) == []
    case = _synthetic_ksign_at(6)
    del case["source"]["synthetic_builder"]["kwargs"]
    assert _ksign_pin_hits(case) == []


def test_v7_a_hvac_present_batch_without_the_synthetic_ksign_site_is_incomplete(tmp_path):
    report = _ksign_r0_report(tmp_path, 7, with_synthetic=False)
    assert CAL_INCOMPLETE in _hits(report), _show(report)
    item = next(v for v in report["violations"] if (v["code"], v["pointer"]) == CAL_INCOMPLETE)
    assert (item["file"], _absent_count(item)) == ("PARENT_SUMMARY.json", 1), _show(report)


def test_v7_one_rev7_row_makes_the_batch_need_the_synthetic_ksign_site(tmp_path):
    """The gate is the batch's: the parent's revision OR any row's (here the parent says 6, the counted row 7)."""
    report = _ksign_r0_report(tmp_path, 6, with_synthetic=False, row_rev=7)
    assert CAL_INCOMPLETE in _hits(report), _show(report)


def test_v7_a_hvac_present_batch_with_both_ksign_sites_is_complete(tmp_path):
    report = _ksign_r0_report(tmp_path, 7, with_synthetic=True)
    assert CAL_INCOMPLETE not in _hits(report), _show(report)
    assert all(v["code"] != "calibration_incomplete" for v in report["unverifiable"])


def test_v7_the_synthetic_ksign_site_is_not_required_before_rev7(tmp_path):
    """Guard (green before and after): the same hvac-only shape at revision 6 is complete, as round 3 left it."""
    report = _ksign_r0_report(tmp_path, 6, with_synthetic=False)
    assert CAL_INCOMPLETE not in _hits(report), _show(report)


def test_v7_a_synthetic_only_batch_needs_only_the_synthetic_ksign_site(tmp_path):
    """Guard (green before and after): under brief 2.3 the KSIGN canary is the synthetic row alone, as for CANARY_GROWTH."""
    cases = [*_synthetic_only_keys(), _resolve("ek")]
    report = _validate(
        tmp_path,
        cases,
        edits=[(len(cases) - 1, "/calibration_ref", "synthetic_only")],
        parent_edits=[("/calibration/status", "synthetic_only"), ("/brief_revision", 7)],
        r0=False,
    )
    assert CAL_INCOMPLETE not in _hits(report), _show(report)


def test_v7_a_pilot_batch_without_the_synthetic_ksign_site_is_unverifiable_one_row_more(tmp_path):
    """A batch with no counted row (a pilot) lists the absent R0 rows as unverifiable, never as violations; at rev 7 a
    lone hvac KSIGN row counts as one more absent row than at rev 6."""
    def pilot(sub: str, rev: int) -> dict:
        cases = [_resolve(k) for k in ("t1", "t0", "neg", "ksign")]
        return _validate(tmp_path / sub, cases, r0=False, parent_edits=[("/brief_revision", rev)])

    six, seven = pilot("six", 6), pilot("seven", 7)
    for report in (six, seven):
        assert CAL_INCOMPLETE not in _hits(report), _show(report)
    items = {name: [v for v in rep["unverifiable"] if v["code"] == "calibration_incomplete"] for name, rep in (("six", six), ("seven", seven))}
    assert len(items["six"]) == 1 and len(items["seven"]) == 1, items
    assert _absent_count(items["seven"][0]) == _absent_count(items["six"][0]) + 1, items


def test_v7_the_ksign_tightenings_share_one_revision_constant(tmp_path, monkeypatch):
    """Both rules read eb.KSIGN_SECOND_SITE_REV by name, so moving the gate (say to 8 before merge-back) is one edit."""
    assert eb.KSIGN_SECOND_SITE_REV == 7
    monkeypatch.setattr(eb, "KSIGN_SECOND_SITE_REV", 8)
    assert _ksign_pin_hits(_synthetic_ksign_at(7, rotate=90)) == []
    assert CAL_INCOMPLETE not in _hits(_ksign_r0_report(tmp_path / "eight", 7, with_synthetic=False))
    monkeypatch.setattr(eb, "KSIGN_SECOND_SITE_REV", 6)
    assert _ksign_pin_hits(_synthetic_ksign_at(6, rotate=90)) == [KSIGN_PIN]
    assert CAL_INCOMPLETE in _hits(_ksign_r0_report(tmp_path / "six", 6, with_synthetic=False))


# stage A fix-up (refuter should_fix 1-3, 2026-10-28): the hvac arm of both two-site blocks, and the no-double-count guard.
def _absent_counts(report: dict) -> list[int]:
    """The absent-row count of every calibration_incomplete item, violation or unverifiable."""
    return [_absent_count(v) for v in report["violations"] + report["unverifiable"] if v["code"] == "calibration_incomplete"]


@pytest.mark.parametrize(
    ("cls", "synthetic", "rev"),
    [("CANARY_KSIGN", _synthetic_ksign, 7), ("CANARY_GROWTH", _canary_growth_syn, 6), ("CANARY_GROWTH", _canary_growth_syn, 7)],
    ids=["ksign-rev7", "growth-rev6", "growth-rev7"],
)
def test_v7_one_synthetic_row_relabelled_hvac_is_not_both_sites(tmp_path, cls, synthetic, rev):
    """The pack with both sites of both two-site classes, the class's rows replaced by ONE synthetic row whose slug (and
    join_key, sha) say hvac: it is the synthetic site only, so the hvac site is still absent (brief 5.1: a synthetic
    row's slug is ctrl-syn).  The hvac arm counts a non-synthetic hvac row, for CANARY_KSIGN from rev 7 and for its
    CANARY_GROWTH twin at every revision."""
    pack = [*(_resolve(k) for k in R0_KEYS), _synthetic_ksign()]
    cases = [*(c for c in pack if c["class_id"] != cls), _retarget(synthetic(), slug="hvac"), _resolve("ek")]
    report = _validate(tmp_path, cases, r0=False, parent_edits=[("/brief_revision", rev)])
    assert CAL_INCOMPLETE in _hits(report), _show(report)
    assert _absent_counts(report) == [1], _show(report)


def test_v7_a_hvac_present_batch_without_the_hvac_ksign_site_is_incomplete(tmp_path):
    """The hvac arm itself (deleting it left every other v7 test green): hvac present, the synthetic KSIGN row alone;
    rev 7 needs the hvac row too, rev 6 does not."""
    six = _ksign_r0_report(tmp_path / "six", 6, with_synthetic=True, with_hvac=False)
    seven = _ksign_r0_report(tmp_path / "seven", 7, with_synthetic=True, with_hvac=False)
    assert _absent_counts(six) == [], _show(six)
    assert CAL_INCOMPLETE in _hits(seven), _show(seven)
    assert _absent_counts(seven) == [1], _show(seven)


def test_v7_a_batch_without_any_ksign_row_counts_it_absent_once(tmp_path):
    """No KSIGN row at all: the class is already absent, so rev 7 adds nothing (the "not already missing" guard; dropping
    it counted KSIGN twice)."""
    counts = {
        rev: _absent_counts(_ksign_r0_report(tmp_path / str(rev), rev, with_synthetic=False, with_hvac=False)) for rev in (6, 7)
    }
    assert counts == {6: [1], 7: [1]}, counts
