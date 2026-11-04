# 20260924_1908_font_search — SEARCH ONLY

This package is an **inventory + candidate list** for future true-text font pilots.

## What this is
- Local PDF font inventory under `test_files/`
- Ranked NON-DEFAULT / specialty font candidates with fingerprints
- Cross-check against existing TEXT_CASES / results.json

## What this is NOT
- **No Claude handoff**
- **No accepted_for_code**
- **No PDF mutations** (originals untouched)
- **No product source changes**
- **No invented case_id** — undocumented faces are `candidate_discovered` with fingerprint fields only

## Files
- `FONT_INVENTORY_FULL.md` — all deep-scanned PDFs
- `NONDEFAULT_CANDIDATES.json` — ranked future pilots + gaps + vector-only
- `PARENT_SUMMARY.json` — compact report for parent agent
- `FINGERPRINTS.json` — page_index/seq/original_text samples via project shows()
- `raw_inventory.json` — machine dump
- `_run_font_inventory.py` — read-only scanner used this round

## Vector-only (not pilotable as true-text)
- [VECTOR_CHB_PDF]
- [AIRPORT_CODE] [AIRPORT_DWG_REV].pdf

Stamp: 20260924_1908 Asia/Taipei
