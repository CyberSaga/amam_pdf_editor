# AGENTS.md

## Shared project rules

Read [CLAUDE.md](CLAUDE.md) before repository work; do not assume Codex loads it
automatically. Follow it as the source of truth for commands, architecture,
scope, planning, tests, documentation, delegation, and finishing work.

CLAUDE.md wins on shared topics. The Astra-only section below governs only
GPT-6 Astra / Codex behavior; it does not waive shared project requirements.
Keep shared rules in CLAUDE.md instead of copying them here.

## Astra-only

### Reasoning effort

- Prefer medium for everyday work. Raise effort when unresolved complexity,
  conflicting evidence, or consequential decisions justify it; do not default
  to max because an older model needed it.
- Honor explicit user and runtime settings. This file expresses a preference;
  it does not change the configured model or reasoning effort.

### Context and skills

- Load context needed for the current task. Avoid mandatory full-repository
  maps, document stacks, and rereading unchanged files before every edit.
- When resuming work, retrieve relevant prior task summaries and plan sections.
  Check historical claims against current files and git state; do not carry
  old task-specific permissions or superseded decisions into new work.
- Try ordinary tasks without optional skills first. Load a skill when explicitly
  requested, required by higher-priority instructions, or useful for a concrete
  workflow or tool capability that the task needs.
- When authoring skills, use one short description stating when to use each.
  Keep SKILL.md a small entry point; load supporting references and scripts only
  for the selected workflow.
- Audit old skill instructions before applying them. Avoid importing generic
  recipes, forced handoffs, automatic commits, or Claude-only slash commands
  into Codex. Follow the shared rules and use available Codex tools.
- Follow explicit user instructions over conflicting skill guidance. If a skill
  blocks authorized work, identify the exact file and instruction and explain
  the conflict; do not invent an approval requirement from a guideline.

### Autonomy and completion

- Treat requests to build, fix, or make something work as authorization to
  implement and verify the requested outcome. Proceed with reversible,
  in-scope steps and routine implementation choices without repeated approval.
- Stop before destructive actions or real scope changes unless already
  explicitly authorized. Ask focused questions when missing information would
  change the intended result; continue independent authorized work meanwhile.
- Establish observable completion criteria from the request and CLAUDE.md.
  When running, inspecting, or fixing the result is in scope, finish that work
  before handing back; do not stop at a plan, first draft, or arbitrary batch.
- Run relevant checks and all required project or task gates. Avoid a full
  suite on every edit; broaden or repeat checks when changed code, failures,
  or unresolved risks justify it, or an explicit gate requires it.
- Finish when the requested behavior is demonstrated and required checks and
  documentation are complete. Report the result, verification evidence, and
  any unresolved blocker or unperformed check. Do not label partial work done.

### Computer use and apps

- Use available apps, connectors, or computer-use tools when they help complete
  or inspect the task. Combine them with code where useful.
- For UI or PDF appearance changes, inspect the relevant user flow or rendered
  result in the app when access is available. Use `.claude/skills/verify/SKILL.md`
  when available and its Qt workflow helps; passing unit tests alone does not
  establish visual correctness. Report unavailable app checks explicitly.
