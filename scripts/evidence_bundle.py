"""Validator for Grok-round evidence bundles (``true-text-case/2``).

Stdlib plus two fitz-free product modules (``pdf_lexer``, ``dto``).  It checks
what arithmetic on the recorded numbers can check: schema shape, cross-field
rules, per-phase recomputation, the status table, the parent summary,
calibration, pre-registration, artifacts and redaction.  Everything that needs
the original file (re-lex, frame conversion, background quad, ParentTree walk,
the advance values themselves) is listed under ``unverifiable`` and measured
by ``scripts/evidence_rederive.py``; unverifiable never means pass and never
fails the CLI.

Run as ``.venv\\Scripts\\python.exe -B scripts\\evidence_bundle.py validate
<batch> --out <json>``.  Exit code 1 iff any violation.  Reports carry
batch-relative paths and never echo matched client or machine text.
"""
from __future__ import annotations

import argparse
import builtins
import dataclasses
import hashlib
import json
import logging
import math
import re
import sys
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeGuard

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from model.text_commit.pdf_lexer import (  # noqa: E402
    TokenKind,
    decode_hex_string,
    decode_literal_string,
    lex_content_stream,
)
from scripts.hooks.pre_commit_device_guard import PATTERNS  # noqa: E402

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
SCHEMA_DIR = ROOT / "scripts" / "evidence_schemas"
CASE_SCHEMA_NAME = "true_text_case.v2.schema.json"
PARENT_SCHEMA_NAME = "true_text_parent.v2.schema.json"
PLAN_SCHEMA_NAME = "true_text_plan.v2.schema.json"
DEFAULT_DENYLIST = ROOT / "test_files" / ".redaction_denylist.txt"

PHASE_NAMES = (
    "probe",
    "structure",
    "growth_zone",
    "render_mupdf",
    "render_poppler",
    "neighbours",
    "glyph_identity",
    "extraction",
    "save_reopen",
)
STATUS_KEYS = (
    "probe_rejected",
    "splice_pass",
    "save_reopen_pass",
    "insufficient_evidence",
    "blocked",
    "out_of_scope_vector",
)
F_CLASSES = frozenset({"F30B", "F30W", "F30N", "F1", "F2I", "F2R", "F2G", "F2K", "F3", "F17", "F31", "F5", "F4", "F6"})
COUNTED_KINDS = frozenset({"positive", "negative", "census"})

# The 12 ``marked_content.CLASS_*`` slugs (that module imports fitz, so the
# values are mirrored here and pinned by a parity test).
WRAPPER_SLUGS = frozenset(
    {
        "oc_layer_visible_default",
        "oc_layer_hidden_default",
        "oc_ocmd",
        "actual_text",
        "alt_text",
        "artifact",
        "struct_content",
        "bmc_bare",
        "bdc_other",
        "props_unresolved",
        "props_unparsed",
        "malformed_pairing",
    }
)
# Calibration-row exemption (brief 5.4): the five literals that already sit in
# plain text in the acceptance file.  Parity-tested against its source text.
CALIBRATION_STRINGS = (
    "空調冰水管線系統圖(1)",
    "空調冰水管線系統圖(4)",
    "Drawing List",
    "Drawing Title",
    "空調冰水管路系統圖(1)",
)
CALIBRATION_CLASSES = frozenset(
    {
        "CTRL_POS_T0",
        "CTRL_POS_T1",
        "CTRL_NEG",
        "CANARY_KSIGN",
        "CANARY_TC",
        "CANARY_FONT",
        "CANARY_UNSAVED",
        "CANARY_WRONGGLYPH",
        "CANARY_INK",
    }
)
# brief 2.2: phases that must FAIL for a canary to count as caught.
MUST_FAIL_PHASES: dict[str, tuple[str, ...]] = {
    "CANARY_KSIGN": ("structure",),
    "CANARY_TC": ("structure",),
    "CANARY_FONT": ("structure", "glyph_identity"),
    "CANARY_UNSAVED": ("save_reopen", "extraction"),
    "CANARY_WRONGGLYPH": ("glyph_identity", "extraction"),
    "CANARY_INK": ("render_mupdf", "render_poppler", "neighbours"),
    "CANARY_GROWTH": ("growth_zone", "neighbours"),
}
COMMITTED_STATUSES = ("committed", "degraded_committed")  # model.text_commit.dto.CommitStatus values that mean the stream changed
R0_CONTROLS = ("CTRL_POS_T0", "CTRL_POS_T1", "CTRL_NEG", "CTRL_DET", "CTRL_SYN_T0", "CTRL_SYN_T1")
# The hvac file (acceptance corpus) and the three controls pinned to it (brief 2.1): class -> (slug, page_index, show_seq).
HVAC_SHA256 = "9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2"
CONTROL_SITES: dict[str, tuple[str, int, int]] = {
    "CTRL_POS_T0": ("hvac", 4, 11),
    "CTRL_NEG": ("hvac", 4, 11),
    "CTRL_POS_T1": ("hvac", 4, 26),
}
GROWTH_LEGS = ("geometry_overlap", "growth_zone_glyph", "growth_zone_raster", "neighbours_overlap")
SYNTHETIC_ALLOWLIST = frozenset({"test_scripts.type0_fixture_builder.build_identity_h_fixture"})
CTRL_SYN_KWARGS = {"text": "你好世界", "rotate": 270, "tail_text": "後綴"}
SYNTHETIC_CLASSES = frozenset({"CTRL_SYN_T0", "CTRL_SYN_T1", "CANARY_GROWTH"})
TABLE_333 = frozenset(
    "Document Part Art Sect Div P H H1 H2 H3 H4 H5 H6 L LI Lbl LBody Table TR TH TD Span Quote Note Reference "
    "BibEntry Code Link Annot Figure Formula Form Artifact OC".split()
)
STD_PROPERTY_KEYS = frozenset("MCID Lang E ActualText Alt Type Subtype BBox Attached O OC".split())
STRUCTELEM_VOCAB = ("ActualText", "Alt", "E", "Lang")
REJECT_REASON_VALUES = frozenset(
    v for k, v in vars(RejectReason).items() if not k.startswith("_") and isinstance(v, str)
)

BBOX_TOL = 1e-3
NUM_TOL = 1e-6
OWN_CHAR_TOL_PT = 0.5

REQUIRED_BATCH_FILES = (
    "METHODS_AND_EVIDENCE_PLAN.md",
    "run_pilot.py",
    "cases.json",
    "PARENT_SUMMARY.json",
    "CROSS_BATCH_DELTA.json",
    "REDACTION.json",
    "INVENTORY.md",
    "README.md",
    "VALIDATION.self.json",
    "DONE.json",
)
REQUIRED_CASE_FILES = ("case_record.json", "neighbours.json", "text_state.json", "mutation.json")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PLACEHOLDER_RE = re.compile(r"\[PLACEHOLDER_[0-9]+\]")
_CASE_ID_TAIL_RE = re.compile(r"^(eq|grow|neg|ctrl|can|cen)[0-9]+$")

# Free-text fields (brief 1, language rule), as pointer patterns; ``*`` = any index/key.
FREE_TEXT_POINTERS = (
    "/observation",
    "/hypotheses/*/statement",
    "/hypotheses/*/falsification",
    "/next_check",
    "/limits/*",
    "/attempts/*/outcome",
    "/attempts/*/variable_changed",
    "/peel_chain/*/removed_feature",
    "/phases/*/detail",
    "/source/lineage_reason",
    "/mutation/variable_changed",
)

_NEIGHBOUR_KEYS: dict[str, tuple] = {
    "trace_index_before": ("int", "null"),
    "trace_index_after": ("int", "null"),
    "show_index": ("int",),
    "char_index_before": ("int", "null"),
    "char_index_after": ("int", "null"),
    "gid_before": ("int", "null"),
    "gid_after": ("int", "null"),
    "origin_before": ("num2", "null"),
    "origin_after": ("num2", "null"),
    "bbox_before": ("num4", "null"),
    "bbox_after": ("num4", "null"),
    "origin_delta_pt": ("num", "null"),
    "role": ("role",),
    "is_space": ("bool",),
    "ink_checked": ("bool",),
    "ink_changed_px_6x": ("int", "null"),
    "overlap": ("bool",),
    "halo_shadowed": ("bool",),
    "ink_after_px_6x": ("int", "null"),
}
NEIGHBOUR_ROLES = ("untouched", "inshow_successor", "target")


# --------------------------------------------------------------------------
# types
# --------------------------------------------------------------------------
class SchemaSubsetError(ValueError):
    """A schema uses a keyword outside the supported subset."""


@dataclass(frozen=True)
class Violation:
    """One entry of ``VALIDATION.json``."""

    code: str
    file: str
    pointer: str
    detail: str
    case_id: str | None = None


@dataclass
class CheckResult:
    violations: list[Violation] = field(default_factory=list)
    unverifiable: list[Violation] = field(default_factory=list)  # never fails the CLI
    fails: dict[str, list[str]] = field(default_factory=dict)  # phase -> reasons the recompute FAILS it
    not_run: dict[str, list[str]] = field(default_factory=dict)  # phase -> reasons it cannot be decided
    info: dict = field(default_factory=dict)  # recomputed side data (calibration)

    def extend(self, other: CheckResult) -> None:
        self.violations += other.violations
        self.unverifiable += other.unverifiable
        for src, dst in ((other.fails, self.fails), (other.not_run, self.not_run)):
            for phase, reasons in src.items():
                dst.setdefault(phase, []).extend(reasons)


@dataclass(frozen=True)
class PhaseCheck:
    result: str  # pass | fail | not_run | blocked
    reasons: tuple[str, ...] = ()


@dataclass
class Batch:
    root: Path
    cases: list[dict]
    records: dict[str, list[dict]]
    parent: dict | None
    done: dict | None
    plan_text: str | None
    plan_bytes: bytes | None = None
    parent_bytes: bytes | None = None


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
_SAFE_KEY = re.compile(r"[A-Za-z0-9_.@:/#-]{1,120}")
_SAFE_REL = re.compile(r"[A-Za-z0-9_./#-]{1,200}")


_OWN_KEYS = frozenset(
    "nine_phases_pass growth_applicable commit_tier K_written K_sum gate_counters raster_proof reason mutation_null status tier "
    "attempted tier1 tier0 growth_phase control_rerender site must_fail_phases failed_phases caught legs missed_legs expected "
    "observed ok failed controls canaries growth_canary_sites phases statuses calibration parent_summary result reasons "
    "cases_total by_status per_class product_findings case_id kind detail text rotate tail_text".split()
) | frozenset(("geometry_overlap", "growth_zone_glyph", "growth_zone_raster", "neighbours_overlap"))
_KNOWN_KEYS: frozenset[str] | None = None


def _known_keys() -> frozenset[str]:
    """Key names that may be printed: schema property names, enum words and this module's own report keys."""
    global _KNOWN_KEYS
    if _KNOWN_KEYS is None:
        names: set[str] = set(_OWN_KEYS) | set(_NEIGHBOUR_KEYS) | set(STATUS_KEYS) | set(PHASE_NAMES) | set(MUST_FAIL_PHASES)
        names |= F_CLASSES | {"OUT", "CTRL_POS_T0", "CTRL_POS_T1", "CTRL_NEG", "CTRL_DET", "CTRL_SYN_T0", "CTRL_SYN_T1"}

        def walk(node: object) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("properties", "$defs") and isinstance(value, dict):
                        names.update(value)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        for fname in (CASE_SCHEMA_NAME, PARENT_SCHEMA_NAME, PLAN_SCHEMA_NAME):
            try:
                walk(json.loads((SCHEMA_DIR / fname).read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        names.update(_DONE_KEYS)
        _KNOWN_KEYS = frozenset(names)
    return _KNOWN_KEYS


_DONE_KEYS = ("stamp", "case_count", "parent_summary_sha256")


def _esc(key: object) -> str:
    """RFC 6901 escape.  Only schema-known key names, indexes and digests print as they are.

    Keys come from untrusted JSON.  Echoing an unknown one into VALIDATION.json could
    write a client string or a machine path into a report that may be committed.
    """
    text = str(key)
    if not (text.isdigit() or re.fullmatch(r"#[0-9a-f]{12}", text) or text in _known_keys()):
        return "#" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]
    return text.replace("~", "~0").replace("/", "~1")


_CASE_ID_SHOWN = re.compile(r"r2-[A-Z0-9_]+-[0-9a-f]{8}-p[0-9]+-s[0-9]+-(?:eq|grow|neg|ctrl|can|cen)[0-9]+")


def _digest(text: str) -> str:
    return "#" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:12]


def _pe(key: object) -> str:
    """Plain RFC 6901 escape, for keys the schema itself declares."""
    return str(key).replace("~", "~0").replace("/", "~1")


_KNOWN_SEGMENTS = frozenset(REQUIRED_BATCH_FILES) | frozenset(REQUIRED_CASE_FILES) | {"cases", "candidates", "before.pdf", "work_copy.pdf"}
_SEGMENT_PATTERNS = (
    re.compile(r"render-(?:mupdf|poppler)-(?:before|after)-6x\.png"),
    re.compile(r"render-(?:mupdf|poppler)-fullpage-diff-2x\.png"),
    re.compile(r"render-growthstrip-before-6x\.png|render-reopened-2x\.png"),
    re.compile(r"peel-[0-9]{1,2}\.pdf"),
    re.compile(r"[0-9]{8}_[0-9]{4}(?:_[a-z0-9_]{1,40})?"),
    re.compile(r"#[0-9a-f]{12}"),
)


def _safe_rel(rel: str) -> str:
    """A batch-relative path that is safe to print: only structural segments print, others as digests."""
    out = []
    for seg in rel.split("/"):
        known = seg in _KNOWN_SEGMENTS or _CASE_ID_SHOWN.fullmatch(seg) or any(p.fullmatch(seg) for p in _SEGMENT_PATTERNS)
        out.append(seg if known else _digest(seg))
    return "/".join(out)


_VOCAB = (
    frozenset({"pass", "fail", "not_run", "blocked", "exception", "prepared", "rejected"})
    | frozenset(STATUS_KEYS)
    | frozenset(PHASE_NAMES)
    | frozenset({"string_token", "whole_operator", "tj_item", "tj_run", "string_fragment", "fragment_split", "canary"})
    | REJECT_REASON_VALUES
)


def _show_id(cid: object) -> str | None:
    """A case id is printed only in its structural shape (brief 5.1), digest otherwise."""
    if cid is None:
        return None
    if isinstance(cid, str) and (_CASE_ID_SHOWN.fullmatch(cid) or re.fullmatch(r"#[0-9a-f]{12}", cid)):
        return cid
    return _digest(str(cid))


def _vocab(value: object) -> str:
    """A bundle-supplied word is printed only if it is a known enum or reason value."""
    return value if isinstance(value, str) and value in _VOCAB else _digest(str(value))


def _scrub_file(rel: str) -> str:
    return _safe_rel(rel)


def _g(obj: object, *path: object, default: Any = None) -> Any:
    """Null-safe nested lookup over dicts and lists."""
    cur: Any = obj
    for key in path:
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and isinstance(key, int) and -len(cur) <= key < len(cur):
            cur = cur[key]
        else:
            return default
        if cur is None:
            return default
    return cur


def _dict(value: object) -> dict[str, Any]:
    """``value`` when it is an object, else an empty one (a malformed record reads as absent fields)."""
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict_or_none(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _is_num(x: object) -> TypeGuard[float]:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _close(a: object, b: object, tol: float) -> bool:
    return _is_num(a) and _is_num(b) and abs(a - b) <= tol  # type: ignore[operator]


def _bbox_ok(box: object) -> TypeGuard[list[float]]:
    return isinstance(box, list) and len(box) == 4 and all(_is_num(v) for v in box)


def _bbox_close(a: object, b: object, tol: float = BBOX_TOL) -> bool:
    return _bbox_ok(a) and _bbox_ok(b) and all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))  # type: ignore[call-overload]


def _bbox_union(boxes: list[list[float]]) -> list[float] | None:
    if not boxes:
        return None
    return [
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    ]


def _bbox_intersects(a: list[float], b: list[float]) -> bool:
    """Positive-area intersection (touching edges do not count)."""
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _is_hex(text: object, *, even: bool = True) -> bool:
    return isinstance(text, str) and re.fullmatch(r"([0-9A-Fa-f]{2})*", text) is not None and (not even or len(text) % 2 == 0)


def _ascii_printable(text: str) -> bool:
    return all(0x20 <= ord(ch) <= 0x7E for ch in text)


_CJK_PREFIXES = ("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH", "HIRAGANA", "KATAKANA", "HANGUL SYLLABLE")


def _is_cjk(ch: str) -> bool:
    return unicodedata.name(ch, "").startswith(_CJK_PREFIXES)


def _tokens(text: str) -> tuple[list[str], list[str]]:
    """Latin words (casefolded) and CJK characters of ``text`` (brief 5.4 tokenizer)."""
    stripped = _PLACEHOLDER_RE.sub(" ", text)
    words = [w.casefold() for w in re.findall(r"[A-Za-z]+", stripped)]
    cjk = [ch for ch in stripped if _is_cjk(ch)]
    return words, cjk


# --------------------------------------------------------------------------
# schema subset validator
# --------------------------------------------------------------------------
_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$defs",
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minLength",
        "pattern",
        "minimum",
        "anyOf",
        "$ref",
    }
)
_REGEX_CACHE: dict[str, re.Pattern[str]] = {}


def _check_subset(node: object, where: str) -> None:
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key not in _SCHEMA_KEYWORDS:
            raise SchemaSubsetError(f"keyword {key!r} at {where or '/'} is outside the supported subset")
        if key == "properties" and isinstance(value, dict):
            for name, sub in value.items():
                _check_subset(sub, f"{where}/properties/{name}")
        elif key == "$defs" and isinstance(value, dict):
            for name, sub in value.items():
                _check_subset(sub, f"{where}/$defs/{name}")
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            _check_subset(value, f"{where}/{key}")
        elif key == "anyOf" and isinstance(value, list):
            for idx, sub in enumerate(value):
                _check_subset(sub, f"{where}/anyOf/{idx}")


def load_schema(path: Path) -> dict:
    """Load a schema file and refuse any keyword outside the validator's subset."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    _check_subset(data, "")
    return data


def _jeq(a: object, b: object) -> bool:
    """JSON equality that never confuses bool with 0/1."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_num(a) and _is_num(b):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_jeq(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_jeq(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def _type_ok(inst: object, name: str) -> bool:
    if name == "null":
        return inst is None
    if name == "boolean":
        return isinstance(inst, bool)
    if name == "integer":
        return (isinstance(inst, int) and not isinstance(inst, bool)) or (isinstance(inst, float) and inst.is_integer())
    if name == "number":
        return _is_num(inst)
    if name == "string":
        return isinstance(inst, str)
    if name == "array":
        return isinstance(inst, list)
    if name == "object":
        return isinstance(inst, dict)
    return False


def _resolve_ref(ref: str, root: dict) -> dict | None:
    m = re.fullmatch(r"#/\$defs/([A-Za-z0-9_]+)", ref)
    if not m:
        return None
    node = _g(root, "$defs", m.group(1))
    return node if isinstance(node, dict) else None


def _admits(branch: dict, inst: object, root: dict) -> bool:
    node = branch
    if "$ref" in node:
        resolved = _resolve_ref(node["$ref"], root)
        if resolved is None:
            return True
        node = resolved
    types = node.get("type")
    if types is None:
        return True
    names = types if isinstance(types, list) else [types]
    return any(_type_ok(inst, n) for n in names)


def validate_instance(obj, schema, *, root=None, pointer="", file: str = "") -> list[Violation]:
    """Validate ``obj`` against ``schema`` (the subset the three schema files use)."""
    root = schema if root is None else root
    out: list[Violation] = []

    def add(code: str, ptr: str, detail: str) -> None:
        out.append(Violation(code, file, ptr, detail))

    if "$ref" in schema:
        target = _resolve_ref(schema["$ref"], root)
        if target is None:
            add("schema_ref_unresolved", pointer, "reference outside #/$defs or missing")
        else:
            out += validate_instance(obj, target, root=root, pointer=pointer, file=file)
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(obj, n) for n in names):
            add("schema_type", pointer, f"expected {'|'.join(names)}")
    if "const" in schema and not _jeq(obj, schema["const"]):
        add("schema_const", pointer, "value differs from the required constant")
    if "enum" in schema and not any(_jeq(obj, member) for member in schema["enum"]):
        add("schema_enum", pointer, "value is outside the allowed vocabulary")
    if isinstance(obj, str):
        if "minLength" in schema and len(obj) < schema["minLength"]:
            add("schema_min_length", pointer, "string shorter than allowed")
        if "pattern" in schema:
            pat = _REGEX_CACHE.setdefault(schema["pattern"], re.compile(schema["pattern"]))
            if not pat.search(obj):
                add("schema_pattern", pointer, "string does not match the required pattern")
    if _is_num(obj) and "minimum" in schema and obj < schema["minimum"]:
        add("schema_minimum", pointer, "number below the minimum")
    if isinstance(obj, list):
        if "minItems" in schema and len(obj) < schema["minItems"]:
            add("schema_min_items", pointer, "array shorter than allowed")
        if "maxItems" in schema and len(obj) > schema["maxItems"]:
            add("schema_max_items", pointer, "array longer than allowed")
        if isinstance(schema.get("items"), dict):
            for idx, item in enumerate(obj):
                out += validate_instance(item, schema["items"], root=root, pointer=f"{pointer}/{idx}", file=file)
    if isinstance(obj, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in obj:
                add("schema_required", f"{pointer}/{_pe(key)}", "required key is missing")
        for key, value in obj.items():
            ptr = f"{pointer}/{_esc(key)}"
            if key in props:
                out += validate_instance(value, props[key], root=root, pointer=f"{pointer}/{_pe(key)}", file=file)
            elif schema.get("additionalProperties") is False:
                add("schema_additional", ptr, "key is not allowed here")
            elif isinstance(schema.get("additionalProperties"), dict):
                out += validate_instance(value, schema["additionalProperties"], root=root, pointer=ptr, file=file)
    if "anyOf" in schema:
        branches = schema["anyOf"]
        admitting = [b for b in branches if _admits(b, obj, root)]
        if len(admitting) == 1:
            out += validate_instance(obj, admitting[0], root=root, pointer=pointer, file=file)
        elif not any(not validate_instance(obj, b, root=root, pointer=pointer, file=file) for b in branches):
            add("schema_any_of", pointer, "no alternative accepts the value")
    return out


# --------------------------------------------------------------------------
# per-case accumulator
# --------------------------------------------------------------------------
class _Acc:
    """Collects violations, unverifiable notes and phase reasons for one case."""

    def __init__(self, case: dict, file: str | None = None) -> None:
        self.case = case
        cid = case.get("case_id") if isinstance(case, dict) else None
        self.raw_id = cid if isinstance(cid, str) else None  # compared, never printed
        self.case_id = _show_id(self.raw_id)
        self.file = file or (f"cases/{self.case_id}/case_record.json" if self.case_id else "cases.json")
        self.res = CheckResult()

    def v(self, code: str, pointer: str, detail: str) -> None:
        self.res.violations.append(Violation(code, self.file, pointer, detail, self.case_id))

    def u(self, code: str, pointer: str, detail: str) -> None:
        self.res.unverifiable.append(Violation(code, self.file, pointer, detail, self.case_id))

    def fail(self, phase: str, reason: str) -> None:
        self.res.fails.setdefault(phase, []).append(reason)

    def undecided(self, phase: str, reason: str) -> None:
        self.res.not_run.setdefault(phase, []).append(reason)


def _advances(case: dict) -> list[tuple[str, dict]]:
    """``(pointer, advance object)`` pairs; empty when there is no usable advance."""
    adv = _g(case, "mutation", "advance")
    if isinstance(adv, dict):
        return [("/mutation/advance", adv)]
    if isinstance(adv, list):
        return [(f"/mutation/advance/{i}", a) for i, a in enumerate(adv) if isinstance(a, dict)]
    return []


def _tolerance(adv: dict) -> float | None:
    tfs = adv.get("Tfs")
    source = adv.get("advance_source")
    if not _is_num(tfs):
        return None
    if source == "face":
        return max(1e-3 * tfs, 1e-4)
    if source in ("W", "DW", "Widths", "type3_widths"):
        return max(1e-9 * tfs, 1e-9)
    return None


def _expected_growth(adv: dict, trm: object, uu: object) -> float | None:
    if not all(_is_num(x) for x in (adv.get("adv_old_text_space"), adv.get("adv_new_text_space"), adv.get("Th"), trm, uu)):
        return None
    return max(0.0, adv["adv_new_text_space"] - adv["adv_old_text_space"]) * adv["Th"] * trm * uu  # type: ignore[operator]


def _applicable_expected(case: dict, adv: dict) -> bool | None:
    old, new, tol = adv.get("adv_old_text_space"), adv.get("adv_new_text_space"), _tolerance(adv)
    if not (_is_num(old) and _is_num(new)):
        return None
    if _g(case, "mutation", "path") == "product_commit":
        return _g(case, "probe", "commit", "tier") == 1 and new > old
    if tol is None:
        return None
    return new - old > tol


def _lex(data: bytes) -> list:
    return list(lex_content_stream(data))


def _operand_bytes(change: object, key: str = "new_operand_bytes_hex") -> bytes | None:
    hexed = _g(change, key)
    if not isinstance(hexed, str) or not _is_hex(hexed):
        return None
    return bytes.fromhex(hexed)


def _string_payloads(data: bytes) -> list[bytes] | None:
    """Decoded payloads of every STRING/HEXSTRING token; None when one will not decode."""
    out: list[bytes] = []
    for tok in _lex(data):
        raw = data[tok.start : tok.end]
        try:
            if tok.kind is TokenKind.STRING:
                out.append(decode_literal_string(raw))
            elif tok.kind is TokenKind.HEXSTRING:
                out.append(decode_hex_string(raw))
        except ValueError:
            return None
    return out


def _numbers(data: bytes) -> list[float]:
    out = []
    for tok in _lex(data):
        if tok.kind is TokenKind.NUMBER:
            try:
                out.append(float(data[tok.start : tok.end]))
            except ValueError:
                continue
    return out


def _k_numbers(data: bytes, canary: bool) -> list[float]:
    """The NUMBER tokens that are K tokens.

    Every number of a non-canary operand is one.  A canary operand may also carry operator operands (brief 2.2:
    ``0.25 Tc``, ``/C2_0 97.023 Tf``, ``x y 1 1 re``), so only the numbers inside a TJ array count there.
    """
    if not canary:
        return _numbers(data)
    out: list[float] = []
    depth = 0
    for tok in _lex(data):
        if tok.kind is TokenKind.ARRAY_OPEN:
            depth += 1
        elif tok.kind is TokenKind.ARRAY_CLOSE:
            depth = max(0, depth - 1)
        elif tok.kind is TokenKind.NUMBER and depth:
            try:
                out.append(float(data[tok.start : tok.end]))
            except ValueError:
                continue
    return out


def _glyph_code_bytes(case: dict) -> bytes | None:
    glyphs = case.get("glyph_identity")
    if not isinstance(glyphs, list):
        return None
    try:
        ordered = sorted(glyphs, key=lambda g: g["index"])
        return b"".join(bytes.fromhex(g["code_bytes_hex"]) for g in ordered)
    except (KeyError, TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# check_cross_field
# --------------------------------------------------------------------------
def check_cross_field(case: dict, records: list[dict] | None = None) -> CheckResult:
    """The brief 5.1 cross-field rules a schema cannot express."""
    acc = _Acc(case)
    kind, cls = case.get("kind"), case.get("class_id")
    src = _dict(case.get("source"))
    cc = _dict(case.get("corpus_case"))
    mut = _dict_or_none(case.get("mutation"))
    cid = acc.raw_id or ""

    # identifiers and paths
    head = f"r2-{cls}-{str(src.get('sha256', ''))[:8]}-p{cc.get('page_index')}-s{cc.get('show_seq')}-"
    tail = cid[len(head):] if cid.startswith(head) else None
    if tail is None or not _CASE_ID_TAIL_RE.match(tail):
        acc.v("case_id_mismatch", "/case_id", "case_id does not follow r2-<class>-<sha8>-p<page>-s<show>-<variant><k>")
    if case.get("join_key") != f"{src.get('slug')}/p{cc.get('page_index')}/show{cc.get('show_seq')}":
        acc.v("join_key_mismatch", "/join_key", "join_key is not <slug>/p<page>/show<show>")
    if _g(case, "artifacts", "dir") != f"cases/{cid}/":
        acc.v("artifact_path_mismatch", "/artifacts/dir", "artifact directory is not cases/<case_id>/")
    if _g(case, "neighbours", "records_file") != f"cases/{cid}/neighbours.json":
        acc.v("artifact_path_mismatch", "/neighbours/records_file", "records file is not cases/<case_id>/neighbours.json")

    # canary markers and kind <-> class
    is_canary = kind == "canary"
    if mut is not None:
        for key, value in (("splice_kind", "canary"), ("path", "canary"), ("method_id", "CANARY")):
            if (mut.get(key) == value) != is_canary:
                acc.v("canary_marker_mismatch", f"/mutation/{key}", f"{key} must be {value!r} exactly when kind is canary")
    elif is_canary:
        acc.v("canary_marker_mismatch", "/mutation", "a canary row needs a mutation")
    if isinstance(cls, str):
        ok = (
            (is_canary and cls.startswith("CANARY_"))
            or (kind == "control" and cls.startswith("CTRL_"))
            or (kind in COUNTED_KINDS and (cls in F_CLASSES or (cls == "OUT" and kind == "census")))
        )
        if not ok:
            acc.v("kind_class_mismatch", "/class_id", "kind and class_id do not belong together")

    # redaction nulls and path nulls
    prov = src.get("provenance")
    if prov not in ("public", "synthetic"):
        for pointer in ("/corpus_case/original", "/target/source_decode/latin1", "/target/source_decode/independent"):
            path_keys = [k for k in pointer.split("/")[1:]]
            if _g(case, *path_keys) is not None:
                acc.v("redaction_null_required", pointer, "non-public rows must carry null here and a sha256 instead")
        for i, ch in enumerate(_g(mut, "changes", default=[]) or []):
            if isinstance(ch, dict) and ch.get("old_operand_bytes_hex") is not None:
                acc.v("redaction_null_required", f"/mutation/changes/{i}/old_operand_bytes_hex", "non-public rows must carry null here")
    if prov not in ("public", "synthetic") and _g(mut, "splice_kind") in ("string_fragment", "fragment_split") and cc.get("font_kind") != "type0":
        # brief 5.4: a non-public simple-font payload is latin-1 text, and single letters pass the layer-2 allowlist
        acc.v("nonpublic_f3_not_type0", "/corpus_case/font_kind", "a non-public F3 row must be a Type0 font so its payload is CIDs, not letters")
    if prov in ("proprietary", "synthetic") and src.get("relative_path") is not None:
        acc.v("relative_path_must_be_null", "/source/relative_path", "proprietary and synthetic rows carry no path")
    if src.get("before_pdf_sha256") != src.get("sha256"):
        acc.v("before_pdf_sha_field", "/source/before_pdf_sha256", "before_pdf_sha256 must equal source.sha256")
    unchanged = _g(case, "save_reopen", "source_sha256_unchanged")
    after_run = src.get("sha256_after_run")
    if isinstance(unchanged, bool) and isinstance(after_run, str) and (after_run == src.get("sha256")) != unchanged:
        acc.v("source_sha_after_mismatch", "/source/sha256_after_run", "sha256_after_run equals sha256 exactly when source_sha256_unchanged is true")
    if isinstance(cc.get("replacement"), str) and isinstance(cc.get("replacement_sha256"), str):
        if cc["replacement_sha256"] != _sha256_bytes(cc["replacement"].encode("utf-8")):
            acc.v("replacement_sha_mismatch", "/corpus_case/replacement_sha256", "replacement_sha256 must be the sha256 of the replacement text")

    # synthetic provenance
    builder = src.get("synthetic_builder")
    if (builder is not None) != (prov == "synthetic"):
        acc.v("synthetic_builder_mismatch", "/source/synthetic_builder", "a builder is present exactly when provenance is synthetic")
    if isinstance(builder, dict):
        if builder.get("callable") not in SYNTHETIC_ALLOWLIST:
            acc.v("synthetic_builder_not_allowlisted", "/source/synthetic_builder/callable", "callable is not on the rederive allowlist")
        kwargs = builder.get("kwargs")
        if isinstance(kwargs, dict):
            for key, value in kwargs.items():
                if not (value is None or isinstance(value, (bool, int, float, str))):
                    acc.v("synthetic_kwargs_not_scalar", f"/source/synthetic_builder/kwargs/{_esc(key)}", "kwargs must be JSON scalars")
            if isinstance(cls, str) and cls.startswith("CTRL_SYN_") and not _jeq(kwargs, CTRL_SYN_KWARGS):
                acc.v("synthetic_pin_mismatch", "/source/synthetic_builder/kwargs", "CTRL_SYN rows pin their kwargs (brief 2.1)")
    if prov == "synthetic":
        allowed = kind in ("control", "canary") and (cls in SYNTHETIC_CLASSES or (is_canary and case.get("calibration_ref") == "synthetic_only"))
        if not allowed:
            acc.v("synthetic_kind", "/kind", "synthetic sources are controls and canaries only")

    # mutation shape
    if mut is not None:
        changes = mut.get("changes")
        if mut.get("splice_kind") != "canary" and isinstance(changes, list) and len(changes) != 1:
            acc.v("changes_count", "/mutation/changes", "exactly one changes[] range unless the row is a canary")
        adv = mut.get("advance")
        if adv is None:
            acc.v("advance_missing", "/mutation/advance", "every mutation carries an advance object")
        elif isinstance(adv, list) and mut.get("splice_kind") != "tj_run":
            acc.v("advance_array_not_tj_run", "/mutation/advance", "an advance array is only allowed for tj_run")
        _check_advance_fields(case, acc, mut)
        _check_text_state_links(case, acc)
        if mut.get("saved_with") != "saveIncr" and _g(case, "phases", "save_reopen", "result") == "pass":
            acc.v("saved_with_save_reopen", "/mutation/saved_with", "save_reopen can only pass on a saveIncr file")
        replacement = cc.get("replacement")
        glyphs = case.get("glyph_identity")
        if isinstance(glyphs, list) and isinstance(replacement, str):
            if len(glyphs) != len(replacement) or sorted(g.get("index", -1) for g in glyphs if isinstance(g, dict)) != list(range(len(replacement))):
                acc.v("glyph_identity_length", "/glyph_identity", "glyph_identity must list every replacement character once")
            else:
                for i, g in enumerate(glyphs):
                    if isinstance(g, dict) and isinstance(g.get("index"), int) and g.get("is_space") != replacement[g["index"]].isspace():
                        acc.v("glyph_identity_is_space", f"/glyph_identity/{i}/is_space", "is_space must equal replacement[index].isspace()")
    else:
        if case.get("glyph_identity") != []:
            acc.v("glyph_identity_not_empty", "/glyph_identity", "a row without mutation lists no glyphs")
        _check_mutation_null(case, acc)
        _check_trm(case, acc)

    probe = _dict(case.get("probe"))
    for name in ("max_tier_1", "max_tier_0"):
        res_ = probe.get(name)
        if isinstance(res_, dict) and (res_.get("result") == "prepared") != (res_.get("prepared") is not None):
            acc.v("probe_prepared_mismatch", f"/probe/{name}/result", "result is prepared exactly when a prepared object is recorded")

    # structelem vocabulary, on both text states
    for which in ("before", "after"):
        for i, wrapper in enumerate(_g(case, "text_state", which, "wrapper_stack", default=[]) or []):
            keys: Any = wrapper.get("structelem_keys") if isinstance(wrapper, dict) else None
            if keys is not None:
                order = [STRUCTELEM_VOCAB.index(k) for k in keys if k in STRUCTELEM_VOCAB]
                if len(order) != len(keys) or order != sorted(set(order)):
                    acc.v(
                        "structelem_keys_vocabulary",
                        f"/text_state/{which}/wrapper_stack/{i}/structelem_keys",
                        "structelem_keys is a subset of ActualText, Alt, E, Lang in that order",
                    )

    _note_unverifiable(case, acc, mut)
    return acc.res


def _check_advance_fields(case: dict, acc: _Acc, mut: dict) -> None:
    """K-null rule, tolerance, function and source rules (per advance object)."""
    font_kind = _g(case, "corpus_case", "font_kind")
    path = mut.get("path")
    changes = [c for c in (mut.get("changes") or []) if isinstance(c, dict)]
    canary = mut.get("splice_kind") == "canary"
    has_number = any(_k_numbers(b, canary) for b in (_operand_bytes(c) for c in changes) if b is not None)
    for base, adv in _advances(case):
        k_names = ("K_written", "K_sum", "K_disp_engine", "K_disp_hand")
        tol = _tolerance(adv)
        if tol is not None and not _close(adv.get("advance_tolerance"), tol, abs(tol) * 1e-12):
            acc.v("advance_tolerance_mismatch", f"{base}/advance_tolerance", "tolerance differs from the brief 5.1 formula")
        want_fn = {"type0": "IdentityHCidCapability.advance_points", "simple": "plan._advance/FontCapability.string_width"}.get(font_kind)
        if adv.get("advance_function") != want_fn:
            acc.v("advance_function_mismatch", f"{base}/advance_function", "advance_function is fixed by font_kind")
        allowed_src = {"type0": ("W", "DW"), "simple": ("Widths", "face")}.get(font_kind, ())
        if adv.get("advance_source") not in allowed_src:
            acc.v("advance_source_font_kind", f"{base}/advance_source", "advance_source is restricted by font_kind")
        old, new = adv.get("adv_old_text_space"), adv.get("adv_new_text_space")
        if path == "product_commit":
            tier = _g(case, "probe", "commit", "tier")
            if _g(case, "probe", "commit", "attempted") is not True or tier not in (0, 1):
                acc.v("product_commit_tier", "/probe/commit", "a product_commit row needs an attempted commit with a tier")
            elif tier == 1 and adv.get("K_written") is None:
                acc.v("k_null_rule", f"{base}/K_written", "a Tier 1 product commit always writes a K token")
            elif tier == 0:
                for name in k_names:
                    if adv.get(name) is not None:
                        acc.v("k_null_rule", f"{base}/{name}", "Tier 0 never writes a number token, whatever the delta")
                        break
                if tol is not None and _is_num(old) and _is_num(new) and abs(new - old) > tol:
                    acc.v("product_advance_mismatch", f"{base}/adv_new_text_space", "Tier 0 tolerates |adv_new - adv_old| <= advance_tolerance")
            prep = _g(case, "probe", f"max_tier_{tier}", "prepared") if tier in (0, 1) else None
            if isinstance(prep, dict) and tol is not None:
                # Only a Tier 1 PreparedEdit carries advances (a Tier 0 one leaves both at 0.0); rederive re-measures Tier 0's.
                for name, key in (("adv_old_text_space", "source_advance"), ("adv_new_text_space", "replacement_advance")) if tier == 1 else ():
                    if not _close(adv.get(name), prep.get(key), tol):
                        acc.v("product_advance_mismatch", f"{base}/{name}", f"must equal the product's prepared {key}")
                if changes:
                    if changes[0].get("start") != prep.get("replacement_start") or changes[0].get("end_old") != prep.get("replacement_end"):
                        acc.v("product_change_mismatch", "/mutation/changes/0", "the change range must copy prepared.replacement")
            elif tier in (0, 1) and prep is None:
                acc.v("product_advance_mismatch", f"/probe/max_tier_{tier}/prepared", "a product commit needs the prepared edit it copied")
        elif path in ("experiment", "canary") and tol is not None and _is_num(old) and _is_num(new):
            if abs(new - old) > tol and adv.get("K_written") is None:
                acc.v("k_null_rule", f"{base}/K_written", "an advance-changing splice must write a K token")
        if not has_number:
            for name in k_names:
                if adv.get(name) is not None:
                    acc.v("k_present_without_number", f"{base}/{name}", "no NUMBER token in the new operand, so K must be null")
                    break
        else:
            # brief 5.2: a K token is tied to the displacement it compensates, so no component may be left out
            for name in k_names:
                if adv.get(name) is None:
                    acc.v("k_null_rule", f"{base}/{name}", "a NUMBER token in the new operand needs K_written, K_sum, K_disp_engine and K_disp_hand")
        # text-state links
        tf = _g(case, "text_state", "before")
        if isinstance(tf, dict):
            if not _close(adv.get("Tfs"), _g(tf, "Tf", "size"), 1e-9):
                acc.v("tfs_mismatch", f"{base}/Tfs", "Tfs must equal the Tf operand")
            if not (_is_num(tf.get("Tz")) and _close(adv.get("Th"), tf["Tz"] / 100.0, 1e-9)):
                acc.v("th_mismatch", f"{base}/Th", "Th must equal Tz/100")
            for name in ("Tc", "Tw"):
                if not _close(adv.get(name), tf.get(name), 1e-9):
                    acc.v("tc_tw_mismatch", f"{base}/{name}", f"{name} must equal the recorded text state")


def _check_trm(case: dict, acc: _Acc) -> None:
    ts = _g(case, "text_state", "before")
    trm = _g(case, "target", "trm_scale")
    if not isinstance(ts, dict):
        return
    tm, ctm = ts.get("Tm"), ts.get("CTM")
    if isinstance(tm, list) and isinstance(ctm, list) and len(tm) == 6 and len(ctm) == 6 and all(_is_num(x) for x in tm + ctm):
        l0 = tm[0] * ctm[0] + tm[1] * ctm[2]
        l1 = tm[0] * ctm[1] + tm[1] * ctm[3]
        if not _close(trm, math.hypot(l0, l1), 1e-6):
            acc.v("trm_scale_mismatch", "/target/trm_scale", "trm_scale is the baseline-row norm hypot(linear[0], linear[1])")


def _check_text_state_links(case: dict, acc: _Acc) -> None:
    _check_trm(case, acc)


def _check_mutation_null(case: dict, acc: _Acc) -> None:
    for name in PHASE_NAMES:
        if name == "probe":
            continue
        phase = _g(case, "phases", name, default={})
        if phase.get("result") != "not_run":
            acc.v("mutation_null_phase_not_run", f"/phases/{name}/result", "without a mutation this phase is not_run")
        elif phase.get("detail") != "no mutation":
            acc.v("mutation_null_phase_not_run", f"/phases/{name}/detail", 'the detail of a not_run phase is "no mutation"')
    must_be_null = [
        "/text_state/after",
        "/text_state/target_equal",
        "/text_state/nontarget_shows_equal",
        "/text_state/show_count_after",
        "/text_state/operator_count_after",
        "/target/after_bbox_visual",
        "/target/after_bbox_raw",
        "/target/verify_bbox_visual",
        "/neighbours/target_glyphs_after",
        "/neighbours/target_origin_delta_pt",
        "/neighbours/untouched_max_origin_delta_pt",
        "/neighbours/inshow_successor_max_origin_delta_pt",
        "/render/halo_area_pt2",
        "/render/live_vs_reopened_changed_px",
        "/render/mupdf/target_changed_px",
        "/render/mupdf/nontarget_changed_px",
        "/render/mupdf/control_rerender_changed_px",
        "/render/poppler/target_changed_px",
        "/render/poppler/nontarget_changed_px",
        "/render/poppler/control_rerender_changed_px",
        "/extraction/after_text_at_target",
        "/extraction/equals_replacement",
        "/extraction/old_text_remains_at_target",
        "/extraction/nontarget_text_changes",
        "/save_reopen/page_count_equal",
        "/save_reopen/new_objects_subset_xref",
        "/save_reopen/reopened_text_at_target_equals_replacement",
        "/save_reopen/text_state_equal",
        "/save_reopen/glyph_identity_equal",
    ]
    growth = case.get("growth_zone")
    if isinstance(growth, dict):
        for key, value in growth.items():
            if key == "files":
                if value:
                    must_be_null.append("/growth_zone/files")
            elif value is not None and value is not False:
                must_be_null.append(f"/growth_zone/{key}")
        if growth.get("applicable") is not False:
            acc.v("growth_applicable_mismatch", "/growth_zone/applicable", "a row without mutation has no growth zone")
    for pointer in dict.fromkeys(must_be_null):
        keys = pointer.split("/")[1:]
        value = _g(case, *keys)
        if value is not None and not (pointer == "/growth_zone/files" and value == []):
            acc.v("mutation_null_fields_not_null", pointer, "a row without mutation carries null here")


def _note_unverifiable(case: dict, acc: _Acc, mut: dict | None) -> None:
    acc.u("user_unit", "/target/user_unit", "needs the original file's page frame (rederive)")
    wrappers = [w for s in ("before", "after") for w in (_g(case, "text_state", s, "wrapper_stack", default=[]) or [])]
    if wrappers:
        acc.u("props_keys", "/text_state/before/wrapper_stack", "props and StructElem values need the original file (rederive)")
    if mut is None:
        return
    acc.u("token_aligned", "/mutation/changes", "token alignment needs the original stream (rederive)")
    acc.u("operator_count_before", "/text_state/operator_count_before", "needs the original stream (rederive)")
    acc.u("old_stream_sha256", "/mutation/changes", "old stream digest needs the original file (rederive)")
    acc.u("after_bbox_frame", "/target/after_bbox_raw", "raw boxes times the quarter turn against the visual boxes need the page frame (rederive)")
    if _g(case, "growth_zone", "applicable") is True:
        acc.u("region_dict", "/growth_zone/region_dict", "dict-space strip needs the page frame (rederive)")
        acc.u("background_bbox", "/growth_zone/background_bbox_visual", "font-metric quad needs the original show (rederive)")
        acc.u("probe_regions_px_96dpi", "/growth_zone/probe_regions_px_96dpi", "pixel regions need the 96 dpi pixmap size (rederive)")


# --------------------------------------------------------------------------
# check_operand_grammar
# --------------------------------------------------------------------------
_FORBIDDEN_KINDS = {
    TokenKind.COMMENT,
    TokenKind.NAME,
    TokenKind.DICT_OPEN,
    TokenKind.DICT_CLOSE,
    TokenKind.MALFORMED,
    TokenKind.INLINE_IMAGE_DATA,
    TokenKind.BRACE_OPEN,
    TokenKind.BRACE_CLOSE,
    TokenKind.INERT_RUN,
}


_CANARY_FORBIDDEN = _FORBIDDEN_KINDS - {TokenKind.NAME}
# a resource name (F1, TT2, C2_0, Im3) is at most two letters and digits: too short to carry text
_RESOURCE_NAME = re.compile(r"[A-Za-z]{1,2}[0-9]+(?:_[0-9]+)?")
PDF_OPERATORS = frozenset(
    "b B b* B* BDC BI BMC BT BX c cm CS cs d d0 d1 Do DP EI EMC ET EX f F f* G g gs h i ID j J K k l m M MP n q Q re RG rg ri s S "
    "SC sc SCN scn sh T* Tc Td TD Tf Tj TJ TL Tm Tr Ts Tw Tz v w W W* y".split()
) | {"'", '"'}


def _shape(data: bytes) -> tuple[str, list] | None:
    """A compact grammar string (S string, N number, [ ], T TJ operator) and the tokens."""
    toks = [t for t in _lex(data) if t.kind is not TokenKind.WHITESPACE]
    letters = []
    for t in toks:
        if t.kind in _FORBIDDEN_KINDS:
            return None
        if t.kind in (TokenKind.STRING, TokenKind.HEXSTRING):
            letters.append("S")
        elif t.kind is TokenKind.NUMBER:
            letters.append("N")
        elif t.kind is TokenKind.ARRAY_OPEN:
            letters.append("[")
        elif t.kind is TokenKind.ARRAY_CLOSE:
            letters.append("]")
        elif t.kind is TokenKind.OPERATOR and data[t.start : t.end] == b"TJ":
            letters.append("T")
        else:
            return None
    return "".join(letters), toks


_SPLIT_BODIES = ("SS", "SSS", "SNS", "SSNS", "SSN")
_GRAMMAR: dict[str, tuple[str, ...]] = {
    "string_token": ("S",),
    "tj_item": ("S",),
    "string_fragment": ("S",),
    "whole_operator": ("[SN]T",),
    "tj_run": ("S", "SN"),
}


def _allowed_shapes(splice_kind: str, operator: object) -> tuple[str, ...]:
    if splice_kind in _GRAMMAR:
        return _GRAMMAR[splice_kind]
    if splice_kind == "fragment_split":
        if operator == "TJ":
            return _SPLIT_BODIES
        return tuple(f"[{b}]T" for b in _SPLIT_BODIES)
    return ()


def check_operand_grammar(case: dict) -> CheckResult:
    """Brief 5.2 structure table: token grammar, glyph binding, F3 slices, K tokens."""
    acc = _Acc(case)
    mut = case.get("mutation")
    if not isinstance(mut, dict):
        return acc.res
    kind = mut.get("splice_kind")
    operator = _g(case, "target", "operator")
    unit = 2 if _g(case, "corpus_case", "font_kind") == "type0" else 1
    glyph_bytes = _glyph_code_bytes(case)
    replacement = _g(case, "corpus_case", "replacement", default="")
    changes = [c for c in (mut.get("changes") or []) if isinstance(c, dict)]
    advances = _advances(case)
    k_written = advances[0][1].get("K_written") if advances else None
    k_ptr = f"{advances[0][0]}/K_written" if advances else "/mutation/advance/K_written"
    for idx, ch in enumerate(changes):
        ptr = f"/mutation/changes/{idx}/new_operand_bytes_hex"
        data = _operand_bytes(ch)
        if data is None:
            acc.v("operand_grammar", ptr, "new_operand_bytes_hex is not an even-length hex string")
            continue
        for number in _k_numbers(data, kind == "canary"):
            if not _is_num(k_written) or abs(number - k_written) > NUM_TOL:
                acc.v("k_token_mismatch", k_ptr, "K_written must equal every NUMBER token written")
                break
        if kind == "canary":
            for tok in _lex(data):
                if tok.kind in _CANARY_FORBIDDEN or (
                    tok.kind is TokenKind.OPERATOR and data[tok.start : tok.end].decode("latin-1") not in PDF_OPERATORS
                ):
                    acc.v("operand_grammar", ptr, "a canary operand holds strings, numbers, names and PDF operators only (brief 2.2)")
                    break
            if unit == 2 and glyph_bytes is not None:
                payload = _string_payloads(data) or []
                known = {glyph_bytes[i : i + 2] for i in range(0, len(glyph_bytes), 2)}
                if any(p[i : i + 2] not in known for p in payload for i in range(0, len(p), 2)):
                    acc.u("type0_cid_unbound", ptr, "canary donor CIDs need the original show (rederive)")
            continue
        shape = _shape(data)
        allowed = _allowed_shapes(str(kind), operator)
        if shape is None or not _shape_matches(shape[0], allowed):
            acc.v("operand_grammar", ptr, f"token sequence is not the {_vocab(kind)} grammar of brief 5.2")
            continue
        payloads = _string_payloads(data)
        if payloads is None or glyph_bytes is None:
            acc.v("operand_binding", ptr, "string tokens do not decode or glyph_identity code bytes are unreadable")
            continue
        old = _operand_bytes(ch, "old_operand_bytes_hex")
        if kind in ("string_fragment", "fragment_split"):
            _check_fragment(case, acc, idx, str(kind), payloads, shape[0], glyph_bytes, old, unit)
        else:
            joined = b"".join(payloads)
            if joined != glyph_bytes or len(joined) != len(replacement) * unit:
                acc.v("operand_binding", ptr, "string bytes must equal the glyph_identity code bytes, one unit per replacement character")
        _check_k_sum(case, acc, idx, str(kind), old)
    return acc.res


def _shape_matches(letters: str, allowed: tuple[str, ...]) -> bool:
    return letters in allowed


def _check_fragment(case, acc, idx, kind, payloads, letters, mid, old, unit) -> None:
    ptr = f"/mutation/changes/{idx}/new_operand_bytes_hex"
    rng = _g(case, "target", "byte_range_in_item")
    if not (isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) for x in rng)):
        acc.v("fragment_range_missing", "/target/byte_range_in_item", "F3 rows need byte_range_in_item")
        return
    b0, b1 = rng
    if unit == 2 and (b0 % 2 or b1 % 2):
        acc.v("fragment_odd_offset", "/target/byte_range_in_item", "Type0 offsets fall on 2-byte boundaries")
    old_item = None
    if old is not None:
        olds = _string_payloads(old)
        old_item = olds[0] if olds else None
        if old_item is None or not 0 <= b0 < b1 <= len(old_item):
            acc.v("fragment_range_missing", "/target/byte_range_in_item", "byte_range_in_item does not fit the old item")
            return
    if kind == "string_fragment":
        item = payloads[0]
        prefix, middle, suffix = item[:b0], item[b0 : b0 + len(mid)], item[b0 + len(mid) :]
        if len(item) < b0 + len(mid) or middle != mid:
            acc.v("operand_binding", ptr, "the replaced slice must equal the glyph_identity code bytes")
            return
        if not prefix and not suffix:
            acc.v("fragment_not_f3", ptr, "prefix and suffix are both empty, so this is a whole-item edit")
    else:
        strings = list(payloads)
        if len(strings) == 3:
            prefix, middle, suffix = strings
        elif b0 > 0:
            (prefix, middle), suffix = strings, b""  # two strings: the first is the prefix exactly when the slice does not start the item
        else:
            prefix, (middle, suffix) = b"", strings
        if middle != mid:
            acc.v("operand_binding", ptr, "the middle string must equal the glyph_identity code bytes")
            return
        if old_item is not None and b0 == 0 and b1 == len(old_item):
            acc.v("fragment_not_f3", ptr, "the whole item is replaced, so this is not a fragment edit")
        if len(prefix) != b0:
            acc.v("fragment_prefix_mismatch", ptr, "prefix length differs from byte_range_in_item")
    if old_item is not None:
        if prefix != old_item[:b0]:
            acc.v("fragment_prefix_mismatch", ptr, "prefix bytes differ from the old operand")
        if suffix != old_item[b1:]:
            acc.v("fragment_suffix_mismatch", ptr, "suffix bytes differ from the old operand")
    else:
        acc.u("fragment_prefix_mismatch", ptr, "prefix and suffix need the original operand (rederive)")


def _check_k_sum(case, acc, idx, kind, old) -> None:
    if old is None:
        return
    advances = _advances(case)
    if not advances:
        return
    base, adv = advances[0]
    numbers = _numbers(old)
    if kind == "tj_run":
        want = sum(numbers)
        if adv.get("K_sum") is not None and not _close(adv["K_sum"], want, NUM_TOL):
            acc.v("k_sum_mismatch", f"{base}/K_sum", "K_sum must equal the old operand's internal kerns")
        dropped = adv.get("internal_kerns_dropped")
        if not (isinstance(dropped, list) and len(dropped) == len(numbers) and all(_close(a, b, NUM_TOL) for a, b in zip(dropped, numbers, strict=True))):
            acc.v("k_sum_mismatch", f"{base}/internal_kerns_dropped", "internal_kerns_dropped must list the old internal kerns")
    elif adv.get("K_sum") is not None and abs(adv["K_sum"]) > NUM_TOL:
        acc.v("k_sum_mismatch", f"{base}/K_sum", "only a tj_run drops internal kerns")


# --------------------------------------------------------------------------
# check_advance
# --------------------------------------------------------------------------
def check_advance(case: dict) -> CheckResult:
    """Arithmetic on the recorded advance numbers (values are rederive's job)."""
    acc = _Acc(case)
    glyphs = _list(case.get("glyph_identity"))
    for base, adv in _advances(case):
        old, new, tfs = adv.get("adv_old_text_space"), adv.get("adv_new_text_space"), adv.get("Tfs")
        if _is_num(old) and _is_num(new):
            if not _close(adv.get("displacement"), old - new, 1e-9):
                acc.v("displacement_mismatch", f"{base}/displacement", "displacement must equal adv_old - adv_new")
            want = _expected_growth(adv, _g(case, "target", "trm_scale"), _g(case, "target", "user_unit"))
            if want is not None and not _close(adv.get("growth_pt"), want, 1e-6):
                acc.v("growth_pt_mismatch", f"{base}/growth_pt", "growth_pt = max(0, d_adv) * Th * trm_scale * user_unit")
        kw, ks, ke, kh = (adv.get(n) for n in ("K_written", "K_sum", "K_disp_engine", "K_disp_hand"))
        if _is_num(kw) and _is_num(ks) and _is_num(ke):
            if not _close(adv.get("abs_diff_written_vs_sum_engine"), abs(kw - (ks + ke)), 1e-9):
                acc.v("k_abs_diff_mismatch", f"{base}/abs_diff_written_vs_sum_engine", "recorded |K_written - (K_sum + K_disp_engine)| differs")
            if abs(kw - (ks + ke)) > NUM_TOL:
                acc.fail("structure", "k_arithmetic")
        if _is_num(ke) and _is_num(kh):
            if not _close(adv.get("abs_diff_engine_hand"), abs(ke - kh), 1e-9):
                acc.v("k_abs_diff_mismatch", f"{base}/abs_diff_engine_hand", "recorded |K_disp_engine - K_disp_hand| differs")
            if abs(ke - kh) > NUM_TOL:
                acc.fail("structure", "k_engine_hand")
        if _is_num(kh) and _is_num(old) and _is_num(new) and _is_num(tfs) and tfs != 0:
            if abs(kh - 1000.0 * (new - old) / tfs) > NUM_TOL:
                acc.fail("structure", "k_hand_formula")
        if adv.get("char_count_new") != len(glyphs) or adv.get("space_count") != sum(
            1 for g in glyphs if isinstance(g, dict) and g.get("is_space") is True
        ):
            acc.v("char_count_mismatch", f"{base}/char_count_new", "char counts must equal glyph_identity")
        elif isinstance(_g(case, "corpus_case", "replacement"), str) and adv.get("char_count_new") != len(case["corpus_case"]["replacement"]):
            acc.v("char_count_mismatch", f"{base}/char_count_new", "char_count_new must equal the replacement length")
    return acc.res


# --------------------------------------------------------------------------
# check_growth_zone
# --------------------------------------------------------------------------
def _dominant_extent(target, other) -> tuple[str, float]:
    """Port of the dominant-edge read in ``verify._growth_zone_rect``."""
    extents = (
        ("right", other[2] - target[2]),
        ("left", target[0] - other[0]),
        ("down", other[3] - target[3]),
        ("up", target[1] - other[1]),
    )
    return max(extents, key=lambda pair: pair[1])


def _growth_strip(target, other) -> tuple[float, float, float, float] | None:
    """Port of ``verify._growth_zone_rect`` (None when nothing grows)."""
    direction, amount = _dominant_extent(target, other)
    if amount <= 0.0:
        return None
    cross_y = (min(target[1], other[1]), max(target[3], other[3]))
    cross_x = (min(target[0], other[0]), max(target[2], other[2]))
    if direction == "right":
        x0, y0, x1, y1 = target[2], cross_y[0], other[2], cross_y[1]
    elif direction == "left":
        x0, y0, x1, y1 = other[0], cross_y[0], target[0], cross_y[1]
    elif direction == "down":
        x0, y0, x1, y1 = cross_x[0], target[3], cross_x[1], other[3]
    else:
        x0, y0, x1, y1 = cross_x[0], other[1], cross_x[1], target[1]
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _extent(target, other) -> float:
    """Dominant-edge extent; a ``None`` strip counts as 0."""
    return max(0.0, _dominant_extent(target, other)[1])


def _extend(box: list[float], direction: str, amount: float) -> list[float]:
    x0, y0, x1, y1 = box
    return {
        "right": [x0, y0, x1 + amount, y1],
        "left": [x0 - amount, y0, x1, y1],
        "down": [x0, y0, x1, y1 + amount],
        "up": [x0, y0 - amount, x1, y1],
    }.get(direction, list(box))


_GROWTH_NULLABLE = (
    "direction",
    "region_visual",
    "region_dict",
    "background_bbox_visual",
    "background_rgb",
    "probe_regions_px_96dpi",
    "probe_regions_failed",
    "raster_proof",
    "gate_detail",
    "before_glyph_bboxes_intersecting",
    "before_drawings_intersecting_bbox",
    "before_drawings_not_provably_clear",
    "stroke_proof",
    "before_images_intersecting",
    "sh_operator_present",
)


def check_growth_zone(case: dict) -> CheckResult:
    """Brief 5.1 applicability and 5.2 growth_zone, recomputed from the record."""
    acc = _Acc(case)
    mut, gz = case.get("mutation"), case.get("growth_zone")
    if not isinstance(mut, dict) or not isinstance(gz, dict):
        return acc.res
    advs = _advances(case)
    if len(advs) != 1:
        acc.undecided("growth_zone", "advance_array")
        acc.u("growth_applicable_mismatch", "/mutation/advance", "advance arrays are not checked here (rederive)")
        return acc.res
    base, adv = advs[0]
    tgt = _dict(case.get("target"))
    T, A, V = tgt.get("target_bbox_visual"), tgt.get("after_bbox_visual"), tgt.get("verify_bbox_visual")
    want = _applicable_expected(case, adv)
    applicable = gz.get("applicable")
    if want is not None and applicable != want:
        acc.v("growth_applicable_mismatch", "/growth_zone/applicable", "applicability differs from the brief 5.1 rule")
    halo = _g(case, "render", "halo_area_pt2")
    if _bbox_ok(T) and _bbox_ok(A) and halo is not None:
        u = _bbox_union([T, A])
        expect = (u[2] - u[0] + 6.0) * (u[3] - u[1] + 6.0)  # type: ignore[index]
        if not _close(halo, expect, BBOX_TOL):
            acc.v("halo_area_mismatch", "/render/halo_area_pt2", "halo area must be (w+6)*(h+6) of the union of both target boxes")
    if not (_bbox_ok(T) and _bbox_ok(A)):
        acc.undecided("growth_zone", "target_boxes_missing")
        return acc.res
    if not applicable:
        for key in _GROWTH_NULLABLE:
            if gz.get(key) is not None:
                acc.v("growth_fields_not_null", f"/growth_zone/{key}", "a non-growth row carries null here")
        if _extent(T, A) > OWN_CHAR_TOL_PT:
            acc.v("growth_after_exceeds_target", "/target/after_bbox_visual", "declared no growth, but the after box is wider than the target box")
        return acc.res
    # applicable
    direction, ext_after = _dominant_extent(T, A)
    if ext_after > 0.0 and gz.get("direction") != direction:
        acc.v("direction_mismatch", "/growth_zone/direction", "direction must be the dominant edge of after versus target")
    growth_pt = _expected_growth(adv, tgt.get("trm_scale"), tgt.get("user_unit"))
    # Basis (11): an honest after box grows by growth_pt to float noise.  An after box that does not grow lets the
    # self-reported direction (and so the proven strip) sit on the wrong side of the real ink.
    if ext_after <= 0.0 or (growth_pt is not None and ext_after < growth_pt - OWN_CHAR_TOL_PT):
        acc.v("growth_after_not_grown", "/target/after_bbox_visual", "applicable growth: the after box must grow by growth_pt on the direction side")
        acc.fail("growth_zone", "after_not_grown")
    use_dir: Any = gz.get("direction") if gz.get("direction") in ("right", "left", "down", "up") else direction
    if growth_pt is not None:
        if not (_bbox_ok(V) and _bbox_close(V, _extend(T, use_dir, growth_pt))):
            acc.v("verify_bbox_mismatch", "/target/verify_bbox_visual", "verify box must be the target extended by growth_pt on direction")
    prepared = None
    if mut.get("path") == "product_commit":
        tier = _g(case, "probe", "commit", "tier")
        prepared = _g(case, "probe", f"max_tier_{tier}", "prepared") if tier in (0, 1) else None
    if isinstance(prepared, dict):
        if not _bbox_close(V, prepared.get("verify_bbox_page")):
            acc.v("prepared_bbox_mismatch", "/target/verify_bbox_visual", "product rows copy prepared.verify_bbox_page")
        if not _bbox_close(gz.get("background_bbox_visual"), prepared.get("background_bbox_page")):
            acc.v("prepared_bbox_mismatch", "/growth_zone/background_bbox_visual", "product rows copy prepared.background_bbox_page")
    if _bbox_ok(V):
        strip = _growth_strip(T, V)
        got = gz.get("region_visual")
        if strip is None or not _bbox_close(got, list(strip)):
            acc.v("region_visual_mismatch", "/growth_zone/region_visual", "region_visual must be the growth strip between target and verify")
        if ext_after > _extent(T, V) + OWN_CHAR_TOL_PT:
            acc.v("growth_after_exceeds_verify", "/target/after_bbox_visual", "the after ink runs past the proven-blank verify box")
            acc.fail("growth_zone", "after_exceeds_verify")
    counters: dict[str, Any] = {k: gz.get(k) for k in (
        "before_glyph_bboxes_intersecting", "before_drawings_intersecting_bbox", "before_drawings_not_provably_clear",
        "before_images_intersecting", "probe_regions_failed", "raster_proof", "stroke_proof", "sh_operator_present",
    )}
    if any(v is None for v in counters.values()):
        acc.undecided("growth_zone", "gate_values_missing")
        return acc.res
    d, npc, sp = counters["before_drawings_intersecting_bbox"], counters["before_drawings_not_provably_clear"], counters["stroke_proof"]
    if isinstance(d, int) and isinstance(npc, int):
        consistent = (d == 0 and sp == "not_needed" and npc == 0) or (d > 0 and ((sp == "clear" and npc == 0) or (sp == "failed" and npc >= 1)))
        if not consistent:
            acc.v("stroke_proof_inconsistent", "/growth_zone/stroke_proof", "stroke_proof must follow the drawing counters")
    if counters["before_glyph_bboxes_intersecting"] > 0:
        acc.fail("growth_zone", "glyph_in_strip")
    if isinstance(npc, int) and npc > 0:
        acc.fail("growth_zone", "drawings_not_provably_clear")
    if sp == "failed":
        acc.fail("growth_zone", "stroke_proof_failed")
    if counters["before_images_intersecting"] > 0:
        acc.fail("growth_zone", "image_in_strip")
    if counters["probe_regions_failed"] != 0:
        acc.fail("growth_zone", "probe_regions_failed")
    if counters["raster_proof"] != "pass":
        acc.fail("growth_zone", "raster_proof")
    if counters["sh_operator_present"] is True:
        acc.fail("growth_zone", "shading_operator")
    return acc.res


# --------------------------------------------------------------------------
# check_pairing
# --------------------------------------------------------------------------
def _field_type_ok(value: object, token: str) -> bool:
    if token == "null":
        return value is None
    if token == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if token == "num":
        return _is_num(value)
    if token == "bool":
        return isinstance(value, bool)
    if token == "role":
        return value in NEIGHBOUR_ROLES
    if token == "num2":
        return isinstance(value, list) and len(value) == 2 and all(_is_num(v) for v in value)
    if token == "num4":
        return _bbox_ok(value)
    return False


def _record_problems(rec: object) -> list[tuple[str, str, str]]:
    if not isinstance(rec, dict):
        return [("schema_type", "", "neighbour record is not an object")]
    out = []
    for key in rec:
        if key not in _NEIGHBOUR_KEYS:
            out.append(("neighbours_record_key", f"/{_esc(key)}", "key outside the neighbours.json allowlist (no text fields)"))
    for key, tokens in _NEIGHBOUR_KEYS.items():
        if key not in rec:
            out.append(("schema_required", f"/{key}", "required key is missing"))
        elif not any(_field_type_ok(rec[key], t) for t in tokens):
            out.append(("schema_type", f"/{key}", f"expected {'|'.join(tokens)}"))
    return out


def _eq_summary(a: object, b: object) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if _is_num(a) and _is_num(b):
        return abs(a - b) <= 1e-9  # type: ignore[operator]
    return a == b


def check_pairing(case: dict, records: list[dict] | None) -> CheckResult:
    """``texttrace_order_origin_match/v1``: pairing, summary recompute and phase fails."""
    acc = _Acc(case)
    nfile = f"cases/{acc.case_id}/neighbours.json" if acc.case_id else "neighbours.json"

    def rv(code: str, pointer: str, detail: str) -> None:
        acc.res.violations.append(Violation(code, nfile, pointer, detail, acc.case_id))

    recs = records if isinstance(records, list) else []
    bad = False
    for i, rec in enumerate(recs):
        for code, ptr, detail in _record_problems(rec):
            rv(code, f"/{i}{ptr}", detail)
            bad = True
    mut, nb = case.get("mutation"), case.get("neighbours")
    if mut is None and not bad:
        # brief 5.1: a row without mutation carries role=untouched records or an empty array, and nothing can move
        for i, rec in enumerate(recs):
            if rec["role"] != "untouched" or rec["trace_index_before"] != rec["trace_index_after"]:
                rv("null_mutation_record", f"/{i}/role", "a row without mutation has only untouched, unmoved records")
    if not isinstance(mut, dict) or not isinstance(nb, dict):
        return acc.res
    if bad:
        acc.undecided("neighbours", "records_invalid")
        return acc.res
    if not recs:
        acc.undecided("neighbours", "no_records")
        return acc.res

    targets = [(i, r) for i, r in enumerate(recs) if r["role"] == "target"]
    others = [(i, r) for i, r in enumerate(recs) if r["role"] != "target"]
    # field rules
    for i, r in enumerate(recs):
        owns_ink = r["role"] == "target" and not r["is_space"] and r["trace_index_after"] is not None
        if r["ink_after_px_6x"] is not None and r["role"] != "target":
            rv("ink_after_field", f"/{i}/ink_after_px_6x", "ink_after_px_6x is only set on target records")
        elif r["ink_after_px_6x"] is not None and (r["is_space"] or r["trace_index_after"] is None):
            rv("ink_after_field", f"/{i}/ink_after_px_6x", "ink_after_px_6x is only set on non-space target glyphs that exist after the edit")
        if r["halo_shadowed"] and r["ink_checked"]:
            rv("halo_shadowed_checked", f"/{i}/ink_checked", "a halo-shadowed glyph is not ink-checked")
        if r["origin_before"] and r["origin_after"] and r["origin_delta_pt"] is not None:
            dist = math.hypot(r["origin_after"][0] - r["origin_before"][0], r["origin_after"][1] - r["origin_before"][1])
            if abs(dist - r["origin_delta_pt"]) > 1e-6:
                rv("neighbours_summary_mismatch", f"/{i}/origin_delta_pt", "origin_delta_pt differs from the recorded origins")
        if owns_ink and (r["ink_after_px_6x"] is None or r["ink_after_px_6x"] < 1):
            acc.fail("neighbours", "target_ink_not_landed")
    # pairing map
    tb = sorted(r["trace_index_before"] for _, r in targets if r["trace_index_before"] is not None)
    ta = sorted(r["trace_index_after"] for _, r in targets if r["trace_index_after"] is not None)
    n_old, n_new = len(tb), len(ta)
    start = (tb or ta or [None])[0]
    if start is not None and (tb != list(range(start, start + n_old)) or ta != list(range(start, start + n_new))):
        acc.v("pairing_map", "/neighbours/target_glyphs_before", "target glyph indices must form one contiguous run")
    shift = n_new - n_old
    unpaired = 0
    for i, r in others:
        b, a = r["trace_index_before"], r["trace_index_after"]
        if b is None or a is None:
            unpaired += 1
            continue
        if start is None or b < start:
            want_after = b
        elif b >= start + n_old:
            want_after = b + shift
        else:
            rv("pairing_map", f"/{i}/trace_index_before", "a non-target glyph sits inside the target run")
            continue
        if a != want_after:
            rv("pairing_map", f"/{i}/trace_index_after", "positional pairing broken (j<i -> j, j>=i+n_old -> j+delta)")
    for key in ("trace_index_before", "trace_index_after"):
        seen = [r[key] for r in recs if r[key] is not None]
        if len(seen) != len(set(seen)):
            acc.v("pairing_map", "/neighbours/glyphs_total", f"{key} repeats: each glyph is paired exactly once")
    len_before = sum(1 for r in recs if r["trace_index_before"] is not None)
    len_after = sum(1 for r in recs if r["trace_index_after"] is not None)
    if unpaired == 0:
        unpaired = abs(len_after - len_before - shift)
    # structure-derived delta
    delta = None
    kind = mut.get("splice_kind")
    unit = 2 if _g(case, "corpus_case", "font_kind") == "type0" else 1
    rng = _g(case, "target", "byte_range_in_item")
    glyphs = case.get("glyph_identity")
    advs = _advances(case)
    if kind in ("string_fragment", "fragment_split") and isinstance(rng, list) and len(rng) == 2 and isinstance(glyphs, list):
        delta = len(glyphs) - (rng[1] - rng[0]) // unit
    elif advs and isinstance(advs[0][1].get("char_count_new"), int) and isinstance(advs[0][1].get("char_count_old"), int):
        delta = advs[0][1]["char_count_new"] - advs[0][1]["char_count_old"]
    if delta is not None and shift != delta:
        acc.v("pairing_delta_mismatch", "/neighbours/target_glyphs_after", "n_new - n_old must equal the structure-derived code-unit delta")
    _check_target_run(case, acc, rv, targets, n_old, n_new)
    # summary recompute
    first = min((r for _, r in targets if r["trace_index_before"] is not None), key=lambda r: r["trace_index_before"], default=None)
    untouched = [r["origin_delta_pt"] for _, r in others if r["role"] == "untouched" and r["origin_delta_pt"] is not None]
    inshow = [r["origin_delta_pt"] for _, r in others if r["role"] == "inshow_successor" and r["origin_delta_pt"] is not None]
    recomputed = {
        "glyphs_total": sum(1 for _, r in others if r["trace_index_before"] is not None),
        "glyphs_checked": sum(1 for _, r in others if r["ink_checked"] or r["halo_shadowed"] or r["overlap"]),
        "unpaired_glyphs": unpaired,
        "target_glyphs_before": n_old,
        "target_glyphs_after": n_new,
        "target_origin_delta_pt": first["origin_delta_pt"] if first else None,
        "untouched_max_origin_delta_pt": max(untouched) if untouched else None,
        "inshow_successor_max_origin_delta_pt": max(inshow) if inshow else None,
        "gid_mismatches": sum(1 for _, r in others if r["gid_before"] != r["gid_after"]),
        "ink_mismatches": sum(1 for _, r in others if r["ink_checked"] and (r["ink_changed_px_6x"] or 0) > 0),
        "overlap_glyphs": sum(1 for _, r in others if r["overlap"] and not r["is_space"]),
        "halo_shadowed_glyphs": sum(1 for _, r in others if r["halo_shadowed"]),
    }
    for key, want in recomputed.items():
        if not _eq_summary(nb.get(key), want):
            acc.v("neighbours_summary_mismatch", f"/neighbours/{key}", f"{key} differs from the value recomputed from neighbours.json")
    after_boxes = [r["bbox_after"] for _, r in targets if r["bbox_after"] is not None]
    union = _bbox_union(after_boxes)
    raw_after = _g(case, "target", "after_bbox_raw")
    if (union is None) != (raw_after is None) or (union is not None and not _bbox_close(union, raw_after)):
        acc.v("after_bbox_raw_mismatch", "/target/after_bbox_raw", "after_bbox_raw must be the union of the target bbox_after boxes")
    raw_before = _bbox_union([r["bbox_before"] for _, r in targets if r["bbox_before"] is not None])
    vis_t, vis_a = _g(case, "target", "target_bbox_visual"), _g(case, "target", "after_bbox_visual")
    if raw_before is not None and _bbox_ok(raw_after) and _bbox_ok(vis_t) and _bbox_ok(vis_a):
        # a quarter turn permutes the four edges, so the dominant growth extent is the same in both spaces (x user_unit)
        uu = _g(case, "target", "user_unit")
        scale = uu if _is_num(uu) and 0 < uu < 1 else 1.0
        if _extent(vis_t, vis_a) <= OWN_CHAR_TOL_PT and _extent(raw_before, raw_after) * scale > OWN_CHAR_TOL_PT + BBOX_TOL:
            acc.v("after_bbox_frame_mismatch", "/target/after_bbox_raw", "the raw after box grows although the visual after box does not")
    if _bbox_ok(raw_after):
        for i, r in others:
            box = r["bbox_after"] or r["bbox_before"]
            if box is not None and r["overlap"] != _bbox_intersects(box, raw_after):
                rv("neighbours_overlap_flag", f"/{i}/overlap", "overlap must follow the geometry against after_bbox_raw")
    _check_halo_flags(rv, targets, others)
    # phase fails: reported numbers and recomputed numbers both count
    kind_c = case.get("kind")
    for source, label in ((nb, "reported"), (recomputed, "recomputed")):
        if (source.get("unpaired_glyphs") or 0) > 0:
            acc.fail("neighbours", f"{label}_unpaired")
        if source.get("untouched_max_origin_delta_pt") not in (None, 0, 0.0):
            acc.fail("neighbours", f"{label}_untouched_moved")
        if (source.get("inshow_successor_max_origin_delta_pt") or 0.0) > 1e-6:
            acc.fail("neighbours", f"{label}_inshow_moved")
        if source.get("target_origin_delta_pt") not in (None, 0, 0.0):
            acc.fail("neighbours", f"{label}_target_moved")
        if (source.get("gid_mismatches") or 0) > 0:
            acc.fail("neighbours", f"{label}_gid_mismatch")
        if (source.get("ink_mismatches") or 0) > 0:
            acc.fail("neighbours", f"{label}_ink_mismatch")
        if (source.get("overlap_glyphs") or 0) > 0 and kind_c in ("positive", "control", "canary"):
            acc.fail("neighbours", f"{label}_overlap")
        if source.get("glyphs_checked") != source.get("glyphs_total"):
            acc.fail("neighbours", f"{label}_unchecked_glyphs")
    return acc.res


HALO_PT = 3.0


def _check_halo_flags(rv, targets, others) -> None:
    """Brief 5.2 neighbours: halo_shadowed and ink_checked follow the geometry, the records do not get to choose.

    The ink zone of a glyph is its own box minus the old+new target union expanded by 3 pt, so a glyph is
    halo-shadowed exactly when its whole box sits inside that halo without touching the unexpanded union; every
    other non-space glyph is ink-checked unless it overlaps the new run.
    """
    boxes = [b for _, r in targets for b in (r["bbox_before"], r["bbox_after"]) if b is not None]
    union = _bbox_union(boxes)
    if union is None:
        return
    halo = [union[0] - HALO_PT, union[1] - HALO_PT, union[2] + HALO_PT, union[3] + HALO_PT]
    tol = BBOX_TOL
    for i, r in others:
        box = r["bbox_after"] or r["bbox_before"]
        if box is None:
            continue
        inside = box[0] >= halo[0] - tol and box[1] >= halo[1] - tol and box[2] <= halo[2] + tol and box[3] <= halo[3] + tol
        touches = _bbox_intersects(box, union)
        shadowed = inside and not touches
        if bool(r["halo_shadowed"]) != shadowed:
            rv("halo_shadowed_flag", f"/{i}/halo_shadowed", "halo_shadowed must follow the geometry (inside the +-3 pt halo, outside the unexpanded union)")
        if r["is_space"] or (touches and not r["overlap"]):
            continue  # a space has no ink; a glyph touching only the old box is left undecided
        if bool(r["ink_checked"]) != (not (shadowed or r["overlap"])):
            rv("ink_checked_flag", f"/{i}/ink_checked", "ink_checked is true exactly for a non-space glyph that is neither halo-shadowed nor overlapping")


def _check_target_run(case: dict, acc: _Acc, rv, targets, n_old: int, n_new: int) -> None:
    """The role=target records are the target run: their count and their flags come from the structure."""
    glyphs = case.get("glyph_identity")
    by_index = {g.get("index"): g for g in glyphs if isinstance(g, dict)} if isinstance(glyphs, list) else {}
    kind = _g(case, "mutation", "splice_kind")
    unit = 2 if _g(case, "corpus_case", "font_kind") == "type0" else 1
    rng = _g(case, "target", "byte_range_in_item")
    advs = _advances(case)
    want_old: int | None = None
    if kind in ("string_fragment", "fragment_split"):
        if isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) for x in rng):
            want_old = (rng[1] - rng[0]) // unit
    elif len(advs) == 1 and isinstance(advs[0][1].get("char_count_old"), int):
        want_old = advs[0][1]["char_count_old"]
    want_new = len(glyphs) if isinstance(glyphs, list) else None
    if want_old is not None and n_old != want_old:
        acc.v("target_run_size_mismatch", "/neighbours/target_glyphs_before", "the role=target records before the edit must number the replaced code units")
    if want_new is not None and n_new != want_new:
        acc.v("target_run_size_mismatch", "/neighbours/target_glyphs_after", "the role=target records after the edit must number the replacement glyphs")
    original = _g(case, "corpus_case", "original")
    for i, r in targets:
        idx = r["char_index_after"]
        if idx is not None and by_index:
            glyph = by_index.get(idx)
            if glyph is None:
                rv("target_run_size_mismatch", f"/{i}/char_index_after", "char_index_after must index glyph_identity")
            elif glyph.get("is_space") is not None and r["is_space"] != glyph.get("is_space"):
                rv("target_is_space_mismatch", f"/{i}/is_space", "a target record's is_space must equal glyph_identity[char_index_after].is_space")
        before = r["char_index_before"]
        if before is not None and isinstance(original, str) and len(original) == n_old and 0 <= before < len(original):
            if idx is None and r["is_space"] != original[before].isspace():
                rv("target_is_space_mismatch", f"/{i}/is_space", "a removed target glyph's is_space must equal the original character")


# --------------------------------------------------------------------------
# check_glyph_identity
# --------------------------------------------------------------------------
_SIMPLE_LEGS = ("glyph_name_agl", "cmap_31_reverse", "standard_14_table")
_SIMPLE_SELECTED = ("glyph_name", "cmap_31_reverse", "standard_14_table")


def check_glyph_identity(case: dict) -> CheckResult:
    acc = _Acc(case)
    glyphs = case.get("glyph_identity")
    if not isinstance(case.get("mutation"), dict) or not isinstance(glyphs, list):
        return acc.res
    simple = _g(case, "corpus_case", "font_kind") == "simple"
    for i, g in enumerate(glyphs):
        if not isinstance(g, dict) or g.get("is_space") is True:
            continue
        gid = g.get("gid_after")
        if not isinstance(gid, int) or gid == 0:
            acc.fail("glyph_identity", "gid_zero_or_missing")
        if g.get("has_outline") is not True:
            acc.fail("glyph_identity", "no_outline")
        cons = g.get("consistency")
        if isinstance(cons, dict):
            note = cons.get("gid") == gid
            if g.get("gid_equals_consistency") is not None and g.get("gid_equals_consistency") != note:
                acc.v("glyph_note_mismatch", f"/glyph_identity/{i}/gid_equals_consistency", "the self-note differs from the recomputed comparison")
            if not note:
                acc.fail("glyph_identity", "consistency_gid_differs")
            ok_sel = _SIMPLE_SELECTED if simple else ("cid_tounicode",)
            if cons.get("selected_by") not in ok_sel:
                acc.fail("glyph_identity", "selected_by_wrong_kind")
        else:
            acc.undecided("glyph_identity", "no_consistency_occurrence")
        leg = g.get("independent_leg")
        if not isinstance(leg, dict):
            acc.undecided("glyph_identity", "no_independent_leg")
            continue
        kind = leg.get("kind")
        if kind == "none" or kind not in (_SIMPLE_LEGS if simple else ("cid_tounicode",)):
            acc.undecided("glyph_identity", "no_independent_leg")
            continue
        if leg.get("equals_char") is not True:
            acc.fail("glyph_identity", "leg_char_differs")
        if not isinstance(leg.get("gid"), int) or leg.get("gid") == 0 or leg.get("gid") != gid:
            acc.fail("glyph_identity", "leg_gid_differs")
    return acc.res


# --------------------------------------------------------------------------
# phase recomputation and the status table
# --------------------------------------------------------------------------
def _combine(fails: list[str], undecided: list[str], recorded: object) -> PhaseCheck:
    if fails:
        return PhaseCheck("fail", tuple(dict.fromkeys(fails)))
    if undecided:
        return PhaseCheck("blocked" if recorded == "blocked" else "not_run", tuple(dict.fromkeys(undecided)))
    return PhaseCheck("pass")


def _probe_phase(case: dict) -> PhaseCheck:
    probe = case.get("probe")
    recorded = _g(case, "phases", "probe", "result")
    if not isinstance(probe, dict):
        return PhaseCheck("not_run", ("probe_missing",))
    fails: list[str] = []
    ran = 0
    for name in ("max_tier_1", "max_tier_0"):
        res = probe.get(name)
        if not isinstance(res, dict) or res.get("result") == "not_run":
            continue
        ran += 1
        if (res.get("result") == "prepared") != (res.get("prepared") is not None):
            fails.append(f"{name}_prepared_mismatch")  # brief 5.1: result=prepared exactly when a prepared object is recorded
        if res.get("result") == "exception":
            fails.append(f"{name}_exception")
        elif res.get("result") == "rejected" and (not res.get("reason") or not res.get("detail")):
            fails.append(f"{name}_rejection_detail_missing")
        elif res.get("result") == "prepared":
            if probe.get("binding_matches_target") is not True:
                fails.append("binding_matches_target")
            prep = res.get("prepared")
            tgt = _dict(case.get("target"))
            if isinstance(prep, dict) and (
                prep.get("stream_xref") != tgt.get("stream_xref")
                or prep.get("binding_op_start") != tgt.get("op_start")
                or not (
                    isinstance(prep.get("replacement_start"), int)
                    and isinstance(prep.get("replacement_end"), int)
                    and isinstance(tgt.get("op_start"), int)
                    and isinstance(tgt.get("op_end"), int)
                    and tgt["op_start"] <= prep["replacement_start"] <= prep["replacement_end"] <= tgt["op_end"]
                )
            ):
                fails.append("binding_differs_from_target")
    if _g(case, "mutation", "path") == "product_commit" and _g(probe, "commit", "status") not in COMMITTED_STATUSES:
        fails.append("commit_not_committed")  # a product commit that did not commit is not a pass
    if ran == 0 and not fails:
        return _combine([], ["probe_not_run"], recorded)
    return _combine(fails, [], recorded)


def _structure_phase(case: dict, res: CheckResult) -> PhaseCheck:
    mut, ts = case.get("mutation"), case.get("text_state")
    recorded = _g(case, "phases", "structure", "result")
    fails = list(res.fails.get("structure", []))
    undecided = list(res.not_run.get("structure", []))
    if _g(mut, "other_xrefs_changed_live"):
        fails.append("other_xrefs_changed_live")
    if _g(mut, "other_xrefs_changed_semantic"):
        fails.append("other_xrefs_changed_semantic")
    changes = _g(mut, "changes", default=[])
    if _g(mut, "splice_kind") != "canary":
        if len(changes) != 1:
            fails.append("changes_count")
        if any(isinstance(c, dict) and c.get("token_aligned") is not True for c in changes):
            fails.append("not_token_aligned")
    wrappers_unchanged = _g(mut, "wrapper_bytes_unchanged")
    if wrappers_unchanged is False:
        fails.append("wrapper_bytes_changed")
    elif wrappers_unchanged is None and _g(ts, "before", "wrapper_stack"):
        undecided.append("wrapper_bytes_unchanged_missing")  # brief 5.2: true is a structure pass condition; null is only vacuous without wrappers
    if isinstance(ts, dict):
        for key in ("target_equal", "nontarget_shows_equal"):
            if ts.get(key) is False:
                fails.append(key)
            elif ts.get(key) is None:
                undecided.append(f"{key}_missing")
        for before, after in (("show_count_before", "show_count_after"), ("operator_count_before", "operator_count_after")):
            if ts.get(after) is None:
                undecided.append(f"{after}_missing")
            elif ts.get(after) != ts.get(before):
                fails.append(after)
    return _combine(fails, undecided, recorded)


def _render_phase(case: dict, name: str) -> PhaseCheck:
    r = _g(case, "render", name)
    recorded = _g(case, "phases", f"render_{name}", "result")
    if not isinstance(r, dict):
        return PhaseCheck("not_run", ("render_missing",))
    fails, undecided = [], []
    target, non, ctrl = r.get("target_changed_px"), r.get("nontarget_changed_px"), r.get("control_rerender_changed_px")
    if target is None:
        undecided.append("target_changed_px_missing")
    elif target < 1:
        fails.append("target_not_changed")
    if non is None:
        undecided.append("nontarget_changed_px_missing")
    elif non != 0:
        fails.append("nontarget_changed")
    if ctrl is None:
        undecided.append("control_rerender_missing")
    elif ctrl != 0:
        fails.append("control_rerender_differs")
    if name == "mupdf":
        live = _g(case, "render", "live_vs_reopened_changed_px")
        if live is None:
            undecided.append("live_vs_reopened_missing")
        elif live != 0:
            fails.append("live_vs_reopened_differs")
    if not _is_num(r.get("crop_zoom")) or r["crop_zoom"] < 6 or not _is_num(r.get("fullpage_zoom")) or r["fullpage_zoom"] < 2:
        fails.append("zoom_below_floor")
    return _combine(fails, undecided, recorded)


def _extraction_phase(case: dict) -> PhaseCheck:
    ex = case.get("extraction")
    recorded = _g(case, "phases", "extraction", "result")
    if not isinstance(ex, dict):
        return PhaseCheck("not_run", ("extraction_missing",))
    fails, undecided = [], []
    for key in ("equals_replacement", "old_text_remains_at_target", "nontarget_text_changes"):
        if ex.get(key) is None:
            undecided.append(f"{key}_missing")
    if ex.get("after_text_at_target") is None and ex.get("equals_replacement") is not None:
        undecided.append("after_text_missing")  # the flag summarises a datum that is absent
    if ex.get("equals_replacement") is False:
        fails.append("text_differs")
    if ex.get("old_text_remains_at_target") is True:
        fails.append("old_text_remains")
    if ex.get("nontarget_text_changes") not in (None, 0):
        fails.append("nontarget_text_changed")
    return _combine(fails, undecided, recorded)


def _save_phase(case: dict) -> PhaseCheck:
    s, mut = case.get("save_reopen"), case.get("mutation")
    recorded = _g(case, "phases", "save_reopen", "result")
    if not isinstance(s, dict) or not isinstance(mut, dict):
        return PhaseCheck("not_run", ("save_reopen_missing",))
    fails, undecided = [], []
    for key in ("page_count_equal", "new_objects_subset_xref", "reopened_text_at_target_equals_replacement", "text_state_equal", "glyph_identity_equal"):
        if s.get(key) is None:
            undecided.append(f"{key}_missing")
        elif s.get(key) is not True:
            fails.append(key)
    if s.get("source_sha256_unchanged") is not True:
        fails.append("source_sha256_unchanged")
    if mut.get("new_objects_all_xref") is not True:
        fails.append("new_objects_not_xref")
    if mut.get("saved_with") != "saveIncr":
        fails.append("saved_with_not_saveIncr")
    live = _g(case, "render", "live_vs_reopened_changed_px")
    if live not in (None, 0):
        fails.append("live_vs_reopened_differs")
    return _combine(fails, undecided, recorded)


def recompute_phase_results(case: dict, records: list[dict] | None) -> tuple[dict[str, PhaseCheck], CheckResult]:
    """Every phase result, recomputed; a recorded result that differs is a violation."""
    res = CheckResult()
    for part in (
        check_cross_field(case, records),
        check_operand_grammar(case),
        check_advance(case),
        check_growth_zone(case),
        check_pairing(case, records),
        check_glyph_identity(case),
    ):
        res.extend(part)
    acc = _Acc(case)
    mut = case.get("mutation")
    phases: dict[str, PhaseCheck] = {"probe": _probe_phase(case)}
    if mut is None:
        for name in PHASE_NAMES[1:]:
            phases[name] = PhaseCheck("not_run", ("no mutation",))
    else:
        phases["structure"] = _structure_phase(case, res)
        phases["growth_zone"] = _combine(
            res.fails.get("growth_zone", []), res.not_run.get("growth_zone", []), _g(case, "phases", "growth_zone", "result")
        )
        phases["render_mupdf"] = _render_phase(case, "mupdf")
        phases["render_poppler"] = _render_phase(case, "poppler")
        phases["neighbours"] = _combine(
            res.fails.get("neighbours", []), res.not_run.get("neighbours", []), _g(case, "phases", "neighbours", "result")
        )
        phases["glyph_identity"] = _combine(
            res.fails.get("glyph_identity", []), res.not_run.get("glyph_identity", []), _g(case, "phases", "glyph_identity", "result")
        )
        phases["extraction"] = _extraction_phase(case)
        phases["save_reopen"] = _save_phase(case)
        ex = _dict(case.get("extraction"))
        after_text = ex.get("after_text_at_target")
        replacement = _g(case, "corpus_case", "replacement")
        if isinstance(after_text, str) and isinstance(replacement, str) and ex.get("equals_replacement") is not None:
            if ex.get("equals_replacement") != (after_text == replacement):
                acc.v("extraction_self_inconsistent", "/extraction/equals_replacement", "equals_replacement differs from the text comparison")
    for name in PHASE_NAMES:
        recorded = _g(case, "phases", name, "result")
        if mut is None and name != "probe":
            continue
        if recorded is not None and recorded != phases[name].result:
            acc.v("phase_result_mismatch", f"/phases/{name}/result", f"recorded {_vocab(recorded)}, recomputed {phases[name].result}")
    for rname, pname in (("mupdf", "render_mupdf"), ("poppler", "render_poppler")):
        recorded = _g(case, "render", rname, "status")
        if recorded is not None and recorded != phases[pname].result:
            acc.v("phase_result_mismatch", f"/render/{rname}/status", f"recorded {_vocab(recorded)}, recomputed {phases[pname].result}")
    res.extend(acc.res)
    return phases, res


def recompute_status(case: dict, phases: dict[str, PhaseCheck], *, calibration_status: str, pre_registered: bool, case_violations: Iterable[Violation]) -> str:
    """Brief 5.3 rules 1-8, in order."""
    kind, mut = case.get("kind"), case.get("mutation")
    probe = _dict(case.get("probe"))
    t1 = _dict(probe.get("max_tier_1"))
    t0 = _dict(probe.get("max_tier_0"))
    results = {name: phases[name].result for name in PHASE_NAMES}
    # 1
    if _g(case, "code_revision", "tracked_diff_empty") is not True or results["probe"] == "blocked":
        return "blocked"
    if any(r.get("result") == "exception" for r in (t1, t0)):
        return "blocked"
    # 2
    if case.get("status") == "out_of_scope_vector" and mut is None and str(case.get("observation", "")).strip():
        return "out_of_scope_vector"
    probe_rejected = t1.get("result") == "rejected" and t0.get("result") in ("rejected", "not_run")
    # 3
    if kind in ("negative", "census"):
        reason_ok = kind == "census" or (t1.get("reason") == _g(case, "corpus_case", "expected_reason") and pre_registered)
        return "probe_rejected" if probe_rejected and reason_ok and mut is None else "insufficient_evidence"
    # 4
    if kind == "positive" or (kind == "control" and mut is not None):
        inconsistent = any(v.code == "phase_result_mismatch" for v in case_violations)
        if (
            any(r in ("not_run", "blocked") for r in results.values())
            or ((t1.get("result") == "prepared" or t0.get("result") == "prepared") and probe.get("binding_matches_target") is not True)
            or calibration_status == "fail"
            or not pre_registered
            or "reported_unpaired" in phases["neighbours"].reasons
            or "recomputed_unpaired" in phases["neighbours"].reasons
            or inconsistent
        ):
            return "insufficient_evidence"
    # 5, 6
    if all(r == "pass" for r in results.values()):
        return "save_reopen_pass"
    if all(results[n] == "pass" for n in PHASE_NAMES[:-1]) and results["save_reopen"] == "fail":
        return "splice_pass"
    # 7
    if probe_rejected and (mut is None or any(r == "fail" for r in results.values())):
        return "probe_rejected"
    return "insufficient_evidence"


# --------------------------------------------------------------------------
# lineage, parent summary
# --------------------------------------------------------------------------
def _lineage_key(slug: str) -> str:
    slug = re.sub(r"-komprimiert$", "", slug)
    slug = re.sub(r"-damaged$", "", slug)
    slug = re.sub(r"-[12]$", "", slug)
    slug = re.sub(r"^(t01-fail)-[a-z]$", r"\1", slug)
    if re.match(r"^habibi", slug):
        return "habibi"
    return slug


def check_lineage(cases: list[dict]) -> tuple[dict[str, tuple[int, int]], list[Violation]]:
    """Brief 3.7 groups.  Returns ``key -> (cases, distinct lineage_ids)`` and violations."""
    seen: dict[str, tuple[str, str]] = {}
    by_sha: dict[str, dict[str, str]] = {}
    tally: dict[str, list[str]] = {}
    out: list[Violation] = []
    for case in cases:
        src = case.get("source") if isinstance(case, dict) else None
        if not isinstance(src, dict) or src.get("provenance") == "synthetic" or not isinstance(src.get("slug"), str):
            continue
        key = _lineage_key(src["slug"])
        lineage = str(src.get("lineage_id"))
        sha = src.get("sha256")
        if isinstance(sha, str):
            # one file is one lineage and one producer family whatever label the bundle gives it (brief 3.7)
            mine = {"slug": src["slug"], "lineage_id": lineage, "producer_family": str(src.get("producer_family"))}
            first = by_sha.setdefault(sha, mine)
            for field_name, value in mine.items():
                if value != first[field_name]:
                    cid = case.get("case_id") if isinstance(case.get("case_id"), str) else None
                    out.append(
                        Violation(
                            "lineage_mismatch",
                            f"cases/{cid}/case_record.json" if cid else "cases.json",
                            f"/source/{field_name}",
                            "one sha256 is one document: slug, lineage_id and producer_family must agree (brief 3.7)",
                            cid,
                        )
                    )
        tally.setdefault(key, []).append(lineage)
        if key in seen and seen[key][0] != lineage:
            cid = case.get("case_id") if isinstance(case.get("case_id"), str) else None
            out.append(
                Violation(
                    "lineage_mismatch",
                    f"cases/{cid}/case_record.json" if cid else "cases.json",
                    "/source/lineage_id",
                    "documents of one lineage group share one lineage_id (brief 3.7)",
                    cid,
                )
            )
        seen.setdefault(key, (lineage, str(case.get("case_id"))))
    return {k: (len(v), len(set(v))) for k, v in tally.items()}, out


def _is_builtin_exception(name: str) -> bool:
    obj = getattr(builtins, name, None)
    return isinstance(obj, type) and issubclass(obj, BaseException)


def _tier_of(case: dict) -> int:
    mut = _dict(case.get("mutation"))
    if mut.get("path") == "product_commit":
        tier = _g(case, "probe", "commit", "tier")
        return 1 if tier == 1 else 0
    advs = _advances(case)
    return 1 if advs and advs[0][1].get("K_written") is not None else 0


def recompute_parent_summary(cases: list[dict], statuses: dict[str, str]) -> dict:
    """cases_total, by_status, per_class and product_findings from cases.json."""
    by_status = dict.fromkeys(STATUS_KEYS, 0)
    per: dict[Any, dict] = {}
    findings: list[dict] = []
    for case in cases:
        cid: Any = case.get("case_id")
        status = statuses.get(cid, case.get("status"))
        if status in by_status:
            by_status[status] += 1
        for name in ("max_tier_1", "max_tier_0"):
            if _g(case, "probe", name, "result") == "exception":
                kind = _g(case, "probe", name, "exception_type")
                shown = kind if isinstance(kind, str) and _is_builtin_exception(kind) else _digest(str(kind))
                findings.append({"case_id": cid, "kind": "engine_exception", "detail": f"{name} raised {shown}"})
        if case.get("kind") not in COUNTED_KINDS:
            continue
        e = per.setdefault(
            case.get("class_id"),
            {"cases": 0, "positives": 0, "negatives": 0, "lin": set(), "fam": set(), "t0": 0, "t1": 0, "by": dict.fromkeys(STATUS_KEYS, 0)},
        )
        e["cases"] += 1
        e["positives"] += case.get("kind") == "positive"
        e["negatives"] += case.get("kind") == "negative"
        src = _dict(case.get("source"))
        if src.get("provenance") != "synthetic":
            e["lin"].add(src.get("lineage_id"))
            e["fam"].add(src.get("producer_family"))
        if status in e["by"]:
            e["by"][status] += 1
        if case.get("kind") == "positive" and status == "save_reopen_pass":
            e["t1" if _tier_of(case) == 1 else "t0"] += 1
    per_class = {}
    for cls, e in per.items():
        passes = e["t0"] + e["t1"]
        if passes == 0:
            proposal = "open"
        elif passes < 2 or len(e["lin"]) < 2:
            proposal = "needs_second_case"
        elif e["negatives"] == 0:
            proposal = "needs_negative"
        else:
            proposal = "method_reproducible" if len(e["fam"]) >= 2 else "method_reproducible_single_family"
        per_class[cls] = {
            "cases": e["cases"],
            "positives": e["positives"],
            "negatives": e["negatives"],
            "distinct_lineages": len(e["lin"]),
            "distinct_producer_families": len(e["fam"]),
            "tier0_positive_pass": e["t0"],
            "tier1_positive_pass": e["t1"],
            "by_status": e["by"],
            "class_state_proposal": proposal,
            "remeasure_pending": True,
        }
    return {"cases_total": len(cases), "by_status": by_status, "per_class": per_class, "product_findings": findings}


def _diff(want: object, got: object, pointer: str, out: list[str]) -> None:
    if isinstance(want, dict) and isinstance(got, dict):
        for key in sorted(set(want) | set(got), key=str):
            if key == "class_state_proposal":
                continue
            _diff(want.get(key), got.get(key), f"{pointer}/{_esc(key)}", out)
    elif not _jeq(want, got):
        out.append(pointer)


def _check_parent(parent: dict | None, cases: list[dict], statuses: dict[str, str], root: Path) -> CheckResult:
    acc = _Acc({}, file="PARENT_SUMMARY.json")
    if not isinstance(parent, dict):
        return acc.res
    want = recompute_parent_summary(cases, statuses)
    for key in ("cases_total", "by_status"):
        pointers: list[str] = []
        _diff(want[key], parent.get(key), f"/{key}", pointers)
        for ptr in pointers:
            acc.v("parent_summary_mismatch", ptr, "differs from the value recomputed from cases.json")
    got_pc = _dict(parent.get("per_class"))
    for cls in sorted(set(want["per_class"]) | set(got_pc), key=str):
        if cls not in F_CLASSES and cls != "OUT":
            acc.v("parent_class_key", f"/per_class/{_esc(cls)}", "per_class keys are F classes or OUT")
            continue
        pointers = []
        _diff(want["per_class"].get(cls), got_pc.get(cls), f"/per_class/{_esc(cls)}", pointers)
        for ptr in pointers:
            acc.v("parent_summary_mismatch", ptr, "differs from the value recomputed from cases.json")
        entry = got_pc.get(cls)
        if isinstance(entry, dict):
            proposal = entry.get("class_state_proposal")
            if proposal in ("method_reproducible", "method_reproducible_single_family"):
                ref = want["per_class"].get(cls, {})
                passes = ref.get("tier0_positive_pass", 0) + ref.get("tier1_positive_pass", 0)
                if passes < 2 or ref.get("distinct_lineages", 0) < 2 or ref.get("negatives", 0) < 1 or (
                    proposal == "method_reproducible" and ref.get("distinct_producer_families", 0) < 2
                ):
                    acc.v("class_state_overclaim", f"/per_class/{_esc(cls)}/class_state_proposal", "the class does not meet the brief 3.0 reproducibility bar")
    found = {(f.get("case_id"), f.get("kind")) for f in (parent.get("product_findings") or []) if isinstance(f, dict)}
    for f in want["product_findings"]:
        if (f["case_id"], f["kind"]) not in found:
            acc.v("parent_summary_mismatch", "/product_findings", "every probe exception needs a product finding")
    # invariants of the parent file itself
    by = parent.get("by_status")
    if isinstance(by, dict) and isinstance(parent.get("cases_total"), int) and sum(v for v in by.values() if isinstance(v, int)) != parent["cases_total"]:
        acc.v("parent_invariant", "/by_status", "by_status must sum to cases_total")
    counted = 0
    for cls, entry in got_pc.items():
        if isinstance(entry, dict) and isinstance(entry.get("by_status"), dict):
            counted += entry.get("cases", 0) if isinstance(entry.get("cases"), int) else 0
            if sum(v for v in entry["by_status"].values() if isinstance(v, int)) != entry.get("cases"):
                acc.v("parent_invariant", f"/per_class/{_esc(cls)}/by_status", "per-class by_status must sum to cases")
    side = sum(1 for c in cases if c.get("kind") in ("control", "canary"))
    if isinstance(parent.get("cases_total"), int) and counted + side != parent["cases_total"]:
        acc.v("parent_invariant", "/cases_total", "per_class cases plus control and canary cases must equal cases_total")
    if parent.get("stamp") != root.name:
        acc.v("parent_invariant", "/stamp", "stamp must equal the batch directory name")
    attempts = _g(parent, "calibration", "attempts")
    if isinstance(attempts, int) and attempts > 3:
        acc.v("parent_invariant", "/calibration/attempts", "R0 may run at most 3 times")
    return acc.res


# --------------------------------------------------------------------------
# calibration
# --------------------------------------------------------------------------
def _all_pass(ph: dict[str, PhaseCheck]) -> bool:
    return all(ph[p].result == "pass" for p in PHASE_NAMES)


def _control_row(case: dict, ph: dict[str, PhaseCheck], status: Any) -> tuple[bool, dict]:
    cls = case.get("class_id")
    gz = _dict(case.get("growth_zone"))
    adv = _advances(case)[0][1] if _advances(case) else {}
    t1 = _g(case, "probe", "max_tier_1", default={})
    t0 = _g(case, "probe", "max_tier_0", default={})
    commit = _g(case, "probe", "commit", default={})
    mutated = case.get("mutation") is not None
    obs: dict = {}
    ok = False
    if cls == "CTRL_POS_T0":
        obs = {"nine_phases_pass": _all_pass(ph), "growth_applicable": gz.get("applicable"), "commit_tier": commit.get("tier")}
        ok = mutated and obs["nine_phases_pass"] and gz.get("applicable") is False and commit.get("tier") == 0
    elif cls == "CTRL_POS_T1":
        obs = {
            "nine_phases_pass": _all_pass(ph),
            "K_written": adv.get("K_written"),
            "K_sum": adv.get("K_sum"),
            "growth_applicable": gz.get("applicable"),
            "gate_counters": [gz.get(k) for k in ("before_glyph_bboxes_intersecting", "before_drawings_not_provably_clear", "before_images_intersecting")],
            "raster_proof": _vocab(gz.get("raster_proof")),
        }
        ok = (
            mutated
            and obs["nine_phases_pass"]
            and _close(adv.get("K_written"), 333.0, NUM_TOL)
            and _close(adv.get("K_sum"), 0.0, NUM_TOL)
            and gz.get("applicable") is True
            and obs["gate_counters"] == [0, 0, 0]
            and gz.get("raster_proof") == "pass"
        )
    elif cls == "CTRL_NEG":
        obs = {"reason": _vocab(t1.get("reason")), "mutation_null": not mutated, "status": _vocab(status)}
        ok = t1.get("reason") == "type0_unicode_unmapped" and not mutated and status == "probe_rejected"
    elif cls == "CTRL_SYN_T0":
        obs = {"tier": t1.get("tier"), "attempted": commit.get("attempted"), "nine_phases_pass": _all_pass(ph), "growth_applicable": gz.get("applicable")}
        ok = (
            t1.get("result") == "prepared"
            and t1.get("tier") == 0
            and commit.get("attempted") is True
            and obs["nine_phases_pass"]
            and gz.get("applicable") is False
        )
    elif cls == "CTRL_SYN_T1":
        detail = t1.get("detail") if isinstance(t1.get("detail"), str) else ""
        obs = {
            "tier1": [_vocab(t1.get("result")), _vocab(t1.get("reason")), detail.startswith("glyphs:")],
            "tier0": [_vocab(t0.get("result")), _vocab(t0.get("reason"))],
            "attempted": commit.get("attempted"),
            "mutation_null": not mutated,
            "growth_applicable": gz.get("applicable"),
            "growth_phase": ph["growth_zone"].result,
            "status": _vocab(status),
        }
        ok = (
            t1.get("result") == "rejected"
            and t1.get("reason") == "growth_region_not_blank"
            and detail.startswith("glyphs:")
            and t0.get("result") == "rejected"
            and t0.get("reason") == "advance_mismatch"
            and commit.get("attempted") is False
            and not mutated
            and gz.get("applicable") is False
            and ph["growth_zone"].result == "not_run"
            and status == "probe_rejected"
        )
    elif cls == "CTRL_DET":
        vals = [_g(case, "render", n, "control_rerender_changed_px") for n in ("mupdf", "poppler")]
        obs = {"control_rerender": vals}
        ok = all(v in (None, 0) for v in vals)
    return ok, obs


def _canary_row(case: dict, ph: dict[str, PhaseCheck], cases_pairs: list) -> dict:
    cls: Any = case.get("class_id")
    failed = [p for p in PHASE_NAMES if ph[p].result == "fail"]
    must = list(MUST_FAIL_PHASES.get(cls, ()))
    legs: dict[str, bool | None] = dict.fromkeys(GROWTH_LEGS)
    if cls == "CANARY_GROWTH":
        after_raw = _g(case, "target", "after_bbox_raw")
        geometry = False
        for rec in cases_pairs:
            if isinstance(rec, dict) and rec.get("role") != "target" and rec.get("is_space") is False and _bbox_ok(rec.get("bbox_before")) and _bbox_ok(after_raw):
                geometry = geometry or _bbox_intersects(rec["bbox_before"], after_raw)
        legs = {
            "geometry_overlap": geometry,
            "growth_zone_glyph": (_g(case, "growth_zone", "before_glyph_bboxes_intersecting", default=0) or 0) >= 1,
            "growth_zone_raster": _g(case, "growth_zone", "raster_proof") == "fail",
            "neighbours_overlap": (_g(case, "neighbours", "overlap_glyphs", default=0) or 0) >= 1,
        }
        caught = legs["geometry_overlap"] and legs["growth_zone_glyph"] and legs["neighbours_overlap"]
    else:
        caught = bool(must) and all(m in failed for m in must)
    return {
        "site": case.get("join_key"),
        "must_fail_phases": must,
        "failed_phases": failed,
        "caught": bool(caught),
        "legs": legs,
        "missed_legs": [leg for leg in GROWTH_LEGS if legs[leg] is False],
    }


def check_calibration(
    parent: dict | None,
    cases: list[dict],
    phases: dict[str, dict[str, PhaseCheck]],
    statuses: dict[Any, str] | None = None,
    records: dict[Any, list[dict]] | None = None,
) -> CheckResult:
    """Controls and canaries recomputed from their rows and compared with the parent."""
    res = CheckResult()
    statuses = statuses or {}
    records = records or {}
    controls: dict[Any, dict] = {}
    canaries: dict[Any, dict] = {}
    sites: list[dict] = []
    pfile = "PARENT_SUMMARY.json"
    class_count: dict[Any, int] = {}
    for c in cases:
        class_count[c.get("class_id")] = class_count.get(c.get("class_id"), 0) + 1
    growth_cases = []
    blocked_rows: set[Any] = set()  # control or canary keys the bundle recorded as blocked (brief 2.3: hvac absent)
    declared = _g(parent, "calibration", "status")
    for c in cases:
        cid = c.get("case_id")
        if cid not in phases:
            continue
        kind = c.get("kind")
        if kind == "control":
            ok, obs = _control_row(c, phases[cid], statuses.get(cid, c.get("status")))
            ckey = c.get("class_id")
            cfile = f"cases/{cid}/case_record.json"
            if ckey in controls:
                # one row per control class: a second row must not replace (and so hide) a failed first one
                res.violations.append(Violation("control_duplicate", cfile, "/class_id", "one row per control class (brief 2.1)", cid))
                if not ok:
                    controls[ckey].update(observed=obs, ok=False)
            else:
                controls[ckey] = {"expected": "brief 2.1 row", "observed": obs, "ok": ok}
            site = CONTROL_SITES.get(ckey) if isinstance(ckey, str) else None
            if site is not None and not (c.get("status") == "blocked" and declared == "synthetic_only"):
                for ptr, got, want in (
                    ("/source/slug", _g(c, "source", "slug"), site[0]),
                    ("/corpus_case/page_index", _g(c, "corpus_case", "page_index"), site[1]),
                    ("/corpus_case/show_seq", _g(c, "corpus_case", "show_seq"), site[2]),
                ):
                    if got != want:
                        res.violations.append(Violation("control_site", cfile, ptr, "this control is pinned to its brief 2.1 hvac site", cid))
            if c.get("status") == "blocked":
                blocked_rows.add(c.get("class_id"))
        elif kind == "canary":
            row = _canary_row(c, phases[cid], records.get(cid, []))
            key = c["class_id"] if class_count.get(c.get("class_id"), 0) == 1 else f"{c['class_id']}@{c.get('join_key')}"
            canaries[key] = row
            if c.get("status") == "blocked":
                blocked_rows.add(key)
            if c.get("class_id") == "CANARY_GROWTH":
                growth_cases.append(c)
                sites.append({"site": c.get("join_key"), "page_rotation": _g(c, "source", "page_rotation"), "show_seq": _g(c, "corpus_case", "show_seq")})
    # brief 2.3: synthetic_only is the fallback for a missing (or different) hvac file only.  A row measured on hvac that
    # is not recorded blocked proves the file is present, so the declaration cannot excuse the hvac controls.
    hvac_measured = declared == "synthetic_only" and any(
        (_g(c, "source", "slug") == "hvac" or _g(c, "source", "sha256") == HVAC_SHA256)
        and statuses.get(c.get("case_id"), c.get("status")) != "blocked"
        for c in cases
    )
    if hvac_measured:
        res.violations.append(
            Violation("synthetic_only_with_hvac_present", pfile, "/calibration/status", "a row measured on the hvac file contradicts synthetic_only (brief 2.3)")
        )
    synthetic_ok = declared == "synthetic_only" and not hvac_measured
    forgiven = blocked_rows if synthetic_ok else set()
    failed = [k for k, v in controls.items() if not v["ok"] and k not in forgiven] + [
        k for k, v in canaries.items() if not v["caught"] and k not in forgiven
    ]
    effective = "fail" if failed else (declared if declared in ("pass", "synthetic_only") else "pass")
    res.info = {"status": effective, "controls": controls, "canaries": canaries, "growth_canary_sites": sites, "failed": failed}
    # growth canary sites
    for c in growth_cases:
        cid = c.get("case_id")
        file = f"cases/{cid}/case_record.json"
        if _g(c, "source", "page_rotation") == 0:
            res.violations.append(Violation("growth_canary_site", file, "/source/page_rotation", "a growth canary must sit on a rotated page", cid))
        if _g(c, "source", "slug") == "hvac" and _g(c, "corpus_case", "page_index") == 4 and _g(c, "corpus_case", "show_seq") not in (161, 162):
            res.violations.append(Violation("growth_canary_site", file, "/corpus_case/show_seq", "the hvac growth site is p4 show 161 (or 162)", cid))
    if growth_cases and not any(_g(c, "source", "provenance") == "synthetic" for c in growth_cases):
        res.violations.append(Violation("growth_canary_site", pfile, "/calibration/growth_canary_sites", "the CTRL_SYN_T1 geometry site is missing"))
    # frontier rows must cite the batch status
    for c in cases:
        if c.get("kind") in COUNTED_KINDS and c.get("calibration_ref") != effective:
            cid = c.get("case_id")
            res.violations.append(Violation("calibration_ref_mismatch", f"cases/{cid}/case_record.json", "/calibration_ref", "calibration_ref must equal the batch calibration status", cid))
    if not isinstance(parent, dict):
        return res
    cal = _dict(parent.get("calibration"))
    pc = _dict(cal.get("controls"))
    for key, row in controls.items():
        entry = pc.get(key)
        if not isinstance(entry, dict) or entry.get("ok") != row["ok"]:
            res.violations.append(Violation("calibration_mismatch", pfile, f"/calibration/controls/{_esc(key)}/ok", f"recomputed control {_esc(key)} ok={row['ok']}"))
    for key in pc:
        if key not in controls:
            res.violations.append(Violation("calibration_mismatch", pfile, f"/calibration/controls/{_esc(key)}", "parent lists a control that has no case row"))
    pcan = _dict(cal.get("canaries"))
    for key, row in canaries.items():
        entry = pcan.get(key)
        if not isinstance(entry, dict):
            res.violations.append(Violation("calibration_mismatch", pfile, f"/calibration/canaries/{_esc(key)}", f"parent lacks canary {_esc(key)}"))
            continue
        for fld in ("caught", "legs", "site"):
            if not _jeq(entry.get(fld), row[fld]):
                res.violations.append(Violation("calibration_mismatch", pfile, f"/calibration/canaries/{_esc(key)}/{fld}", f"recomputed canary {_esc(key)} {fld} differs"))
        for fld in ("failed_phases", "must_fail_phases", "missed_legs"):
            if not (isinstance(entry.get(fld), list) and sorted(entry[fld]) == sorted(row[fld])):
                res.violations.append(Violation("calibration_mismatch", pfile, f"/calibration/canaries/{_esc(key)}/{fld}", f"recomputed canary {_esc(key)} {fld} differs"))
    for key in pcan:
        if key not in canaries:
            res.violations.append(Violation("calibration_mismatch", pfile, f"/calibration/canaries/{_esc(key)}", "parent lists a canary that has no case row"))
    if (effective == "fail") != (declared == "fail"):
        res.violations.append(Violation("calibration_mismatch", pfile, "/calibration/status", f"recomputed calibration status is {effective}"))
    got_sites = _list(cal.get("growth_canary_sites"))
    key_of = lambda s: json.dumps(s, sort_keys=True)  # noqa: E731
    if sorted(map(key_of, got_sites)) != sorted(map(key_of, sites)):
        res.violations.append(Violation("calibration_mismatch", pfile, "/calibration/growth_canary_sites", "site list differs from the growth canary rows"))
    # R0 completeness (brief 2: no frontier case before R0 passes).  A batch with a counted row must carry the whole pack;
    # under synthetic_only (brief 2.3, hvac absent) only the synthetic subset: CTRL_SYN_T0/T1, every canary but CANARY_FONT
    # (not_run on a one-font page) and the synthetic growth site.  A batch without counted rows is a calibration-fail batch.
    synthetic_only = synthetic_ok
    need_controls = ["CTRL_SYN_T0", "CTRL_SYN_T1"] if synthetic_only else list(R0_CONTROLS)
    need_canaries = [c for c in MUST_FAIL_PHASES if not (synthetic_only and c == "CANARY_FONT")]
    missing = [r for r in need_controls if r not in controls] + [
        r for r in need_canaries if not any(k == r or k.startswith(r + "@") for k in canaries)
    ]
    if "CANARY_GROWTH" in need_canaries and "CANARY_GROWTH" not in missing:
        if not any(_g(c, "source", "provenance") == "synthetic" for c in growth_cases):
            missing.append("CANARY_GROWTH")  # the synthetic site (CTRL_SYN_T1 geometry)
        elif not synthetic_only and not any(_g(c, "source", "slug") == "hvac" for c in growth_cases):
            missing.append("CANARY_GROWTH")  # the hvac site is mandatory whenever hvac exists
    if missing:
        item = Violation("calibration_incomplete", pfile, "/calibration", f"{len(missing)} R0 control or canary row(s) absent from this batch")
        if any(c.get("kind") in COUNTED_KINDS for c in cases):
            res.violations.append(item)
        else:
            res.unverifiable.append(item)
    return res


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------
def _case_dir_name(case: object) -> str | None:
    cid = case.get("case_id") if isinstance(case, dict) else None
    return cid if isinstance(cid, str) and _ID_RE.match(cid) else None


def load_batch(batch_dir: Path) -> tuple[Batch, list[Violation]]:
    """Read the whole brief-6 layout; every miss is a violation and nothing stops early."""
    root = Path(batch_dir)
    out: list[Violation] = []

    for rel in REQUIRED_BATCH_FILES:
        if not (root / rel).is_file():
            out.append(Violation("file_missing", rel, "", "required batch file is missing"))
    cases_raw = _read_optional(root / "cases.json", out, "cases.json")
    cases = [c for c in cases_raw if isinstance(c, dict)] if isinstance(cases_raw, list) else []
    parent = _read_optional(root / "PARENT_SUMMARY.json", out, "PARENT_SUMMARY.json")
    done = _read_optional(root / "DONE.json", out, "DONE.json")
    plan_bytes = (root / "METHODS_AND_EVIDENCE_PLAN.md").read_bytes() if (root / "METHODS_AND_EVIDENCE_PLAN.md").is_file() else None
    parent_bytes = (root / "PARENT_SUMMARY.json").read_bytes() if (root / "PARENT_SUMMARY.json").is_file() else None
    records: dict[str, list[dict]] = {}
    listed: set[str] = set()
    for case in cases:
        cid = _case_dir_name(case)
        if cid is None:
            out.append(Violation("case_id_mismatch", "cases.json", "", "a cases.json element has no usable case_id"))
            continue
        listed.add(cid)
        for name in REQUIRED_CASE_FILES:
            rel = f"cases/{cid}/{name}"
            if not (root / rel).is_file():
                out.append(Violation("file_missing", rel, "", "required case file is missing", cid))
        record = _read_optional(root / "cases" / cid / "case_record.json", out, f"cases/{cid}/case_record.json", cid)
        if record is not None and record != case:
            out.append(Violation("cases_json_mismatch", f"cases/{cid}/case_record.json", "", "case_record.json differs from its cases.json element", cid))
        nb = _read_optional(root / "cases" / cid / "neighbours.json", out, f"cases/{cid}/neighbours.json", cid)
        records[cid] = [r for r in nb] if isinstance(nb, list) else []
        if nb is not None and not isinstance(nb, list):
            out.append(Violation("json_unparseable", f"cases/{cid}/neighbours.json", "", "neighbours.json is not an array", cid))
        for name in ("text_state.json", "mutation.json"):
            _read_optional(root / "cases" / cid / name, out, f"cases/{cid}/{name}", cid)
    cases_dir = root / "cases"
    if cases_dir.is_dir():
        for child in sorted(cases_dir.iterdir()):
            if child.is_dir() and child.name not in listed:
                out.append(Violation("cases_json_mismatch", _safe_rel(f"cases/{child.name}"), "", "case directory is not listed in cases.json"))
    plan_text = plan_bytes.decode("utf-8", errors="replace") if plan_bytes is not None else None
    return Batch(root, cases, records, parent if isinstance(parent, dict) else None, done if isinstance(done, dict) else None, plan_text, plan_bytes, parent_bytes), out


def _read_optional(path: Path, out: list[Violation], rel: str, cid: str | None = None):
    if not path.is_file():
        return None
    try:
        return _read_json(path)
    except (ValueError, OSError) as exc:
        out.append(Violation("json_unparseable", rel, "", f"{type(exc).__name__}: file does not parse", cid))
        return None


# --------------------------------------------------------------------------
# pre-registration, artifacts, code revision
# --------------------------------------------------------------------------
def _plan_block(text: str) -> dict | None:
    for m in re.finditer(r"```json[ \t]*\r?\n(.*?)\r?\n[ \t]*```", text, re.S):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and "pre_registration" in data:
            return data
    return None


def _variant_of(case_id: str) -> str:
    return re.sub(r"[0-9]+$", "", case_id.rsplit("-", 1)[-1])


def check_pre_registration(batch: Batch) -> tuple[CheckResult, dict[str, bool]]:
    """Brief 6.1: the fenced plan block, the plan digest and ``pre_registered``."""
    res = CheckResult()
    flags: dict[str, bool] = {}
    pfile = "METHODS_AND_EVIDENCE_PLAN.md"
    plan = _plan_block(batch.plan_text) if batch.plan_text is not None else None
    if plan is None:
        if batch.plan_text is not None:
            res.violations.append(Violation("plan_block_missing", pfile, "", "no fenced json block with a pre_registration key"))
        return res, flags
    plan_schema = load_schema(SCHEMA_DIR / PLAN_SCHEMA_NAME)
    res.violations += validate_instance(plan, plan_schema, file=pfile)
    digest = _sha256_bytes(batch.plan_bytes or b"")
    if isinstance(batch.parent, dict) and batch.parent.get("methods_plan_sha256") != digest:
        res.violations.append(Violation("methods_plan_sha_mismatch", "PARENT_SUMMARY.json", "/methods_plan_sha256", "must equal the sha256 of METHODS_AND_EVIDENCE_PLAN.md"))
    registered: dict[tuple, object] = {}
    for entry in plan.get("cases", []) if isinstance(plan.get("cases"), list) else []:
        if isinstance(entry, dict):
            registered[(entry.get("class_id"), entry.get("slug"), entry.get("page_index"), entry.get("show_seq"), entry.get("variant"))] = entry.get("expected_reason")
    for case in batch.cases:
        raw_id = case.get("case_id")
        cid = raw_id if isinstance(raw_id, str) else ""
        file = f"cases/{cid}/case_record.json"
        if case.get("methods_plan_sha256") != digest:
            res.violations.append(Violation("methods_plan_sha_mismatch", file, "/methods_plan_sha256", "must equal the sha256 of METHODS_AND_EVIDENCE_PLAN.md", cid))
        key = (case.get("class_id"), _g(case, "source", "slug"), _g(case, "corpus_case", "page_index"), _g(case, "corpus_case", "show_seq"), _variant_of(cid))
        want = key in registered and registered[key] == _g(case, "corpus_case", "expected_reason")
        flags[cid] = want
        if case.get("pre_registered") != want:
            res.violations.append(Violation("pre_registered_mismatch", file, "/pre_registered", "pre_registered must match the plan block (case present, same expected_reason)", cid))
    return res, flags


def check_code_revision(cases: list[dict], parent: dict | None) -> CheckResult:
    res = CheckResult()
    first = None
    for case in cases:
        cid = case.get("case_id") if isinstance(case.get("case_id"), str) else None
        file = f"cases/{cid}/case_record.json" if cid else "cases.json"
        rev = _dict(case.get("code_revision"))
        if rev.get("tracked_diff_empty") is not True:
            res.violations.append(Violation("tracked_diff_not_empty", file, "/code_revision/tracked_diff_empty", "product code was modified (brief 1)", cid))
        ident = (rev.get("git_head"), rev.get("dirty_diff_id"))
        if first is None:
            first = ident
        elif ident != first:
            res.violations.append(Violation("code_revision_inconsistent", file, "/code_revision/git_head", "all cases come from one working-tree snapshot", cid))
    if first is not None and isinstance(parent, dict):
        prev = _dict(parent.get("code_revision"))
        if (prev.get("git_head"), prev.get("dirty_diff_id")) != first:
            res.violations.append(Violation("code_revision_inconsistent", "PARENT_SUMMARY.json", "/code_revision/git_head", "parent code_revision differs from the cases"))
    return res


_DONE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["stamp", "case_count", "parent_summary_sha256"],
    "properties": {
        "stamp": {"type": "string"},
        "case_count": {"type": "integer", "minimum": 0},
        "parent_summary_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}


def check_artifacts(batch_dir: Path, batch: Batch) -> CheckResult:
    """Names, locations, listed files, before.pdf digests and DONE.json."""
    res = CheckResult()
    root = Path(batch_dir)
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        shown = _safe_rel(rel)
        suffix = path.suffix.lower()
        if suffix == ".png":
            if not path.name.startswith("render-"):
                res.violations.append(Violation("png_name", shown, "", "PNG files are named render-*.png (only those are gitignored)"))
        elif suffix == ".pdf":
            if not rel.startswith("candidates/"):
                res.violations.append(Violation("pdf_location", shown, "", "PDF files live under candidates/ only"))
        elif suffix not in (".json", ".md", ".py"):
            res.violations.append(Violation("unexpected_file", shown, "", "only json, md, py, png and pdf files belong in a batch"))
    for case in batch.cases:
        cid = _case_dir_name(case)
        if cid is None:
            continue
        file = f"cases/{cid}/case_record.json"
        listed = _g(case, "artifacts", "files", default=[])
        for i, rel in enumerate(listed if isinstance(listed, list) else []):
            if isinstance(rel, str) and ".." not in rel and not (root / rel).is_file():
                res.violations.append(Violation("artifact_missing", file, f"/artifacts/files/{i}", "listed artifact is not in the batch", cid))
        for pointer in ("/growth_zone/files", "/render/mupdf/files", "/render/poppler/files"):
            names = _g(case, *pointer.split("/")[1:], default=[])
            for i, name in enumerate(names if isinstance(names, list) else []):
                if isinstance(name, str) and _ID_RE.match(name.replace(".", "-")) and not (root / "cases" / cid / name).is_file():
                    res.violations.append(Violation("artifact_missing", file, f"{pointer}/{i}", "referenced render is not in the case folder", cid))
        before = root / "candidates" / cid / "before.pdf"
        if before.is_file() and _sha256_bytes(before.read_bytes()) != _g(case, "source", "sha256"):
            res.violations.append(Violation("before_pdf_sha_mismatch", f"candidates/{cid}/before.pdf", "", "sha256 of before.pdf differs from source.sha256", cid))
    if not (root / "DONE.json").is_file():
        res.violations.append(Violation("done_missing", "DONE.json", "", "DONE.json is the completion signal and is missing"))
    elif batch.done is not None:
        res.violations += validate_instance(batch.done, _DONE_SCHEMA, file="DONE.json")
        if batch.done.get("stamp") != root.name:
            res.violations.append(Violation("done_stamp_mismatch", "DONE.json", "/stamp", "stamp must equal the batch directory name"))
        if isinstance(batch.parent, dict) and batch.done.get("case_count") != batch.parent.get("cases_total"):
            res.violations.append(Violation("done_case_count_mismatch", "DONE.json", "/case_count", "case_count must equal cases_total"))
        if batch.parent_bytes is not None and batch.done.get("parent_summary_sha256") != _sha256_bytes(batch.parent_bytes):
            res.violations.append(Violation("done_sha_mismatch", "DONE.json", "/parent_summary_sha256", "must equal the sha256 of PARENT_SUMMARY.json"))
    return res


# --------------------------------------------------------------------------
# redaction scan
# --------------------------------------------------------------------------
_STATIC_ALLOW: tuple[frozenset[str], frozenset[str]] | None = None


def _static_allowlist() -> tuple[frozenset[str], frozenset[str]]:
    global _STATIC_ALLOW
    if _STATIC_ALLOW is not None:
        return _STATIC_ALLOW
    words: set[str] = set()
    cjk: set[str] = set()

    def feed(text: object) -> None:
        if isinstance(text, str):
            w, c = _tokens(text)
            words.update(w)
            cjk.update(c)

    for group in (REJECT_REASON_VALUES, WRAPPER_SLUGS, TABLE_333, STD_PROPERTY_KEYS):
        for item in group:
            feed(item)
    feed("placeholder")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("enum",) and isinstance(value, list):
                    for member in value:
                        feed(member)
                elif key == "const":
                    feed(value)
                elif key in ("properties", "$defs") and isinstance(value, dict):
                    for name, sub in value.items():
                        feed(name)
                        walk(sub)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(load_schema(SCHEMA_DIR / CASE_SCHEMA_NAME))
    _STATIC_ALLOW = (frozenset(words), frozenset(cjk))
    return _STATIC_ALLOW


def _walk_strings(obj: object, pointer: str = ""):
    """Yield ``(pointer, text, is_key)`` for every decoded key and string of a JSON value."""
    if isinstance(obj, str):
        yield pointer, obj, False
    elif isinstance(obj, dict):
        for key, value in obj.items():
            yield f"{pointer}/{_esc(key)}", str(key), True
            yield from _walk_strings(value, f"{pointer}/{_esc(key)}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _walk_strings(value, f"{pointer}/{i}")


def _free_text(case: dict):
    for pattern in FREE_TEXT_POINTERS:
        parts = pattern.split("/")[1:]

        def rec(node: object, rest: list[str], ptr: str):
            if not rest:
                if isinstance(node, str):
                    yield ptr, node
                return
            head, tail = rest[0], rest[1:]
            if head == "*":
                items = list(enumerate(node)) if isinstance(node, list) else list(node.items()) if isinstance(node, dict) else []
                for key, sub in items:
                    yield from rec(sub, tail, f"{ptr}/{_esc(key)}")
            elif isinstance(node, dict) and head in node:
                yield from rec(node[head], tail, f"{ptr}/{head}")

        yield from rec(case, parts, "")


def _regex_matcher(pat: re.Pattern[str]) -> Callable[[str], bool]:
    return lambda text: pat.search(text) is not None


def _substring_matcher(low: str) -> Callable[[str], bool]:
    return lambda text: low in text.casefold()


def _deny_matchers(denylist: Iterable[str]) -> list[Callable[[str], bool]]:
    out: list[Callable[[str], bool]] = []
    for entry in denylist:
        entry = entry.strip()
        if not entry or entry.startswith("#"):
            continue
        if entry.isascii():
            pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(entry) + r"(?![A-Za-z0-9])", re.I)
            out.append(_regex_matcher(pat))
        else:
            low = entry.casefold()
            out.append(_substring_matcher(low))
    return out


def scan_redaction(batch_dir: Path, batch: Batch, *, denylist: Iterable[str] = ()) -> tuple[CheckResult, dict[str, int], list[dict]]:
    """Three layers of brief 5.4.  Details name the rule, never the matched text."""
    res = CheckResult()
    counts = {"client_strings_left": 0, "machine_paths_left": 0, "language_warnings": 0}
    warnings: list[dict] = []
    root = Path(batch_dir)
    matchers = _deny_matchers(denylist)

    def layer1(rel: str, pointer: str, text: str, cid: str | None) -> None:
        for label, pat in PATTERNS:
            if pat.search(text):
                res.violations.append(Violation("machine_path", rel, pointer, f"device-guard pattern matched ({label})", cid))
                counts["machine_paths_left"] += 1
        for i, match in enumerate(matchers):
            if match(text):
                res.violations.append(Violation("denylist_hit", rel, pointer, f"denylist entry #{i + 1} matched", cid))

    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("candidates/"):
            continue
        cid = rel.split("/")[1] if rel.startswith("cases/") and rel.count("/") >= 2 else None
        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                data = _read_json(path)
            except (ValueError, OSError):
                continue
            for pointer, text, _is_key in _walk_strings(data):
                layer1(rel, pointer, text, cid)
        elif suffix in (".md", ".py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            for n, line in enumerate(text.splitlines(), start=1):
                for label, pat in PATTERNS:
                    if pat.search(line):
                        res.violations.append(Violation("machine_path", rel, "", f"device-guard pattern matched ({label}) on line {n}"))
                        counts["machine_paths_left"] += 1
                for i, match in enumerate(matchers):
                    if match(line):
                        res.violations.append(Violation("denylist_hit", rel, "", f"denylist entry #{i + 1} matched on line {n}"))
    static_words, static_cjk = _static_allowlist()
    for case in batch.cases:
        prov = _g(case, "source", "provenance")
        if prov in ("public", "synthetic"):
            continue
        acc = _Acc(case)
        allow_w, allow_c = set(static_words), set(static_cjk)
        own_chars: set[str] = set()
        for source in [_g(case, "corpus_case", "replacement", default="")] + (list(CALIBRATION_STRINGS) if case.get("class_id") in CALIBRATION_CLASSES else []):
            w, c = _tokens(source)
            allow_w.update(w)
            allow_c.update(c)
            own_chars.update(source)

        def scan(pointer: str, text: object, acc=acc, allow_w=allow_w, allow_c=allow_c, own_chars=own_chars) -> None:
            if not isinstance(text, str) or (len(text) == 1 and text in own_chars):
                return
            w, c = _tokens(text)
            bad = [t for t in w if t not in allow_w] + [t for t in c if t not in allow_c]
            if bad:
                acc.v("client_string", pointer, f"{len(bad)} token(s) outside the redaction allowlist")
                counts["client_strings_left"] += len(bad)

        scan("/source/producer", _g(case, "source", "producer"))
        scan("/source/creator", _g(case, "source", "creator"))
        for which in ("before", "after"):
            for i, wrapper in enumerate(_g(case, "text_state", which, "wrapper_stack", default=[]) or []):
                if not isinstance(wrapper, dict):
                    continue
                base = f"/text_state/{which}/wrapper_stack/{i}"
                scan(f"{base}/tag", wrapper.get("tag"))
                for field_name in ("props_keys", "structelem_keys"):
                    for j, key in enumerate(wrapper.get(field_name) or []):
                        scan(f"{base}/{field_name}/{j}", key)
                name = wrapper.get("props_name")
                if isinstance(name, str) and not _ascii_printable(name):
                    acc.v("props_name_not_ascii", f"{base}/props_name", "props_name must be printable ASCII")
                    counts["client_strings_left"] += 1
        scan("/extraction/after_text_at_target", _g(case, "extraction", "after_text_at_target"))
        for i, g in enumerate(case.get("glyph_identity") or []):
            if isinstance(g, dict):
                scan(f"/glyph_identity/{i}/char", g.get("char"))
        scan("/target/source_decode/latin1", _g(case, "target", "source_decode", "latin1"))
        scan("/target/source_decode/independent", _g(case, "target", "source_decode", "independent"))
        scan("/corpus_case/original", _g(case, "corpus_case", "original"))
        glyph_codes = _glyph_code_bytes(case)
        known_cids = {glyph_codes[k : k + 2] for k in range(0, len(glyph_codes), 2)} if glyph_codes else set()
        type0 = _g(case, "corpus_case", "font_kind") == "type0"
        for i, change in enumerate(_g(case, "mutation", "changes", default=[]) or []):
            for key in ("new_operand_bytes_hex", "old_operand_bytes_hex"):
                data = _operand_bytes(change, key)
                if data is None:
                    continue
                pointer = f"/mutation/changes/{i}/{key}"
                for tok in _lex(data):
                    # text hidden in a hex field behind a non-string token: names and comments go through the same scans
                    if tok.kind not in (TokenKind.NAME, TokenKind.COMMENT):
                        continue
                    word = data[tok.start + 1 : tok.end].decode("latin-1")
                    if tok.kind is TokenKind.NAME and _RESOURCE_NAME.fullmatch(word):
                        continue
                    scan(pointer, word)
                    for n, match in enumerate(matchers):
                        if match(word):
                            res.violations.append(Violation("denylist_hit", acc.file, pointer, f"denylist entry #{n + 1} matched", acc.case_id))
                for payload in _string_payloads(data) or []:
                    if type0:
                        if any(payload[k : k + 2] not in known_cids for k in range(0, len(payload), 2)):
                            acc.u("type0_cid_unbound", pointer, "CIDs outside glyph_identity need the original show (rederive)")
                    else:
                        scan(pointer, payload.decode("latin-1"))
        for pointer in ("/probe/max_tier_1/detail", "/probe/max_tier_0/detail", "/growth_zone/gate_detail"):
            detail = _g(case, *pointer.split("/")[1:])
            if isinstance(detail, str) and not _ascii_printable(detail):
                acc.v("detail_not_ascii", pointer, "product detail fields are printable ASCII")
                counts["client_strings_left"] += 1
        for pointer, text in _free_text(case):
            if any(_is_cjk(ch) for ch in text):
                warnings.append({"file": acc.file, "pointer": pointer, "case_id": acc.case_id})
                counts["language_warnings"] += 1
        res.extend(acc.res)
    return res, counts, warnings


# --------------------------------------------------------------------------
# validate_batch
# --------------------------------------------------------------------------
def _dedupe(items: Iterable[Violation]) -> list[Violation]:
    seen: set[tuple] = set()
    out = []
    for v in items:
        key = (v.code, v.file, v.pointer, v.detail, v.case_id)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _case_file(case: dict) -> str:
    cid = _case_dir_name(case)
    return f"cases/{cid}/case_record.json" if cid else "cases.json"


_SCALAR_FIELDS = (
    ("class_id",),
    ("kind",),
    ("status",),
    ("case_id",),
    ("join_key",),
    ("source", "slug"),
    ("source", "provenance"),
    ("source", "lineage_id"),
    ("source", "producer_family"),
    ("source", "sha256"),
    ("source", "page_rotation"),
    ("corpus_case", "page_index"),
    ("corpus_case", "show_seq"),
    ("corpus_case", "expected_reason"),
)


def _scalar_view(case: dict) -> dict:
    """case with every field the batch-level checks use as a dict key or set member forced to a scalar.

    A list or dict there is a schema defect (reported from the original row); it must not be a TypeError that
    stops the report.  Nothing else changes, and the original case is never modified.
    """

    def scalar(value: object) -> object:
        return value if value is None or isinstance(value, (str, int, float, bool)) else None

    out = dict(case)
    for path in _SCALAR_FIELDS:
        node: Any = out
        for key in path[:-1]:
            sub = node.get(key) if isinstance(node, dict) else None
            if not isinstance(sub, dict):
                node = None
                break
            copy_ = dict(sub)
            node[key] = copy_
            node = copy_
        if isinstance(node, dict) and path[-1] in node:
            node[path[-1]] = scalar(node[path[-1]])
    return out


def _guarded(res: CheckResult, name: str, fn: Callable[[], Any], default: Any) -> Any:
    """Run one batch-level check; a crash is a check_error violation (fail closed), never a missing report."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - the report must survive any malformed shape
        kind = type(exc).__name__ if _is_builtin_exception(type(exc).__name__) else "an exception"
        res.violations.append(Violation("check_error", "", "", f"{kind} while running {name}"))
        return default


def validate_batch(batch_dir: Path, *, denylist: Iterable[str] | None = None) -> dict:
    """Run every check, never stopping early, and return the VALIDATION report."""
    root = Path(batch_dir)
    batch, load_violations = load_batch(root)
    res = CheckResult()
    res.violations += load_violations
    res.extend(_guarded(res, "check_artifacts", lambda: check_artifacts(root, batch), CheckResult()))
    case_schema = load_schema(SCHEMA_DIR / CASE_SCHEMA_NAME)
    parent_schema = load_schema(SCHEMA_DIR / PARENT_SCHEMA_NAME)
    if batch.parent is not None:
        res.violations += validate_instance(batch.parent, parent_schema, file="PARENT_SUMMARY.json")
    schema_bad: set[str] = set()
    for case in batch.cases:
        found = validate_instance(case, case_schema, file=_case_file(case))
        cid = _case_dir_name(case)
        res.violations += [dataclasses.replace(v, case_id=cid) for v in found]
        if found and cid:
            schema_bad.add(cid)
    batch = dataclasses.replace(batch, cases=[_scalar_view(c) for c in batch.cases])
    pre, prereg = _guarded(res, "check_pre_registration", lambda: check_pre_registration(batch), (CheckResult(), {}))
    res.extend(pre)
    res.extend(_guarded(res, "check_code_revision", lambda: check_code_revision(batch.cases, batch.parent), CheckResult()))
    phases_by_case: dict[str, dict[str, PhaseCheck]] = {}
    case_violations: dict[str, list[Violation]] = {}
    for case in batch.cases:
        cid = _case_dir_name(case)
        if cid is None:
            continue
        try:
            phases, part = recompute_phase_results(case, batch.records.get(cid, []))
        except Exception as exc:  # noqa: BLE001 - fail closed on any malformed shape
            if cid not in schema_bad:
                res.violations.append(Violation("check_error", _case_file(case), "", f"{type(exc).__name__} while checking this case", cid))
            continue
        phases_by_case[cid] = phases
        case_violations[cid] = part.violations
        res.extend(part)
    provisional = {}
    for case in batch.cases:
        cid = _case_dir_name(case)
        if cid in phases_by_case:
            provisional[cid] = _safe_status(case, phases_by_case[cid], "pass", prereg.get(cid, False), case_violations[cid])
    cal = _guarded(res, "check_calibration", lambda: check_calibration(batch.parent, batch.cases, phases_by_case, provisional, batch.records), CheckResult())
    res.extend(cal)
    cal_status = cal.info.get("status", "pass") if hasattr(cal, "info") else "pass"
    statuses: dict[str, str] = {}
    for case in batch.cases:
        cid = _case_dir_name(case)
        if cid not in phases_by_case:
            continue
        statuses[cid] = _safe_status(case, phases_by_case[cid], cal_status, prereg.get(cid, False), case_violations[cid])
        if case.get("status") != statuses[cid]:
            res.violations.append(
                Violation("status_mismatch", _case_file(case), "/status", f"recorded {_vocab(case.get('status'))}, recomputed {statuses[cid]}", cid)
            )
    _, lineage_violations = _guarded(res, "check_lineage", lambda: check_lineage(batch.cases), ({}, []))
    res.violations += lineage_violations
    recorded_statuses: dict[str, str] = {
        c["case_id"]: c["status"] for c in batch.cases if isinstance(c.get("case_id"), str) and isinstance(c.get("status"), str)
    }
    res.extend(_guarded(res, "check_parent", lambda: _check_parent(batch.parent, batch.cases, recorded_statuses, root), CheckResult()))
    deny = list(denylist) if denylist is not None else []
    red, counts, warnings = _guarded(
        res,
        "scan_redaction",
        lambda: scan_redaction(root, batch, denylist=deny),
        (CheckResult(), {"client_strings_left": 0, "machine_paths_left": 0, "language_warnings": 0}, []),
    )
    res.extend(red)
    matchers = _deny_matchers(deny)
    parent_summary = (
        _guarded(res, "recompute_parent_summary", lambda: recompute_parent_summary(batch.cases, recorded_statuses), {}) if batch.cases else {}
    )
    violations = _dedupe(_scrub_entry(v, matchers) for v in res.violations)
    unverifiable = _dedupe(_scrub_entry(v, matchers) for v in res.unverifiable)
    recomputed = {
        "phases": {cid: {p: {"result": pc.result, "reasons": list(pc.reasons)} for p, pc in ph.items()} for cid, ph in phases_by_case.items()},
        "statuses": statuses,
        "calibration": cal.info,
        "parent_summary": parent_summary,
    }
    return {
        "schema": "evidence-validation/1",
        "batch": _scrub_file(root.name),
        "ok": not violations,
        # unverifiable is the fixture-bound work only rederive can do (this validator never opens a PDF), so a clean
        # validate run on its own is not a clean bill: the pipeline is validate, then rederive.
        "pending_rederive": bool(unverifiable),
        # rederive refuses a report whose digest is not that of the cases.json it is about to measure
        "cases_json_sha256": _sha256_bytes((root / "cases.json").read_bytes()) if (root / "cases.json").is_file() else None,
        "violations": [dataclasses.asdict(v) for v in violations],
        "unverifiable": [dataclasses.asdict(v) for v in unverifiable],
        "language_warnings": [
            {"file": _scrub_file(w["file"]), "pointer": w["pointer"], "case_id": _show_id(w["case_id"]) if w["case_id"] else None}
            for w in warnings
        ],
        "redaction_scan": counts,
        "recomputed": _scrub_obj(recomputed, matchers),
    }


def _scrub_text(text: str, matchers: list[Callable[[str], bool]]) -> str:
    """Last line of defence: nothing non-ASCII, device-specific or denylisted leaves in a report."""
    if len(text) > 400 or not _ascii_printable(text):
        return "[detail withheld]"
    if any(pat.search(text) for _, pat in PATTERNS) or any(m(text) for m in matchers):
        return "[detail withheld]"
    return text


def _scrub_entry(v: Violation, matchers: list[Callable[[str], bool]]) -> Violation:
    clean = re.fullmatch(r"[A-Za-z0-9_.@:/#~-]*", v.pointer) and _scrub_text(v.pointer, matchers) == v.pointer
    pointer = v.pointer if clean else _digest(v.pointer)
    return Violation(
        v.code,
        _scrub_file(v.file),
        pointer,
        _scrub_text(v.detail, matchers),
        _show_id(v.case_id) if v.case_id is not None else None,
    )


def _scrub_obj(obj: object, matchers: list[Callable[[str], bool]]):
    if isinstance(obj, dict):
        return {(_show_id(k) if isinstance(k, str) and k.startswith("r2-") else _esc(k)): _scrub_obj(v, matchers) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_obj(v, matchers) for v in obj]
    if isinstance(obj, str):
        return obj if re.fullmatch(r"[A-Za-z0-9_.@:/# -]{0,160}", obj) and not _scrub_text(obj, matchers).startswith("[") else _digest(obj)
    return obj


def _safe_status(case: dict, phases: dict[str, PhaseCheck], cal_status: str, pre_registered: bool, case_violations: list[Violation]) -> str:
    try:
        return recompute_status(case, phases, calibration_status=cal_status, pre_registered=pre_registered, case_violations=case_violations)
    except Exception:  # noqa: BLE001 - a malformed case never earns a status
        return "insufficient_evidence"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _cmd_validate(args: argparse.Namespace) -> int:
    batch_dir = Path(args.batch_dir)
    deny_path = Path(args.denylist) if args.denylist else DEFAULT_DENYLIST
    notes = []
    denylist: list[str] = []
    if deny_path.is_file():
        denylist = deny_path.read_text(encoding="utf-8").splitlines()
    else:
        notes.append("denylist file absent; the denylist layer scanned nothing")
    report = validate_batch(batch_dir, denylist=denylist)
    report["notes"] = notes
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    for v in report["violations"]:
        print(f"{v['code']}\t{v['file']}\t{v['pointer']}\t{v['detail']}", file=sys.stderr)
    return 1 if report["violations"] else 0


def _cmd_find_show(args: argparse.Namespace) -> int:
    import fitz  # lazy: the validator itself never needs it

    from model.text_commit.fonts import DocumentFontRegistry
    from model.text_commit.replay import replay_page_streams

    doc = fitz.open(args.pdf)
    page = doc[args.page]
    replay = replay_page_streams([(x, doc.xref_stream(x)) for x in page.get_contents()])
    registry = DocumentFontRegistry(doc)
    rows = []
    for show in replay.shows:
        cap = registry.capability(page, show.font_resource) if show.font_resource else None
        cid_cap = getattr(cap, "cid", None)
        if cid_cap is not None:
            decoded = cid_cap.decode_show_bytes(show.decoded_bytes)
            decoded = decoded if isinstance(decoded, str) else ""
        else:
            decoded = show.decoded_bytes.decode("latin-1")
        rows.append(
            {
                "show_seq": show.seq,
                "operator": show.operator,
                "op_start": show.op_start,
                "op_end": show.op_end,
                "font_resource": show.font_resource,
                "decoded": decoded,
                "match": args.text in decoded,
            }
        )
    print(json.dumps(rows, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evidence_bundle", description="Validate a Grok-round evidence bundle.")
    sub = parser.add_subparsers(dest="command", required=True)
    val = sub.add_parser("validate", help="validate a batch directory and write VALIDATION json")
    val.add_argument("batch_dir")
    val.add_argument("--out", required=True)
    val.add_argument("--denylist", default=None)
    val.set_defaults(func=_cmd_validate)
    find = sub.add_parser("find-show", help="list the shows of one page whose decoded text contains --text")
    find.add_argument("--pdf", required=True)
    find.add_argument("--page", type=int, required=True)
    find.add_argument("--text", required=True)
    find.set_defaults(func=_cmd_find_show)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
