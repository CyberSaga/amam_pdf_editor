# -*- coding: utf-8 -*-
"""Pilot for HVAC cases 2, 8, and deepened case 10. Evidence folder only; no product source edits."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import fitz
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from model.text_commit.cid_fonts import CidCapabilityFailure
from model.text_commit.dto import StreamReplacement
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.pdf_lexer import encode_hex_string, splice_stream
from model.text_commit.plan import PlanRejection
from model.text_commit.replay import replay_page_streams

EV = Path(__file__).resolve().parent
SRC = EV / "candidates" / "HVAC-source-copy.pdf"
SOURCE_SHA = "9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2"

# (case_id, page_index, seq, original, replacement, signature, primary_variable, deepen_label)
PILOT = (
    (
        2,
        4,
        16,
        "空調冷卻水管線系統圖(1)",
        "空調冷卻水管線系統表(1)",
        "mc_malformed_pairing",
        "cjk_ideograph_tu_to_biao_vs_case1_digit_only",
        None,
    ),
    (
        8,
        5,
        58,
        "空調系統設計圖說A版",
        "空調系統設計圖說B版",
        "verification_failed",
        "nonzero_tj_compensation_Aban_to_Bban_vs_case7_date_digit_kern0",
        None,
    ),
    (
        10,
        6,
        5,
        "Buffer Tank",
        "Tank Buf",
        "trm_reflected",
        "shorter_replacement_preserving_negative_det_tm_vs_prior_same_length_swap",
        "deepen_case_10",
    ),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shows(doc, page_index):
    page = doc[page_index]
    result = replay_page_streams([(x, doc.xref_stream(x)) for x in page.get_contents()])
    assert not result.malformed and not result.refusal_reason, result
    return result.shows


def trace_for(page, show, text):
    origin = fitz.Point(show.origin_user) * page.transformation_matrix
    matches = []
    for trace in page.get_texttrace():
        full = "".join(chr(c[0]) for c in trace["chars"])
        start = full.find(text)
        while start >= 0:
            chars = trace["chars"][start : start + len(text)]
            rect = fitz.Rect(chars[0][3])
            for char in chars[1:]:
                rect |= fitz.Rect(char[3])
            matches.append(dict(trace, chars=chars, bbox=tuple(rect)))
            start = full.find(text, start + 1)
    assert matches, text
    match = min(matches, key=lambda t: abs(fitz.Point(t["chars"][0][2]) - origin))
    assert abs(fitz.Point(match["chars"][0][2]) - origin) < 0.02
    return match


def render(page, zoom=2, clip=None):
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def engine_probe(engine, page, show, original, replacement):
    trace = trace_for(page, show, original)
    visual_origin = fitz.Point(trace["chars"][0][2]) * page.rotation_matrix
    visual_bbox = fitz.Rect(trace["bbox"]) * page.rotation_matrix
    plan = engine.prepare(
        page,
        target_text=original,
        replacement_text=replacement,
        expected_origin=tuple(visual_origin),
        target_bbox=tuple(visual_bbox),
    )
    if isinstance(plan, PlanRejection):
        return {"prepared": False, "reason": plan.reason, "detail": plan.detail}
    return {"prepared": True, "tier": int(plan.tier)}


def build_payload(cid, show, replacement):
    assert show.operator == "Tj" and show.string_kind == "hex"
    old_cids = tuple(
        int.from_bytes(show.decoded_bytes[i : i + 2], "big")
        for i in range(0, len(show.decoded_bytes), 2)
    )
    new_cids = cid.encode_strict(replacement)
    assert not isinstance(new_cids, CidCapabilityFailure), new_cids
    assert cid.glyph_gate(new_cids, replacement) is None
    delta = cid.advance_points(new_cids, show.font_size, show.char_spacing) - cid.advance_points(
        old_cids, show.font_size, show.char_spacing
    )
    kern = delta * 1000 / show.font_size
    encoded = encode_hex_string(cid.encode_cids(new_cids))
    if abs(kern) < 1e-8:
        start, end = show.string_start, show.string_end
        payload = encoded
    else:
        start, end = show.op_start, show.op_end
        payload = b"[" + encoded + f" {kern:.10f}".encode("ascii") + b"] TJ"
    return start, end, payload, kern, old_cids, new_cids


STATE_KEYS = (
    "font_resource",
    "font_size",
    "tm",
    "ctm",
    "hscale",
    "char_spacing",
    "word_spacing",
    "rise",
    "render_mode",
)


def same_attr(a, b):
    if hasattr(a, "__iter__") and not isinstance(a, (str, bytes)):
        return list(a) == list(b)
    return a == b


def hypotheses_for(case_id, probe, det):
    if case_id == 2:
        return [
            {
                "id": "H1_mc_wrapper",
                "statement": "seq=16 still mc_malformed_pairing despite different show/text",
                "falsification": "prepare reason/detail",
                "result": "supported" if probe.get("reason") == "mc_malformed_pairing" else "unresolved",
                "evidence": probe,
            },
            {
                "id": "H2_encode_tu_biao",
                "statement": "圖→表 encode_strict+glyph_gate clean (primary variable)",
                "falsification": "encode_strict / glyph_gate in M2",
                "result": "pending",
            },
            {
                "id": "H3_splice",
                "statement": "CID splice preserves font/Tm/neighbors",
                "falsification": "structure+render+save_reopen",
                "result": "pending",
            },
        ]
    if case_id == 8:
        return [
            {
                "id": "H1_fingerprint",
                "statement": "scratch fingerprint reject on seq=58",
                "falsification": "detail phrase",
                "result": (
                    "supported"
                    if probe.get("reason") == "verification_failed"
                    and "fingerprint" in str(probe.get("detail", "")).lower()
                    else "unresolved"
                ),
                "evidence": probe,
            },
            {
                "id": "H2_nonzero_tj",
                "statement": "A版→B版 needs nonzero TJ compensation (primary variable)",
                "falsification": "|kern|>>0",
                "result": "pending",
            },
            {
                "id": "H3_splice",
                "statement": "splice+TJ compensate+saveIncr no-jump",
                "falsification": "structure+render+save_reopen",
                "result": "pending",
            },
        ]
    return [
        {
            "id": "H1_engine_trm",
            "statement": "shorter replacement still trm_reflected",
            "falsification": "live reason",
            "result": "supported" if probe.get("reason") == "trm_reflected" else "unresolved",
            "evidence": probe,
        },
        {
            "id": "H2_preserve_neg_det",
            "statement": "negative det(Tm) preserved after shorter splice",
            "falsification": "det_tm before==after and <0",
            "result": "pending",
            "evidence": {"det_tm_before": det},
        },
        {
            "id": "H3_shorter_splice",
            "statement": "shorter replacement structure/render/save_reopen pass",
            "falsification": "structure+render+save_reopen",
            "result": "pending",
        },
    ]


def write_case_docs(case_dir, case_id, signature, page_index, seq, primary_variable, deepen):
    deepen_note = f"\n- Label: `{deepen}` (NOT a new trm case_id).\n" if deepen else "\n"
    (case_dir / "suggested_product_layer_changes.md").write_text(
        f"""# Suggested product-layer changes (case {case_id} / {signature})

- Primary variable this run: `{primary_variable}`{deepen_note}- Keep fail-closed; do not disable `{signature}` globally.
- Use this show fingerprint + live probe detail as a regression fixture.
- Case 2: MC gate locality across distinct shows (seq 11 vs 16) with ideograph-class edits.
- Case 8: fingerprint stable spelling under nonzero TJ compensation paths.
- Case 10 deepen: admit intentional reflected TRM only with tests that preserve negative det under length-changing replacements.
- Experiment splice success is NOT product acceptance while prepare still rejects.
""",
        encoding="utf-8",
    )
    (case_dir / "suggested_regression_tests.md").write_text(
        f"""# Regression tests (case {case_id})

1. Pin HVAC sha256 `{SOURCE_SHA}`, page_index={page_index}, seq={seq}.
2. Assert prepare reason == `{signature}` until an intentional gate change.
3. Primary variable under test: `{primary_variable}`.
4. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
5. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
""",
        encoding="utf-8",
    )
    (case_dir / "unproven_limits.md").write_text(
        """# Unproven limits
- UI preview / Apply / Undo / Redo not run.
- No accepted_for_code: product engine still rejects; UI unverified.
- Multi-item TJ (pre-existing), Form XObject, signed PDFs, missing-glyph embedding not covered.
- No second explicit trm_reflected case_id found in inventory/results.
""",
        encoding="utf-8",
    )


def run_one(source, case_id, page_index, seq, original, replacement, signature, primary_variable, deepen):
    case_dir = EV / (f"case-{case_id}-deepen" if deepen else f"case-{case_id}")
    case_dir.mkdir(exist_ok=True)
    record = {
        "case_id": str(case_id),
        "deepen_label": deepen,
        "status": "discovered",
        "source_sha256": SOURCE_SHA,
        "page_index": page_index,
        "text_object_fingerprint": None,
        "text_class": "type0_cid_single_hex_tj",
        "original_text": original,
        "replacement_text": replacement,
        "primary_variable": primary_variable,
        "mutation_type": "in_stream_cid_operand_replace",
        "hypothesis": [],
        "proposed_edit_method": [
            "M1_TieredCommitEngine_prepare_max_tier_1",
            "M2_replay_cid_encode_strict_stream_splice",
            "M3_tj_trailing_compensation_if_advance_delta",
        ],
        "preconditions": [
            "isolated HVAC copy with verified sha256",
            f"replay show seq={seq} on page_index={page_index}",
            "encode_strict + glyph_gate",
            f"primary_variable={primary_variable}",
        ],
        "changed_objects": [],
        "evidence_refs": [
            f"{case_dir.name}/",
            "METHODS_AND_EVIDENCE_PLAN.md",
            "output/pdf/manual-font-study/results.json",
            "docs/experiments/2026-09-21-hvac-font-edits.md",
            "scripts/experiment_hvac_font_edits.py",
            "_evidence_pilot/20260924_1431/",
        ],
        "failed_alternatives": [],
        "unverified_items": ["product_ui_preview_apply_undo_redo"],
        "next_job": None,
        "signature_expected": signature,
        "seq": seq,
        "accepted_for_code": False,
    }
    failed = []

    page = source[page_index]
    show = shows(source, page_index)[seq]
    registry = DocumentFontRegistry(source)
    cap = registry.capability(page, show.font_resource)
    assert cap is not None and cap.cid is not None
    assert cap.cid.decode_show_bytes(show.decoded_bytes) == original

    tm = list(show.tm)
    det = tm[0] * tm[3] - tm[1] * tm[2]
    fp = {
        "page_index": page_index,
        "seq": seq,
        "stream_xref": show.stream_xref,
        "font_resource": show.font_resource,
        "font_size": show.font_size,
        "tm": tm,
        "ctm": list(show.ctm),
        "det_tm": det,
        "hscale": show.hscale,
        "char_spacing": show.char_spacing,
        "word_spacing": show.word_spacing,
        "rise": show.rise,
        "render_mode": show.render_mode,
        "origin_user": list(show.origin_user),
        "op_start": show.op_start,
        "op_end": show.op_end,
        "string_start": show.string_start,
        "string_end": show.string_end,
    }
    record["text_object_fingerprint"] = hashlib.sha256(
        json.dumps(fp, sort_keys=True).encode("utf-8")
    ).hexdigest()
    (case_dir / "structure_notes.json").write_text(
        json.dumps(
            {
                "fields": fp,
                "decoded": original,
                "font_xref": cap.font_xref,
                "primary_variable": primary_variable,
                "deepen_label": deepen,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    engine = TieredCommitEngine(source, max_tier=1)
    probe = engine_probe(engine, page, show, original, replacement)
    (case_dir / "live_engine_probe.json").write_text(
        json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if probe.get("reason") == signature:
        record["status"] = "reproducible_engine"
    else:
        failed.append({"method": "M1", "note": "reason mismatch", "probe": probe})

    hyp = hypotheses_for(case_id, probe, det)

    cand_name = f"HVAC-case-{case_id}-deepen-edited.pdf" if deepen else f"HVAC-case-{case_id}-edited.pdf"
    cand = EV / "candidates" / cand_name
    if cand.exists():
        cand.unlink()
    shutil.copyfile(SRC, cand)

    with fitz.open(cand) as cand_doc:
        with fitz.open(SRC) as src2:
            show0 = shows(src2, page_index)[seq]
            reg2 = DocumentFontRegistry(src2)
            cap2 = reg2.capability(src2[page_index], show0.font_resource)
            assert cap2 is not None and cap2.cid is not None
            start, end, payload, kern, old_cids, new_cids = build_payload(
                cap2.cid, show0, replacement
            )
            if case_id == 2:
                for h in hyp:
                    if h["id"] == "H2_encode_tu_biao":
                        h["result"] = "supported"
                        h["evidence"] = {
                            "old_cids_len": len(old_cids),
                            "new_cids_len": len(new_cids),
                            "kern": kern,
                        }
            if case_id == 8:
                for h in hyp:
                    if h["id"] == "H2_nonzero_tj":
                        h["result"] = "supported" if abs(kern) > 1e-6 else "falsified"
                        h["evidence"] = {"kern": kern}
            stream = cand_doc.xref_stream(show0.stream_xref)
            new_stream = splice_stream(
                stream,
                [
                    StreamReplacement(
                        show0.stream_xref,
                        start,
                        end,
                        stream[start:end],
                        payload,
                        hashlib.sha256(stream).hexdigest(),
                    )
                ],
            )
            cand_doc.update_stream(show0.stream_xref, new_stream)
            cand_doc.saveIncr()

    out_sha = sha256(cand)
    with fitz.open(cand) as cand_doc:
        with fitz.open(SRC) as src2:
            show_b = shows(src2, page_index)[seq]
            show_a = shows(cand_doc, page_index)[seq]
            reg_a = DocumentFontRegistry(cand_doc)
            cap_a = reg_a.capability(cand_doc[page_index], show_a.font_resource)
            decoded_a = cap_a.cid.decode_show_bytes(show_a.decoded_bytes)
            state_errors = []
            for key in STATE_KEYS:
                vb = getattr(show_b, key)
                va = getattr(show_a, key)
                if not same_attr(vb, va):
                    state_errors.append(
                        {
                            key: {
                                "old": list(vb) if hasattr(vb, "__iter__") and not isinstance(vb, (str, bytes)) else vb,
                                "new": list(va) if hasattr(va, "__iter__") and not isinstance(va, (str, bytes)) else va,
                            }
                        }
                    )
            if list(show_b.origin_user) != list(show_a.origin_user):
                if not any("origin_user" in e for e in state_errors):
                    state_errors.append(
                        {"origin_user": {"old": list(show_b.origin_user), "new": list(show_a.origin_user)}}
                    )
            det_a = show_a.tm[0] * show_a.tm[3] - show_a.tm[1] * show_a.tm[2]
            text_ok = decoded_a == replacement
            structure_ok = text_ok and not state_errors
            (case_dir / "object_diffs.json").write_text(
                json.dumps(
                    {
                        "stream_xref": show_b.stream_xref,
                        "start": start,
                        "end": end,
                        "kern": kern,
                        "payload": payload.decode("ascii"),
                        "decoded_after": decoded_a,
                        "text_ok": text_ok,
                        "state_errors": state_errors,
                        "det_tm_before": det,
                        "det_tm_after": det_a,
                        "output_sha256": out_sha,
                        "primary_variable": primary_variable,
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            record["changed_objects"] = [
                {"stream_xref": show_b.stream_xref, "start": start, "end_old": end, "kern": kern}
            ]

            if case_id == 10:
                for h in hyp:
                    if h["id"] == "H2_preserve_neg_det":
                        ok = abs(det_a - det) < 1e-12 and det_a < 0
                        h["result"] = "supported" if ok else "falsified"
                        h["evidence"] = {
                            "det_tm_before": det,
                            "det_tm_after": det_a,
                            "tm_after": list(show_a.tm),
                        }

            sh_b = shows(src2, page_index)
            sh_a = shows(cand_doc, page_index)
            neighbor_diffs = []
            for i, (a, b) in enumerate(zip(sh_b, sh_a)):
                if i == seq:
                    continue
                if list(a.origin_user) != list(b.origin_user) or a.font_resource != b.font_resource:
                    neighbor_diffs.append(
                        {
                            "seq": i,
                            "origin_before": list(a.origin_user),
                            "origin_after": list(b.origin_user),
                        }
                    )
                    if len(neighbor_diffs) >= 25:
                        break
            (case_dir / "neighbor_notes.json").write_text(
                json.dumps(
                    {"neighbor_diff_count": len(neighbor_diffs), "sample": neighbor_diffs[:10]},
                    indent=2,
                ),
                encoding="utf-8",
            )

            old_tr = trace_for(src2[page_index], show_b, original)
            new_tr = trace_for(cand_doc[page_index], show_a, replacement)
            rect = fitz.Rect(old_tr["bbox"]) | fitz.Rect(new_tr["bbox"])
            rect = rect * src2[page_index].rotation_matrix
            rect += (-3, -3, 3, 3)
            before = render(src2[page_index], 6, rect)
            after = render(cand_doc[page_index], 6, rect)
            changed = int(np.any(np.array(before) != np.array(after), axis=2).sum())
            before.save(case_dir / "render-before.png")
            after.save(case_dir / "render-after.png")
            before2 = np.array(render(src2[page_index], 2))
            after2 = np.array(render(cand_doc[page_index], 2))
            diff = np.any(before2 != after2, axis=2)
            bounds = (rect * fitz.Matrix(2, 2)).irect
            diff[max(0, bounds.y0) : bounds.y1, max(0, bounds.x0) : bounds.x1] = False
            outside = int(diff.sum())
            render_notes = {
                "changed_pixels_6x_crop": changed,
                "outside_target_changed_pixels_2x": outside,
                "crop_visual": list(rect),
                "primary_variable": primary_variable,
            }
            (case_dir / "render_diff_notes.json").write_text(
                json.dumps(render_notes, indent=2), encoding="utf-8"
            )
            (case_dir / "save_reopen_notes.json").write_text(
                json.dumps(
                    {
                        "candidate": str(cand),
                        "output_sha256": out_sha,
                        "source_sha256": SOURCE_SHA,
                        "method": "copyfile+update_stream+saveIncr+reopen",
                        "decoded_after_reopen": decoded_a,
                        "replacement": replacement,
                        "kern": kern,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            if structure_ok and not neighbor_diffs:
                record["status"] = "structure_pass"
                for h in hyp:
                    if h["id"].startswith("H3"):
                        h["result"] = "supported_structure"
                if changed > 0 and outside == 0:
                    record["status"] = "save_reopen_pass"
                    for h in hyp:
                        if h["id"].startswith("H3"):
                            h["result"] = "supported"
                    record["unverified_items"].append("UI_not_verified_in_this_pilot")
                    record["next_job"] = (
                        f"Product engine still rejects with {signature}; "
                        "do not accepted_for_code until gate fix + UI phases."
                    )
                else:
                    failed.append({"method": "render", "notes": render_notes})
                    if changed == 0:
                        record["status"] = "insufficient_evidence"
            else:
                failed.append(
                    {
                        "method": "M2_structure",
                        "text_ok": text_ok,
                        "state_errors": state_errors,
                        "neighbor_diffs": len(neighbor_diffs),
                    }
                )
                record["status"] = "rejected" if neighbor_diffs else "blocked"

    assert sha256(SRC) == SOURCE_SHA
    write_case_docs(case_dir, case_id, signature, page_index, seq, primary_variable, deepen)
    (case_dir / "failed_methods.json").write_text(
        json.dumps(failed, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    record["hypothesis"] = hyp
    record["failed_alternatives"] = failed
    assert record["status"] != "accepted_for_code"
    assert record["accepted_for_code"] is False
    (case_dir / "case_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    label = f"{case_id}/{deepen}" if deepen else str(case_id)
    print(f"CASE {label}: status={record['status']} probe={probe} kern={kern}", flush=True)
    return record


def main():
    assert SRC.exists(), SRC
    assert sha256(SRC) == SOURCE_SHA, sha256(SRC)
    cases_out = []
    with fitz.open(SRC) as source:
        for row in PILOT:
            cases_out.append(run_one(source, *row))

    blocked = {
        "case_id": None,
        "label": "next_trm_reflected_sibling",
        "status": "blocked",
        "reason": "insufficient_evidence",
        "detail": (
            "Repo/results/docs/prior inventory contain only HVAC case_id=10 with "
            "explicit engine reason trm_reflected. No second explicit case_id; not invented."
        ),
        "search_refs": [
            "output/pdf/manual-font-study/results.json (trm cases: [10])",
            "scripts/experiment_hvac_font_edits.py CASES",
            "docs/experiments/2026-09-21-hvac-font-edits.md",
            "output/pdf/cad-font-study/results.json (no trm_reflected)",
            "_evidence_pilot/20260924_1431/INVENTORY.md",
        ],
        "accepted_for_code": False,
    }
    (EV / "trm_sibling_blocked.json").write_text(
        json.dumps(blocked, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    cases_out.append(blocked)
    (EV / "cases.json").write_text(
        json.dumps(cases_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("DONE", EV / "cases.json")


if __name__ == "__main__":
    main()
