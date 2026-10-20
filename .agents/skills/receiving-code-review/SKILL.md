---
name: receiving-code-review
description: Use when receiving code review feedback, before implementing suggestions, especially if feedback seems unclear or technically questionable - requires technical rigor and verification, not performative agreement or blind implementation
---

# Receiving Code Review

- Verify each item against the codebase before implementing it: does the current code exist for a reason (compat, platform, a prior user decision), and does the suggestion break anything?
- Restate the technical requirement in your own words; if any item is unclear, ask about all unclear items before implementing any of them — items are often related.
- Push back with evidence (`file:line`, a test, a version pin) when a suggestion is wrong for this codebase or adds unused capability (grep for callers; if none, propose removal instead).
- If a suggestion conflicts with a decision the user made earlier, raise it with the user before acting.
- Order: blocking issues (breaks, security) → simple fixes → refactors. Test each fix individually; report with the fix itself, not with agreement.
- On GitHub, reply to inline review comments in-thread (`gh api repos/{owner}/{repo}/pulls/{pr}/comments/{id}/replies`), not as a top-level PR comment.
