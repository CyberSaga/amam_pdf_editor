# UI entry discovery — 20260924_1959

## How to launch the product GUI
- Entry: `main.py` / `run.bat` (`python .\main.py [files...]`)
- Toolkit: **PySide6** (`QApplication` + `view.pdf_view.PDFView` + `controller.pdf_controller.PDFController`)
- Composition root: `main.run()` constructs `PDFView`, applies theme, then wires controller on open

## APIs the UI uses for true-text edit
| Concern | Path |
|---|---|
| Apply | View `sig_edit_text` → `PDFController.edit_text` → `EditTextCommand` → `model.edit_text` / `TieredCommitEngine` |
| Plan preview | View `sig_text_edit_plan_preview` → `PDFController.on_text_edit_plan_preview_request` → `open_preview_session` + `TextCommitPreviewCoordinator` (QThread) → `view.apply_text_edit_plan_preview` |
| Undo / Redo | View `sig_undo` / `sig_redo` → `PDFController.undo` / `redo` → `model.command_manager` |
| Settings | `TextCommitSettings` / env `TEXT_COMMIT_ENGINE`, `TEXT_COMMIT_MAX_TIER`, `TEXT_COMMIT_STRICT`, `TEXT_COMMIT_PREVIEW` |

Defaults (product): `engine=tiered`, `max_tier=0`, `strict=False`, `preview=legacy`.
This evidence run intentionally uses `max_tier=1`, `strict=True`, `preview=plan` so true-text prepare/preview gates are visible and legacy fallback cannot be counted as true-text Apply success.

## Headless / automated UI harness
- Exists: `test_scripts/test_text_commit_consent_flow.py` (and related `test_text_commit_preview_*.py`)
- Pattern: `QT_QPA_PLATFORM=offscreen` + real `PDFModel`/`PDFView`/`PDFController` + emit production signals
- This package's `run_ui_flow.py` follows that same pattern on isolated HVAC/ECC copies
- Interactive GUI + computerUse was **not** required; offscreen harness drives the same controller code path

## Launch notes for interactive GUI (not used this round)
```
run.bat
# or
.\.venv\Scripts\python.exe main.py "path\to\isolated.pdf"
```
