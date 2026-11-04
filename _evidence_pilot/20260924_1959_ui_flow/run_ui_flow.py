# -*- coding: utf-8 -*-
"""Product UI-path Preview/Apply/Undo/Redo evidence harness.
Evidence-folder only. No product source edits.
Patterned on test_scripts/test_text_commit_consent_flow.py (same controller path).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import fitz
from PySide6.QtWidgets import QApplication

from controller.pdf_controller import PDFController
from model.edit_commands import EditTextResult
from model.edit_requests import EditTextRequest
from model.pdf_model import PDFModel
from model.text_commit.dto import TextCommitSettings
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.plan import PlanRejection
from model.text_commit.replay import replay_page_streams
from view.pdf_view import PDFView

EV = Path(__file__).resolve().parent
HVAC_SRC = EV / "candidates" / "HVAC-source-copy.pdf"
ECC_SRC = EV / "candidates" / "ecc-dwg-source-copy.pdf"
HVAC_SHA = "9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2"
ECC_SHA = "0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853"

# Explicit prior case_ids only (do not invent).
CASES = [
    {
        "case_id": "1",
        "pdf": "HVAC",
        "page_index": 4,
        "seq": 11,
        "probe_text": "空調冰水管線系統圖(1)",
        "replacement_text": "空調冰水管線系統圖(4)",
        "expected_signature": "mc_malformed_pairing",
        "lineage_ref": "_evidence_pilot/20260924_1431/case-1",
        "has_explicit_case_id": True,
    },
    {
        "case_id": "7",
        "pdf": "HVAC",
        "page_index": 5,
        "seq": 60,
        "probe_text": "2026.05.15",
        "replacement_text": "2026.05.16",
        "expected_signature": "verification_failed",
        "lineage_ref": "_evidence_pilot/20260924_1431/case-7",
        "has_explicit_case_id": True,
    },
    {
        "case_id": "10",
        "pdf": "HVAC",
        "page_index": 6,
        "seq": 5,
        "probe_text": "Buffer Tank",
        "replacement_text": "Tank Buffer",
        "expected_signature": "trm_reflected",
        "lineage_ref": "_evidence_pilot/20260924_1431/case-10",
        "has_explicit_case_id": True,
        "ui_targeting_note": "UI index splits show into Buffer+Tank spans; may diverge from direct prepare",
    },
    {
        "case_id": "ecc-1",
        "pdf": "ECC",
        "page_index": 0,
        "seq": 31,
        "probe_text": "專案名稱",
        "replacement_text": "專案圖名",
        "expected_signature": "mc_malformed_pairing",
        "lineage_ref": "_evidence_pilot/20260924_1612/case-ecc-1",
        "has_explicit_case_id": True,
        "font_name": "DFKaiShu-SB-Estd-BF",
    },
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def silence_message_boxes() -> None:
    import view.message_boxes as mb

    mb.show_error = lambda *a, **k: None
    mb.show_info = lambda *a, **k: None
    mb.show_warning = lambda *a, **k: None


def launch(pdf_path: Path, settings: TextCommitSettings):
    model = PDFModel(text_commit_settings=settings)
    view = PDFView(defer_heavy_panels=True)
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    controller.open_pdf(str(pdf_path))
    controller.show_page = lambda _page: None
    controller._update_undo_redo_tooltips = lambda: None
    if hasattr(controller, "_invalidate_active_render_state"):
        controller._invalidate_active_render_state = lambda *a, **k: None
    view.capture_viewport_anchor = lambda: None
    silence_message_boxes()
    return model, view, controller


def teardown(model, view, app):
    try:
        coord = getattr(controller_safe(model), "_text_commit_preview_coordinator", None)
    except Exception:
        coord = None
    # end preview sessions if any — handled per-case
    model.close()
    view.close()
    app.processEvents()


def controller_safe(model):
    return None


def find_run(model: PDFModel, page_idx: int, probe: str):
    """Prefer exact run text match; fallback contains; special-case Buffer Tank."""
    model.ensure_page_index_built(page_idx + 1)
    runs = list(model.block_manager.get_runs(page_idx))
    exact = [r for r in runs if (r.text or "") == probe]
    if exact:
        return exact[0], "exact_run"
    if probe == "Buffer Tank":
        # Prefer the line whose Buffer+Tank union matches prior show seq=5 origin.
        page = model.doc[page_idx]
        result = replay_page_streams(
            [(x, model.doc.xref_stream(x)) for x in page.get_contents()]
        )
        show = result.shows[5]
        origin = fitz.Point(show.origin_user) * page.transformation_matrix
        buffers = [r for r in runs if (r.text or "") == "Buffer"]
        best = None
        best_d = 1e9
        for b in buffers:
            para = model.block_manager.find_paragraph_for_run(page_idx, b.span_id)
            if para is None or getattr(para, "text", None) != "Buffer Tank":
                continue
            d = abs(fitz.Point(b.origin) - origin)
            if d < best_d:
                best_d = d
                best = b
        if best is not None:
            return best, f"buffer_span_near_show5_dist={best_d:.6f}"
    contains = [r for r in runs if probe in (r.text or "")]
    if contains:
        return contains[0], "contains_run"
    return None, "not_found"


def direct_prepare_probe(doc_path: Path, page_index: int, seq: int, original: str, replacement: str):
    doc = fitz.open(str(doc_path))
    try:
        page = doc[page_index]
        result = replay_page_streams(
            [(x, doc.xref_stream(x)) for x in page.get_contents()]
        )
        show = result.shows[seq]
        origin = fitz.Point(show.origin_user) * page.transformation_matrix
        matches = []
        for trace in page.get_texttrace():
            full = "".join(chr(c[0]) for c in trace["chars"])
            start = full.find(original)
            while start >= 0:
                chars = trace["chars"][start : start + len(original)]
                rect = fitz.Rect(chars[0][3])
                for ch in chars[1:]:
                    rect |= fitz.Rect(ch[3])
                matches.append((abs(fitz.Point(chars[0][2]) - origin), chars[0][2], rect))
                start = full.find(original, start + 1)
        if not matches:
            return {"prepared": False, "reason": "trace_not_found", "detail": original}
        matches.sort()
        visual_origin = fitz.Point(matches[0][1]) * page.rotation_matrix
        visual_bbox = matches[0][2] * page.rotation_matrix
        engine = TieredCommitEngine(doc, max_tier=1)
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
    finally:
        doc.close()


def wait_preview(app, holder: dict, timeout_s: float = 8.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if holder.get("done"):
            return True
        time.sleep(0.05)
    return bool(holder.get("done"))


def render_clip(page, bbox, zoom=1.5):
    """Best-effort crop for evidence screenshots (supporting only)."""
    from PIL import Image
    import io
    # Render a modest region around bbox in the page's current display space.
    base = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = Image.frombytes("RGB", (base.width, base.height), base.samples)
    rect = fitz.Rect(bbox)
    # Map bbox through page rotation display matrix approximately via page.rect scale.
    # Fallback: full-page thumbnail if crop math fails.
    try:
        pr = page.rect
        sx = base.width / pr.width if pr.width else 1.0
        sy = base.height / pr.height if pr.height else 1.0
        x0 = int(max(0, (rect.x0 - 8) * sx))
        y0 = int(max(0, (rect.y0 - 8) * sy))
        x1 = int(min(base.width, (rect.x1 + 8) * sx))
        y1 = int(min(base.height, (rect.y1 + 8) * sy))
        if x1 - x0 >= 2 and y1 - y0 >= 2:
            img = img.crop((x0, y0, x1, y1))
    except Exception:
        pass
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    # Return a tiny shim with .save(path)
    class _Png:
        def __init__(self, data: bytes):
            self._data = data
        def save(self, path: str):
            Path(path).write_bytes(self._data)
    return _Png(buf.getvalue())



def run_case(app, case: dict) -> dict:
    src = HVAC_SRC if case["pdf"] == "HVAC" else ECC_SRC
    case_dir = EV / f"case-{case['case_id']}"
    case_dir.mkdir(exist_ok=True)
    work = case_dir / "work_copy.pdf"
    shutil.copy2(src, work)

    settings = TextCommitSettings(
        engine="tiered", max_tier=1, strict=True, preview="plan"
    )
    model, view, controller = launch(work, settings)

    record = {
        "case_id": case["case_id"],
        "has_explicit_case_id": case["has_explicit_case_id"],
        "lineage_ref": case["lineage_ref"],
        "pdf": case["pdf"],
        "page_index": case["page_index"],
        "seq": case["seq"],
        "probe_text": case["probe_text"],
        "replacement_text": case["replacement_text"],
        "expected_signature": case["expected_signature"],
        "settings": {
            "engine": "tiered",
            "max_tier": 1,
            "strict": True,
            "preview": "plan",
        },
        "drive_method": "offscreen_PDFView_sig_edit_text_and_plan_preview",
        "ui_preview": {"status": "attempted"},
        "ui_apply": {"status": "attempted"},
        "ui_undo": {"status": "skipped", "notes": "pending apply"},
        "ui_redo": {"status": "skipped", "notes": "pending apply"},
        "save_reopen": {"status": "skipped"},
        "screenshots": [],
        "direct_prepare_context": None,
        "status": "incomplete",
        "accepted_for_code": False,
    }

    page_idx = case["page_index"]
    run, how = find_run(model, page_idx, case["probe_text"])
    record["ui_target"] = {
        "resolution": how,
        "span_id": None if run is None else run.span_id,
        "run_text": None if run is None else run.text,
        "bbox": None if run is None else list(run.bbox),
        "font": None if run is None else run.font,
    }

    # Context-only direct prepare (not counted as UI success)
    record["direct_prepare_context"] = direct_prepare_probe(
        src, page_idx, case["seq"], case["probe_text"], case["replacement_text"]
    )

    if run is None:
        record["ui_preview"] = {
            "status": "blocked",
            "notes": "no EditableSpan/run matched probe_text in product block index",
        }
        record["ui_apply"] = {
            "status": "blocked",
            "notes": "no run target; cannot emit EditTextRequest",
        }
        record["ui_undo"]["notes"] = "apply_not_attempted"
        record["ui_redo"]["notes"] = "apply_not_attempted"
        record["status"] = "ui_blocked"
        model.close()
        view.close()
        app.processEvents()
        (case_dir / "case_record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return record

    # --- screenshot before ---
    page = model.doc[page_idx]
    before_path = case_dir / "render-before.png"
    try:
        before_pix = render_clip(page, run.bbox)
        before_pix.save(str(before_path))
        record["screenshots"].append(str(before_path.relative_to(EV)))
    except Exception as exc:
        record["screenshots"].append({"path": str(before_path.relative_to(EV)), "error": type(exc).__name__})

    # --- PREVIEW ---
    preview_holder = {"done": False, "payload": None}

    def _capture_preview(**kwargs):
        image = kwargs.get("image")
        has_image = image is not None and (
            not image.isNull() if hasattr(image, "isNull") else True
        )
        preview_png = None
        if has_image:
            preview_png = case_dir / "preview-plan.png"
            try:
                image.save(str(preview_png), "PNG")
                record["screenshots"].append(str(preview_png.relative_to(EV)))
            except Exception as exc:
                preview_png = f"save_failed:{type(exc).__name__}"
        preview_holder["done"] = True
        preview_holder["payload"] = {
            "session_key": kwargs.get("session_key"),
            "generation": kwargs.get("generation"),
            "has_image": has_image,
            "plan_token": kwargs.get("plan_token"),
            "reject_reason": kwargs.get("reject_reason"),
            "preview_png": str(preview_png) if preview_png is not None else None,
        }

    view.apply_text_edit_plan_preview = _capture_preview

    # For Buffer Tank, preview original_text should match what UI would show.
    preview_original = run.text
    preview_replacement = case["replacement_text"]
    if case["case_id"] == "10" and run.text == "Buffer":
        # Keep replacement same length as targeted span for preview attempt
        preview_replacement = "TankBf"
        record["ui_preview"]["notes_pre"] = (
            "targeted Buffer span (show is Buffer Tank); replacement shortened to TankBf"
        )

    payload = {
        "session_key": f"ui-ev-{case['case_id']}",
        "page_idx": page_idx,
        "generation": 1,
        "replacement_text": preview_replacement,
        "clip_rect": list(run.bbox),
        "render_scale": 2.0,
        "rect": list(run.bbox),
        "original_text": preview_original,
        "target_span_id": run.span_id,
        "target_mode": "run",
        "new_rect": None,
        "style_overrides": None,
    }
    try:
        controller.on_text_edit_plan_preview_request(payload)
        got = wait_preview(app, preview_holder, timeout_s=12.0)
        # also drain coordinator
        coord = getattr(controller, "_text_commit_preview_coordinator", None)
        if coord is not None and hasattr(coord, "has_active_job"):
            deadline = time.time() + 12.0
            while time.time() < deadline and coord.has_active_job:
                app.processEvents()
                time.sleep(0.05)
            wait_preview(app, preview_holder, timeout_s=2.0)
        if not got and not preview_holder.get("done"):
            # target_unresolved notifies synchronously without worker
            record["ui_preview"] = {
                "status": "fail",
                "notes": "no apply_text_edit_plan_preview callback within timeout",
                "payload_sent_keys": list(payload.keys()),
            }
        else:
            p = preview_holder.get("payload") or {}
            reject = p.get("reject_reason")
            has_img = bool(p.get("has_image"))
            token = p.get("plan_token")
            if has_img and token and not reject:
                status = "pass"
            elif reject:
                status = "blocked"
            else:
                status = "fail"
            record["ui_preview"] = {
                "status": status,
                "reject_reason": reject,
                "plan_token_present": bool(token),
                "has_image": has_img,
                "callback": p,
                "notes": "product on_text_edit_plan_preview_request path",
            }
    except Exception as exc:
        record["ui_preview"] = {
            "status": "fail",
            "notes": f"preview exception: {type(exc).__name__}: {exc}",
        }

    # End preview session before apply
    try:
        controller._end_text_edit_plan_preview_session()
        coord = getattr(controller, "_text_commit_preview_coordinator", None)
        if coord is not None and hasattr(coord, "wait_for_done"):
            coord.wait_for_done(2000)
    except Exception:
        pass
    app.processEvents()

    # --- APPLY ---
    apply_original = run.text
    apply_replacement = case["replacement_text"]
    if case["case_id"] == "10" and run.text == "Buffer":
        apply_replacement = "TankBf"
        record["ui_apply"]["targeting_adjustment"] = (
            "span split: editing Buffer->TankBf on product run index; "
            "direct_prepare_context still uses full Buffer Tank / Tank Buffer"
        )

    fp_before = None
    try:
        from model.text_commit.inspect import page_fingerprint

        fp_before = page_fingerprint(model.doc, model.doc[page_idx])
    except Exception as exc:
        fp_before = f"unavailable:{type(exc).__name__}"

    edit_count_before = model.edit_count
    can_undo_before = model.command_manager.can_undo()

    req = EditTextRequest(
        page=page_idx + 1,
        rect=fitz.Rect(run.bbox),
        new_text=apply_replacement,
        font=run.font or "helv",
        size=float(run.size or 12.0),
        color=(0.0, 0.0, 0.0),
        original_text=apply_original,
        target_span_id=run.span_id,
        target_mode="run",
    )
    view.sig_edit_text.emit(req)
    app.processEvents()

    result = controller._last_edit_result
    outcome = model.last_commit_outcome
    degraded = getattr(outcome, "degraded_reason", None) if outcome else None
    chain = list(getattr(outcome, "fallback_chain", ()) or ()) if outcome else []
    status_name = str(getattr(outcome, "status", None)) if outcome else None

    fp_after = None
    try:
        from model.text_commit.inspect import page_fingerprint

        fp_after = page_fingerprint(model.doc, model.doc[page_idx])
    except Exception as exc:
        fp_after = f"unavailable:{type(exc).__name__}"

    mutated = fp_before != fp_after
    apply_ok = result is EditTextResult.SUCCESS and mutated

    if apply_ok:
        record["ui_apply"] = {
            "status": "pass",
            "edit_text_result": str(result),
            "outcome_status": status_name,
            "degraded_reason": degraded,
            "fallback_chain": chain,
            "mutated": True,
        }
    elif result in (
        EditTextResult.REJECTED_STRICT,
        EditTextResult.REJECTED_UNSUPPORTED,
        EditTextResult.FALLBACK_DECLINED,
    ):
        record["ui_apply"] = {
            "status": "blocked",
            "edit_text_result": str(result),
            "outcome_status": status_name,
            "engine_reason": degraded,
            "fallback_chain": chain,
            "mutated": mutated,
            "edit_count_delta": model.edit_count - edit_count_before,
            "notes": "strict true-text Apply refused; zero or non-success commit",
        }
    elif result is EditTextResult.TARGET_BLOCK_NOT_FOUND:
        record["ui_apply"] = {
            "status": "fail",
            "edit_text_result": str(result),
            "notes": "UI resolve could not find target block/span",
        }
    else:
        record["ui_apply"] = {
            "status": "fail",
            "edit_text_result": str(result) if result is not None else None,
            "outcome_status": status_name,
            "engine_reason": degraded,
            "fallback_chain": chain,
            "mutated": mutated,
        }

    # --- UNDO / REDO ---
    if apply_ok and model.command_manager.can_undo():
        controller.undo()
        app.processEvents()
        undone = not model.command_manager.can_undo() or model.command_manager.can_redo()
        record["ui_undo"] = {
            "status": "pass" if model.command_manager.can_redo() else "fail",
            "can_redo_after": model.command_manager.can_redo(),
            "can_undo_after": model.command_manager.can_undo(),
        }
        if model.command_manager.can_redo():
            controller.redo()
            app.processEvents()
            record["ui_redo"] = {
                "status": "pass" if model.command_manager.can_undo() else "fail",
                "can_undo_after": model.command_manager.can_undo(),
                "can_redo_after": model.command_manager.can_redo(),
            }
        else:
            record["ui_redo"] = {"status": "blocked", "notes": "undo did not arm redo"}
        # save/reopen only if apply still in effect after redo
        if model.command_manager.can_undo():
            out_pdf = case_dir / "after_ui_apply.pdf"
            model.doc.save(str(out_pdf), incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            # reopen check
            re = fitz.open(str(out_pdf))
            try:
                re_page = re[page_idx]
                record["save_reopen"] = {
                    "status": "attempted",
                    "pages": re.page_count,
                    "notes": "saved after UI apply+undo+redo; true-text decode not re-asserted beyond open",
                }
            finally:
                re.close()
    else:
        record["ui_undo"] = {
            "status": "skipped",
            "notes": "apply_did_not_commit",
            "can_undo": model.command_manager.can_undo(),
            "can_undo_before": can_undo_before,
        }
        record["ui_redo"] = {
            "status": "skipped",
            "notes": "apply_did_not_commit",
            "can_redo": model.command_manager.can_redo(),
        }
        record["save_reopen"] = {
            "status": "skipped",
            "notes": "no successful UI apply to persist",
        }

    # after render (document unchanged if blocked)
    after_path = case_dir / "render-after.png"
    try:
        after_pix = render_clip(model.doc[page_idx], run.bbox)
        after_pix.save(str(after_path))
        record["screenshots"].append(str(after_path.relative_to(EV)))
    except Exception as exc:
        record["screenshots"].append({"path": str(after_path.relative_to(EV)), "error": type(exc).__name__})

    # overall status
    statuses = [
        record["ui_preview"]["status"],
        record["ui_apply"]["status"],
        record["ui_undo"]["status"],
        record["ui_redo"]["status"],
    ]
    if all(s == "pass" for s in statuses):
        record["status"] = "ui_pass"
    elif record["ui_apply"]["status"] == "blocked":
        record["status"] = "ui_blocked"
    elif "fail" in statuses:
        record["status"] = "ui_fail"
    else:
        record["status"] = "ui_partial"

    record["accepted_for_code"] = False
    record["structure_notes"] = {
        "ui_target_resolution": how,
        "page_rotation": model.doc[page_idx].rotation,
        "fingerprint_before": fp_before if isinstance(fp_before, str) else str(fp_before),
        "fingerprint_after": fp_after if isinstance(fp_after, str) else str(fp_after),
        "mutated": mutated,
        "note": "screenshots are supporting evidence; structured apply/preview fields are authoritative",
    }

    # cleanup coordinator
    try:
        controller._end_text_edit_plan_preview_session()
        coord = getattr(controller, "_text_commit_preview_coordinator", None)
        if coord is not None and hasattr(coord, "wait_for_done"):
            coord.wait_for_done(2000)
    except Exception:
        pass

    model.close()
    view.close()
    app.processEvents()

    (case_dir / "case_record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (case_dir / "notes.md").write_text(
        "\n".join(
            [
                f"# case-{case['case_id']} UI flow notes",
                "",
                f"- expected_signature: `{case['expected_signature']}`",
                f"- ui_preview: `{record['ui_preview'].get('status')}` reason=`{record['ui_preview'].get('reject_reason')}`",
                f"- ui_apply: `{record['ui_apply'].get('status')}` engine_reason=`{record['ui_apply'].get('engine_reason')}` result=`{record['ui_apply'].get('edit_text_result')}`",
                f"- ui_undo/redo: `{record['ui_undo'].get('status')}` / `{record['ui_redo'].get('status')}`",
                f"- direct_prepare_context: `{record['direct_prepare_context']}`",
                f"- overall: `{record['status']}` accepted_for_code={record['accepted_for_code']}",
                "",
                "Drive path: offscreen PDFView/PDFController (same as GUI signals).",
            ]
        ),
        encoding="utf-8",
    )
    return record


def main():
    assert sha256(HVAC_SRC) == HVAC_SHA, sha256(HVAC_SRC)
    assert sha256(ECC_SRC) == ECC_SHA, sha256(ECC_SRC)

    app = QApplication.instance() or QApplication([])
    results = []
    for case in CASES:
        print("RUNNING", case["case_id"], flush=True)
        rec = run_case(app, case)
        results.append(rec)
        print(
            " ",
            rec["status"],
            "preview=",
            rec["ui_preview"].get("status"),
            "apply=",
            rec["ui_apply"].get("status"),
            "reason=",
            rec["ui_apply"].get("engine_reason"),
            flush=True,
        )

    (EV / "cases.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = {
        "stamp": "20260924_1959_ui_flow",
        "timezone_label": "Asia/Taipei (UTC+8)",
        "mode": "product_ui_preview_apply_undo_redo",
        "drive_method": "offscreen_harness_same_as_test_text_commit_consent_flow",
        "interactive_gui": False,
        "product_source_changes": 0,
        "case_ids_invented": 0,
        "hashes_verified": {"HVAC": HVAC_SHA, "ECC": ECC_SHA},
        "settings": {
            "engine": "tiered",
            "max_tier": 1,
            "strict": True,
            "preview": "plan",
            "why": "expose true-text prepare/preview; prevent legacy fallback counting as ui_pass",
        },
        "cases": [
            {
                "case_id": r["case_id"],
                "status": r["status"],
                "ui_preview": r["ui_preview"].get("status"),
                "ui_preview_reject": r["ui_preview"].get("reject_reason"),
                "ui_apply": r["ui_apply"].get("status"),
                "ui_apply_engine_reason": r["ui_apply"].get("engine_reason"),
                "ui_undo": r["ui_undo"].get("status"),
                "ui_redo": r["ui_redo"].get("status"),
                "expected_signature": r["expected_signature"],
                "direct_prepare_context": r["direct_prepare_context"],
                "accepted_for_code": False,
            }
            for r in results
        ],
        "ui_pass_count": sum(1 for r in results if r["status"] == "ui_pass"),
        "ui_blocked_count": sum(1 for r in results if r["status"] == "ui_blocked"),
        "accepted_for_code_count": 0,
        "accepted_for_code": False,
        "evidence_path_user": str(EV),
        "evidence_path_workspace_mirror": "/workspace/pdf_editor_evidence/20260924_1959_ui_flow",
        "blockers_for_remaining": [
            "Engine still rejects selected pilots; Apply cannot reach undo/redo on true-text path under strict=True",
            "Case 10 UI span split (Buffer|Tank) diverges from show-level Buffer Tank used in engine pilots",
            "Default product preview=legacy / max_tier=0 not exercised here (this run opts into plan+tier1+strict)",
            "Interactive GUI computerUse not used; offscreen harness covers same controller signals",
        ],
    }
    (EV / "PARENT_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    readme = """# UI flow evidence — 20260924_1959

Product UI-path Preview / Apply / Undo / Redo for prior true-text pilots.

- Drive: offscreen harness = same `PDFView`/`PDFController` signals as GUI (`sig_edit_text`, plan preview).
- Settings: tiered / max_tier=1 / strict / preview=plan.
- No product source edits. Isolated copies only. No `ui_pass` claimed if Apply blocked.
- See `UI_ENTRY.md`, `METHODS_AND_EVIDENCE_PLAN.md`, `cases.json`, `PARENT_SUMMARY.json`.
"""
    (EV / "README.md").write_text(readme, encoding="utf-8")
    print("DONE", summary["ui_blocked_count"], "blocked,", summary["ui_pass_count"], "ui_pass")


if __name__ == "__main__":
    main()
