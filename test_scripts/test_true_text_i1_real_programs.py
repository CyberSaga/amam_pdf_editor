"""Slice I1, stage B1: the helper's glyph-identity legs read the REAL programs of the round-10 quarantines.

``needs_fixtures`` lane: the four public files live in the gitignored ``test_files/`` tree (their relative paths
and digests are rows of ``test_scripts/fixtures/public_corpus_sha256.json``); a missing file skips its case.

Until B1 the helper raised ``IndependentLegUnavailable`` on all of them: multicolumn (two shows) and
minimal-document are pdftex **Type1 ``FontFile``** programs (no ``/Encoding``, flags 4, AGL glyph names), and
bug1868759 / veraPDF 6-8-3-3 are **TrueType programs with no ``post`` table** (WinAnsi, a (3,1) cmap).  The
shows are checked UNEDITED (the show is its own before and after), so the leg must come back with no detail.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz
import pytest

from model.text_commit.fonts import page_scoped_font_entry
from test_scripts import true_text_acceptance_helpers as helpers

pytestmark = pytest.mark.needs_fixtures

_PUBLIC_LIST = Path(__file__).resolve().parent / "fixtures" / "public_corpus_sha256.json"

#: (relative path in the public list, page 0 show index, expected leg)
_CASES = (
    ("test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf", 3, "glyph_name_agl"),
    ("test_files/sample-files-main/026-latex-multicolumn/multicolumn.pdf", 49, "glyph_name_agl"),
    ("test_files/sample-files-main/001-trivial/minimal-document.pdf", 7, "glyph_name_agl"),
    ("test_files/mozilla-pdf/bug1868759.pdf", 68, "cmap_31_reverse"),
    (
        "test_files/veraPDF-corpus-staging/ISO 32000-1/veraPDF test suite 6-8-3-3-t01-fail-a.pdf",
        0,
        "cmap_31_reverse",
    ),
)


def _open_public(relative_path: str) -> fitz.Document:
    rows = {row["relative_path"]: row for row in json.loads(_PUBLIC_LIST.read_text(encoding="utf-8"))["files"]}
    assert relative_path in rows, f"{relative_path} is not in the public list"
    path = helpers.ROOT / relative_path
    if not path.exists():
        raise helpers.FixtureUnavailable(f"missing optional public fixture: {relative_path}")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == rows[relative_path]["sha256"], relative_path
    return fitz.open(path)


def _unedited_show_inputs(doc: fitz.Document, show_index: int):
    """``(show, codes, gids, text)`` of an unedited simple-font show: its decoded bytes, the texttrace gids of the
    show and the texttrace text of its glyphs."""
    shows = helpers._shows(doc, 0)
    show = shows[show_index]
    assert show.seq == show_index
    edited = helpers.edited_show(show, show, code_bytes=1)
    frame = helpers.visual_frame(doc[0])
    inputs = helpers.glyph_identity_inputs(doc, 0, edited, frame=frame, code_bytes=1)
    assert isinstance(inputs, tuple), inputs
    with helpers._measurement_copy(doc) as measured:
        flat = helpers._flatten_trace(measured[0])
    located = helpers._emissions(flat, shows, edited.after_show, frame, edited.n_new)
    assert not isinstance(located, str), located
    text = "".join(chr(glyph.ucs) for glyph in flat[located[0] : located[0] + edited.n_new])
    return show, inputs[0], inputs[1], text


@pytest.mark.parametrize(
    ("relative_path", "show_index", "leg"),
    _CASES,
    ids=[f"{'-'.join(Path(path).stem.split()[-3:])}-show{index}" for path, index, _ in _CASES],
)
def test_the_real_program_has_an_independent_glyph_leg(relative_path, show_index, leg):
    try:
        doc = _open_public(relative_path)
    except helpers.FixtureUnavailable as exc:
        pytest.skip(str(exc))
    try:
        show, codes, gids, text = _unedited_show_inputs(doc, show_index)
        entries = [entry for entry in doc[0].get_fonts(full=True) if entry[4] == show.font_resource]
        entry = next(item for item in entries if page_scoped_font_entry(item))
        measurements: dict = {}
        # IndependentLegUnavailable propagates: that is the failure this stage removes
        detail = helpers.check_glyph_identity(
            doc,
            0,
            entry[0],
            text,
            "simple",
            gid_after=gids,
            codes=codes,
            measurements=measurements,
        )
        assert detail is None, detail
        assert measurements["leg"] == leg
        assert measurements["glyphs_checked"] >= 1
        assert measurements["outline_checked"] == measurements["glyphs_checked"]
    finally:
        doc.close()
