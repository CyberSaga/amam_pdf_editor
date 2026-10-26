"""Synthetic CI twins of the true-text frontier loop (slice I0b).

``test_files/`` is gitignored and CI deselects ``needs_fixtures``, so CI sees only twins: small
synthetic documents whose ``TieredCommitEngine.prepare`` outcome is pinned.  Design:
``plans/true-text-frontier-design.md`` "Synthetic CI twins" and ``plans/true-text-i0b.md`` section 4.

Stage S2 (this file) holds the skeleton only:

* :class:`TwinSpec` and the :data:`TWINS` registry (class id -> specs) with its lookups.  The
  entries are the simple-font twins of ``simple_font_fixture_builder`` (F30W and F30B); each ``expected`` is
  what ``prepare`` + ``commit`` do AT HEAD, observed and not assumed.  A ``"COMMITTED"`` negative
  twin is the red of the slice named in ``owned_until_slice``: it is retired by name in that
  slice's commit, and any other flip is a regression.
* :class:`OracleTwinSpec`, the shape of the ORACLE twins (i)-(xii) of plan section 4, and the
  empty :data:`ORACLE_TWINS`.

Not here yet (later I0b stages): S3a fills :data:`ORACLE_TWINS` with the growth and neighbour twins
(vi, vii, viii, viii-b, ix, x, xi, xii) and their helper agreement; S3b the byte, wrapper, count and
glyph-identity twins (i-v).  S2's observations of those twins' product paths live as a pinned table
in ``test_text_commit_frontier_twins.py``; S3a/S3b turn each into an ``OracleTwinSpec.product_expected``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import fitz

from test_scripts import simple_font_fixture_builder as sfb

#: The shared simple-font twin text.  Replacing ``B`` by ``A`` is advance-neutral in every builder
#: kind (all glyphs advance the same), a Tier 0 candidate, and writes the byte 0x41 whose glyph the
#: two "lying" kinds draw as B.
TWIN_TARGET = "Level B 2024"
TWIN_REPLACEMENT = "Level A 2024"

COMMITTED = "COMMITTED"


@dataclass(frozen=True)
class TwinSpec:
    """One synthetic twin: build a document, edit ``target`` -> ``replacement``, expect ``expected``.

    ``expected`` is ``"COMMITTED"`` (``prepare`` returns a ``PreparedEdit`` and ``commit`` reports
    ``CommitStatus.COMMITTED``) or the ``RejectReason`` value of the ``PlanRejection``.
    ``polarity`` is ``"positive"`` (the edit should commit) or ``"negative"`` (it should be refused).
    ``owned_until_slice`` names the slice that makes ``expected`` flip; ``None`` for a guard.
    """

    twin_id: str
    class_id: str
    polarity: str
    build: Callable[[], fitz.Document]
    target: str
    replacement: str
    expected: str
    owned_until_slice: str | None


@dataclass(frozen=True)
class OracleTwinSpec:
    """Shape of an ORACLE twin (plan section 4; fields only, S3a/S3b fill :data:`ORACLE_TWINS`).

    ``paths`` is a subset of ``{"product", "experiment"}``; ``experiment`` is the experiment-path
    callable and ``defect`` the post-commit defect (applied after ``engine.commit`` and before the
    live render and ``saveIncr``); ``product_expected`` is ``"COMMITTED"``, a reject reason or
    ``None`` (no product path).  ``must_fail`` and ``must_pass`` both list the helpers by name:
    a helper in neither set is not asserted for that twin.
    """

    twin_id: str
    build: Callable[[], fitz.Document]
    paths: frozenset[str]
    experiment: Callable[..., object] | None
    defect: Callable[..., None] | None
    product_expected: str | None
    must_fail: frozenset[str]
    must_pass: frozenset[str]


ORACLE_TWINS: tuple[OracleTwinSpec, ...] = ()


def _simple(kind: str) -> Callable[[], fitz.Document]:
    def build() -> fitz.Document:
        return sfb.build_embedded_simple_fixture(kind, TWIN_TARGET).doc

    return build


def _simple_twin(
    kind: str, class_id: str, polarity: str, expected: str, owned_until_slice: str | None
) -> TwinSpec:
    return TwinSpec(
        twin_id=f"simple_{kind}",
        class_id=class_id,
        polarity=polarity,
        build=_simple(kind),
        target=TWIN_TARGET,
        replacement=TWIN_REPLACEMENT,
        expected=expected,
        owned_until_slice=owned_until_slice,
    )


#: class id -> specs.  Observed at HEAD (413557f), not assumed; the test file records the table.
#: Classes follow brief v5: F30W = embedded with a WinAnsi/MacRoman/Standard /Encoding, F30B =
#: embedded with no /Encoding (built-in encoding or symbolic cmap; the H-F30b false-safe class).
TWINS: dict[str, tuple[TwinSpec, ...]] = {
    "F30W": (
        _simple_twin("winansi", "F30W", "positive", COMMITTED, None),
        _simple_twin("post3_cmap31", "F30W", "positive", COMMITTED, None),
    ),
    "F30B": (
        # design :203 expected COMMITTED; HEAD refuses it (a face with only a (3,0) cmap has no
        # Unicode glyph lookup, so the product's own coverage rule fails closed).  I1's G1'
        # (font_builtin_encoding_unproven) decides what it becomes.
        _simple_twin("symbolic_ascii", "F30B", "positive", "encoding_failed", "I1"),
        # the false-safe twins.  HEAD refuses wrongname only because MuPDF extracts a glyph's text
        # from its name (the committed byte reads back as B); no glyph-identity gate exists yet, so
        # the reason flips in I1.  HEAD COMMITS tounicode_lie: I1's G1' red.
        _simple_twin("symbolic_wrongname", "F30B", "negative", "verification_failed", "I1"),
        _simple_twin("tounicode_lie", "F30B", "negative", COMMITTED, "I1"),
        # the nameless shapes (post format 3, no ToUnicode): MuPDF reads the CODE BYTE as the text,
        # so nothing in the product can see the wrong outline.  The guard commits (gid A); the
        # wrongglyph twin COMMITS a wrong glyph (gid B): I1's G1' red.
        _simple_twin("symbolic_post3", "F30B", "positive", COMMITTED, None),
        _simple_twin("symbolic_post3_wrongglyph", "F30B", "negative", COMMITTED, "I1"),
    ),
}


def all_twins() -> tuple[TwinSpec, ...]:
    return tuple(spec for specs in TWINS.values() for spec in specs)


def twins_for(class_id: str) -> tuple[TwinSpec, ...]:
    return TWINS.get(class_id, ())


def twin(twin_id: str) -> TwinSpec:
    for spec in all_twins():
        if spec.twin_id == twin_id:
            return spec
    raise KeyError(twin_id)
