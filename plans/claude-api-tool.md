# Claude API development tool

## Current state and next step
- Scope: development-only Opus call tool; no App runtime integration.
- Owner authorizes up to USD 200 total. Reuse one ledger; never reset it to regain budget.
- Tool reserves full counted-input plus maximum-output cost before generation, without refunds, including failures. It does not observe spending by other clients.
- Focused tests: 8 passed with normal permissions after review fixes. Live Opus 5.5 smoke succeeded with expected marker and normal end_turn; 60 input / 25 output tokens, estimated USD 0.00074, reservation USD 0.02072.
- Independent review found temporary-neighbor overwrite and missing console redaction; offline regression reproduced both (2 failed, 6 passed), then corrected with exclusive unique temporary files and sanitized summary data.
- Status: delivered; 8 focused tests passed, ruff and diff checks passed, independent delta reviewer returned ship with both blockers resolved.
- NEXT: use this tool for bounded development reviews only when requested. Full suite remains owner-paused; no commit or App change made.

## Contract
- Fixed official HTTPS destination, no redirects, no automatic retries.
- Key supplied via a local file path; no key in command arguments, output, logs or prompts.
- Opus 5.5 standard input/output prices: USD 4/20 per million tokens, verified 2026-11-06 against official pricing. No paid tools or prompt caching.
- Token counting precedes generation; per-call default USD 2, maximum USD 10; ledger cap USD 200.
- Reservations persist before dispatch; uncertain/failed requests remain charged against local budget. This conservative ledger is not the provider billing ledger.
- Output is a new JSON artifact with response, usage, prompt digest and reservation; never overwrite an existing result.
- Stop reasons and response content must be inspected: HTTP success alone does not prove a useful review.
- No shell tools or workspace write access delegated to Claude.

## Running log
- Red: focused test collection failed with ModuleNotFoundError before implementation existed.
- Initial sandbox test run: 2 passed, 4 setup errors from pytest temporary-directory access; request normal-permission verification, no environment shim.
