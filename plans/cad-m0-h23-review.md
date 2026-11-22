# H23 Codex review of M0 (A1 to A6), 2026-11-22

Reviewer: Codex (gpt-6-astra, high, read-only), three scopes at HEAD 7a68c2cb. Adjudication below is the main session's;
every finding is ACCEPTED (reproduced by Codex in memory or traced in source) and OPEN: none is fixed yet.
Status: A1-A4 and A6 reviews complete. A5 review was cut by the Codex usage limit (resets 1:58 PM local) after four
partial findings; it must be re-run.

## A1-A4 (3 findings, all P2)
1. Table answer fields are not validated (controller/object_probe_coordinator.py:307): rect of length 3, NaN, a 401-digit
   coordinate (OverflowError, no terminal signal). Class: untrusted child answer (A6 test_text_answer_untrusted covers the
   text kind only). Close: the 392-case mutation test, extended to every table-answer field.
2. A newer right or middle press does not invalidate a pending object click (view/pdf_view.py:4578; only left presses
   advance the generation). Class: stale press replay (A6.5 closed it for text). Close: pending click then each press type
   must leave the selection unchanged; scroll and zoom exceptions kept.
3. CAD acceptance counts a failed analysis as success (test_scripts/test_cad_sample_click.py:123, gui_stall_probe.py:37;
   only no_headroom rejected). Class: completion mistaken for success. Close: inject each failure status per gesture.

## A5 (partial, reproduced in memory before the limit)
4. A forged span deletes the image's Do operator (writer trusts the child's span).
5. An Infinity field leaves a scan job with no terminal signal.
6. An honest 200,001-record scan answer costs 333 ms to parse and reject in the parent.
7. Occurrence index differs between the partial discovery (skip set) and the writer's lookup: with a skipped stream,
   object_id native_image:1:0 names the second image in the hit and the first in the writer
   (model/pdf_object_ops.py _find_native_image_invocation vs model/pdf_content_ops.py occurrence_index).
Re-run the A5 review after the quota returns; findings 4-7 are not complete.

## A6 (4 findings)
8. P1 OCProperties carry expands a shared reference graph exponentially (model/table_objects.py:223, no memo or budget).
9. P2 Routing fully decompresses streams before the size limit (model/text_index_jobs.py:75).
10. P2 Malformed child stdout floods GUI logging, one warning per line (controller/object_probe_runner.py:225).
11. P2 Mode-entry acceptance passes on a failed or dropped text signal (test_gui_stall.py:136, test_cad_sample_click.py:104).

## Recurrence
Rounds on the same mechanism: this is the first H23 round. Classes seen again: (a) untrusted child answer not validated
field by field (1, 5, 6, 10), (b) input amplification on the GUI thread before containment (6, 8, 9, 10), (c) completion or
done-signal accepted as success in the stall harness (3, 11), (d) stale input replay not tied to the newest press (2).
One outcome check per class: (a) one mutation test over every field of every child answer kind, (b) one budget test that
feeds each parent-side parser a compact amplifying input and bounds time and memory, (c) one injection test over every
failure status of every watch, (d) one test over every press type for every pending click kind.

## Fix status (2026-11-22)
Fixed in the working tree and reviewed by Opus (plan-code-reviewer, ship-with-fixes, fixes applied): 1 (table answer validation,
test_table_answer_untrusted.py), 2 (any newer press, plus the interaction-epoch filter bumps the pending object click on any
mouse press or key press, wheel and zoom excluded), 3 and 11 (acceptance helpers in gui_stall_probe.py, settle predicate
that keeps waiting on a stale dropped signal), 9 (routing never calls xref_stream: single plain Flate decoded with a cap,
every other filter chain routes to the child), 10 (stdout parse stops after 32 rejected lines, 3 warnings and one summary).
Finding 8 fixed earlier (33ea7985). Astra review of all of these is owed (quota). Open: A5 findings 4 to 7 (review to re-run).
Opus's open notes: U2 a bomb the child answers resource_limited is marked failed and routes inline at the next gesture;
U3 a finite absurd rect (1e308) passes the table-answer validation; tables/scan answer lines have no byte cap (32 huge lines).
