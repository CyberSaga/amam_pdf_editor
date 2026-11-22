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

## Astra round (2026-11-22, quota restored; one review at a time at the owner's request)
Astra reviewed the H23 fixes, B1 completion plus item 5, and re-ran the A5 review. All findings below are ACCEPTED and OPEN
unless marked fixed.

### H23 fixes (33ea7985, 7ca27888): 2 x P2
H1. OCProperties root bypasses both budgets (model/table_objects.py:250): the root is rewritten without being charged and
    mapped OCG references return before accounting; a 3,595-byte PDF produced 1,800,056 characters (cap 262,144) in 220 ms.
    Class: input amplification before containment. Closure check: compact oversized configurations through a direct and an
    indirect root must be refused in bounded time and memory.
H2. Click acceptance still hides failed text analysis (test_scripts/gui_stall_probe.py:133): for a gesture that requests both
    analyses, tables=ready with text=analysis_failed gives done=True and acceptance success. Class: completion mistaken for
    success. Closure check: inject every text failure and drop alongside table success through each combined gesture's real
    acceptance path.

### B1 completion plus item 5: 2 x P1, 3 x P2
B1. P1 O-scan accepts wrong rectangle geometry (test_scripts/vector_oracle_scan.py:113): corner sets are compared separately,
    so four edges replaced by diagonals pass. Class: lossy oracle comparison. Check: enumerate wrong corner connections.
B2. P1 the sweep does not enforce every must-kill cell (test_vector_oracle_mutation_sweep.py:396): a survivor is recorded only
    when O-rebuild accepts, the other oracles need five aggregate kills; a probe that suppressed one genuine O-struct
    rejection still passed. Check: suppress any single established must-kill cell and require the run to fail.
B3. P2 O-flat accepts NaN geometry (vector_oracle_flat.py:113). Check: NaN and +/-inf in every coordinate position rejected.
B4. P2 D23 reads PDF string contents as references (commit_state.py:231): `/Note (9999 0 R)` records a dangling reference.
    Check: compare recorded references with a typed object walk across strings, names, arrays, dictionaries.
B5. P2 the vendor matcher bypasses H7's edge cap (vector_matching.py:137): 71 identical records give 5,041 edges, match_multisets
    raises AmbiguousFixture while unmatched() accepts. Check: the same over-cap outcome check through both entry points.

### A5 re-review (7c8710fa..2a842bf3): confirms 4 to 7, two new
A4. P1 forged span turns a move into image deletion (model/pdf_object_ops.py:433): the child's cm_span is used without
    verification; extending it through Do made move_object() return True and the image stayed missing after save and reopen.
A5. P2 Infinity in a scan field: OverflowError escapes (model/content_scan.py:496, controller/object_probe_coordinator.py:428),
    the job is consumed with no terminal signal.
A6. P2 over-budget answer: every record is built before the limit check (coordinator.py:425), 206 ms for 200,001 records.
A7. P2 partial discovery and the writer lookup number occurrences differently (pdf_content_ops.py:546, pdf_object_ops.py:328);
    the controller blocks edits while the scan failure is recorded, so UI corruption is not established.
A8. P2 new: scan routing fully decompresses streams in the parent (pdf_content_ops.py:398): 8,200 stored bytes gave an
    8,388,644-byte parent payload.
A9. P2 new: many short streams bypass offloading collectively (pdf_content_ops.py:410, :337): 32 streams of about 126 KB gave
    zero child jobs and 445 ms.
Classes: unvalidated child data (A4, A5, A6, and table answers before), amplification before containment (H1, A6, A8, A9),
completion as success (H2), lossy or aggregate-only oracle judgement (B1, B2, B3, B5), positional identity (A7).

### Fix status of the Astra round (2026-11-22, evening; Opus reviewed once, a second Opus pass and the Astra re-review are OWED: both reviewers hit quota)
Fixed in the working tree, each with an outcome-check test: H1 (every emitted OC piece charged, root included), H2 (combined acceptance
requires text None or ready), B1 (rectangle rows compared by edge sequence, 20,735 wrong traversals rejected), B2 (must-kill derived
from facts with an independent reader, sweep fails when any single oracle hides one genuine rejection), B3 (non-finite O-flat input), B4
(strings, hex strings and comments masked before the dangling scan), B5 (edge cap in unmatched), A4 (the writer lexes the stream in the
parent and never trusts a child offset; outcome sweep over every span field at every byte position), A5 (every scan field validated, one
terminal outcome), A6 (count checked before conversion, stdout cap ANSWER_MAX_BYTES 64 MiB for every kind), A7 (ids from a partially
discovered set are refused and never offered), A8 (only no filter or up to 4 Flate stages are decoded, with a cap; everything else is over
the cap), A9 (offload decision on the page total; discovery skip set covers every offloaded or over-cap stream).
Behaviour changes the OWNER should rule on: (a) honest ASCII85 or LZW content streams, and any page with a decoded content stream over
8 MiB, now make the page resource_limited (image objects on it are blocked with the limited-scan message) instead of scanning in the child;
(b) after a child scan failure, images in the short streams are no longer selectable (their ids would be partial); (c) every image
mutation lexes the whole stream in the parent (about 0.4 s for 7 MB, not measured on the GUI thread); (d) O-vendor keeps the 0.3 pt
tolerance, so a 1e-6 number change is allowlisted as equivalent.
Opus residual notes: C1 charges count the same text two or three times, so the effective OC cap is about a third of 262,144 characters.

### Parent lex moved off the GUI thread (owner approved 2026-11-22)
Measured first: the parent lex costs about 150 ms per MB (1 MB 150 ms, 7 MB 1,055 ms, the CAD sample page's 31 MB stream 3.7 s), over the 100 ms
standard above about 0.7 MB. Now: a verified-scan cache (content key to a parent-lexed scan), a controller-layer `ScanVerifier` (one QThread
worker, started 150 ms after the request, bounded by the stream and page decode caps, results dropped when the page, handle generation or
key changed) schedules the lex after a child scan answer; at mutation time a verified scan costs no lex, an unverified stream up to 256 KiB
is lexed inline, a larger one is refused with the new ObjectOpRefusal.ANALYSING message ("retry in a few seconds") and queued. Measured on a
7 MB page after verification: move 107 to 143 ms, delete 170 to 189 ms on the calling thread, zero lex calls (the lex alone was 1,055 ms);
GUI heartbeat gap during the verification 62 to 65 ms. Residual over the 100 ms standard: decode (3 x 17 ms), zlib level 1 (51 ms) and
content-key hashes (23 ms) of a delete on a 7 MB stream, work that predates this change (owner item: fewer decodes and hashes per delete).
Corpus census (test_files, 4,422 PDFs, 8,330 pages): content-stream filters Flate 6,267, none 3,316, LZW 124 (in 17 files, nearly all pdf.js
edge-case fixtures), ASCII85 about 13: pages with non-Flate content filters are under 0.5 percent; they now make the page resource_limited
for image editing only (text, lines and tables are unaffected). Owner ruled: O-vendor keeps 0.3 pt.

### Astra round 4 (reviewed 5789848d plus the verifier work; 3 x P2, OPEN)
R1. Worker lifetime: ScanVerifier.cancel_all only marks work cancelled and main.py can quit with the QThread still running
    (controller/scan_verifier.py:97, main.py:492); the cancellation test cancels before the delayed start. Check: close the app
    during active lexing and require worker completion before teardown.
R2. Byte limits do not bound lexing work: model/content_scan.py:179 visits every enclosing q for every Do (quadratic; 40,000 bytes with
    4,000 nested scopes and 4,000 invocations took 454 ms), inline discovery and writer verification are exposed. Check: vary nesting
    and invocation density independently; bounded inline latency and bounded or cancellable background work.
R3. Valid Flate chains are resource-limited: pdf_content_ops.py:364 splits filter names on whitespace, MuPDF returns
    [/FlateDecode/FlateDecode]. Check: valid small chains decode, oversized chains stay bounded (tests must distinguish).
Opus extra (manual-switch design review): at pdf_content_ops.py ~374 a zlib error falls through to an uncapped MuPDF decode.
Opus card proposal (owner to decide): card A, automatic bounds for ASCIIHex/ASCII85/RunLength (fixed worst-case blow-up) with no button;
card B, a manual per-page analyse switch for resource_limited pages (preference default hidden, no preferences dialog exists yet, approval
session-only keyed by content key, finite measured ceilings, child memory cap, timeout, cancel), after the Astra round.

### Astra round 5 and 6: worker lifetime at exit (THIRD consecutive round on one mechanism: STOP, owner decision needed)
Round 5 (on R1): main.py ignored shutdown_background()==False; the retiring primary's worker was never joined on promotion; the
source-grep pin could not fail. Class fix applied (controller/worker_registry.py: one registry drained by teardown, per-pass latch,
retire() on promotion/release, outcome tests with real objects). Round 6 on that class fix, all ACCEPTED and OPEN:
W1. P1 timeout survivors still reach exit: main.py:522 logs survivors then finish_owned_shutdown() quits; synchronous aboutToQuit
    re-entry hits the draining flag and skips the second pass; nothing keeps the event loop alive until the worker finishes.
W2. P2 worker_registry.py:53 unregisters a worker whose shutdown raised ANY RuntimeError (only a deleted Qt object means done).
W3. P2 main.py:297 attaches release_context to `destroyed` only; secondary editor windows are hidden on close (no WA_DeleteOnClose),
    so retirement never runs on an ordinary secondary close.
W4. P2 search and OCR coordinators (search_coordinator.py:186, ocr_coordinator.py:212) cancel without joining and are not in the
    registry; render, thumbnail, preview, print and optimize are defensible because existing close guards join or defer the close.
W5. P3 the tests replace quit() with a no-op and invoke a second pass by hand (test_scan_verifier_shutdown.py:332), and the promotion
    test permits natural completion before teardown.
Recurrence: round 4 (R1 worker lifetime), round 5 (retire, join, grep pin), round 6 (this). Class: a background worker's lifetime
has no single owner that decides when the process may exit. Single check that would close it: an end-to-end test that quits with a worker
held past the deadline and asserts the process does not exit (or exits only after the worker finished), for ScanVerifier and for every
thread-owning coordinator. The fix is an application-level shutdown design (a quit gate that stays closed until the registry is empty,
a registry for all QThread-owning coordinators, window-close hooks on close not destroyed), not another patch of the verifier.
Owner decisions: scope (verifier only, or all thread-owning coordinators incl. search/OCR), whether exit may wait (how long) or
force-terminate, and whether this card is worth doing before B2.
