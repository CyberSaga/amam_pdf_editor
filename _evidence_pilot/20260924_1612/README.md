# Evidence package 20260924_1612 — non-default fonts (標楷體 / DFKaiShu)

Timezone: Asia/Taipei (UTC+8). Stamp from local clock at package creation.

## Purpose
User-requested true-text editing evidence for **non-default fonts**, especially **標楷體 (DFKaiShu-SB-Estd-BF)**, vs prior HVAC PMingLiU/Arial pilots.

## Constraints honored
- No product source changes
- Isolated copies only under this folder (`candidates/`)
- Originals under `test_files/` hash-verified untouched
- No PDF binaries uploaded to box; JSON/MD mirror only
- No invented case_id/hashes (ECC seq from cad-font-study TEXT_CASES)
- Vector CHB/[AIRPORT_CODE] classify-only
- `accepted_for_code` = 0 (UI unverified; engine rejects)

## Files
- `FONT_INVENTORY.md` — font scan of test PDFs
- `METHODS_AND_EVIDENCE_PLAN.md` — written BEFORE edits
- `cases.json` / `PARENT_SUMMARY.json` — outcomes
- `case-ecc-1/` `case-ecc-2/` `case-ecc-3/` — per-case evidence
- `candidates/` — isolated ECC copies + edited PDFs (local only)
- `ecc4_deferred.json` — seq60 deferred (column neighbors)
- `run_pilot.py` — evidence-folder runner

## No Claude handoff
This package is self-contained evidence for the parent agent. No Claude Code handoff document.

## Statuses
See `PARENT_SUMMARY.json`. Expect `save_reopen_pass` with engine reject; not product acceptance.
