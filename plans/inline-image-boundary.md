# Plan: a proved inline-image boundary for every content-stream lexer

<!-- Status: OPENED 2026-11-17 by the owner ("find how to get both"). Investigation only; nothing designed or implemented. -->

## Current state / next step (≤40 lines)

- **Problem.** `_scan_inline_image_payload` (`model/text_commit/pdf_lexer.py:106`) ends an inline image at the first `EI` that has whitespace before it and whitespace or a delimiter after it. Binary payload can contain those bytes. A wrong boundary makes the lexer read image data as operators, or operators as image data.
- **Why "both".** Two needs pull apart. Safety wants a boundary that is proved or a refusal. Coverage wants pages with an inline image to stay editable: the text-commit engine today, and CAD vector editing, which stops indexing at the first `BI` (`plans/cad-vector-object-editing.md`, D14, O9).
- **Who reads the token today** (grep 2026-11-17, not audited further):
  - Refuse on it: `model/text_paint_state.py:674` and `:1151`, `model/tools/watermark_rendering.py:303`, `model/text_commit/verify.py:77`.
  - Trusts the boundary: `model/text_commit/replay.py:605` clears the operand stack and continues lexing after the payload.
  - So the exposure to measure first is replay: what does a false `EI` let through, and does a later gate (verify) always catch it?
- **Candidate proof ladder** (each step is exact or refuses; none guesses):
  1. `/L` (or `/Length`) in the image dictionary (PDF 2.0): the payload length is stated.
  2. No filter: length = height × ceil(width × components × bits / 8), from `/W /H /BPC /CS` or `/IM`. Needs the colour space resolved; a named colour space from `/Resources` refuses.
  3. `/Fl` only: the zlib stream ends where `zlib.decompressobj` reports `eof`; `unused_data` gives the boundary.
  4. `/DCT`: scan JPEG markers to EOI. `/A85`, `/AHx`: their own end markers (`~>`, `>`).
  5. Anything else (`/LZW`, `/CCF`, `/RL`, filter chains): refuse.
  After a proved end, require optional whitespace, then `EI`, then a delimiter; a mismatch refuses.
- **Cross-check.** MuPDF parses the same stream. A probe can compare our boundary with what MuPDF accepted (for example the operator count after the image through `get_cdrawings` / `get_texttrace`), as an oracle in tests, not as the product mechanism.
- **Open questions.**
  1. How many real pages carry `BI`? CAD plan probe P9 counts it on `test_files/`; the text corpora need the same count.
  2. Which ladder steps cover those pages? If step 2 and 3 cover nearly all, the rest can stay refused.
  3. Is a refusal at replay acceptable for text commit (it would turn some edits that work today into refusals), or must the heuristic stay as a fallback behind verify?
  4. One shared function for both lexers (`pdf_lexer` and the vector scanner), so the class is fixed once.
- **Measured 2026-11-17 (log below):** 246 of 27,768 pages hold a `BI`; the ladder proves 89% of those pages and 11.5% of the images (`CCF` dominates); the current rule cuts 4 real ASCII85 images short.
- **Schedule (owner, 2026-11-17, CAD plan O9).** The proof function `inline_image_end` is built after CAD M1, as this plan's first step; until then the vector scanner stops at every inline image.
- **Next step.** Done: the count of `BI` pages and filter kinds. Remaining: build false-`EI` fixtures and run them through replay and verify to see what gets through today. Then design. Owner decides question 3.

## Running log

- **2026-11-17.** Opened from the CAD vector review (Codex finding F1; that plan's R9). No measurement yet.
- **2026-11-17. Probe (`plans/cad-vector-object-editing-probes/p11_inline_image_ladder.py`, whole `test_files/`: 4,451 files, 27,768 pages).** Answers open questions 1 and 2. It finds `BI` outside strings and comments, proves the end, and requires `EI` after it.
  - 246 pages hold a real `BI` (0.9%), 174,629 images. **By page, 218 of 246 (89%) are proved in full.**
  - Proved with `EI` in place: 20,054 images (11.5%): computed length 16,676, `Fl` 3,311, `A85` 37, `DCT` 26, `AHx` 4.
  - Not proved: 151,977 `CCF` (151,963 of them on two pages of two files, text drawn as fax bitmaps); 1,689 unfiltered with a named colour space (needs `/Resources`; two pages of one file); 887 `Fl` that zlib rejects (not looked into); 9 `LZW`; 8 with a stated or computed length and no `EI` there (`/L` stated twice, wrong both times); 1 `A85` with no `~>`; 1 unreadable dictionary.
  - So ladder step 5's refusal of `CCF` is what costs coverage by image count; by page it costs 9 pages.
  - The ladder changes in two ways: the **outermost** filter alone decides (the first `~>` ends A85+Fl and A85+LZW, no zlib step), and `RL` is provable by its EOD byte.
  - **`_scan_inline_image_payload` itself, run on those files, ends 4 ASCII85 payloads in 3 files too early** (a line break followed by `EI(` or `EI[` inside the data). So the boundary replay trusts is wrong on real files.
  - An earlier count by another model (174,795 images, 99.97% provable) has the right total but read the `CCF` images as unfiltered and checked no boundary; its percentage is not used.
  - Still open: questions 3 and 4, the false-`EI` fixtures through replay and verify, and whether step 2 may read the colour space from `/Resources` for the text engine (the vector scanner may not: that plan's D15).
