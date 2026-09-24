# -*- coding: utf-8 -*-
"""Isolated true-text pilots for five non-default font candidates.
Evidence folder only; no product source edits. Labels not invented integer case_ids.
"""
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
ECC_SRC = EV / "candidates" / "ECC-source-copy.pdf"
HVAC_SRC = EV / "candidates" / "HVAC-source-copy.pdf"
ECC_SHA = "0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853"
HVAC_SHA = "9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2"

# (label, pdf_key, page_index, seq, original, replacement, primary_variable, font_name, expected_resource, expected_xref)
PILOT = (
    (
        "cand-ecc-jhenghei-seq0",
        "ECC",
        0,
        0,
        "排煙室",
        "排煙房",
        "ecc_jhenghei_plan_label",
        "MicrosoftJhengHeiRegular",
        "F1",
        13,
    ),
    (
        "cand-hvac-simsun-2f",
        "HVAC",
        6,
        4,
        "2F-平台",
        "1F-平台",
        "cjk_song_simsun_cad_labels",
        "SimSun",
        "C2_0",
        9185,
    ),
    (
        "cand-hvac-kai-cover",
        "HVAC",
        0,
        7,
        "[CLIENT_ORG]",
        "[CLIENT_ORG_SITE]",
        "hvac_kai_cover_vs_ecc_titleblock",
        "DFKaiShu-SB-Estd-BF",
        "F5",
        10663,
    ),
    (
        "cand-hvac-trebuchet-m5",
        "HVAC",
        3,
        53,
        "M5 System Engineering Division",
        "MM System Engineering Division",
        "latin_specialty_trebuchet_cid",
        "TrebuchetMS",
        "C2_4",
        9167,
    ),
    (
        "cand-hvac-yahei-bold",
        "HVAC",
        3,
        1,
        "空調系統",
        "系統空調",
        "cjk_yahei_bold_beyond_jhenghei",
        "MicrosoftYaHei-Bold",
        "C2_1",
        9161,
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
    """Support Tj hex and single-item TJ array hex (Kai cover)."""
    assert show.string_kind in ("hex", "array"), show.string_kind
    if show.operator == "TJ":
        assert getattr(show, "array_item_count", 1) == 1, show.array_item_count
    else:
        assert show.operator == "Tj", show.operator

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
        if show.operator == "Tj":
            start, end = show.string_start, show.string_end
            payload = encoded
        else:
            # string span is [<hex>] for single-item TJ
            start, end = show.string_start, show.string_end
            payload = b"[" + encoded + b"]"
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


def hypotheses_for(label, probe, det, kern=None):
    base = [
        {
            "id": "H1_engine_prepare",
            "statement": f"TieredCommitEngine prepare max_tier=1 rejects or reports reason for {label}",
            "falsification": "live probe prepared/reason/detail",
            "result": (
                "supported_reject"
                if not probe.get("prepared")
                else ("unexpected_prepare_ok" if probe.get("prepared") else "unresolved")
            ),
            "evidence": probe,
        },
        {
            "id": "H2_encode_strict",
            "statement": f"encode_strict+glyph_gate succeed for planned replacement on {label}",
            "falsification": "CidCapabilityFailure / glyph_gate",
            "result": "pending",
        },
        {
            "id": "H3_splice_checks",
            "statement": (
                f"CID splice preserves font_resource/Tm/det={det:.6g}/neighbors; "
                "crop changes; outside halo 0; saveIncr reopen decodes"
            ),
            "falsification": "structure+render+save_reopen",
            "result": "pending",
        },
    ]
    return base


def write_case_docs(case_dir, label, page_index, seq, primary_variable, font_name, source_sha):
    (case_dir / "suggested_product_layer_changes.md").write_text(
        f"""# Suggested product-layer changes ({label})

- Primary variable: {primary_variable} (font face/family vs prior PMingLiU/Arial/ECC-Kai).
- Font under test: {font_name}.
- Lineage: candidate_discovered from 20260924_1908_font_search; has_explicit_case_id=false.
- Keep fail-closed; do not weaken prepare gates globally from this experiment splice.
- Experiment splice success is NOT product acceptance while prepare still rejects / UI unverified.
""",
        encoding="utf-8",
    )
    (case_dir / "suggested_regression_tests.md").write_text(
        f"""# Regression tests ({label})

1. Pin source sha256 {source_sha}, page_index={page_index}, seq={seq}, font {font_name}.
2. Record prepare reason from live_engine_probe.json until intentional gate change.
3. Primary variable: {primary_variable}.
4. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
5. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
""",
        encoding="utf-8",
    )
    (case_dir / "unproven_limits.md").write_text(
        """# Unproven limits
- UI preview / Apply / Undo / Redo not run.
- No accepted_for_code: product engine may still reject; UI unverified.
- Multi-item TJ (non-single), Form XObject, signed PDFs, missing-glyph embedding not covered.
- Sparse subset fonts may only allow glyph-reuse edits (documented in case_record).
""",
        encoding="utf-8",
    )


def run_one(source_path, source_sha, label, page_index, seq, original, replacement,
            primary_variable, font_name, expected_resource, expected_xref):
    case_dir = EV / f"case-{label}"
    case_dir.mkdir(exist_ok=True)
    record = {
        "case_id": label,
        "has_explicit_case_id": False,
        "lineage": "candidate_discovered",
        "lineage_ref": "_evidence_pilot/20260924_1908_font_search/PARENT_SUMMARY.json#top_pilot_candidates",
        "status": "discovered",
        "source_sha256": source_sha,
        "page_index": page_index,
        "text_object_fingerprint": None,
        "text_class": "type0_cid_identity_h",
        "font_name": font_name,
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
            "isolated source copy with verified sha256",
            f"replay show seq={seq} on page_index={page_index}",
            "encode_strict + glyph_gate",
            f"primary_variable={primary_variable}",
            f"font={font_name} resource={expected_resource} xref={expected_xref}",
        ],
        "changed_objects": [],
        "evidence_refs": [
            f"{case_dir.name}/",
            "METHODS_AND_EVIDENCE_PLAN.md",
            "FONT_CASE_MAP.md",
            "_evidence_pilot/20260924_1908_font_search/",
            "_evidence_pilot/20260924_1431/",
            "_evidence_pilot/20260924_1453/",
            "_evidence_pilot/20260924_1612/",
        ],
        "failed_alternatives": [],
        "unverified_items": ["product_ui_preview_apply_undo_redo"],
        "next_job": None,
        "seq": seq,
        "accepted_for_code": False,
        "attempts": 0,
    }
    failed = []
    attempts = 0

    with fitz.open(source_path) as source:
        page = source[page_index]
        show = shows(source, page_index)[seq]
        registry = DocumentFontRegistry(source)
        cap = registry.capability(page, show.font_resource)
        assert cap is not None and cap.cid is not None
        assert cap.cid.decode_show_bytes(show.decoded_bytes) == original
        assert show.font_resource == expected_resource, (show.font_resource, expected_resource)
        assert cap.font_xref == expected_xref, (cap.font_xref, expected_xref)

        tm = list(show.tm)
        det = tm[0] * tm[3] - tm[1] * tm[2]
        fp = {
            "page_index": page_index,
            "seq": seq,
            "stream_xref": show.stream_xref,
            "font_resource": show.font_resource,
            "font_xref": cap.font_xref,
            "font_name": font_name,
            "font_size": show.font_size,
            "operator": show.operator,
            "string_kind": show.string_kind,
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
        record["text_class"] = (
            "type0_cid_single_hex_tj_array"
            if show.operator == "TJ"
            else "type0_cid_single_hex_tj"
        )
        (case_dir / "structure_notes.json").write_text(
            json.dumps(
                {
                    "fields": fp,
                    "decoded": original,
                    "font_xref": cap.font_xref,
                    "primary_variable": primary_variable,
                    "has_explicit_case_id": False,
                    "lineage": "candidate_discovered",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        attempts += 1
        engine = TieredCommitEngine(source, max_tier=1)
        probe = engine_probe(engine, page, show, original, replacement)
        (case_dir / "live_engine_probe.json").write_text(
            json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not probe.get("prepared"):
            record["status"] = "reproducible_engine_reject"
            record["signature_observed"] = probe.get("reason")
        else:
            record["status"] = "engine_prepared_unexpected"
            failed.append({"method": "M1", "note": "prepare succeeded unexpectedly", "probe": probe})

        hyp = hypotheses_for(label, probe, det)

    cand_name = f"{label}-edited.pdf"
    cand = EV / "candidates" / cand_name
    if cand.exists():
        cand.unlink()
    shutil.copyfile(source_path, cand)

    attempts += 1
    with fitz.open(cand) as cand_doc:
        with fitz.open(source_path) as src2:
            show0 = shows(src2, page_index)[seq]
            reg2 = DocumentFontRegistry(src2)
            cap2 = reg2.capability(src2[page_index], show0.font_resource)
            assert cap2 is not None and cap2.cid is not None
            start, end, payload, kern, old_cids, new_cids = build_payload(
                cap2.cid, show0, replacement
            )
            for h in hyp:
                if h["id"] == "H2_encode_strict":
                    h["result"] = "supported"
                    h["evidence"] = {
                        "old_cids_len": len(old_cids),
                        "new_cids_len": len(new_cids),
                        "kern": kern,
                        "operator": show0.operator,
                    }
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

    attempts += 1
    out_sha = sha256(cand)
    with fitz.open(cand) as cand_doc:
        with fitz.open(source_path) as src2:
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
                                "old": list(vb)
                                if hasattr(vb, "__iter__") and not isinstance(vb, (str, bytes))
                                else vb,
                                "new": list(va)
                                if hasattr(va, "__iter__") and not isinstance(va, (str, bytes))
                                else va,
                            }
                        }
                    )
            if list(show_b.origin_user) != list(show_a.origin_user):
                if not any("origin_user" in e for e in state_errors):
                    state_errors.append(
                        {
                            "origin_user": {
                                "old": list(show_b.origin_user),
                                "new": list(show_a.origin_user),
                            }
                        }
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
                        "font_resource_preserved": show_a.font_resource == expected_resource,
                        "font_xref_preserved": cap_a.font_xref == expected_xref,
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
                        "source_sha256": source_sha,
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
                        f"Product prepare reason={probe.get('reason')}; "
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

    assert sha256(source_path) == source_sha
    write_case_docs(case_dir, label, page_index, seq, primary_variable, font_name, source_sha)
    (case_dir / "failed_methods.json").write_text(
        json.dumps(failed, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    record["hypothesis"] = hyp
    record["failed_alternatives"] = failed
    record["attempts"] = attempts
    assert record["accepted_for_code"] is False
    assert record["status"] != "accepted_for_code"
    (case_dir / "case_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        f"CASE {label}: status={record['status']} probe={probe} kern={kern} attempts={attempts}",
        flush=True,
    )
    return record


def main():
    assert ECC_SRC.exists() and HVAC_SRC.exists()
    assert sha256(ECC_SRC) == ECC_SHA, sha256(ECC_SRC)
    assert sha256(HVAC_SRC) == HVAC_SHA, sha256(HVAC_SRC)
    (EV / "_STAMP.txt").write_text("20260924_1941_font_pilots\\n", encoding="utf-8")

    cases_out = []
    for row in PILOT:
        label, pdf_key, page_index, seq, original, replacement, primary, font, res, xref = row
        if pdf_key == "ECC":
            src, sha = ECC_SRC, ECC_SHA
        else:
            src, sha = HVAC_SRC, HVAC_SHA
        try:
            cases_out.append(
                run_one(src, sha, label, page_index, seq, original, replacement, primary, font, res, xref)
            )
        except Exception as e:
            err = {
                "case_id": label,
                "has_explicit_case_id": False,
                "lineage": "candidate_discovered",
                "status": "blocked",
                "error": repr(e),
                "accepted_for_code": False,
                "primary_variable": primary,
                "font_name": font,
                "page_index": page_index,
                "seq": seq,
                "original_text": original,
                "replacement_text": replacement,
            }
            case_dir = EV / f"case-{label}"
            case_dir.mkdir(exist_ok=True)
            (case_dir / "case_record.json").write_text(
                json.dumps(err, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (case_dir / "failed_methods.json").write_text(
                json.dumps([{"method": "exception", "error": repr(e)}], indent=2),
                encoding="utf-8",
            )
            print(f"CASE {label}: BLOCKED {e!r}", flush=True)
            cases_out.append(err)

    (EV / "cases.json").write_text(
        json.dumps(cases_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("DONE", EV / "cases.json")


if __name__ == "__main__":
    main()
