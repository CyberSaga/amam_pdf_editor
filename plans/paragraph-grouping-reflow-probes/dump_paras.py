from __future__ import annotations

import io
import sys

sys.path.insert(0, sys.argv[2])
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import fitz  # noqa: E402

from model.text_block import TextBlockManager  # noqa: E402

doc = fitz.open(sys.argv[1])
mgr = TextBlockManager()
mgr.rebuild_page(0, doc)
page = doc[0]
print("plain-lines sample:", [ln[:30] for ln in mgr._page_plain_lines.get(0, [])[:6]])
for p in mgr.get_paragraphs(0):
    bb = tuple(round(x, 1) for x in p.bbox)
    print(
        f"{p.paragraph_id} bbox={bb} lines={p.line_start}-{p.line_end} "
        f"font={p.font} size={p.size:.2f} nrun={len(p.run_ids)}\n    text={p.text[:90]!r}"
    )
