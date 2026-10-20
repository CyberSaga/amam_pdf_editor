---
name: adversarial-verify
description: >
  Self-refutation step before presenting non-trivial deliverables.
  Use after completing an architecture decision, a plan, a root-cause analysis,
  or any recommendation the user will act on — anything where being wrong is costly.
---

# Adversarial Verify

## When This Activates

Invoke this skill **after** you've drafted a deliverable but **before** you
present it to the user. It applies to:

- Architecture or design decisions.
- Root-cause analyses and debugging conclusions.
- Plans, before presenting them.
- Recommendations the user will act on (dependency choices, API designs).
- Non-obvious claims about how the codebase works.

It does **not** apply to:

- Mechanical edits (renames, formatting) — the tests and linter cover these.
- Answers to simple factual questions ("what does this function return?").
- Changes already validated by a passing test suite (red-light-first covers these).


## The Protocol

### Step 1 — Steel-man the opposite

Ask yourself: "What is the strongest argument that my conclusion is wrong?"
Write it down internally. Consider:

- Did I read the actual code, or am I relying on memory/docs that could be stale?
- Is there a simpler explanation I dismissed too early?
- Does my reasoning depend on an assumption I haven't verified?
- Would this break under an edge case I haven't considered?

### Step 2 — Test the weak link

Identify the single weakest link in your reasoning — the claim you're least
certain about. Verify it concretely:

- If it's about code behavior: read the source or grep for evidence.
- If it's about system state: check live state (git, filesystem, runtime).
- If it's about a dependency: check the actual version and API.

### Step 3 — Revise or confirm

- If refutation succeeds: revise your conclusion before presenting. Note what
  changed and why.
- If refutation fails (your original conclusion holds): present with confidence.
  Optionally note the counter-argument you considered and why it doesn't apply.

## Output Format

When verification changes your conclusion, include a brief note:

```
> Verified: initially concluded X, but [evidence] shows Y instead.
```

When verification confirms your conclusion, no special output is needed — just
present normally. The skill is invisible when it doesn't change anything.
