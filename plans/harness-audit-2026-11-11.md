# Harness audit 2026-11-11

Goal (owner request): audit the whole agent environment (rulebooks, hooks, agent definitions, settings, plans,
memory, past session transcripts) with subagents of several models; find statements that no longer match the
code, unsuitable design, redundant instructions and detours; improve it for task success rate and token use.

## Current state and next step

- State (2026-11-12): audit done, the changes below are applied in the working tree and NOT committed. Seven
  harness test files pass (shell_read_guard 71, shell_edit_guard 65, ruff_on_edit_shell 15,
  claude_settings_hooks 5, codex_hooks 70, claude_hooks 155, codex_harness_drift 10 + 1 skipped);
  `ruff check .` clean. The whole suite was not run (hooks, tests and docs only; no product code touched).
- 2026-11-12 owner rulings applied (uncommitted): completion-gate chain and fusion tools retired (git rm,
  references cleaned); `utils/` QtWidgets grep in ci.yml and the pre-push gate (tested); tracked `_evidence_pilot`
  baselines kept as cited references (AGENTS.md names the exception); unrelated skills off in the local settings;
  user settings cleaned (default model opus, branch `main`, dead soft-deny and malformed lines removed; the
  subagent-model variable kept: it routes unnamed spawns to Sonnet); effort left to the Jev hook unless the owner
  states one (CLAUDE.md line); `handoff-1103` and `run-suite-job-object` archived; tracked `enabledPlugins` dropped.
- Left for the owner, by hand: `git worktree remove --force .claude/worktrees/fork-setup-checklist` (the auto-mode
  classifier refused it; diff and a branch bundle were backed up first), and the folder rename to a path without
  spaces with a migration script kept outside the repo (dry run checked; needs every tool closed).
- CLAUDE.md Delegation also gives a standing authorization for readers (Haiku), the diff reviewer and
  deep-reasoner, so only Workflows still need the owner's words.
- Committed 2026-11-12 on the owner's request. Next: extract the generic hooks, agents and rules into a
  personal plugin kept outside this repo. The owner tries it per repo first; no user-level registration
  until they say so.
- Watch for one week: false denies from the shell-read rule, and whether shell-read volume drops (rerun the
  transcript count: it was 3.65 M of 5.6 M Bash result characters in 2026-11-04..11).

## Method

| Lane | Model | Scope | Result |
|---|---|---|---|
| 0 | main | stdlib miner streaming all transcripts (1.9 GB, never loaded into a context) into a 76 KB digest | counts used to rank everything below |
| 1 | Haiku | every path, command, flag, section reference in the rulebooks, agent files, skills, Codex files; plan states; memory notes | 12 doc mismatches, 28 plans classified, 22 memory items |
| 2 | Sonnet | each hook (registration, rule, test, docs), liveness of harness scripts, settings, agent definitions, CI vs rulebook | 18 hook findings, 18 scripts classified, 9 settings, 16 agent, 4 CI |
| 3 | Sonnet | measured friction in 27 sessions since 2026-11-04 (shell output, errors, denies, spawns, cache, compactions, owner corrections) | 13 ranked findings |
| 4 | Opus (deep-reasoner) | verdict on every candidate change against the code | apply list, modifications, must-not list |
| 5 | Sonnet (implementer) | `shell_read_guard.py` + tests + replay over historical shell calls | first replay 359 denies / 2.1 M chars, no false deny in the 70 largest; after the `cut -c` escape: 322 of 2,319 calls, 1.9 M chars |

The replay figure is result volume the rule covers, not tokens saved: a Read returns the same lines. The
expected gains are the Edit "not read yet" errors (15), whole-file `cat` dumps, and file state the harness can
track. Measure again after a week.

Main-thread spot checks before applying: QMessageBox gone from `utils/`, no QtWidgets grep in ci.yml,
CONTRIBUTING commands, tracked `_evidence_pilot` count, CLAUDE.md length, the completion-gate references,
origin/main state, the replay deny list.

## Measured findings (2026-11-04..11, 2,366 shell calls, 895 Read, 74 Agent spawns, 28 compactions)

1. 65 % of Bash result characters were file reads through the shell (`sed -n` 1.6 M, `cat` 1.4 M, loops
   0.66 M); implementer subagents made 85 Bash calls against 9 Read in their first six calls. All 15 Edit
   "File has not been read yet" errors followed a shell read.
2. 20 "unexpected EOF" shell errors: all quoted Python heredocs (median 7.3k chars). `shell_edit_guard`'s own
   deny message recommended that form.
3. `agent_prompt_guard`: 6 of 7 denies were false (`"$PY" -m pytest` with the venv path in a variable whose
   value contains a space).
4. `ruff_on_edit`: 62 blocks, 9 on scratch files outside any git tree.
5. 49 of 74 spawn prompts carried a ~658-char RULES block in ~20 wordings that the hooks already enforce.
6. Model routing works: an explicit `model` on a spawn wins over the user-level subagent-model env var; the
   variable still decides unnamed spawns (the forked `/code-review` skill agents under plan-code-reviewer ran
   on Sonnet). plan-code-reviewer made 0 Agent calls in 28 transcripts (54 Skill calls), and the CLAUDE.md
   text is present at the start of every subagent transcript except web-fetch.
7. Cold-cache rewrites: ~1 M of 14.2 M main-thread cache-write tokens. Not a problem any more.
8. Skills: 13 invocations in the window (verify 4, code-review 3, pdf-text-fidelity 2); the skill listing costs
   ~18 KB per session and is mostly unrelated user-level and plugin skills.

## Done-map (working tree)

Hooks (red-light first, each with a test):
- `scripts/hooks/shell_read_guard.py` (new library) + `test_scripts/test_shell_read_guard.py`: deny a plain
  shell read of a git-tracked file; wired in `shell_edit_guard.main()` only, so the Codex dispatcher (which
  imports `shell_edit_guard.violations`) is unaffected; pinned by a new test in `test_codex_hooks.py`.
  Changed after the replay review: a `| cut -c1-N` stage allows the call (Read cannot cap line width).
- `agent_prompt_guard._runner_kind`: the variable's value runs to the closing quote or the next shell operator.
- `quota_breaker.decide`: a window whose `resets_at` has passed is skipped.
- `ruff_on_edit` Edit/Write leg: skip a `.py` outside any git tree (lane worktrees are still linted).
- `shell_edit_guard` deny message: scratchpad `.py` instead of a heredoc.
- `test_scripts/test_claude_settings_hooks.py` (new): pins every registration in `.claude/settings.json`
  (event, matcher, `--event` argument, script exists, no unwired script), with checker self-tests.

Rulebooks and docs:
- CLAUDE.md: stale QMessageBox clause removed; CI qualifier on the whole-suite line; scratchpad-script line;
  shell-read line (hook + character cap); spawn-prompt line; hooks sentence no longer lists six of nine hooks.
- AGENTS.md: QMessageBox clause removed (mirror). pyproject.toml comment corrected.
- docs/ARCHITECTURE.md 7.4 retitled "Test-suite supervisor and agent hooks"; hooks paragraph updated.
- docs/PITFALLS.md entry + index regen; TODOS.md section; CONTRIBUTING.md test commands; ci.yml comments
  (three, no behaviour change); docs/codex/HOOKS.md role-file sentence.
- `.claude/agents/`: plan-code-reviewer loses the `Agent` tool and its delegation rule; implementer starts by
  Reading the named ranges and writes no heredocs; fast-worker preserves line endings.
- `plans/claude-api-tool.md` -> `plans/archive/` ("Status: delivered", no inbound links).

Local, untracked (backed up first): memory index and four notes corrected, two superseded notes deleted, one
new note for this audit.

## Decisions and rejected alternatives

- Read-deny lives beside the edit guard, not as a sixth registration: one interpreter launch per shell call
  (each launch measured ~70 ms; 4 per shell call today).
- No single dispatcher for the Claude hooks: saves ~4 min a week and makes one crash disable every rule.
- `PYTHONUTF8=1` for the session: rejected. It would hide the cp950/cp1252 bug class that CI catches.
- F401/F821 stay in the per-edit lint: a PostToolUse block cannot undo the edit, it only reports; an
  undetected F821 costs a failed test cycle later.
- "Hard constraints" blocks stay in the agent definitions: ~7k tokens a week is not worth a success-rate risk.
- `§` references (28 across 22 files, product code included) stay; the legacy map line in CLAUDE.md stays.
- `stop_latch` pattern left alone: no false arm measured, and a missed stop is the owner's top complaint.
- Plans whose top block exceeds 40 lines (app-performance-v2, true-text-frontier-loop, codex-parity-harness,
  handoff-1103) left to their owners: live handoff state.

## Owner decisions (nothing below was changed)

1. Dead completion-gate chain: `completion_gate.py`, `gate_anchor.py`, `check_gate_passed.py`,
   `check_completion_proof_hook.py`, `codex_session_guard.py` (~1,100 lines + a test + `.gitattributes` pins).
   Never registered, its goal file is gone, and TODOS "Rebind the Stop-hook completion gate" has been open
   since July. Rebind or retire. `verify_no_jump.py` still writes the signoff it binds to.
2. 216 tracked `_evidence_pilot` files vs AGENTS.md "run artifacts stay out of commits": untrack, or reword
   the rule to name what is deliberately committed.
3. Leftover worktree under `.claude/worktrees/` (138 MB, pre-rewrite branch, one modified file): it makes Glob
   return ~1,100 duplicate paths. Removal is destructive; check for junctions first (PITFALLS / memory
   2026-11-05 incident). About 80 local branches carry pre-rewrite hashes.
4. Skill listing: turn off the skills unrelated to this repo in the local settings `skillOverrides`
   (largest fixed per-session cost found).
5. User-level settings: duplicated and malformed lines in the auto-mode environment text, "default branch
   unknown" (it is `main`; `origin/HEAD` is unset), a soft-deny on the code-graph indexer that no longer
   protects anything now that `graph.db` is untracked, a default model that differs from the routing note,
   and a subagent-model env var that silently picks Sonnet for unnamed spawns (forked skills).
6. `.claude/settings.json`: two allow rules spelled with forward slashes (they match only the agent-file
   spelling), and a tracked `enabledPlugins` entry whose marketplace exists on one machine only.
7. `fusion*.py` (1,124 lines) and `ux_signoff_agent.py` (789 lines) are referenced by their own tests only.
8. `utils/` must not import QtWidgets: add the grep to ci.yml, or leave it a convention (comment now says so).
9. Plans: `handoff-1103-new-conversation.md` (PR #43 merged; archive once the lane merge it describes is
   committed), `run-suite-job-object.md` (archive condition met, CI-only questions open),
   `performance-handoff-2026-11-07.md` and `perf-heavy-files.md` stay (still cited by TODOS, scripts, tests).
   Nine plans have no current-state block (list in the lane-1 report).
10. Effort for Opus subagents: the transcripts show two different owner instructions; state one in CLAUDE.md.
11. A TokenEconomizer hook exits with code 49 on SessionStart / UserPromptSubmit in three sessions.

## Log

- 2026-11-11: miner, lanes 1-3, Opus verdict.
- 2026-11-12: hook fixes, read guard built, replayed, adjusted (`cut -c` escape) and wired; docs, agents,
  memory. Raw lane reports and the replay list stayed in the session scratchpad, outside the repo.
