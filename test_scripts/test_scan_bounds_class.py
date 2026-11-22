"""Opus round 2 on the routing bounds: A8 (any filter chain), F3 (an over-cap stream is a recorded
resource_limited), F4/F6 (what the child handles or refused is never scanned on the caller thread)."""

from __future__ import annotations

import time
import zlib

import fitz
import pytest

from model import content_scan, pdf_content_ops
from model.pdf_model import PDFModel
from test_scripts.test_native_image_probe import (  # noqa: F401
    IMAGE_POINT,
    SCAN_LIMITED_MSG,
    _controller,
    needs_child,
)
from test_scripts.test_scan_routing_bounds import _distinct_chunks, _page_with_streams, _spy_decodes

BOMB = 64 * 1024 * 1024


@pytest.fixture(autouse=True)
def _clean_cache():
    content_scan.clear_scan_cache()
    yield
    content_scan.clear_scan_cache()


def _chain_bomb_page(kind: str) -> tuple[fitz.Document, int]:
    doc = _page_with_streams([b"0 0 m 1 1 l S\n", b"0 0 m 1 1 l S\n"])
    bomb = int(doc[0].get_contents()[-1])
    zeros = b"\x00" * BOMB
    if kind == "predictor":
        doc.update_stream(bomb, zlib.compress(zeros, 9), compress=0)
        doc.xref_set_key(bomb, "Filter", "/FlateDecode")
        doc.xref_set_key(bomb, "DecodeParms", "<< /Predictor 1 >>")
    else:
        doc.update_stream(bomb, zlib.compress(zlib.compress(zeros, 9), 9), compress=0)
        doc.xref_set_key(bomb, "Filter", "[/FlateDecode /FlateDecode]")
    return doc, bomb


@pytest.mark.parametrize("kind", ["predictor", "double_flate"])
def test_no_filter_chain_is_decoded_unbounded_by_routing_or_discovery(monkeypatch, kind):
    doc, bomb = _chain_bomb_page(kind)
    with doc:
        calls = _spy_decodes(monkeypatch)
        t = time.perf_counter()
        set_key, jobs = pdf_content_ops.page_scan_set(doc, 1)
        pdf_content_ops.discover_native_image_invocations(doc, 1)
        assert bomb not in calls
        assert time.perf_counter() - t < 2.0
        assert all(len(payload) < 1_000_000 for _key, payload in jobs)
        assert len(set_key) == 2


def _save(doc: fitz.Document, tmp_path) -> str:
    path = tmp_path / "t.pdf"
    doc.save(path)
    return str(path)


def _open(path: str) -> PDFModel:
    content_scan.clear_scan_cache()
    model = PDFModel()
    model.open_pdf(path)
    return model


# ---- F3 --------------------------------------------------------------------------------------------

OVER_CAP = b"0.2 w 10 10 m 12 14 l S\n" * 400_000  # 9.6 MB decoded: over STREAM_DECODE_CAP_BYTES


@needs_child
def test_an_honest_over_cap_stream_is_a_recorded_resource_limited(tmp_path):
    with _page_with_streams([OVER_CAP], flate=True) as doc:
        model = _open(_save(doc, tmp_path))
    try:
        jobs, _skip = model.image_scan_lookup(1)
        assert jobs == []
        assert model.image_scan_failed(1) is True
        assert model.image_scan_failure_reason(1) == "resource_limited"
        info = model.get_object_info_at_point(1, IMAGE_POINT, blocking=False)
        assert getattr(info, "object_kind", None) != "native_image", info  # (a pending tables lookup is fine)
    finally:
        model.close()


@needs_child
def test_no_id_of_a_partially_discovered_page_is_offered_by_the_hit_test(tmp_path):
    with _page_with_streams([OVER_CAP, b"0 0 m 1 1 l S\n"], flate=True) as doc:
        model = _open(_save(doc, tmp_path))
    try:
        info = model.get_object_info_at_point(1, IMAGE_POINT, blocking=False)
        assert getattr(info, "object_kind", None) != "native_image", getattr(info, "object_id", info)
    finally:
        model.close()


@needs_child
def test_the_controller_says_why_an_over_cap_page_cannot_edit_images(qapp, tmp_path, monkeypatch):
    from test_scripts.qt_teardown import dispose_pdf_view

    with _page_with_streams([OVER_CAP], flate=True) as doc:
        model = _open(_save(doc, tmp_path))
    view, controller, _stub, log = _controller(qapp, model, monkeypatch)
    try:
        controller.lookup_object_at_point(1, IMAGE_POINT)
        assert controller.object_op_ready([1], ["native_image"]) is False
        assert log.status[-1] == SCAN_LIMITED_MSG
    finally:
        dispose_pdf_view(view, controller, model)


# ---- F4 / F6 ---------------------------------------------------------------------------------------


def _scan_spy(monkeypatch) -> list[int]:
    sizes: list[int] = []
    real = content_scan.scan_stream

    def spy(stream):
        sizes.append(len(stream))
        return real(stream)

    monkeypatch.setattr(pdf_content_ops, "scan_stream", spy)
    return sizes


@needs_child
def test_discovery_on_the_caller_thread_scans_nothing_the_child_handles_or_refused(tmp_path, monkeypatch):
    """The S2 page: 8 streams of 7.2 MB (the page cap lets four be offloaded and refuses the rest)."""
    part = b"0.2 w 10 10 m 12 14 l S\n" * 300_000
    with _page_with_streams([part + f"% {i}\n".encode() for i in range(8)], flate=True) as doc:
        model = _open(_save(doc, tmp_path))
    try:
        _jobs, skip = model.image_scan_lookup(1)
        sizes = _scan_spy(monkeypatch)
        t = time.perf_counter()
        pdf_content_ops.discover_native_image_invocations(model.doc, 1, skip)
        elapsed = time.perf_counter() - t
        assert sum(sizes) < 200_000, sizes
        assert elapsed < 1.0
    finally:
        model.close()


def test_a_cached_stream_counts_toward_the_page_bound_like_an_uncached_one(monkeypatch):
    """The reviewer's S2 sequence: the child answered the offloaded streams, the page set was walked
    again (the answered streams are now alias hits), and discovery runs with no skip.  The page bound
    must not depend on what is cached: the excess streams are still never decoded or scanned."""
    part = b"0.2 w 10 10 m 12 14 l S\n" * 300_000
    with _page_with_streams([part + f"% {i}\n".encode() for i in range(8)], flate=True) as doc:
        _key, jobs = pdf_content_ops.page_scan_set(doc, 1)
        assert len(jobs) == 4
        for key, payload in jobs:
            content_scan.store_scan(key, content_scan.scan_stream(payload))
        pdf_content_ops.page_scan_set(doc, 1)  # a second walk: aliases of the answered streams are stored
        again = pdf_content_ops.PageScanSet(doc, 1)
        assert again.jobs == [] and len(again.limited_keys) == 4  # the same four limited as before the answers
        sizes = _scan_spy(monkeypatch)
        pdf_content_ops.discover_native_image_invocations(doc, 1)
        assert sizes == [], sizes


@needs_child
def test_after_a_child_failure_no_offloaded_stream_is_scanned_on_the_caller_thread(tmp_path, monkeypatch):
    """32 streams of 126 KB are each under the inline limit but offloaded as a page; a failure skips them all."""
    with _page_with_streams(_distinct_chunks(4_000_000, 32)) as doc:
        model = _open(_save(doc, tmp_path))
    try:
        offloaded = model.image_scan_lookup(1)[0]
        assert len(offloaded) == 32
        model.mark_image_scan_failed(1, model.image_scan_set_key(1), "crashed")
        jobs, skip = model.image_scan_lookup(1)
        assert jobs == []
        sizes = _scan_spy(monkeypatch)
        pdf_content_ops.discover_native_image_invocations(model.doc, 1, skip)
        assert sum(sizes) == 0, sizes
    finally:
        model.close()
