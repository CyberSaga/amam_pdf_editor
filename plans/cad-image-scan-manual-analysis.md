# CAD image scan: automatic bounds for simple filters (card A) and a manual per-page analysis (card B)

Status: DESIGN ONLY, 2026-11-22. Opus reviewed the idea; the owner ruled the points below. Both cards come AFTER the open Astra rounds (worker
lifetime at exit, plans/cad-m0-h23-review.md W1-W5), because they touch the same files.

## Owner rulings (2026-11-22)
- Two cards. Card A first.
- Manual ceilings: the numbers below, measured on the dev machine (see "Measurements").
- Preferences: a NEW preferences window, opened by a keyboard shortcut for now, no menu button. The setting "show the manual analyse button
  for pages the automatic scan refuses" defaults to hidden; hidden means such pages can never be analysed manually.
- The manual "analyse this page for editing" button lives in the RIGHT sidebar.
- An approval is valid only while the file stays open (session only, keyed by generation, page and content key, so any edit of the stream
  cancels it).

## Card A: automatic bounds, no button
`_bounded_stream` (model/pdf_content_ops.py) refuses ASCIIHex, ASCII85 and RunLength by name. Their worst-case expansion is a fixed factor of
the raw length (ASCIIHex shrinks 2:1, ASCII85 expands at most 4x through the `z` shortcut, RunLength at most 128x), so a decode with the
existing room cap (stop when the output passes room + 1) is safe without a button. Accept chains of these plus up to four capped stages
as the Flate chain does, in the parent, with zlib-style incremental decode written in pure Python or via a bounded MuPDF call; verify against
MuPDF's decoded bytes on a corpus (the 17 pdf.js fixtures with LZW, ASCII85, ASCIIHex) and on damaged input. LZW has no useful ratio bound and
stays in card B. Done when: honest ASCIIHex/ASCII85/RunLength content streams within the caps are scanned and edited like Flate; bombs of each
kind are refused without a decode over the cap; outcome check: decoded length equals MuPDF's on every corpus stream and on mutated streams.
Cost: small to medium.

## Card B: manual analysis for resource-limited pages
Scope: only the failure reason resource_limited (not INLINE_REFUSED, which a manual run does not fix). Applies to honest Flate pages over the
automatic caps and to LZW pages.
- Preference: a new `UserPreferences` pair (utils/preferences.py) plus a new preferences window opened by a shortcut (there is no
  preferences dialog today; the "Preferences..." action in view/pdf_view.py is not connected). Default hidden.
- Sidebar: in the right sidebar, for the current page when the refusal is resource_limited and the preference is on: a button "Analyse this page
  for editing (may take up to about 30 s)"; states offered, running (progress by phase, cancel), done, failed; one page at a time.
- Model: `manual_scan_allowed` keyed by (handle generation, page, set key); cleared on close of the file and by any edit of the stream.
- Three places must honour an approval: the caps in `_scan_set_walk` and `_scan_for_discovery`, `_record_over_cap` in pdf_model.py, and
  `ScanVerifier.request` (else edits stay in "analysing" forever). The decode for the child scan and the parent verification stays bounded by
  the manual ceilings; the parent never decodes more than they allow; LZW is decoded by the child (memory cap) and its size checked against
  MuPDF's length on a corpus.
- Ceilings (measured): per-stream decoded 64 MiB, per-page decoded 64 MiB, wall-clock timeout 45 s per phase (child scan, parent verification),
  user told "up to about 30 s" at the ceiling. Child memory cap unchanged (375 MB at 64 MiB against 1,728 MiB).
- Tests (outcome checks): a bomb over the ceiling is refused with flat parent memory; approve, edit, save, reopen; an edit invalidates the
  approval; closing the file clears it; cancel and timeout record nothing; with the preference off the button never appears and no analysis can
  start; LZW size check equals MuPDF's on damaged corpora.
- Cost: medium to large (preferences window, sidebar, model state, three cap sites, tests).

## Measurements (dev machine, single runs, +-10 percent; synthetic CAD-like page, Flate level 1, about 3.6:1)
| Decoded | child scan | parent lex | GUI arrival (set key) | verify wall | move | delete | undo kept per edit | save |
|---|---|---|---|---|---|---|---|---|
| 8.7 MB | 1.13 s | 1.10 s | 0.05 s | 1.4 s | 0.12 s | 0.19 s | 4.8 MB | 0.17 s |
| 32.8 MB | 4.28 s | 4.22 s | 0.20 s | 5.0 s | 0.46 s | 0.68 s | 18 MB | 0.65 s |
| 64.4 MB | 8.5 s / 375 MB | 8.5 s / 292 MB | 0.39 s | 9.9 s | 0.90 s / 363 MB | 1.35 s / 410 MB | 36 MB | 1.3 s |
| 128.9 MB | 17.1 s / 733 MB | 17.0 s / 586 MB | 0.79 s | 19.6 s | 1.80 s / 577 MB | 2.70 s / 835 MB | 71 MB | 2.6 s |
| 4 x 16.4 MB | 8.4 s | 2.1 s per stream | 0.40 s | 10.1 s | 0.28 s | 0.59 s | 36 MB | 1.3 s |
| CAD before.pdf p0 (30.3 MB) | 3.87 s / 157 MB | 3.84 s | (not an image page) | | | | | |
Lex rate 0.13 s per MB, linear. Delete about 1.5x move. The manual run lexes twice (child then parent): wait about 0.28 s per MB.
Freeze over 0.5 s at about 24 MB (delete) / 35 MB (move); over 1 s at 48 / 70 MB; over 2 s at 95 / 140 MB. The undo command keeps two whole
serialized documents, not a decoded stream. Surprise: the arrival of the child answer costs 0.39 s at 64 MB on the GUI thread (decode and hash of
the page in `image_scan_set_key`), above 0.1 s from about 16 MB: a separate item for card B.

### Owner ruling 2026-11-23: card A is option (c)
Decoding of untrusted image-stream bytes moves off the GUI thread (card B's worker owns it); card A is NOT shipped as a GUI-thread bounded decode in any narrowed form. Not implemented yet, by the owner's choice: this is the recorded plan. The parked work (local branches wip/card-a-filter-bounds 3e9dcb01 and wip/card-a-narrowed bdfb67f7) stays as reference only. Design inputs from three Astra rounds: charge raw reads and hashing to the page budget; whole-page placement must not interpret a Form that admission never examined; cold and warm admission must give the same verdict (including Flate predictors at the room boundary); indirect /Length on small unfiltered content streams must keep working (9 of 9 ImageMagick sample streams); a refused image needs a message at click time; the single closing check is an instrumented object-selection walk, cold and warm, counting raw bytes read and hashed, pre-predictor work, native peak and placement calls. Class: parent-side decode, read or hash of untrusted stream bytes is GUI-thread work the budget does not see.
