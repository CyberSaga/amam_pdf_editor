"""Slice I1, refuter 2 (negatives-flip hunter): refusals that I1 turns into commits outside the plan section 4 row.

Measured 2026-11-01 by a differential probe (the same harness against a ``git archive`` of 2acd192 ``model/`` +
``utils/`` and against the lane): ``missing_glyphs`` now asks the program (``BuiltinGlyphProof.present``) instead of
``fitz.Font.has_glyph``, so every in-scope font whose face had NO Unicode lookup at HEAD (every edit refused
``encoding_failed`` at the SOURCE encode check) now passes both encode checks, and G1' (replacement codes only, plan
7.2) admits any replacement made of glyphs the program proves.  Plan section 4 names only ``symbolic_ascii``; these
tests pin the other instances so the owner's 7.1 ruling has to touch them, and check the admitted glyph is the honest one:

- builder kinds ``symbolic_postname_variant`` (a NEGATIVE twin) and ``nonsymbolic_builtin_conflict`` (a guard): HEAD
  refused every edit; the lane commits every replacement without the lying ``A`` (96 of 102 probed);
- real negative-control file isartor-6-3-7-t03-fail-a (Wingdings, symbolic, names not AGL except ``space``): HEAD
  refused every edit; the lane COMMITS a space-only replacement (tier 1);
- reportlab-overlay (Roboto, nameless, no (3,1)): still refuses everything, now ``font_builtin_encoding_unproven``.
"""
from __future__ import annotations

from io import BytesIO

import fitz
import pytest
from fontTools.ttLib import TTFont

from model.text_commit.dto import CommitStatus
from model.text_commit.engine import TieredCommitEngine
from model.text_commit.fonts import DocumentFontRegistry
from model.text_commit.plan import PlanRejection
from test_scripts import simple_font_fixture_builder as sfb
from test_scripts import true_text_acceptance_helpers as helpers
from test_scripts.test_true_text_i1_real_programs import _open_public

_TARGET = "Level B 2024"


@pytest.mark.parametrize(
    ("kind", "char"),
    [
        ("symbolic_postname_variant", "C"),
        ("symbolic_postname_variant", "9"),
        ("nonsymbolic_builtin_conflict", "C"),
        ("nonsymbolic_builtin_conflict", "-"),
        ("symbolic_ascii", "C"),
    ],
)
def test_a_font_whose_face_had_no_glyph_now_commits_the_honest_glyph(kind, char):
    """HEAD (2acd192): ``REJECTED encoding_failed`` "reverse encoder does not reproduce the source string bytes" for
    every replacement on these kinds.  Lane: COMMITTED, and the committed glyph is the program's honest one."""
    doc = sfb.build_embedded_simple_fixture(kind, _TARGET).doc
    try:
        engine = TieredCommitEngine(doc, max_tier=1)
        replacement = _TARGET[:6] + char + _TARGET[7:]
        prepared = engine.prepare(doc[0], target_text=_TARGET, replacement_text=replacement, expected_origin=None)
        assert not isinstance(prepared, PlanRejection), (kind, char, prepared)
        assert engine.commit(prepared).status is CommitStatus.COMMITTED
        with helpers._measurement_copy(doc) as measured:
            chars = measured[0].get_texttrace()[0]["chars"]
        assert chars[6][1] == sfb.glyph_id(char, kind), (kind, char, chars[6])
    finally:
        doc.close()


@pytest.mark.parametrize("kind", ["symbolic_postname_variant", "nonsymbolic_builtin_conflict"])
def test_the_lying_code_on_those_kinds_still_refuses(kind):
    doc = sfb.build_embedded_simple_fixture(kind, _TARGET).doc
    try:
        result = TieredCommitEngine(doc, max_tier=1).prepare(
            doc[0], target_text=_TARGET, replacement_text="Level A 2024", expected_origin=None
        )
        assert isinstance(result, PlanRejection) and result.reason == "font_builtin_encoding_unproven", result
    finally:
        doc.close()


_ISARTOR = (
    "test_files/veraPDF-corpus-staging/Isartor test files/PDFA-1b/6.3 Fonts/6.3.7 Character encodings/"
    "isartor-6-3-7-t03-fail-a.pdf"
)
_REPORTLAB_SUFFIX = "reportlab-overlay"


def _open(relative_path: str) -> fitz.Document:
    try:
        return _open_public(relative_path)
    except helpers.FixtureUnavailable as exc:
        pytest.skip(str(exc))


@pytest.mark.needs_fixtures
def test_isartor_wingdings_negative_control_commits_a_space_only_replacement():
    """The F30B negative-control file of every full batch (case ``r2-F30B-644ac66a-p0-s0-neg1``, show 0 'text' in
    Wingdings).  HEAD: every edit ``encoding_failed`` at the source encode check.  Lane: the batch row's own reversed
    replacement refuses ``font_builtin_encoding_unproven`` (the recorded churn-A change) but '    ' COMMITS, writing
    the program's glyph named ``space``."""
    doc = _open(_ISARTOR)
    try:
        page = doc[0]
        show = helpers._shows(doc, 0)[0]
        target = show.decoded_bytes.decode("latin-1")
        assert target == "text"
        engine = TieredCommitEngine(doc, max_tier=1)
        row = engine.prepare(page, target_text=target, replacement_text=target[::-1], expected_origin=None)
        assert isinstance(row, PlanRejection) and row.reason == "font_builtin_encoding_unproven", row
        prepared = engine.prepare(page, target_text=target, replacement_text=" " * len(target), expected_origin=None)
        assert not isinstance(prepared, PlanRejection), prepared
        assert engine.commit(prepared).status is CommitStatus.COMMITTED
        font_xref = prepared.font_xref
        program = TTFont(BytesIO(doc.extract_font(font_xref)[3]))
        space_gid = program.getGlyphID("space")
        with helpers._measurement_copy(doc) as measured:
            glyphs = [c for trace in measured[0].get_texttrace() if trace["font"].endswith("Wingdings-Regular") for c in trace["chars"]]
        assert glyphs and all(c[1] == space_gid for c in glyphs[: len(target)]), glyphs[: len(target)]
    finally:
        doc.close()


@pytest.mark.needs_fixtures
def test_reportlab_roboto_proves_nothing_and_still_refuses_everything():
    """Roboto (symbolic, (1,0) only, post 3): present for all 95 printable codes, proved for none, so every edit
    refuses; HEAD said ``encoding_failed`` (source), the lane says ``font_builtin_encoding_unproven``."""
    import json

    rows = json.loads(helpers.ROOT.joinpath("test_scripts", "fixtures", "public_corpus_sha256.json").read_text(encoding="utf-8"))["files"]
    rel = next(r["relative_path"] for r in rows if r["relative_path"].rsplit("/", 1)[-1].lower().startswith(_REPORTLAB_SUFFIX))
    doc = _open(rel)
    try:
        page = doc[0]
        registry = DocumentFontRegistry(doc)
        show = helpers._shows(doc, 0)[0]
        capability = registry.capability(page, show.font_resource)
        proof = capability.builtin_proof
        assert proof is not None and proof.program_kind == "truetype"
        assert all(proof.present(code) for code in range(0x20, 0x7F))
        assert not any(proof.proves(code, chr(code)) for code in range(0x20, 0x7F))
        target = show.decoded_bytes.decode("latin-1")
        engine = TieredCommitEngine(doc, max_tier=1)
        for replacement in (target[::-1], " " * len(target), " "):
            result = engine.prepare(page, target_text=target, replacement_text=replacement, expected_origin=None)
            assert isinstance(result, PlanRejection) and result.reason == "font_builtin_encoding_unproven", (replacement, result)
    finally:
        doc.close()
