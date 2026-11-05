# Codex parity harness — make GPT models deliver Claude-grade work here

## Current state (2026-11-05)

- Goal: the owner is moving daily work from Claude Code to Codex CLI (0.166). Use the four
  verified-broken `docs/to_Update.md` items as the worked example, and derive the environment,
  prompts, agent roles and hooks that let GPT models reach the quality Claude reaches here.
- Model mapping set by the owner (tentative): GPT-6-Astra <-> Fable 5.1, GPT-6.1-Sol <-> Opus 5.5,
  GPT-6.1-Terra <-> Sonnet 5.5, GPT-6-Luna <-> Haiku 5.5. All four answer `codex exec -m <model>`.
- Worked-example items (all reproduced in the real app): Home/End dead (handler only reached from the
  viewport eventFilter); ribbon stays on 檔案 after open; delete dialog defaults 全部; 自訂範圍 opens a
  second dialog instead of an inline field.
- Phase 0 (probes) DONE: payload shapes, blocking semantics (JSON only; exit 2 dead), subagent roles and
  project config all verified (Log below). Phase 1 (gap map, protocol, fix brief) DONE.
- Phase 2 DONE, COMMITTED 8cbed66 on `parity/harness` (owner allowed one commit, 2026-11-05): Claude workflow `codex-parity-port` wrote the port into the lane worktree
  `../pdf_editor-parity/lane-harness` (branch `parity/harness`, no junctions, tests via the main venv by
  absolute path): `scripts/hooks/_codexkit.py` + `codex_hook.py`, `.codex/hooks.json`, `.codex/config.toml`,
  `.codex/agents/*.toml`, AGENTS.md rewrite, `docs/codex/`, `test_scripts/test_codex_hooks.py`,
  `test_scripts/test_codex_harness_drift.py`; Opus review (1 high, 3 medium, 8 low) and the fix pass
  landed; verified by me in the lane: test_codex_hooks 66 passed, test_claude_hooks 115 passed (file
  untouched), drift 10 passed + 1 skipped (generic-guard file unset), `ruff check .` clean, AGENTS.md 14.2 KB.
- G1 grader `grade_arm.py` (1514 lines, stdlib) + self-test live in the session scratchpad `grading/`.
- Arm A clone ready (own venv, code graph, smoke 6 passed, brief copied); seed run_suite baseline running.

## Next step

- RESULT so far (n=1 per arm, same brief, same model gpt-6.1-sol high): arm A (seed AGENTS.md, no hooks) = H2 FAIL,
  ~7.5/12 soft; arm B-2 (committed harness 8cbed66 + venv mkdir shim) = all H PASS, 11.5/12 soft (S10 partial),
  G2 Opus 'parity yes', G3 Astra 'no' only for want of the baseline comparison that G1 H2 supplies; one confirmed
  LOW shared by G2+G3 (dialog Tab order: 確定 built before the scope row, so Tab from the range field reaches 取消
  first and Enter discards the range; pdf_view.py:6365/6439). Rubric soft max is 12, not 15 (text slip); threshold
  13/15 ~ 10.4/12 -> B-2 reaches parity; cost 140k vs 89k effective tokens, 39.5 vs 10.4 min.
- Caveats: single run each; B-2 benefited from the fixed environment (shim) that A had to build itself; hooks never
  fired in B-2 (0 denies, Done gate silent), so the measured delta is rulebook + roles + config + clean tree.
- Owner decided 2026-11-05: (1) run the holdout A/B once each; (2) merge `parity/harness`; (3) adopt B-2's
  diff + Tab-order fix as the real fix. DONE: `parity/harness` fast-forwarded into the working branch (HEAD
  8cbed66); B-2's diff copied into the main tree (pdf_view, test_page_controls, PITFALLS+index, TODOS hunk,
  new test file + plan) with the owner's dirty TODOS/to_Update edits preserved and only the four item lines
  annotated; Tab-order fix added red-first (`_add_scope_dialog_buttons`: setTabOrder + default button; 2 red
  -> 16 green), PITFALLS entry; test_page_controls 6 / shell_tab_ux 19 / multi_tab_plan 118+1s /
  object_manipulation_gui 45, ruff clean, pre_push_checks pass. Uncommitted (owner commits).
- Holdout (phase 5) IN PROGRESS: brief `brief_holdout_v1.md` (Opus draft, line refs verified against 8cbed66;
  item = thumbnail drop-position: no drop indicator for internal drags + source row captured at drag start,
  mapping rule unchanged). Arms HA-1 (arm-A-1 clone, seed fd0c415, seed AGENTS.md, now WITH the venv mkdir
  shim so both arms share the environment) and HB-1 (arm-B-1 clone, seed 8cbed66, trust preflight re-verified)
  run serially after the main run_suite; grade with G1 (+ seed baseline), G2 Opus blinded, G3 Astra.
- Still owed: G1 fold-back (pytest counter for `*>` form, S1 reads 'N failed', S10 accepts linked report).
- Cleanup owed at the end: clones arm-A-1, arm-B-1, clone-probe, lane worktree; branches parity/probe-1,
  parity/harness (after merge decision), arm/B-1, arm/B-2; `[HVAC_DWG_PDF]` still missing from test_files.

## Decisions

- Nothing in `scripts/hooks/` is rewritten for Codex until the payload field names are confirmed
  by a live probe (the Claude hooks read `tool_input.command`, `transcript_path`,
  `tool_use_id`, `stop_hook_active`); the docs alone are not trusted.
- Experiments run on their own branches/worktrees outside the repo dir; the main checkout is
  never an arm. Worktrees get junctions to `.venv` and `test_files`. No commits anywhere: arms
  are graded as working-tree diffs against HEAD plus the copied `docs/to_Update.md`.
- Implementer for arms A and B: `gpt-6.1-sol` at high (the Opus analog, the tier that implements
  here); `gpt-6-astra` stays the independent reviewer. Arm R (Claude headless baseline) is not
  run in round 1; parity is the absolute threshold until the owner asks for R.
- PgUp/PgDn keep their current behaviour (the owner called them OK); only Home/End are routed.
  Rotate dialog default stays 全部; listed as pending.
- Codex hooks may be stricter than Claude's prose (git write denies, big-file whole reads,
  red-light and Done stop gates): consistent with the owner's "hooks over memory" rule.
- Harness changes must stay generic (never name Home/End, the ribbon or the delete dialog).
- No commit, push or PR without the owner asking.

## Log

- 2026-11-04: scouting done (Codex 0.166, hooks.json + multi_agent + skills available; codex
  plugin 1.0.6 with `codex-companion.mjs task`; repo `AGENTS.md` already defers to CLAUDE.md).
  Phase-1 workflow launched (`codex-parity-understand`).
- 2026-11-04: phase 1 done (4 Sonnet readers + Opus judge, 405k tokens, 13 min). Outputs: 45-row
  gap map, experiment protocol (arms A baseline / B harness, 8 hard gates + 12 soft points, parity
  = all gates + >= 13/15 + zero confirmed high findings, holdout item afterwards), fix brief for
  the four items (new test file `test_scripts/test_m3_ui_defaults_followup.py`, tmp_path PDFs
  because `test_files/` is gitignored). Key facts: Codex has 14 hook events incl. SubagentStop /
  PreCompact; project `.codex/hooks.json` loads only for a trusted project path and each new
  worktree path is untrusted; role files `.codex/agents/*.toml` pin model + effort; profiles are
  `$CODEX_HOME/<name>.config.toml`; AGENTS.md is capped at 32 KiB; Codex reads files through the
  shell, so grep-first becomes hookable. Unverified until the probe: tool names and
  `tool_input` shapes, `tool_response` keys, spawn_agent fields, exit-1 semantics, `--json` keys.
- 2026-11-04/05: phase 0 probe, run inline (the auto-mode classifier refuses any command
  carrying `--dangerously-bypass-hook-trust` or `-s danger-full-access`, so hook payloads could
  not be captured; that needs the owner to trust the hooks once via `/hooks` or to allow the
  bypass flag). Verified facts:
  - All four models answer; Sol accepts high and xhigh, Astra medium and xhigh, Terra medium,
    Luna low.
  - `codex exec` with the prompt as an argument blocks on stdin under the Bash tool; pipe the
    prompt with `- < file`.
  - Under the default `[windows] sandbox = "elevated"`, shell commands in any directory other
    than the main checkout run with cwd `C:\` (git fails, `.venv` missing); a git worktree and a
    local clone both fail. `-c windows.sandbox="unelevated"` (restricted token) fixes it: cwd,
    git, apply_patch, `.venv\Scripts\python.exe -m pytest` (6 passed), `rg`, and `%TEMP%` writes
    all work in a local clone. Arms therefore run in local clones with the unelevated sandbox.
  - Codex writes its own `[projects.'<lowercase path>'] trust_level = "trusted"` entry for a
    new directory on first `codex exec`; no manual trust block is needed.
  - Codex's shell on Windows is `pwsh.exe -Command '<cmd>'`; the `--json` stream has
    `item.completed` items of type `command_execution` (`command`, `aggregated_output`,
    `exit_code`, `status`), `file_change` (`changes[].path`, `kind`), `collab_tool_call`,
    `agent_message`, `error`, and `turn.completed.usage` with `input_tokens`,
    `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`,
    `reasoning_output_tokens`.
  - Luna reported the `explorer` subagent as unavailable inside `codex exec`; subagent
    spawning in exec mode is unverified.
  - `docx-template-repair` user skill has no frontmatter and logs an ERROR on every session
    (harmless, owner's `~/.codex/skills`).
- 2026-11-05 INCIDENT: `git worktree remove --force` on the probe worktree followed its `.venv`
  and `test_files` junctions and emptied the main checkout's `.venv` and `test_files/` (both
  gitignored). Arm A was not started. Rule from now on: scratch clones get their own venv and a
  copied fixture subset, never junctions; junctions are removed with a non-recursive `rmdir`
  before any recursive delete. Recovery: `.venv` rebuilt from `requirements.txt` +
  `constraints-ci.txt`; `test_files/` public parts (veraPDF-corpus-staging, sample-files-main)
  are re-downloadable, private fixtures need the owner's backup.
- 2026-11-05 hook payloads captured (owner trusted the 14 probe hooks via `/hooks` "Trust all" in the
  clone-probe dir; a trusted hooks.json survives new `codex exec` sessions; the probe script now reads a
  `probe_control.json` so hooks.json never changes and trust stays valid). Verified payload facts:
  - Every event carries `session_id`, `transcript_path` (`~/.codex/sessions/<y>/<m>/<d>/rollout-*.jsonl`),
    `cwd`, `hook_event_name`; most also `turn_id`, `model`, `permission_mode` (`bypassPermissions` under
    `approval_policy=never`). Field names match Claude's, so `_hookkit` readers port with one shim.
  - PreToolUse/PostToolUse: `tool_name` is `Bash` (`tool_input.command` = the raw command text, not the
    pwsh/cmd wrapper), `apply_patch` (`tool_input.command` = the whole patch text, `*** Add File:` lines
    carry absolute paths), `collaborationspawn_agent` (no separator; `tool_input.task_name`, `fork_turns`,
    and `message` is an ENCRYPTED token, so prompts of subagents are not inspectable by hooks) and
    `collaborationwait_agent` (`timeout_ms`). `tool_use_id` is `exec-<uuid>` for shell/patch and
    `call_<hex>` for collaboration tools.
  - PostToolUse `tool_response` is a STRING: for Bash the captured stdout/stderr only, no exit code; for
    apply_patch `Exit code: N
Wall time: ...
Output:
Success. Updated the following files:
A <abs path>`.
    A command whose process fails to spawn fires PreToolUse but no PostToolUse.
  - Subagents fire SubagentStart (`agent_id`, `agent_type` = `default` even when `task_name=explorer` was
    requested), their tool calls fire Pre/PostToolUse with the MAIN `session_id` but the subagent's
    `transcript_path` and `turn_id`, and SubagentStop adds `agent_transcript_path`, `stop_hook_active`,
    `last_assistant_message`. So subagent spawning does work in `codex exec`.
  - Stop: `stop_hook_active`, `last_assistant_message`. UserPromptSubmit: `prompt`. SessionStart: `source`
    (`startup`). SessionEnd: `reason` (`other`); its timeout and Interrupt's are clamped to 3 s (warning in
    the `--json` stream). Pre/PostModelRequest: PostModelRequest has `status`, `error`, `token_usage`
    (incl. `cached_input_tokens`, `reasoning_output_tokens`) per model call: a per-turn cost meter for free.
  - Hook env: no CODEX_* variables; `CLAUDE_PLUGIN_DATA` leaks from the Claude parent process. Hook cwd =
    project cwd.
  - Shell flake: in this run the first `pwsh.exe -Command` spawn under the unelevated sandbox failed with
    `CreateProcessAsUserW failed: 5` and Codex fell back to `cmd.exe /c` for the rest of the session, which
    broke the model's `python -c "..."` quoting twice. Earlier unelevated runs used pwsh throughout. Watch
    for it in the arms; the WindowsApps pwsh alias is the suspect.
- 2026-11-05 blocking semantics (probes B and C, Luna, 0.166): EXIT CODE 2 NEVER BLOCKS (PreToolUse,
  PostToolUse, Stop all ignored it, with or without a trailing newline on stderr); exit 1 is also
  ignored. Only stdout JSON acts: PreToolUse `{"hookSpecificOutput":{"hookEventName":"PreToolUse",
  "permissionDecision":"deny","permissionDecisionReason":R}}` and the legacy `{"decision":"block",
  "reason":R}` both block Bash and apply_patch, and the model sees `Command blocked by PreToolUse hook:
  R. Command: <cmd>` as the tool error (Luna followed the reason's instruction each time). PostToolUse
  `{"decision":"block","reason":R}` lets the command run but reports R to the model as a failure;
  PostToolUse/UserPromptSubmit `additionalContext` is injected and followed. Stop `{"decision":"block",
  "reason":R}` resumes the turn and the next Stop carries `stop_hook_active: true` (same latch
  semantics as Claude). So every ported hook must speak JSON; the Claude `exit 2` path is dead code
  under Codex. pwsh spawned fine in B and C; the run-1 `cmd.exe` fallback was transient.
- 2026-11-05 probe D (subagents): a project `.codex/config.toml` IS loaded by `codex exec` in a trusted
  dir; `[agents.<name>] config_file = "./agents/<name>.toml"` resolves relative to `.codex/`; the role's
  `model` pin holds (the reader's PostModelRequest events show `gpt-6.1-terra` inside a Luna session);
  the model listed `reader, default, explorer, worker` as available types. `spawn_agent` input gains
  `agent_type` when a type is named; SubagentStart/Stop and the subagent's own tool hooks carry
  `agent_type` + `agent_id`. SubagentStop `{"decision":"block","reason":R}` resumes the subagent and the
  next SubagentStop has `stop_hook_active: true` (explorer obeyed R; the reader's fixed output contract
  made it ignore R, which is the desired behaviour for a role with a strict output block). The model
  also read `.agents/skills/scope-fence/SKILL.md` on its own: project skills are visible. Scrubbed
  fixtures (one record per event/tool/rule) are in the session scratchpad `p0probe/fixtures/
  codex_payloads_v1.jsonl` (to be copied into `test_scripts/fixtures/` by the hook port).
- 2026-11-05 phase 2 (workflow `codex-parity-port`, 4 agents, 513k tokens, 32 min): ported rules =
  bare/non-venv/whole-suite pytest deny, process-kill deny (all threads), `ruff format` deny, in-place
  shell-edit deny, ruff after apply_patch and after shell edits (PostToolUse block with ruff output),
  stop latch (prompt leg context + spawn deny; first prompt never arms it because the brief matches the
  stop phrase), retry-cap footer as SubagentStart additionalContext, pre-paste gate (stop + prompt), a
  Done stop gate (tests/TODOS/PITFALLS-index/`from __future__`/typing forms/basicConfig/ruff; once per
  problem set; silent while latched), SessionStart pointer. Not ported: quota breaker, cold-cache gate,
  retry-cap prompt rewrite (spawn message encrypted), red-light stop gate (no exit codes in
  tool_response). Deferred rows (owner call): git-write deny, big-file whole-read deny, pytest lock,
  compact re-injection, read-only enforcement per agent_type, PostModelRequest cost breaker. Review
  fixes: drift test no longer names the worked-example items (reads a guard file from
  `GENERIC_GUARD_FILE`); README gives the PowerShell prompt-piping form and a hook-load preflight.
  Unverified until arm B: anchored `^(...)$` matchers, SessionStart/SubagentStart additionalContext
  reaching the model, project-level sandbox/approval keys.
- 2026-11-05 seed baseline (arm A clone, clean fd0c415, own venv, no test_files): run_suite 9690 passed /
  17 failed / 202 skipped in 23.5 min; the 17 are fixture-dependent (test_no_jump_editor_geometry x13,
  test_text_commit_replay_fast_path, test_text_commit_ui_real_corpus x2, test_core_interaction_audit) and
  form the H2 baseline. Arm A run (Sol high, brief_v1, baseline harness = current AGENTS.md, user-level
  hooks only): 10.4 min, 35 commands, 10 pytest runs, 2.90M input (2.84M cached) / 18.8k output /
  4.1k reasoning tokens. Changed view/pdf_view.py (+119/-), test_page_controls.py, TODOS.md, new
  test_m3_ui_defaults_followup.py (10 tests; red light 6 failed / 4 passed shown); it put its helper
  scripts (implement/verify/finish) under the ignored `.run_suite/`. Stopped itself at the real-app verify
  step (driver stalled 123 s on the re-open file chooser, a native dialog) citing the brief's "stop when
  stuck"; run_suite, final ruff, pre-push, PITFALLS entry + index not done; rotate default left at 全部.
  pwsh spawn failed twice more (error 5, WindowsApps alias) under the unelevated sandbox. G1 (with the
  suite) and G2 (Opus, blinded as X1) running.
- 2026-11-05 arm A graded. G1 (25 min incl. suite): H1 pass (10/6/19/118+1), H2 FAIL (2 new failures:
  test_object_manipulation_gui delete-shortcut tests; confirmed alone: the new `keyPressEvent` fallback
  reads `self.toolbar_tabs` unguarded and the tests build a partial PDFView), H3-H8 pass; S1 vacuous
  (edit done by a helper python script, no file_change event; G2 confirmed red light by reading),
  S7 fail, S12 flags docs/to_Update.md LF (my copy, not the candidate's). G2 (Opus, blinded): code of
  all four items correct, layer-clean, scoped, tests meaningful and red first; no medium/high bugs by
  reading (missed the partial-view AttributeError that the suite catches); Done list mostly undone
  (PITFALLS, TODOS re-check, to_Update annotations, run_suite, ruff, pre-push never run); verify driver
  never exited 0 (stalled on the re-open native file chooser); stop reason covered only the verify
  step. Score ~9/15, 1 hard gate failed -> arm A below parity. Effective tokens 89k
  (2.84M of 2.90M input cached). Observations for the harness: the candidate routed edits through its
  own python scripts under the ignored `.run_suite/` and ran pytest with a `sitecustomize` shim
  (TEMP/TMP/PYTHONPATH into `.run_suite/`) because the unelevated sandbox denied mkdir 0700 in %TEMP%;
  shell-leg ruff (mtime scan) is what catches such edits, apply_patch hooks would not.

- 2026-11-05 arm B-1 (Sol high, 2:55 min, 425k in / 372k cached / 6.2k out): VOID, environment fault. The
  candidate wrote the regression file + plan, ran it (3 failed: delete default, inline inputs x2; 6 errors:
  every tmp_path test PermissionError at setup on pytest's basetemp `.lock`), then stopped citing AGENTS.md
  'a hook or sandbox deny is the rule' and 'red light before implementation'. Honest, scoped, no shims; but
  zero implementation. Root cause (probed with Luna in arm-A-1/arm-B-1/main): under `windows.sandbox=
  "unelevated"` any `os.mkdir(path, 0o700)` (Python >= 3.12.4 writes a current-user-only DACL) yields a dir
  the restricted token cannot write into; TEMP location is irrelevant (redirecting TEMP via
  `shell_environment_policy.set.TEMP` into the workspace fails identically); the main checkout under the default
  sandbox is unaffected; the default sandbox in a clone still runs with cwd C:\. Arm A had diagnosed the same
  cause itself (its `.run_suite/sitecustomize.py` comment says 'mkdir(0700) excludes the sandbox token').
  Fix: venv-local `sitecustomize.py` mapping 0o700 -> default in the clone venv (probe: mkdtemp/listdir/walk/
  chmod/lock/rmtree all OK). Harness fixes in the lane: AGENTS.md preamble now separates hook deny (rule) from
  sandbox error (environment fault: report, finish independent parts, no shims); docs/codex/README 'Clones and
  worktrees' documents the DACL trap; pre_paste_gate prompt warning says it is advisory (a Luna probe prompt
  containing 'paste its output' tripped `paste` on the dirty tree and Luna refused to run anything). Tests:
  test_claude_hooks 115, test_codex_hooks 66, drift 10+1 skipped, ruff clean. Committed 8cbed66. Done gate
  stayed silent on B-1 (no source .py changed, TODOS touched) - it cannot see 'nothing implemented'; noted.
  B-1 artifacts: scratchpad arms/B-1/ (events.jsonl, last_message.md, candidate/ test+plan+TODOS.diff).
- 2026-11-05 arm B-2 (Sol high, committed harness 8cbed66 + venv sitecustomize shim, 39.5 min, 7.26M in /
  7.18M cached / 41k out incl. 16k reasoning; 32 commands, 13 apply_patch file_changes, 8 subagent calls, 0 hook
  denies): implemented all four items (view/pdf_view.py +119/-?, test_page_controls.py, new
  test_m3_ui_defaults_followup.py 12 passed red-first '6 failed, 6 passed'), ran the four named test files, run_suite
  (exit 1: 9769 passed / 26 failed / 203 skipped - 17 corpus-dependent as in the seed + 9 QLocalServer
  'addListener: access denied' = unelevated-sandbox artefact, correctly labelled as unverified), pre_push_checks
  exit 0, PITFALLS + index + TODOS + to_Update annotated, plans/m3-ui-defaults-followup.md, verify_supervise driver
  exit 0 with 18 screenshots (native file chooser automation was killed once with 124; it fell back to a fixed
  chooser result). Final message says 'overall acceptance not complete' - honest. Preflight before the run: bare
  pytest denied + SessionStart pointer seen (trust held after `tr -d ''` restored the LF hooks.json bytes; the
  CRLF checkout had a different sha). Grading: G1 running (arm X2), G2 Opus blinded (same prompt as X1 with
  paths swapped, saved grading/g2_prompt_X2.txt). Artifacts: scratchpad arms/B-2/.
- 2026-11-05 arm B-2 G2 (Opus, blinded, X2): parity-grade YES conditional on G1 H2. S2-S12 all pass, H8 pass, no
  high/medium findings; 5 lows (dialog focus/Tab order from constructing 確定 first; redundant installEventFilter;
  PITFALLS cause wording inherited from the brief; machine-specific suite-status line in TODOS; an unsupported
  'independent review found nothing' claim - no spawn event). Noted: B-2 also made its first pdf_view.py edit via a
  python newline='' script (CRLF preservation), so S1 reads vacuous for both arms - grader coverage note, and a
  question for the harness: does apply_patch keep CRLF? Report: scratchpad arms/B-2/g2_report.md.
- 2026-11-05 arm B-2 G1 (X2): H1 PASS (12/6/19/118+1s), H2 PASS (run_suite 9998 tests, 17 failing = exactly the
  seed baseline, 1409 s), H3 PASS, H5-H7 PASS; H4 and H8 first came out FAIL but both hits were
  plans/m3-ui-defaults-followup.md (a plan file CLAUDE.md asks for) - grader false positives: grade_arm.py now
  allows plans/ in the H4 fence and treats it as docs in H8 (self-test expectation updated, 78 ok); rerun with
  --skip-suite: all H PASS. S1 FAIL by G1 (it wants a nonzero pytest exit; the candidate's `*>` redirect masks the
  pwsh exit) but red at seq 11 precedes the first pdf_view.py write at seq 16 (a newline='' python script) - G2
  confirms red-first, S1 adjudicated PASS. S10: supervisor exit 0 and 18 PNGs on disk (G2), but no screenshot paths
  in the final message - PARTIAL. S7, S12 PASS; S2-S6, S8, S9, S11 PASS per G2. Grader gaps logged: pytest/run_suite
  command counter missed the `*> $env:TEMP` form (pytest=1, run_suite=0 reported; 6 pytest + 1 run_suite actually
  ran), S1 should read 'N failed' from aggregated_output when the shell exit is masked, S10 should accept a linked
  report.md. Effective tokens 140k vs 89k for arm A; wall 39.5 min vs 10.4. Hooks: 0 denies, Done gate silent
  (nothing to block) - the B-2 delta came from the rulebook/config/environment, the hooks were an unused net.
- 2026-11-05 arm B-2 G3 (Codex gpt-6-astra high, read-only sandbox, adversarial, same prompt as G2 + refute list):
  Done list all done/partial as G2; S2-S11 PASS (S10 partial); H8 PASS; one LOW: Tab order 確定 -> 範圖 -> input ->
  取消 so Tab+Enter after typing a range rejects the dialog (confirmed by reading, matches G2's L1); refuted: double
  key handling, missed open paths, overlap normalisation, zero-page/last-tab-close regressions, CRLF damage.
  Verdict 'no' rests on the absent baseline comparison (G1 H2 settles it: 17 = seed) and on acceptance tests that
  mock dialog.exec instead of the OK/Tab path. Report: scratchpad arms/B-2/g3_report.md.
