# Codex hook adapter

## Current state and next step

- Goal: make applicable existing hook protections work under Codex on Windows while retaining Claude and Git hooks.
- `scripts/hooks/codex_hook.py` adapts shell policy, Ruff checks, a stop latch and the pre-paste Stop gate. `test_scripts/test_codex_hook_adapter.py` covers the key paths; 258 related tests passed.
- The replacement configuration was installed in `.codex/hooks.json` with sandbox approval.
- User re-trusted the hooks. Real `apply_patch` and shell writes producing Ruff violations were both blocked by PostToolUse. A shell pre-call stamp and prompt-state file were also observed. The Stop decision was checked directly with a dirty tracked tree; its actual end-of-turn dispatch was not probed.
- The prompt warning reuses the existing Claude classifier and dirty-tree check. SessionStart was only a context pointer and cleanup; the proposed Done gate is a heuristic that duplicates or conflicts with project instructions. Neither was present in the copied configuration.
- User re-trusted the revised hooks. A real subagent received the retry footer; a second real spawn was denied with a temporary isolated armed-state fixture. The actual tool name observed here was `collaborationspawn_agent`; the documented `spawn_agent` name has a synthetic regression test.
- A separate read-only Codex turn exercised Stop with the dirty tracked tree: the first event was captured as `active: false, blocked: true`, the next as `active: true, blocked: false`. The temporary fixture did not modify the active session latch and was removed. Stop-event and turn evidence are in `.tmp-claude-api/hook-stop-live-evidence.jsonl` and `.tmp-claude-api/hook-stop-live-turn.jsonl`.

## Decisions and log

- Opus 5.5 reviewed the Claude and Codex configuration and advised an adapter. The first API call exhausted its output allowance in thinking; a narrowed second call returned a complete review.
- Claude and Git hooks remain separate. Codex's quota and cache inputs do not match Claude's, so their copied registrations are omitted from the proposed config.
- Live probes created untracked Python files with unused imports via `apply_patch` and shell; Codex returned the Ruff diagnostics as tool errors. The probes were then deleted.
- Regression tests first demonstrated that paste prompts lacked warnings and that a separate `--check` could improperly allow `ruff format`; both defects were fixed.
- Additional red tests reproduced the missing `spawn_agent` latch and missing SubagentStart retry context. Both passed after the adapter and registration changes.
- Live verification after re-trust: SubagentStart supplied the retry cap; PreToolUse denied an actual spawn using an isolated armed-state fixture; an isolated Codex turn produced the expected two Stop attempts. The adapter regression file passed 12 tests after removing the temporary instrumentation.
