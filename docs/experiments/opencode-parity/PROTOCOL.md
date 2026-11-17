# Protocol (frozen 2026-11-11, before the second model runs)

## Tasks
Real fixes from commit 4e7776ae, start state its parent b214fa57. T1 XMP leak after a metadata edit (1 layer), T2 a detached tab carries the watermark list (3 layers), T3 a closing primary stops serving hand-offs (2 files). Excluded: print/export level change (its guard was green before the fix), U2 (test tied to a private method). Held-out tests use only names that existed at the parent (T3 needs only `main.run`, `try_become_server`, `app._pdf_owned_shutdown`).

## Brief ladder (same for every model and harness arm)
L1: the TODO item verbatim plus the instruction to follow the project rulebook. L2: L1 plus files, symbols, expected behaviour, acceptance commands. Report the lowest level that passes. An identical environment note precedes both (Linux, which python to use, one pytest at a time, no whole suite, no commit).

## Sandbox and privacy
Per run: `git archive` of the parent into a fresh directory (no history, no PDFs: the repo tracks none), copied to the WSL native filesystem. OpenCode runs `--standalone` inside a private mount namespace where `/mnt` is an empty tmpfs, so the owner's private test PDFs on the Windows drives are unreachable. Source code may go to free endpoints; test PDFs may not. The model tests with a Linux venv on the repo's CI pins; a Windows venv grades.

## Quota rules
One model per day (free tier request cap, 50/day assumed; the first cell used about 56 steps). A 429, DNS failure or timeout before any edit is an infrastructure failure: recorded separately, re-run the same cell, never counted against the model.

## Grading
Outcome (hard gates, all must pass): held-out tests (3 runs when repeating), neighbouring test files, `ruff check .`, import-linter, `mypy model/ utils/`, CRLF preserved.
Process, hard: a forbidden command, bare pytest, whole-suite pytest. Process, soft: no failing run before the first source edit, files outside the task, report claims that do not match tool output (manual), Done-rule items (TODOS, PITFALLS, tests added).
Provisional grades by a stronger model are recorded with the checks that confirmed or corrected them.

## Harness arms (design; only H1 has run)
- H0: sandbox with the rulebook and role files removed (measures the bare model).
- H1: sandbox as committed (AGENTS.md, CLAUDE.md, skills, hooks scripts present). Whether OpenCode loads AGENTS.md is itself under test (see HARNESS.md).
- H2: H1 plus hooks wired so a deliberate bare pytest or whole-suite run is really denied.
The gap H0 to H1 is the rulebook's value, H1 to H2 the hooks' value.
