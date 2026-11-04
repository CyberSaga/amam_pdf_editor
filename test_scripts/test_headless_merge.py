from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import fitz  # noqa: E402
import pytest  # noqa: E402

import model.pdf_model as pdf_model  # noqa: E402
from model.headless_merge import headless_merge  # noqa: E402
from test_scripts.navigation_fixtures import (  # noqa: E402
    labels,
    link_targets,
    make_nav_pdf,
    make_src_pdf,
    outline_attrs,
)


def _make_pdf(path: Path, text: str, *, pages: int = 1) -> None:
    doc = fitz.open()
    for page_index in range(pages):
        page = doc.new_page(width=200, height=200)
        page.insert_text((36, 72), f"{text}-{page_index}")
    doc.save(path)
    doc.close()


def test_headless_merge_combines_inputs(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    merged = tmp_path / "merged.pdf"
    _make_pdf(first, "alpha", pages=2)
    _make_pdf(second, "beta", pages=1)

    headless_merge([str(first), str(second)], str(merged))

    assert merged.exists()
    merged_doc = fitz.open(merged)
    try:
        assert merged_doc.page_count == 3
        assert "alpha-0" in merged_doc[0].get_text("text")
    finally:
        merged_doc.close()


def test_headless_merge_rejects_empty_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        headless_merge([], str(tmp_path / "merged.pdf"))


def test_headless_merge_rejects_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        headless_merge([str(tmp_path / "missing.pdf")], str(tmp_path / "merged.pdf"))


def test_headless_merge_rejects_oversize_input(tmp_path: Path, monkeypatch) -> None:
    # Phase 2.3: headless merge inputs are foreign PDFs and must pass the same
    # resource guards (_guard_foreign_doc) as every other open path.
    first = tmp_path / "a.pdf"
    merged = tmp_path / "merged.pdf"
    _make_pdf(first, "alpha")
    monkeypatch.setattr(pdf_model, "_MAX_PDF_BYTES", 0)

    with pytest.raises(ValueError):
        headless_merge([str(first)], str(merged))
    assert not merged.exists()


def test_headless_merge_rejects_missing_output_directory(tmp_path: Path) -> None:
    first = tmp_path / "a.pdf"
    _make_pdf(first, "alpha")

    with pytest.raises(FileNotFoundError):
        headless_merge([str(first)], str(tmp_path / "missing" / "merged.pdf"))


def test_headless_merge_failed_write_keeps_an_existing_output(tmp_path: Path, monkeypatch) -> None:
    # LS-2: MuPDF's path output truncates the destination as it opens it; the
    # merge must stage + replace so a writer that dies half way leaves the old file.
    first = tmp_path / "a.pdf"
    merged = tmp_path / "merged.pdf"
    _make_pdf(first, "alpha")
    _make_pdf(merged, "previous", pages=2)
    before = merged.read_bytes()

    def _failing(self, filename, *a, **k):
        with open(filename, "wb") as handle:
            handle.write(b"%PDF-1.7\n% partial")
        raise RuntimeError("injected: disk full")

    monkeypatch.setattr(fitz.Document, "save", _failing)
    with pytest.raises(RuntimeError, match="injected"):
        headless_merge([str(first)], str(merged))
    monkeypatch.undo()

    assert merged.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.pdf", "merged.pdf"]
    headless_merge([str(first)], str(merged))
    out = fitz.open(merged)
    try:
        assert out.page_count == 1
    finally:
        out.close()


def test_headless_merge_carries_outline_labels_names_and_links(tmp_path: Path) -> None:
    # F16-NAV-3: the CLI merge went through insert_pdf alone and wrote a document
    # without bookmarks, page labels, named destinations or /Fit links.
    nav = tmp_path / "nav.pdf"
    src = tmp_path / "src.pdf"
    out = tmp_path / "out.pdf"
    make_nav_pdf(nav)
    make_src_pdf(src)

    headless_merge([str(nav), str(src)], str(out))

    original = fitz.open(nav)
    merged = fitz.open(out)
    try:
        assert len(merged) == 9
        assert [row[1:3] for row in merged.get_toc()] == [
            ["Intro", 2],
            ["Website", -1],
            ["Chapter 4", 4],
            ["Section 4.1", 5],
            ["Last", 6],
            ["Src A", 7],
            ["Src C", 9],
        ]
        expected = outline_attrs(original)
        assert {title: outline_attrs(merged)[title] for title in expected} == expected
        assert labels(merged) == [*labels(original), "1", "2", "3"]
        assert set(merged.resolve_names()) == {"chap3", "chap3.2"}
        assert link_targets(merged, 0) == {80: 4, 600: "chap3", 662: 3, 712: 4}
        assert link_targets(merged, 6) == {80: 8, 600: "chap3.2"}
    finally:
        merged.close()
        original.close()
