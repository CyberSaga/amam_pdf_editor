# Three CAD PDF editing experiments

## Scope
Pause the production integration plan. Edit separate copies of the three supplied
CAD fixtures, covering a font different from the HVAC experiment, and record
reproducible PyMuPDF operations and before/after evidence. No production changes.

## Findings and decisions
- [ECC_DWG] has embedded DFKaiShu-SB-Estd-BF (new) and MicrosoftJhengHeiRegular.
- CHB and Taoyuan have no fonts, text traces, images, or Form XObjects; visible
  lettering is ordinary vector paths. Treat these as vector glyph reuse, not CID
  text edits or identified font families. Reuse source geometry without guessing
  replacement system fonts.
- TypeSafe live State/Models docs were read. Jev is text-only and no API credential
  is configured; no remote inference is claimed. Numeric/font/geometry decisions
  stay deterministic as the skill instructs.

## Steps
- [x] Inventory and render all three originals.
- [x] Select and record exact glyph/text targets and donor evidence (12 cases).
- [x] Add verifier; demonstrate unchanged originals fail expected edits (all 3).
- [x] Produce edited copies with original CID or vector glyph geometry.
- [x] Reopen, check target changes and non-target pixel/resource identity.
- [x] Inspect comparisons and app rendering; document methods and limits.
- [x] Run lint and relevant checks; archive this experiment log.

## Dead ends
Using text insertion on the two outlined PDFs cannot preserve a source font:
there is no font resource or Unicode mapping to reuse.

Vector path reuse initially lost per-stroke lineJoin on Taoyuan S. The independent
geometry/style verifier caught it; parser now tracks j through q/Q and copies it
per donor path. Rounded coordinate strings falsely disagreed at 0.00019 pt of
MuPDF float32 drift; geometric comparison now uses 0.002 pt, while byte splices
and paint styles remain exact. [ECC_DWG_LONG] crowded the table boundary, so the final
length-changing case is ECC-3.

## Results
All 12 edits passed. MuPDF and Poppler at 216 dpi both report zero non-target
changed pixels on all 3 pages. Originals unchanged; source font resources and
non-target objects unchanged. The public Qt entry point loaded all 3 outputs;
QTest switched tabs and zoom, and high-quality page render screenshots were
visually inspected. Desktop helper could not activate its pre-existing window;
the project verify workflow provided app evidence instead.

`ruff check .`: clean. Lexer/CID regression suite: 105 passed in 15.86s.
Full product suite not run: this task changes only experiment code and docs.
Reproduction script: `scripts/experiment_cad_font_edits.py`.
Report: `docs/experiments/2026-09-21-three-cad-font-edits.md`.
