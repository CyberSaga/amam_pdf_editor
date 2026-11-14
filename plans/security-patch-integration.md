# Security patch integration

## Current state

- Sixteen accepted patches, CF18 and integration fixes are applied on baseline `6554db9`; pre-existing main-worktree changes were preserved.
- Complete suite on a frozen tree: **10,900 passed, 0 failed, 17 skipped, 0 errors, 0 hung, 0 crashed, 1 rc5-ok**, 2,510.2 seconds. HEAD, tracked diff, all 40 untracked files and status matched before and after. All 17 skips match the earlier full run by test ID and reason: missing optional PDFs or OCR dependencies, and an absent real gate plan. The rc5 file is a manual printing validation script with no pytest test functions.
- Focused recheck: 7,474 passed, 12 skipped. It is supporting evidence only: documentation changed during that run and no starting snapshot was recorded.
- Supervised real-App flow passed three edits, preview, apply, undo/redo, save/reopen, two renderers and masked password input. Offscreen screenshots show Chinese labels as boxes, so Chinese UI typography is unverified.
- The full working-tree device-identity scan found eight Windows user-profile paths in the pre-existing untracked handoff document; keep it local and do not stage it. The product integration and other worktree files have no such findings in that scan.
- F4, F13, F15 and F25 remain unresolved; signed history, detached transfer and OCR policy residuals remain in TODOS. No commit or push authorized.
- After the suite, documentation only was updated. The worktree scan excluding the handoff covered the other 39 untracked files and tracked changes: 7,888 added lines, zero findings; the full scan covered 7,993 added lines and retained the eight handoff findings. A synthetic positive check passed.
- Printing pipeline collection was independently checked: no tests collected, pytest exit 5. Its manual `main()` is not an automated test. The real gate skip covers `test_hook_real_goal_path_blocks_without_proof`; optional OCR/large PDF fixtures were unavailable.
- Object-stream measurement on a 1,310-page public corpus: source 32,472,771 bytes, unpacked 50,503,116, packed 42,741,473.

## Milestones and acceptance

1. Preserve source artifacts; inventory the sixteen current patches and rejected candidates.
2. Diagnose CF18 and the save/reopen oracle with a minimal counterexample. Establish red tests before fixes. Sonnet proposes bounded implementation; Opus reviews fixed source/diffs and evidence.
3. Integrate all applicable patches and documentation. Record unresolved candidates and accepted signed-document/OCR residuals explicitly.
4. Run targeted security/persistence tests, lint, types, layer contracts, device guard, and the supervised whole suite. One pytest process at a time outside the suite runner.
5. Drive the real App through editing, preview, apply, undo/redo, save/reopen; inspect screenshots and non-target rendering. Integrate verified changes into the main worktree without overwriting existing work.

## Decisions

- Full saves pack object streams without introducing deleted content or changing encryption/permissions.
- Unsigned note deletion uses the CF17 replaced-content flag, preserving xrefs; signed documents preserve their signed prefix.
- Thumbnail limit is 10:1; OCR checkpoint policy remains unchanged.
- No commit, push, merge, or PR is authorized.
- API inputs contain bounded source excerpts and measurements, never credentials or source PDFs. Opus handles design/review, Sonnet implementation/evidence. Fable is reserved for unresolved architecture conflicts.

## Evidence log

- Handoff distinguishes a previously passing Qt lane from pure-lane environment failures and thirty save/reopen failures. These must be independently reproduced before changing tests.

- CF18 red/green: five tests failed on the sixteen-patch base and passed on the integration; expanded controls now cover permissions/owner password, partial-write recovery, and textbox redo across packed save (eight passed).
- Opus independently reviewed fixed save and other-runtime diffs. The alleged redo collision did not reproduce: xref lengths 5 -> 17 -> 17 -> 19, storage containers 17/18, redo succeeded. The Save As wrapper uses the same staging helper; its outer damaged-session gate remains.
- Opus identified a confirmed interaction: malformed FT made the conservative signature boolean True, so old note text survived an append. Sonnet proposed strict classification; four malformed-field save/delete cases failed before and pass after. The default probe remains fail-closed; known signed documents still append (40 consent tests passed).
- Sonnet implementation/review informed the two-leg oracle. Its counterexamples for a fake object-stream container and undeclared target dictionary changes were reproduced and fixed; twelve oracle tests pass. This oracle checks semantic fidelity; dedicated security tests separately scan for removed secret markers.
- Windows command-line regression: repeating long worktree paths exceeded CreateProcess limits (84,769 characters). Relative repository paths fixed it; three command-builder tests passed. External paths keep their original form.
- Local API artifacts record completed usage, conservative reservations including uncertain timeouts, immutable review inputs and responses. No PDF or key content was sent in prompts.

- Complete suite first pure lane: 7,349 passed, 3 failed, 12 skipped. The failures were confined to test_run_suite.py: pytester inherited the ancestor project rootdir when TEMP was under the checkout; two external-path layout cases also implicitly assumed TEMP was outside REPO_ROOT. Sonnet proposed explicit child rootdir/config and a fake sibling repository root; exact assertions were retained. Product runtime code was unchanged. Qt lane also had twelve storage-normalization failures; those cases were corrected and are included in the running recheck.

- Additional concrete CF18 failure probe: successful GC4 prune changed note xref 6 -> 5 (table 9 -> 8), then a forced packing failure propagated while epoch stayed 1. Opus independently confirmed the notification must follow the first successful prune write; caller notification must remain only in the one-pass branch. Five regression/control cases in test_packed_save_failure_epoch.py are green after moving notification to the successful prune boundary.
