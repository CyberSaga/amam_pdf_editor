# Claude API development tool

Select `--model claude-sonnet-5-5` for bounded implementation-patch proposals or
`--model claude-opus-5-5` (default) for review. The tool sends prompt text and
returns text; it does not execute patches, run tests or edit the worktree.
Codex reviews and applies proposals, establishes red tests before implementation,
and verifies actual App behavior. Keep scope and source snippets narrow.
Standard Sonnet 5.5 prices, checked 2026-11-07: USD 2 input / 10 output per MTok
([official model page](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)).
Both models share the existing USD 200 ledger; changing models never resets it.

Run the development-only tool with the project venv:

```powershell
.venv\Scripts\python.exe scripts/claude_api_tool.py --key-file <local-key-file> --prompt-file <prompt.txt> --output <new-response.json> --ledger <persistent-ledger.json> --max-tokens 4096
```

Use one persistent ledger for this owner's USD 200 allowance. Do not create a fresh ledger after a failure. Local reservations conservatively count full output limits and never refund; external calls using the same account are not tracked. Provider billing remains authoritative. The default per-call ceiling is USD 2; requests above USD 10 are rejected. Prices are pinned to the standard Opus 5.5 tariff checked on 2026-11-06; revalidate before changing models, pricing or service options.

The key file contains only the key. The tool uses it only in the HTTPS authentication header. It does not print the key or store it in request artifacts. Do not include credentials in prompts. Prompts and responses may contain project information: select the source snippets needed for the review. The tool sends only prompt text, not arbitrary files or PDFs.

No automatic retry or redirects are allowed. On a failed request inspect the failure and ledger before a manual retry. A stale lock requires checking that no call is active before removal. Reservations remain after uncertain failures. Output JSON includes usage and stop reason; inspect text and truncation before treating the task as successful.

This tool has no App dependency, tool-execution loop or ability for Claude to modify the worktree. Store run artifacts outside commits.
