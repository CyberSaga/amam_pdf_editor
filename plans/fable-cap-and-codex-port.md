# Fable subagent cap (merged route guard) + Codex adapter comparison

## Current state and next step

- Decided 2026-11-14 (owner), nothing built yet. Work on branch `merge/security-remediation` (worktree
  `pdf_editor_merge`, merge commit `500c73d7`) or a branch cut from it.
- Blocked until the 7d quota resets (quota_breaker at 98% on 2026-11-14; reset 03:00).
- Next, in order:
  1. Codex comparison: spawn a Sonnet agent (owner explicitly authorized) to compare
     `origin/feat/codex-hook-adapter` (`b9b46332`, base `5dc65697`) file by file with the local Codex setup
     and merge in whatever the remote does better.
  2. Fable cap: merge `scripts/hooks/fable_dispatch_guard.py` into `scripts/hooks/model_route_guard.py`.

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

- SubagentStop payload: does it carry the agent id / model so the slot is released for the right agent?
  Probe before relying on it.

## Log

- 2026-11-14: decisions recorded; spawning blocked by quota_breaker.
