---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
---

# Systematic Debugging

Find the root cause before changing anything.

1. Read the whole error and stack trace; note file, line, and the exact message.
2. Reproduce it reliably. If it is intermittent, gather more data before theorising. For suspected test-order pollution, bisect by hand: run the failing test alone, then after halves of the tests that precede it (`.venv\Scripts\python.exe -m pytest <subset> <failing test>`), one run at a time.
3. Check what changed: `git log`/`git diff` on the touched area, dependency and config changes, environment differences (this repo: venv vs system PyMuPDF).
4. Trace the bad value back to where it originates; fix at the source, not where the symptom appears. In multi-layer paths (View → Controller → Model → PyMuPDF) log what enters and leaves each boundary once, then narrow.
5. State one hypothesis, make the smallest change that tests it, verify. If it fails, form a new hypothesis rather than stacking fixes.
6. Write the failing reproduction test first (CLAUDE.md red-light rule), then the fix; run the neighbouring tests.
7. After three failed fixes, stop and question the design with the user — repeated symptom fixes in different places mean the structure is wrong, not the patch.
