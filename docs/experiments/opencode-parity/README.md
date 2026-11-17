# OpenCode + OpenRouter free models: does this harness deliver the same task quality?

Two questions, kept apart on purpose:

1. **Model**: how far can each free model get on the repo's real tasks?
2. **Harness**: how much of any result comes from the harness (AGENTS.md rulebook, role files, hooks, the brief ladder) and not from the model? A pass with the rulebook never reaching the model measures the model; a rule-breaking pass measures the missing enforcement.

Every run therefore records the harness identity next to the model identity (`HARNESS.md`), and outcome (is the task solved) is graded separately from process (was the rulebook followed).

Files here:
- `PROTOCOL.md`: tasks, sandbox, privacy rules, grading, the frozen rubric, the harness arms.
- `HARNESS.md`: what "the harness" was for each run (files, hashes, what OpenCode loads).
- `RUNS.md`: one row per cell, newest last.
- `runs/<cell>.md`: the per-run write-up (no transcripts: they hold local paths).
- Plan with current state and next step: `plans/opencode-parity-harness.md`.

The reference solutions, held-out tests, grader and raw transcripts are NOT in the repo; they live in a sibling directory next to the checkout (`pdf_editor-opencode`) so a sandbox can never reach them.
