"""Security patch P1 (finding F1): PDF resource guards.

Untrusted PDFs are parsed/rasterized with no bound on file size, page count, or
page dimensions, allowing memory/CPU exhaustion (CWE-400 / CWE-409). These tests
cover the two helpers (`_guard_before_open`, `_safe_render_scale`) directly and
the two `open_pdf` guards via integration with the real parser (constants are
monkeypatched down so a tiny real PDF trips them — no giant fixtures needed).
"""

from __future__ import annotations

import math
import re

import fitz
import pytest

import model.pdf_model as pdf_model
from model.pdf_model import PDFModel, _guard_before_open, _safe_render_scale


# --- _guard_before_open -----------------------------------------------------

class _FakeStat:
    def __init__(self, size: int) -> None:
        self.st_size = size


class _FakePath:
    def __init__(self, size: int) -> None:
        self._size = size

    def stat(self) -> _FakeStat:
        return _FakeStat(self._size)


def test_guard_before_open_rejects_oversize() -> None:
    with pytest.raises(ValueError):
        _guard_before_open(_FakePath(pdf_model._MAX_PDF_BYTES + 1))


def test_guard_before_open_allows_normal_size() -> None:
    # Returns None without raising.
    assert _guard_before_open(_FakePath(1024)) is None


# --- _safe_render_scale -----------------------------------------------------

class _FakeRect:
    def __init__(self, w: float, h: float) -> None:
        self.width = w
        self.height = h


class _FakePage:
    def __init__(self, w: float, h: float) -> None:
        self.rect = _FakeRect(w, h)


def test_safe_render_scale_clamps_huge_page() -> None:
    # 10000x10000 at scale 2.0 -> 4e8 px, way over the cap. Expected ceiling is
    # sqrt(40e6 / 1e8) ~= 0.632.
    out = _safe_render_scale(_FakePage(10_000, 10_000), 2.0)
    expected_ceiling = math.sqrt(pdf_model._MAX_PIXMAP_PX / 1e8)
    assert out <= expected_ceiling + 1e-9
    assert out > 0.1  # not floored for this size


def test_safe_render_scale_leaves_normal_page_untouched() -> None:
    # A4 at scale 2.0 -> ~2M px, well under the cap; scale must be unchanged.
    assert _safe_render_scale(_FakePage(595, 842), 2.0) == 2.0


def test_safe_render_scale_floors_at_min() -> None:
    # An extreme page bottoms out at the 0.1 floor (documented tradeoff).
    assert _safe_render_scale(_FakePage(1_000_000, 1_000_000), 2.0) == 0.1


# --- open_pdf integration ---------------------------------------------------

def _make_pdf(path, pages: int = 1):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=200, height=200)
    doc.save(str(path))
    doc.close()
    return path


def _track_fitz_opens(monkeypatch) -> list[fitz.Document]:
    """Route the model's ``fitz.open`` through a spy; returns the handles it hands out."""
    opened: list[fitz.Document] = []
    real_open = fitz.open

    def _tracking_open(*args, **kwargs):
        doc = real_open(*args, **kwargs)
        opened.append(doc)
        return doc

    monkeypatch.setattr(pdf_model.fitz, "open", _tracking_open)
    return opened


def test_open_pdf_rejects_oversize_before_parsing(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path / "tiny.pdf")
    # Force the size guard to trip on a tiny real file, and prove fitz.open is
    # never reached (the guard fires first).
    monkeypatch.setattr(pdf_model, "_MAX_PDF_BYTES", 0)
    opened = _track_fitz_opens(monkeypatch)

    model = PDFModel()
    try:
        with pytest.raises(Exception) as exc:
            model.open_pdf(str(pdf))
        assert "size limit" in str(exc.value)
        assert opened == []  # parser never invoked
        assert model.get_active_session_id() is None
    finally:
        model.close()


def test_open_pdf_rejects_excess_page_count(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path / "tiny.pdf", pages=1)
    monkeypatch.setattr(pdf_model, "_MAX_PAGES", 0)  # 1-page doc now exceeds

    model = PDFModel()
    try:
        with pytest.raises(Exception) as exc:
            model.open_pdf(str(pdf))
        assert "page limit" in str(exc.value)
        assert model.get_active_session_id() is None
    finally:
        model.close()


def test_open_pdf_allows_normal_document(tmp_path) -> None:
    # Regression guard: a normal small PDF still opens under default limits.
    pdf = _make_pdf(tmp_path / "ok.pdf", pages=3)
    model = PDFModel()
    try:
        sid = model.open_pdf(str(pdf))
        assert sid
        assert model.get_active_session_id() == sid
        assert len(model.doc) == 3
    finally:
        model.close()


# --- _guard_foreign_doc (Phase 2.3 chokepoint) -------------------------------
#
# Foreign PDFs (merge/insert sources) must pass the same resource guards as the
# primary open path: size limit, page limit, and an encryption check. Accessed
# via the module attribute so these tests fail (AttributeError) until the
# helper exists — that is the red-light signal.


def test_guard_foreign_doc_rejects_oversize(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path / "src.pdf")
    monkeypatch.setattr(pdf_model, "_MAX_PDF_BYTES", 0)
    with pytest.raises(ValueError) as exc:
        pdf_model._guard_foreign_doc(pdf)
    assert "size limit" in str(exc.value)


def test_guard_foreign_doc_rejects_excess_pages(tmp_path, monkeypatch) -> None:
    pdf = _make_pdf(tmp_path / "src.pdf", pages=2)
    monkeypatch.setattr(pdf_model, "_MAX_PAGES", 0)
    with pytest.raises(ValueError) as exc:
        pdf_model._guard_foreign_doc(pdf)
    assert "page limit" in str(exc.value)


def test_guard_foreign_doc_allows_normal_pdf(tmp_path) -> None:
    pdf = _make_pdf(tmp_path / "src.pdf", pages=2)
    doc = pdf_model._guard_foreign_doc(pdf)
    try:
        assert doc.page_count == 2
    finally:
        doc.close()


def test_insert_pages_from_file_rejects_oversize_source(tmp_path, monkeypatch) -> None:
    base = _make_pdf(tmp_path / "base.pdf", pages=2)
    src = _make_pdf(tmp_path / "src.pdf", pages=1)
    model = PDFModel()
    try:
        model.open_pdf(str(base))
        monkeypatch.setattr(pdf_model, "_MAX_PDF_BYTES", 0)
        with pytest.raises((ValueError, RuntimeError)) as exc:
            model.insert_pages_from_file(str(src), [1], 1)
        assert "size limit" in str(exc.value)
        assert len(model.doc) == 2  # base document untouched
    finally:
        model.close()


def test_insert_pages_from_file_respects_post_merge_invariant(tmp_path, monkeypatch) -> None:
    base = _make_pdf(tmp_path / "base.pdf", pages=3)
    src = _make_pdf(tmp_path / "src.pdf", pages=3)
    model = PDFModel()
    try:
        model.open_pdf(str(base))
        monkeypatch.setattr(pdf_model, "_MAX_PAGES", 4)  # 3 existing + 3 source > 4
        with pytest.raises((ValueError, RuntimeError)) as exc:
            model.insert_pages_from_file(str(src), [1, 2, 3], 1)
        assert "page limit" in str(exc.value)
        assert len(model.doc) == 3  # nothing was inserted
    finally:
        model.close()


def test_insert_pages_from_file_returns_contiguous_positions(tmp_path) -> None:
    # Regression guard for the batched insert: non-contiguous source pages
    # still land as one contiguous run at the insert position.
    base = _make_pdf(tmp_path / "base.pdf", pages=2)
    src = _make_pdf(tmp_path / "src.pdf", pages=5)
    model = PDFModel()
    try:
        model.open_pdf(str(base))
        inserted = model.insert_pages_from_file(str(src), [1, 2, 4], 2)
        assert inserted == [2, 3, 4]
        assert len(model.doc) == 5
    finally:
        model.close()


def _encrypted_pdf(path, user_pw: str = "secret"):
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw=user_pw,
        owner_pw=user_pw + "-owner",
    )
    doc.close()
    return path


def test_guard_foreign_doc_authenticates_encrypted_source(tmp_path) -> None:
    src = tmp_path / "encrypted.pdf"
    _encrypted_pdf(src, "secret")

    with pytest.raises(RuntimeError) as needs_pw:
        pdf_model._guard_foreign_doc(src, password=None)
    assert "encrypted" in str(needs_pw.value).lower() or "需要密碼" in str(needs_pw.value)

    with pytest.raises(RuntimeError) as wrong_pw:
        pdf_model._guard_foreign_doc(src, password="wrong")
    assert "密碼驗證失敗" in str(wrong_pw.value) or "authenticate" in str(wrong_pw.value)

    doc = pdf_model._guard_foreign_doc(src, password="secret")
    try:
        assert doc.page_count == 1
    finally:
        doc.close()


def test_insert_pages_from_file_accepts_encrypted_source_password(tmp_path) -> None:
    base = _make_pdf(tmp_path / "base.pdf", pages=1)
    src = tmp_path / "encrypted-source.pdf"
    _encrypted_pdf(src, "secret")

    model = PDFModel()
    try:
        model.open_pdf(str(base))
        inserted = model.insert_pages_from_file(str(src), [1], 2, password="secret")
        assert inserted == [2]
        assert len(model.doc) == 2
    finally:
        model.close()


# --- render_page_pixmap central clamp (F1 follow-up, fixed Phase 2.1) --------
#
# ToolManager.render_page_pixmap is the central raster chokepoint; it now clamps
# the requested scale via _safe_render_scale so the interactive zoom path
# (set_scale -> PDFModel.get_page_pixmap -> render_page_pixmap) is bounded even
# for a page that clears the open-time size/page guards but carries an outsized
# MediaBox. get_pixmap is mocked so the effective scale is captured WITHOUT
# allocating the pixmap an unclamped path would build.


def test_render_page_pixmap_clamps_oversized_scale(tmp_path, monkeypatch) -> None:
    big = tmp_path / "huge_page.pdf"
    doc = fitz.open()
    doc.new_page(width=10_000, height=10_000)  # 1e8 px at scale 1.0, well over 40 MP
    doc.save(str(big))
    doc.close()

    model = PDFModel()
    try:
        model.open_pdf(str(big))
        rect = model.doc[0].rect
        w, h = rect.width, rect.height
        # Sanity: the page really is oversized at the requested scale.
        assert w * h * 2.0 * 2.0 > pdf_model._MAX_PIXMAP_PX

        captured: dict[str, float | None] = {}

        def _capture_get_pixmap(self, *args, matrix=None, **kwargs):
            captured["scale"] = matrix.a if matrix is not None else None
            return object()  # dummy; the return value is not under test

        monkeypatch.setattr(fitz.Page, "get_pixmap", _capture_get_pixmap)

        model.tools.render_page_pixmap(1, scale=2.0)

        eff = captured["scale"]
        assert eff is not None, "render_page_pixmap did not reach get_pixmap"
        # The chokepoint must clamp so the rendered pixmap stays under the cap.
        assert w * h * eff * eff <= pdf_model._MAX_PIXMAP_PX * 1.01
    finally:
        model.close()


# --- H10-3: a file MuPDF reads as 0 pages must be refused, never substituted --
#
# A malformed ``/Prev`` loop makes MuPDF report ``page_count == 0`` without
# repairing, while other readers still see every page. ``open_pdf`` used to
# install a blank in-memory page; Ctrl+S then replaced the real file with it.


def _prev_loop_pdf(path):
    """Two text pages plus one incremental revision whose /Prev points at itself."""
    doc = fitz.open()
    for label in ("page one", "page two"):
        doc.new_page(width=200, height=200).insert_text((20, 50), label)
    doc.save(str(path))
    doc.close()
    doc = fitz.open(str(path))
    doc.set_metadata({"title": "rev2"})
    doc.saveIncr()
    doc.close()
    data = path.read_bytes()
    last_startxref = [int(m.group(1)) for m in re.finditer(rb"startxref\s+(\d+)", data)][-1]
    trailer_at = data.rfind(b"trailer")
    prev = re.compile(rb"/Prev\s+(\d+)").search(data, trailer_at)
    assert prev is not None
    path.write_bytes(
        data[: prev.start(1)] + str(last_startxref).encode() + data[prev.end(1):]
    )
    probe = fitz.open(str(path))
    try:
        assert probe.page_count == 0, "fixture must make MuPDF read zero pages"
    finally:
        probe.close()
    return path


def test_open_pdf_refuses_a_zero_page_file_instead_of_substituting_a_blank(tmp_path) -> None:
    pdf = _prev_loop_pdf(tmp_path / "loop.pdf")
    original = pdf.read_bytes()
    model = PDFModel()
    try:
        with pytest.raises(RuntimeError) as exc:
            model.open_pdf(str(pdf))
        assert "0" in str(exc.value) or "頁" in str(exc.value)
        assert model.get_active_session_id() is None
        assert model.doc is None
        assert not model.has_unsaved_changes()
    finally:
        model.close()
    assert pdf.read_bytes() == original


def test_open_pdf_zero_page_refusal_keeps_the_already_open_session(tmp_path) -> None:
    good = _make_pdf(tmp_path / "good.pdf", pages=2)
    pdf = _prev_loop_pdf(tmp_path / "loop.pdf")
    model = PDFModel()
    try:
        sid = model.open_pdf(str(good))
        with pytest.raises(RuntimeError):
            model.open_pdf(str(pdf), append=True)
        assert model.get_active_session_id() == sid
        assert len(model.doc) == 2
    finally:
        model.close()


# --- F11-OPEN-5: a failed replace-open must not destroy the open sessions ----


def _corrupt_pdf(path):
    path.write_bytes(b"this is definitely not a pdf\n" * 8)
    return path


# label -> (build the file under tmp_path, password): every way a replace-open can
# fail after the size guard.
_FAILING_OPEN_CASES = {
    "corrupt": (lambda tmp_path: _corrupt_pdf(tmp_path / "corrupt.pdf"), None),
    "missing-file": (lambda tmp_path: tmp_path / "nope.pdf", None),
    "password-required": (lambda tmp_path: _encrypted_pdf(tmp_path / "enc1.pdf"), None),
    "password-wrong": (lambda tmp_path: _encrypted_pdf(tmp_path / "enc2.pdf"), "not-the-password"),
    "zero-page": (lambda tmp_path: _prev_loop_pdf(tmp_path / "loop.pdf"), None),
}


@pytest.mark.parametrize("label", list(_FAILING_OPEN_CASES))
def test_failed_replace_open_keeps_existing_sessions(tmp_path, label) -> None:
    build, password = _FAILING_OPEN_CASES[label]
    bad = build(tmp_path)
    good_a = _make_pdf(tmp_path / "a.pdf", pages=2)
    good_b = _make_pdf(tmp_path / "b.pdf", pages=3)
    model = PDFModel()
    try:
        sid_a = model.open_pdf(str(good_a), append=True)
        sid_b = model.open_pdf(str(good_b), append=True)
        assert model.get_active_session_id() == sid_b
        with pytest.raises(Exception):
            model.open_pdf(str(bad), password=password, append=False)
        assert model.session_ids == [sid_a, sid_b]
        assert model.get_active_session_id() == sid_b
        assert len(model.doc) == 3
        # The path map still routes the surviving files to their sessions.
        assert model.open_pdf(str(good_a), append=True) == sid_a
    finally:
        model.close()


def test_failed_replace_open_over_size_limit_keeps_existing_sessions(
    tmp_path, monkeypatch
) -> None:
    good = _make_pdf(tmp_path / "a.pdf", pages=2)
    other = _make_pdf(tmp_path / "b.pdf", pages=1)
    model = PDFModel()
    try:
        sid = model.open_pdf(str(good), append=True)
        monkeypatch.setattr(pdf_model, "_MAX_PDF_BYTES", 0)
        with pytest.raises(Exception, match="size limit"):
            model.open_pdf(str(other), append=False)
        assert model.session_ids == [sid]
    finally:
        model.close()


def test_failed_replace_open_over_page_limit_keeps_existing_sessions(
    tmp_path, monkeypatch
) -> None:
    good = _make_pdf(tmp_path / "a.pdf", pages=1)
    big = _make_pdf(tmp_path / "big.pdf", pages=3)
    model = PDFModel()
    try:
        sid = model.open_pdf(str(good), append=True)
        monkeypatch.setattr(pdf_model, "_MAX_PAGES", 2)
        with pytest.raises(Exception, match="page limit"):
            model.open_pdf(str(big), append=False)
        assert model.session_ids == [sid]
        assert len(model.doc) == 1
    finally:
        model.close()


def test_replace_open_success_replaces_every_session(tmp_path) -> None:
    a = _make_pdf(tmp_path / "a.pdf", pages=1)
    b = _make_pdf(tmp_path / "b.pdf", pages=2)
    c = _make_pdf(tmp_path / "c.pdf", pages=3)
    model = PDFModel()
    try:
        sid_a = model.open_pdf(str(a), append=True)
        sid_b = model.open_pdf(str(b), append=True)
        sid_c = model.open_pdf(str(c), append=False)
        assert model.session_ids == [sid_c]
        assert sid_c not in (sid_a, sid_b)
        assert model.get_active_session_id() == sid_c
        assert len(model.doc) == 3
    finally:
        model.close()


def test_replace_open_of_the_already_open_path_yields_one_fresh_session(tmp_path) -> None:
    a = _make_pdf(tmp_path / "a.pdf", pages=2)
    model = PDFModel()
    try:
        old = model.open_pdf(str(a), append=True)
        new = model.open_pdf(str(a), append=False)
        assert new != old
        assert model.session_ids == [new]
        assert model.open_pdf(str(a), append=True) == new
    finally:
        model.close()


def test_replace_open_runs_before_activate_while_old_sessions_are_alive(tmp_path) -> None:
    a = _make_pdf(tmp_path / "a.pdf", pages=1)
    b = _make_pdf(tmp_path / "b.pdf", pages=2)
    model = PDFModel()
    seen: list[list[str]] = []
    try:
        sid_a = model.open_pdf(str(a), append=True)
        sid_b = model.open_pdf(str(b), append=False, before_activate=lambda: seen.append(
            list(model.session_ids)
        ))
        assert seen == [[sid_a]]
        assert model.session_ids == [sid_b]
    finally:
        model.close()


def test_replace_open_before_activate_failure_keeps_sessions_and_closes_new_doc(
    tmp_path, monkeypatch
) -> None:
    a = _make_pdf(tmp_path / "a.pdf", pages=1)
    b = _make_pdf(tmp_path / "b.pdf", pages=2)
    model = PDFModel()
    try:
        sid_a = model.open_pdf(str(a), append=True)
        opened = _track_fitz_opens(monkeypatch)

        def _boom() -> None:
            raise RuntimeError("editor teardown failed")

        with pytest.raises(Exception):
            model.open_pdf(str(b), append=False, before_activate=_boom)
        assert model.session_ids == [sid_a]
        assert opened and all(d.is_closed for d in opened)
    finally:
        model.close()


@pytest.mark.parametrize("password", [None, "not-the-password"])
def test_failed_open_on_encrypted_file_closes_the_parsed_handle(
    tmp_path, monkeypatch, password
) -> None:
    enc = _encrypted_pdf(tmp_path / "enc.pdf")
    opened = _track_fitz_opens(monkeypatch)
    model = PDFModel()
    try:
        with pytest.raises(Exception):
            model.open_pdf(str(enc), password=password)
        assert opened and all(d.is_closed for d in opened)
    finally:
        model.close()


def test_guard_foreign_doc_rejects_a_zero_page_source(tmp_path) -> None:
    pdf = _prev_loop_pdf(tmp_path / "loop.pdf")
    with pytest.raises(RuntimeError):
        pdf_model._guard_foreign_doc(pdf)


def test_headless_merge_refuses_a_zero_page_input_and_writes_nothing(tmp_path) -> None:
    from model.headless_merge import headless_merge

    good = _make_pdf(tmp_path / "good.pdf", pages=2)
    loop = _prev_loop_pdf(tmp_path / "loop.pdf")
    out = tmp_path / "merged.pdf"
    with pytest.raises(RuntimeError):
        headless_merge([str(good), str(loop)], str(out))
    assert not out.exists()


def test_insert_pages_from_file_refuses_a_zero_page_source(tmp_path) -> None:
    base = _make_pdf(tmp_path / "base.pdf", pages=2)
    loop = _prev_loop_pdf(tmp_path / "loop.pdf")
    model = PDFModel()
    try:
        model.open_pdf(str(base))
        with pytest.raises((ValueError, RuntimeError)):
            model.insert_pages_from_file(str(loop), [1], 1)
        assert len(model.doc) == 2
        assert not model.has_unsaved_changes()
    finally:
        model.close()


def test_password_failures_are_typed_and_survive_the_open_wrapper(tmp_path) -> None:
    # F11-OPEN-3: the controller retries on the exception TYPE, so both the foreign
    # guard and PDFModel.open_pdf (which re-wraps every failure) must keep it.
    src = tmp_path / "locked.pdf"
    _encrypted_pdf(src, "secret")

    with pytest.raises(pdf_model.PdfPasswordRequiredError):
        pdf_model._guard_foreign_doc(src, password=None)
    with pytest.raises(pdf_model.PdfPasswordRejectedError):
        pdf_model._guard_foreign_doc(src, password="wrong")

    model = PDFModel()
    try:
        with pytest.raises(pdf_model.PdfPasswordRequiredError):
            model.open_pdf(str(src))
        with pytest.raises(pdf_model.PdfPasswordRejectedError):
            model.open_pdf(str(src), password="wrong")
    finally:
        model.close()


def test_non_password_failures_are_never_password_errors_even_with_keyword_paths(tmp_path) -> None:
    folder = tmp_path / "Unencrypted 需要密碼 密碼驗證失敗"
    folder.mkdir()
    bad = folder / "report.pdf"
    bad.write_bytes(b"not a pdf")
    model = PDFModel()
    try:
        for call in (
            lambda: model.open_pdf(str(bad)),
            lambda: model.open_pdf(str(folder / "missing.pdf")),
            lambda: pdf_model._guard_foreign_doc(bad),
        ):
            with pytest.raises(RuntimeError) as err:
                call()
            assert not isinstance(err.value, pdf_model.PdfPasswordError)
    finally:
        model.close()
