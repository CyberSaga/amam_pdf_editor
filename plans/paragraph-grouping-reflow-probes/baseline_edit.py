from __future__ import annotations

import io
import shutil
import sys

repo, src, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, repo)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import fitz  # noqa: E402

from model.pdf_model import PDFModel  # noqa: E402
from model.edit_requests import RebuildConsent  # noqa: E402

INSERT_AFTER = "文件範本"
ADD = "（包含測試點位範本）"


def run(tag: str, mode: str, allow_rebuild: bool) -> None:
    copy = f"{outdir}/base_{tag}.pdf"
    shutil.copyfile(src, copy)
    model = PDFModel()
    model.open_pdf(copy)
    model.ensure_page_index_built(1)
    mgr = model.block_manager
    para = next(p for p in mgr.get_paragraphs(0) if p.paragraph_id == "pg0_b18_p0")
    print(f"[{tag}] para text={para.text!r} runs={len(para.run_ids)}")
    if INSERT_AFTER not in para.text:
        print("  anchor text missing")
        return
    new_text = para.text.replace(INSERT_AFTER, INSERT_AFTER + ADD, 1)

    def consent(chain):
        loss = getattr(model, "pending_rebuild_glyph_loss", ())
        print(f"  consent asked chain={chain} glyph_loss={loss!r}")
        return RebuildConsent(acknowledged_glyph_loss=loss)

    kwargs = dict(
        font=para.font, size=float(para.size), color=tuple(para.color),
        original_text=para.text, target_mode=mode, allow_rebuild=allow_rebuild,
    )
    if mode == "run":
        kwargs["target_span_id"] = para.run_ids[0]
    if allow_rebuild:
        kwargs["confirm_fallback"] = consent
    try:
        res = model.edit_text(1, fitz.Rect(para.bbox), new_text, **kwargs)
        print(f"  result={res}")
    except Exception as exc:  # noqa: BLE001
        print(f"  raised {type(exc).__name__}: {exc}")
    oc = model.last_commit_outcome
    if oc is not None:
        print(f"  outcome status={oc.status} tier={oc.tier} chain={oc.fallback_chain} degraded={oc.degraded_reason}")
    page = model.doc[0]
    clip = fitz.Rect(40, 380, 560, 540)
    page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip).save(f"{outdir}/base_{tag}.png")
    fonts = sorted({s["font"] for b in page.get_text("dict", clip=clip)["blocks"] for ln in b.get("lines", []) for s in ln["spans"]})
    print(f"  fonts in band after: {fonts}")


run("para_strict", "paragraph", False)
run("para_rebuild", "paragraph", True)
doc = fitz.open(src)
doc[0].get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(40, 380, 560, 540)).save(f"{outdir}/base_orig.png")
