# Task 16 — Legacy-path fidelity (T16-1 … T16-4)

Branch: `task16/legacy-path-fidelity` (off `88b90bb`). Started 2026-09-05.
Source: `TODOS.md` "Task 16 — Legacy-path fidelity, found by manual test (2026-09-04)".

## Goal

Make the fidelity-preserving tiered engine the shipping default, make every
legacy (redact+reinsert) commit visible to the user, stop paragraph mode from
swallowing sibling table cells, and unblock the main CJK body face of both
corpus documents by parsing array-destination `bfrange` fail-closed.

## Affected modules (from the Understand fan-out, 2026-09-05)

| Item | Files | Anchor |
|---|---|---|
| T16-1 notice | `controller/pdf_controller.py:2321-2366, 2513-2521`; `view/pdf_view.py:2411` (no change) | `_is_notifiable_degrade` delegates to `is_real_fallback_commit`, which deliberately excludes `fallback_chain == ("legacy",)` |
| T16-2 paragraph | `model/text_block_parsing.py:544-634 _build_paragraphs` (primary); `model/text_block.py:152-221` (para-id `_p0` assumption) | no horizontal/column check at all; HVAC page 1 raw block 6 holds 4 cells |
| T16-3 parser | `model/text_commit/cid_fonts.py:412-504` (`b'['` refusal at :460), `:363-396 ToUnicodeMap`, `:398-409 _hex_items` | single choke point; records are `("char", c, c, text)` / `("range", lo, hi, base)` |
| T16-3 flip | `model/text_commit/dto.py:210` AND `:242` (two literals) ; `main.py:93-98,140-145` | `from_env` fallback literal is the one real users hit |
| T16-4 tandem | `model/text_commit/plan.py:1006-1010, 463-521, 581-793, 1190-1204`; `inspect.py:82-96, 798-950`; `patch.py:132-176` | 1:1 binding contract; stroke ink unboundable today |

## Decisions

1. **T16-1 is additive in the Controller.** `is_real_fallback_commit` stays
   untouched (it also gates the redo-reprompt in `edit_commands.py:357`). A
   second condition — `status == DEGRADED_COMMITTED and degraded_reason ==
   "legacy_redact_reinsert"` — fires the same `view.notify_degraded_commit`
   toast with a message naming the legacy engine and the untracked-fidelity
   warning. It also sets `_last_edit_degraded` so the success toast is
   suppressed, matching the real-fallback path. Per commit, not per document:
   consistent with the existing channel and non-blocking (5 s warning toast).
2. **T16-3 parser:** array-destination blocks are exploded into per-code
   `("char", code, code, text)` records at parse time (reuses `decode_cid` /
   `cids_for_char` untouched). Refuse (`TYPE0_TOUNICODE_UNPARSEABLE`, distinct
   `detail` strings) on: element count ≠ `hi-lo+1`, unterminated/nested
   bracket, non-hex element, non-UTF-16BE element, empty element, `hi < lo`.
   Exploded records count against `_MAX_TOUNICODE_RECORDS`. Scalar and array
   blocks may mix in one stream. No new `RejectReason` constant: a malformed
   array *is* unparseable, and the funnel keys on reason codes.
3. **T16-3 flip:** both literals in `dto.py` go to `"tiered"`. Tests named
   `test_default_legacy_*` are rewritten to pass `engine="legacy"` explicitly
   (they keep guarding the legacy path) and a new test pins the kill switch.
   Known behaviour delta: `pdf_model.py:3729` (signed/widget page reject) goes
   live. That is the intended fail-closed behaviour.
4. **T16-2:** fix in `_build_paragraphs`, not the consumer. Within a raw
   block: (a) split a line into cells at a span gap > 2.0 × the larger span's
   font size; (b) group lines/cells into sub-paragraphs by horizontal-range
   overlap (share a column ⇔ x-overlap ≥ 50 % of the narrower); (c) emit
   `_p0, _p1, …` per block. Thresholds are provisional — the implementer
   must keep `test_text_extraction_line_joining.py` and the `_build_paragraphs`
   unit tests green and record the final numbers here.
5. **Serial execution in the main tree** (editable install points at the repo;
   worktrees cannot run the venv suite). Order: T16-1 → T16-3 parser →
   T16-3 flip + latency A/B → T16-2 → docs. T16-4 is designed after the
   first four land.

## Steps

- [x] Understand fan-out (5 readers).
- [ ] T16-1 red → green → adversarial review.
- [ ] T16-3 parser red → green → review; corpus scan before/after
      (`scripts/scan_tounicode_parse.py`, new: counts Type0 fonts whose
      ToUnicode passes `parse_tounicode_strict` per document, code-only output).
- [ ] T16-3 default flip + kill-switch test + same-session latency A/B
      (`scripts/benchmark_engine_default_ab.py`, new).
- [ ] T16-2 red → green → review.
- [ ] PITFALLS / ARCHITECTURE / TODOS; archive this plan.
- [ ] T16-4 design (separate workflow).

## Log

- 2026-09-05: plan written; baseline suite run started.
