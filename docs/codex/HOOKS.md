# Codex hooks for this repo

`.codex/hooks.json` runs `scripts/hooks/codex_hook.py` for Codex events. The
Claude Code configuration and Git hooks are separate and remain in place.

| Event | Behavior |
|---|---|
| PreToolUse `Bash` | Applies the existing test-command and tracked-shell-edit guards, rejects process kills and unsafe `ruff format`, and stamps the shell call for Ruff. |
| PreToolUse `spawn_agent` / `collaborationspawn_agent` | Denies a spawn while the session stop latch is armed. |
| PostToolUse `Bash` / `apply_patch` | Runs Ruff on changed Python files and returns findings as a tool error. The edit has already happened. |
| UserPromptSubmit | Maintains the session stop latch and warns if the owner is about to paste while tracked files differ from HEAD. The first prompt does not arm the latch; slash and harness messages do not change it. |
| SubagentStart | Gives the subagent the same retry-cap instruction used by Claude's retry hook. |
| Stop | Blocks once if the final message calls for pasting while tracked files differ from HEAD, unless the message already warns about the dirty tree. |

Session state defaults to `<tempdir>/pdf_editor_codex` and can be redirected
with `PDF_EDITOR_CODEX_STATE_DIR`. Ruff stamps use `CLAUDE_RUFF_STAMP_DIR`.
Malformed events and unexpected exceptions fail open; see the tests for the
precise behavior. Start Codex from the project root so relative commands resolve.

The Claude quota and cache hooks depend on Claude-specific inputs and are not
registered for Codex. Its retry-prompt rewrite is replaced by SubagentStart
context injection. The old proposed SessionStart pointer and heuristic Done
gate were not part of the installed configuration.

After `.codex/hooks.json` changes, review and re-trust it in Codex `/hooks`.
In the trusted configuration, real `apply_patch` and shell edits reported Ruff
findings; a real subagent received the retry footer. A real spawn was denied
using a temporary isolated armed-state fixture (the live session's state was not
changed); the observed tool name was `collaborationspawn_agent`. In a separate
read-only Codex turn, captured Stop events showed `blocked: true` followed by
`stop_hook_active: true` and `blocked: false`. Temporary
instrumentation was removed. `test_scripts/test_codex_hook_adapter.py` covers
the adapter, including synthetic tests for the other documented spawn name.
