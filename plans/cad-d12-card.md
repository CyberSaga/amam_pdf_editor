# Card D12 (Opus design, 2026-11-20): a page's scans are admitted as one set; scan failures are scoped; stale-tables status (C); delete-after-stale outcome test

Owner ruling (handoff, D12): the scans a page needs are admitted to the cache as one set; if they do not fit, the job ends `resource_limited`; failures are scoped to the document generation and the page frame. Also from the D1 review: C (status stays after a stale drop) and the unwritten outcome test.

## Current-state block
- D12..D10 built; A5 review done; waiting owner rulings (images off Windows; commit with Accept not met). Nothing committed. Q1 default withdrawn after review: failure key is the owner's literal `(handle_generation, page, set_key)`.

## 1. Defect today (A5 tree)
- `content_scan._cache`: OrderedDict, cap `SCAN_CACHE_MAX_RECORDS = 200_000` DoRecord rows. `store_scan` evicts from the LRU front while over cap and `len > 1`, so a set whose scans together exceed the cap evicts its own siblings: the resolve re-looks-up, finds a sibling missing, requests another child job, forever, while the status says "此頁影像分析完成".
- `_failed_keys` is process-wide, keyed on stream content only, unbounded, never cleared in production; `_alias` is unbounded.
- `_on_object_probe_failed` ignores the kind, so scan failures say 表格.
- C: a stale tables answer returns silently (coordinator `_on_finished` / `_on_failed` stale branches), so the pending status stays.

## 2. Design
- **Set.** `set_key` = ordered tuple of distinct content keys of every stream discovery reads on the page (contents + image-bearing Forms, short included). New `pdf_content_ops.page_scan_set(doc, page_num) -> (set_key, missing_long)`; `image_scan_jobs` becomes its second half.
- **Size.** Sum of `max(1, len(scan.dos))` over all members (cached ones included). Cap unchanged.
- **Admission chokepoint** `content_scan.admit_set(members: dict[bytes, StreamScan]) -> bool`: total over cap -> store nothing, evict nothing, return False. Else move cached members to MRU, insert new ones, evict from the front (never reaches a member). The "kept alone" branch is removed (replaces A5 judgement call, handoff line 444).
- **Store sites.** coordinator answer -> `model.admit_image_scan_set(frame, answered)`; discovery (pdf_content_ops inline stores) collects and admits once; derived stores after an edit (pdf_object_ops) use `store_scan(key, scan, keep=<page's other set keys>)`, eviction skips `keep`.
- **resource_limited** (child `MemoryError`, or admission refused): mark scoped failure, no retry, cache nothing, emit `probe_failed("scan", page, "resource_limited")`; controller drops the pending click. `_on_object_probe_failed` branches on kind. Wording (D11): resource_limited "此頁內容過多，影像分析超出上限而未完成；此頁的影像目前無法選取或編輯（其他物件不受影響）"; no_headroom "目前可用記憶體不足，暫時無法分析此頁的影像，請稍後再操作一次". `no_headroom` is transient and is NOT marked as a failure.
- **Failure scope (D12 literal; the Q1 default is withdrawn after the A5 review).** Key `(handle_generation, page_num, set_key)`, LRU `MAX_FAILED_SETS = 256` in `content_scan._failed_sets` (OrderedDict; value = the recorded status; API `mark_set_failed`, `set_failed`, `failure_reason`; stdlib only). A failure may be transient (child MemoryError, ledger refusal, crash), so it is no fact about the bytes: the same bytes in another document are retried, and Save As (a new generation) retries once. Different stream bytes are never covered. `retire_failed_sets(live_generations)` drops the entries of dead handles (called wherever `table_objects.retire_dead_handles` is). `no_headroom` stays unmarked. Removed: `_failed_keys`, `mark_scan_failed`, `scan_failed`. A refusal on a failed page names a cause only from the recorded status: `_SCAN_LIMITED_TEXT` for `resource_limited`, the neutral text otherwise (D2).
- **Job frame.** `Job.frame = (page, set_key)` set at request; `job.key` stays the missing keys. On an answer the frame is current only if the page's `set_key` is unchanged. Current+complete: admit; True -> `image_scan_ready`; False -> mark + `resource_limited`; a long member evicted meanwhile (neither answered nor cached) -> admit what is there, emit ready (the resolve requests the rest). Current+typed failure/second crash: mark, emit `probe_failed`. Not current+complete: admit the answered scans as their own set if they fit (valid content); no mark, no ready. Not current+failure: drop, no mark, no message (class of the D1 late-failure bug). Both not-current cases emit `probe_dropped`.
- **Skip into discovery.** `PDFModel.image_scan_jobs` and the discovery call in `get_object_info_at_point` pass `skip: frozenset[bytes]` (members of a failed current frame) down; `pdf_content_ops` stays model-free.
- **object_op_ready.** An image/native_image edit on a page whose frame is failed is refused with the scan failure message.

## 3. C fix
Coordinator: `probe_dropped = Signal(str, int)`; `has_pending(kind)`; stale branches call `self._drop(job)` which emits `probe_dropped(kind, page)`. Controller `_on_object_probe_dropped(kind, page)` (wired in `activate()`): if `not has_pending(kind)` and the current status is one of that kind's pending texts -> `_set_object_status(None)` and `drop_pending_object_click()` (Q3 default: yes). Pending texts become module constants. Failure/ready messages are never cleared.

## 4. Tests (red first; names are outcomes)
Fixtures: `_long_image_pdf`, new `_two_long_streams_pdf` (two long streams each with a `Do`), `StubRunner`, `_coordinator`, `_controller`, `_force_id_collision`, `_make_annotated_pdf`, `_make_other_pdf`; cap via `monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", n)`.
- T1 over_cap_set_stores_nothing_and_ends_resource_limited (other page's entry still hits; `image_scan_ready` not emitted).
- T2 answered_click_on_over_cap_page_starts_no_second_job (controller; `runner.order` length 1; scan resource_limited text; click dropped; READY never shown). Expected red today.
- T3 single_scan_over_cap_is_refused_not_kept_alone.
- T4 fitting_set_evicts_other_pages_never_its_own_members.
- T5 short_inline_store_never_evicts_a_long_sibling.
- T6 derived_store_after_edit_never_evicts_a_sibling.
- T7 failure scope: (a) same bytes in document B are retried (a job); (b) Save As (new generation) retries once, then is failed again; (c) changed page content not covered; (d) last `close_session` empties `_failed_sets`; (e) 257 marks evict the oldest; (f) `no_headroom` is not marked.
- T8 late_failure_for_a_changed_frame_is_dropped (typed, crash x2).
- T9 op_on_failed_image_page_is_refused_with_the_scan_message.
- T10 scan_messages_name_images.
- T11 stale_tables_answer_clears_pending_status_when_no_tables_job_pending (complete, each typed failure, crash; both pending texts).
- T12 keeps_status_while_a_newer_tables_job_is_pending.
- T13 never_clears_a_non_pending_status.
- T14 delete_after_a_stale_table_answer_leaves_b_bytes_unchanged (test_table_probe_non_mutation.py): A has a table, lookup pending, close A, open B with `_force_id_collision`, deliver A's complete answer; click B, delete; also a forged A object_id on B before/after B's answer. Assert sha256 of B's `tobytes(no_new_id=True)` one-page copy and page text unchanged. Passes at HEAD (D1 fixed the bug); show red by making `_is_stale` return False and record it in the log.
Rewrite to outcomes: test_native_image_probe.py (marks of key -> frame), test_content_scan.py:318.

## 5. Files
Touch: model/content_scan.py, model/pdf_content_ops.py, model/pdf_model.py, model/pdf_object_ops.py, controller/object_probe_coordinator.py, controller/pdf_controller.py, the tests above, docs/ARCHITECTURE.md (content_scan entry A5 owes + admission + scope), PITFALLS entry + index regen ("storing a page's scans one at a time into an LRU evicts siblings, so the resolve loops"), TODOS (`_alias` unbounded: Q4 default = TODOS).
Do not touch: model/table_objects.py keys/stores, helper_main.py, runner `_STATUSES`/`_parse`, view/.

## 6. Resolved defaults (owner may overrule)
Q1 withdrawn: the key includes the handle generation (section 2). Q2 wording above. Q3 yes. Q4 TODOS. Unverified: whether the CAD sample's page set fits the cap (measure the record sum in acceptance).
