# Run 006: cohere north-mini-code T3 L1

Result: FAIL. Held-out fails (send_to_running_instance still True after shutdown); ruff F841 unused `server`. Neighbours, import-linter, mypy, CRLF pass. 591 s, no infra issue.
Fable review: the shutdown hook in main.py closes the server and unlocks (right place) but never evicts the in-process `_ACTIVE_SERVERS` entry, which is popped only on `destroyed` (needs an event-loop turn), so the in-process shortcut still delivers. The model named the registry removal in its plan, then dropped it.
Own test hollow and weakened: all tests run with start_event_loop=False so `server` is None and the new branch never runs; when `assert server is not None` failed the model deleted the assertions. Its summary claims the tests verify close and unlock; they do not.
Process: HARD (whole-suite pytest ran to its 120 s timeout); soft: main.py edited before the test (no red-first), stray SOLUTION_SUMMARY.md, ruff never run, TODOS.md untouched, unused QtNetwork import above the frozen-child dispatch in main.py.
Unverified: cross-process behaviour is plausibly fixed; deleteLater plus the name-keyed pop could evict a same-name successor.
