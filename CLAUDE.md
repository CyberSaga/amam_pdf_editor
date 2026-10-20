# CLAUDE.md — PDF Editor

Desktop PDF editor: Python 3.10+, PySide6 ≥ 6.4, PyMuPDF `>=1.27,<1.28` (`fitz`; single-minor pin — the text-commit engine needs byte-identical content streams across dev/CI). MVC + ToolManager; entry `main.py`.

## Layer rules (the four import-linter contracts + the threading grep are CI-blocking; the rest is convention)

View →(signals)→ Controller → Model → ToolManager

- View never calls Model; Controller is the only View↔Model coordinator; Model never imports Qt.
- ToolManager: annotation/watermark/search/OCR extensions only. `main.py` is the only place all layers meet.
- Background work: QThread + Signals only. A `threading.Thread` grep over `view/` and `controller/` blocks CI.
- Never design across these boundaries. `view-no-model` has a small DTO `ignore_imports` allowlist in pyproject.toml.
- `utils/` may import QtCore/QtNetwork but not QtWidgets (convention, not linted; `utils/helpers.py`'s QMessageBox is a tracked violation).

## Conventions the linters cannot catch (ruff selects only E4/E7/E9/F)

- `snake_case` functions, `PascalCase` classes; every module starts with `from __future__ import annotations` and uses `list`/`dict`/`X | None`, not `typing.List`/`Optional`. Every package dir has `__init__.py`.
- Font sizes stay `float` (PyMuPDF returns floats; `int` truncates).
- `logging.getLogger(__name__)` per module; `logging.basicConfig` only in `main.py`.
- Call `model.ensure_page_index_built(page_num)` before any text edit/search; structural ops mark pages `"stale"`.
- `PDFController.__init__()` stays cheap; all signal wiring goes in `activate()`.
- Continuous mode: `change_scale` rebuilds the whole scene, not one page.

## Commands (this machine)

- Tests: `.venv\Scripts\python.exe -m pytest …` — never bare `pytest` (system Python has a different PyMuPDF and masks runtime-only bugs). Run one full suite at a time; a concurrent pytest aborts Qt tests.
- Types: `.venv\Scripts\python.exe -m mypy model/ utils/` — same command as CI; the venv is for version parity with `constraints-ci.txt`.
- Lint: `ruff check .` must be fully clean — the whole tree (tests and scripts included) is at zero and CI's lint job blocks on it. The repo is not `ruff format`-clean; do not run it.
- Code graph: `python .codegraph/query.py search|context|callers|callees|explore <symbol>`; re-index with `python .codegraph/indexer.py` after structural changes (no `--help`; any invocation rewrites `graph.db`).

## Context loading

Grep first. `docs/PITFALLS.md`, `docs/ARCHITECTURE.md`, `TODOS.md` and `.codegraph/CODEINDEX.md` (use `query.py` instead) are large: use `docs/PITFALLS_INDEX.md` (regen `python scripts/build_pitfalls_index.py`) or `rg "^## "`, then read matched entries by offset.

## Workflow

- For this project's PDF text appearance bugs, fidelity edits, related tests/plans or completion reviews, read [pdf-text-fidelity](.agents/skills/pdf-text-fidelity/SKILL.md). Codex and Claude use this same project skill; load its references only for the selected workflow. Its acceptance standard is visual consistency before/after a real edit, including save/reopen.

- Red-light first: write the test, run it, show the failure, then implement. A test that passes before the implementation exists is invalid.
- Tests assert state changes and side effects, including empty input, page boundaries, bad types. Mock I/O, not the PyMuPDF document.
- Work that spans sessions, is handed to another agent or Codex, or moves structure/public API gets `plans/<name>.md` (goal, modules, steps, decisions, dead ends), updated as you go; keep a current-state and next-step block of at most 40 lines at the top and the running log below it. On completion `git mv` it to `plans/archive/` — never delete a plan.
- Done means, in the same commit: ruff clean, no test regressions, new tests for the change, `docs/ARCHITECTURE.md` updated when structure or public API moved, a `docs/PITFALLS.md` entry (Area/Symptom/Cause/Fix/File) + index regen for new gotchas, `TODOS.md` current.
- Never add machine-specific data (`C:\Users\<name>\…`, home paths, hostnames, MAC addresses) to any tracked file — the blocking CI `device-guard` job and the local pre-commit hook (`scripts/hooks/pre_commit_device_guard.py`, installed by `scripts/hooks/install_git_hooks.py`) reject added lines that match.
- Commit only when asked. Never push, merge, or open a PR unprompted.

## Delegation

- `deep-reasoner` (read-only analysis), `fast-worker` (fully specified mechanical edits), `plan-code-reviewer` (diff-vs-plan verdict). Their rules live in `.claude/agents/`.
- High-stakes decisions: task deep-reasoner and an independent peer (Codex `/codex:rescue --background` where the Codex plugin is installed) separately, then synthesize.

## Compact instructions

When compacting, keep the user's most recent instructions verbatim, the current state and next step, open decisions, and the paths of plan and record files. Drop tool output; it can be re-read from those files.

Legacy section refs in code/docs: §2 = Layer rules, §3.1 = Commands, §4 = Context loading, §5.x/§6/§7/§8 = Workflow, §10 = Commands (code graph), §11 = Delegation.
