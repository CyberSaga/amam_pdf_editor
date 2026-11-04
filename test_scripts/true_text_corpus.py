"""Pure loader for the true-text corpus manifest (frontier design 2a, slice I0a).

``test_scripts/fixtures/true_text_corpus/manifest.json`` is the tracked, redacted
description of every real-corpus edit the suite proves or must keep refusing.
This module reads it with the standard library only (no fitz, no Qt) so the
CI lane can pin the manifest's invariants without any fixture PDF.

Row states
----------
``candidate``     rederive refuses it at the ingest HEAD (or it is a false-safe
                  row, see below); read only by the candidates watch.
``engine_active`` acceptance prepare/commit and the refusals test are green;
                  never click-path-proven, never in a UI shard.
``active``        click-path loops and the UI umbrella passed on it; sits in
                  exactly one ``ui_shard``.
``retired``       a refusal row or twin that a later slice opened.

A false-safe row is ``kind="refusal"`` with ``expected_reason is None`` (the
product commits it at HEAD although an oracle helper says it must not).  It has
no exact reason to assert, so :meth:`Manifest.refusal_cases` never yields it.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

MANIFEST = Path(__file__).resolve().parent / "fixtures" / "true_text_corpus" / "manifest.json"
SCHEMA = "true-text-corpus/1"

STATES = ("candidate", "engine_active", "active", "retired")
KINDS = ("positive", "refusal")
FONT_KINDS = ("type0", "simple", "type3")
DEFAULT_STATES = ("active", "engine_active")

#: Active positives the click-path loops must always cover (the historic fourteen).
MIN_ACTIVE_POSITIVES = 14

#: The five plaintext strings that may appear as ``original``/``replacement`` text outside the
#: hash-pinned fixtures (acceptance table and the missing-glyph calibration).  They are the
#: validator's whitelist for the calibration exemption and the only plaintext originals the
#: manifest tests tolerate.
CALIBRATION_STRINGS: tuple[str, ...] = (
    '空調冰水管線系統圖(1)',
    '空調冰水管線系統圖(4)',
    'Drawing List',
    'Drawing Title',
    '空調冰水管路系統圖(1)',
)

#: ``(slug, page_index, show_seq, replacement, expected_tj_compensation, original_sha256)``
#: of the fourteen edits proven end to end before the manifest existed.  Deliberately a
#: literal outside the manifest: deleting a manifest row cannot silently shrink the floor.
#: ``original_sha256`` is sha256 of the UTF-8 text the hash-pinned fixture decodes to.
HISTORIC_FOURTEEN: tuple[tuple[str, int, int, str, float | None, str], ...] = (
    ('hvac', 4, 11, '空調冰水管線系統圖(4)', None, '04add7adddcac2509b48fcc44f42bf284ecd4429172c66d83f970107b9f6a283'),
    ('hvac', 4, 16, '空調冷卻水管線系統表(1)', None, 'af9f2f74d577026503de06fb0c636455ca97b773ec9de27617cf42d324b9ec19'),
    ('hvac', 4, 6, '空調系統圖說', None, '437006c1f1f136f2592a28ff4987df1d271229ca9a8eecb56638634f07759967'),
    ('hvac', 4, 7, 'Chilled Water Distribution System Diagram(4)', None, 'a93138becfc9d22fd41b81ba952fde375d3eec919cef7d5d8e1137429382c546'),
    ('hvac', 4, 18, '2F Chilled Water System Plan Layout', None, '129d6a2f80df206f50eb4b341dd1c3b78679c54a749f67bdc2e1fb2a4819f620'),
    ('hvac', 4, 26, 'Drawing Title', 333.0, '38f476fdadbd43d915ef2891813701fae6dc4e190067946a77aa8f5ed44dc469'),
    ('hvac', 5, 60, '2026.05.16', None, '07754e3791bcb2edc65abdbbf05e461f09e79ca3039c62e88ddd948f1b1a3417'),
    ('hvac', 5, 58, '空調系統設計圖說B版', -79.0, 'c3d80a576397b4ca48b7f636b880613587331ddb1549664819ec84b22377dae6'),
    ('hvac', 6, 7, 'Tank Buffer', None, 'b01bb530d93576aea0cb56320d3aaa6e28052a7edd825ff9f5c7e353e169ba9a'),
    ('hvac', 6, 5, 'Tank Buffer', None, 'b01bb530d93576aea0cb56320d3aaa6e28052a7edd825ff9f5c7e353e169ba9a'),
    ('ecc', 0, 31, '專案圖名', None, 'c4f17fe66069aa7420fe46f9b65ef4f41d838d0192ea786253c1f146c4fe6064'),
    ('ecc', 0, 38, '機房配置圖', None, '631e4daeb802a91576034a3d92d3b5a0fc70d788f7d956cd194a32814efbbae2'),
    ('ecc', 0, 57, '113.05.05', None, '15f346856376aa83eb454847e820b6dc125bc908c238cfb0e1a47419dc1d09d7'),
    ('ecc', 0, 60, 'ECC-3', -500.0, '306a3a57a5bfe7d06316a66c06f4adde43b9d4a647266cabcebc412485bd0660'),
)

#: ``(slug, page_index, show_seq) -> (font_resource, basefont, font_kind)`` of the same fourteen edits, a sibling
#: literal so the ``HISTORIC_FOURTEEN`` tuple shape stays as designed: a pure test can then notice an edit of a
#: historic row's font identity.
HISTORIC_FONTS: dict[tuple[str, int, int], tuple[str, str, str]] = {
    ('hvac', 4, 11): ('C2_1', 'PMingLiU', 'type0'),
    ('hvac', 4, 16): ('C2_1', 'PMingLiU', 'type0'),
    ('hvac', 4, 6): ('C2_1', 'PMingLiU', 'type0'),
    ('hvac', 4, 7): ('C2_0', 'ArialMT', 'type0'),
    ('hvac', 4, 18): ('C2_0', 'ArialMT', 'type0'),
    ('hvac', 4, 26): ('C2_0', 'ArialMT', 'type0'),
    ('hvac', 5, 60): ('C2_1', 'MicrosoftJhengHeiRegular', 'type0'),
    ('hvac', 5, 58): ('C2_1', 'MicrosoftJhengHeiRegular', 'type0'),
    ('hvac', 6, 7): ('C2_1', 'ArialMT', 'type0'),
    ('hvac', 6, 5): ('C2_1', 'ArialMT', 'type0'),
    ('ecc', 0, 31): ('F2', 'DFKaiShu-SB-Estd-BF', 'type0'),
    ('ecc', 0, 38): ('F2', 'DFKaiShu-SB-Estd-BF', 'type0'),
    ('ecc', 0, 57): ('F2', 'DFKaiShu-SB-Estd-BF', 'type0'),
    ('ecc', 0, 60): ('F2', 'DFKaiShu-SB-Estd-BF', 'type0'),
}

_KEY_RE = re.compile(r"^(?P<slug>[A-Za-z0-9][A-Za-z0-9._-]*)/p(?P<page>\d+)/show(?P<show>\d+)(?:#(?P<variant>[A-Za-z0-9._-]+))?$")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_CORPUS_KEYS = ("slug", "relative_path", "sha256", "provenance", "lineage_id", "ui_shard")
_CASE_KEYS = (
    "key", "slug", "page_index", "show_seq", "original", "original_sha256", "replacement",
    "font_resource", "basefont", "font_kind", "class_id", "kind", "expected_tier",
    "expected_tj_compensation", "expected_reason", "expected_reason_at_head", "click_reachable",
    "state", "owned_until_slice", "false_safe_oracle", "twin", "twin_waiver", "provenance",
)


@dataclass(frozen=True)
class CorpusCase:
    page_index: int
    show_seq: int
    original: str | None
    replacement: str
    font_resource: str
    basefont: str
    expected_tj_compensation: float | None = None
    # When ``original`` is None the target text is read from the hash-pinned
    # fixture and checked against this digest, keeping identifying text out of git.
    original_sha256: str | None = None
    class_id: str = "historic"
    font_kind: str = "type0"
    expected_tier: int | None = None
    click_reachable: bool = True
    key: str | None = None
    state: str = "active"

    @property
    def label(self) -> str:
        return f"p{self.page_index + 1}/show{self.show_seq}: {self.original!r} -> {self.replacement!r}"


@dataclass(frozen=True)
class CorpusSpec:
    slug: str
    relative_path: str
    sha256: str
    cases: tuple[CorpusCase, ...]
    provenance: str = "proprietary"
    lineage_id: str | None = None
    ui_shard: int = 0


@dataclass(frozen=True)
class RefusalCase:
    slug: str
    page_index: int
    show_seq: int
    original: str | None
    original_sha256: str | None
    replacement: str
    expected_reason: str
    click_reachable: bool
    owned_until_slice: str | None


@dataclass(frozen=True)
class Manifest:
    """The parsed manifest.  ``corpora`` keep file order; ``rows`` are the raw case dicts (read-only by convention)."""

    corpora: tuple[CorpusSpec, ...]
    rows: tuple[dict, ...]

    def _spec(self, corpus: CorpusSpec, cases: tuple[CorpusCase, ...]) -> CorpusSpec:
        return CorpusSpec(
            slug=corpus.slug,
            relative_path=corpus.relative_path,
            sha256=corpus.sha256,
            cases=cases,
            provenance=corpus.provenance,
            lineage_id=corpus.lineage_id,
            ui_shard=corpus.ui_shard,
        )

    def _positive_rows(self, slug: str, states: tuple[str, ...]) -> list[dict]:
        return [r for r in self.rows if r["slug"] == slug and r["kind"] == "positive" and r["state"] in states]

    def _specs(self, states: tuple[str, ...], *, click_only: bool = False) -> tuple[CorpusSpec, ...]:
        out: list[CorpusSpec] = []
        for corpus in self.corpora:
            rows = self._positive_rows(corpus.slug, states)
            if click_only:
                rows = [r for r in rows if r["click_reachable"]]
            if rows:
                out.append(self._spec(corpus, tuple(_to_case(r) for r in rows)))
        return tuple(out)

    def corpus_specs(self, states: tuple[str, ...] = DEFAULT_STATES) -> tuple[CorpusSpec, ...]:
        """Positive rows per corpus in the given states; a corpus with no such row is left out."""
        return self._specs(tuple(states))

    def refusal_cases(self, states: tuple[str, ...] = DEFAULT_STATES) -> tuple[RefusalCase, ...]:
        """Refusal rows in ``states`` that name an exact reason.

        A false-safe row (``expected_reason is None``: the product commits it at HEAD) is never
        yielded whatever ``states`` says; the candidates watch owns it until a slice retires it.
        """
        out: list[RefusalCase] = []
        for r in self.rows:
            if r["kind"] != "refusal" or r["state"] not in states or r["expected_reason"] is None:
                continue
            out.append(
                RefusalCase(
                    slug=r["slug"],
                    page_index=r["page_index"],
                    show_seq=r["show_seq"],
                    original=r["original"],
                    original_sha256=r["original_sha256"],
                    replacement=r["replacement"],
                    expected_reason=r["expected_reason"],
                    click_reachable=r["click_reachable"],
                    owned_until_slice=r["owned_until_slice"],
                )
            )
        return tuple(out)

    def click_reachable_positives(self) -> tuple[CorpusCase, ...]:
        """The ``active`` positives: the cases the click-path loops must cover."""
        return tuple(case for spec in self.click_reachable_specs() for case in spec.cases)

    def click_reachable_specs(self) -> tuple[CorpusSpec, ...]:
        """Specs filtered to their ``active`` click-reachable rows, for the click-path loops."""
        return self._specs(("active",), click_only=True)

    def ui_cases(self, shard: int) -> tuple[CorpusCase, ...]:
        """``active`` rows whose corpus sits in ``shard`` (the case ``key`` carries its corpus slug)."""
        shard_slugs = {c.slug for c in self.corpora if c.ui_shard == shard}
        return tuple(
            case
            for spec in self.click_reachable_specs()
            if spec.slug in shard_slugs
            for case in spec.cases
        )

    def candidates(self) -> tuple[dict, ...]:
        """Raw ``candidate`` rows (positives, refusals and false-safe rows) for the candidates watch."""
        return tuple(r for r in self.rows if r["state"] == "candidate")

    def spec_by_slug(self, slug: str) -> CorpusSpec:
        """The corpus ``slug`` with all its active and engine_active positives; ``KeyError`` on an unknown slug."""
        for corpus in self.corpora:
            if corpus.slug == slug:
                return self._spec(corpus, tuple(_to_case(r) for r in self._positive_rows(slug, DEFAULT_STATES)))
        raise KeyError(f"unknown corpus slug {slug!r}")


def _to_case(row: dict) -> CorpusCase:
    comp = row["expected_tj_compensation"]
    return CorpusCase(
        page_index=row["page_index"],
        show_seq=row["show_seq"],
        original=row["original"],
        replacement=row["replacement"],
        font_resource=row["font_resource"],
        basefont=row["basefont"],
        expected_tj_compensation=None if comp is None else float(comp),
        original_sha256=row["original_sha256"],
        class_id=row["class_id"],
        font_kind=row["font_kind"],
        expected_tier=row["expected_tier"],
        click_reachable=row["click_reachable"],
        key=row["key"],
        state=row["state"],
    )


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_corpus(item: object) -> CorpusSpec:
    if not isinstance(item, dict):
        raise ValueError("manifest corpus entry is not an object")
    for name in _CORPUS_KEYS:
        if name not in item:
            raise ValueError(f"manifest corpus entry lacks {name!r}")
    text_fields = [item[name] for name in ("slug", "relative_path", "sha256", "provenance", "lineage_id")]
    if not all(isinstance(v, str) and v for v in text_fields):
        raise ValueError("manifest corpus text fields must be non-empty strings")
    if not _SHA_RE.fullmatch(item["sha256"]):
        raise ValueError("manifest corpus sha256 must be 64 lowercase hex digits")
    if not _is_int(item["ui_shard"]) or item["ui_shard"] < 0:
        raise ValueError("manifest corpus ui_shard must be a non-negative integer")
    return CorpusSpec(
        slug=item["slug"],
        relative_path=item["relative_path"],
        sha256=item["sha256"],
        cases=(),
        provenance=item["provenance"],
        lineage_id=item["lineage_id"],
        ui_shard=item["ui_shard"],
    )


def _check_row(row: object, slugs: set[str]) -> dict:
    if not isinstance(row, dict):
        raise ValueError("manifest case is not an object")
    missing = [name for name in _CASE_KEYS if name not in row]
    if missing:
        raise ValueError(f"manifest case lacks {missing}")
    match = _KEY_RE.match(row["key"]) if isinstance(row["key"], str) else None
    if match is None:
        raise ValueError(f"manifest case key {row['key']!r} is malformed")
    if row["slug"] not in slugs:
        raise ValueError(f"manifest case {row['key']!r} names a slug missing from corpora")
    if not (_is_int(row["page_index"]) and _is_int(row["show_seq"]) and row["page_index"] >= 0 and row["show_seq"] >= 0):
        raise ValueError(f"manifest case {row['key']!r} needs non-negative integer page_index and show_seq")
    if (match["slug"], int(match["page"]), int(match["show"])) != (row["slug"], row["page_index"], row["show_seq"]):
        raise ValueError(f"manifest case key {row['key']!r} disagrees with its slug/page_index/show_seq")
    for name, allowed in (("state", STATES), ("kind", KINDS), ("font_kind", FONT_KINDS)):
        if row[name] not in allowed:
            raise ValueError(f"manifest case {row['key']!r}: {name} {row[name]!r} is not one of {allowed}")
    if not isinstance(row["click_reachable"], bool):
        raise ValueError(f"manifest case {row['key']!r}: click_reachable must be a bool")
    for name in ("replacement", "font_resource", "basefont", "class_id"):
        if not isinstance(row[name], str):
            raise ValueError(f"manifest case {row['key']!r}: {name} must be a string")
    if row["original"] is not None and not isinstance(row["original"], str):
        raise ValueError(f"manifest case {row['key']!r}: original must be a string or null")
    digest = row["original_sha256"]
    if digest is not None and not (isinstance(digest, str) and _SHA_RE.fullmatch(digest)):
        raise ValueError(f"manifest case {row['key']!r}: original_sha256 must be 64 lowercase hex digits or null")
    comp = row["expected_tj_compensation"]
    if comp is not None and (isinstance(comp, bool) or not isinstance(comp, (int, float))):
        raise ValueError(f"manifest case {row['key']!r}: expected_tj_compensation must be a number or null")
    tier = row["expected_tier"]
    if tier is not None and (not _is_int(tier) or tier not in (0, 1)):
        raise ValueError(f"manifest case {row['key']!r}: expected_tier must be 0, 1 or null")
    return row


def load_manifest(path: Path | str = MANIFEST) -> Manifest:
    """Parse and structurally validate the manifest.  Raises on a missing or invalid file; never skips."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("true-text corpus manifest has an unknown schema")
    if not isinstance(data.get("corpora"), list):
        raise ValueError("true-text corpus manifest has no 'corpora' list")
    if not isinstance(data.get("cases"), list):
        raise ValueError("true-text corpus manifest has no 'cases' list")
    corpora = tuple(_parse_corpus(item) for item in data["corpora"])
    slugs = [c.slug for c in corpora]
    if len(set(slugs)) != len(slugs):
        raise ValueError("manifest corpora repeat a slug")
    shas = [c.sha256 for c in corpora]
    if len(set(shas)) != len(shas):
        raise ValueError("manifest corpora repeat a sha256")
    rows = tuple(_check_row(row, set(slugs)) for row in data["cases"])
    keys = [r["key"] for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("manifest cases repeat a key")
    return Manifest(corpora=corpora, rows=rows)
