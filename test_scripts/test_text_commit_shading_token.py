"""Page-level, token-aware ``sh`` scan of the growth occupancy gate (``verify._shading_presence``).

CI lane, no marker, no Qt: every document is built at run time.

Decision (TODOS "growth shading gate", option b): the page-wide ``sh`` scan used to run a regex over the raw decoded
bytes of every content stream, so the user's own replacement text (``"M sh M"``), a comment or a ``/sh1`` resource name
tripped a page-wide refusal.  The scan now lexes the page's streams joined as MuPDF reads them (one space between
elements of ``/Contents``) and refuses only on an OPERATOR token that the regex matches, or on anything the lexer
cannot prove (a MALFORMED token, an inline-image payload or ``ID`` operator, an INERT_RUN).  Lexing is paid only on
pages with a regex hit (the pages refused today).

Red-first record: ``test_growth_edit_whose_literal_holds_sh_commits_at_tier1`` (prepare refused
``growth_region_not_blank``: "occupancy: shading operator present; bounds are uncertain"), five recorded exemption cases
of ``test_shading_presence_ignores_sh_inside_non_operator_tokens`` (a sixth, ``after-inert-colour-operators``, was added
after the first mutant sweep; it would also be red today) plus ``test_shading_presence_lexes_the_pages_streams_as_one_concatenation``
(``_shading_presence`` returned True).  Guards, green before and after (they pin what the gate must keep refusing, and
what it must keep NOT refusing: the pre-filter and the join byte):
``test_growth_edit_on_a_page_with_a_real_sh_operator_is_still_refused``, ``test_shading_presence_still_flags_a_real_sh_operator``,
``test_shading_presence_falls_back_to_the_regex_on_a_stream_the_lexer_cannot_prove``, the two cross-stream counterexamples
(red against a per-stream implementation, green on today's regex and on the page-level rule), the control and the two
MuPDF premise tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import model.text_commit.verify as verify  # noqa: E402
from model.text_commit.dto import CommitStatus, CommitTier, RejectReason  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.inspect import page_fingerprint, read_page_streams  # noqa: E402
from model.text_commit.pdf_lexer import TokenKind, lex_content_stream  # noqa: E402
from model.text_commit.plan import PlanRejection, PreparedEdit  # noqa: E402

TARGET = "iii"
GROWTH_REPLACEMENT = "MMM"
SH_REPLACEMENT = "M sh M"
SHADING_DETAIL = "occupancy: shading operator present; bounds are uncertain"
_TARGET_STREAM = b"BT /F1 12 Tf 72 700 Td (iii) Tj ET"

_FONT_OBJECT = (
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
    "/Encoding /WinAnsiEncoding >>"
)


def _doc(*streams: bytes, shading: bool = False) -> fitz.Document:
    """One page, ``/Contents`` = the given streams (an array when more than one), /F1 = Helvetica.

    ``shading`` also writes ``/Shading << /Sh0 N 0 R >>`` into the SAME /Resources dict as /Font (one
    ``xref_set_key``: setting /Resources twice overwrites the first), far from the target.
    """
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    xrefs = []
    for data in streams:
        xref = doc.get_new_xref()
        doc.update_object(xref, "<<>>")
        doc.update_stream(xref, data)
        xrefs.append(xref)
    contents = f"{xrefs[0]} 0 R" if len(xrefs) == 1 else "[" + " ".join(f"{x} 0 R" for x in xrefs) + "]"
    doc.xref_set_key(page.xref, "Contents", contents)
    font_xref = doc.get_new_xref()
    doc.update_object(font_xref, _FONT_OBJECT)
    resources = f"<< /Font << /F1 {font_xref} 0 R >>"
    if shading:
        shading_xref = doc.get_new_xref()
        doc.update_object(
            shading_xref,
            "<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [0 0 40 40] /Extend [true true] "
            "/Function << /FunctionType 2 /Domain [0 1] /C0 [0 0 0] /C1 [0 0 0] /N 1 >> >>",
        )
        resources += f" /Shading << /Sh0 {shading_xref} 0 R >>"
    doc.xref_set_key(page.xref, "Resources", resources + " >>")
    return doc


def _span(page: fitz.Page, probe: str) -> dict:
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if probe in "".join(ch["c"] for ch in span["chars"]):
                    return span
    raise AssertionError(f"span {probe!r} not found")


def _prepare(doc: fitz.Document, engine: TieredCommitEngine, replacement: str):
    page = doc[0]
    span = _span(page, TARGET)
    return engine.prepare(
        page,
        target_text=TARGET,
        replacement_text=replacement,
        expected_origin=tuple(span["origin"]),
        target_bbox=tuple(span["bbox"]),
    )


def _presence(*streams: bytes) -> bool | None:
    doc = _doc(*streams)
    try:
        return verify._shading_presence(doc[0], doc)
    finally:
        doc.close()


def _covering_kinds(stream: bytes) -> list[TokenKind]:
    """The kind of the ONE token covering each regex hit (asserts a hit never straddles two tokens)."""
    tokens = list(lex_content_stream(stream))
    kinds = []
    for hit in verify._SHADING_OPERATOR_RE.finditer(stream):
        covering = [t for t in tokens if t.start <= hit.start() and hit.end() <= t.end]
        assert len(covering) == 1, (hit, covering)
        kinds.append(covering[0].kind)
    assert kinds, "premise: the regex hits the stream"
    return kinds


# ----------------------------------------------------------------------------------------------
# the product path
# ----------------------------------------------------------------------------------------------
def test_a_growth_edit_on_the_bare_target_page_commits_at_tier1_control():
    """Control (green before and after): the same page with a replacement that holds no ``sh`` commits at Tier 1, so the
    red below is attributable to the ``sh`` in the literal and to nothing else about the page."""
    doc = _doc(_TARGET_STREAM)
    engine = TieredCommitEngine(doc, max_tier=1)
    prepared = _prepare(doc, engine, GROWTH_REPLACEMENT)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE and prepared.has_ink_growth
    assert engine.commit(prepared).status is CommitStatus.COMMITTED
    doc.close()


def test_growth_edit_whose_literal_holds_sh_commits_at_tier1():
    """RED today: ``_growth_probe_failure`` -> ``_occupancy_failure`` judges the PATCHED scratch page (and commit the
    observed post-state), and the regex matched `` sh `` inside the new literal, so a page with no shading was refused
    ``growth_region_not_blank`` ("occupancy: shading operator present; bounds are uncertain")."""
    doc = _doc(_TARGET_STREAM)
    engine = TieredCommitEngine(doc, max_tier=1)
    prepared = _prepare(doc, engine, SH_REPLACEMENT)
    assert isinstance(prepared, PreparedEdit), prepared
    assert prepared.tier is CommitTier.TIER1_REBUILD_WITH_VALIDATED_FACE and prepared.has_ink_growth
    # anti-vacuity: the regex WOULD hit the bytes the commit writes
    assert b"(M sh M)" in prepared.replacement.replacement_bytes
    assert verify._SHADING_OPERATOR_RE.search(prepared.replacement.replacement_bytes) is not None

    outcome = engine.commit(prepared)
    assert outcome.status is CommitStatus.COMMITTED, outcome
    page = doc[0]
    stream = doc.xref_stream(page.get_contents()[0])
    assert b"(M sh M)" in stream
    assert SH_REPLACEMENT in page.get_text()

    reopened = fitz.open("pdf", doc.tobytes())
    assert SH_REPLACEMENT in reopened[0].get_text()
    assert reopened.xref_stream(reopened[0].get_contents()[0]) == stream
    reopened.close()
    doc.close()


def test_growth_edit_on_a_page_with_a_real_sh_operator_is_still_refused():
    """GUARD, green before and after: a real ``/Sh0 sh`` painted on the page stream (clipped far from the target, so the
    drawing gate does not fire first) still refuses the same edit with the exact shading detail and leaves the page alone."""
    doc = _doc(_TARGET_STREAM + b" q 0 0 40 40 re W n /Sh0 sh Q", shading=True)
    page = doc[0]
    fingerprint = page_fingerprint(doc, page)
    engine = TieredCommitEngine(doc, max_tier=1)
    refusal = _prepare(doc, engine, GROWTH_REPLACEMENT)
    assert isinstance(refusal, PlanRejection), refusal
    assert refusal.reason == RejectReason.GROWTH_REGION_NOT_BLANK
    assert refusal.detail == SHADING_DETAIL
    assert page_fingerprint(doc, page) == fingerprint
    doc.close()


# ----------------------------------------------------------------------------------------------
# the scan itself
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("stream", "kind"),
    [
        pytest.param(b"BT /F1 12 Tf 72 700 Td (sh) Tj ET", TokenKind.STRING, id="literal"),
        pytest.param(b"BT /F1 12 Tf 72 700 Td [(sh) -20 (ow)] TJ ET", TokenKind.STRING, id="tj-array"),
        pytest.param(b"BT /F1 12 Tf 72 700 Td (a\\) sh) Tj ET", TokenKind.STRING, id="escaped-paren"),
        pytest.param(
            b"0 g 1 0 0 RG BT /F1 12 Tf 72 700 Td (sh) Tj ET",
            TokenKind.STRING,
            id="after-inert-colour-operators",  # ``coalesce_inert`` would make the leading ops one INERT_RUN: spurious True
        ),
        pytest.param(b"% sh\nBT /F1 12 Tf 72 700 Td (iii) Tj ET", TokenKind.COMMENT, id="comment"),
        pytest.param(b"q /sh1 gs Q", TokenKind.NAME, id="name"),
    ],
)
def test_shading_presence_ignores_sh_inside_non_operator_tokens(stream, kind):
    """RED today (True for all six cases; the first five were in the recorded red run, ``after-inert-colour-operators``
    was added after the first mutant sweep and would also be red today).  Each premise: the regex hits, and the ONE token
    covering the hit is a STRING, COMMENT or NAME, which can never execute ``sh``."""
    assert verify._SHADING_OPERATOR_RE.search(stream) is not None
    assert _covering_kinds(stream) == [kind]
    assert _presence(stream) is False


@pytest.mark.parametrize(
    "stream",
    [b"/Sh0 sh", b"q /Sh0 sh Q", b"/Sh0 0sh"],
    ids=["bare", "in-q-block", "glued-0sh"],
)
def test_shading_presence_still_flags_a_real_sh_operator(stream):
    """GUARD, True before and after.  ``0sh`` lexes as the OPERATOR ``0sh`` (it is not a number), which today's regex
    matches: an ``== b"sh"`` implementation would be less strict."""
    assert _covering_kinds(stream) == [TokenKind.OPERATOR], "premise: ONE OPERATOR token covers the regex hit"
    assert _presence(stream) is True


def test_shading_presence_flags_a_real_sh_on_a_later_stream_of_the_page():
    """GUARD, True before and after: the real operator sits in the second element of ``/Contents``."""
    assert _presence(b"BT /F1 12 Tf 72 700 Td (sh) Tj ET", b"/Sh0 sh") is True


@pytest.mark.parametrize(
    "stream",
    [_TARGET_STREAM, b"/Fish Do"],
    ids=["no-hit", "sh-inside-a-word"],
)
def test_shading_presence_is_false_without_any_sh(stream):
    """GUARD, False before and after."""
    assert verify._SHADING_OPERATOR_RE.search(stream) is None
    assert _presence(stream) is False


@pytest.mark.parametrize(
    ("stream", "kind"),
    [
        pytest.param(
            b"q 4 0 0 1 72 72 cm BI /W 4 /H 1 /BPC 8 /CS /G ID abcd EI Q",
            TokenKind.INLINE_IMAGE_DATA,
            id="inline-image-without-sh",
        ),
        pytest.param(b"BT /F1 12 Tf 72 700 Td (abc) Tj ET )", TokenKind.MALFORMED, id="stray-close-paren-without-sh"),
        pytest.param(b"BT /F1 12 Tf 72 700 Td (abc Tj ET", TokenKind.MALFORMED, id="unterminated-string-without-sh"),
    ],
)
def test_shading_presence_pre_filter_keeps_unprovable_streams_without_a_hit_false(stream, kind):
    """GUARD, False before and after.  An inline image (``ID``), a stray ``)`` or an unterminated string is something the
    lexer cannot prove, but with NO regex hit anywhere the answer must stay False, as today: without the pre-filter every
    such page (inline images are common) would refuse growth.  Premise: the lexer flags the stream, the regex has no hit."""
    assert verify._SHADING_OPERATOR_RE.search(stream) is None
    assert kind in {t.kind for t in lex_content_stream(stream)}, "premise: the lexer yields the unproven kind"
    assert _presence(stream) is False


@pytest.mark.parametrize(
    ("stream", "kind"),
    [
        pytest.param(b"BT /F1 12 Tf 72 700 Td (sh) Tj ET )", TokenKind.STRING, id="stray-close-paren"),
        pytest.param(b"BT /F1 12 Tf 72 700 Td (sh Tj ET", TokenKind.MALFORMED, id="unterminated-string"),
        pytest.param(
            b"q 4 0 0 1 72 72 cm BI /W 4 /H 1 /BPC 8 /CS /G ID  sh EI Q",
            TokenKind.INLINE_IMAGE_DATA,
            id="inline-image-payload",
        ),
    ],
)
def test_shading_presence_falls_back_to_the_regex_on_a_stream_the_lexer_cannot_prove(stream, kind):
    """GUARD, True before and after.  The only regex hit sits inside a STRING, a MALFORMED run or an inline-image
    payload, so a token-only view would say False; the lexer cannot prove such a stream (its EI search can disagree with
    MuPDF's length-based payload end), so the answer stays the regex answer: refuse."""
    assert verify._SHADING_OPERATOR_RE.search(stream) is not None
    assert _covering_kinds(stream) == [kind]
    kinds = {t.kind for t in lex_content_stream(stream)}
    assert kinds & {TokenKind.MALFORMED, TokenKind.INLINE_IMAGE_DATA}, "premise: the lexer flags the stream"
    assert _presence(stream) is True


# ----------------------------------------------------------------------------------------------
# page level: /Contents = [a b] is ONE stream
# ----------------------------------------------------------------------------------------------
def test_mupdf_reads_a_literal_across_two_content_streams_with_one_space_between_them():
    """Premise (MuPDF 1.27.1, measured), so a MuPDF change surfaces here: a literal opened in stream a and closed in
    stream b is one string, and the comment of stream a does NOT end at the stream boundary (the pad is a space, not an
    end-of-line byte)."""
    doc = _doc(b"BT /F1 12 Tf 20 100 Td (abc", b"% comment\n) Tj (xyz) Tj ET")
    assert doc[0].get_text().split() == ["abc", "%", "comment", "xyz"]
    doc.close()
    doc = _doc(b"BT /F1 12 Tf 20 100 Td (q) Tj ET % note", b"BT /F1 12 Tf 20 60 Td (hidden) Tj ET")
    assert doc[0].get_text().strip() == "q"
    doc.close()


def test_shading_presence_joins_the_streams_with_a_pad_byte_a_word_cannot_cross():
    """GUARD (green before and after; red under a no-pad join).  Stream a ends in the name ``/Sh0`` and stream b opens
    with ``sh``: MuPDF reads ``/Sh0 sh`` (the pad separates them) and paints.  Joined with no pad the lexer would read the
    single NAME ``/Sh0sh`` and the answer would drop to False, less strict than today's regex."""
    a = b"q /Sh0"
    b = b"sh Q"
    assert verify._SHADING_OPERATOR_RE.search(a) is None and verify._SHADING_OPERATOR_RE.search(b) is not None
    fused = a + b
    names = [fused[t.start : t.end] for t in lex_content_stream(fused) if t.kind is TokenKind.NAME]
    assert names == [b"/Sh0sh"], "premise: no pad fuses the two words into one NAME"
    assert _presence(a, b) is True


def test_shading_presence_lexes_the_pages_streams_as_one_concatenation():
    """RED today: a literal opened in stream a and closed in stream b holds the only ``sh`` (in b).  Lexed as the
    concatenation (one pad space) it is one STRING, so the page paints no shading; the regex says True."""
    a = b"BT /F1 12 Tf 72 700 Td [(abc"
    b = b"sh) -20 (x)] TJ ET"
    assert verify._SHADING_OPERATOR_RE.search(a) is None and verify._SHADING_OPERATOR_RE.search(b) is not None
    assert _covering_kinds(a + b" " + b) == [TokenKind.STRING]
    doc = _doc(a, b)
    assert "abc sh" in doc[0].get_text(), "premise: MuPDF reads the same literal"
    assert verify._shading_presence(doc[0], doc) is False
    doc.close()


def test_shading_presence_a_comment_cannot_hide_a_real_sh_in_the_next_stream():
    """GUARD (green on today's regex and on the page-level rule; red under a per-stream scan).  Stream a opens a literal and
    has no hit; stream b alone is one COMMENT.  Concatenated, the literal swallows the ``% `` and closes at the ``)``, so
    ``/Sh0 sh`` executes."""
    a = b"BT /F1 12 Tf 72 700 Td (abc"
    b = b"% ) /Sh0 sh"
    assert verify._SHADING_OPERATOR_RE.search(a) is None
    assert [t.kind for t in lex_content_stream(a)][-1] is TokenKind.MALFORMED, "premise: a alone is unprovable"
    assert [t.kind for t in lex_content_stream(b)] == [TokenKind.COMMENT], "premise: b alone is one comment"
    assert _presence(a, b) is True


def test_shading_presence_a_trailing_comment_without_eol_cannot_hide_a_real_sh_in_the_next_stream():
    """GUARD (red under a per-stream scan).  Stream a ends in a comment with no end-of-line byte; stream b alone is one clean
    STRING holding the only ``sh``.  The pad is a space, so the comment swallows the ``(`` and ``/Sh0 sh`` executes."""
    a = _TARGET_STREAM + b" % note"
    b = b"(\n/Sh0 sh %)\n"
    assert verify._SHADING_OPERATOR_RE.search(a) is None
    assert _covering_kinds(b) == [TokenKind.STRING], "premise: b alone hides its sh in a string"
    assert _presence(a, b) is True


def test_shading_presence_an_inline_image_opened_in_one_stream_covers_the_next():
    """GUARD (red under a per-stream scan, which never lexes the hit-free stream a).  Stream a ends at ``ID`` (no hit); in b
    the payload runs up to the whitespace-bounded ``EI`` and a real ``/Sh0 sh`` follows."""
    a = b"q 4 0 0 1 72 72 cm BI /W 4 /H 1 /BPC 8 /CS /G ID"
    b = b"(ab EI Q /Sh0 sh)"
    assert verify._SHADING_OPERATOR_RE.search(a) is None
    assert _covering_kinds(b) == [TokenKind.STRING], "premise: b alone hides its sh in a string"
    assert _presence(a, b) is True


def test_the_scan_reads_the_same_streams_as_read_page_streams():
    """The page-level scan sees every element of ``/Contents`` (the streams the product patches)."""
    doc = _doc(b"BT ET", b"/Sh0 sh")
    assert len(read_page_streams(doc, doc[0])) == 2
    assert verify._shading_presence(doc[0], doc) is True
    doc.close()
