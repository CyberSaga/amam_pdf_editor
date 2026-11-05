# Codex harness for this repo

Files: `AGENTS.md` (Codex rulebook; `CLAUDE.md` stays the Claude rulebook), `.codex/config.toml`
(sandbox baseline, subagent limits, role registration), `.codex/agents/*.toml` (four roles),
`.codex/hooks.json` (hooks, see `docs/codex/HOOKS.md`), `docs/codex/pdf-editor.config.toml`
(user-profile template). `test_scripts/test_codex_harness_drift.py` keeps them consistent.

## One-time setup

1. Install the profile. Copy `docs/codex/pdf-editor.config.toml` to `$CODEX_HOME/pdf-editor.config.toml`
   (`$CODEX_HOME` defaults to `~/.codex`), review it, and start Codex from the repo root with
   `codex -p pdf-editor`. Machine-specific keys (trust entries, paths, providers) stay in your own
   `config.toml`, never in the template. Unverified: that `-p pdf-editor` resolves a standalone
   `pdf-editor.config.toml` rather than a `[profiles.pdf-editor]` table in `config.toml`; if it does not,
   paste the template's keys into a `[profiles.pdf-editor]` table.
2. Trust the project path. Codex loads `.codex/config.toml` (roles, sandbox) only for a trusted project.
   Every new checkout or worktree path is a new, untrusted project; Codex writes its own
   `[projects.<path>]` trust entry when you accept the prompt.
3. Trust the hooks once. Open `/hooks` in the interactive UI and trust the entries from
   `.codex/hooks.json`. Trust is keyed by the file's content: any edit to `hooks.json` needs a fresh
   trust. Until then Codex skips the hooks silently and the rules in `AGENTS.md` are prose only.
4. Launch from the repo root. Hook commands are relative (`python scripts/hooks/codex_hook.py <Event>`)
   and run with the project root as cwd.

## Models and roles

The Claude and Codex model tiers map as follows (tentative, owner mapping of 2026-11-04):

| Claude | Codex | Used by |
|---|---|---|
| Fable | gpt-6-astra | main-session orchestrator and judge only; never a subagent |
| Opus | gpt-6.1-sol | implementer (profile, high); `deep-reasoner` (xhigh); `plan-code-reviewer` (high) |
| Sonnet | gpt-6.1-terra | `reader` (medium); default subagent model |
| Haiku | gpt-6-luna | `fast-worker` (low) |

Role files pin `model`, `model_reasoning_effort`, `model_verbosity` and `developer_instructions`. They
cannot set the sandbox or approval policy, so read-only roles are read-only by instruction only; the
sandbox comes from `.codex/config.toml` and the CLI.

## Clones and worktrees on Windows

Under the default `[windows] sandbox = "elevated"`, shell commands in any directory other than the main
checkout run with cwd `C:\`. For a clone or worktree, pass `-c windows.sandbox="unelevated"`.

Under `unelevated`, Python 3.12.4+ creates `os.mkdir(path, 0o700)` directories with a DACL for the current user only, which the restricted sandbox token cannot write into; `tempfile.mkdtemp` and pytest's `tmp_path`/basetemp both use 0o700, so every `tmp_path` test fails at setup with `PermissionError ... .lock`, whatever `TEMP` points at (redirecting `TEMP` into the workspace changes nothing). The main checkout under the default sandbox is unaffected. For a clone, put a `sitecustomize.py` in the clone venv's `site-packages` that maps mode `0o700` to the default in `os.mkdir` (the harness runner does this; it is never a tracked file), and say so in the run record because it is an environment difference from the owner's setup.
## Running non-interactively

Pipe the prompt through stdin, run from the repo root, and write outputs outside the repo.

PowerShell (the repo shell; `<` redirection is a parse error there):

```
Get-Content -Raw prompt.md | codex exec -C <repo-root> -p pdf-editor -c windows.sandbox=unelevated -
```

Git Bash or cmd only:

```
codex exec -C <repo-root> -p pdf-editor -c windows.sandbox="unelevated" - < prompt.md
```

Preflight before any graded run in a fresh clone or worktree: Codex skips untrusted hooks silently, and
trust for a new path is not assumed to carry over. Run one `codex exec --json` with a trivial prompt that
runs a bare `pytest --version`, and require `Command blocked by PreToolUse hook` in the event stream (or
the SessionStart pointer in the injected context). If neither appears, trust the project path and the hooks
via the interactive `/hooks` UI in that path, then repeat the preflight.

Add `-m <model>` explicitly when the run must not depend on the profile. Run one `codex exec` at a time.
The first prompt of a session never arms the stop latch, so a brief containing phrases such as
"do not run more than one pytest" is safe.
