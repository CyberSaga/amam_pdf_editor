"""Re-derive Grok-round evidence bundles at HEAD (``true-text-case/2``).

The second half of the ingest (``plans/true-text-frontier-loop.md`` section 2
steps 5-7).  ``scripts/evidence_bundle.py`` checks the arithmetic of a bundle;
this module measures it again with the product itself, read-only:

* ``resolve_source`` finds the original file by ``source.sha256`` in tracked
  lists only (the public sha list, the manifest corpora (hvac and ecc
  included), the allowlisted synthetic builder).  A bundle's ``candidates/**/before.pdf`` is
  hashed with ``hashlib`` and never opened.
* ``recompute_fixture_fields`` re-derives every field the validator lists as
  ``unverifiable`` (page frame, background quad, ParentTree keys, change
  ranges, counts, source text).
* ``remeasure_advances`` recomputes both advances with the product's own
  functions (H1).
* ``rederive_case`` re-probes product rows with the frame-correct locate step
  (H3) and re-commits them; ``replay_experiment`` re-applies the declared
  ``changes[]`` bytes and re-measures everything.
* ``emit_rows`` turns a clean result into manifest rows.  A quarantined case
  never emits a row, and a measurement-only class (F2R, F2G: owner decision 2,
  X5) is measured and recorded but emits nothing, however the plan was built;
  only an explicit boolean ``measurement_only: false`` entry lifts the hold (``null``, ``0``, ``"false"`` hold; ``--planned``
  refuses them).
* V12 (brief revision >= 3): the target of an F2/F3 row is a SLICE of its show.
  ``_derive_target`` reads it off the PDF (``item_range`` = indices of the
  string items of the TJ array, ``byte_range_in_item`` = decoded bytes of item
  ``i0``); the slice is located inside the whole-show run and probed, and the
  whole show is probed as a second view.
* V13: a miss of rederive's own locate is never a product exception.  The row is quarantined
  ``target_unlocatable`` and the probe is not compared (``at_head`` carries ``result: "unlocatable"``).  The text
  locate has two fallbacks, both pure (a row the text locate resolves never takes them): the POSITIONAL locate (the
  texttrace glyphs at the replayed origin are U+FFFD or private-use; ``remeasured.locate_method == "positional"``,
  absent means ``text``) and, for census and negative rows whose recorded geometry is null, the REASON-ONLY probe
  (``expected_origin=None``; ``remeasured.probe_fallback == "reason_only"`` when exactly one replayed show spells the
  target and it is the record's; Q13: ``"reason_only_shared"`` when several do and the record's is one of them, accepted
  only if the product answered ``ambiguous_source_match``, any other answer stays ``target_unlocatable``).  A show whose replayed origin is untracked is never located (the origin
  belongs to an earlier show) and recorded geometry on it is a ``geometry_on_untracked_origin`` divergence.

Bundle code is never imported or executed, and no ``model/`` code changes: every
product function is called as a reader.  No Qt.  Run as
``.venv\\Scripts\\python.exe -B scripts\\evidence_rederive.py rederive <batch>
--validation <VALIDATION.json> --out <rederive_report.json>``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import math
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import cached_property
from pathlib import Path
from typing import Any, NamedTuple, TypeGuard

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fitz  # noqa: E402

from model.text_commit import transforms, verify  # noqa: E402
from model.text_commit.dto import CommitStatus, RejectReason, StreamReplacement  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry, FontCapability  # noqa: E402
from model.text_commit.patch import kern_for_displacement  # noqa: E402
from model.text_commit.pdf_lexer import (  # noqa: E402
    SpliceError,
    TokenKind,
    decode_hex_string,
    decode_literal_string,
    lex_content_stream,
    splice_stream,
)
from model.text_commit.plan import PlanRejection, PreparedEdit, _advance, _grown_verify_bbox  # noqa: E402
from model.text_commit.replay import PageReplay, ShowOp, replay_page_streams  # noqa: E402
from scripts import evidence_bundle as eb  # noqa: E402
from test_scripts import true_text_acceptance_helpers as helpers  # noqa: E402

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# vocabulary
# --------------------------------------------------------------------------
QUARANTINE = ("provenance_unverified", "before_pdf_mismatch", "remeasure", "target_unlocatable", "reason_order", "builder_not_allowlisted")
SKIP_CANARY_UNSAVED = "canary_unsaved_handle_fault"
DEFERRED_ORACLES = "oracles_incomplete"
REQUIRED_ORACLES = (
    "assert_target_stream_changed_only_within",
    "assert_wrapper_bytes_unchanged",
    "assert_show_and_operator_counts_equal",
    "assert_neighbour_glyphs_unchanged",
    "assert_growth_zone_was_blank",
    "assert_glyph_identity",
)
SYNTHETIC_ALLOWLIST = eb.SYNTHETIC_ALLOWLIST
# Q2 (owner ruling 2026-10-26): the owner of a false-safe found by a stream-range, wrapper, count, neighbour or growth helper is the
# CASE'S CLASS planned slice (``--planned`` ``owned_until_slice``), never the landed I0b; ``emit_rows`` raises when a class has none.
# Only glyph identity has a fixed owner: G1' (I1) closes an unproven glyph identity for every class.
ORACLE_OWNERS = {"assert_glyph_identity": "I1"}
# The classes the design's 2b table plans slices for; the owner extends it.
DEFAULT_PLANNED = ("F30B", "F30W", "F30N", "F1", "F2I", "F2R", "F2G", "F2K", "F3", "F17", "F31", "F5", "OUT")
# owner ruling 2026-10-28 (Q2 applied): the slice that owns a false-safe an I0b helper finds on a row of each planned class
# (design :230-239 slice rows; OUT's only observed failure is glyph identity, which I1's G1' closes for every class)
DEFAULT_OWNERS = {
    "F30B": "I1", "F30W": "I1", "F30N": "I1", "F1": "I2", "F2I": "I3", "F2R": "I4", "F2G": "I5", "F2K": "I5",
    "F3": "I6", "F17": "I7", "F31": "I8", "F5": "I9", "OUT": "I1",
}
# owner decision 2 (X5 deferred) then X5 RATIFIED 2026-10-28 (dropped internal pair kerns count as natural width; the five
# F2R/F2G positives remeasured untouched 0.0 / in-show 0.0 / overlap 0 / ink >= 50 px at 6x): these classes stay planned,
# executed and recorded, never written to a manifest, until the I4/I5 product slices land and lift measurement_only
MEASUREMENT_ONLY_CLASSES = ("F2R", "F2G")
NO_EMIT_KINDS = frozenset({"control", "canary", "census"})
# the recomputed validator status a row of each kind needs before emit_rows may write it (a missing status writes nothing)
EMIT_STATUSES = {"positive": ("save_reopen_pass", "splice_pass"), "negative": ("probe_rejected",)}
STRUCTELEM_VOCAB = eb.STRUCTELEM_VOCAB
TOL_STATE = 1e-9
TOL_SCALAR = 1e-6
TOL_BBOX = 1e-3
LOCATE_MAX_PT = 0.02
GEOMETRY_KEYS = ("expected_origin_visual", "target_bbox_visual", "target_bbox_raw")
FALLBACK_KINDS = frozenset({"census", "negative"})  # kinds whose probe may run without geometry (Q5)
AFTER_BBOX_MAX_PT = 0.5
UNSAVED_CLASS = "CANARY_UNSAVED"
FAULT_CANARIES = frozenset({"CANARY_FONT", "CANARY_WRONGGLYPH"})  # the after glyphs are meant to differ from the claimed text (V14)
F2_CLASSES = frozenset({"F2I", "F2R"})
# Unverifiable codes the validator can emit that this module closes by recomputing them.
RECOMPUTED_CODES = (
    "user_unit",
    "props_keys",
    "token_aligned",
    "operator_count_before",
    "old_stream_sha256",
    "region_dict",
    "background_bbox",
    "probe_regions_px_96dpi",
    "type0_cid_unbound",
    "fragment_prefix_mismatch",
    "growth_applicable_mismatch",
    "after_bbox_frame",
    "k_sum_unverified",
    "item_range_span",
)
BATCH_LEVEL_CODES = frozenset(
    {
        "code_revision_inconsistent",
        "tracked_diff_not_empty",
        "methods_plan_sha_mismatch",
        "plan_block_missing",
        "denylist_missing",
        "validation_is_self_check",
        "synthetic_only_with_hvac_resolvable",
        "runs_missing",
        "runs_malformed",
        "runner_partial_rerun",
        "runner_sha_disk_mismatch",
        "runner_sha_mixed",
        "runner_sha_missing",
    }
)
_LOCAL_TEST_FILES = "test_files"
_CASE_DIR_RE = re.compile(r"[A-Za-z0-9_-]+")


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RegistryEntry:
    slug: str
    relative_path: str
    sha256: str
    provenance: str  # public | proprietary | local_unrecorded
    lineage_id: str


@dataclass(frozen=True)
class CorpusRegistry:
    root: Path
    entries: tuple[RegistryEntry, ...] = ()

    def by_sha(self, sha256: str, provenance: str | None = None) -> RegistryEntry | None:
        for entry in self.entries:
            if entry.sha256 == sha256 and (provenance is None or entry.provenance == provenance):
                return entry
        return None

    def resolve(self, entry: RegistryEntry) -> Path | None:
        """``root/relative_path`` when it exists, lies under ``test_files/`` and hashes to ``entry.sha256``."""
        path = self.root / entry.relative_path
        return path if _read_verified(path, entry.sha256, self.root, None) is not None else None


def _sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _contained(path: Path, root: Path, batch_dir: Path | None) -> bool:
    """``path`` resolves under ``root/test_files`` and not under the bundle directory."""
    try:
        real = path.resolve()
        base = (root / _LOCAL_TEST_FILES).resolve()
        real.relative_to(base)
    except (OSError, ValueError):
        return False
    if batch_dir is not None:
        try:
            real.relative_to(batch_dir.resolve())
        except (OSError, ValueError):
            return True
        return False
    return True


def _read_verified(path: Path, sha256: str, root: Path, batch_dir: Path | None) -> bytes | None:
    """The bytes of ``path`` when it is contained, exists and hashes to ``sha256``; else None."""
    if not _contained(path, root, batch_dir):
        return None
    try:
        if not path.is_file():
            return None
        data = path.read_bytes()
    except OSError:
        return None
    return data if _sha256(data) == sha256 else None


_slugify = eb._slugify  # one rule for the registry slugs and for the validator's slug_not_derived


_MANIFEST_RELATIVE = ("test_scripts", "fixtures", "true_text_corpus", "manifest.json")
_MANIFEST_PROVENANCE = ("local_unrecorded", "proprietary")
_SHA_RE = re.compile(r"[0-9a-f]{64}")


def _manifest_entries(path: Path, taken: set[str]) -> list[RegistryEntry]:
    """The manifest ``corpora`` as registry entries; a missing file registers nothing, a malformed one raises.

    The manifest registers ``local_unrecorded`` and ``proprietary`` rows.  A missing manifest is fail closed (those rows
    stay ``provenance_unverified``), which is why the tmp
    repo roots of the tests and a fresh checkout need no special case.  A present manifest must be exact: the public
    list keeps its name honest, so a ``public`` label, a sha the public list already holds, a path outside
    ``test_files/`` or a repeated sha is a ``ValueError``, never a silently skipped entry.
    """
    if not path.is_file():
        logger.warning("true-text corpus manifest absent; local_unrecorded entries not registered")
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != "true-text-corpus/1" or not isinstance(data.get("corpora"), list):
        raise ValueError("true-text corpus manifest has an unknown schema")
    out: list[RegistryEntry] = []
    for item in data["corpora"]:
        if not isinstance(item, dict):
            raise ValueError("true-text corpus manifest entry is not an object")
        rel, sha, prov, slug = item["relative_path"], item["sha256"], item["provenance"], item["slug"]
        if prov not in _MANIFEST_PROVENANCE:
            raise ValueError("manifest provenance must be local_unrecorded or proprietary")
        if not (isinstance(rel, str) and rel.startswith(_LOCAL_TEST_FILES + "/") and ".." not in rel.split("/") and "\\" not in rel and ":" not in rel):
            raise ValueError("manifest relative_path must be a relative path under test_files/")
        if not (isinstance(sha, str) and _SHA_RE.fullmatch(sha)):
            raise ValueError("manifest sha256 must be 64 lowercase hex digits")
        if sha in taken:
            raise ValueError("manifest sha256 is already registered")
        taken.add(sha)
        out.append(RegistryEntry(slug=str(slug), relative_path=rel, sha256=sha, provenance=prov, lineage_id=str(item.get("lineage_id") or slug)))
    return out


def load_registry(
    repo_root: Path,
    *,
    public_list: Path | None = None,
    manifest: Path | None = None,
) -> CorpusRegistry:
    """The tracked public sha list and the manifest ``corpora``.

    The manifest leg (I0a, V16) registers the ``local_unrecorded`` and ``proprietary`` files, hvac and ecc included;
    ``CorpusRegistry.by_sha`` keeps its provenance filter, so an entry only vouches for a row that declares the same
    provenance.  There is no acceptance-suite leg any more: since I0a stage 3 ``acc.CORPORA`` is
    ``load_manifest().corpus_specs()``, so every corpus it can name is already a manifest ``corpora`` entry
    (``test_v5_every_acc_corpus_is_registered_by_the_manifest_alone``).
    """
    root = Path(repo_root)
    listing = public_list if public_list is not None else root / "test_scripts" / "fixtures" / "public_corpus_sha256.json"
    entries: list[RegistryEntry] = []
    data = json.loads(Path(listing).read_text(encoding="utf-8"))
    if data.get("schema") != "public-corpus-sha256/1":
        raise ValueError("public corpus list has an unknown schema")
    for item in data.get("files", []):
        rel = str(item["relative_path"])
        entries.append(
            RegistryEntry(
                slug=_slugify(Path(rel).stem),
                relative_path=rel,
                sha256=str(item["sha256"]),
                provenance="public",
                lineage_id=str(item.get("lineage_id") or _slugify(Path(rel).stem)),
            )
        )
    taken = {e.sha256 for e in entries}
    entries.extend(_manifest_entries(Path(manifest) if manifest is not None else root.joinpath(*_MANIFEST_RELATIVE), taken))
    return CorpusRegistry(root=root, entries=tuple(entries))


# --------------------------------------------------------------------------
# result types
# --------------------------------------------------------------------------
OracleFn = Callable[["OracleContext"], "str | None"]  # None = pass, str = failure detail


@dataclass(frozen=True)
class OracleContext:
    source_doc: Any  # fitz.Document: the fixture before the edit
    after_doc: Any  # fitz.Document: the reopened file after the edit
    page_index: int
    show: ShowOp
    frame: transforms.PageVisualFrame
    target_bbox_visual: tuple[float, float, float, float]
    verify_bbox_visual: tuple[float, float, float, float]
    adv_old: float
    prepared: PreparedEdit | None
    case: dict
    # text-space advance the show draws before the first target item (Q10); 0.0 = a whole show without a leading kern
    # (the product's quad; tier 1 rejects a leading kern);
    # None = not provable, which the growth oracle refuses rather than guesses
    x_pre: float | None = 0.0
    # sum of the kern numbers between the target's own string items (Q11, thousandths of Tfs); 0.0 for a single item, an F3,
    # a Tj and a tier 1 plan; None = not provable, refused like ``x_pre``
    k_inner: float | None = 0.0
    # S4: the target slice inside the show in code units (Identity-H 2 bytes, simple 1 byte): (units before it, units after
    # it); (0, 0) = the whole show; None = unknown, which the neighbour and glyph-identity adapters refuse (never a guess)
    target_span: tuple[int, int] | None = None
    # S4: measurement sink; the neighbour adapter writes sink["neighbours"], the callers copy only that key to remeasured
    sink: dict | None = None


@dataclass(frozen=True)
class Divergence:
    field: str
    record: object
    recomputed: object
    tol: float | None


@dataclass
class RederiveResult:
    case_id: str
    outcome: str = "rederived"  # rederived | quarantined | skipped | deferred | validator_rejected
    quarantine: list[str] = field(default_factory=list)
    skipped: str | None = None
    deferred: str | None = None
    provenance_verified: bool = False
    resolved_slug: str | None = None
    at_head: dict = field(default_factory=dict)
    remeasured: dict = field(default_factory=dict)
    divergences: list[Divergence] = field(default_factory=list)
    oracles_run: dict[str, str | None] = field(default_factory=dict)
    closed_unverifiable: list[str] = field(default_factory=list)
    validated_status: str | None = None  # the validator's RECOMPUTED status, carried by the CLI; emit_rows gates on it


RemeasureResult = RederiveResult


def _plain(value: object) -> Any:
    """JSON-clean copy: no Rect, Matrix, tuple, bytes or non-ASCII leaks."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)) or hasattr(value, "__iter__") and not isinstance(value, str):
        try:
            return [_plain(v) for v in value]  # type: ignore[union-attr]
        except TypeError:
            pass
    return repr(value)


# Strings this module writes itself (field names are fixed; these are the fixed messages).  Everything else that
# reaches a report from the bundle or from a document is printed as a 12-hex digest, as Part A does: a report may be
# committed (owner decision 3).
_MESSAGES = frozenset(
    {
        "object",
        "list",
        "unlexable",
        "unreadable",
        "present",
        "show missing",
        "an experiment row needs a change",
        "change outside its stream",
        "new operand is not hex",
        "page index is outside the document",
        "the page streams do not replay",
        "show sequence is outside the page",
        "the show has no font resource",
        "the font resource has no capability",
        "the show does not decode through the font registry",
        "page geometry is unsupported",
        "no texttrace run within 0.02 pt of the replayed origin",
        "odd Type0 payload",
        "advance is not provable for this font",
        "advance is not provable for this font and text",
        "nan",
        "inf",
        "-inf",
        "substring_of_single_string_item",
        "substring_of_multi_item_tj_item",
        "spans_tj_items",
    }
)
_SAFE_WORDS = (
    eb._VOCAB
    | _MESSAGES
    | frozenset({"W", "DW", "Widths", "face", "+", "-", "committed", "degraded_committed", "stale_plan", "failed", "unknown"})
)
_SAFE_PATTERNS = (re.compile(r"[0-9a-f]{64}"), re.compile(r"#[0-9a-f]{12}"))


def _safe_value(value: object) -> Any:
    """A report-safe copy: numbers and None as they are, a known word or digest as it is, any other string a digest."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, str):
        if value in _SAFE_WORDS or eb._is_builtin_exception(value) or any(p.fullmatch(value) for p in _SAFE_PATTERNS):
            return value
        return eb._digest(value)
    if isinstance(value, Mapping):
        return f"<object of {len(value)} keys>"
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_value(v) for v in value]
    return eb._digest(repr(value))


def _div(name: str, record: object, recomputed: object, tol: float | None = None) -> Divergence:
    return Divergence(name, _safe_value(record), _safe_value(recomputed), tol)


def _ascii(text: object, limit: int = 300) -> str | None:
    """Product detail strings are ASCII templates; anything else is withheld, never echoed."""
    if text is None:
        return None
    out = "".join(ch if 0x20 <= ord(ch) <= 0x7E else "?" for ch in str(text))
    return out[:limit]


# --------------------------------------------------------------------------
# comparison helpers
# --------------------------------------------------------------------------
def _is_num(x: object) -> TypeGuard[float]:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _num_close(a: object, b: object, tol: float) -> bool:
    if not (_is_num(a) and _is_num(b)):
        return False
    return abs(float(a) - float(b)) <= tol  # type: ignore[arg-type]


def _cmp_num(divs: list[Divergence], name: str, rec: object, got: float | None, tol: float) -> None:
    if got is None or not _num_close(rec, got, tol):
        divs.append(_div(name, rec, got, tol))


def _cmp_eq(divs: list[Divergence], name: str, rec: object, got: object) -> None:
    if rec != got or isinstance(rec, bool) != isinstance(got, bool):
        divs.append(_div(name, rec, got))


def _box_close(rec: object, got: Sequence[float] | None, tol: float) -> bool:
    if got is None or not isinstance(rec, (list, tuple)) or len(rec) != 4:
        return False
    return all(_num_close(a, b, tol) for a, b in zip(rec, got, strict=True))


def _cmp_box(divs: list[Divergence], name: str, rec: object, got: Sequence[float] | None, tol: float = TOL_BBOX) -> None:
    if not _box_close(rec, got, tol):
        divs.append(_div(name, rec, None if got is None else list(got), tol))


def _d(value: object) -> dict:
    """``value`` when it is an object, else an empty one (a malformed record reads as absent fields)."""
    return value if isinstance(value, dict) else {}


def _g(obj: object, *path: object, default: object = None) -> Any:
    cur: Any = obj
    for key in path:
        if isinstance(cur, Mapping) and isinstance(key, str):
            if key not in cur:
                return default
            cur = cur[key]
        elif isinstance(cur, list) and isinstance(key, int) and 0 <= key < len(cur):
            cur = cur[key]
        else:
            return default
    return cur


# --------------------------------------------------------------------------
# lexer helpers (read-only over the product lexer)
# --------------------------------------------------------------------------
def _payloads(data: bytes) -> list[bytes] | None:
    """The decoded STRING/HEXSTRING payloads of ``data`` in order; None when it will not lex."""
    out: list[bytes] = []
    for tok in lex_content_stream(data):
        raw = data[tok.start : tok.end]
        try:
            if tok.kind is TokenKind.STRING:
                out.append(decode_literal_string(raw))
            elif tok.kind is TokenKind.HEXSTRING:
                out.append(decode_hex_string(raw))
            elif tok.kind is TokenKind.MALFORMED:
                return None
        except ValueError:
            return None
    return out


def _numbers(data: bytes) -> list[float]:
    out: list[float] = []
    for tok in lex_content_stream(data):
        if tok.kind is TokenKind.NUMBER:
            try:
                out.append(float(data[tok.start : tok.end]))
            except ValueError:
                continue
    return out


def _expected_kerns(splice_kind: object, old: bytes) -> tuple[float, list[float]]:
    """``(K_sum, internal_kerns_dropped)`` the OLD operand implies: only a tj_run drops its internal kerns (brief 5.2)."""
    if splice_kind != "tj_run":
        return 0.0, []
    kerns = _numbers(old)
    return float(sum(kerns)), kerns


def _operator_count(doc: fitz.Document, page: fitz.Page) -> int:
    total = 0
    for xref in page.get_contents():
        stream = doc.xref_stream(xref) or b""
        total += sum(1 for tok in lex_content_stream(stream) if tok.kind is TokenKind.OPERATOR)
    return total


def _cids(data: bytes) -> tuple[int, ...]:
    return tuple(int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data), 2))


# --------------------------------------------------------------------------
# the per-case measurement scene
# --------------------------------------------------------------------------
class LocateError(ValueError):
    """The texttrace match for the target is missing or farther than 0.02 pt from the replayed origin."""


class _SceneError(ValueError):
    def __init__(self, name: str, detail: str) -> None:
        super().__init__(detail)
        self.name = name


def _locate_trace(
    mpage: fitz.Page,
    show: ShowOp,
    frame: transforms.PageVisualFrame,
    needle: str,
    *,
    near: tuple[float, float] | None = None,
    sub: tuple[int, int] | None = None,
    sub_text: str | None = None,
) -> tuple[float, tuple[float, float], tuple[float, float, float, float]] | None:
    """The texttrace run of ``needle`` whose first glyph origin is nearest ``show.origin_user * frame.base``.

    ``frame.base`` is the space texttrace lives in.  ``page.transformation_matrix`` drops the CropBox origin and
    /UserUnit on a rotated page, so it is never used (design H3).

    ``sub=(g0, gn)`` (V12) makes the target glyphs ``[g0, g0+gn)`` of the run that spells ``needle`` (the whole show):
    the run is still chosen by ITS first glyph, and the returned distance is that glyph's, but the origin and the box
    are the slice's.  ``sub_text`` must equal the slice's texttrace unicode, else the candidate is skipped.
    """
    want = fitz.Point(show.origin_user) * frame.base if near is None else fitz.Point(near)
    best = None
    if not needle:
        return None
    for trace in mpage.get_texttrace():
        full = "".join(chr(c[0]) for c in trace["chars"])
        i = full.find(needle)
        while i >= 0:
            run = trace["chars"][i : i + len(needle)]
            chars = run if sub is None else trace["chars"][i + sub[0] : i + sub[0] + sub[1]]
            if sub is not None and (len(chars) != sub[1] or not chars or (sub_text is not None and "".join(chr(c[0]) for c in chars) != sub_text)):
                i = full.find(needle, i + 1)
                continue
            rect = fitz.Rect(chars[0][3])
            for c in chars[1:]:
                rect |= fitz.Rect(c[3])
            origin = fitz.Point(chars[0][2])
            dist = float(abs(fitz.Point(run[0][2]) - want))
            if best is None or dist < best[0]:
                best = (dist, (float(origin.x), float(origin.y)), (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)))
            i = full.find(needle, i + 1)
    return best


def _span_at(mpage: fitz.Page, want: fitz.Point, glyphs: int) -> list | None:
    """The ``glyphs`` texttrace glyphs that start at ``want``: exactly ONE glyph lies within 0.02 pt of it and the span is
    contiguous in one texttrace run (so one font).  None when ``glyphs`` is not positive, the anchor is ambiguous or the run ends early.
    """
    if glyphs <= 0:
        return None
    hits = [
        (trace["chars"], i)
        for trace in mpage.get_texttrace()
        for i, c in enumerate(trace["chars"])
        if float(abs(fitz.Point(c[2]) - want)) < LOCATE_MAX_PT
    ]
    if len(hits) != 1:
        return None
    chars, i = hits[0]
    span = chars[i : i + glyphs]
    return span if len(span) == glyphs else None


class _AfterLocate(NamedTuple):
    dist: float
    origin: tuple[float, float]
    box: tuple[float, float, float, float]
    method: str  # "text" or "positional"
    identity: bool  # the glyphs at the anchor spell the claimed replacement


def _locate_after(mpage: fitz.Page, frame: transforms.PageVisualFrame, text: str, anchor: tuple[float, float], glyphs: int) -> _AfterLocate | None:
    """V14 (memo A9): the replacement's glyphs in the reopened file, anchored on the BEFORE-origin rederive located.

    Never on the record's ``after_bbox_raw`` and never on the nearest occurrence of the text anywhere on the page: a second
    occurrence of the replacement (or a target whose glyphs are not the claimed text) must not be measured instead.  The text
    locate must start within 0.02 pt of ``anchor``; failing that, the ``glyphs`` glyphs that start at the anchor are taken
    positionally (unique anchor glyph, one contiguous run) and their text is compared with ``text`` as ``identity``.
    """
    del frame  # texttrace space is the anchor's space already
    want = fitz.Point(anchor)
    best: tuple[float, list] | None = None
    for trace in mpage.get_texttrace() if text else ():
        full = "".join(chr(c[0]) for c in trace["chars"])
        i = full.find(text)
        while i >= 0:
            run = trace["chars"][i : i + len(text)]
            dist = float(abs(fitz.Point(run[0][2]) - want))
            if dist < LOCATE_MAX_PT and (best is None or dist < best[0]):
                best = (dist, run)
            i = full.find(text, i + 1)
    if best is not None:
        return _AfterLocate(best[0], _point(best[1][0][2]), _glyph_union(best[1]), "text", True)
    span = _span_at(mpage, want, glyphs)
    if span is None:
        return None
    spelled = "".join(chr(c[0]) for c in span)
    return _AfterLocate(float(abs(fitz.Point(span[0][2]) - want)), _point(span[0][2]), _glyph_union(span), "positional", spelled == text)


def _point(value: Any) -> tuple[float, float]:
    point = fitz.Point(value)
    return float(point.x), float(point.y)


def _glyph_union(chars: Sequence) -> tuple[float, float, float, float]:
    """The plain min/max union of the glyph boxes, as the brief and the validator define it (``fitz.Rect.__or__`` drops
    an empty box, e.g. the zero-height boxes of glyphs a fallback font could not draw, and so would under-measure)."""
    boxes = [c[3] for c in chars]
    return (
        float(min(b[0] for b in boxes)),
        float(min(b[1] for b in boxes)),
        float(max(b[2] for b in boxes)),
        float(max(b[3] for b in boxes)),
    )


def _undecodable(code: int) -> bool:
    """U+FFFD or a private-use code point: texttrace could not map the glyph to text."""
    return code == 0xFFFD or 0xE000 <= code <= 0xF8FF or 0xF0000 <= code <= 0xFFFFD or 0x100000 <= code <= 0x10FFFD


def _locate_positional(
    mpage: fitz.Page,
    show: ShowOp,
    frame: transforms.PageVisualFrame,
    glyphs: int,
    *,
    sub: tuple[int, int] | None = None,
) -> tuple[float, tuple[float, float], tuple[float, float, float, float]] | None:
    """The brief's positional branch (V13, memo A8) for a show whose texttrace unicode is undecodable.

    Preconditions, each one a refusal: ``glyphs`` (the show's glyph count from rederive's own decode of the bytes) is
    positive; exactly ONE texttrace glyph lies within 0.02 pt of ``show.origin_user * frame.base`` (the anchor); the
    ``glyphs`` glyphs from the anchor are one contiguous span of one texttrace run (so one font); the anchor glyph is
    U+FFFD or private-use (a decodable glyph that merely differs from the show text is a real mismatch, not this).
    ``sub = (first, count)`` takes a slice of that span, as the text locate does.  The caller has already checked
    ``show.origin_reliable``.
    """
    want = fitz.Point(show.origin_user) * frame.base
    span = _span_at(mpage, want, glyphs)
    if span is None or not _undecodable(span[0][0]):
        return None
    pick = span if sub is None else span[sub[0] : sub[0] + sub[1]]
    if not pick or (sub is not None and len(pick) != sub[1]):
        return None
    rect = fitz.Rect(pick[0][3])
    for c in pick[1:]:
        rect |= fitz.Rect(c[3])
    origin = fitz.Point(pick[0][2])
    dist = float(abs(fitz.Point(span[0][2]) - want))
    return (dist, (float(origin.x), float(origin.y)), (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)))


def _locate_target(
    mpage: fitz.Page,
    show: ShowOp,
    frame: transforms.PageVisualFrame,
    text: str,
    *,
    locate_text: str | None = None,
    sub: tuple[int, int] | None = None,
    glyphs: int | None = None,
) -> tuple[tuple[float, tuple[float, float], tuple[float, float, float, float]], str] | None:
    """``(located, method)`` with method ``"text"`` or ``"positional"``, else None: the one locate every consumer shares.

    A show whose replayed origin is untracked is never located: the origin belongs to an earlier show, so a text hit
    there (the 2116 F17 row) would describe the wrong glyphs.  The text locate comes first and the positional one only
    runs when it found nothing within 0.02 pt, so a row the text locate resolves never changes.
    """
    if not show.origin_reliable:
        return None
    found = _locate_trace(mpage, show, frame, text if locate_text is None else locate_text, sub=sub, sub_text=text if sub else None)
    if found is not None and found[0] < LOCATE_MAX_PT:
        return found, "text"
    positional = _locate_positional(mpage, show, frame, glyphs, sub=sub) if glyphs else None
    return None if positional is None else (positional, "positional")


def _glyph_unit(cap: Any) -> int:
    """Bytes per glyph code: 2 for any Type0 font (the /Subtype, not whether a CID codec parsed), else 1."""
    return 2 if cap.subtype == "Type0" else 1


@dataclass(frozen=True)
class _Target:
    """What a row's edit targets inside its show (V12), read off the PDF, never off the record."""

    text: str  # the decoded target
    data: bytes  # its code bytes
    glyph_start: int  # first target glyph inside the show's texttrace run
    glyph_count: int
    whole: bool  # the target is the whole show
    item_lo: int | None  # index of the first string item it touches, None for a whole-show target
    item_hi: int | None  # one past the last
    in_item: tuple[int, int] | None  # decoded byte range inside item ``item_lo`` (F3)


class _Scene:
    """Replay, font capability, page frame and texttrace location of one case's target show.

    Everything is read from ``doc`` (the registry document, never touched) or from an in-memory measurement
    copy: ``get_texttrace`` toggles /Rotate and dirties the page it runs on.
    """

    def __init__(self, case: dict, doc: fitz.Document) -> None:
        self.case = case
        self.doc = doc
        self.closed: set[str] = set()  # unverifiable codes whose check actually ran on this record
        corpus = _g(case, "corpus_case", default={})
        self.page_index = corpus.get("page_index")
        self.show_seq = corpus.get("show_seq")
        if not isinstance(self.page_index, int) or not 0 <= self.page_index < doc.page_count:
            raise _SceneError("page_index", "page index is outside the document")
        self.page = doc[self.page_index]
        self.replay = replay_page_streams([(x, doc.xref_stream(x)) for x in self.page.get_contents()])
        if self.replay.malformed or self.replay.refusal_reason is not None:
            raise _SceneError("replay", "the page streams do not replay")
        if not isinstance(self.show_seq, int) or not 0 <= self.show_seq < len(self.replay.shows):
            raise _SceneError("show_seq", "show sequence is outside the page")
        self.show = self.replay.shows[self.show_seq]
        self.stream = doc.xref_stream(self.show.stream_xref) or b""
        if self.show.font_resource is None:
            raise _SceneError("capability", "the show has no font resource")
        cap = DocumentFontRegistry(doc).capability(self.page, self.show.font_resource)
        if cap is None:
            raise _SceneError("capability", "the font resource has no capability")
        self.cap: FontCapability = cap
        self.text = self._decode(self.show.decoded_bytes)
        self.fallback_used = False  # the PRIMARY probe ran reason-only (V13, Q5); the whole-show second view never sets it
        self.fallback_mode: str | None = None  # "unique" or "shared" (Q13) when fallback_used

    @cached_property
    def string_items(self) -> list[tuple[int, int, bytes]] | None:
        """``(start, end, payload)`` of every string item of the show's operand, in stream offsets; None when it will not lex."""
        lo, hi = self.show.string_start, self.show.string_end
        if not 0 <= lo <= hi <= len(self.stream):
            return None
        data = self.stream[lo:hi]
        items: list[tuple[int, int, bytes]] = []
        for tok in lex_content_stream(data):
            raw = data[tok.start : tok.end]
            try:
                if tok.kind is TokenKind.STRING:
                    items.append((lo + tok.start, lo + tok.end, decode_literal_string(raw)))
                elif tok.kind is TokenKind.HEXSTRING:
                    items.append((lo + tok.start, lo + tok.end, decode_hex_string(raw)))
                elif tok.kind is TokenKind.MALFORMED:
                    return None
            except ValueError:
                return None
        return items if b"".join(p for _, _, p in items) == self.show.decoded_bytes else None

    @cached_property
    def target_info(self) -> tuple[_Target, list[Divergence]]:
        return _derive_target(self)

    @property
    def target(self) -> _Target:
        return self.target_info[0]

    def _decode(self, data: bytes) -> str:
        if self.cap.cid is not None:
            decoded = self.cap.cid.decode_show_bytes(data)
            if not isinstance(decoded, str):
                raise _SceneError("source_text", "the show does not decode through the font registry")
            return decoded
        return data.decode("latin-1")

    @cached_property
    def meas(self) -> fitz.Document:
        return fitz.open("pdf", self.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))

    @cached_property
    def mpage(self) -> fitz.Page:
        return self.meas[self.page_index]

    @cached_property
    def frame(self) -> transforms.PageVisualFrame | None:
        return transforms.page_visual_frame_or_none(self.mpage)

    @property
    def glyph_total(self) -> int:
        """Glyphs of the whole show from rederive's own decode of its bytes (a Type0 code is 2 bytes, codec or not)."""
        return len(self.show.decoded_bytes) // _glyph_unit(self.cap)

    @cached_property
    def locate_info(self) -> tuple[tuple[float, tuple[float, float], tuple[float, float, float, float]], str] | None:
        if self.frame is None:
            return None
        tgt = self.target
        if tgt.whole:
            return _locate_target(self.mpage, self.show, self.frame, self.text, glyphs=self.glyph_total)
        return _locate_target(
            self.mpage, self.show, self.frame, tgt.text, locate_text=self.text, sub=(tgt.glyph_start, tgt.glyph_count), glyphs=self.glyph_total
        )

    @property
    def located(self) -> tuple[float, tuple[float, float], tuple[float, float, float, float]] | None:
        return None if self.locate_info is None else self.locate_info[0]

    @property
    def locate_method(self) -> str | None:
        return None if self.locate_info is None else self.locate_info[1]

    @property
    def unlocatable(self) -> bool:
        """The page frame is fine and rederive's own locate found nothing (or the origin is untracked)."""
        return self.frame is not None and self.locate_info is None

    @cached_property
    def pixmap_meta(self) -> tuple[int, int, int, int]:
        pix = self.mpage.get_pixmap(dpi=verify._VERIFY_DPI)
        return (pix.width, pix.height, pix.stride, pix.n)

    @cached_property
    def trm_scale(self) -> float:
        linear = transforms.combined_linear(self.show.tm, self.show.ctm)
        return float(math.hypot(linear[0], linear[1]))

    @cached_property
    def adv(self) -> tuple[dict, list[Divergence]]:
        return _measure_advances(self)

    def target_visual(self) -> tuple[float, float, float, float] | None:
        """The located target box in visual space, else None."""
        if self.located is None or self.frame is None or self.located[0] >= LOCATE_MAX_PT:
            return None
        rect = fitz.Rect(self.located[2]) * self.frame.quarter_turn
        return (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))

    def close(self) -> None:
        if "meas" in self.__dict__:
            self.meas.close()


def _idx_pair(value: object) -> tuple[int, int] | None:
    """Two strict (non-bool) ints, else None."""
    if isinstance(value, list) and len(value) == 2 and all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        return (value[0], value[1])
    return None


def _derive_target(scene: _Scene) -> tuple[_Target, list[Divergence]]:
    """The slice of the show the row edits, derived from the PDF (V12; brief revision >= 3).

    ``item_range`` = half-open INDEX range of the string items of the TJ array (null for a Tj, a quote operator and a
    whole-array target); ``byte_range_in_item`` = decoded bytes of item ``i0`` (F3, so ``i1 == i0 + 1``).  A malformed
    pointer is a divergence and the target falls back to the whole show, so the other checks still run.  Rows below
    revision 3 never meant a slice: their target is the whole show.
    """
    case, show = scene.case, scene.show
    unit = _glyph_unit(scene.cap)
    whole = _Target(scene.text, show.decoded_bytes, 0, len(show.decoded_bytes) // unit, True, None, None, None)
    if eb._rev(case) < 3:
        return whole, []
    target = _d(case.get("target"))
    item_range, byte_range = target.get("item_range"), target.get("byte_range_in_item")
    if item_range is None and byte_range is None:
        return whole, []
    items = scene.string_items
    if items is None:
        return whole, [_div("item_range", item_range, "unlexable")]
    n = len(items)
    if item_range is None:
        if show.operator == "TJ" or n != 1:
            return whole, [_div("item_range", item_range, n)]  # an F3 target inside a TJ names its item
        lo, hi = 0, 1
    else:
        pair = _idx_pair(item_range)
        if pair is None or show.operator != "TJ" or not 0 <= pair[0] < pair[1] <= n:
            return whole, [_div("item_range", item_range, n if show.operator == "TJ" else None)]
        lo, hi = pair
    in_item: tuple[int, int] | None = None
    if byte_range is not None:
        if hi != lo + 1:
            return whole, [_div("item_range", item_range, [lo, lo + 1])]  # an F3 target is exactly one item
        payload = items[lo][2]
        bpair = _idx_pair(byte_range)
        if bpair is None or not 0 <= bpair[0] < bpair[1] <= len(payload) or bpair[0] % unit or bpair[1] % unit:
            return whole, [_div("byte_range_in_item", byte_range, len(payload))]
        in_item = bpair
        data = payload[bpair[0] : bpair[1]]
        start_bytes = sum(len(p) for _, _, p in items[:lo]) + bpair[0]
    else:
        data = b"".join(p for _, _, p in items[lo:hi])
        start_bytes = sum(len(p) for _, _, p in items[:lo])
    try:
        text = scene._decode(data)
    except _SceneError:
        return whole, [_div("source_text", None, "the show does not decode through the font registry")]
    is_whole = start_bytes == 0 and data == show.decoded_bytes
    return _Target(text, data, start_bytes // unit, len(data) // unit, is_whole, lo, hi, in_item), []


def _expected_subclass(scene: _Scene, derive_divs: list[Divergence]) -> str | None:
    """``no_source_match_subclass`` the derived target implies (V12); None when the target is the whole show or malformed."""
    tgt = scene.target
    if tgt.whole or derive_divs or tgt.item_lo is None or tgt.item_hi is None:
        return None
    if tgt.item_hi - tgt.item_lo >= 2:
        return "spans_tj_items"
    return "substring_of_multi_item_tj_item" if len(scene.string_items or ()) > 1 else "substring_of_single_string_item"


def _mutation(case: dict) -> dict | None:
    mut = case.get("mutation")
    return mut if isinstance(mut, dict) else None


def _changes(case: dict) -> list[dict]:
    mut = _mutation(case)
    return [c for c in (mut.get("changes") or []) if isinstance(c, dict)] if mut else []


_STRING_KINDS = frozenset({TokenKind.STRING, TokenKind.HEXSTRING})


def _new_token_kinds(change: dict) -> set[TokenKind] | None:
    """The token kinds rederive's own lexer finds in a change's new operand (whitespace aside); None when it is not lexable hex."""
    raw = change.get("new_operand_bytes_hex")
    if not isinstance(raw, str):
        return None
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return None
    kinds = {tok.kind for tok in lex_content_stream(data)} - {TokenKind.WHITESPACE}
    return None if TokenKind.MALFORMED in kinds else kinds


def _operand_index(scene: _Scene) -> int | None:
    """Index of the change that carries the show's string operand (V14, memo A9); None when there is none or the shape is wrong.

    Every row but a MULTI-change canary reads ``changes[0]``, as before.  A canary may carry operator insertions around the
    string (Tc, Tf, a drawing op): exactly one change must hold a STRING/HEXSTRING lying inside the show's operator span
    ``[op_start, op_end]`` of its own stream, and every other change must be a zero-width insertion of tokens that include an
    operator and no string.  Anything else is ``canary_changes_shape``, a divergence the record cannot talk its way past.
    """
    changes = _changes(scene.case)
    if not changes:
        return None
    if len(changes) == 1 or _g(scene.case, "mutation", "path") != "canary":
        return 0
    show = scene.show
    picked: int | None = None
    for i, change in enumerate(changes):
        kinds = _new_token_kinds(change)
        start, end_old = change.get("start"), change.get("end_old")
        if kinds is None or not (isinstance(start, int) and isinstance(end_old, int)):
            return None
        if kinds & _STRING_KINDS:
            inside = change.get("stream_xref") == show.stream_xref and show.op_start <= start <= end_old <= show.op_end
            if picked is not None or not inside:
                return None
            picked = i
        elif not (start == end_old and TokenKind.OPERATOR in kinds):
            return None
    return picked


def _operand_change(scene: _Scene) -> dict | None:
    index = _operand_index(scene)
    return None if index is None else _changes(scene.case)[index]


def _advances(case: dict) -> list[dict]:
    mut = _mutation(case)
    adv = mut.get("advance") if mut else None
    if isinstance(adv, dict):
        return [adv]
    return [a for a in adv if isinstance(a, dict)] if isinstance(adv, list) else []


# --------------------------------------------------------------------------
# structure keys (design H2)
# --------------------------------------------------------------------------
_REF = re.compile(r"(\d+)\s+(\d+)\s+R(?![A-Za-z0-9])")
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_NAME = re.compile(r"/[^\s()<>\[\]{}/%]*")
_WORD = re.compile(r"[A-Za-z]+")
_OPAQUE: tuple[str] = ("opaque",)  # a name, string, dictionary or keyword: it holds an index, it is never read


def _skip_string(text: str, i: int) -> int:
    """Index after the literal string that opens at ``text[i]`` (escapes and nested parentheses)."""
    depth = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _skip_dict(text: str, i: int) -> int:
    """Index after the ``<< ... >>`` that opens at ``text[i]``."""
    depth = 0
    while i < len(text):
        if text.startswith("<<", i):
            depth += 1
            i += 2
        elif text.startswith(">>", i):
            depth -= 1
            i += 2
            if depth == 0:
                return i
        elif text[i] == "(":
            i = _skip_string(text, i)
        else:
            i += 1
    return len(text)


def _parse_array(text: str) -> list[Any]:
    """Nested lists of ints, ``("ref", n)``, ``None`` (null) and ``_OPAQUE`` from one PDF array string (``xref_get_key`` output).

    Every entry of the array takes exactly one slot, so ``entry[mcid]`` indexes what the file says; a null, a name, a
    string or a dictionary used to vanish and shift every later index down by one.
    """
    stack: list[list[Any]] = [[]]
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == "[":
            stack.append([])
            i += 1
        elif ch == "]":
            if len(stack) > 1:
                done = stack.pop()
                stack[-1].append(done)
            i += 1
        elif ch == "(":
            i = _skip_string(text, i)
            stack[-1].append(_OPAQUE)
        elif text.startswith("<<", i):
            i = _skip_dict(text, i)
            stack[-1].append(_OPAQUE)
        elif ch == "<":
            end = text.find(">", i)
            i = n if end < 0 else end + 1
            stack[-1].append(_OPAQUE)
        elif ch == "/":
            m = _NAME.match(text, i)
            i = m.end() if m else i + 1
            stack[-1].append(_OPAQUE)
        elif ch == "%":
            end = text.find("\n", i)
            i = n if end < 0 else end + 1
        else:
            m = _REF.match(text, i)
            if m:
                stack[-1].append(("ref", int(m.group(1))))
                i = m.end()
                continue
            m = _NUMBER.match(text, i)
            if m:
                stack[-1].append(int(float(m.group(0))))
                i = m.end()
                continue
            m = _WORD.match(text, i)
            if m:
                stack[-1].append(None if m.group(0) == "null" else _OPAQUE)
                i = m.end()
                continue
            i += 1
    return stack[0][0] if stack[0] and isinstance(stack[0][0], list) else stack[0]


def _array_of(doc: fitz.Document, xref: int, key: str) -> list[Any] | None:
    kind, value = doc.xref_get_key(xref, key)
    if kind == "array":
        return _parse_array(value)
    if kind == "xref":
        n = int(value.split()[0])
        return _parse_array(doc.xref_object(n, compressed=True))
    return None


def _tree_lookup(doc: fitz.Document, node: int, number: int, seen: set[int], depth: int = 0) -> Any:
    """The value stored at integer ``number`` in a number tree (``/Nums`` plus recursive ``/Kids``)."""
    if node in seen or depth > 8:
        return None
    seen.add(node)
    nums = _array_of(doc, node, "Nums")
    if nums is not None:
        for i in range(0, len(nums) - 1, 2):
            if nums[i] == number:
                return nums[i + 1]
    kids = _array_of(doc, node, "Kids")
    for kid in kids or []:
        if isinstance(kid, tuple) and kid[0] == "ref":
            found = _tree_lookup(doc, kid[1], number, seen, depth + 1)
            if found is not None:
                return found
    return None


def _structelem_keys(doc: fitz.Document, page: fitz.Page, mcid: int | None) -> list[str] | None:
    """Null when the page has no /StructParents; else the subset of (ActualText, Alt, E, Lang) on the StructElem."""
    kind, value = doc.xref_get_key(page.xref, "StructParents")
    if kind == "null":
        return None
    try:
        number = int(float(value))
        if mcid is None:
            return []
        catalog = doc.pdf_catalog()
        k_root, v_root = doc.xref_get_key(catalog, "StructTreeRoot")
        if k_root != "xref":
            return []
        root = int(v_root.split()[0])
        k_tree, v_tree = doc.xref_get_key(root, "ParentTree")
        if k_tree == "xref":
            tree_node = int(v_tree.split()[0])
            entry = _tree_lookup(doc, tree_node, number, set())
        elif k_tree == "dict":
            nums = _array_of(doc, root, "ParentTree/Nums")
            entry = None
            for i in range(0, len(nums or []) - 1, 2):
                if (nums or [])[i] == number:
                    entry = (nums or [])[i + 1]
        else:
            return []
        if isinstance(entry, tuple) and entry[0] == "ref":
            entry = _parse_array(doc.xref_object(entry[1], compressed=True))
        if not isinstance(entry, list) or not 0 <= mcid < len(entry):
            return []
        element = entry[mcid]
        if not (isinstance(element, tuple) and element[0] == "ref"):
            return []
        return [key for key in STRUCTELEM_VOCAB if doc.xref_get_key(element[1], key)[0] != "null"]
    except (ValueError, RuntimeError, IndexError):
        return []


def _wrapper_mcid(doc: fitz.Document, wrapper: Any) -> int | None:
    """``/MCID`` of the inline property dictionary in front of the opening BDC, if there is one."""
    data = doc.xref_stream(wrapper.stream_xref) or b""
    end = wrapper.open_op_end
    toks = []
    for tok in lex_content_stream(data):
        if tok.end > end:
            break
        if tok.kind is not TokenKind.WHITESPACE:
            toks.append(tok)
    if not toks or toks[-1].end != end or len(toks) < 2 or toks[-2].kind is not TokenKind.DICT_CLOSE:
        return None
    depth = 0
    start = None
    for idx in range(len(toks) - 2, -1, -1):
        if toks[idx].kind is TokenKind.DICT_CLOSE:
            depth += 1
        elif toks[idx].kind is TokenKind.DICT_OPEN:
            depth -= 1
            if depth == 0:
                start = idx
                break
    if start is None:
        return None
    body = toks[start + 1 : len(toks) - 2]
    level = 0
    for i, tok in enumerate(body):
        if tok.kind in (TokenKind.DICT_OPEN, TokenKind.ARRAY_OPEN):
            level += 1
        elif tok.kind in (TokenKind.DICT_CLOSE, TokenKind.ARRAY_CLOSE):
            level -= 1
        elif level == 0 and tok.kind is TokenKind.NAME and data[tok.start : tok.end] == b"/MCID":
            nxt = body[i + 1] if i + 1 < len(body) else None
            if nxt is not None and nxt.kind is TokenKind.NUMBER:
                try:
                    return int(float(data[nxt.start : nxt.end]))
                except ValueError:
                    return None
    return None


# --------------------------------------------------------------------------
# step 1: resolve the source
# --------------------------------------------------------------------------
@dataclass
class _Resolved:
    doc: fitz.Document | None = None
    data: bytes | None = None
    quarantine: list[str] = field(default_factory=list)
    verified: bool = False
    slug: str | None = None


def _add(codes: list[str], code: str) -> None:
    if code not in codes:
        codes.append(code)


def _resolve(case: dict, batch_dir: Path, registry: CorpusRegistry) -> _Resolved:
    out = _Resolved()
    source = _d(case.get("source"))
    case_id = str(case.get("case_id"))
    sha = source.get("sha256")
    prov = source.get("provenance")
    if not isinstance(sha, str):
        _add(out.quarantine, "before_pdf_mismatch")
        return out
    # the bundle's own before.pdf is only hashed, with hashlib; it is never opened
    bundle_pdf = Path(batch_dir) / "candidates" / case_id / "before.pdf"
    try:
        # a case id with path parts is a schema violation; it never steers a read outside candidates/
        if _CASE_DIR_RE.fullmatch(case_id) and bundle_pdf.is_file() and _sha256(bundle_pdf.read_bytes()) != sha:
            _add(out.quarantine, "before_pdf_mismatch")
    except OSError:
        _add(out.quarantine, "before_pdf_mismatch")

    if prov == "synthetic":
        return _resolve_synthetic(case, source, out)

    data: bytes | None = None
    if prov in ("public", "local_unrecorded", "proprietary"):
        entry = registry.by_sha(sha, prov)
        if entry is not None:
            data = _read_verified(registry.root / entry.relative_path, sha, registry.root, Path(batch_dir))
            out.slug = entry.slug
            if data is None:
                _add(out.quarantine, "before_pdf_mismatch")
            else:
                out.verified = True
        elif prov == "proprietary":
            _add(out.quarantine, "before_pdf_mismatch")  # unresolvable: relative_path is null by brief 5.4
        else:
            _add(out.quarantine, "provenance_unverified")
            rel = source.get("relative_path")
            if isinstance(rel, str):
                data = _read_verified(registry.root / rel, sha, registry.root, Path(batch_dir))
            if data is None:
                _add(out.quarantine, "before_pdf_mismatch")
    else:
        _add(out.quarantine, "before_pdf_mismatch")
    if data is not None:
        out.data = data
        out.doc = fitz.open("pdf", data)
    return out


def _resolve_synthetic(case: dict, source: dict, out: _Resolved) -> _Resolved:
    builder = source.get("synthetic_builder")
    name = builder.get("callable") if isinstance(builder, dict) else None
    if name not in SYNTHETIC_ALLOWLIST:
        _add(out.quarantine, "builder_not_allowlisted")
        return out
    kwargs = _d(_d(builder).get("kwargs"))
    module_name, _, func_name = str(name).rpartition(".")
    try:
        fixture = getattr(importlib.import_module(module_name), func_name)(**kwargs)
        data = fixture.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)
        fixture.doc.close()
    except Exception:  # noqa: BLE001 - an unbuildable fixture is an unresolvable source
        logger.warning("allowlisted synthetic builder failed", exc_info=True)
        _add(out.quarantine, "before_pdf_mismatch")
        return out
    doc = fitz.open("pdf", data)
    changes = _changes(case)
    ok = True
    for change in changes:
        stream = doc.xref_stream(change.get("stream_xref")) if isinstance(change.get("stream_xref"), int) else None
        if stream is None or _sha256(stream) != change.get("old_stream_sha256"):
            ok = False
    target_xref = _g(case, "target", "stream_xref")
    if not changes and (not isinstance(target_xref, int) or doc.xref_stream(target_xref) is None):
        ok = False
    if not ok:
        _add(out.quarantine, "before_pdf_mismatch")
        doc.close()
        return out
    out.data = data
    out.doc = doc
    out.verified = False  # H4: a synthetic source counts toward no lineage
    return out


def resolve_source(
    case: dict, batch_dir: Path, registry: CorpusRegistry
) -> tuple[fitz.Document | None, list[str], bool]:
    """``(document, quarantine codes, provenance_verified)``; the document is None when nothing may be measured."""
    resolved = _resolve(case, Path(batch_dir), registry)
    return resolved.doc, resolved.quarantine, resolved.verified


# --------------------------------------------------------------------------
# step 2: recompute the fixture-bound fields
# --------------------------------------------------------------------------
def _check_text_state(prefix: str, rec: object, scene_show: ShowOp, divs: list[Divergence]) -> None:
    if not isinstance(rec, dict):
        divs.append(_div(prefix, rec, "object"))
        return
    show = scene_show
    tf = _d(rec.get("Tf"))
    _cmp_eq(divs, f"{prefix}.Tf.resource", tf.get("resource"), show.font_resource)
    _cmp_num(divs, f"{prefix}.Tf.size", tf.get("size"), show.font_size, TOL_STATE)
    for key, got in (("Tm", show.tm), ("CTM", show.ctm)):
        recv = rec.get(key)
        if not (isinstance(recv, list) and len(recv) == 6 and all(_num_close(a, b, TOL_STATE) for a, b in zip(recv, got, strict=True))):
            divs.append(_div(f"{prefix}.{key}", recv, list(got), TOL_STATE))
    for scalar_key, scalar in (
        ("Tz", show.hscale),
        ("Tc", show.char_spacing),
        ("Tw", show.word_spacing),
        ("Ts", show.rise),
        ("TL", show.leading),
    ):
        _cmp_num(divs, f"{prefix}.{scalar_key}", rec.get(scalar_key), scalar, TOL_STATE)
    _cmp_eq(divs, f"{prefix}.Tr", rec.get("Tr"), show.render_mode)
    origin = rec.get("origin_user")
    if not (isinstance(origin, list) and len(origin) == 2 and all(_num_close(a, b, TOL_STATE) for a, b in zip(origin, show.origin_user, strict=True))):
        divs.append(_div(f"{prefix}.origin_user", origin, list(show.origin_user), TOL_STATE))
    _cmp_eq(divs, f"{prefix}.origin_reliable", rec.get("origin_reliable"), show.origin_reliable)
    _cmp_eq(divs, f"{prefix}.q_depth", rec.get("q_depth"), show.gs_depth)
    _cmp_eq(divs, f"{prefix}.in_bt", rec.get("in_bt"), show.in_bt)
    linear = transforms.combined_linear(show.tm, show.ctm)
    sign = "+" if linear[0] * linear[3] - linear[1] * linear[2] >= 0.0 else "-"
    _cmp_eq(divs, f"{prefix}.det_sign", rec.get("det_sign"), sign)
    _cmp_eq(divs, f"{prefix}.extgstate_names", rec.get("extgstate_names"), list(show.extgstate_names))


def _check_wrappers(scene: _Scene, divs: list[Divergence]) -> None:
    rec_stack = _g(scene.case, "text_state", "before", "wrapper_stack", default=[])
    if not isinstance(rec_stack, list):
        divs.append(_div("wrapper_stack", rec_stack, "list"))
        return
    wrappers = scene.replay.wrappers_for(scene.show)
    if len(rec_stack) != len(wrappers):
        divs.append(_div("wrapper_stack.length", len(rec_stack), len(wrappers)))
        return
    for k, (rec, got) in enumerate(zip(rec_stack, wrappers, strict=True)):
        if not isinstance(rec, dict):
            divs.append(_div(f"wrapper_stack.{k}", rec, "object"))
            return
        _cmp_eq(divs, "wrapper.kind", rec.get("kind"), got.operator)
        _cmp_eq(divs, "wrapper.tag", rec.get("tag"), got.tag)
        _cmp_eq(divs, "wrapper.props_kind", rec.get("props_kind"), got.props_kind)
        _cmp_eq(divs, "wrapper.props_name", rec.get("props_name"), got.props_name)
        if rec.get("props_keys") != list(got.props_dict_keys):
            divs.append(_div("props_keys", rec.get("props_keys"), list(got.props_dict_keys)))
        want = _structelem_keys(scene.doc, scene.page, _wrapper_mcid(scene.doc, got))
        if rec.get("structelem_keys") != want:
            divs.append(_div("structelem_keys", rec.get("structelem_keys"), want))
    else:
        scene.closed.add("props_keys")


def _new_operand_payloads(change: dict) -> list[bytes] | None:
    raw = change.get("new_operand_bytes_hex")
    if not isinstance(raw, str):
        return None
    try:
        return _payloads(bytes.fromhex(raw))
    except ValueError:
        return None


def _int_pair(value: object, limit: int | None) -> bool:
    """A two-int range, inside ``[0, limit]`` when a limit is given."""
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, int) and not isinstance(v, bool) for v in value)
        and 0 <= value[0] <= value[1]
        and (limit is None or value[1] <= limit)
    )


def _check_changes(scene: _Scene, divs: list[Divergence]) -> None:
    case = scene.case
    mut = _mutation(case)
    if mut is None:
        return
    kind = _g(case, "corpus_case", "font_kind")
    if len(_changes(case)) > 1 and _g(case, "mutation", "path") == "canary" and _operand_index(scene) is None:
        divs.append(_div("canary_changes_shape", len(_changes(case)), None))
    glyph_cids: set[int] = set()
    for g in _g(case, "glyph_identity", default=[]) or []:
        code = g.get("code_bytes_hex") if isinstance(g, dict) else None
        if isinstance(code, str):
            try:
                glyph_cids |= set(_cids(bytes.fromhex(code)))
            except ValueError:
                continue
    complete = True  # every change reached its last check
    fragment_ran = True
    type0_ran = kind == "type0"
    indexed = eb._rev(case) >= 3  # V12: item_range is an index range, original is the target slice
    span_ran, span_ok = False, True
    changes = _changes(case)
    for i, change in enumerate(changes):
        p = f"mutation.changes.{i}"
        xref = change.get("stream_xref")
        stream = scene.doc.xref_stream(xref) if isinstance(xref, int) else None
        if stream is None:
            divs.append(_div(f"{p}.stream_xref", xref, None))
            complete = fragment_ran = type0_ran = False
            continue
        _cmp_eq(divs, "old_stream_sha256", change.get("old_stream_sha256"), _sha256(stream))
        start, end_old = change.get("start"), change.get("end_old")
        if not (isinstance(start, int) and isinstance(end_old, int) and 0 <= start <= end_old <= len(stream)):
            divs.append(_div(f"{p}.range", [start, end_old], len(stream)))
            complete = fragment_ran = type0_ran = False
            continue
        old = stream[start:end_old]
        _cmp_eq(divs, "old_operand_sha256", change.get("old_operand_sha256"), _sha256(old))
        advs = _advances(case)
        if advs and advs[0].get("K_written") is not None:
            # K_sum is read off the fixture, never off the bundle: brief 5.4 nulls old_operand_bytes_hex on non-public rows
            want_sum, want_drop = _expected_kerns(mut.get("splice_kind"), old)
            _cmp_num(divs, "K_sum", advs[0].get("K_sum"), want_sum, TOL_SCALAR)
            if eb._rev(case) >= 3 and mut.get("splice_kind") == "tj_run":
                scene.closed.add("k_sum_unverified")  # the recorded K_sum the validator sized a non-public strip by
            if mut.get("splice_kind") == "tj_run":
                got_drop = advs[0].get("internal_kerns_dropped")
                if not (isinstance(got_drop, list) and len(got_drop) == len(want_drop) and all(_num_close(a, b, TOL_SCALAR) for a, b in zip(got_drop, want_drop, strict=True))):
                    divs.append(_div("internal_kerns_dropped", got_drop if isinstance(got_drop, list) else None, want_drop))
        bounds: set[int] = set()
        token_kinds: dict[tuple[int, int], TokenKind] = {}
        for tok in lex_content_stream(stream):
            bounds.add(tok.start)
            bounds.add(tok.end)
            token_kinds[(tok.start, tok.end)] = tok.kind
        aligned = start in bounds and end_old in bounds
        _cmp_eq(divs, "token_aligned", change.get("token_aligned"), aligned)
        rec_old = change.get("old_operand_bytes_hex")
        if rec_old is not None:
            _cmp_eq(divs, "old_operand_bytes_hex", rec_old, old.hex().upper())
        new_payloads = _new_operand_payloads(change)
        if new_payloads is None:
            divs.append(_div(f"{p}.new_operand_bytes_hex", "unlexable", None))
            fragment_ran = type0_ran = False
            continue
        splice = mut.get("splice_kind")
        fragment = splice in ("string_fragment", "fragment_split")
        item_range, byte_range = _g(case, "target", "item_range"), _g(case, "target", "byte_range_in_item")
        item_bytes: bytes | None = None
        if indexed:
            if fragment:
                picked = _indexed_fragment(scene, splice, change, start, end_old, divs)
                if picked is None:
                    fragment_ran = False
                    span_ok = False
                    byte_range = None
                else:
                    item_bytes, byte_range = picked
                    span_ran = True
            elif splice in INDEXED_SPLICES:
                if _indexed_run(scene, change, stream, start, end_old, splice, divs):
                    span_ran = span_ran or (splice in ("tj_item", "tj_run") and scene.target.item_lo is not None)
                else:
                    span_ok = False
        else:
            if fragment:
                if not (_int_pair(item_range, len(stream)) and _int_pair(byte_range, None)):
                    divs.append(_div("fragment_ranges", item_range, byte_range))
                    fragment_ran = False
                    item_range = byte_range = None
            if fragment and item_range is not None:
                # the item the H1 remeasure reads must be ONE string token that the change actually edits
                token = token_kinds.get((item_range[0], item_range[1]))
                if token not in (TokenKind.STRING, TokenKind.HEXSTRING) or not (start <= item_range[0] and item_range[1] <= end_old):
                    divs.append(_div("fragment_item_range", item_range, [start, end_old]))
                    fragment_ran = False
                    item_range = byte_range = None
            if fragment and item_range is not None and byte_range is not None:
                item_bytes = b"".join(_payloads(stream[item_range[0] : item_range[1]]) or [])
        if fragment and item_bytes is not None and byte_range is not None:
            item = item_bytes
            prefix, suffix = item[: byte_range[0]], item[byte_range[1] :]
            ok = False
            if len(new_payloads) == 1:
                whole = new_payloads[0]
                ok = whole.startswith(prefix) and whole.endswith(suffix) and len(whole) >= len(prefix) + len(suffix)
            elif len(new_payloads) == 3:
                ok = new_payloads[0] == prefix and new_payloads[2] == suffix
            elif len(new_payloads) == 2:
                # (middle)(suffix) when the slice starts the item, (prefix)(middle) when it ends it; the absent side is empty
                if byte_range[0] == 0:
                    ok = new_payloads[1] == suffix
                elif byte_range[1] == len(item):
                    ok = new_payloads[0] == prefix
            if not ok:
                divs.append(_div("fragment_prefix_mismatch", None, None))
        if kind == "type0":
            old_cids = set(_cids(b"".join(_payloads(old) or [])))
            new_cids = set(_cids(b"".join(new_payloads)))
            if not new_cids <= (glyph_cids | old_cids):
                divs.append(_div("type0_cid_unbound", sorted(new_cids - glyph_cids - old_cids), None))
    if changes and complete:
        scene.closed |= {"old_stream_sha256", "token_aligned"}
        if mut.get("splice_kind") in ("string_fragment", "fragment_split") and fragment_ran:
            scene.closed.add("fragment_prefix_mismatch")
        if type0_ran:
            scene.closed.add("type0_cid_unbound")
        if indexed and span_ran and span_ok:
            scene.closed.add("item_range_span")


INDEXED_SPLICES = ("tj_item", "tj_run", "string_token", "whole_operator")


def _indexed_fragment(
    scene: _Scene, splice: object, change: dict, start: int, end_old: int, divs: list[Divergence]
) -> tuple[bytes, tuple[int, int]] | None:
    """F3 under the index reading: ``(item payload, byte range inside it)``, or None with the divergence appended.

    A ``string_fragment`` change is exactly the token of item ``i0``; a ``fragment_split`` in a TJ replaces that token
    too, and the Tj form replaces the whole operator, which must contain the token.
    """
    case, show, tgt, items = scene.case, scene.show, scene.target, scene.string_items
    item_range, byte_range = _g(case, "target", "item_range"), _g(case, "target", "byte_range_in_item")
    if tgt.in_item is None or tgt.item_lo is None or items is None:
        divs.append(_div("fragment_ranges", item_range, byte_range))
        return None
    s, e, payload = items[tgt.item_lo]
    if change.get("stream_xref") != show.stream_xref:
        ok = False
    elif splice == "string_fragment" or show.operator == "TJ":
        ok = (start, end_old) == (s, e)
    else:
        ok = start <= s and e <= end_old and show.op_start <= start and end_old <= show.op_end
    if not ok:
        divs.append(_div("fragment_item_range", item_range, [s, e]))
        return None
    return payload, tgt.in_item


def _indexed_run(scene: _Scene, change: dict, stream: bytes, start: int, end_old: int, splice: object, divs: list[Divergence]) -> bool:
    """tj_item / tj_run / string_token / whole_operator under the index reading.

    The lexed span of items ``[i0, i1)`` is the change (tj_item, tj_run) and the decoded string payloads of the change
    (kerns excluded) are the derived target.  False when a divergence was appended.
    """
    show, tgt, items = scene.show, scene.target, scene.string_items
    sliced = splice in ("tj_item", "tj_run")
    if change.get("stream_xref") != show.stream_xref:
        if sliced:
            divs.append(_div("change_stream", change.get("stream_xref"), show.stream_xref))
        return not sliced
    ok = True
    if sliced and tgt.item_lo is not None and tgt.item_hi is not None and items is not None:
        want = (items[tgt.item_lo][0], items[tgt.item_hi - 1][1])
        if (start, end_old) != want:
            divs.append(_div("item_range_span", _g(scene.case, "target", "item_range"), list(want)))
            ok = False
    payloads = _payloads(stream[start:end_old])
    joined = None if payloads is None else b"".join(payloads)
    if joined != tgt.data:
        divs.append(_div("change_target_bytes", None if joined is None else _sha256(joined), _sha256(tgt.data)))
        ok = False
    return ok


def _recompute(scene: _Scene) -> list[Divergence]:
    divs: list[Divergence] = []
    case, show = scene.case, scene.show
    target = _d(case.get("target"))
    frame = scene.frame
    _cmp_eq(divs, "target.stream_xref", target.get("stream_xref"), show.stream_xref)
    _cmp_eq(divs, "target.op_start", target.get("op_start"), show.op_start)
    _cmp_eq(divs, "target.op_end", target.get("op_end"), show.op_end)
    _cmp_eq(divs, "target.operator", target.get("operator"), show.operator)
    _cmp_eq(divs, "target.string_kind", target.get("string_kind"), show.string_kind)
    _cmp_eq(divs, "target.array_item_count", target.get("array_item_count"), show.array_item_count)
    _cmp_eq(divs, "target.font_xref", target.get("font_xref"), scene.cap.font_xref)
    source = _d(case.get("source"))
    _cmp_eq(divs, "source.page_rotation", source.get("page_rotation"), scene.page.rotation)
    _cmp_eq(divs, "source.page_count", source.get("page_count"), scene.doc.page_count)
    corpus = _d(case.get("corpus_case"))
    kind = {"Type0": "type0", "Type3": "type3"}.get(scene.cap.subtype, "simple")  # /Subtype (V13), not whether a CID codec parsed
    _cmp_eq(divs, "font_kind", corpus.get("font_kind"), kind)
    _cmp_eq(divs, "font_resource", corpus.get("font_resource"), show.font_resource)
    _check_text_state("text_state.before", _g(case, "text_state", "before"), show, divs)
    _check_wrappers(scene, divs)
    # counts and source text
    ts = _g(case, "text_state", default={})
    _cmp_eq(divs, "show_count_before", ts.get("show_count_before"), len(scene.replay.shows))
    _cmp_eq(divs, "operator_count_before", ts.get("operator_count_before"), _operator_count(scene.doc, scene.page))
    scene.closed.add("operator_count_before")
    tgt, tgt_divs = scene.target_info
    divs += tgt_divs
    text_sha = _sha256(tgt.text)  # the target slice (the whole show below brief revision 3)
    _cmp_eq(divs, "original_sha256", _g(case, "corpus_case", "original_sha256"), text_sha)
    original = _g(case, "corpus_case", "original")
    if original is not None:
        _cmp_eq(divs, "original", _sha256(original), text_sha)
    show_sha = _g(case, "corpus_case", "show_text_sha256")
    if show_sha is not None:
        _cmp_eq(divs, "show_text_sha256", show_sha, _sha256(scene.text))
    want_subclass = _expected_subclass(scene, tgt_divs)
    if want_subclass is not None:
        _cmp_eq(divs, "no_source_match_subclass", target.get("no_source_match_subclass"), want_subclass)
    _check_changes(scene, divs)
    if frame is None:
        if case.get("status") != "blocked":
            divs.append(_div("frame", case.get("status"), None))
        return divs
    _cmp_num(divs, "user_unit", target.get("user_unit"), frame.user_unit, TOL_STATE)
    scene.closed.add("user_unit")
    _cmp_num(divs, "trm_scale", target.get("trm_scale"), scene.trm_scale, TOL_SCALAR)
    on_untracked = [k for k in GEOMETRY_KEYS if not show.origin_reliable and target.get(k) is not None]
    if on_untracked:
        divs.append(_div("geometry_on_untracked_origin", on_untracked, None))  # the numbers describe an earlier show
    located = scene.located
    if located is not None:  # a miss is `target_unlocatable` (a quarantine code of its own), never a divergence
        _cmp_box(divs, "target_bbox_raw", target.get("target_bbox_raw"), list(located[2]))
        origin = fitz.Point(located[1]) * frame.quarter_turn
        expected = target.get("expected_origin_visual")
        if not (isinstance(expected, list) and len(expected) == 2 and all(_num_close(a, b, TOL_BBOX) for a, b in zip(expected, (origin.x, origin.y), strict=True))):
            divs.append(_div("expected_origin_visual", expected, [float(origin.x), float(origin.y)], TOL_BBOX))
    for raw_key, vis_key in (("target_bbox_raw", "target_bbox_visual"), ("after_bbox_raw", "after_bbox_visual")):
        raw, vis = target.get(raw_key), target.get(vis_key)
        if isinstance(raw, list) and len(raw) == 4:
            mapped = fitz.Rect(raw) * frame.quarter_turn
            _cmp_box(divs, vis_key, vis, [mapped.x0, mapped.y0, mapped.x1, mapped.y1])
            if raw_key == "after_bbox_raw":
                scene.closed.add("after_bbox_frame")
    _check_growth_geometry(scene, divs)
    return divs


NEIGHBOURS_TOTAL = "neighbours_glyphs_total_mismatch"


def _page_glyph_count(mpage: fitz.Page) -> int:
    """Every glyph of the page's texttrace, flattened span by span (the brief's pairing list; no Tr filter)."""
    return sum(len(span["chars"]) for span in mpage.get_texttrace())


def _neighbour_records(case: dict, batch_dir: Path) -> list | None:
    """``cases/<case_id>/neighbours.json`` as a list, else None; the declared path is compared, never followed."""
    case_id = case.get("case_id")
    if not isinstance(case_id, str) or not _CASE_DIR_RE.fullmatch(case_id):
        return None
    if _g(case, "neighbours", "records_file") != f"cases/{case_id}/neighbours.json":
        return None
    try:
        data = json.loads((Path(batch_dir) / "cases" / case_id / "neighbours.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def _check_neighbour_total(scene: _Scene, batch_dir: Path, divs: list[Divergence]) -> None:
    """V3: ``glyphs_total`` is the before page's texttrace glyph count minus ``n_old``, and the records file holds
    exactly that many non-target before glyphs (each before glyph is paired once).  A row without mutation may
    carry an empty records file (brief 5.1); everything else that does not add up fails closed.
    """
    case = scene.case
    nb = _d(case.get("neighbours"))
    declared, n_old = nb.get("glyphs_total"), nb.get("target_glyphs_before")
    records = _neighbour_records(case, batch_dir)
    counted = None
    if records is not None:
        counted = sum(
            1
            for r in records
            if isinstance(r, dict)
            and r.get("role") != "target"
            and isinstance(r.get("trace_index_before"), int)
            and not isinstance(r.get("trace_index_before"), bool)
        )
    page_total = _page_glyph_count(scene.mpage)
    expected = None
    if isinstance(n_old, int) and not isinstance(n_old, bool) and 0 <= n_old <= page_total:
        expected = page_total - n_old
    declared_ok = expected is not None and isinstance(declared, int) and not isinstance(declared, bool) and declared == expected
    records_ok = expected is not None and counted is not None and (counted == expected or (_mutation(case) is None and records == []))
    if not (declared_ok and records_ok):
        divs.append(_div(NEIGHBOURS_TOTAL, [declared, counted], expected))


def _text_advance(cap: FontCapability, data: bytes, show: ShowOp) -> float:
    """Advance of ``data`` in text space (points at Tfs, before Th) by the function ``_measure_advances`` uses for ``adv_old``.

    Raises ``ValueError`` for an odd-length Type0 payload and for a simple font whose advance is not provable.
    """
    if cap.cid is not None:
        if len(data) % 2:
            raise ValueError("odd Type0 payload")
        return cap.cid.advance_points(_cids(data), show.font_size, show.char_spacing)
    if cap.advance_source not in ("widths", "face"):
        raise ValueError("advance is not provable for this font")
    return _advance(cap, data.decode("latin-1"), show.font_size, show.char_spacing, show.word_spacing)


def _slice_terms(scene: _Scene) -> tuple[float, float] | None:
    """``(x_pre, k_inner)``: where the target starts and how many kern thousandths lie inside it (Q10, Q11).

    ``x_pre`` is the text-space advance (the unit of brief 5.1 ``adv_old_text_space``, before Th) of everything the show
    draws before the target: the string items before item ``i0`` contribute their advance, every kern number K before the
    target ``-K / 1000 * Tfs``, and an F3 adds the advance of ``items[i0][:b0]``.  ``k_inner`` is the sum of the kern numbers
    BETWEEN the target's own string items (``items[i0].end <= pos < items[i1 - 1].start``); the quad is
    ``(x_pre, ., x_pre + adv_old - k_inner / 1000 * Tfs, .)`` times Th.  ``x_pre`` is always the advance before the FIRST
    target item, so a whole-show target has ``x_pre == 0.0`` unless the TJ opens with a kern (0.0 for a Tj and for the
    product's tier 1, which rejects a leading kern) and its ``k_inner`` spans all items (0.0 for a Tj); a single item or an
    F3 has ``k_inner == 0.0``.  ``None`` when the operand
    will not lex or an advance is not provable: the caller then expects nothing.  One lex serves both terms.
    """
    tgt = scene.target
    items = scene.string_items
    if not items:
        return (0.0, 0.0) if tgt.whole else None  # an unlexable or empty whole show keeps the pre-Q10 reading
    lo, hi = (0, len(items)) if tgt.item_lo is None or tgt.item_hi is None else (tgt.item_lo, tgt.item_hi)
    if not 0 <= lo < hi <= len(items):
        return None
    show, cap = scene.show, scene.cap
    first_start, last_start = items[lo][0], items[hi - 1][0]
    x_pre = 0.0
    k_inner = 0.0
    try:
        for _, _, payload in items[:lo]:
            x_pre += _text_advance(cap, payload, show)
        if tgt.in_item is not None and tgt.in_item[0]:
            x_pre += _text_advance(cap, items[lo][2][: tgt.in_item[0]], show)
        base = show.string_start
        data = scene.stream[base : show.string_end]
        for tok in lex_content_stream(data):
            if tok.kind is not TokenKind.NUMBER:
                continue
            number, pos = float(data[tok.start : tok.end]), base + tok.start
            if pos < first_start:
                x_pre -= number / 1000.0 * show.font_size
            elif items[lo][1] <= pos < last_start:
                k_inner += number
    except ValueError:
        return None
    return x_pre, k_inner


def _quad_terms(scene: _Scene) -> dict[str, float | None]:
    """The ``OracleContext`` fields ``x_pre`` and ``k_inner`` of the scene's target (None, None when not provable)."""
    terms = _slice_terms(scene)
    return {"x_pre": None if terms is None else terms[0], "k_inner": None if terms is None else terms[1]}


def _check_growth_geometry(scene: _Scene, divs: list[Divergence]) -> None:
    """On an applicable row every strip field must be present and equal to its recomputation; a null never passes."""
    case, frame = scene.case, scene.frame
    gz = _d(case.get("growth_zone"))
    if gz.get("applicable") is not True or frame is None:
        return
    region_visual = gz.get("region_visual")
    if isinstance(region_visual, list) and len(region_visual) == 4 and all(_is_num(v) for v in region_visual):
        back = fitz.Rect(region_visual) * ~frame.quarter_turn
        _cmp_box(divs, "region_dict", gz.get("region_dict"), [back.x0, back.y0, back.x1, back.y1])
        scene.closed.add("region_dict")
    else:
        divs.append(_div("region_dict", gz.get("region_dict"), None))
    adv_old = scene.adv[0].get("adv_old")
    if adv_old is None:
        adv_old = _g(_advances(case), 0, "adv_old_text_space") if _advances(case) else None
    terms = _slice_terms(scene) if isinstance(adv_old, (int, float)) and not isinstance(adv_old, bool) else None
    if terms is not None and isinstance(adv_old, (int, float)):
        show = scene.show
        x_pre, k_inner = terms
        # Q10/Q11: the quad starts where the target starts and ends K_inner thousandths of Tfs short of the string
        # advances (x_pre = 0.0 and k_inner = 0.0 for a whole Tj, the product's _build_tier1)
        quad = transforms.map_text_quad_to_visual(
            scene.mpage,
            show.tm,
            show.ctm,
            (
                x_pre * show.hscale / 100.0,
                -0.35 * show.font_size,
                (x_pre + float(adv_old) - k_inner / 1000.0 * show.font_size) * show.hscale / 100.0,
                show.font_size,
            ),
            frame=frame,
        )
        _cmp_box(divs, "background_bbox_visual", gz.get("background_bbox_visual"), list(quad))
        scene.closed.add("background_bbox")
    else:
        divs.append(_div("background_bbox_visual", gz.get("background_bbox_visual"), None))
    target_vis = _g(case, "target", "target_bbox_visual")
    verify_vis = _g(case, "target", "verify_bbox_visual")
    regions = gz.get("probe_regions_px_96dpi")
    if _box_close(target_vis, target_vis, 0.0) and _box_close(verify_vis, verify_vis, 0.0) and regions is not None:
        want = [list(r) for r in verify.growth_probe_regions(tuple(target_vis), tuple(verify_vis), scene.pixmap_meta)]
        if regions != want:
            divs.append(_div("probe_regions_px_96dpi", regions, want))
        scene.closed.add("probe_regions_px_96dpi")
    else:
        divs.append(_div("probe_regions_px_96dpi", regions, None))


def recompute_fixture_fields(case: dict, doc: fitz.Document) -> list[Divergence]:
    """Close the validator's ``unverifiable`` list on the registry fixture ``doc``; empty means all equal."""
    try:
        scene = _Scene(case, doc)
    except _SceneError as exc:
        return [_div(exc.name, None, str(exc))]
    try:
        divs = _recompute(scene)
        if scene.unlocatable and any(_d(case.get("target")).get(k) is not None for k in GEOMETRY_KEYS):
            divs.append(_div("target_unlocatable", None, "no texttrace run could be tied to the replayed show"))
        return divs
    finally:
        scene.close()


# --------------------------------------------------------------------------
# step 3: remeasure the advances (H1)
# --------------------------------------------------------------------------
def _old_new_codes(scene: _Scene) -> tuple[bytes, bytes] | None:
    case = scene.case
    change = _operand_change(scene)
    if change is None:
        return None
    start, end_old = change.get("start"), change.get("end_old")
    stream = scene.stream
    if scene.show.stream_xref != change.get("stream_xref"):
        stream = scene.doc.xref_stream(change.get("stream_xref")) or b""
    if not (isinstance(start, int) and isinstance(end_old, int) and 0 <= start <= end_old <= len(stream)):
        return None
    item_range = _g(case, "target", "item_range")
    byte_range = _g(case, "target", "byte_range_in_item")
    fragment = _g(case, "mutation", "splice_kind") in ("string_fragment", "fragment_split")
    if fragment and eb._rev(case) >= 3:
        # V12: the edited bytes are the slice [b0, b1) of item i0 and the replacement glyphs, never the whole item
        if scene.target.in_item is None:
            return None
        replaced = bytearray()
        for g in _g(case, "glyph_identity", default=[]) or []:
            code = g.get("code_bytes_hex") if isinstance(g, dict) else None
            try:
                replaced += bytes.fromhex(code) if isinstance(code, str) else b""
            except ValueError:
                return None
        return scene.target.data, bytes(replaced)
    if fragment and isinstance(item_range, list) and len(item_range) == 2:
        old_pay = _payloads(stream[item_range[0] : item_range[1]])
    else:
        old_pay = _payloads(stream[start:end_old])
    if old_pay is None:
        return None
    old = b"".join(old_pay)
    new = bytearray()
    for g in _g(case, "glyph_identity", default=[]) or []:
        code = g.get("code_bytes_hex") if isinstance(g, dict) else None
        try:
            new += bytes.fromhex(code) if isinstance(code, str) else b""
        except ValueError:
            return None
    if fragment and isinstance(byte_range, list) and len(byte_range) == 2:
        new = bytearray(old[: byte_range[0]]) + new + bytearray(old[byte_range[1] :])
    return old, bytes(new)


def _first_change_old(scene: _Scene) -> bytes | None:
    """The OLD operand bytes of the change that carries the string operand (the first change unless a canary says otherwise)."""
    change = _operand_change(scene)
    if change is None:
        return None
    start, end_old, xref = change.get("start"), change.get("end_old"), change.get("stream_xref")
    stream = scene.stream if scene.show.stream_xref == xref else (scene.doc.xref_stream(xref) if isinstance(xref, int) else None)
    if not (isinstance(start, int) and isinstance(end_old, int) and stream is not None and 0 <= start <= end_old <= len(stream)):
        return None
    return stream[start:end_old]


def _measure_advances(scene: _Scene) -> tuple[dict, list[Divergence]]:
    """Recompute both advances with the product's own functions and compare with the record."""
    divs: list[Divergence] = []
    out: dict = {}
    case, show, cap = scene.case, scene.show, scene.cap
    recs = _advances(case)
    if _mutation(case) is None or not recs:
        return out, divs
    codes = _old_new_codes(scene)
    if codes is None:
        divs.append(_div("advance.operands", None, "unreadable"))
        return out, divs
    old, new = codes
    tfs = show.font_size
    try:
        if cap.cid is not None:
            if len(old) % 2 or len(new) % 2:
                raise ValueError("odd Type0 payload")
            old_c, new_c = _cids(old), _cids(new)
            adv_old = cap.cid.advance_points(old_c, tfs, show.char_spacing)
            adv_new = cap.cid.advance_points(new_c, tfs, show.char_spacing)
            hits = all(any(a <= cid <= b for a, b, _ in cap.cid.w_records) for cid in (*old_c, *new_c))
            source = "W" if hits else "DW"
            tol = max(1e-9 * tfs, 1e-9)
        else:
            adv_old = _advance(cap, old.decode("latin-1"), tfs, show.char_spacing, show.word_spacing)
            adv_new = _advance(cap, new.decode("latin-1"), tfs, show.char_spacing, show.word_spacing)
            source = {"widths": "Widths", "face": "face"}.get(cap.advance_source, "")
            tol = max(1e-3 * tfs, 1e-4) if cap.advance_source == "face" else max(1e-9 * tfs, 1e-9)
            if not source:
                raise ValueError("advance is not provable for this font")
    except ValueError as exc:
        divs.append(_div("advance_unprovable", None, str(exc)))
        return out, divs
    th = show.hscale / 100.0
    delta = adv_new - adv_old
    try:
        k_eng: float | None = kern_for_displacement(show, adv_old - adv_new)
    except ValueError:
        k_eng = None
    out.update(
        {
            "adv_old": adv_old,
            "adv_new": adv_new,
            "delta": delta,
            "advance_source": source,
            "advance_tolerance": tol,
            "Tfs": tfs,
            "Th": th,
            "trm_scale": scene.trm_scale,
            "user_unit": None if scene.frame is None else scene.frame.user_unit,
            "K_disp_engine": k_eng,
        }
    )
    splice_kind = _g(case, "mutation", "splice_kind")
    old_operand = _first_change_old(scene)
    k_sum_re = None if old_operand is None else _expected_kerns(splice_kind, old_operand)[0]
    unit = _glyph_unit(cap)
    for adv in recs:
        if splice_kind in ("whole_operator", "string_token"):
            _cmp_eq(divs, "char_count_old", adv.get("char_count_old"), len(old) // unit)
        _cmp_num(divs, "adv_old_text_space", adv.get("adv_old_text_space"), adv_old, tol)
        _cmp_num(divs, "adv_new_text_space", adv.get("adv_new_text_space"), adv_new, tol)
        _cmp_eq(divs, "advance_source", adv.get("advance_source"), source)
        if not _num_close(adv.get("advance_tolerance"), tol, abs(tol) * 1e-9 + 1e-15):
            divs.append(_div("advance_tolerance", adv.get("advance_tolerance"), tol))
        _cmp_num(divs, "Tfs", adv.get("Tfs"), tfs, TOL_STATE)
        _cmp_num(divs, "Th", adv.get("Th"), th, TOL_STATE)
        k_written = adv.get("K_written")
        if k_written is not None or adv.get("K_disp_engine") is not None:
            # a K token is tied to the displacement it compensates: the engine K is recomputed whether or not the record offers it
            _cmp_num(divs, "K_disp_engine", adv.get("K_disp_engine"), k_eng, TOL_SCALAR)
        if _is_num(k_written) and k_eng is not None and k_sum_re is not None:
            want = abs(float(k_written) - (k_sum_re + k_eng))
            _cmp_num(divs, "abs_diff_written_vs_sum_engine", adv.get("abs_diff_written_vs_sum_engine"), want, TOL_SCALAR)
    scene.closed.add("growth_applicable_mismatch")  # every entry of an advance array was compared
    # the verify box the growth gates are fed is rebuilt from the RECOMPUTED delta; a brief v3 TJ splice sizes it by
    # the ink displacement delta + K_sum * Tfs / 1000 (TJ sign, K_sum read off the fixture), never by a guess (R7-1)
    # Applicability follows the same growth (brief v3 5.1: displacement_ink > advance_tolerance); ink == delta for
    # every rev 2 row and every non-TJ splice, so those keep the old delta rule.
    ink = delta
    if eb._ink_sized(case):
        if k_sum_re is None:
            divs.append(_div("displacement_ink", None, "old operand unreadable"))
            return out, divs
        ink = eb._ink_displacement(delta, k_sum_re, tfs)
    if eb._rev(case) >= 3:
        out["displacement_ink"] = ink
        ink_tol = 2.0 * tol + TOL_SCALAR * abs(tfs) / 1000.0  # both advances at tol, K_sum at TOL_SCALAR
        for adv in recs:
            _cmp_num(divs, "displacement_ink", adv.get("displacement_ink"), ink, ink_tol)
    target_vis = scene.target_visual()
    frame = scene.frame
    if target_vis is not None and frame is not None:
        growth = max(0.0, ink) * th if ink > tol else 0.0
        verify_vis = (
            _grown_verify_bbox(scene.mpage, show, target_vis, growth, frame=frame) if growth > 0.0 else target_vis
        )
        out["target_bbox_visual"] = list(target_vis)
        out["verify_bbox_visual"] = [float(v) for v in verify_vis]
        rec_verify = _g(case, "target", "verify_bbox_visual")
        if rec_verify is not None or growth > 0.0:
            _cmp_box(divs, "verify_bbox_visual", rec_verify, list(verify_vis))
    return out, divs


def remeasure_advances(case: dict, doc: fitz.Document, show: ShowOp) -> tuple[dict, list[Divergence]]:
    """``(measured numbers, divergences)``: both advances, source, tolerance, K and the verify box (H1)."""
    try:
        scene = _Scene(case, doc)
    except _SceneError as exc:
        return {}, [_div(exc.name, None, str(exc))]
    try:
        if scene.show.seq != show.seq:
            scene.show = show
        return _measure_advances(scene)
    finally:
        scene.close()


# --------------------------------------------------------------------------
# step 4: the frame-correct prepare (H3)
# --------------------------------------------------------------------------
def frame_prepare(
    engine: TieredCommitEngine,
    doc: fitz.Document,
    case: dict,
    show: ShowOp,
    text: str,
    *,
    locate_text: str | None = None,
    sub: tuple[int, int] | None = None,
    replacement: str | None = None,
    glyphs: int | None = None,
) -> PreparedEdit | PlanRejection:
    """acc's ``_prepare`` with the page frame applied; ``doc`` is never texttraced (a measurement copy is).

    Locates the texttrace run nearest ``show.origin_user * frame.base`` (must be within 0.02 pt),
    ``expected_origin = chars[0] origin * frame.quarter_turn``, ``target_bbox = union of char boxes * frame.quarter_turn``.
    ``page.rotation_matrix`` and ``page.transformation_matrix`` are never used.  Raises :class:`LocateError`.

    V12: ``text`` is the TARGET.  For a slice, ``locate_text`` is the whole show (the run the replay origin pins) and
    ``sub = (first glyph, glyph count)`` picks the slice's glyphs out of it, so ``expected_origin`` and ``target_bbox``
    are the slice's.  ``replacement`` overrides the record's replacement (the whole-show view embeds it in the show).

    V13: the locate is :func:`_locate_target` (the scene's own), so the probe and the recompute cannot disagree; ``glyphs``
    enables the positional branch.  An untracked origin raises :class:`LocateError` without locating.
    """
    page_index = _g(case, "corpus_case", "page_index")
    with fitz.open("pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)) as meas:
        mpage = meas[page_index]
        frame = transforms.page_visual_frame_or_none(mpage)
        if frame is None:
            raise LocateError("page geometry is unsupported")
        found = _locate_target(mpage, show, frame, text, locate_text=locate_text, sub=sub, glyphs=glyphs)
    if found is None:
        raise LocateError(
            "the replayed origin is untracked" if not show.origin_reliable else "no texttrace run within 0.02 pt of the replayed origin"
        )
    located = found[0]
    origin = fitz.Point(located[1]) * frame.quarter_turn
    rect = fitz.Rect(located[2]) * frame.quarter_turn
    return engine.prepare(
        doc[page_index],
        target_text=text,
        replacement_text=_g(case, "corpus_case", "replacement") if replacement is None else replacement,
        expected_origin=(float(origin.x), float(origin.y)),
        target_bbox=(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
    )


def _probe_view(result: PreparedEdit | PlanRejection | BaseException) -> dict:
    if isinstance(result, LocateError):  # rederive's own miss, not something the product did (V13)
        return {"result": "unlocatable", "tier": None, "reason": None, "detail": _ascii(str(result)), "exception_type": None, "prepared": None}
    if isinstance(result, BaseException):
        return {"result": "exception", "tier": None, "reason": None, "detail": None, "exception_type": type(result).__name__, "prepared": None}
    if isinstance(result, PlanRejection):
        return {"result": "rejected", "tier": None, "reason": result.reason, "detail": _ascii(result.detail), "exception_type": None, "prepared": None}
    return {
        "result": "prepared",
        "tier": int(result.tier),
        "reason": None,
        "detail": None,
        "exception_type": None,
        "prepared": {
            "stream_xref": result.stream_xref,
            "replacement_start": result.replacement.start,
            "replacement_end": result.replacement.end,
            "binding_op_start": result.binding.show.op_start,
            "binding_op_end": result.binding.show.op_end,
            "font_xref": result.font_xref,
            "source_advance": result.source_advance,
            "replacement_advance": result.replacement_advance,
            "kern_adjustment": result.kern_adjustment,
            "verify_bbox_page": None if result.verify_bbox_page is None else [float(v) for v in result.verify_bbox_page],
            "background_bbox_page": None if result.background_bbox_page is None else [float(v) for v in result.background_bbox_page],
        },
    }


def _whole_show_replacement(scene: _Scene) -> str:
    """The replacement that makes the slice edit a coherent whole-show edit: prefix + slice replacement + suffix."""
    tgt = scene.target
    unit = _glyph_unit(scene.cap)
    data = scene.show.decoded_bytes
    cut = tgt.glyph_start * unit
    after = (tgt.glyph_start + tgt.glyph_count) * unit
    prefix = scene._decode(data[:cut]) if cut else ""
    suffix = scene._decode(data[after:]) if after < len(data) else ""
    return prefix + str(_g(scene.case, "corpus_case", "replacement")) + suffix


def _fallback_probe_ok(scene: _Scene, data: bytes, *, whole: bool) -> str | None:
    """May the product be probed without geometry for this case (V13, owner Q5; Q13), and in which mode?

    Only a census or negative row whose recorded geometry is null, and only when the record's show is among the replayed
    shows of the page that spell the target bytes (a whole-show target must equal a show's bytes, a slice only has to occur
    in them).  ``"unique"``: it is the only one, so the probe's answer is the record's show's.  ``"shared"`` (Q13): another
    show spells it too, so with ``expected_origin=None`` the product binds by text and may bind either; the caller then
    accepts the probe only when the product answered ``ambiguous_source_match`` (it bound to nothing, so the answer does
    not depend on which show was meant).  ``None``: wrong kind, recorded geometry, or the record's show is not a spelling.
    """
    case = scene.case
    if case.get("kind") not in FALLBACK_KINDS or any(_d(case.get("target")).get(k) is not None for k in GEOMETRY_KEYS):
        return None
    shows = scene.replay.shows
    spelling = [i for i, s in enumerate(shows) if (s.decoded_bytes == data if whole else data in s.decoded_bytes)]
    if spelling == [scene.show_seq]:
        return "unique"
    return "shared" if scene.show_seq in spelling else None


def _run_probe(
    engine: TieredCommitEngine, doc: fitz.Document, case: dict, scene: _Scene, divs: list[Divergence], *, whole: bool = False
) -> PreparedEdit | PlanRejection | BaseException:
    tgt = scene.target
    glyphs = scene.glyph_total
    if whole:
        # the second view: target = the whole show, replacement = the slice edit embedded in it
        text, kwargs = scene.text, {"replacement": _whole_show_replacement(scene)}
        data, is_whole = scene.show.decoded_bytes, True
    elif tgt.whole:
        text, kwargs, data, is_whole = scene.text, {}, scene.show.decoded_bytes, True
    else:
        text, kwargs, data, is_whole = tgt.text, {"locate_text": scene.text, "sub": (tgt.glyph_start, tgt.glyph_count)}, tgt.data, False
    try:
        return frame_prepare(engine, doc, case, scene.show, text, glyphs=glyphs, **kwargs)
    except LocateError as exc:
        mode = _fallback_probe_ok(scene, data, whole=is_whole)
        if not mode:
            return exc
        try:
            replacement = kwargs.get("replacement")
            answer: PreparedEdit | PlanRejection | BaseException = engine.prepare(
                doc[_g(case, "corpus_case", "page_index")],
                target_text=text,
                replacement_text=_g(case, "corpus_case", "replacement") if replacement is None else replacement,
                expected_origin=None,
                target_bbox=None,
            )
        except Exception as exc2:  # noqa: BLE001 - a raising product is a recorded outcome (result=exception)
            logger.info("fallback prepare raised %s", type(exc2).__name__)
            answer = exc2
        if mode == "shared" and not (isinstance(answer, PlanRejection) and answer.reason == RejectReason.AMBIGUOUS_MATCH):
            # Q13: another show spells the target too, so only "bound to nothing" is independent of the show meant; a
            # prepared edit, any other reason or an exception belongs to whichever show the product bound
            return exc
        if not whole:
            # the primary (slice) probe alone decides target_unlocatable: the whole-show second view may take the
            # fallback (its spelling is unique even when the slice occurs twice) without lifting the quarantine
            scene.fallback_used = True
            scene.fallback_mode = mode
        return answer
    except Exception as exc:  # noqa: BLE001 - a raising product is a recorded outcome (result=exception)
        logger.info("prepare raised %s", type(exc).__name__)
        return exc


def _whole_show_view(scene: _Scene, data: bytes, folder: Path, tag: str) -> dict | None:
    """The max_tier=1 probe of the whole show carrying the slice edit; None when the target IS the whole show."""
    if scene.target.whole:
        return None
    doc = _open_scratch(data, folder / f"{tag}-W.pdf")
    try:
        return _probe_view(_run_probe(TieredCommitEngine(doc, max_tier=1), doc, scene.case, scene, [], whole=True))
    finally:
        doc.close()


def _compare_whole_view(rec: object, got: dict, tol_adv: float, divs: list[Divergence]) -> None:
    tmp: list[Divergence] = []
    _compare_probe(rec, got, tol_adv, tmp)
    divs += [Divergence(f"whole_show_max_tier_1.{d.field}", d.record, d.recomputed, d.tol) for d in tmp]


def _compare_probe(rec: object, got: dict, tol_adv: float, divs: list[Divergence]) -> None:
    """Result, tier and reason exact; ranges and font exact; advances within tolerance; K 1e-6; boxes 1e-3."""
    if not isinstance(rec, dict):
        divs.append(_div("probe", rec, "object"))
        return
    if got["result"] == "unlocatable":
        return  # rederive could not locate the target: nothing was asked of the product, so there is nothing to compare
    _cmp_eq(divs, "result", rec.get("result"), got["result"])
    _cmp_eq(divs, "tier", rec.get("tier"), got["tier"])
    _cmp_eq(divs, "reason", rec.get("reason"), got["reason"])
    if got["result"] == "rejected":
        _cmp_eq(divs, "detail", _ascii(rec.get("detail")), got["detail"])  # a control row reads the detail's prefix (brief 2.1)
    if got["result"] == "exception":
        _cmp_eq(divs, "exception_type", rec.get("exception_type"), got["exception_type"])
    rp, gp = rec.get("prepared"), got["prepared"]
    if gp is None or not isinstance(rp, dict):
        if (gp is None) != (rp is None):
            divs.append(_div("prepared", rp is not None, gp is not None))
        return
    for key in ("stream_xref", "replacement_start", "replacement_end", "binding_op_start", "binding_op_end", "font_xref"):
        _cmp_eq(divs, key, rp.get(key), gp[key])
    for key in ("source_advance", "replacement_advance"):
        _cmp_num(divs, key, rp.get(key), gp[key], tol_adv)
    rk = rp.get("kern_adjustment")
    _cmp_num(divs, "kern_adjustment", 0.0 if rk is None else rk, gp["kern_adjustment"], TOL_SCALAR)
    for key in ("verify_bbox_page", "background_bbox_page"):
        if rp.get(key) is None or gp[key] is None:
            if (rp.get(key) is None) != (gp[key] is None):
                divs.append(_div(key, rp.get(key), gp[key]))
        else:
            _cmp_box(divs, key, rp.get(key), gp[key])


# --------------------------------------------------------------------------
# step 5/6: oracles
# --------------------------------------------------------------------------
def _growth_checks(ctx: OracleContext) -> tuple[int, str | None]:
    """``(glyphs already in the growth zone, raster/occupancy failure detail or None)`` from the product gates.

    A thin ``ctx`` unpacker over ``helpers.growth_zone_checks`` (the shared core, moved to the acceptance helpers
    in I0b S3a); the ``_ascii`` boundary stays here because the report never echoes a non-ASCII detail."""
    glyphs, detail = helpers.growth_zone_checks(
        ctx.source_doc,
        ctx.page_index,
        ctx.show,
        ctx.frame,
        ctx.target_bbox_visual,
        ctx.verify_bbox_visual,
        ctx.adv_old,
        prepared=ctx.prepared,
        x_pre=ctx.x_pre,
        k_inner=ctx.k_inner,
    )
    return glyphs, _ascii(detail)


def assert_growth_zone_was_blank(ctx: OracleContext) -> str | None:
    """Built-in oracle: the product's growth gates, read-only (None = blank or not applicable)."""
    if tuple(ctx.verify_bbox_visual) == tuple(ctx.target_bbox_visual):
        return None  # shrink or equal advance: no growth zone
    try:
        glyphs, failure = _growth_checks(ctx)
    except Exception as exc:  # noqa: BLE001 - an oracle that cannot run does not pass
        return f"oracle raised {type(exc).__name__}"
    if glyphs:
        return f"glyphs: {glyphs} character(s) already occupy the growth zone"
    return failure


# ---- S4: the five I0b oracles as adapters over ``test_scripts.true_text_acceptance_helpers`` ----------------------------------
# Rules for every adapter: it calls only ``helpers.check_*``, ``glyph_identity_inputs``, ``edited_show``, ``page_streams`` and
# ``q12_inshow_residual_pt`` (never an ``assert_*`` wrapper, which ``python -O`` removes, and never acc, ``frontier_twins`` or
# pytest); extraction and rendering happen only inside the helpers, on their own measurement copies (stream reads and capability
# lookups run on the ctx documents directly, read-only, as ``_Scene`` does); no adapter keeps a document handle, because
# ``_commit_and_judge`` closes both in its ``finally``.  A detail starts with the oracle's head and is ASCII.
#: the head every detail of an adapter starts with (``_templated`` keeps it as the template word for a proprietary source)
ORACLE_HEADS = {
    "assert_target_stream_changed_only_within": "stream_range",
    "assert_wrapper_bytes_unchanged": "wrapper",
    "assert_show_and_operator_counts_equal": "counts",
    "assert_neighbour_glyphs_unchanged": "neighbours",
    "assert_glyph_identity": "glyph_identity",
}
#: the sink keys the neighbour adapter reports in ``remeasured["neighbours"]`` (the X5 inputs); nothing else is merged
NEIGHBOUR_REPORT_KEYS = ("max_untouched_dev", "max_inshow_dev", "overlap_glyphs", "min_ink_after_px_6x")
#: in-show successors of a slice target are judged against the exact Q12 residual to this tolerance (pt): the residual itself is
#: ~1e-3 pt, so a 1e-3 tolerance would be near-vacuous; the product's own exact limit (1e-6) applies wherever no residual is proven
Q12_INSHOW_TOL_PT = 1e-4
#: only an operator abort leaves ``_run_oracle``; any other BaseException is a recorded failure, not the end of the batch
_ORACLE_ABORTS = (KeyboardInterrupt, SystemExit, GeneratorExit)


def _guarded(head: str, body: Callable[[OracleContext], str | None], ctx: OracleContext) -> str | None:
    """Run an adapter body.  A helper precondition (``visual_frame``, ``edited_show``, the pairing invariant) is an ``assert``:
    it becomes a detail that starts with the oracle's head (ASCII, the assertion's own text kept).  Everything else is
    ``_run_oracle``'s: ``oracle raised <Type>``, so no programming error is hidden."""
    try:
        detail = body(ctx)
    except AssertionError as exc:
        text = _ascii(str(exc)) or ""
        return _ascii(text if text.startswith(head + ":") else (f"{head}: assertion: {text}" if text else f"{head}: assertion"))
    return _ascii(detail)


def _page_replay(doc: fitz.Document, page_index: int) -> PageReplay:
    return replay_page_streams([(x, doc.xref_stream(x)) for x in doc[page_index].get_contents()])


def _capability(doc: fitz.Document, page_index: int, show: ShowOp) -> FontCapability | None:
    return DocumentFontRegistry(doc).capability(doc[page_index], show.font_resource) if show.font_resource else None


def _binds_target(prepared: PreparedEdit, show: ShowOp) -> bool:
    """The edit the product prepared belongs to ``show`` (the expression ``_check_prepared`` records as ``binding_matches_target``)."""
    return (
        (prepared.stream_xref, prepared.binding.show.op_start) == (show.stream_xref, show.op_start)
        and show.op_start <= prepared.replacement.start
        and prepared.replacement.end <= show.op_end
    )


def _target_span(scene: _Scene) -> tuple[int, int]:
    """The target slice inside its show, in code units: ``(units before it, units after it)``; ``(0, 0)`` is the whole show."""
    target = scene.target
    return (target.glyph_start, scene.glyph_total - target.glyph_start - target.glyph_count)


def _trm_scale(show: ShowOp) -> float:
    linear = transforms.combined_linear(show.tm, show.ctm)
    return float(math.hypot(linear[0], linear[1]))


def _after_show(ctx: OracleContext, head: str) -> ShowOp | str:
    """The edited show of the reopened page, or a detail.  The after page is replayed here, BEFORE any helper calls its
    assert-based ``_shows``, so a ``PageReplay`` repr can never become a detail; the before page replayed when the scene was built."""
    replay = _page_replay(ctx.after_doc, ctx.page_index)
    if replay.malformed or replay.refusal_reason is not None:
        return f"{head}: replay: the after page does not replay"
    if not 0 <= ctx.show.seq < len(replay.shows):
        return f"{head}: pairing: edited show missing after"
    if ctx.prepared is not None and not _binds_target(ctx.prepared, ctx.show):
        return f"{head}: binding: the product edited another show"
    return replay.shows[ctx.show.seq]


def _change_ranges(changes: Sequence[Mapping[str, Any]]) -> dict[int, list[tuple[int, int, int]]]:
    """``{stream xref: [(start, end_old, end_new)]}`` of an experiment's splice, from ``start``, ``end_old`` and the NEW operand's
    own length with the shift rule of ``_replay`` (a later range sits in the earlier ranges' shifted suffix).  The record's
    ``end_new`` is a claim that ``_replay`` compares; it is never read here.  Ordered like ``splice_stream`` orders them:
    ``(start, end_old)``, so a zero-width insertion at ``s`` precedes a change that starts at ``s``."""
    grouped: dict[int, list[Mapping[str, Any]]] = {}
    for change in changes:
        grouped.setdefault(change["stream_xref"], []).append(change)
    out: dict[int, list[tuple[int, int, int]]] = {}
    for xref, group in grouped.items():
        shift = 0
        ranges: list[tuple[int, int, int]] = []
        for change in sorted(group, key=lambda c: (c["start"], c["end_old"])):
            new_len = len(bytes.fromhex(str(change["new_operand_bytes_hex"])))
            ranges.append((change["start"], change["end_old"], change["start"] + shift + new_len))
            shift += new_len - (change["end_old"] - change["start"])
        out[xref] = ranges
    return out


def _stream_range_body(ctx: OracleContext) -> str | None:
    if ctx.prepared is not None:
        rep = ctx.prepared.replacement
        ranges = {rep.stream_xref: [(rep.start, rep.end, rep.start + len(rep.replacement_bytes))]}
    else:
        ranges = _change_ranges(_changes(ctx.case))
    legs: list[tuple[int, str]] = []
    for xref in sorted(ranges):
        before = ctx.source_doc.xref_stream(xref) or b""
        after = ctx.after_doc.xref_stream(xref) or b""
        detail = helpers.check_target_stream_changed_only_within(before, after, ranges[xref])
        if detail is not None:
            legs.append((xref, detail.removeprefix("stream_range: ")))
        if sum(end - start for start, end, _ in ranges[xref]) >= len(before):
            legs.append((xref, "vacuous: no byte outside the changes"))  # nothing was left to compare
    others = [(xref, data) for xref, data in helpers.page_streams(ctx.source_doc, ctx.page_index) if xref not in ranges]
    moved = sum(1 for xref, data in others if (ctx.after_doc.xref_stream(xref) or b"") != data)
    parts = [text if len(ranges) == 1 else f"xref {xref}: {text}" for xref, text in legs]
    if moved:
        parts.append(f"other_stream_changed: {moved} of {len(others)} stream(s)")
    return "stream_range: " + "; ".join(parts) if parts else None


def assert_target_stream_changed_only_within(ctx: OracleContext) -> str | None:
    """Every byte of every content stream outside the declared edit is unchanged (product rows: the prepared splice; experiment
    rows: the replayed ``changes[]``), and a stream with no byte outside its edit is vacuous, not a pass."""
    return _guarded(ORACLE_HEADS["assert_target_stream_changed_only_within"], _stream_range_body, ctx)


def _wrapper_body(ctx: OracleContext) -> str | None:
    before = dict(helpers.page_streams(ctx.source_doc, ctx.page_index))
    after = dict(helpers.page_streams(ctx.after_doc, ctx.page_index))
    before_replay, after_replay = replay_page_streams(list(before.items())), replay_page_streams(list(after.items()))
    if ctx.prepared is not None:
        if not _binds_target(ctx.prepared, ctx.show):
            return "wrapper: binding: the product edited another show"
        rep = ctx.prepared.replacement
        xref, delta = rep.stream_xref, len(rep.replacement_bytes) - (rep.end - rep.start)
    else:
        changes = _changes(ctx.case)
        inside = [c for c in changes if c.get("stream_xref") == ctx.show.stream_xref]
        if len(changes) != 1 or len(inside) != 1:
            # the helper models ONE splice and one shift; multi-change rows are canary-only (the validator's changes_count rule)
            return f"wrapper: unsupported: {len(changes)} change(s), {len(inside)} in the edited show's stream"
        change = changes[0]
        xref = ctx.show.stream_xref
        delta = len(bytes.fromhex(str(change["new_operand_bytes_hex"]))) - (change["end_old"] - change["start"])
    return helpers.check_wrapper_bytes_unchanged(before, after, before_replay, after_replay, ctx.show.seq, xref, delta)


def assert_wrapper_bytes_unchanged(ctx: OracleContext) -> str | None:
    """The marked-content wrappers around the edited show are byte-for-byte what they were.  A row without a wrapper passes
    legitimately (unlike the twin judge, which counts that as vacuous); a wrapper that appears or a show span that moves does not."""
    return _guarded(ORACLE_HEADS["assert_wrapper_bytes_unchanged"], _wrapper_body, ctx)


def _counts_body(ctx: OracleContext) -> str | None:
    return helpers.check_show_and_operator_counts_equal(
        helpers.page_streams(ctx.source_doc, ctx.page_index), helpers.page_streams(ctx.after_doc, ctx.page_index)
    )


def assert_show_and_operator_counts_equal(ctx: OracleContext) -> str | None:
    """Per content stream, the number of shows and of operator tokens is unchanged by the edit."""
    return _guarded(ORACLE_HEADS["assert_show_and_operator_counts_equal"], _counts_body, ctx)


def _slice_codes(show: ShowOp, pre: int, count: int, code_bytes: int) -> list[int]:
    data = show.decoded_bytes[pre * code_bytes : (pre + count) * code_bytes]
    return [int.from_bytes(data[i : i + code_bytes], "big") for i in range(0, len(data), code_bytes)]


def _inshow_expectation(
    ctx: OracleContext, edited: helpers.EditedShow, after_show: ShowOp, cap: FontCapability, code_bytes: int
) -> tuple[float, float]:
    """``(residual along the baseline in pt, tolerance in pt)`` the in-show successors of the edit are judged against.

    MuPDF integerises a fractional ``/Widths`` entry and a Type0 ``/W`` / ``/DW`` width alike (half UP after the float32
    parse; pinned in the S2 and S4 frontier-twin tests), while the product computes its kern from the fractional advances:
    successors that share the show move by the residual of the replaced slice, ``helpers.q12_inshow_residual_pt``.  That
    residual is claimed only where it is proven: an experiment row, a slice with successors, one font, widths read from the
    document.  Everywhere else the product's exact limit applies, and a width the document does not prove fails closed to
    it, never to the validator's looser ``eb._inshow_successor_bound`` budget."""
    exact = (0.0, eb.INSHOW_SUCCESSOR_LIMIT_PT)
    if ctx.prepared is not None or edited.post == 0 or after_show.font_resource != ctx.show.font_resource:
        return exact
    if code_bytes == 1:
        if cap.advance_source != "widths":
            return exact
        width_of = cap.width_of_code
    elif cap.cid is not None:
        width_of = cap.cid.width_of_cid
    else:
        return exact
    old = [width_of(code) for code in _slice_codes(ctx.show, edited.pre, edited.n_old, code_bytes)]
    new = [width_of(code) for code in _slice_codes(after_show, edited.pre, edited.n_new, code_bytes)]
    try:
        residual = helpers.q12_inshow_residual_pt(
            old,
            new,
            font_size=ctx.show.font_size,
            hscale=ctx.show.hscale,
            trm_scale=_trm_scale(ctx.show),
            user_unit=ctx.frame.user_unit,
        )
    except ValueError:  # a width the document does not prove: no residual is claimed
        return exact
    return residual, Q12_INSHOW_TOL_PT


def _neighbours_body(ctx: OracleContext) -> str | None:
    after_show = _after_show(ctx, "neighbours")
    if isinstance(after_show, str):
        return after_show
    if ctx.target_span is None:
        return "neighbours: context: the target slice is unknown"
    cap = _capability(ctx.source_doc, ctx.page_index, ctx.show)
    if cap is None:
        return "neighbours: context: no font capability"
    code_bytes = _glyph_unit(cap)
    edited = helpers.edited_show(ctx.show, after_show, code_bytes=code_bytes, pre=ctx.target_span[0], post=ctx.target_span[1])
    # a committed row is judged for overlap whatever its record says; an experiment row's kind is the validator's field
    kind = _g(ctx.case, "kind")
    kind = "positive" if ctx.prepared is not None or kind not in helpers._NEIGHBOUR_KINDS else kind
    residual, tolerance = _inshow_expectation(ctx, edited, after_show, cap, code_bytes)
    measured: dict = {}
    detail = helpers.check_neighbour_glyphs_unchanged(
        ctx.source_doc,
        ctx.after_doc,
        ctx.page_index,
        [edited],
        kind=kind,
        frame=ctx.frame,
        inshow_tolerance=tolerance,
        inshow_residual_pt=residual,
        measurements=measured,
    )
    if measured and ctx.sink is not None:  # the helper completed (passed or returned a leg detail), not an early pairing/frame exit
        ctx.sink["neighbours"] = {key: measured[key] for key in NEIGHBOUR_REPORT_KEYS}
    if detail is None and measured.get("target_glyphs_ink_checked", 0) < 1:
        return "neighbours: vacuous: no target glyph ink checked"
    return detail


def assert_neighbour_glyphs_unchanged(ctx: OracleContext) -> str | None:
    """Every glyph the edit did not target is where and what it was; the new glyphs landed ink.  Measurements go to the sink."""
    return _guarded(ORACLE_HEADS["assert_neighbour_glyphs_unchanged"], _neighbours_body, ctx)


def _glyph_identity_body(ctx: OracleContext) -> str | None:
    after_show = _after_show(ctx, "glyph_identity")
    if isinstance(after_show, str):
        return after_show
    if ctx.target_span is None:
        return "glyph_identity: context: the target slice is unknown"
    replacement = _g(ctx.case, "corpus_case", "replacement")  # the claim under test, the one ``frame_prepare`` hands the product
    if not isinstance(replacement, str):
        return "glyph_identity: claim: the record carries no replacement text"
    changed = "glyph_identity: font_changed: the edited show draws in another font"
    if after_show.font_resource != ctx.show.font_resource:
        return changed
    source_cap = _capability(ctx.source_doc, ctx.page_index, ctx.show)
    after_cap = _capability(ctx.after_doc, ctx.page_index, after_show)
    if source_cap is None or after_cap is None:
        return "glyph_identity: font: no capability for the edited show"
    if after_cap.font_xref != source_cap.font_xref:  # the helper's consistency leg assumes this font drew the glyphs
        return changed
    code_bytes = _glyph_unit(source_cap)  # code unit, font and font kind come from the source capability, never from the record
    edited = helpers.edited_show(ctx.show, after_show, code_bytes=code_bytes, pre=ctx.target_span[0], post=ctx.target_span[1])
    inputs = helpers.glyph_identity_inputs(ctx.after_doc, ctx.page_index, edited, frame=ctx.frame, code_bytes=code_bytes)
    if isinstance(inputs, str):
        return inputs
    codes, gids = inputs
    if len(codes) != len(replacement):
        return f"glyph_identity: inputs: {len(codes)} glyph(s) drawn for {len(replacement)} character(s)"
    measured: dict = {}
    try:
        detail = helpers.check_glyph_identity(
            ctx.after_doc,
            ctx.page_index,
            source_cap.font_xref,
            replacement,
            "type0" if code_bytes == 2 else "simple",
            gid_after=gids,
            codes=codes,
            measurements=measured,
        )
    except helpers.IndependentLegUnavailable:
        return helpers.GLYPH_LEG_UNAVAILABLE  # the fixed sentence, no suffix: the message could name a font
    if detail is None and measured.get("glyphs_checked", 0) < 1:
        return "glyph_identity: vacuous: no glyph checked"
    return detail


def assert_glyph_identity(ctx: OracleContext) -> str | None:
    """The glyphs drawn for the replacement are the characters it claims (two legs, both required)."""
    return _guarded(ORACLE_HEADS["assert_glyph_identity"], _glyph_identity_body, ctx)


# growth runs first: on a committed row it then judges the documents before any other adapter has touched them, as at baseline
DEFAULT_ORACLES: dict[str, OracleFn] = {
    "assert_growth_zone_was_blank": assert_growth_zone_was_blank,
    "assert_target_stream_changed_only_within": assert_target_stream_changed_only_within,
    "assert_wrapper_bytes_unchanged": assert_wrapper_bytes_unchanged,
    "assert_show_and_operator_counts_equal": assert_show_and_operator_counts_equal,
    "assert_neighbour_glyphs_unchanged": assert_neighbour_glyphs_unchanged,
    "assert_glyph_identity": assert_glyph_identity,
}


def _run_oracle(fn: OracleFn, ctx: OracleContext) -> str | None:
    try:
        return fn(ctx)
    except _ORACLE_ABORTS:
        raise  # an operator abort ends the run; no report is written
    except BaseException as exc:  # noqa: BLE001 - an oracle that cannot run does not pass, whatever it raised
        return f"oracle raised {type(exc).__name__}"


# --------------------------------------------------------------------------
# the pipeline
# --------------------------------------------------------------------------
def _finalize(res: RederiveResult, *, committed: bool | None, gated: bool = False) -> RederiveResult:
    """``gated``: an experiment replay ran; like a committed product row it waits for the six oracles."""
    if res.divergences:
        _add(res.quarantine, "remeasure")
    order = {code: i for i, code in enumerate(QUARANTINE)}
    res.quarantine = sorted(set(res.quarantine), key=lambda c: (order.get(c, len(order)), c))
    if res.skipped and not res.quarantine:
        res.outcome = "skipped"
    elif res.quarantine:
        res.outcome = "quarantined"
    elif (committed or gated) and set(REQUIRED_ORACLES) - set(res.oracles_run):
        res.outcome = "deferred"
        res.deferred = DEFERRED_ORACLES
    else:
        res.outcome = "rederived"
    return res


def _safe_name(case_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", case_id)[:120]


def _tol_for(scene: _Scene) -> float:
    return max(1e-3 * scene.show.font_size, 1e-4) if scene.cap.advance_source == "face" else max(1e-9 * scene.show.font_size, 1e-9)


def rederive_case(
    case: dict,
    batch_dir: Path,
    registry: CorpusRegistry,
    *,
    oracles: Mapping[str, OracleFn] | None = None,
    work_dir: Path | None = None,
) -> RederiveResult:
    """Re-derive one case at HEAD (loop plan section 2 step 5).  Never raises on bundle content."""
    mut = _mutation(case) if isinstance(case, dict) else None
    experiment = isinstance(mut, dict) and mut.get("path") in ("experiment", "canary")
    return _rederive(case, Path(batch_dir), registry, oracles, work_dir, experiment=experiment)


def replay_experiment(
    case: dict,
    batch_dir: Path,
    registry: CorpusRegistry,
    *,
    oracles: Mapping[str, OracleFn] | None = None,
    work_dir: Path | None = None,
) -> RemeasureResult:
    """Re-apply the declared ``changes[]`` bytes of an experiment or canary row and re-measure (G7, H1)."""
    return _rederive(case, Path(batch_dir), registry, oracles, work_dir, experiment=True)


def _templated(detail: str | None, verbatim: bool) -> str | None:
    """Product and oracle detail strings: verbatim (ASCII) for public and synthetic sources, else a template word and a digest."""
    if detail is None:
        return None
    if verbatim:
        return _ascii(detail)
    head = re.match(r"([a-z_]{1,24}):", detail)
    return f"{head.group(1)}: {eb._digest(detail)}" if head else eb._digest(detail)


def _scrub_details(res: RederiveResult, case: object) -> RederiveResult:
    source = _d(case.get("source")) if isinstance(case, dict) else {}
    claimed = source.get("provenance")
    # the bundle's claim is not evidence: a public claim counts only when the registry resolved the sha as public
    verbatim = (claimed == "public" and res.provenance_verified) or (
        claimed == "synthetic" and not {"builder_not_allowlisted", "before_pdf_mismatch", "provenance_unverified"} & set(res.quarantine)
    )
    for key in ("max_tier_1", "max_tier_0"):
        view = res.at_head.get(key)
        if isinstance(view, dict):
            view["detail"] = _templated(view.get("detail"), verbatim)
    res.oracles_run = {name: _templated(detail, verbatim) for name, detail in res.oracles_run.items()}
    return res


def _rederive(
    case: dict,
    batch_dir: Path,
    registry: CorpusRegistry,
    oracles: Mapping[str, OracleFn] | None,
    work_dir: Path | None,
    *,
    experiment: bool,
) -> RederiveResult:
    res = _rederive_inner(case, batch_dir, registry, oracles, work_dir, experiment=experiment)
    return _scrub_details(res, case)


def _rederive_inner(
    case: dict,
    batch_dir: Path,
    registry: CorpusRegistry,
    oracles: Mapping[str, OracleFn] | None,
    work_dir: Path | None,
    *,
    experiment: bool,
) -> RederiveResult:
    raw_id = str(case.get("case_id")) if isinstance(case, dict) else "unknown"
    res = RederiveResult(case_id=str(eb._show_id(raw_id)))
    if not isinstance(case, dict):
        res.divergences.append(_div("record_shape", None, "object"))
        return _finalize(res, committed=None)
    corpus = _d(case.get("corpus_case"))
    # R3-1 / V15: an F2I/F2R row may claim tj_multi_item_array only as the whole-show negative twin; that is decided from the
    # recomputed scene below, never from the record, so a row that never reaches a scene stays quarantined (fail closed)
    reason_claim = case.get("class_id") in F2_CLASSES and corpus.get("expected_reason") == "tj_multi_item_array"
    try:
        resolved = _resolve(case, batch_dir, registry)
    except Exception:  # noqa: BLE001 - a source that cannot even be opened is unresolvable
        logger.warning("source resolution failed", exc_info=True)
        resolved = _Resolved(quarantine=["before_pdf_mismatch"])
    for code in resolved.quarantine:
        _add(res.quarantine, code)
    res.provenance_verified = resolved.verified
    res.resolved_slug = resolved.slug
    source = _d(case.get("source"))
    if source.get("provenance") == "synthetic" and case.get("kind") not in ("control", "canary"):
        _add(res.quarantine, "provenance_unverified")  # H4: a synthetic file is never a source for a frontier class
    if resolved.doc is None or resolved.data is None:
        if reason_claim:
            _add(res.quarantine, "reason_order")
        return _finalize(res, committed=None)
    if experiment and case.get("class_id") == UNSAVED_CLASS:
        res.skipped = SKIP_CANARY_UNSAVED  # a handle-discipline fault, not a byte splice: never replayed (G7)
        resolved.doc.close()
        return _finalize(res, committed=None)
    own_folder = work_dir is None  # the scratch copies may be full copies of proprietary fixtures: never leave them in %TEMP%
    folder = Path(work_dir) if work_dir is not None else Path(tempfile.mkdtemp(prefix="evidence-rederive-"))
    folder.mkdir(parents=True, exist_ok=True)
    scene: _Scene | None = None
    committed: bool | None = None
    gated = False
    try:
        try:
            scene = _Scene(case, resolved.doc)
            if reason_claim and not _is_whole_show_negative(scene):
                _add(res.quarantine, "reason_order")
            res.divergences += _recompute(scene)
            _check_neighbour_total(scene, batch_dir, res.divergences)
            measured, adv_divs = scene.adv
            res.divergences += adv_divs
            res.closed_unverifiable = [code for code in RECOMPUTED_CODES if code in scene.closed]
            res.remeasured.update(measured)
            res.remeasured.update(_geometry_summary(scene))
            if experiment:
                _replay(scene, resolved.data, folder, res, oracles if oracles is not None else DEFAULT_ORACLES)
                committed = None
                gated = True
            else:
                committed = _product(scene, resolved.data, folder, res, oracles if oracles is not None else DEFAULT_ORACLES)
            if scene.unlocatable and not scene.fallback_used:
                _add(res.quarantine, "target_unlocatable")
            if scene.fallback_used:
                res.remeasured["probe_fallback"] = "reason_only" if scene.fallback_mode == "unique" else "reason_only_shared"
        except _SceneError as exc:
            res.divergences.append(_div(exc.name, None, str(exc)))
            if reason_claim and scene is None:
                _add(res.quarantine, "reason_order")  # no scene, no proof of a whole-show target
        except Exception as exc:  # noqa: BLE001 - fail closed on any malformed record shape
            logger.warning("rederive failed on a malformed case", exc_info=True)
            res.divergences.append(_div("check_error", None, type(exc).__name__))
            if reason_claim and scene is None:
                _add(res.quarantine, "reason_order")
    finally:
        if scene is not None:
            scene.close()
        resolved.doc.close()
        if own_folder:
            shutil.rmtree(folder, ignore_errors=True)
    return _finalize(res, committed=committed, gated=gated)


def _is_whole_show_negative(scene: _Scene) -> bool:
    """True when the case provably targets the whole show as a refused negative (the R3-1 twin, brief L237) or as the census
    row of the same shape (owner ruling D22, 2026-10-28: a whole-show census row claiming ``tj_multi_item_array`` is the same
    twin and never commits).

    Decided from recomputed facts only: the recomputed show text hashes to the record's ``original_sha256``, the record carries no
    mutation and no sub-show byte range, and the kind is negative or census.  The record's ``item_range`` is never consulted.
    """
    case = scene.case
    return (
        case.get("kind") in ("negative", "census")
        and _mutation(case) is None
        and _g(case, "target", "byte_range_in_item") is None
        and _g(case, "corpus_case", "original_sha256") == _sha256(scene.text)
    )


def _geometry_summary(scene: _Scene) -> dict:
    out: dict = {"trm_scale": scene.trm_scale}
    if scene.frame is not None:
        out["user_unit"] = scene.frame.user_unit
        vis = scene.target_visual()
        if vis is not None:
            out["target_bbox_visual"] = list(vis)
        if scene.located is not None:
            out["target_bbox_raw"] = list(scene.located[2])
        if scene.locate_method == "positional":
            out["locate_method"] = "positional"  # absent means the text locate
    return out


# ---- product path -------------------------------------------------------
def _open_scratch(data: bytes, path: Path) -> fitz.Document:
    """A scratch copy opened BY PATH: ``saveIncr`` raises on a bytes-opened document."""
    path.write_bytes(data)
    return fitz.open(str(path))


def _product(scene: _Scene, data: bytes, folder: Path, res: RederiveResult, oracles: Mapping[str, OracleFn]) -> bool | None:
    case = scene.case
    tag = _safe_name(res.case_id)
    path_b, path_c = folder / f"{tag}-B.pdf", folder / f"{tag}-C.pdf"
    doc_b, doc_c = _open_scratch(data, path_b), _open_scratch(data, path_c)
    probe = _d(case.get("probe"))
    tol = _tol_for(scene)
    try:
        engine_b = TieredCommitEngine(doc_b, max_tier=1)
        engine_c = TieredCommitEngine(doc_c, max_tier=0)
        out_b = _run_probe(engine_b, doc_b, case, scene, res.divergences)
        out_c = _run_probe(engine_c, doc_c, case, scene, res.divergences)
        view_b, view_c = _probe_view(out_b), _probe_view(out_c)
        res.at_head = {"max_tier_1": view_b, "max_tier_0": view_c, "committed": False}
        _compare_probe(probe.get("max_tier_1"), view_b, tol, res.divergences)
        _compare_probe(probe.get("max_tier_0"), view_c, tol, res.divergences)
        view_w = _whole_show_view(scene, data, folder, tag)
        if view_w is not None:
            res.at_head["whole_show_max_tier_1"] = view_w
            if probe.get("whole_show_max_tier_1") is not None:
                _compare_whole_view(probe.get("whole_show_max_tier_1"), view_w, tol, res.divergences)
        if isinstance(out_b, PreparedEdit):
            _check_prepared(scene, out_b, probe, tol, res)
        if not isinstance(out_b, PreparedEdit):
            return False
        return _commit_and_judge(scene, data, doc_b, path_b, engine_b, out_b, probe, res, oracles)
    finally:
        for doc in (doc_b, doc_c):
            if not doc.is_closed:
                doc.close()


def _check_prepared(scene: _Scene, prepared: PreparedEdit, probe: dict, tol: float, res: RederiveResult) -> None:
    binding = _binds_target(prepared, scene.show)
    res.at_head["binding_matches_target"] = binding
    rec = probe.get("binding_matches_target")
    if rec is not None:
        _cmp_eq(res.divergences, "binding_matches_target", rec, binding)
    measured = res.remeasured
    if prepared.tier == 1 and "adv_old" in measured:
        _cmp_num(res.divergences, "source_advance", prepared.source_advance, measured["adv_old"], tol)
        _cmp_num(res.divergences, "replacement_advance", prepared.replacement_advance, measured["adv_new"], tol)
    mut = _mutation(scene.case)
    if mut is None:
        return
    changes = _changes(scene.case)
    if changes:
        ch = changes[0]
        _cmp_eq(res.divergences, "change_start", ch.get("start"), prepared.replacement.start)
        _cmp_eq(res.divergences, "change_end_old", ch.get("end_old"), prepared.replacement.end)
        _cmp_eq(res.divergences, "new_operand_bytes_hex", ch.get("new_operand_bytes_hex"), bytes(prepared.replacement.replacement_bytes).hex().upper())
    k_product = prepared.kern_adjustment if prepared.tier == 1 else None
    measured["K_written"] = k_product
    for adv in _advances(scene.case):
        rec_k = adv.get("K_written")
        if (rec_k is None) != (k_product is None) or (rec_k is not None and not _num_close(rec_k, k_product, TOL_SCALAR)):
            res.divergences.append(_div("K", rec_k, k_product, TOL_SCALAR))
    rec_vb = _g(scene.case, "target", "verify_bbox_visual")
    if prepared.verify_bbox_page is not None:
        _cmp_box(res.divergences, "verify_bbox_visual", rec_vb, list(prepared.verify_bbox_page))


def _commit_and_judge(
    scene: _Scene,
    data: bytes,
    doc_b: fitz.Document,
    path_b: Path,
    engine_b: TieredCommitEngine,
    prepared: PreparedEdit,
    probe: dict,
    res: RederiveResult,
    oracles: Mapping[str, OracleFn],
) -> bool:
    commit = _d(probe.get("commit"))
    try:
        outcome = engine_b.commit(prepared)
    except Exception as exc:  # noqa: BLE001
        res.at_head["commit"] = {"status": "exception", "tier": None, "chain": [], "exception_type": type(exc).__name__}
        return False
    committed = outcome.status in (CommitStatus.COMMITTED, CommitStatus.DEGRADED_COMMITTED)
    chain = list(outcome.decision_chain or outcome.fallback_chain)
    res.at_head["committed"] = committed
    res.at_head["commit"] = {"status": outcome.status.value, "tier": None if outcome.tier is None else int(outcome.tier), "chain": chain}
    if commit.get("attempted") is True:
        _cmp_eq(res.divergences, "commit.status", commit.get("status"), outcome.status.value)
        _cmp_eq(res.divergences, "commit.tier", commit.get("tier"), None if outcome.tier is None else int(outcome.tier))
    if not committed:
        return False
    doc_b.saveIncr()
    doc_b.close()
    after = fitz.open(str(path_b))
    source = fitz.open("pdf", data)
    sink: dict = {}
    try:
        ctx = OracleContext(
            source_doc=source,
            after_doc=after,
            page_index=scene.page_index,
            show=scene.show,
            frame=scene.frame,  # type: ignore[arg-type]
            target_bbox_visual=tuple(prepared.target_bbox_page),  # type: ignore[arg-type]
            verify_bbox_visual=tuple(prepared.effective_verify_bbox),  # type: ignore[arg-type]
            adv_old=float(prepared.source_advance if prepared.tier == 1 else res.remeasured.get("adv_old", 0.0)),
            prepared=prepared,
            case=scene.case,
            # a tier 1 plan only ever targets the whole show and the product rejects kerns in a tier 1 range
            **({"x_pre": 0.0, "k_inner": 0.0} if prepared.tier == 1 else _quad_terms(scene)),
            target_span=_target_span(scene),
            sink=sink,
        )
        for name, fn in oracles.items():
            detail = _run_oracle(fn, ctx)
            res.oracles_run[name] = detail
            if detail is not None:
                _add(res.quarantine, f"oracle_{name}")  # the false-safe shape (H5)
        if isinstance(sink.get("neighbours"), dict):
            res.remeasured["neighbours"] = dict(sink["neighbours"])  # the only sink key that is reported
    finally:
        source.close()
        after.close()
    return True


# ---- experiment path ----------------------------------------------------
def _replay(scene: _Scene, data: bytes, folder: Path, res: RederiveResult, oracles: Mapping[str, OracleFn] = DEFAULT_ORACLES) -> None:
    case = scene.case
    mut = _mutation(case)
    changes = _changes(case)
    if mut is None or not changes:
        res.divergences.append(_div("changes", None, "an experiment row needs a change"))
        return
    # product probe at HEAD (no commit): the state emit_rows decides from.  A mismatch with the record is not a
    # quarantine here, the experiment exists because the product refused; HEAD may have moved on since.
    _probe_at_head(scene, data, folder, res)
    by_xref: dict[int, list[StreamReplacement]] = {}
    sources: dict[int, bytes] = {}
    for ch in changes:
        xref = ch.get("stream_xref")
        stream = scene.doc.xref_stream(xref) if isinstance(xref, int) else None
        if stream is None or not isinstance(xref, int) or not isinstance(ch.get("start"), int) or not isinstance(ch.get("end_old"), int):
            res.divergences.append(_div("splice", None, "change outside its stream"))
            return
        try:
            replacement_bytes = bytes.fromhex(str(ch.get("new_operand_bytes_hex")))
        except ValueError:
            res.divergences.append(_div("splice", None, "new operand is not hex"))
            return
        sources[xref] = stream
        by_xref.setdefault(xref, []).append(
            StreamReplacement(
                stream_xref=xref,
                start=ch["start"],
                end=ch["end_old"],
                expected_bytes=stream[ch["start"] : ch["end_old"]],
                replacement_bytes=replacement_bytes,
                expected_stream_digest=_sha256(stream),
            )
        )
    new_streams: dict[int, bytes] = {}
    for xref, reps in by_xref.items():
        try:
            new_streams[xref] = splice_stream(sources[xref], reps)
        except SpliceError as exc:
            res.divergences.append(_div("splice", None, _ascii(exc)))
            return
    shift: dict[int, int] = {}
    for ch in sorted(changes, key=lambda c: (c["stream_xref"], c["start"])):
        xref = ch["stream_xref"]
        new_len = len(bytes.fromhex(ch["new_operand_bytes_hex"]))
        offset = shift.get(xref, 0)
        _cmp_eq(res.divergences, "end_new", ch.get("end_new"), ch["start"] + offset + new_len)
        shift[xref] = offset + new_len - (ch["end_old"] - ch["start"])
        _cmp_eq(res.divergences, "new_stream_sha256", ch.get("new_stream_sha256"), _sha256(new_streams[xref]))
    scratch_path = folder / f"{_safe_name(res.case_id)}-X.pdf"
    scratch = _open_scratch(data, scratch_path)
    for xref, stream in new_streams.items():
        scratch.update_stream(xref, stream)
    scratch.saveIncr()
    scratch.close()
    res.remeasured["output_sha256"] = _sha256(scratch_path.read_bytes())  # informational: the bundle's file differs in trailer bytes
    after = fitz.open(str(scratch_path))
    try:
        _judge_experiment(scene, after, _operand_change(scene) or changes[0], res)
        _experiment_oracles(scene, after, res, oracles)
    finally:
        after.close()


def _probe_at_head(scene: _Scene, data: bytes, folder: Path, res: RederiveResult) -> None:
    tag = _safe_name(res.case_id)
    views: dict[str, dict] = {}
    for label, tier, suffix in (("max_tier_1", 1, "B"), ("max_tier_0", 0, "C")):
        doc = _open_scratch(data, folder / f"{tag}-{suffix}.pdf")
        try:
            tmp: list[Divergence] = []
            out = _run_probe(TieredCommitEngine(doc, max_tier=tier), doc, scene.case, scene, tmp)
            views[label] = _probe_view(out)
        finally:
            doc.close()
    view_w = _whole_show_view(scene, data, folder, tag)
    if view_w is not None:
        views["whole_show_max_tier_1"] = view_w
    res.at_head = {**views, "committed": None}


def _judge_experiment(scene: _Scene, after: fitz.Document, change: dict, res: RederiveResult) -> None:
    case, frame = scene.case, scene.frame
    page2 = after[scene.page_index]
    replay2 = replay_page_streams([(x, after.xref_stream(x)) for x in page2.get_contents()])
    ts = _g(case, "text_state", default={})
    _cmp_eq(res.divergences, "show_count_after", ts.get("show_count_after"), len(replay2.shows))
    _cmp_eq(res.divergences, "operator_count_after", ts.get("operator_count_after"), _operator_count(after, page2))
    show2 = replay2.shows[scene.show_seq] if scene.show_seq < len(replay2.shows) else None
    rec_after = ts.get("after")
    if rec_after is not None and show2 is not None:
        _check_text_state("text_state.after", rec_after, show2, res.divergences)
    elif rec_after is not None:
        res.divergences.append(_div("text_state.after", "present", "show missing"))
    # K token: the NUMBER tokens of the new operand against K_written, and K_disp on the recomputed advances
    try:
        new_operand = bytes.fromhex(str(change.get("new_operand_bytes_hex")))
    except ValueError:
        new_operand = b""
    numbers = _numbers(new_operand)
    res.remeasured["new_operand_numbers"] = numbers
    for adv in _advances(case):
        k_written = adv.get("K_written")
        if k_written is not None and not any(_num_close(k_written, n, TOL_SCALAR) for n in numbers):
            res.divergences.append(_div("K_written", k_written, numbers, TOL_SCALAR))
    res.remeasured["K_written"] = numbers[-1] if numbers else None
    # after ink: the replacement glyph boxes in the reopened file
    target = _g(case, "target", default={})
    rec_raw = target.get("after_bbox_raw")
    anchor = None if scene.located is None else scene.located[1]  # V14: the before-origin rederive located, never the record's
    if rec_raw is not None and show2 is not None and frame is not None and anchor is not None:
        replacement = str(_g(case, "corpus_case", "replacement"))
        with fitz.open("pdf", after.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP)) as ameas:
            found = _locate_after(ameas[scene.page_index], frame, replacement, anchor, len(replacement))
        if found is None:
            res.divergences.append(_div("after_bbox_raw", rec_raw, None, TOL_BBOX))
        else:
            res.remeasured["after_bbox_raw"] = list(found.box)
            res.remeasured["after_text_identity"] = found.identity
            if found.method != "text":
                res.remeasured["after_locate_method"] = found.method  # absent means the text locate
            if not found.identity and case.get("class_id") not in FAULT_CANARIES:
                res.divergences.append(_div("after_text_identity", True, False))  # the fault canaries exist to show it
            _cmp_box(res.divergences, "after_bbox_raw", rec_raw, list(found.box))
            _after_bound(scene, found.box, res)
    _growth_phase(scene, after, res)


def _experiment_oracles(scene: _Scene, after: fitz.Document, res: RederiveResult, oracles: Mapping[str, OracleFn]) -> None:
    """The oracles (by default the six adapters) on (fixture, replayed file).  The growth helper already ran built-in.

    A failure is recorded, not quarantined: an experiment is allowed to show the fault (a canary exists to), and what it
    may become is decided in ``emit_rows`` by the validator's recomputed status, and a failed or raised oracle emits no
    row there (finding ``remeasure_oracle_failed``).  A mapping that lacks a required oracle leaves the row ``deferred``
    (``oracles_incomplete``), so a partial mapping is never emitted.
    """
    target_vis = scene.target_visual()
    verify_vis = res.remeasured.get("verify_bbox_visual")
    adv_old = res.remeasured.get("adv_old")
    if target_vis is None or adv_old is None or scene.frame is None:
        return
    sink: dict = {}
    ctx = OracleContext(
        source_doc=scene.doc,
        after_doc=after,
        page_index=scene.page_index,
        show=scene.show,
        frame=scene.frame,
        target_bbox_visual=target_vis,
        verify_bbox_visual=tuple(verify_vis) if verify_vis is not None else target_vis,  # type: ignore[arg-type]
        adv_old=float(adv_old),
        prepared=None,
        case=scene.case,
        **_quad_terms(scene),
        target_span=_target_span(scene),
        sink=sink,
    )
    for name, fn in oracles.items():
        if name != "assert_growth_zone_was_blank":
            res.oracles_run[name] = _run_oracle(fn, ctx)
    if isinstance(sink.get("neighbours"), dict):
        res.remeasured["neighbours"] = dict(sink["neighbours"])  # the only sink key that is reported


def _after_bound(scene: _Scene, after_raw: Sequence[float], res: RederiveResult) -> None:
    """H1: the after ink may not outrun the verify strip by more than 0.5 pt (applicable rows).

    The extent is the dominant-edge amount of ``_growth_zone_rect`` (``eb._extent``): the larger side of the strip
    would be the cross axis whenever growth is smaller than the glyph height, which is the usual case.
    """
    gz = _d(scene.case.get("growth_zone"))
    frame = scene.frame
    target_vis = scene.target_visual()
    verify_vis = res.remeasured.get("verify_bbox_visual")
    if gz.get("applicable") is not True or frame is None or target_vis is None or verify_vis is None:
        return
    after_vis = fitz.Rect(after_raw) * frame.quarter_turn
    extent_after = eb._extent(list(target_vis), [after_vis.x0, after_vis.y0, after_vis.x1, after_vis.y1])
    extent_verify = eb._extent(list(target_vis), list(verify_vis))
    if eb._rev(scene.case) >= 3:
        # V10 mirror of the validator: under brief v3 the spill is the growth_zone phase fail ``after_exceeds_verify``
        # recomputed from the record, not a quarantine; a lying after_bbox_raw is still the ``after_bbox_raw`` comparison.
        # The extents are recorded for triage; rev-2 rows keep the HEAD report shape (divergence only, no extent keys).
        res.remeasured["after_bbox_extent"] = extent_after
        res.remeasured["verify_bbox_extent"] = extent_verify
    elif extent_after > extent_verify + AFTER_BBOX_MAX_PT:
        res.divergences.append(_div("after_bbox_extent", extent_after, extent_verify, AFTER_BBOX_MAX_PT))


def _growth_phase(scene: _Scene, after: fitz.Document, res: RederiveResult) -> None:
    """The growth gates on the fixture, fed the RECOMPUTED verify box; compared with what the record claims."""
    target_vis = scene.target_visual()
    verify_vis = res.remeasured.get("verify_bbox_visual")
    adv_old = res.remeasured.get("adv_old")
    if target_vis is None or verify_vis is None or adv_old is None or scene.frame is None:
        return
    ctx = OracleContext(
        source_doc=scene.doc,
        after_doc=after,
        page_index=scene.page_index,
        show=scene.show,
        frame=scene.frame,
        target_bbox_visual=target_vis,
        verify_bbox_visual=tuple(verify_vis),  # type: ignore[arg-type]
        adv_old=float(adv_old),
        prepared=None,
        case=scene.case,
        **_quad_terms(scene),
    )
    name = "assert_growth_zone_was_blank"
    if tuple(verify_vis) == tuple(target_vis):
        res.oracles_run[name] = None
        return
    try:
        glyphs, failure = _growth_checks(ctx)
    except _ORACLE_ABORTS:
        raise
    except BaseException as exc:  # noqa: BLE001 - recorded like any other raise; only an operator abort leaves
        res.oracles_run[name] = f"oracle raised {type(exc).__name__}"
        res.divergences.append(_div("growth_zone", None, type(exc).__name__))
        return
    detail = f"glyphs: {glyphs} character(s) already occupy the growth zone" if glyphs else failure
    res.oracles_run[name] = detail
    gz = _g(scene.case, "growth_zone", default={})
    if gz.get("applicable") is not True:
        return
    rec_glyphs = gz.get("before_glyph_bboxes_intersecting")
    if rec_glyphs != glyphs:
        res.divergences.append(_div("before_glyph_bboxes_intersecting", rec_glyphs, glyphs))
    rec_raster = gz.get("raster_proof")
    if rec_raster in ("pass", "fail") and rec_raster != ("fail" if failure is not None else "pass"):
        res.divergences.append(_div("raster_proof", rec_raster, "fail" if failure is not None else "pass"))


# --------------------------------------------------------------------------
# step 7: emit rows
# --------------------------------------------------------------------------
def _batch_cases(batch: object) -> list[dict]:
    if isinstance(batch, Mapping):
        return [c for c in batch.get("cases", []) if isinstance(c, dict)]
    cases: Any = getattr(batch, "cases", batch)
    return [c for c in cases if isinstance(c, dict)]


def _planned_entry(planned: object, class_id: str) -> dict | None:
    if isinstance(planned, Mapping):
        if class_id not in planned:
            return None
        value = planned[class_id]
        return dict(value) if isinstance(value, Mapping) else {}
    return {} if class_id in planned else None  # type: ignore[operator]


def _check_planned(planned: object) -> None:
    """Refuse a plan whose ``measurement_only`` is not a JSON boolean: the X5 hold is lifted by ``false`` alone, never by
    a look-alike (``null``, ``0``, ``1``, ``"false"``), so a plan that carries one has no decision in it."""
    if not isinstance(planned, Mapping):
        return
    for class_id, entry in planned.items():
        if isinstance(entry, Mapping) and "measurement_only" in entry and not isinstance(entry["measurement_only"], bool):
            raise ValueError(f"planned class {_ascii(str(class_id))}: measurement_only must be true or false, got {type(entry['measurement_only']).__name__}")


def _variant(case_id: str) -> str:
    return re.sub(r"[0-9]+$", "", case_id.rsplit("-", 1)[-1])


def _class_word(class_id: str) -> str:
    """A class id is printed only in its structural shape (``F30B``, ``CANARY_KSIGN``), a digest otherwise."""
    return class_id if re.fullmatch(r"[A-Z][A-Z0-9_]{0,23}", class_id) else eb._digest(class_id)


def _false_safe_owner(helper: str, plan: Mapping[str, Any], owners: Mapping[str, str], class_id: str, case_id: str) -> str:
    """Q2: who owns the false-safe a required helper found.  A per-helper override wins (glyph identity: I1); otherwise the CASE'S
    CLASS planned slice owns it, never the landed I0b.  A class with none is a hard error, not a silent default."""
    owner = owners.get(helper)
    if owner is None and helper in REQUIRED_ORACLES:
        owner = plan.get("owned_until_slice")
    if not isinstance(owner, str) or not owner:
        raise ValueError(
            f"no owning slice for oracle {_printable_code(helper)} on planned class {_class_word(class_id)} "
            f"(case {eb._show_id(case_id)}): set owned_until_slice in --planned"
        )
    return owner


def emit_rows(
    batch: object,
    report: Mapping[str, Any],
    planned_classes: object,
    *,
    oracle_owners: Mapping[str, str] | None = None,
    report_sha256: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """``(manifest rows, findings)`` from a rederive report.  The report is never mutated; nothing is written."""
    cases = {c.get("case_id"): c for c in _batch_cases(batch)}
    owners = ORACLE_OWNERS if oracle_owners is None else oracle_owners
    rep_sha = report_sha256 or _sha256(json.dumps(report, sort_keys=True, ensure_ascii=True))
    rows: list[dict] = []
    findings: list[dict] = []
    for result in report.get("results", []):
        case = cases.get(result.get("case_id"))
        if case is None:
            continue
        source = _d(case.get("source"))
        if source.get("provenance") == "synthetic" or case.get("kind") in NO_EMIT_KINDS:
            continue
        class_id = case.get("class_id")
        plan = _planned_entry(planned_classes, str(class_id))
        if plan is None or result.get("outcome") in ("skipped", "deferred", "validator_rejected"):
            continue
        quarantine = list(result.get("quarantine") or [])
        oracle_failures = [q[len("oracle_") :] for q in quarantine if q.startswith("oracle_")]
        if any(not q.startswith("oracle_") for q in quarantine):
            continue  # a quarantined case emits nothing, whatever the product did with it
        if result.get("validated_status") not in EMIT_STATUSES.get(str(case.get("kind")), ()):
            # the validator's recomputed status decides what a row may become: a failed experiment is a finding, not a candidate
            findings.append({"kind": "status_not_emittable", "case_id": case["case_id"]})
            continue
        if (result.get("remeasured") or {}).get("probe_fallback"):
            findings.append({"kind": "geometry_unverifiable", "case_id": case["case_id"]})  # no geometry was checked: never a manifest row
            continue
        # the hold belongs to the class, not to whoever built the plan: only the boolean False lifts it (None, 0, 1 and
        # "false" are not a decision), and True holds any class
        flag = plan.get("measurement_only")
        if flag is True or (str(class_id) in MEASUREMENT_ONLY_CLASSES and flag is not False):
            findings.append({"kind": "measurement_only", "case_id": case["case_id"]})  # measured and recorded, never a manifest row
            continue
        at_head = result.get("at_head") or {}
        view = at_head.get("max_tier_1") or {}
        row = _row(case, result, rep_sha, report)
        if oracle_failures:
            if at_head.get("committed") is not True:
                continue
            helper = sorted(oracle_failures, key=lambda n: REQUIRED_ORACLES.index(n) if n in REQUIRED_ORACLES else 99)[0]
            row.update(
                state="candidate",
                kind="refusal",
                expected_reason=None,
                expected_reason_at_head="COMMITTED",
                false_safe_oracle=helper,
                owned_until_slice=_false_safe_owner(helper, plan, owners, str(class_id), str(case["case_id"])),
            )
            rows.append(row)
            findings += [{"kind": "false_safe_suspect", "case_id": case["case_id"], "oracle": name} for name in oracle_failures]
            continue
        ran = result.get("oracles_run") or {}
        failed = sorted(name for name, detail in ran.items() if detail is not None)
        if failed:
            # V4: an oracle that failed or raised re-measured a fault; no branch below may turn the case into a row
            findings += [{"kind": "remeasure_oracle_failed", "case_id": case["case_id"], "oracle": name} for name in failed]
            continue
        if at_head.get("committed") is True:
            if set(REQUIRED_ORACLES) - set(ran):
                continue
            row.update(state="engine_active", kind="positive" if case.get("kind") == "positive" else "refusal")
            row["expected_tier"] = view.get("tier")
            if view.get("tier") == 1:
                row["expected_tj_compensation"] = _g(view, "prepared", "kern_adjustment")
            rows.append(row)
            continue
        if view.get("result") == "prepared" and at_head.get("committed") is None:
            # an experiment row the product now prepares: nothing was committed, so no state is decided
            findings.append({"kind": "experiment_now_prepares", "case_id": case["case_id"]})
            continue
        if view.get("result") == "rejected" and at_head.get("committed") is not True:
            reason = view.get("reason")
            row["expected_reason_at_head"] = reason
            guard = case.get("kind") == "negative" and reason == _g(case, "corpus_case", "expected_reason")
            owner = plan.get("owned_until_slice")
            row["kind"] = "refusal" if case.get("kind") == "negative" else "positive"
            if guard and not owner:
                row.update(state="engine_active", expected_reason=reason)
            else:
                row.update(state="candidate", owned_until_slice=owner)
            rows.append(row)
    return rows, findings


def default_plan() -> dict[str, dict]:
    """Every default class planned with its owning slice (owner ruling 2026-10-28); F2R and F2G are measurement-only until
    I4/I5 land (X5 ratified 2026-10-28).  A false-safe on a planned class is therefore always owned, so ``emit`` without
    ``--planned`` refuses only for a class outside this table."""
    return {
        c: ({"owned_until_slice": DEFAULT_OWNERS[c], "measurement_only": True} if c in MEASUREMENT_ONLY_CLASSES else {"owned_until_slice": DEFAULT_OWNERS[c]})
        for c in DEFAULT_PLANNED
    }


def _row(case: dict, result: Mapping[str, Any], report_sha: str, report: Mapping[str, Any]) -> dict:
    source = case["source"]
    corpus = case.get("corpus_case") or {}
    target = case.get("target") or {}
    case_id = str(case["case_id"])
    slug = result.get("resolved_slug") or source.get("slug")
    return {
        "key": f"{slug}/p{corpus.get('page_index')}/show{corpus.get('show_seq')}#{_variant(case_id)}",
        "slug": slug,
        "page_index": corpus.get("page_index"),
        "show_seq": corpus.get("show_seq"),
        "original": corpus.get("original") if source.get("provenance") == "public" else None,
        "original_sha256": corpus.get("original_sha256"),
        # V12: original is the target SLICE; the whole show and the slice's coordinates travel with the row
        "show_text_sha256": corpus.get("show_text_sha256"),
        "item_range": target.get("item_range"),
        "byte_range_in_item": target.get("byte_range_in_item"),
        "replacement": corpus.get("replacement"),
        "font_resource": corpus.get("font_resource"),
        "basefont": corpus.get("basefont"),
        "font_kind": corpus.get("font_kind"),
        "class_id": case.get("class_id"),
        "kind": case.get("kind"),
        "expected_tier": None,
        "expected_tj_compensation": None,
        "expected_reason": None,
        "expected_reason_at_head": None,
        "click_reachable": False,
        "state": "candidate",
        "owned_until_slice": None,
        "false_safe_oracle": None,
        "twin": None,
        "twin_waiver": None,
        "provenance": {
            "batch": report.get("batch"),
            "case_id": case_id,
            "rederive_head": report.get("head"),
            "rederive_report_sha256": report_sha,
            "rederive_date": report.get("date_utc"),
        },
    }


# --------------------------------------------------------------------------
# report and unverifiable closure
# --------------------------------------------------------------------------
def build_report(
    batch_name: str,
    results: Iterable[RederiveResult],
    *,
    head: str,
    validation_sha256: str,
    date_utc: str | None = None,
    unverifiable_closure: Mapping[str, Any] | None = None,
) -> dict:
    report: dict = {
        "schema": "evidence-rederive/1",
        "batch": batch_name,
        "head": head,
        "date_utc": date_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "validation_sha256": validation_sha256,
        "results": [_plain(asdict(r)) for r in results],
    }
    if unverifiable_closure is not None:
        report["unverifiable_closure"] = {
            key: [_closure_item(i) for i in unverifiable_closure.get(key, [])] for key in ("closed", "open")
        }
    return report


def _closure_item(item: Mapping[str, Any]) -> dict:
    """Only the structural part of a validator item: a code word and a case id in its printable shape."""
    code = str(item.get("code", ""))
    case_id = item.get("case_id")
    return {
        "code": code if re.fullmatch(r"[a-z0-9_]{1,40}", code) else eb._digest(code),
        "case_id": None if case_id is None else eb._show_id(case_id),
    }


def close_unverifiable(items: Iterable[Mapping[str, Any]], results: Iterable[RederiveResult | Mapping[str, Any]]) -> dict:
    """Every validator ``unverifiable`` item is closed by a recompute here or by a quarantine, else reported open."""
    by_case: dict[str, Mapping[str, Any]] = {}
    for r in results:
        entry: Mapping[str, Any] = asdict(r) if isinstance(r, RederiveResult) else r
        by_case[str(entry.get("case_id"))] = entry
    closed: list[Mapping[str, Any]] = []
    still_open: list[Mapping[str, Any]] = []
    for item in items:
        owner = by_case.get(str(item.get("case_id"))) if item.get("case_id") else None
        data: Mapping[str, Any] | None = owner
        if data is None:
            still_open.append(item)  # case-less (calibration_incomplete, plan_row_invalid): left open for the triage reader
        elif data.get("outcome") in ("quarantined", "skipped", "validator_rejected") or item.get("code") in (data.get("closed_unverifiable") or []):
            closed.append(item)
        else:
            still_open.append(item)
    return {"closed": closed, "open": still_open}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _git_head(repo_root: Path) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, read-only
            ["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip() or "unknown"


def _printable_code(code: object) -> str:
    text = str(code)
    return text if re.fullmatch(r"[a-z0-9_]{1,40}", text) else eb._digest(text)


def _is_batch_level(violation: Mapping[str, Any]) -> bool:
    code = str(violation.get("code", ""))
    if code.startswith(("done_", "parent_")) or code in BATCH_LEVEL_CODES:
        return True
    if code == "file_missing":
        return Path(str(violation.get("file", ""))).as_posix() in eb.REQUIRED_BATCH_FILES
    return False


def _validation_tie_problem(validation: object, batch_dir: Path, cases_bytes: bytes) -> str | None:
    """Why ``validation`` is not the validator's report for exactly this batch's cases.json (None = it is)."""
    if not isinstance(validation, dict) or validation.get("schema") != "evidence-validation/1":
        return "schema"
    if validation.get("batch") != eb._scrub_file(batch_dir.name):
        return "batch"
    if validation.get("cases_json_sha256") != _sha256(cases_bytes):
        return "cases"
    return None


def _hvac_resolvable(registry: CorpusRegistry) -> bool:
    """A registry entry for the hvac file (its sha, or the slug ``hvac``) resolves to a hash-verified file on disk."""
    return any((e.sha256 == eb.HVAC_SHA256 or e.slug == "hvac") and registry.resolve(e) is not None for e in registry.entries)


def _calibration_problem(batch_dir: Path, registry: CorpusRegistry) -> dict | None:
    """Brief 2.3: ``synthetic_only`` is the fallback for a missing (or different) hvac file only.

    The validator catches a row measured on hvac; this catches a batch that claims synthetic_only while the hvac file
    resolves here.  A missing or unreadable PARENT_SUMMARY is the validator's file_missing / parent_* violation.
    """
    try:
        summary = json.loads((batch_dir / "PARENT_SUMMARY.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if _g(summary, "calibration", "status") != "synthetic_only" or not _hvac_resolvable(registry):
        return None
    return {
        "code": "synthetic_only_with_hvac_resolvable",
        "file": "PARENT_SUMMARY.json",
        "pointer": "/calibration/status",
        "detail": "",
        "case_id": None,
    }


@contextmanager
def _production_text_flags() -> Iterator[None]:
    """R16: ``PDFModel.__init__``'s process-global small glyph heights (ON, ``model/pdf_model.py``) and PyMuPDF's default quad
    corrections, as ``test_scripts/conftest.py`` pins them for acc and the twins.  The CLI process sets neither flag, and the shared
    helpers' rawdict boxes (``count_growth_zone_glyphs``) depend on the first; restored on exit, also on an exception."""
    glyph, quad = bool(fitz.TOOLS.set_small_glyph_heights()), bool(fitz.TOOLS.unset_quad_corrections())
    fitz.TOOLS.set_small_glyph_heights(True)
    fitz.TOOLS.unset_quad_corrections(False)
    try:
        yield
    finally:
        fitz.TOOLS.set_small_glyph_heights(glyph)
        fitz.TOOLS.unset_quad_corrections(quad)


def _assertions_disabled() -> bool:
    """True under ``python -O`` / ``-OO``: the oracle helpers' preconditions are ``assert`` statements and would not run."""
    return sys.flags.optimize > 0


def _cmd_rederive(args: argparse.Namespace) -> int:
    if _assertions_disabled():
        print("refused: assertions are disabled (python -O); the oracle helpers rely on them", file=sys.stderr)
        return 2
    batch_dir = Path(args.batch_dir)
    try:
        validation_bytes = Path(args.validation).read_bytes()
        validation = json.loads(validation_bytes)
        cases_bytes = (batch_dir / "cases.json").read_bytes()
        cases = json.loads(cases_bytes.decode("utf-8"))
    except (OSError, ValueError) as exc:
        print(f"refused: {type(exc).__name__} while reading the validation report or cases.json", file=sys.stderr)
        return 2
    problem = _validation_tie_problem(validation, batch_dir, cases_bytes)
    if problem is not None:
        print(f"refused: the validation report does not belong to this batch ({problem})", file=sys.stderr)
        return 2
    violations = [v for v in validation.get("violations", []) if isinstance(v, dict)]
    if "self_check" in validation and validation["self_check"] is not False:
        # a --self-check report skipped the DONE.json / VALIDATION.self.json presence rules: it never gates a rederive
        violations.append(
            {"code": "validation_is_self_check", "file": "VALIDATION.json", "pointer": "/self_check", "detail": "", "case_id": None}
        )
    case_list = cases if isinstance(cases, list) else []
    forms: dict[str, str] = {}  # every spelling the validator may use for a case id -> the raw id
    for case in case_list:
        if isinstance(case, dict) and case.get("case_id"):
            raw = str(case["case_id"])
            forms[raw] = raw
            forms[str(eb._show_id(raw))] = raw  # an id outside the r2 shape is printed as a digest, in case_id and in cases/<digest>/
    rejected: set[str] = set()
    blocking: list[Mapping[str, Any]] = []
    for v in violations:
        owner = forms.get(str(v["case_id"])) if v.get("case_id") else None
        if owner is None:
            m = re.match(r"cases/([^/]+)/", Path(str(v.get("file", ""))).as_posix())
            owner = forms.get(m.group(1)) if m else None
        if _is_batch_level(v) or owner is None:
            blocking.append(v)  # a violation that belongs to no case taints the whole batch
        else:
            rejected.add(owner)
    repo_root = Path(args.repo_root).resolve()
    try:
        registry = load_registry(
            repo_root,
            public_list=Path(args.public_list) if args.public_list else None,
            manifest=Path(args.manifest) if args.manifest else None,
        )
    except (OSError, ValueError, KeyError) as exc:
        print(f"refused: {type(exc).__name__} while loading the corpus registry", file=sys.stderr)
        return 2
    calibration = _calibration_problem(batch_dir, registry)
    if calibration is not None:
        blocking.append(calibration)
    if blocking:
        codes = sorted({_printable_code(v.get("code")) for v in blocking})
        print(f"refused: {len(blocking)} batch-level violation(s): {codes}", file=sys.stderr)
        return 2
    statuses = _d(_g(validation, "recomputed", "statuses"))
    work = Path(tempfile.mkdtemp(prefix="evidence-rederive-"))
    results: list[RederiveResult] = []
    try:
        with _production_text_flags():
            for index, case in enumerate(cases if isinstance(cases, list) else []):
                case_id = str(case.get("case_id")) if isinstance(case, dict) and case.get("case_id") else f"case-{index}"
                if case_id in rejected or not isinstance(case, dict):
                    res = RederiveResult(case_id=str(eb._show_id(case_id)), outcome="validator_rejected")
                    results.append(res)
                    continue
                res = rederive_case(case, batch_dir, registry, work_dir=work)
                status = statuses.get(case_id, statuses.get(str(eb._show_id(case_id))))
                res.validated_status = status if isinstance(status, str) and re.fullmatch(r"[a-z_]{1,32}", status) else None
                results.append(res)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    closure = close_unverifiable([u for u in validation.get("unverifiable", []) if isinstance(u, dict)], results)
    report = build_report(
        batch_dir.name,
        results,
        head=_git_head(repo_root),
        validation_sha256=_sha256(validation_bytes),
        unverifiable_closure=closure,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return 1 if any(r.outcome == "quarantined" for r in results) else 0


def _cmd_emit(args: argparse.Namespace) -> int:
    report_path = Path(args.report)
    try:
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes)
        cases = json.loads((Path(args.batch) / "cases.json").read_text(encoding="utf-8"))
        planned: object = json.loads(Path(args.planned).read_text(encoding="utf-8")) if args.planned else default_plan()
    except (OSError, ValueError) as exc:
        print(f"refused: {type(exc).__name__} while reading the report, cases.json or planned classes", file=sys.stderr)
        return 2
    try:
        _check_planned(planned)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    try:
        rows, findings = emit_rows(cases, report, planned, report_sha256=_sha256(report_bytes))
    except ValueError as exc:  # a false-safe whose class has no planned slice: nothing is written
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "findings": findings}, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence_rederive", description="Re-derive a Grok-round evidence bundle at HEAD.")
    sub = parser.add_subparsers(dest="command", required=True)
    red = sub.add_parser("rederive", help="re-derive every case of a validated batch and write rederive_report.json")
    red.add_argument("batch_dir")
    red.add_argument("--validation", required=True)
    red.add_argument("--out", required=True)
    red.add_argument("--repo-root", default=".")
    red.add_argument("--public-list", default=None)
    red.add_argument("--manifest", default=None, help="true-text corpus manifest (default: the tracked one under the repo root)")
    red.set_defaults(func=_cmd_rederive)
    emit = sub.add_parser("emit", help="print manifest rows for a rederive report (never edits a manifest)")
    emit.add_argument("report")
    emit.add_argument("--batch", required=True)
    emit.add_argument("--out", required=True)
    emit.add_argument("--planned", default=None, help="JSON mapping class_id -> {owned_until_slice, measurement_only}; F2R/F2G stay held unless measurement_only is false")
    emit.set_defaults(func=_cmd_emit)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
