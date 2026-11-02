"""Characterizations of the consented legacy rebuild (改用重建文字).

The shipped tiered engine (``TextCommitSettings()``) refuses the two cases
below before any tier runs.  Both refusals are *rebuildable*
(``view/text_edit_reasons.py``), so the user can answer the consent dialog
and the edit is then performed by the legacy redact+reinsert engine
(``PDFModel._apply_redact_insert``) -- on shipped settings, no
``engine="legacy"`` override.  These tests pin what that rebuild does today
so the behavior cannot drift silently (PITFALLS "characterization needs
teeth"):

* plain asserts on the branch preconditions first (SUCCESS, the consent
  callback asked exactly once, the legacy engine entered exactly once,
  ``DEGRADED_COMMITTED`` / ``TIER2_LEGACY`` / the two-step fallback chain),
  so a refusal, a crash, or the tiered engine later admitting the case
  fails loudly at the precondition, never as a vacuous pass;
* then the characterized behavior, with a comment naming the intended
  behavior and the condition under which the expectation flips.

History (plans/xfail-skip-retirement.md, 2026-11-02): until then this file
held five ``xfail(strict=True)`` tests pinned to ``engine="legacy"``.  The
untouched-scalar-font case has a green tiered twin in
``test_text_commit_no_silent_legacy.py``; the fast-vs-htmlbox pixel case and
the neighbor push-down case were deleted (legacy-only preview divergence;
push-down of a separate block under a consented rebuild is accepted
behavior, guarded by ``test_edit_text_helpers.py``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.edit_commands import EditTextResult  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_commit.dto import (  # noqa: E402
    CommitStatus,
    CommitTier,
    RejectReason,
    TextCommitSettings,
)


def _open_model(pdf_path: Path) -> PDFModel:
    settings = TextCommitSettings()
    assert settings.engine == "tiered" and settings.strict is False
    model = PDFModel(text_commit_settings=settings)
    model.open_pdf(str(pdf_path))
    model.ensure_page_index_built(1)
    return model


class _ConsentRoute:
    """Count the consent ask and the legacy-engine entry (pass-through spy)."""

    def __init__(self, model: PDFModel, monkeypatch) -> None:
        self.asked: list[tuple[str, ...]] = []
        self.legacy_calls = 0
        original = model._apply_redact_insert

        def _spy(*args, **kwargs):
            self.legacy_calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(model, "_apply_redact_insert", _spy)

    def confirm(self, chain: tuple[str, ...]) -> bool:
        self.asked.append(tuple(chain))
        return True

    def assert_consented_rebuild(self, model: PDFModel, result: EditTextResult) -> None:
        assert result is EditTextResult.SUCCESS, (result, model.last_commit_outcome)
        assert len(self.asked) == 1, self.asked
        assert self.legacy_calls == 1
        outcome = model.last_commit_outcome
        assert outcome is not None
        assert outcome.status is CommitStatus.DEGRADED_COMMITTED, outcome
        assert outcome.tier is CommitTier.TIER2_LEGACY, outcome
        chain = outcome.fallback_chain
        assert len(chain) == 2 and chain[0].startswith("tier0:") and chain[-1] == "legacy", chain
        assert self.asked[0] == chain


def _find_block(model: PDFModel, probe: str):
    for block in model.block_manager.get_blocks(0):
        if probe in (block.text or ""):
            return block
    raise AssertionError(f"no block containing {probe!r}")


def _edit(model: PDFModel, probe: str, new_text: str, **kwargs) -> EditTextResult:
    block = _find_block(model, probe)
    return model.edit_text(
        1,
        fitz.Rect(block.layout_rect),
        new_text,
        original_text=block.text,
        **kwargs,
    )


def _page_font_types(page: fitz.Page) -> set[str]:
    return {entry[2] for entry in page.get_fonts(full=True)}


@pytest.fixture()
def embedded_font_pdf(tmp_path: Path) -> Path:
    """A page whose only font is an embedded Type0 face with a CFF
    (CIDFontType0) descendant -- what ``TextWriter`` + ``Font("helv")`` writes.
    The tiered engine does not admit CFF Type0 (T16-4 lists it as
    register-only), so every edit on this page is a refusal."""
    pdf_path = tmp_path / "embedded.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    writer = fitz.TextWriter(page.rect)
    writer.append((72, 100), "Alpha embedded line", font=fitz.Font("helv"), fontsize=12)
    writer.write_text(page)
    doc.save(str(pdf_path), garbage=0)
    doc.close()
    return pdf_path


def test_cff_type0_page_is_refused_without_consent(embedded_font_pdf: Path, monkeypatch):
    """Teeth for the test below: the same edit without ``allow_rebuild`` is a
    refusal with zero legacy entry and the consent callback never consulted,
    so the consented run really exercises the rebuild, not a tiered commit."""
    model = _open_model(embedded_font_pdf)
    try:
        route = _ConsentRoute(model, monkeypatch)
        result = _edit(
            model,
            "Alpha embedded",
            "Alpha embedded lines",
            confirm_fallback=route.confirm,
        )
        assert result is EditTextResult.REJECTED, result
        assert route.asked == [] and route.legacy_calls == 0
        outcome = model.last_commit_outcome
        assert outcome is not None and outcome.status is CommitStatus.REJECTED
        assert _page_font_types(model.doc[0]) == {"Type0"}
    finally:
        model.close()


def test_consented_rebuild_substitutes_the_font_resource_on_a_cff_type0_page(
    embedded_font_pdf: Path, monkeypatch
):
    """Consented rebuild on a CFF Type0 page: the text lands, but through a
    substitute font resource -- the page's font-resource type set changes.

    Intended behavior (V2: no silent substitution) is that the edited run
    keeps being served by the original embedded resource.  This expectation
    flips only if the tiered engine admits CFF Type0 (T16-4 S9, not planned)
    -- then the precondition asserts fail first, because no consent is asked
    -- or if the legacy rebuild learns to reuse the embedded resource.  The
    refusal code is deliberately not pinned: on a page whose only font is a
    refused CFF Type0 the surfaced reason is ``target_reconstruction_unverified``
    (``type0_descendant_unsupported`` is masked for latin-1 targets).
    """
    model = _open_model(embedded_font_pdf)
    try:
        types_before = _page_font_types(model.doc[0])
        assert types_before == {"Type0"}
        route = _ConsentRoute(model, monkeypatch)

        result = _edit(
            model,
            "Alpha embedded",
            "Alpha embedded lines",
            allow_rebuild=True,
            confirm_fallback=route.confirm,
        )
        route.assert_consented_rebuild(model, result)
        assert "Alpha embedded lines" in model.doc[0].get_text()

        types_after = _page_font_types(model.doc[0])
        assert types_after != types_before, (
            "the rebuild now reuses the embedded resource; update this "
            f"characterization (font types {types_before} -> {types_after})"
        )
    finally:
        model.close()


def test_consented_paragraph_rebuild_rebreaks_the_paragraph(tmp_path: Path, monkeypatch):
    """Consented rebuild of a multi-line paragraph (refused as
    ``multi_span_target`` before any tier) widens the insert box up to the
    page's safe right margin and lets MuPDF's HTML engine re-break the text,
    so three committed lines come back as one -- the "layout jumps around"
    symptom.

    Intended behavior: same line count, same first word on each line.  The
    fixture is a *shorter* replacement (heavy -> light); plans/paragraph-reflow.md
    D16/Q2 keep shorter replacements on today's path, and whether D18/Q6
    (paragraph-mode edits use the breaker) overrides that is recorded there as
    an open question (§7.2).  Flip this expectation when that plan says so;
    until then this is a characterized product defect, not accepted behavior.
    """
    original_lines = [
        "The quick brown fox jumps",
        "over the lazy dog while",
        "carrying a heavy basket",
    ]
    pdf_path = tmp_path / "para.pdf"
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i, line in enumerate(original_lines):
        page.insert_text((72, 100 + 14 * i), line, fontsize=12.0, fontname="helv")
    doc.save(str(pdf_path), garbage=0)
    doc.close()

    model = _open_model(pdf_path)
    try:
        block = _find_block(model, "quick brown")
        assert "heavy" in (block.text or "")
        replacement = (block.text or "").replace("heavy", "light")
        route = _ConsentRoute(model, monkeypatch)

        result = _edit(
            model,
            "quick brown",
            replacement,
            allow_rebuild=True,
            confirm_fallback=route.confirm,
        )
        route.assert_consented_rebuild(model, result)
        assert model.last_commit_outcome.fallback_chain == (
            f"tier0:{RejectReason.MULTI_SPAN_TARGET}",
            "legacy",
        )
        page_text = model.doc[0].get_text()
        assert "light" in page_text and "heavy" not in page_text

        committed_lines: list[str] = []
        for blk in model.doc[0].get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                text = "".join(span["text"] for span in line["spans"]).strip()
                if text:
                    committed_lines.append(text)
        assert len(committed_lines) == 1, (
            "the rebuild no longer collapses the paragraph; update this "
            f"characterization ({len(original_lines)} lines -> {committed_lines})"
        )
    finally:
        model.close()
