# Run 004: cohere/north-mini-code:free, T2 (detach carries watermarks), L1, H1, run 1 - FAIL

Date 2026-11-14, 166 s. Re-run of run 003 (which hit the free daily cap) on a fresh allowance.

Gates: held-out PASS, neighbours PASS, ruff PASS, import-linter PASS, CRLF PASS, mypy FAIL (1 error: `model/tools/watermark_tool.py:383` `len()` of `Any | None`). Outcome = fail on the mypy gate only.

Verification (revert only the 3 source files, keep held-out test): 2 of 3 held-out tests go red (`test_unsaved_added_watermark_survives_a_detach`, `test_a_clean_session_detach_keeps_its_saved_watermark_and_stays_clean`), so the fix is real and the held-out is not vacuous.

Process: no hard findings. Soft: no failing run/repro before the first source edit (red-first); it added no test of its own. Changed files: controller/session_transfer.py, model/pdf_model.py, model/tools/watermark_tool.py (+39 lines, all in scope).

Grading note: grade_task gates are the provisional grade; the Fable review of the diff itself is not done (needs /model fable).
