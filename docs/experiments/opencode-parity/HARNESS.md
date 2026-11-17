# Harness identity per run

Snapshot b214fa57 (the sandbox start state): `AGENTS.md` sha256 d3827a056821 (14,613 bytes), `CLAUDE.md` sha256 2a07f210afcf (7,885 bytes), `.claude/` roles and settings, `.codex/` config, roles and hooks, `.agents/skills/` (6 skills), `scripts/hooks/` hook scripts. No OpenCode project config or plugin in the repo.

OpenCode 2.2.6 (WSL), standalone server, `--auto` approvals, global config provides only a local-proxy provider; the OpenRouter provider is a stored login.

| Question | Status |
|---|---|
| Does OpenCode inject AGENTS.md into the system prompt? | YES (verified 2026-11-12). One request, nemotron-3.5-super-vl, throwaway sandbox whose only file was an `AGENTS.md` holding a canary token, told to answer without tools or file reads: it returned the token exactly. So the rulebook reaches the model in every run, even when it never reads the file. Caveat: this proves injection, not that the model obeys it (cohere ran a whole-suite pytest anyway). |
| Do the repo's hook scripts run under OpenCode? | UNVERIFIED, expected NO: they are Claude and Codex hooks; nothing wires them into OpenCode. First run: no hook fired, so the whole-suite rule was unenforced. |
| Do role files (`.claude/agents`, `.codex/agents`) reach OpenCode? | UNVERIFIED, expected no. |
| Environment shim | The rulebook names Windows paths; a note in every brief maps them to the Linux venv. |
