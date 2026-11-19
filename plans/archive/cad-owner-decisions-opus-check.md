# CAD M0 owner decisions: Opus check of Astra's advice

Status: closed 2026-11-19, the owner took every recommendation (rulings in the handoff running log); archived. Written 2026-11-19 by Opus. Inputs: `plans/cad-owner-decisions-for-astra.md` (brief) and `plans/cad-owner-decisions-astra-advice.md` (advice). Rulings go into the handoff log; then all three files move to `plans/archive/`.

## Re-run of Astra's measurements (same scripts, dirty A5 tree, PyMuPDF 1.27.1)

| Claim | Astra | Opus re-run | Holds |
|---|---|---|---|
| A: model-layer edit, `compress=1` | 854–986 ms | 705–713 ms | yes (shape) |
| A: edit, `compress=0` | 134–149 ms | 102–115 ms | yes |
| A: edit, zlib level 1 | 170–212 ms | 152–162 ms | yes |
| A: saved bytes (garbage=1), 1 / 0 / zlib1 | 1,405,890 / 4,296,546 / 1,817,233 | identical | yes |
| A: decoded save/reopen equality | all true | 12 of 12 true | yes |
| A: discovery with placements removed, identical result | images 231→0.8 ms, heavy 87→5 ms | images 216→0.7 ms, heavy 65→3.8 ms, identical | yes |
| B: native malloc fail under 128 MiB cap → `find_tables` returns `None`, peak ≈ 33 % of cap | yes | same output | yes |
| C: `id(doc)` sites = `table_objects.py:61` + `font_stream_compaction.py` scope counter | yes | same | yes |
| C: two oversized scans evict each other; failure set is global | yes | same output | yes |

Source citations checked: `pymupdf/__init__.py:7819` (`update_stream`, `compress` truthy), `:19081` (`FZ_DEFLATE_BEST`, Astra wrote `:19075`, the function start), `:11774`–`:11801` (`get_image_rects` forces `hashes=True`); `helper_main.py:102` (`_read_payloads` outside the `try`, N3); `pdf_content_ops.py:401`–`:437` (direct `cm` in a proven frame uses placements only for the offset counter, D10); `memory_limit.py:82` (unsupported platform raise, Astra wrote `:78`).

## Verdict per decision

| ID | Astra | Opus | Owner word needed for |
|---|---|---|---|
| D1 | c: handle generation + retire | agreed | H3 text change |
| D2 | a: honest "not completed" message | agreed; fold N3 in | A3b item 4 text change |
| D3 | a: zoom keeps pending click | agreed | none (follows H4) |
| D4 | a: resolve whole batch before first mutation | agreed | none |
| D5 | c: Windows-only, explicit unsupported message | agreed | platform scope of M0 |
| D6 | fix now | agreed | none |
| D7 | keep all, add to card text | agreed | the additions themselves |
| D8 | c: new card A6 (async text hit + reuse), before Track B | agreed; A6 needs an Opus design pass before an implementer gets it | A6 and its place in the order |
| D9 | new: explicit zlib level-1 writer | agreed | A5 item 3 text change |
| D10 | new: lazy placements | agreed | A5 item 2 text change |
| D11 | kind-specific scan message | agreed | none |
| D12 | bounded atomic admission; failures scoped to document + frame | agreed in direction; the pin/admission mechanics are the largest design item and need an Opus card first | A5 items 1 and 4 text change |

No disagreements. Line-number drift of a few lines in two citations; no claim depends on it.

## Not verified by re-run

- D3, D4, D6, D7 rest on source reading only (Astra did not measure; no measurement needed).
- D8 latency figures are from the A4 log, not re-measured.
- N4 (alias map growth) is source-only.
