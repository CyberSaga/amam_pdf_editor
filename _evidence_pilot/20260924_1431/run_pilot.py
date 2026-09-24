# -*- coding: utf-8 -*-
"""Pilot for HVAC cases 1,7,10 only. Evidence folder script; does not modify product source."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import traceback
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

# Explicit case numbers from scripts/experiment_hvac_font_edits.py CASES / results.json "case"
PILOT = (
    (1, 4, 11, "空調冰水管線系統圖(1)", "空調冰水管線系統圖(4)", "mc_malformed_pairing"),
    (7, 5, 60, "2026.05.15", "2026.05.16", "verification_failed"),
    (10, 6, 5, "Buffer Tank", "Tank Buffer", "trm_reflected"),
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
    return start, end, payload, kern


def main():
    assert SRC.exists(), SRC
    assert sha256(SRC) == SOURCE_SHA, sha256(SRC)

    cases_out = []
    with fitz.open(SRC) as source:
        for case_id, page_index, seq, original, replacement, signature in PILOT:
            case_dir = EV / f"case-{case_id}"
            case_dir.mkdir(exist_ok=True)
            record = {
                "case_id": str(case_id),
                "status": "discovered",
                "source_sha256": SOURCE_SHA,
                "page_index": page_index,
                "text_object_fingerprint": None,
                "text_class": "type0_cid_single_hex_tj",
                "original_text": original,
                "replacement_text": replacement,
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
                ],
                "changed_objects": [],
                "evidence_refs": [
                    f"case-{case_id}/",
                    "METHODS_AND_EVIDENCE_PLAN.md",
                    "output/pdf/manual-font-study/results.json",
                    "docs/experiments/2026-09-21-hvac-font-edits.md",
                    "scripts/experiment_hvac_font_edits.py",
                ],
                "failed_alternatives": [],
                "unverified_items": ["product_ui_preview_apply_undo_redo"],
                "next_job": None,
                "signature_expected": signature,
                "seq": seq,
            }
            failed = []
            hyp = []

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
                json.dumps({"fields": fp, "decoded": original, "font_xref": cap.font_xref}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # M1 engine probe
            engine = TieredCommitEngine(source, max_tier=1)
            probe = engine_probe(engine, page, show, original, replacement)
            (case_dir / "live_engine_probe.json").write_text(
                json.dumps(probe, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            if probe.get("reason") == signature:
                record["status"] = "reproducible_engine"
            else:
                failed.append({"method": "M1", "note": "reason mismatch", "probe": probe})

            if case_id == 1:
                hyp = [
                    {"id": "H1_mc_wrapper", "statement": "wrapper unclosed or crosses q/Q",
                     "falsification": "prepare reason/detail", "result": "supported" if probe.get("reason") == "mc_malformed_pairing" else "unresolved",
                     "evidence": probe},
                    {"id": "H2_local_gate", "statement": "rejection is show-local",
                     "falsification": "other page shows may differ", "result": "insufficient_evidence"},
                    {"id": "H3_splice", "statement": "CID splice preserves font/Tm/neighbors",
                     "falsification": "structure+render+save_reopen", "result": "pending"},
                ]
            elif case_id == 7:
                hyp = [
                    {"id": "H1_fingerprint", "statement": "scratch fingerprint changes",
                     "falsification": "detail phrase", "result": "supported" if "fingerprint" in str(probe.get("detail", "")).lower() else "unresolved",
                     "evidence": probe},
                    {"id": "H2_numeric_spelling", "statement": "drift is float/int spelling",
                     "falsification": "fingerprint input compare", "result": "insufficient_evidence"},
                    {"id": "H3_splice", "statement": "splice+saveIncr still no-jump",
                     "falsification": "structure+render+save_reopen", "result": "pending"},
                ]
            else:
                hyp = [
                    {"id": "H1_negative_det", "statement": "Tm negative determinant (mirror)",
                     "falsification": f"det_tm={det}", "result": "supported" if det < 0 else "rejected"},
                    {"id": "H2_engine_trm", "statement": "prepare refuses trm_reflected",
                     "falsification": "live reason", "result": "supported" if probe.get("reason") == "trm_reflected" else "unresolved",
                     "evidence": probe},
                    {"id": "H3_preserve_tm", "statement": "splice keeping Tm passes checks",
                     "falsification": "structure+render+save_reopen", "result": "pending"},
                ]

            # M2/M3 splice on isolated copy
            cand = EV / "candidates" / f"HVAC-case-{case_id}-edited.pdf"
            shutil.copyfile(SRC, cand)
            start, end, payload, kern = build_payload(cap.cid, show, replacement)
            stream = source.xref_stream(show.stream_xref)
            repl = StreamReplacement(
                show.stream_xref,
                start,
                end,
                stream[start:end],
                payload,
                hashlib.sha256(stream).hexdigest(),
            )
            with fitz.open(cand) as candidate:
                original_stream = candidate.xref_stream(show.stream_xref)
                candidate.update_stream(
                    show.stream_xref, splice_stream(original_stream, [repl]), compress=True
                )
                candidate.saveIncr()

            out_sha = sha256(cand)
            with fitz.open(SRC) as src2, fitz.open(cand) as cand_doc:
                show_b = shows(src2, page_index)[seq]
                show_a = shows(cand_doc, page_index)[seq]
                reg_a = DocumentFontRegistry(cand_doc)
                cap_a = reg_a.capability(cand_doc[page_index], show_a.font_resource)
                decoded_a = cap_a.cid.decode_show_bytes(show_a.decoded_bytes)
                state_errors = []
                for key in (
                    "font_resource",
                    "font_size",
                    "tm",
                    "ctm",
                    "hscale",
                    "char_spacing",
                    "word_spacing",
                    "rise",
                    "render_mode",
                ):
                    if getattr(show_b, key) != getattr(show_a, key):
                        state_errors.append({key: {"old": getattr(show_b, key), "new": getattr(show_a, key)}})
                if list(show_b.origin_user) != list(show_a.origin_user):
                    state_errors.append(
                        {"origin_user": {"old": list(show_b.origin_user), "new": list(show_a.origin_user)}}
                    )
                text_ok = decoded_a == replacement
                structure_ok = text_ok and not state_errors
                (case_dir / "object_diffs.json").write_text(
                    json.dumps(
                        {
                            "stream_xref": show.stream_xref,
                            "start": start,
                            "end": end,
                            "kern": kern,
                            "payload": payload.decode("ascii"),
                            "decoded_after": decoded_a,
                            "text_ok": text_ok,
                            "state_errors": state_errors,
                            "output_sha256": out_sha,
                        },
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    ),
                    encoding="utf-8",
                )
                record["changed_objects"] = [{"stream_xref": show.stream_xref, "start": start, "end_old": end}]

                # neighbors
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
                    json.dumps({"neighbor_diff_count": len(neighbor_diffs), "sample": neighbor_diffs[:10]}, indent=2),
                    encoding="utf-8",
                )

                # render crop + outside halo
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
                # outside halo zoom2
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
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

                # status ladder
                if structure_ok and not neighbor_diffs:
                    record["status"] = "structure_pass"
                    for h in hyp:
                        if h["id"].startswith("H3"):
                            h["result"] = "supported_structure"
                    if changed > 0 and outside == 0:
                        record["status"] = "render_pass"
                        # save/reopen already proven via reopen decode
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

            # Verify original source untouched
            assert sha256(SRC) == SOURCE_SHA

            (case_dir / "suggested_product_layer_changes.md").write_text(
                f"""# Suggested product-layer changes (case {case_id} / {signature})

- Keep fail-closed; do not disable `{signature}` globally.
- Use this show fingerprint + live probe detail as a regression fixture.
- Case 1: split true malformed MC from valid q/Q-crossing OC before widening admission.
- Case 7: stabilize scratch fingerprint spelling (live vs tobytes) before trusting prepare.
- Case 10: admit intentional reflected TRM only with explicit tests (preserve negative det).
- Experiment splice success is NOT product acceptance while prepare still rejects.
""",
                encoding="utf-8",
            )
            (case_dir / "suggested_regression_tests.md").write_text(
                f"""# Regression tests (case {case_id})

1. Pin HVAC sha256 `{SOURCE_SHA}`, page_index={page_index}, seq={seq}.
2. Assert prepare reason == `{signature}` until an intentional gate change.
3. After any gate change: same font_resource/Tm/CTM/hscale/origin; neighbors unmoved;
   outside-halo pixels 0 at zoom=2; reopen decode equals replacement; no scale-to-bbox.
4. Negative: font-swap / insert_text rebuild must still fail fidelity asserts.
""",
                encoding="utf-8",
            )
            (case_dir / "unproven_limits.md").write_text(
                """# Unproven limits
- UI preview / Apply / Undo / Redo not run.
- No accepted_for_code: product engine still rejects; UI unverified.
- Multi-item TJ, Form XObject, signed PDFs, missing-glyph embedding not covered.
""",
                encoding="utf-8",
            )
            (case_dir / "failed_methods.json").write_text(
                json.dumps(failed, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )

            record["hypothesis"] = hyp
            record["failed_alternatives"] = failed
            # Never grant accepted_for_code here
            assert record["status"] != "accepted_for_code"
            (case_dir / "case_record.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
            cases_out.append(record)
            print(f"CASE {case_id}: status={record['status']} probe={probe}", flush=True)

    (EV / "cases.json").write_text(json.dumps(cases_out, ensure_ascii=False, indent=2), encoding="utf-8")

    # README for handoff (prepare only; do not hand off)
    (EV / "README_CLAUDE_CODE_HANDOFF.md").write_text(
        f"""# Claude Code handoff package (NOT handed off — local prep only)

Package: `{EV}`
Timezone stamp: 20260924_1431 Asia/Taipei (UTC+8)

## Chosen pilots
- case_id 1 → mc_malformed_pairing (HVAC page_index=4 seq=11)
- case_id 7 → verification_failed (HVAC page_index=5 seq=60)
- case_id 10 → trm_reflected (HVAC page_index=6 seq=5)

Case IDs are the explicit `case` integers from `output/pdf/manual-font-study/results.json`
and `scripts/experiment_hvac_font_edits.py` (enumerate CASES from 1).

## Verified hashes
- HVAC: `{SOURCE_SHA}`
- ECC (verified, not piloted edits): `0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853`

## Constraints honored
- No product source modifications
- Original PDFs untouched; candidates only under this folder
- Vector/outline PDFs classified out of true-text scope
- No cloud upload of PDF binaries
- accepted_for_code not claimed (engine still rejects; UI unverified)

## Next
See each case-*/suggested_product_layer_changes.md and cases.json statuses.
""",
        encoding="utf-8",
    )
    print("DONE", EV / "cases.json")


if __name__ == "__main__":
    main()
