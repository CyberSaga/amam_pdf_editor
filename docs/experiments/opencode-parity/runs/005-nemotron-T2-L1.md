# Run 005: nemotron-3.5-super-vl T2 L1

Result: PASS. Held-out, neighbours, ruff, import-linter, mypy, CRLF all pass. 351 s, no infra issue.
Verified: reverting only the 3 source fixes turns 2 of 3 held-out tests red.
Process: clean. Red-first genuine (test edit, 3 failed, then source edits); added ~92 lines of tests to test_tab_detach.py; TODOS and PITFALLS updated. Soft: docs/ARCHITECTURE.md payload field list not updated.
Fable review: adoption rule `payload.watermarks is not None` handles the hidden-watermark case that cohere's `if watermarks or flag` misses; reference-quality cell.
Grader note: result.json first showed hard 'ruff format' because the model's report said it did not run it; matcher now scans shell commands only.
Cohere (run 004) for comparison: FAIL on mypy; also hidden-watermark resurrection bug, no tests landed, no docs.
