# Claude API development tool

Select `--model claude-sonnet-5-5` for bounded implementation-patch proposals or
`--model claude-opus-5-5` (default) for review. The tool sends prompt text and
returns text; it does not execute patches, run tests or edit the worktree.
Codex reviews and applies proposals, establishes red tests before implementation,
and verifies actual App behavior. Keep scope and source snippets narrow.
Standard Sonnet 5.5 prices, checked 2026-11-07: USD 2 input / 10 output per MTok
([official model page](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)).
Both models share the existing USD 200 ledger; changing models never resets it.

`--max-tokens` is the output cap and thinking shares it: an 8192 request spent
everything on thinking and returned no patch. The tool accepts 1..131072 (the
synchronous maximum of both models); the default stays 4096. Pick the cap by task:

| Task | `--max-tokens` | Sonnet 5.5 output cost cap |
|---|---:|---:|
| Narrow review | 8192-16384 | USD 0.08-0.16 |
| Bounded implementation | 32768 | USD 0.33 |
| Cross-module design or long patch | 65536 | USD 0.66 |
| Required large task | up to 131072 | USD 1.31 |

Input is billed on top. The cap is a ceiling, billing follows actual usage, but the
local ledger reserves the full cap and never refunds. Opus 5.5 costs twice as much:
131072 reserves about USD 2.62, above the default per-call ceiling of USD 2, so the
owner must approve it explicitly with `--call-limit-usd`; the default is never
raised silently.

Above 16384 the tool streams the response (SSE) and rebuilds the same JSON shape,
because one non-streaming request can exceed the 90 s read timeout and be billed
without a result. If the stream ends early the partial text is kept and
`stop_reason` is `stream_incomplete`; treat it like `max_tokens` below.

Request one complete patch rather than repeating code in prose. If a
response ends with `max_tokens` or `stream_incomplete`, preserve it as partial evidence and inspect it;
never apply an incomplete patch or treat the call as successful implementation.
For a follow-up, narrow scope or increase the explicit limit within the call
budget. Split tests, Controller and View changes when needed, while preserving
their shared contract and red-before-production order.

The tool prices four models (standard tariff, USD per MTok input/output, checked
2026-11-07): `claude-opus-5-5` 4/20 (default), `claude-sonnet-5-5` 2/10,
`claude-fable-5-1` 10/50 and `claude-haiku-5-5` 0.10/0.50 for prompts up to 100,000
tokens, 0.50/2.50 above that (tier picked from the counted prompt). Fable at the full
131072 cap reserves about USD 6.6 and Opus about USD 2.6, so both need an explicit
`--call-limit-usd`; Haiku at the full cap costs about USD 0.07.

Suggested model division (a recommendation, not enabled configuration; session model
and `.codex/agents` pins are unchanged): Terra coordinates and executes; Sonnet proposes bounded implementations;
Opus handles architecture and independent review; Haiku suits large, verifiable,
low-risk parallel jobs; Fable is for major bottlenecks or architecture disputes;
Luna only does mechanical edits with a fixed specification. The API sees only the
context it is given, so the main model must supply the relevant context, inspect
every patch and look for measurement gaps. Judge the split by defects, regressions
and acceptance pass rate at equal workload, not by model names.

Run the development-only tool with the project venv:

```powershell
.venv\Scripts\python.exe scripts/claude_api_tool.py --key-file <local-key-file> --prompt-file <prompt.txt> --output <new-response.json> --ledger <persistent-ledger.json> --max-tokens 4096
```

Use one persistent ledger for this owner's USD 200 allowance. Do not create a fresh ledger after a failure. Local reservations conservatively count full output limits and never refund; external calls using the same account are not tracked. Provider billing remains authoritative. The default per-call ceiling is USD 2; requests above USD 10 are rejected. Prices are pinned to the standard tariffs checked on 2026-11-07; revalidate before changing models, pricing or service options.

The key file contains only the key. The tool uses it only in the HTTPS authentication header. It does not print the key or store it in request artifacts. Do not include credentials in prompts. Prompts and responses may contain project information: select the source snippets needed for the review. The tool sends only prompt text, not arbitrary files or PDFs.

No automatic retry or redirects are allowed. On a failed request inspect the failure and ledger before a manual retry. A stale lock requires checking that no call is active before removal. Reservations remain after uncertain failures. Output JSON includes usage and stop reason; inspect text and truncation before treating the task as successful.

This tool has no App dependency, tool-execution loop or ability for Claude to modify the worktree. Store run artifacts outside commits.
