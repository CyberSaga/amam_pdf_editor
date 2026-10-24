---
name: scope-fence
description: >
  Execute only what was requested; flag everything else without acting.
  Use when starting any implementation task to prevent mid-task feature creep,
  drive-by refactors, and unasked-for cleanup.
---

# Scope Fence

## When This Activates

This skill is active during every implementation task. Before writing or editing
any production code, check the request against the fence.


## The Rule

Do exactly what the user asked — nothing more, nothing less.

If you notice something outside the request (a nearby bug, a style violation,
a refactor opportunity, a missing test for unrelated code, a doc that could be
better), **do not fix it**. Instead, append it to a fence log and continue with
the actual task.

## Fence Log Format

At the end of your response, if you flagged anything, include:

```
### Fence log
- [ ] <file>:<line> — <one-line description of what you noticed>
```

The user decides whether to act on fence-log items. Never act on them yourself
unless the user explicitly asks.

## What Counts as In-Scope

- The specific change the user described.
- Test(s) required by the red-light-first protocol (CLAUDE.md §5.1) for that change.
- Doc updates required by the Definition of Done (CLAUDE.md §7) for that change.
- Fixing lint/type errors you introduced in your own diff.

## What Counts as Out-of-Scope

- Refactoring code you didn't need to touch.
- Fixing pre-existing lint warnings in files you edited.
- Adding error handling "while you're in there."
- Renaming variables for style in lines you didn't change.
- Upgrading dependencies, unless that is the task.
- Improving tests for code you didn't modify.
- Any change whose justification starts with "while we're here" or "might as well."

## Edge Case: Blocking Issues

If the out-of-scope issue **blocks** your in-scope work (e.g., a bug in a
function you must call), fix the minimum required to unblock, note it in the
fence log as addressed, and explain why it was necessary.
