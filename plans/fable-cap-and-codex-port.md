# Fable subagent cap (merged route guard) + Codex adapter comparison

## Current state and next step

- DONE 2026-11-14 on `merge/security-remediation`: Codex comparison (commit `e6741b4a`) and the Fable guard
  merge (below). Nothing left except the live checks under Open questions.
- Fable merge: `model_route_guard.py` now holds the former `fable_dispatch_guard.py` logic plus the cap;
  `fable_dispatch_guard.py` removed; `.claude/settings.json` drops its entry and registers
  `model_route_guard.py --event release` on SubagentStop; `EXPECTED` updated; tests in
  `test_scripts/test_fable_dispatch_guard.py` (kept name, now imports `model_route_guard`). Docs: CLAUDE.md
  Workflows line, ARCHITECTURE hooks paragraph, PITFALLS entry, TODOS.

## Decisions (owner, 2026-11-14)

- Secure-save floor stays `SECURE_SAVE_GARBAGE_LEVEL = 1` (closes review item 1 of plans/security-merge-level1.md).
- One route guard: fold `fable_dispatch_guard.py` into `model_route_guard.py`, remove the former and its
  `.claude/settings.json` registration and `EXPECTED` entry in `test_scripts/test_claude_settings_hooks.py`.
- Fable subagents: at most ONE running at a time (concurrent cap, not per-session total).
  - Counts toward the cap: an Agent with `model` containing "fable", and from a Fable main session any
    dispatch that would inherit it (fork, no `model` with an `inherit`/missing definition).
  - Workflow `agent()` with Fable (explicit or inherited) stays denied outright: one workflow fans out.
  - Release: a SubagentStop hook frees the slot; a TTL guards against a killed subagent that never reports.
  - Keep the existing "every spawn names a model" rule and the override `fable-dispatch-ok` /
    `CLAUDE_FABLE_DISPATCH_OK=1` (decide whether the override still makes sense with a cap).
  - Update CLAUDE.md (Delegation/Workflows lines that say Fable never inside agents), AGENTS.md if it mirrors
    the rule, docs/ARCHITECTURE.md hooks paragraph, PITFALLS entry, and the owner's memory note.
- Codex: owner authorized a Sonnet agent to compare the remote adapter file by file and merge the better parts.
  Known remote fixes to check first: canonical `spawn_agent` tool name (local matches only
  `collaborationspawn_agent`), `ruff format` flags checked per command segment. 7 add/add conflicts:
  `.codex/agents/{deep-reasoner,fast-worker,plan-code-reviewer}.toml`, `.codex/hooks.json`,
  `docs/codex/CLAUDE_API.md`, `docs/codex/HOOKS.md`, `scripts/hooks/codex_hook.py`; remote also adds
  `docs/codex/README.md`, `docs/codex/pdf-editor.config.toml`, `test_scripts/test_codex_hook_adapter.py`,
  `plans/archive/codex-hook-adapter.md`. Do not merge the branch wholesale.

## Open questions

- SubagentStop payload: the release reads `agent_type` and `agent_transcript_path` (documented fields) but this was
  NOT probed live. If they are missing the slot is only freed by the 45-minute TTL; check in a real session after
  a Fable subagent finishes (`<tempdir>/pdf_editor_claude_fable_slot/<session_id>/slot.json` should disappear).

## Log

- 2026-11-14: decisions recorded; spawning blocked by quota_breaker.
- 2026-11-14 Codex comparison DONE (main thread, Sonnet; no subagent, quota breaker). Remote
  `origin/feat/codex-hook-adapter` (`b9b46332`) is a 138-line adapter, older and smaller than the local setup
  (`codex_hook.py` 424 lines + `_codexkit.py` 239, `reader.toml`, `.codex/config.toml`, captured-payload fixtures,
  `test_codex_hooks.py`, `test_codex_harness_drift.py`). Local is a superset; no file taken wholesale.
  - Gap 1 REAL, fixed: the Codex spawn tool spelled `spawn_agent` was ignored by the stop latch. Red test
    `test_stop_latch_also_denies_the_unprefixed_spawn_agent_name` failed first; `_codexkit.TOOL_KINDS` and the
    `.codex/hooks.json` PreToolUse matcher now accept both spellings (captured payloads use the prefixed one).
  - Gap 2 NOT real locally: `RUFF_FORMAT_RE` args stop at `; & |`, so `ruff format .; echo --check` is denied.
    Regression test `test_ruff_format_check_flag_must_belong_to_the_format_command` added; passed without a fix.
  - Remote agent tomls are older/shorter than local; remote lacks reader/config/drift tests. Nothing else adopted.
  - Codex tests: 82 passed, 1 skipped; ruff clean. Staged, not committed.
- 2026-11-14: Fable guard merged and cap implemented. Tests written after the implementation (not red-light first);
  273 hook tests pass, ruff and mypy clean.
- 2026-11-14 advisor review of the cap, three holes fixed red-first: (1) claim race (exclusive create `open(..., 'x')`;
  only a really stale claim is cleared); (2) a non-Fable agent of the same type no longer frees the slot (model
  decides when readable, type only when the stopped agent's transcript model is unreadable; a real
  `subagents/*.jsonl` returns its model through `tail_records` + `last_assistant`); (3) the override no longer
  blanks the main model for Agent calls, so it never lifts the cap (Workflow inheritance checks only). The owner
  was not asked whether the override should exist at all: open. 276 hook tests pass.

## Known gaps (block merging back to the main checkout, not the branch commit)

- Slot leak on a denied call: the claim is written in PreToolUse. If another hook (`quota_breaker`, `stop_latch`,
  `agent_prompt_guard`) or the permission prompt denies the same call, no SubagentStop fires and the slot is
  stuck until the 45 min TTL. Likely fix: a short pending claim confirmed at SubagentStart, released by
  `agent_id`; depends on payload fields not yet seen.
- Live probe owed (after the quota reset): dump one real SubagentStart and SubagentStop payload; check
  `session_id` (same as the parent's?), `agent_id`, `agent_type` for a fork and a default agent, and
  `agent_transcript_path`. Until then the release path is only unit-tested.
- `plan-code-reviewer` not yet run (quota breaker).
