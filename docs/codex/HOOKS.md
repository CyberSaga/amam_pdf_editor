# Codex hooks for this repo

`.codex/hooks.json` registers one dispatcher, `python scripts/hooks/codex_hook.py <Event>`
(adapter: `scripts/hooks/_codexkit.py`; tests: `test_scripts/test_codex_hooks.py`). It applies the
rules of the Claude hooks in `scripts/hooks/` (`.claude/settings.json`) in Codex's contract.

## The contract: JSON on stdout, exit 0, nothing else

- **Exit codes do nothing under Codex** (CLI 0.166, live probes): exit 2 never blocks, exit 1 is
  not a warning, and stderr never reaches the model. A Claude hook registered unchanged is a no-op.
- Only ONE stdout JSON object acts, so the dispatcher merges the reasons of every rule that fires:
  - PreToolUse deny: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": R}}`.
    The model sees `Command blocked by PreToolUse hook: R. Command: <cmd>`.
  - PostToolUse `{"decision": "block", "reason": R}`: the command already ran. R comes back to the model as its failure.
  - Stop `{"decision": "block", "reason": R}`: the turn resumes, and the next Stop carries
    `stop_hook_active: true`. Every Stop rule lets that second stop through.
  - `{"hookSpecificOutput": {"hookEventName": <Event>, "additionalContext": T}}` injects T.
- The hook always exits 0. On its own error, or on a payload it cannot read, it prints nothing to
  stdout (a one-line note may go to stderr). A broken hook must never lock a session.
- Commands are relative: Codex runs hooks with cwd = project root and sets no project-dir variable.
  Launch Codex from the repo root (`-C <repo>`).

## What each event does

| Event (matcher) | Rule | Answer |
|---|---|---|
| PreToolUse `Bash` | Denies bare `pytest`, and pytest on any interpreter other than `.venv`. Denies the whole suite in one pytest process (`pytest test_scripts/`, or pytest without a file); use `scripts/run_suite.py`. Denies `taskkill`, `pkill`, `Stop-Process` and `kill -9` in every thread: Codex sessions run unattended. Denies `ruff format` (`--check` and `--diff` pass). Denies in-place shell edits of git-tracked files (`sed -i`, `perl -i`, `>`, `tee`, `Set-Content`, `Out-File`, `[IO.File]::WriteAll*`); use apply_patch or a `newline=''` Python edit. | deny |
| PreToolUse `collaborationspawn_agent` | Denies the spawn while the stop latch is armed. | deny |
| PostToolUse `apply_patch` | Runs ruff on the `.py` files the patch added, updated or moved to. Paths may be absolute or relative to cwd; only files inside the project count. Deletions and failed patches are skipped. | block with the findings |
| PostToolUse `Bash` | Runs ruff on every `.py` changed since the PreToolUse stamp of the same call (shell-run edit scripts). | block with the findings |
| UserPromptSubmit | A stop instruction ("stop when this round finishes", 「停止」…) arms the latch. The session's first prompt never arms it: under `codex exec` it is the brief, and brief rules such as "do not run more than one pytest" read as stop phrases. The owner's next non-stop prompt lifts it; slash lines and harness text do neither. When the owner says they pasted while tracked files differ from HEAD, the hook adds a warning. | additionalContext |
| Stop | Pre-paste gate: the final message tells the owner to paste, but the tree is dirty. Done gate: runs over the files this session changed (dirty in git with an mtime after the session start), see the list below. | block once |
| SubagentStart | Injects the retry-cap footer (three identical failures: stop and report). | additionalContext |
| SessionStart | Points at AGENTS.md and this file, and prunes state files older than a week. | additionalContext |

The Done gate checks:

- a source `.py` changed without any `test_scripts/*.py` changing;
- a source `.py` changed without TODOS.md changing;
- `docs/PITFALLS.md` changed without `docs/PITFALLS_INDEX.md` changing;
- a new module lacks `from __future__ import annotations`;
- added lines use the old typing forms `List`, `Dict`, `Optional`, `Tuple`, `Set` or `Union`;
- added lines call `logging.basicConfig` outside `main.py`;
- the changed `.py` files have ruff findings.

The Done gate never runs pytest or `build_pitfalls_index.py`.

State lives in `PDF_EDITOR_CODEX_STATE_DIR`, default `<tempdir>/pdf_editor_codex`, as one JSON
file per session_id holding the latch and the session start. Subagents share the parent's
session_id, so the latch covers them too. Ruff stamps reuse `ruff_on_edit.py`'s
`CLAUDE_RUFF_STAMP_DIR`.

## Not ported (and why)

- **Retry-cap prompt rewrite** (`updatedInput`): the spawn `message` is an encrypted token. The
  footer goes in through SubagentStart instead; the planned `.codex/agents/*.toml` role files are
  meant to carry it in `developer_instructions` too (not on this branch yet).
- **Agent/Workflow prompt scanning** for pytest and kill rules: subagent prompts are encrypted.
  Their shell calls are checked instead.
- **quota_breaker**: Codex exposes no rate-limit percentages to hooks.
- **cold_cache_gate**: Codex uses a different cache model.
- **Red-light Stop gate** (a failing test run before the first source edit): the Bash
  `tool_response` has no exit code, and the mandated `*> file` redirect leaves it empty. AGENTS.md
  carries the rule as prose.
- Not yet built (separate gap-map rows): the git-write deny, the whole-file-read deny for the big
  files, the pytest concurrency lock, plan re-injection on compact, and read-only enforcement for
  the reader and reviewer roles.

## Registration choices

- PreToolUse matches `^(Bash|collaborationspawn_agent)$`. `apply_patch` is left out because no
  rule acts before a patch, and leaving it out saves a process per edit. The anchored form is
  unverified in a live run.
- SubagentStop is not registered: no ported rule targets it. The Stop gates are the main
  thread's job.
- Timeouts are 20 s, except PostToolUse and Stop at 60 s: both run ruff, and Stop also runs git.

## Trust: re-trust after every change

Project hooks load only when the project path is trusted AND the hooks were trusted once in the
interactive `/hooks` UI. Trust is keyed by the `hooks.json` content, so **any edit to
`.codex/hooks.json` needs a fresh `/hooks` trust**. Until then Codex skips the hooks silently. A new
worktree path is a new, untrusted project.
