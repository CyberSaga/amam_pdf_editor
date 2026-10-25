"""Tests for ``scripts/evidence_rederive.py`` (I0c, SPEC B).

The re-derivation half of the Grok-round ingest
(``plans/true-text-frontier-loop.md`` section 2 steps 5-7).  Every fixture is
synthetic and built at run time under ``tmp_path``; the corpus registry is
injected, so no test touches ``test_files/``.

``_experiment_record`` and ``_product_record`` build HONEST bundle records.
They are the only place this file computes truth, and they do it with the
product functions (``prepare``, ``_advance``/``advance_points``,
``map_text_quad_to_visual``, ``growth_probe_regions``).  Test 0 and the
experiment base prove that builder and ``rederive_case`` agree before any
forged shape is judged, so a reject can only come from the forgery.

Machine-path samples are never written as literals (device guard).
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit import transforms, verify  # noqa: E402
from model.text_commit.engine import TieredCommitEngine  # noqa: E402
from model.text_commit.fonts import DocumentFontRegistry  # noqa: E402
from model.text_commit.patch import kern_for_displacement  # noqa: E402
from model.text_commit.pdf_lexer import TokenKind, lex_content_stream  # noqa: E402
from model.text_commit.plan import PlanRejection, _grown_verify_bbox  # noqa: E402
from model.text_commit.plan import _advance as _plan_advance  # noqa: E402
from model.text_commit.replay import replay_page_streams  # noqa: E402
from scripts import evidence_bundle as eb  # noqa: E402
from scripts import evidence_rederive as rd  # noqa: E402
from scripts.hooks.pre_commit_device_guard import PATTERNS  # noqa: E402
from test_scripts import type0_fixture_builder as tb  # noqa: E402

PUBLIC_LIST = ROOT / "test_scripts" / "fixtures" / "public_corpus_sha256.json"
BRIEF = ROOT / "plans" / "grok-briefs" / "brief-v2.md"
ACC = ROOT / "test_scripts" / "test_text_commit_real_corpus_acceptance.py"
SYN_CALLABLE = "test_scripts.type0_fixture_builder.build_identity_h_fixture"
SYN_KWARGS = {"text": "你好世界", "rotate": 270, "tail_text": "後綴"}
SIX_ORACLES = (
    "assert_target_stream_changed_only_within",
    "assert_wrapper_bytes_unchanged",
    "assert_show_and_operator_counts_equal",
    "assert_neighbour_glyphs_unchanged",
    "assert_growth_zone_was_blank",
    "assert_glyph_identity",
)


# --------------------------------------------------------------------------
# generic helpers
# --------------------------------------------------------------------------
def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _box(rect) -> list[float]:
    return [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])]


def _cids(data: bytes) -> tuple[int, ...]:
    return tuple(int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data), 2))


def _op_count(doc: fitz.Document, page: fitz.Page) -> int:
    total = 0
    for xref in page.get_contents():
        total += sum(1 for t in lex_content_stream(doc.xref_stream(xref)) if t.kind is TokenKind.OPERATOR)
    return total


def _locate(mpage: fitz.Page, show, frame, needle: str, *, near: tuple[float, float] | None = None):
    """Texttrace match of ``needle`` nearest to the show origin (or to ``near``)."""
    want = fitz.Point(show.origin_user) * frame.base if near is None else fitz.Point(near)
    best = None
    for trace in mpage.get_texttrace():
        full = "".join(chr(c[0]) for c in trace["chars"])
        i = full.find(needle)
        while i >= 0:
            chars = trace["chars"][i : i + len(needle)]
            rect = fitz.Rect(chars[0][3])
            for c in chars[1:]:
                rect |= fitz.Rect(c[3])
            dist = abs(fitz.Point(chars[0][2]) - want)
            if best is None or dist < best[0]:
                best = (dist, tuple(fitz.Point(chars[0][2])), tuple(rect))
            i = full.find(needle, i + 1)
    assert best is not None, needle
    return best


def _ts_of(show, replay) -> dict:
    wrappers = []
    for w in replay.wrappers_for(show):
        wrappers.append(
            {
                "kind": w.operator,
                "tag": w.tag,
                "class_slug": "oc_layer_visible_default",
                "props_kind": w.props_kind,
                "props_name": w.props_name,
                "props_keys": list(w.props_dict_keys),
                "structelem_keys": None,
                "stream_xref": w.stream_xref,
                "start": 0,
                "end": w.open_op_end,
            }
        )
    return {
        "Tf": {"resource": show.font_resource, "size": show.font_size},
        "Tm": list(show.tm),
        "CTM": list(show.ctm),
        "det_sign": "+",
        "Tz": show.hscale,
        "Tc": show.char_spacing,
        "Tw": show.word_spacing,
        "Ts": show.rise,
        "TL": show.leading,
        "Tr": show.render_mode,
        "fill_colour_op": {"op": None, "operands_raw": None, "is_pattern": False},
        "stroke_colour_op": {"op": None, "operands_raw": None, "is_pattern": False},
        "line_width": None,
        "extgstate_names": list(show.extgstate_names),
        "wrapper_stack": wrappers,
        "q_depth": show.gs_depth,
        "in_bt": show.in_bt,
        "origin_user": list(show.origin_user),
        "origin_reliable": show.origin_reliable,
    }


# --------------------------------------------------------------------------
# corpus scene: a fixture written under tmp_path/test_files and registered
# --------------------------------------------------------------------------
@dataclass
class Scene:
    tmp: Path
    slug: str
    path: Path
    rel: str
    data: bytes
    sha: str
    registry: object
    provenance: str


def _scene(
    tmp_path: Path,
    slug: str = "fx-a",
    provenance: str = "public",
    *,
    text: str = tb.CJK_TEXT,
    rotate: int = 270,
    tail: str | None = tb.TAIL_TEXT,
    prepare=None,
    register: bool = True,
    fontsize: float = 12.0,
    origin: tuple[float, float] = (72.0, 700.0),
) -> Scene:
    fx = tb.build_identity_h_fixture(text, rotate=rotate, tail_text=tail, fontsize=fontsize, origin=origin)
    if prepare is not None:
        prepare(fx)
    folder = tmp_path / "test_files"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.pdf"
    fx.doc.save(str(path))
    fx.doc.close()
    data = path.read_bytes()
    sha = _sha(data)
    rel = f"test_files/{slug}.pdf"
    entries = (rd.RegistryEntry(slug, rel, sha, provenance, slug),) if register else ()
    return Scene(tmp_path, slug, path, rel, data, sha, rd.CorpusRegistry(root=tmp_path, entries=entries), provenance)


class Truth:
    """What the product itself says about one show of one fixture file."""

    def __init__(self, path: Path, show_seq: int = 0, page_index: int = 0) -> None:
        self.path = path
        self.page_index = page_index
        self.doc = fitz.open(str(path))
        self.page = self.doc[page_index]
        self.replay = replay_page_streams([(x, self.doc.xref_stream(x)) for x in self.page.get_contents()])
        self.show = self.replay.shows[show_seq]
        self.stream = self.doc.xref_stream(self.show.stream_xref)
        self.cap = DocumentFontRegistry(self.doc).capability(self.page, self.show.font_resource)
        self.text = self.cap.cid.decode_show_bytes(self.show.decoded_bytes)
        meas = fitz.open("pdf", self.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))
        mpage = meas[page_index]
        self.frame = transforms.page_visual_frame_or_none(mpage)
        pix = mpage.get_pixmap(dpi=verify._VERIFY_DPI)
        self.meta = (pix.width, pix.height, pix.stride, pix.n)
        _, origin_raw, bbox_raw = _locate(mpage, self.show, self.frame, self.text)
        # the before page's whole texttrace glyph count, flattened the way the brief's pairing rule does
        self.page_glyphs = sum(len(span["chars"]) for span in mpage.get_texttrace())
        self.origin_raw = origin_raw
        self.bbox_raw = bbox_raw
        self.origin_vis = tuple(fitz.Point(origin_raw) * self.frame.quarter_turn)
        self.bbox_vis = tuple(fitz.Rect(bbox_raw) * self.frame.quarter_turn)
        meas.close()
        linear = transforms.combined_linear(self.show.tm, self.show.ctm)
        self.trm = float(math.hypot(linear[0], linear[1]))
        self.th = self.show.hscale / 100.0

    def adv(self, codes: bytes) -> float:
        return self.cap.cid.advance_points(_cids(codes), self.show.font_size, self.show.char_spacing)

    def source_kind(self, *code_sets: bytes) -> str:
        for codes in code_sets:
            for cid in _cids(codes):
                if not any(a <= cid <= b for a, b, _ in self.cap.cid.w_records):
                    return "DW"
        return "W"

    def close(self) -> None:
        self.doc.close()


def _probe_dict(scene_path: Path, tr: Truth, replacement: str, max_tier: int):
    doc = fitz.open(str(scene_path))
    eng = TieredCommitEngine(doc, max_tier=max_tier)
    res = eng.prepare(
        doc[tr.page_index],
        target_text=tr.text,
        replacement_text=replacement,
        expected_origin=tr.origin_vis,
        target_bbox=tr.bbox_vis,
    )
    if isinstance(res, PlanRejection):
        out = {"result": "rejected", "tier": None, "reason": res.reason, "detail": res.detail, "exception_type": None, "prepared": None}
    else:
        out = {
            "result": "prepared",
            "tier": int(res.tier),
            "reason": None,
            "detail": None,
            "exception_type": None,
            "prepared": {
                "stream_xref": res.stream_xref,
                "replacement_start": res.replacement.start,
                "replacement_end": res.replacement.end,
                "binding_op_start": res.binding.show.op_start,
                "binding_op_end": res.binding.show.op_end,
                "font_xref": res.font_xref,
                "source_advance": res.source_advance,
                "replacement_advance": res.replacement_advance,
                "kern_adjustment": res.kern_adjustment,
                "verify_bbox_page": None if res.verify_bbox_page is None else _box(res.verify_bbox_page),
                "background_bbox_page": None if res.background_bbox_page is None else _box(res.background_bbox_page),
            },
        }
    return out, doc, eng, res


def _glyphs(replacement: str, codes: bytes | None = None) -> list[dict]:
    codes = tb.encode_cids(replacement) if codes is None else codes
    out = []
    for i, ch in enumerate(replacement):
        gid = int.from_bytes(codes[2 * i : 2 * i + 2], "big")
        out.append(
            {
                "index": i,
                "char": ch,
                "is_space": ch.isspace(),
                "code_bytes_hex": codes[2 * i : 2 * i + 2].hex().upper(),
                "gid_after": gid,
                "has_outline": True,
                "consistency": None,
                "gid_equals_consistency": None,
                "independent_leg": {"kind": "cid_tounicode", "value": ch, "equals_char": True, "gid": gid, "gid_equals_after": True},
            }
        )
    return out


def _source_block(*, provenance: str, sha: str, rel: str | None, builder=None, slug="fx-a", rotation: int = 270, pages: int = 1) -> dict:
    return {
        "slug": slug,
        "relative_path": rel,
        "provenance": provenance,
        "sha256": sha,
        "sha256_after_run": sha,
        "before_pdf_sha256": sha,
        "lineage_id": slug,
        "lineage_reason": "single document",
        "producer_family": "fixture-family",
        "single_producer_family": True,
        "producer": None,
        "creator": None,
        "page_count": pages,
        "page_rotation": rotation,
        "synthetic_builder": builder,
    }


def _advance_block(tr: Truth, *, adv_old, adv_new, source, k_written, k_sum=0.0, spaces=0, n_old=4, n_new=5) -> dict:
    tfs = tr.show.font_size
    disp = adv_old - adv_new
    has_k = k_written is not None
    eng = kern_for_displacement(tr.show, disp) if has_k else None
    tol = max(1e-9 * tfs, 1e-9)
    hand = 1000.0 * (adv_new - adv_old) / tfs
    return {
        "K_written": k_written,
        "K_sum": k_sum if has_k else None,
        "K_disp_engine": eng,
        "K_disp_hand": hand if has_k else None,
        "abs_diff_written_vs_sum_engine": abs(k_written - (k_sum + eng)) if has_k else None,
        "abs_diff_engine_hand": abs(eng - hand) if has_k else None,
        "displacement": disp,
        "adv_old_text_space": adv_old,
        "adv_new_text_space": adv_new,
        "growth_pt": max(0.0, adv_new - adv_old) * tr.th * tr.trm * tr.frame.user_unit,
        "advance_tolerance": tol,
        "Tfs": tfs,
        "Th": tr.th,
        "Tc": tr.show.char_spacing,
        "Tw": tr.show.word_spacing,
        "char_count_old": n_old,
        "char_count_new": n_new,
        "space_count": spaces,
        "advance_source": source,
        "advance_function": "IdentityHCidCapability.advance_points",
        "internal_kerns_dropped": [],
        "border_kerns_byte_identical": None,
    }


def _target_block(tr: Truth, *, after_raw, after_vis, verify_vis) -> dict:
    show = tr.show
    return {
        "stream_xref": show.stream_xref,
        "op_start": show.op_start,
        "op_end": show.op_end,
        "operator": show.operator,
        "string_kind": show.string_kind,
        "array_item_count": show.array_item_count,
        "item_range": None,
        "byte_range_in_item": None,
        "font_xref": tr.cap.font_xref,
        "basefont_raw": "DroidSansFallback",
        "font_subtype": "Type0",
        "font_embedding": "FontFile2",
        "font_file3_subtype": None,
        "encoding": "Identity-H",
        "has_differences": False,
        "tounicode": "present",
        "symbolic_flag": None,
        "descendant_subtype": "CIDFontType2",
        "origin_recipe": "texttrace_chars0_x_quarter_turn/v1",
        "expected_origin_visual": list(tr.origin_vis),
        "target_bbox_visual": _box(tr.bbox_vis),
        "target_bbox_raw": _box(tr.bbox_raw),
        "after_bbox_visual": after_vis,
        "after_bbox_raw": after_raw,
        "verify_bbox_visual": verify_vis,
        "trm_scale": tr.trm,
        "user_unit": tr.frame.user_unit,
        "no_source_match_subclass": None,
        "replacement_provenance": "chars_already_drawn_by_font",
        "source_decode": {"latin1": None, "latin1_sha256": None, "independent": None, "independent_sha256": _sha(tr.text), "leg": "cid_tounicode", "agrees": True},
    }


def _growth_block_off() -> dict:
    return {
        "applicable": False,
        "direction": None,
        "region_visual": None,
        "region_dict": None,
        "background_bbox_visual": None,
        "background_rgb": None,
        "probe_regions_px_96dpi": None,
        "probe_regions_failed": None,
        "raster_proof": None,
        "gate_detail": None,
        "before_glyph_bboxes_intersecting": None,
        "before_drawings_intersecting_bbox": None,
        "before_drawings_not_provably_clear": None,
        "stroke_proof": None,
        "before_images_intersecting": None,
        "sh_operator_present": None,
        "files": [],
    }


def _quad(tr: Truth, adv_old: float):
    show = tr.show
    return transforms.map_text_quad_to_visual(
        tr.page, show.tm, show.ctm, (0.0, -0.35 * show.font_size, adv_old * tr.th, show.font_size), frame=tr.frame
    )


def _growth_block(tr: Truth, verify_vis, adv_old: float) -> dict:
    """The growth_zone object of an honest record whose verify box is ``verify_vis``."""
    target = tuple(tr.bbox_vis)
    rect = verify._growth_zone_rect(target, tuple(verify_vis))
    extents = (
        ("right", verify_vis[2] - target[2]),
        ("left", target[0] - verify_vis[0]),
        ("down", verify_vis[3] - target[3]),
        ("up", target[1] - verify_vis[1]),
    )
    direction = max(extents, key=lambda p: p[1])[0]
    regions = verify.growth_probe_regions(target, tuple(verify_vis), tr.meta)
    meas = fitz.open("pdf", tr.doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))
    glyphs = verify.count_growth_zone_glyphs(meas[tr.page_index], target_bbox=target, verify_bbox=tuple(verify_vis))
    meas.close()
    return {
        "applicable": True,
        "direction": direction,
        "region_visual": _box(rect),
        "region_dict": _box(rect * ~tr.frame.quarter_turn),
        "background_bbox_visual": _box(_quad(tr, adv_old)),
        "background_rgb": [1.0, 1.0, 1.0],
        "probe_regions_px_96dpi": [list(r) for r in regions],
        "probe_regions_failed": 0,
        "raster_proof": "pass",
        "gate_detail": None,
        "before_glyph_bboxes_intersecting": glyphs,
        "before_drawings_intersecting_bbox": 0,
        "before_drawings_not_provably_clear": 0,
        "stroke_proof": "not_needed",
        "before_images_intersecting": 0,
        "sh_operator_present": False,
        "files": ["render-growthstrip-before-6x.png"],
    }


def _case_shell(tr: Truth, *, class_id: str, kind: str, variant: str, source: dict, replacement: str, expected_reason, expected_outcome, expected_tier, original=None) -> dict:
    cid = f"r2-{class_id}-{source['sha256'][:8]}-p{tr.page_index}-s{tr.show.seq}-{variant}1"
    return {
        "schema_version": "true-text-case/2",
        "brief_revision": 2,
        "case_id": cid,
        "join_key": f"{source['slug']}/p{tr.page_index}/show{tr.show.seq}",
        "class_id": class_id,
        "subclass": None,
        "kind": kind,
        "source": source,
        "corpus_case": {
            "page_index": tr.page_index,
            "show_seq": tr.show.seq,
            "original": original,
            "original_sha256": _sha(tr.text),
            "replacement": replacement,
            "replacement_sha256": _sha(replacement),
            "font_resource": tr.show.font_resource,
            "basefont": "DroidSansFallback",
            "font_kind": "type0",
            "expected_outcome": expected_outcome,
            "expected_reason": expected_reason,
            "expected_tier": expected_tier,
            "expected_tj_compensation": None,
        },
        "neighbours": {
            "pairing_rule": "texttrace_order_origin_match/v1",
            "glyphs_total": tr.page_glyphs - len(tr.text),
            "target_glyphs_before": len(tr.text),
            "records_file": f"cases/{cid}/neighbours.json",
        },
    }


def _honest_records(case: dict) -> list[dict]:
    """One record per before glyph: the target run first, then every other glyph of the page, unmoved."""
    nb = case["neighbours"]
    n_old, rest = nb["target_glyphs_before"], nb["glyphs_total"]
    out = [{"role": "target", "trace_index_before": j, "trace_index_after": j} for j in range(n_old)]
    out += [{"role": "untouched", "trace_index_before": j, "trace_index_after": j} for j in range(n_old, n_old + rest)]
    return out


def _write_records(batch: Path, case: dict, records: list[dict] | None = None) -> None:
    """Write ``cases/<case_id>/neighbours.json`` (honest unless ``records`` is given) for a record that has a neighbours block."""
    cid = case.get("case_id") if isinstance(case, dict) else None
    if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", cid) or not isinstance(case.get("neighbours"), dict):
        return
    folder = batch / "cases" / cid
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "neighbours.json").write_text(json.dumps(_honest_records(case) if records is None else records), encoding="utf-8")


def _probe_block(p1: dict, p0: dict, *, committed: dict | None) -> dict:
    return {
        "engine": "TieredCommitEngine",
        "handle": "fresh_no_texttrace",
        "max_tier_1": p1,
        "max_tier_0": p0,
        "binding_matches_target": None,
        "commit": committed or {"attempted": False, "status": None, "tier": None, "font_actions": []},
    }


def _changes(tr: Truth, start: int, end_old: int, new_op: bytes) -> list[dict]:
    new_stream = tr.stream[:start] + new_op + tr.stream[end_old:]
    kinds = [t.kind.name for t in lex_content_stream(new_op) if t.kind is not TokenKind.WHITESPACE]
    return [
        {
            "stream_xref": tr.show.stream_xref,
            "start": start,
            "end_old": end_old,
            "end_new": start + len(new_op),
            "token_aligned": True,
            "old_operand_bytes_hex": tr.stream[start:end_old].hex().upper(),
            "old_operand_sha256": _sha(tr.stream[start:end_old]),
            "new_operand_bytes_hex": new_op.hex().upper(),
            "new_operand_token_kinds": kinds,
            "old_stream_sha256": _sha(tr.stream),
            "new_stream_sha256": _sha(new_stream),
        }
    ]


def _common_counts(tr: Truth) -> dict:
    return {
        "before": _ts_of(tr.show, tr.replay),
        "after": None,
        "target_equal": None,
        "nontarget_shows_equal": None,
        "show_count_before": len(tr.replay.shows),
        "show_count_after": None,
        "operator_count_before": _op_count(tr.doc, tr.page),
        "operator_count_after": None,
    }


def _product_record(scene: Scene, replacement: str, *, class_id="F30B", kind="positive", variant="eq", expected_reason=None, provenance=None, builder=None, commit_status="committed", show_seq=0, page_index=0) -> dict:
    """An honest product-path record: probe at max_tier 1 and 0, commit when prepared."""
    tr = Truth(scene.path, show_seq, page_index)
    try:
        p1, d1, _e1, res1 = _probe_dict(scene.path, tr, replacement, 1)
        p0, d0, _e0, _res0 = _probe_dict(scene.path, tr, replacement, 0)
        d1.close()
        d0.close()
        prov = provenance or scene.provenance
        src = _source_block(provenance=prov, sha=scene.sha, rel=None if prov in ("proprietary", "synthetic") else scene.rel, builder=builder, slug=scene.slug, rotation=tr.page.rotation, pages=tr.doc.page_count)
        outcome = "refuse" if p1["result"] == "rejected" else ("commit_tier1" if p1["tier"] == 1 else "commit_tier0")
        case = _case_shell(
            tr, class_id=class_id, kind=kind, variant=variant, source=src, replacement=replacement,
            expected_reason=expected_reason, expected_outcome=outcome, expected_tier=p1["tier"],
            original=tr.text if prov in ("public", "synthetic") else None,
        )
        old_codes = tr.show.decoded_bytes
        new_codes = tb.encode_cids(replacement)
        case["target"] = _target_block(tr, after_raw=None, after_vis=None, verify_vis=None)
        case["probe"] = _probe_block(p1, p0, committed=None)
        case["text_state"] = _common_counts(tr)
        case["growth_zone"] = _growth_block_off()
        case["glyph_identity"] = []
        case["mutation"] = None
        if p1["result"] == "prepared":
            prep = p1["prepared"]
            tier = p1["tier"]
            new_op = bytes(res1.replacement.replacement_bytes)
            new_codes = b"".join(rd._payloads(new_op) or [])  # the product's own CIDs, whatever the font
            adv_old, adv_new = tr.adv(old_codes), tr.adv(new_codes)
            src_kind = tr.source_kind(old_codes, new_codes)
            k_written = prep["kern_adjustment"] if tier == 1 else None
            case["glyph_identity"] = _glyphs(replacement, new_codes)
            case["probe"] = _probe_block(p1, p0, committed={"attempted": True, "status": commit_status, "tier": tier, "font_actions": []})
            case["mutation"] = {
                "path": "product_commit",
                "method_id": "M2_COMMIT",
                "variable_changed": "replacement operand",
                "splice_kind": "whole_operator" if tier == 1 else "string_token",
                "changes": _changes(tr, prep["replacement_start"], prep["replacement_end"], new_op),
                "advance": _advance_block(tr, adv_old=adv_old, adv_new=adv_new, source=src_kind, k_written=k_written, n_new=len(replacement), n_old=len(old_codes) // 2),
                "other_xrefs_changed_live": [],
                "other_xrefs_changed_semantic": [],
                "other_xrefs_reserialized": [],
                "wrapper_bytes_unchanged": None,
                "new_objects_after_save": [],
                "new_objects_all_xref": True,
                "saved_with": "saveIncr",
                "output_sha256": _sha("output"),
            }
            if tier == 1:
                case["target"]["verify_bbox_visual"] = prep["verify_bbox_page"]
                case["growth_zone"] = _growth_block(tr, tuple(prep["verify_bbox_page"]), adv_old)
                case["growth_zone"]["background_bbox_visual"] = prep["background_bbox_page"]
        return case
    finally:
        tr.close()


def _experiment_record(
    scene: Scene,
    *,
    replacement: str = tb.REPLACEMENT_LONGER,
    class_id: str = "F30B",
    kind: str = "positive",
    variant: str = "grow",
    path: str = "experiment",
    method_id: str = "E_KERN",
    splice_kind: str = "whole_operator",
    k_sign: float = 1.0,
    understate: float = 0.0,
    provenance: str | None = None,
    builder=None,
    new_op: bytes | None = None,
    k_sum: float = 0.0,
) -> dict:
    """An honest experiment record: the splice is really applied, saved and re-measured.

    ``k_sum`` is a FORGED internal-kern sum: the record then claims ``K_written = K_sum + K_disp_engine`` and
    writes that K token, so it is internally consistent and only a re-measurement can tell.
    """
    tr = Truth(scene.path)
    try:
        p1, d1, _e1, _r1 = _probe_dict(scene.path, tr, replacement, 1)
        p0, d0, _e0, _r0 = _probe_dict(scene.path, tr, replacement, 0)
        d1.close()
        d0.close()
        prov = provenance or scene.provenance
        src = _source_block(provenance=prov, sha=scene.sha, rel=None if prov in ("proprietary", "synthetic") else scene.rel, builder=builder, slug=scene.slug, rotation=tr.page.rotation, pages=tr.doc.page_count)
        case = _case_shell(
            tr, class_id=class_id, kind=kind, variant=variant, source=src, replacement=replacement,
            expected_reason=p1["reason"], expected_outcome="refuse", expected_tier=None,
            original=tr.text if prov in ("public", "synthetic") else None,
        )
        old_codes, new_codes = tr.show.decoded_bytes, tb.encode_cids(replacement)
        adv_old = tr.adv(old_codes)
        adv_new = tr.adv(new_codes) - understate
        k_eng = kern_for_displacement(tr.show, adv_old - adv_new)
        k_written = k_sign * k_eng + k_sum
        if new_op is None:
            new_op = f"[<{new_codes.hex().upper()}> {k_written:.6f}] TJ".encode("ascii")
        start, end_old = tr.show.op_start, tr.show.op_end
        # really apply: path-opened scratch, update_stream, saveIncr, reopen
        folder = scene.tmp / "truthwork"
        folder.mkdir(parents=True, exist_ok=True)
        scratch_path = folder / f"truth-{scene.slug}-{class_id}-{variant}.pdf"
        scratch_path.write_bytes(scene.data)
        scratch = fitz.open(str(scratch_path))
        new_stream = tr.stream[:start] + new_op + tr.stream[end_old:]
        scratch.update_stream(tr.show.stream_xref, new_stream)
        scratch.saveIncr()
        scratch.close()
        after = fitz.open(str(scratch_path))
        apage = after[tr.page_index]
        replay2 = replay_page_streams([(x, after.xref_stream(x)) for x in apage.get_contents()])
        show2 = replay2.shows[tr.show.seq]
        ameas = fitz.open("pdf", after.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))
        text2 = DocumentFontRegistry(after).capability(apage, show2.font_resource).cid.decode_show_bytes(show2.decoded_bytes)
        _, _, araw = _locate(ameas[tr.page_index], show2, tr.frame, text2)
        ameas.close()
        after_vis = tuple(fitz.Rect(araw) * tr.frame.quarter_turn)
        text_state = _common_counts(tr)
        text_state["after"] = _ts_of(show2, replay2)
        text_state["target_equal"] = True
        text_state["nontarget_shows_equal"] = True
        text_state["show_count_after"] = len(replay2.shows)
        text_state["operator_count_after"] = _op_count(after, apage)
        after.close()
        tol = max(1e-9 * tr.show.font_size, 1e-9)
        growing = adv_new - adv_old > tol
        if growing:
            verify_vis = _grown_verify_bbox(tr.page, tr.show, tuple(tr.bbox_vis), max(0.0, adv_new - adv_old) * tr.th, frame=tr.frame)
        else:
            verify_vis = tuple(tr.bbox_vis)
        src_kind = tr.source_kind(old_codes, new_codes)
        case["target"] = _target_block(tr, after_raw=_box(araw), after_vis=_box(after_vis), verify_vis=_box(verify_vis))
        case["probe"] = _probe_block(p1, p0, committed=None)
        case["text_state"] = text_state
        case["glyph_identity"] = _glyphs(replacement)
        case["growth_zone"] = _growth_block(tr, verify_vis, adv_old) if growing else _growth_block_off()
        case["mutation"] = {
            "path": path,
            "method_id": method_id,
            "variable_changed": "replacement operand",
            "splice_kind": splice_kind,
            "changes": _changes(tr, start, end_old, new_op),
            "advance": _advance_block(tr, adv_old=adv_old, adv_new=adv_new, source=src_kind, k_written=k_written, k_sum=k_sum, n_new=len(replacement), n_old=len(old_codes) // 2),
            "other_xrefs_changed_live": [],
            "other_xrefs_changed_semantic": [],
            "other_xrefs_reserialized": [],
            "wrapper_bytes_unchanged": None,
            "new_objects_after_save": [],
            "new_objects_all_xref": True,
            "saved_with": "saveIncr",
            "output_sha256": _sha(scratch_path.read_bytes()),
        }
        return case
    finally:
        tr.close()


def _full_oracles(fail: str | None = None) -> dict:
    out = {}
    for name in SIX_ORACLES:
        if name == fail:
            out[name] = lambda ctx: "forced failure detail"
        else:
            out[name] = lambda ctx: None
    return out


def _run(case, scene, tmp_path, *, oracles=None, registry=None, records=None):
    batch = tmp_path / "batch"
    batch.mkdir(exist_ok=True)
    _write_records(batch, case, records)
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return rd.rederive_case(case, batch, registry if registry is not None else scene.registry, oracles=oracles, work_dir=work)


def _fields(result) -> list[str]:
    return [d.field for d in result.divergences]


def _edit(case: dict, *edits) -> dict:
    out = copy.deepcopy(case)
    for pointer, value in edits:
        cur = out
        toks = pointer.strip("/").split("/")
        for tok in toks[:-1]:
            cur = cur[int(tok)] if isinstance(cur, list) else cur[tok]
        last = toks[-1]
        if isinstance(cur, list):
            cur[int(last)] = value
        else:
            cur[last] = value
    return out


@pytest.fixture
def open_spy(monkeypatch):
    calls: list[str] = []
    real = fitz.open

    def spy(*args, **kwargs):
        first = args[0] if args else kwargs.get("filename")
        calls.append(str(first))
        return real(*args, **kwargs)

    monkeypatch.setattr(fitz, "open", spy)
    return calls


def _no_bundle_open(calls: list[str], batch: Path) -> None:
    bad = [c for c in calls if str(batch) in c or "candidates" in c]
    assert not bad, bad


# ==========================================================================
# 0. honest bases
# ==========================================================================
def test_honest_product_row_rederives_clean(tmp_path):
    """T0 equal-advance product row: the proven-clean base of every reject below."""
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    assert case["probe"]["max_tier_1"]["tier"] == 0  # the record is the Tier 0 shape
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.divergences == []
    assert res.quarantine == []
    assert res.at_head["committed"] is True
    assert res.at_head["max_tier_1"]["tier"] == 0
    assert res.provenance_verified is True
    assert res.resolved_slug == "fx-a"
    assert set(res.oracles_run) == set(SIX_ORACLES)
    assert all(v is None for v in res.oracles_run.values())
    assert res.remeasured["adv_old"] == pytest.approx(48.0)
    assert res.remeasured["adv_new"] == pytest.approx(48.0)
    json.dumps(asdict(res))  # JSON-clean: plain floats, lists and strings only
    # both layers agree on the honest Tier 0 row: a Tier 0 PreparedEdit carries 0.0 advances, the record carries 48.0
    assert case["probe"]["max_tier_1"]["prepared"]["source_advance"] == 0.0
    assert case["mutation"]["advance"]["adv_old_text_space"] == pytest.approx(48.0)
    assert "product_advance_mismatch" not in {v.code for v in eb.check_cross_field(case).violations}


def test_honest_experiment_row_rederives_clean(tmp_path):
    """E_KERN growth on a tail-free page: the proven-clean base of every experiment reject."""
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    assert case["growth_zone"]["applicable"] is True
    assert case["probe"]["max_tier_1"]["result"] == "prepared"  # product commits this one
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.divergences == []
    assert res.remeasured["adv_new"] == pytest.approx(60.0)
    assert res.remeasured["K_disp_engine"] == pytest.approx(1000.0)
    assert res.oracles_run.get("assert_growth_zone_was_blank") is None
    json.dumps(asdict(res))


def test_honest_tier1_product_row_rederives_clean(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _product_record(scene, tb.REPLACEMENT_LONGER, variant="grow")
    assert case["probe"]["max_tier_1"]["tier"] == 1
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.at_head["committed"] is True
    assert res.remeasured["K_written"] == pytest.approx(1000.0)


def test_tier1_product_row_agrees_with_the_built_in_growth_oracle(tmp_path):
    """On a real Tier 1 commit the built-in oracle sees the product's own quad and verify box: no false failure."""
    scene = _scene(tmp_path, tail=None)
    case = _product_record(scene, tb.REPLACEMENT_LONGER, variant="grow")
    oracles = _full_oracles()
    oracles["assert_growth_zone_was_blank"] = rd.assert_growth_zone_was_blank
    res = _run(case, scene, tmp_path, oracles=oracles)
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.oracles_run["assert_growth_zone_was_blank"] is None


def test_registry_file_is_never_modified(tmp_path):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    _run(case, scene, tmp_path, oracles=_full_oracles())
    assert scene.path.read_bytes() == scene.data


# ==========================================================================
# 1. source resolution
# ==========================================================================
def test_rederive_ignores_bundle_before_pdf(tmp_path, open_spy):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    honest = _run(case, scene, tmp_path, oracles=_full_oracles())
    cdir = tmp_path / "batch" / "candidates" / case["case_id"]
    cdir.mkdir(parents=True)
    doctored = bytearray(scene.data)
    doctored[-5] ^= 0xFF
    (cdir / "before.pdf").write_bytes(bytes(doctored))
    del open_spy[:]
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert "before_pdf_mismatch" in res.quarantine
    assert res.remeasured == honest.remeasured
    assert res.at_head == honest.at_head
    _no_bundle_open(open_spy, tmp_path / "batch")


def test_matching_before_pdf_is_hashed_and_still_never_opened(tmp_path, open_spy):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    cdir = tmp_path / "batch" / "candidates" / case["case_id"]
    cdir.mkdir(parents=True)
    (cdir / "before.pdf").write_bytes(scene.data)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == []
    _no_bundle_open(open_spy, tmp_path / "batch")


def test_case_id_with_path_parts_never_steers_a_hash_read(tmp_path, monkeypatch):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    (tmp_path / "batch" / "candidates").mkdir(parents=True)
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "before.pdf").write_bytes(b"not the fixture")
    hostile = _edit(case, ("/case_id", "../../outside"))  # batch/candidates/../../outside == tmp_path/outside
    reads: list[str] = []
    real = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: reads.append(str(self)) or real(self))
    res = _run(hostile, scene, tmp_path, oracles=_full_oracles())
    assert not [r for r in reads if "outside" in r], reads
    assert "before_pdf_mismatch" not in res.quarantine
    # twin: without the case-id rule the same layout is read (so the assertion above is not vacuous)
    monkeypatch.setattr(rd, "_CASE_DIR_RE", re.compile(r".*"))
    res = _run(hostile, scene, tmp_path, oracles=_full_oracles())
    assert [r for r in reads if "outside" in r]
    assert "before_pdf_mismatch" in res.quarantine


def test_relative_path_cannot_climb_into_bundle(tmp_path, open_spy):
    """test_files/../<batch>/candidates/<id>/before.pdf passes the schema pattern and must open nothing."""
    scene = _scene(tmp_path, register=False)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    cdir = tmp_path / "batch" / "candidates" / case["case_id"]
    cdir.mkdir(parents=True)
    (cdir / "before.pdf").write_bytes(scene.data)  # matching sha: the only defence is the path rule
    climb = f"test_files/../batch/candidates/{case['case_id']}/before.pdf"
    assert re.match(r"^test_files/[^:\\]+\.pdf$", climb)
    case = _edit(case, ("/source/relative_path", climb))
    del open_spy[:]
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert "provenance_unverified" in res.quarantine
    assert "before_pdf_mismatch" in res.quarantine
    assert res.remeasured == {}
    _no_bundle_open(open_spy, tmp_path / "batch")


def test_resolution_is_by_sha_only(tmp_path):
    """The record names a doctored copy; the sha names the fixture: the registry path wins."""
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    doctored = bytearray(scene.data)
    doctored[-5] ^= 0xFF
    (tmp_path / "test_files" / "doctored.pdf").write_bytes(bytes(doctored))
    case = _edit(case, ("/source/relative_path", "test_files/doctored.pdf"))
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.provenance_verified is True


def test_public_sha_absent_is_provenance_unverified(tmp_path):
    scene = _scene(tmp_path, register=False)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["provenance_unverified"]
    assert res.outcome == "quarantined"
    assert res.provenance_verified is False
    assert res.remeasured  # still remeasured: the file resolves by the record's path with a matching sha
    assert res.divergences == []


def test_rederive_quarantines_unlisted_local_unrecorded(tmp_path):
    scene = _scene(tmp_path, provenance="local_unrecorded", register=False)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["provenance_unverified"]
    assert res.provenance_verified is False
    assert res.remeasured


def test_listed_provenance_must_match_the_declared_one(tmp_path):
    """A proprietary registry entry cannot vouch for a row that declares itself public."""
    scene = _scene(tmp_path, provenance="proprietary")
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE, provenance="public")
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert "provenance_unverified" in res.quarantine
    assert res.provenance_verified is False


def test_unregistered_proprietary_is_before_pdf_mismatch(tmp_path):
    scene = _scene(tmp_path, provenance="proprietary", register=False)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE, provenance="proprietary")
    assert case["source"]["relative_path"] is None
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["before_pdf_mismatch"]
    assert res.remeasured == {}
    assert res.at_head == {}
    assert res.outcome == "quarantined"
    # a census row from the same unresolvable source measures nothing and emits nothing
    census = _edit(case, ("/kind", "census"), ("/class_id", "F1"))
    res = _run(census, scene, tmp_path, oracles=_full_oracles())
    assert res.remeasured == {}
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
    assert rd.emit_rows([census], report, {"F1": {}})[0] == []


def test_registered_proprietary_resolves_without_a_relative_path(tmp_path):
    scene = _scene(tmp_path, provenance="proprietary")
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE, provenance="proprietary")
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.provenance_verified is True


def test_synthetic_builder_not_allowlisted(tmp_path, monkeypatch):
    scene = _scene(tmp_path, register=False)
    case = _product_record(
        scene, tb.REPLACEMENT_EQUAL_ADVANCE, class_id="CTRL_SYN_T0", kind="control", variant="ctrl",
        provenance="synthetic", builder={"callable": "test_scripts.painter_matrix_fixtures.replace_show_with_tj", "kwargs": {}},
    )
    imported: list[str] = []
    real = importlib.import_module

    def spy(name, *a, **k):
        imported.append(name)
        return real(name, *a, **k)

    monkeypatch.setattr(rd.importlib, "import_module", spy)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["builder_not_allowlisted"]
    assert "test_scripts.painter_matrix_fixtures" not in imported
    assert res.remeasured == {}


def test_synthetic_rebuild_matches_stream_sha(tmp_path):
    """CTRL_SYN_T1 (rejected probe) and CTRL_SYN_T0 (commit) rebuild from the allowlisted builder."""
    builder = {"callable": SYN_CALLABLE, "kwargs": dict(SYN_KWARGS)}
    syn = _scene(tmp_path, slug="syn", provenance="synthetic", register=False)
    t1 = _product_record(syn, tb.REPLACEMENT_LONGER, class_id="CTRL_SYN_T1", kind="control", variant="ctrl", provenance="synthetic", builder=builder)
    assert t1["probe"]["max_tier_1"]["reason"] == "growth_region_not_blank"
    assert t1["probe"]["max_tier_1"]["detail"].startswith("glyphs:")
    assert t1["probe"]["max_tier_0"]["reason"] == "advance_mismatch"
    res = _run(t1, syn, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.provenance_verified is False  # H4: counts toward no lineage
    assert res.at_head["max_tier_1"]["reason"] == "growth_region_not_blank"
    assert res.at_head["committed"] is False
    t0 = _product_record(syn, tb.REPLACEMENT_EQUAL_ADVANCE, class_id="CTRL_SYN_T0", kind="control", variant="ctrl", provenance="synthetic", builder=builder)
    res = _run(t0, syn, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.at_head["committed"] is True
    bad = _edit(t0, ("/mutation/changes/0/old_stream_sha256", "0" * 64))
    res = _run(bad, syn, tmp_path, oracles=_full_oracles())
    assert "before_pdf_mismatch" in res.quarantine


def test_synthetic_positive_quarantined(tmp_path):
    """H4: a synthetic positive is never a source for a frontier class."""
    builder = {"callable": SYN_CALLABLE, "kwargs": {"text": tb.CJK_TEXT, "rotate": 270, "tail_text": tb.TAIL_TEXT}}
    syn = _scene(tmp_path, slug="syn", provenance="synthetic", register=False)
    case = _product_record(syn, tb.REPLACEMENT_EQUAL_ADVANCE, class_id="F17", kind="positive", variant="eq", provenance="synthetic", builder=builder)
    res = _run(case, syn, tmp_path, oracles=_full_oracles())
    assert "provenance_unverified" in res.quarantine
    assert res.provenance_verified is False
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
    assert rd.emit_rows([case], report, {"F17": {}}) == ([], [])


def test_reason_order_quarantine(tmp_path):
    scene = _scene(tmp_path)
    base = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    for class_id in ("F2I", "F2R"):
        case = _edit(base, ("/class_id", class_id), ("/corpus_case/expected_reason", "tj_multi_item_array"))
        res = _run(case, scene, tmp_path, oracles=_full_oracles())
        assert res.quarantine == ["reason_order"]
    other = _edit(base, ("/class_id", "F30B"), ("/corpus_case/expected_reason", "tj_multi_item_array"))
    assert _run(other, scene, tmp_path, oracles=_full_oracles()).quarantine == []


# ==========================================================================
# 2. remeasure (H1) and the fixture-bound fields
# ==========================================================================
def test_replay_experiment_quarantines_understated_advance(tmp_path):
    scene = _scene(tmp_path, tail=None)
    tol = max(1e-9 * 12.0, 1e-9)
    case = _experiment_record(scene, understate=10 * tol)
    # the understated record is internally consistent: SPEC A's arithmetic validator accepts it
    assert eb.check_advance(case).violations == []
    assert eb.check_growth_zone(case).violations == []
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "adv_new_text_space" in _fields(res)
    assert res.outcome == "quarantined"


def test_type0_advance_source_widths_quarantined(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    bad = _edit(case, ("/mutation/advance/advance_source", "Widths"))
    assert any(v.code == "advance_source_font_kind" for v in eb.check_cross_field(bad).violations)  # both layers are live
    res = _run(bad, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "advance_source" in _fields(res)


def test_advance_source_dw_vs_w_is_recomputed(tmp_path):
    """W when every old and new CID hits a /W record, else DW: the record's word is recomputed either way."""
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    honest = case["mutation"]["advance"]["advance_source"]
    other = "DW" if honest == "W" else "W"
    res = _run(_edit(case, ("/mutation/advance/advance_source", other)), scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "advance_source" in _fields(res)


def test_rederive_quarantines_k_divergence(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _product_record(scene, tb.REPLACEMENT_LONGER, variant="grow")
    k = case["mutation"]["advance"]["K_written"]
    res = _run(_edit(case, ("/mutation/advance/K_written", k + 1e-3)), scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "K" in _fields(res)


def test_rederive_quarantines_reason_tier_and_range_divergence(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _product_record(scene, tb.REPLACEMENT_LONGER, variant="grow")
    for pointer, value, field in (
        ("/probe/max_tier_1/tier", 0, "tier"),
        ("/probe/max_tier_1/prepared/replacement_start", 1, "replacement_start"),
        ("/probe/max_tier_1/prepared/font_xref", 9999, "font_xref"),
        ("/probe/max_tier_1/prepared/verify_bbox_page", [0.0, 0.0, 1.0, 1.0], "verify_bbox_page"),
    ):
        res = _run(_edit(case, (pointer, value)), scene, tmp_path, oracles=_full_oracles())
        assert res.quarantine == ["remeasure"], pointer
        assert field in _fields(res), (pointer, _fields(res))


def test_rederive_quarantines_wrong_refusal_reason(tmp_path):
    scene = _scene(tmp_path)  # tail page: growth is refused
    case = _product_record(scene, tb.REPLACEMENT_LONGER, kind="negative", variant="neg", expected_reason="growth_region_not_blank")
    assert _run(case, scene, tmp_path, oracles=_full_oracles()).outcome == "rederived"
    res = _run(_edit(case, ("/probe/max_tier_1/reason", "advance_mismatch")), scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "reason" in _fields(res)


def test_replay_experiment_quarantines_remeasure_divergence(tmp_path):
    """The bytes render a different stream than the record claims."""
    scene = _scene(tmp_path, tail=None)
    honest = _experiment_record(scene)
    codes = bytearray(tb.encode_cids(tb.REPLACEMENT_LONGER))
    donor = tb.encode_cids("好")
    codes[0:2] = donor  # same width, a different CID
    new_op = f"[<{bytes(codes).hex().upper()}> {honest['mutation']['advance']['K_written']:.6f}] TJ".encode("ascii")
    altered = copy.deepcopy(honest)
    altered["mutation"]["changes"][0]["new_operand_bytes_hex"] = new_op.hex().upper()
    glyphs = copy.deepcopy(honest["glyph_identity"])
    glyphs[0]["code_bytes_hex"] = donor.hex().upper()
    glyphs[0]["char"] = "好"
    altered["glyph_identity"] = glyphs
    res = _run(altered, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert set(_fields(res)) & {"new_stream_sha256", "after_bbox_raw"}


def test_new_operand_k_token_must_match_k_written(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    res = _run(_edit(case, ("/mutation/advance/K_written", 999.0)), scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "K_written" in _fields(res)


def test_end_new_and_counts_are_recomputed(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    for pointer, value, field in (
        ("/mutation/changes/0/end_new", case["mutation"]["changes"][0]["end_new"] + 1, "end_new"),
        ("/text_state/show_count_after", 7, "show_count_after"),
        ("/text_state/operator_count_after", 99, "operator_count_after"),
        ("/text_state/operator_count_before", 99, "operator_count_before"),
        ("/text_state/show_count_before", 9, "show_count_before"),
    ):
        res = _run(_edit(case, (pointer, value)), scene, tmp_path, oracles=_full_oracles())
        assert res.quarantine == ["remeasure"], pointer
        assert field in _fields(res), (pointer, _fields(res))


def test_text_state_and_target_binding_are_recomputed(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    for pointer, value, field in (
        ("/text_state/before/Tf/size", 13.0, "text_state.before.Tf.size"),
        ("/text_state/before/Tz", 90.0, "text_state.before.Tz"),
        ("/text_state/before/origin_user", [1.0, 2.0], "text_state.before.origin_user"),
        ("/target/op_start", case["target"]["op_start"] + 1, "target.op_start"),
        ("/target/trm_scale", 0.5, "trm_scale"),
        ("/target/target_bbox_raw", [0.0, 0.0, 1.0, 1.0], "target_bbox_raw"),
        ("/corpus_case/original_sha256", "0" * 64, "original_sha256"),
    ):
        res = _run(_edit(case, (pointer, value)), scene, tmp_path, oracles=_full_oracles())
        assert res.quarantine == ["remeasure"], pointer
        assert field in _fields(res), (pointer, _fields(res))


def test_font_kind_and_resource_are_recomputed(tmp_path):
    """The Type0 binding rules read corpus_case.font_kind, so a Type0 show cannot be relabelled simple."""
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    for pointer, value, field in (
        ("/corpus_case/font_kind", "simple", "font_kind"),
        ("/corpus_case/font_resource", "F99", "font_resource"),
    ):
        res = _run(_edit(case, (pointer, value)), scene, tmp_path, oracles=_full_oracles())
        assert res.quarantine == ["remeasure"], pointer
        assert field in _fields(res), (pointer, _fields(res))


def test_unreadable_source_bytes_are_unresolvable_not_a_crash(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    junk = b"not a pdf at all"
    (tmp_path / "test_files" / "junk.pdf").write_bytes(junk)
    registry = rd.CorpusRegistry(root=tmp_path, entries=(rd.RegistryEntry("fx-a", "test_files/junk.pdf", _sha(junk), "public", "fx-a"),))
    case = _edit(case, ("/source/sha256", _sha(junk)))
    res = _run(case, scene, tmp_path, oracles=_full_oracles(), registry=registry)
    assert res.outcome == "quarantined"
    assert "before_pdf_mismatch" in res.quarantine
    assert res.remeasured == {}


def test_change_range_is_recomputed(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    ch = case["mutation"]["changes"][0]
    for pointer, value, field in (
        ("/mutation/changes/0/old_stream_sha256", "0" * 64, "old_stream_sha256"),
        ("/mutation/changes/0/old_operand_sha256", "0" * 64, "old_operand_sha256"),
        ("/mutation/changes/0/token_aligned", False, "token_aligned"),
        ("/mutation/changes/0/old_operand_bytes_hex", "00" * 3, "old_operand_bytes_hex"),
    ):
        res = _run(_edit(case, (pointer, value)), scene, tmp_path, oracles=_full_oracles())
        assert res.quarantine, pointer
        assert field in _fields(res), (pointer, _fields(res))
    assert ch["token_aligned"] is True


def test_region_dict_frame_quarter_turn(tmp_path):
    """/Rotate 270 passes; a /UserUnit 2 + /Rotate 90 + offset CropBox page exposes page.rotation_matrix."""
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    assert _run(case, scene, tmp_path, oracles=_full_oracles()).outcome == "rederived"

    def odd_page(fx):
        page = fx.doc[0]
        fx.doc.xref_set_key(page.xref, "UserUnit", "2")
        page.set_cropbox(fitz.Rect(20, 30, 575, 800))
        page.set_rotation(90)

    odd = _scene(tmp_path, slug="odd", tail=None, rotate=0, prepare=odd_page)
    base = _experiment_record(odd)
    assert base["target"]["user_unit"] == 2.0
    res = _run(base, odd, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    mpage = fitz.open(str(odd.path))[0]
    wrong = fitz.Rect(base["growth_zone"]["region_visual"]) * ~mpage.rotation_matrix
    assert _box(wrong) != base["growth_zone"]["region_dict"]  # the frame matters on this page
    res = _run(_edit(base, ("/growth_zone/region_dict", _box(wrong))), odd, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "region_dict" in _fields(res)
    res = _run(_edit(base, ("/target/user_unit", 1.0)), odd, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "user_unit" in _fields(res)


def test_background_quad_must_be_metric_box(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    res = _run(_edit(case, ("/growth_zone/background_bbox_visual", case["target"]["target_bbox_visual"])), scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "background_bbox_visual" in _fields(res)


def test_probe_regions_must_match_exactly(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    regions = copy.deepcopy(case["growth_zone"]["probe_regions_px_96dpi"])
    regions[0][0] += 1
    res = _run(_edit(case, ("/growth_zone/probe_regions_px_96dpi", regions)), scene, tmp_path, oracles=_full_oracles())
    assert "probe_regions_px_96dpi" in _fields(res)


def test_verify_bbox_rebuilt_from_recomputed_delta(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    v = list(case["target"]["verify_bbox_visual"])
    v[3] += 5.0
    res = _run(_edit(case, ("/target/verify_bbox_visual", v)), scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "verify_bbox_visual" in _fields(res)


def test_growth_claim_contradicting_the_product_gates_is_quarantined(tmp_path):
    """The record says the growth strip was blank; the product gates say a tail glyph sits in it."""
    scene = _scene(tmp_path)  # tail page
    case = _experiment_record(scene)
    assert case["growth_zone"]["before_glyph_bboxes_intersecting"] >= 1
    claimed = _edit(case, ("/growth_zone/before_glyph_bboxes_intersecting", 0))
    res = _run(claimed, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "before_glyph_bboxes_intersecting" in _fields(res)
    honest = _run(case, scene, tmp_path, oracles=_full_oracles())
    # the honest record of a failing growth agrees with the oracle (a growth canary shape)
    assert "before_glyph_bboxes_intersecting" not in _fields(honest)


def _structured_pages(tmp_path):
    def oc(fx):
        tb.install_oc_layer(fx, name="MC0", label="L")
        tb.wrap_content_in_marked_content(fx, "/OC /MC0 BDC")

    def tree(fx, *, with_parents=True, lang="en"):
        doc = fx.doc
        tb.wrap_content_in_marked_content(fx, "/P <</MCID 0>> BDC")
        root = doc.get_new_xref()
        parent_tree = doc.get_new_xref()
        elem = doc.get_new_xref()
        doc.update_object(elem, f"<< /Type /StructElem /S /P /P {root} 0 R /K 0 /Lang ({lang}) >>")
        doc.update_object(parent_tree, f"<< /Nums [ 0 [ {elem} 0 R ] ] >>")
        doc.update_object(root, f"<< /Type /StructTreeRoot /K {elem} 0 R /ParentTree {parent_tree} 0 R >>")
        doc.xref_set_key(doc.pdf_catalog(), "StructTreeRoot", f"{root} 0 R")
        if with_parents:
            doc.xref_set_key(fx.page.xref, "StructParents", "0")

    return oc, tree


def test_props_and_structelem_recomputed(tmp_path):
    oc, tree = _structured_pages(tmp_path)
    # OCG dictionary keys are never folded into props_keys
    ocs = _scene(tmp_path, slug="oc", tail=None, prepare=oc)
    case = _experiment_record(ocs, class_id="F1", variant="grow")
    wrapper = case["text_state"]["before"]["wrapper_stack"][0]
    assert (wrapper["tag"], wrapper["props_kind"], wrapper["props_name"], wrapper["props_keys"]) == ("OC", "name", "MC0", [])
    assert _run(case, ocs, tmp_path, oracles=_full_oracles()).outcome == "rederived"
    bad = _edit(case, ("/text_state/before/wrapper_stack/0/props_keys", ["Type", "Name", "Usage"]))
    res = _run(bad, ocs, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "props_keys" in _fields(res)

    # a /P <</MCID 0>> wrapper resolved through a hand-written ParentTree
    structured = _scene(tmp_path, slug="tree", tail=None, prepare=lambda fx: tree(fx))
    case = _experiment_record(structured, class_id="F1", variant="grow")
    wrapper = case["text_state"]["before"]["wrapper_stack"][0]
    assert (wrapper["tag"], wrapper["props_kind"], wrapper["props_keys"]) == ("P", "dict", ["MCID"])
    case = _edit(case, ("/text_state/before/wrapper_stack/0/structelem_keys", ["Lang"]))
    res = _run(case, structured, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    for keys in (["S", "P", "K", "Pg"], [], None):
        bad = _edit(case, ("/text_state/before/wrapper_stack/0/structelem_keys", keys))
        res = _run(bad, structured, tmp_path, oracles=_full_oracles())
        assert res.quarantine == ["remeasure"], keys
        assert "structelem_keys" in _fields(res), keys

    # no /StructParents: the only honest value is null
    plain = _scene(tmp_path, slug="noparents", tail=None, prepare=lambda fx: tree(fx, with_parents=False))
    case = _experiment_record(plain, class_id="F1", variant="grow")
    assert case["text_state"]["before"]["wrapper_stack"][0]["structelem_keys"] is None
    assert _run(case, plain, tmp_path, oracles=_full_oracles()).outcome == "rederived"
    bad = _edit(case, ("/text_state/before/wrapper_stack/0/structelem_keys", ["Lang"]))
    res = _run(bad, plain, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "structelem_keys" in _fields(res)


def test_structelem_keys_only_the_four_key_vocabulary(tmp_path):
    _, tree = _structured_pages(tmp_path)

    def both(fx):
        tree(fx)
        elem = int(fx.doc.xref_get_key(fx.doc.pdf_catalog(), "StructTreeRoot")[1].split()[0])
        k = fx.doc.xref_get_key(elem, "K")[1].split()[0]
        fx.doc.xref_set_key(int(k), "Alt", "(a)")
        fx.doc.xref_set_key(int(k), "ActualText", "(b)")

    scene = _scene(tmp_path, slug="four", tail=None, prepare=both)
    case = _experiment_record(scene, class_id="F1", variant="grow")
    good = _edit(case, ("/text_state/before/wrapper_stack/0/structelem_keys", ["ActualText", "Alt", "Lang"]))
    assert _run(good, scene, tmp_path, oracles=_full_oracles()).outcome == "rederived"
    swapped = _edit(case, ("/text_state/before/wrapper_stack/0/structelem_keys", ["Lang", "Alt", "ActualText"]))
    assert "structelem_keys" in _fields(_run(swapped, scene, tmp_path, oracles=_full_oracles()))


# ==========================================================================
# 3. canaries
# ==========================================================================
def test_replay_experiment_skips_canary_unsaved(tmp_path, monkeypatch):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene, class_id="CANARY_UNSAVED", kind="canary", variant="can", path="canary", method_id="CANARY", splice_kind="canary")
    calls: list[int] = []
    monkeypatch.setattr(rd, "splice_stream", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(AssertionError("spliced")))
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.outcome == "skipped"
    assert res.skipped == "canary_unsaved_handle_fault"
    assert res.quarantine == []
    assert calls == []


def test_canary_ksign_is_replayed(tmp_path, monkeypatch):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene, class_id="CANARY_KSIGN", kind="canary", variant="can", path="canary", method_id="CANARY", splice_kind="canary", k_sign=-1.0)
    assert case["mutation"]["advance"]["K_written"] == pytest.approx(-1000.0)
    seen: list[int] = []
    real = rd.splice_stream
    monkeypatch.setattr(rd, "splice_stream", lambda *a, **k: seen.append(1) or real(*a, **k))
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert seen, "the canary must be re-applied"
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.skipped is None


# ==========================================================================
# 4. oracles and emit_rows
# ==========================================================================
def test_oracle_failure_after_commit_is_quarantined(tmp_path):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    res = _run(case, scene, tmp_path, oracles=_full_oracles(fail="assert_glyph_identity"))
    assert res.quarantine == ["oracle_assert_glyph_identity"]
    assert res.outcome == "quarantined"
    assert res.at_head["committed"] is True
    assert res.oracles_run["assert_glyph_identity"] == "forced failure detail"


def test_default_oracles_defer_committed_rows(tmp_path):
    """Only the growth oracle is landed: a committed row is deferred, never engine_active."""
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    res = _run(case, scene, tmp_path)
    assert res.outcome == "deferred"
    assert res.deferred == "oracles_incomplete"
    assert set(res.oracles_run) == {"assert_growth_zone_was_blank"}
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
    assert rd.emit_rows([case], report, {"F30B": {}}) == ([], [])


def test_emit_rows_false_safe_branch(tmp_path):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    res = _set_status(_run(case, scene, tmp_path, oracles=_full_oracles(fail="assert_glyph_identity")), "save_reopen_pass")
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
    before = copy.deepcopy(report)
    rows, findings = rd.emit_rows([case], report, {"F30B": {}})
    assert report == before  # the input report is never mutated
    assert len(rows) == 1
    row = rows[0]
    for key, value in {
        "state": "candidate",
        "kind": "refusal",
        "expected_reason": None,
        "expected_reason_at_head": "COMMITTED",
        "false_safe_oracle": "assert_glyph_identity",
        "owned_until_slice": "I1",
        "class_id": "F30B",
    }.items():
        assert row[key] == value, key
    assert row["provenance"]["batch"] == "batch"
    assert row["provenance"]["rederive_head"] == "deadbeef"
    assert findings == [{"kind": "false_safe_suspect", "case_id": case["case_id"], "oracle": "assert_glyph_identity"}]
    # the stream/wrapper/count/growth helpers are owned by I0b
    res = _set_status(_run(case, scene, tmp_path, oracles=_full_oracles(fail="assert_growth_zone_was_blank")), "save_reopen_pass")
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
    assert rd.emit_rows([case], report, {"F30B": {}})[0][0]["owned_until_slice"] == "I0b"
    # a missing owner is a hard error, never a silent default
    with pytest.raises(ValueError):
        rd.emit_rows([case], report, {"F30B": {}}, oracle_owners={})


def test_emit_rows_never_emits_quarantined_cases(tmp_path):
    scene = _scene(tmp_path, register=False)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["provenance_unverified"]
    assert res.at_head["committed"] is True  # it commits cleanly at HEAD, and still emits nothing
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
    assert rd.emit_rows([case], report, {"F30B": {}}) == ([], [])


def test_emit_rows_emits_nothing_for_synthetic(tmp_path):
    builder = {"callable": SYN_CALLABLE, "kwargs": dict(SYN_KWARGS)}
    syn = _scene(tmp_path, slug="syn", provenance="synthetic", register=False)
    t0 = _product_record(syn, tb.REPLACEMENT_EQUAL_ADVANCE, class_id="CTRL_SYN_T0", kind="control", variant="ctrl", provenance="synthetic", builder=builder)
    res = _run(t0, syn, tmp_path, oracles=_full_oracles())
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
    assert rd.emit_rows([t0], report, {"CTRL_SYN_T0": {}}) == ([], [])


def test_emit_rows_engine_active_and_candidate(tmp_path):
    scene = _scene(tmp_path)
    committed = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE, variant="eq")
    guard = _product_record(scene, tb.REPLACEMENT_LONGER, kind="negative", variant="neg", expected_reason="growth_region_not_blank")
    refused_positive = _product_record(scene, tb.REPLACEMENT_LONGER, kind="positive", variant="grow", class_id="F2G")
    results = [
        _set_status(_run(committed, scene, tmp_path, oracles=_full_oracles()), "save_reopen_pass"),
        _set_status(_run(guard, scene, tmp_path, oracles=_full_oracles()), "probe_rejected"),
        _set_status(_run(refused_positive, scene, tmp_path, oracles=_full_oracles()), "splice_pass"),  # a refused positive carries an experiment that passed
    ]
    assert [r.outcome for r in results] == ["rederived"] * 3, [(r.quarantine, r.divergences) for r in results]
    report = rd.build_report("batch", results, head="deadbeef", validation_sha256="0" * 64)
    rows, findings = rd.emit_rows([committed, guard, refused_positive], report, {"F30B": {}, "F2G": {}})
    by_case = {r["provenance"]["case_id"]: r for r in rows}
    assert findings == []
    assert by_case[committed["case_id"]]["state"] == "engine_active"
    assert by_case[committed["case_id"]]["kind"] == "positive"
    assert by_case[guard["case_id"]]["state"] == "engine_active"  # a by-design guard
    assert by_case[guard["case_id"]]["kind"] == "refusal"
    assert by_case[guard["case_id"]]["expected_reason"] == "growth_region_not_blank"
    cand = by_case[refused_positive["case_id"]]
    assert cand["state"] == "candidate"
    assert cand["expected_reason_at_head"] == "growth_region_not_blank"
    assert cand["kind"] == "positive"
    # a slice that owns the refusal keeps the guard a candidate
    rows, _ = rd.emit_rows([guard], rd.build_report("batch", [results[1]], head="h", validation_sha256="0" * 64), {"F30B": {"owned_until_slice": "I3"}})
    assert rows[0]["state"] == "candidate"
    assert rows[0]["owned_until_slice"] == "I3"
    # a class that is not planned emits nothing, whatever the product did
    assert rd.emit_rows([committed], rd.build_report("batch", [results[0]], head="h", validation_sha256="0" * 64), {"F2G": {}}) == ([], [])


def test_emit_rows_skips_control_canary_census(tmp_path):
    scene = _scene(tmp_path)
    base = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    for kind in ("control", "canary", "census"):
        case = _edit(base, ("/kind", kind))
        res = _run(case, scene, tmp_path, oracles=_full_oracles())
        report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
        assert rd.emit_rows([case], report, {"F30B": {}}) == ([], []), kind


def test_emitted_rows_carry_no_text_for_non_public_sources(tmp_path):
    scene = _scene(tmp_path, provenance="proprietary")
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE, provenance="proprietary")
    res = _set_status(_run(case, scene, tmp_path, oracles=_full_oracles()), "save_reopen_pass")
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
    rows, _ = rd.emit_rows([case], report, {"F30B": {}})
    assert rows[0]["original"] is None
    assert rows[0]["original_sha256"] == _sha(tb.CJK_TEXT)
    assert rows[0]["key"].startswith("fx-a/p0/show")


# ==========================================================================
# 5. the built-in growth oracle
# ==========================================================================
def _oracle_ctx(tr: Truth, source: fitz.Document, replacement: str, verify_vis):
    return rd.OracleContext(
        source_doc=source,
        after_doc=source,
        page_index=tr.page_index,
        show=tr.show,
        frame=tr.frame,
        target_bbox_visual=tuple(tr.bbox_vis),
        verify_bbox_visual=tuple(verify_vis),
        adv_old=tr.adv(tr.show.decoded_bytes),
        prepared=None,
        case={"corpus_case": {"replacement": replacement}},
    )


def test_built_in_growth_oracle_agrees_with_product(tmp_path):
    tail = _scene(tmp_path, slug="tail")  # growth runs into the tail glyphs
    tr = Truth(tail.path)
    growth = 12.0 * tr.th
    grown = _grown_verify_bbox(tr.page, tr.show, tuple(tr.bbox_vis), growth, frame=tr.frame)
    src = fitz.open(str(tail.path))
    detail = rd.assert_growth_zone_was_blank(_oracle_ctx(tr, src, tb.REPLACEMENT_LONGER, grown))
    assert detail is not None
    assert detail.startswith("glyphs:")
    # not applicable when verify == target (shrink or equal advance)
    assert rd.assert_growth_zone_was_blank(_oracle_ctx(tr, src, tb.REPLACEMENT_EQUAL_ADVANCE, tr.bbox_vis)) is None
    src.close()
    tr.close()
    blank = _scene(tmp_path, slug="blank", tail=None)
    tr = Truth(blank.path)
    grown = _grown_verify_bbox(tr.page, tr.show, tuple(tr.bbox_vis), growth, frame=tr.frame)
    src = fitz.open(str(blank.path))
    assert rd.assert_growth_zone_was_blank(_oracle_ctx(tr, src, tb.REPLACEMENT_LONGER, grown)) is None
    src.close()
    tr.close()


def test_built_in_oracle_never_passes_a_missing_background_quad(tmp_path):
    """The oracle feeds the product the font-metric quad: it is never background_bbox=None."""
    import model.text_commit.verify as product_verify

    blank = _scene(tmp_path, slug="blank", tail=None)
    tr = Truth(blank.path)
    grown = _grown_verify_bbox(tr.page, tr.show, tuple(tr.bbox_vis), 12.0 * tr.th, frame=tr.frame)
    src = fitz.open(str(blank.path))
    seen: list[object] = []
    real = product_verify._growth_probe_failure

    def spy(state, **kwargs):
        seen.append(kwargs.get("background_bbox"))
        return real(state, **kwargs)

    old = rd.verify._growth_probe_failure
    rd.verify._growth_probe_failure = spy
    try:
        assert rd.assert_growth_zone_was_blank(_oracle_ctx(tr, src, tb.REPLACEMENT_LONGER, grown)) is None
    finally:
        rd.verify._growth_probe_failure = old
    assert seen and seen[0] is not None
    assert tuple(seen[0]) == pytest.approx(tuple(_quad(tr, tr.adv(tr.show.decoded_bytes))))
    src.close()
    tr.close()


# ==========================================================================
# 6. registry and the tracked public list
# ==========================================================================
def test_public_corpus_sha_list_shape():
    data = json.loads(PUBLIC_LIST.read_text(encoding="utf-8"))
    assert data["schema"] == "public-corpus-sha256/1"
    files = data["files"]
    assert files, "the tracked list must name at least the brief's public files"
    seen_sha: set[str] = set()
    seen_path: set[str] = set()
    for item in files:
        assert set(item) == {"relative_path", "sha256", "origin", "lineage_id"}, item
        rel = item["relative_path"]
        assert rel.startswith("test_files/") and rel.endswith(".pdf"), rel
        assert ":" not in rel and "\\" not in rel and ".." not in rel, rel
        assert re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), item
        assert item["origin"] in {"sample-files-main", "veraPDF-corpus-staging", "Test-PDF-Files-master"}
        assert rel.split("/")[1] == item["origin"], rel
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", item["lineage_id"]), item
        assert item["sha256"] not in seen_sha and rel not in seen_path
        seen_sha.add(item["sha256"])
        seen_path.add(rel)
        for _label, pattern in PATTERNS:
            assert not pattern.search(rel), rel
            assert not pattern.search(json.dumps(item)), rel
    # the file as a whole is clean for the device guard
    text = PUBLIC_LIST.read_text(encoding="utf-8")
    assert not any(p.search(text) for _l, p in PATTERNS)
    # nothing proprietary or local_unrecorded is anchored here (G2 keeps the list's name honest)
    acc = ACC.read_text(encoding="utf-8")
    for sha in re.findall(r'sha256="([0-9a-f]{64})"', acc):
        assert sha not in seen_sha, "an hvac/ecc sha leaked into the public list"
    brief = BRIEF.read_text(encoding="utf-8")
    prefixes = re.findall(r"(?:test-colored-background|test-horizontal-texts|test-hierarchy-bookmarks|test-complexed-layout)[^0-9a-f]*([0-9a-f]{8})", brief)
    assert len(prefixes) >= 4, prefixes
    for prefix in prefixes:
        assert not any(s.startswith(prefix) for s in seen_sha), prefix
    assert not any("test-colored-background" in p or "hvac-dwg" in p or "ecc-dwg" in p for p in seen_path)


def test_load_registry_reads_the_tracked_list_and_acc_corpora():
    registry = rd.load_registry(ROOT)
    publics = [e for e in registry.entries if e.provenance == "public"]
    props = {e.slug: e for e in registry.entries if e.provenance == "proprietary"}
    listed = json.loads(PUBLIC_LIST.read_text(encoding="utf-8"))["files"]
    assert len(publics) == len(listed)
    assert set(props) == {"hvac", "ecc"}  # duck-typed from acc.CORPORA: slug, relative_path, sha256 only
    assert props["hvac"].relative_path == "test_files/hvac-dwg.pdf"
    assert all(e.lineage_id == e.slug for e in props.values())
    assert registry.by_sha(listed[0]["sha256"]).provenance == "public"
    assert registry.by_sha("0" * 64) is None
    none_acc = rd.load_registry(ROOT, include_acc=False)
    assert not [e for e in none_acc.entries if e.provenance == "proprietary"]


def test_registry_resolve_needs_the_file_and_a_matching_sha(tmp_path):
    folder = tmp_path / "test_files"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(b"%PDF-1.4 a")
    good = rd.RegistryEntry("a", "test_files/a.pdf", _sha(b"%PDF-1.4 a"), "public", "a")
    bad = rd.RegistryEntry("a", "test_files/a.pdf", _sha(b"other"), "public", "a")
    gone = rd.RegistryEntry("b", "test_files/b.pdf", _sha(b"b"), "public", "b")
    registry = rd.CorpusRegistry(root=tmp_path, entries=(good, bad, gone))
    assert registry.resolve(good) == (folder / "a.pdf")
    assert registry.resolve(bad) is None
    assert registry.resolve(gone) is None
    assert registry.by_sha(good.sha256) is good


def test_public_list_files_resolve_when_present():
    """When the owner's test_files/ is there, every listed sha must match the bytes on disk."""
    registry = rd.load_registry(ROOT, include_acc=False)
    present = 0
    for entry in registry.entries:
        path = ROOT / entry.relative_path
        if path.is_file():
            present += 1
            assert registry.resolve(entry) is not None, entry.relative_path
    if present == 0:
        pytest.skip("owner test_files/ is not available")


# ==========================================================================
# 7. report, closure, CLI
# ==========================================================================
def test_report_shape(tmp_path):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="a" * 64)
    assert report["schema"] == "evidence-rederive/1"
    assert report["batch"] == "batch"
    assert report["head"] == "deadbeef"
    assert report["validation_sha256"] == "a" * 64
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", report["date_utc"])
    assert report["results"][0]["case_id"] == case["case_id"]
    json.dumps(report)


def test_unverifiable_items_are_closed_or_reported(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    items = [
        {"code": "user_unit", "case_id": case["case_id"]},
        {"code": "token_aligned", "case_id": case["case_id"]},
        {"code": "region_dict", "case_id": case["case_id"]},
        {"code": "calibration_incomplete", "case_id": None},
        {"code": "props_keys", "case_id": case["case_id"]},
    ]
    closure = rd.close_unverifiable(items, [res])
    assert {i["code"] for i in closure["closed"]} == {"user_unit", "token_aligned", "region_dict", "props_keys"}
    assert [i["code"] for i in closure["open"]] == ["calibration_incomplete"]
    # a quarantined case closes everything it owns: the quarantine is the closure
    bad = _run(_edit(case, ("/mutation/advance/advance_source", "Widths")), scene, tmp_path, oracles=_full_oracles())
    assert rd.close_unverifiable(items[:1], [bad])["open"] == []


def _write_batch(root: Path, cases: list[dict]) -> Path:
    batch = root / "20261024_0100_r2"
    batch.mkdir()
    (batch / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
    for case in cases:
        _write_records(batch, case)
    return batch


def test_cli_refuses_on_batch_level_violation(tmp_path):
    batch = _write_batch(tmp_path, [])
    out = tmp_path / "out" / "rederive_report.json"
    for code in ("done_missing", "parent_summary_mismatch", "code_revision_inconsistent", "methods_plan_sha_mismatch", "plan_block_missing"):
        validation = tmp_path / f"v-{code}.json"
        validation.write_text(json.dumps({"violations": [{"code": code, "file": "DONE.json", "pointer": "", "detail": "", "case_id": None}]}), encoding="utf-8")
        assert rd.main(["rederive", str(batch), "--validation", str(validation), "--out", str(out), "--repo-root", str(ROOT)]) == 2, code
    assert not out.exists()
    assert rd.main(["rederive", str(batch), "--validation", str(tmp_path / "absent.json"), "--out", str(out), "--repo-root", str(ROOT)]) == 2


def test_cli_validator_rejected_case_is_recorded_not_rederived(tmp_path):
    scene = _scene(tmp_path)
    ok = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    rejected = _edit(ok, ("/case_id", ok["case_id"].replace("eq1", "eq2")))
    batch = _write_batch(tmp_path, [ok, rejected])
    public = tmp_path / "public.json"
    public.write_text(json.dumps({"schema": "public-corpus-sha256/1", "files": [{"relative_path": scene.rel, "sha256": scene.sha, "origin": "sample-files-main", "lineage_id": "fx-a"}]}), encoding="utf-8")
    validation = tmp_path / "validation.json"
    validation.write_text(
        json.dumps(
            _complete(
                {"violations": [{"code": "schema_required", "file": f"cases/{rejected['case_id']}/case_record.json", "pointer": "/x", "detail": "", "case_id": rejected["case_id"]}], "unverifiable": []},
                batch,
            )
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out" / "rederive_report.json"
    # the repo root is the registry root: copy the fixture there is not allowed, so point it at tmp_path
    code = rd.main(["rederive", str(batch), "--validation", str(validation), "--out", str(out), "--repo-root", str(tmp_path), "--public-list", str(public), "--no-acc"])
    report = json.loads(out.read_text(encoding="utf-8"))
    by_id = {r["case_id"]: r for r in report["results"]}
    assert by_id[rejected["case_id"]]["outcome"] == "validator_rejected"
    assert by_id[rejected["case_id"]]["at_head"] == {}
    assert by_id[ok["case_id"]]["outcome"] in {"rederived", "deferred", "quarantined"}
    assert by_id[ok["case_id"]]["provenance_verified"] is True
    assert report["validation_sha256"] == _sha(validation.read_bytes())
    assert code in (0, 1)
    # emit never edits a manifest: it only prints rows
    rows_path = tmp_path / "rows.json"
    assert rd.main(["emit", str(out), "--batch", str(batch), "--out", str(rows_path)]) == 0
    assert json.loads(rows_path.read_text(encoding="utf-8")) == {"rows": [], "findings": []}


def test_module_imports_without_qt():
    source = (ROOT / "scripts" / "evidence_rederive.py").read_text(encoding="utf-8")
    assert "from __future__ import annotations" in source
    toolkit = "Py" + "Side6"  # spelled in two halves: the suite runner classifies a file naming it as a Qt file
    assert not re.search(rf"^\s*(from|import) ({toolkit}|view|controller)", source, re.MULTILINE)
    assert "logging.getLogger(__name__)" in source
    assert "basicConfig" not in source
    used = {n.attr for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Attribute)}
    assert not used & {"rotation_matrix", "derotation_matrix", "transformation_matrix"}  # frame only (H3)


def test_quarantine_vocabulary():
    assert rd.QUARANTINE == ("provenance_unverified", "before_pdf_mismatch", "remeasure", "reason_order", "builder_not_allowlisted")
    assert rd.SKIP_CANARY_UNSAVED == "canary_unsaved_handle_fault"
    assert rd.REQUIRED_ORACLES == SIX_ORACLES
    assert set(rd.DEFAULT_ORACLES) == {"assert_growth_zone_was_blank"}
    assert rd.SYNTHETIC_ALLOWLIST == eb.SYNTHETIC_ALLOWLIST


@pytest.mark.needs_fixtures
def test_ctrl_pos_t1_rederives_on_hvac(tmp_path):
    """The mandatory Tier 1 control on the owner's hvac file: K 333, growth_pt 2.1096, trm_scale 0.060."""
    registry = rd.load_registry(ROOT)
    entry = next((e for e in registry.entries if e.slug == "hvac"), None)
    path = registry.resolve(entry) if entry is not None else None
    if entry is None or path is None:
        pytest.skip("owner hvac fixture is not available")
    scene = Scene(tmp_path, "hvac", path, entry.relative_path, path.read_bytes(), entry.sha256, registry, "proprietary")
    case = _product_record(
        scene, "Drawing Title", class_id="CTRL_POS_T1", kind="control", variant="ctrl", provenance="proprietary", show_seq=26, page_index=4
    )
    advance = case["mutation"]["advance"]
    assert advance["K_written"] == pytest.approx(333.0, abs=1e-6)
    assert advance["growth_pt"] == pytest.approx(2.10955810546875, abs=1e-3)
    assert case["target"]["trm_scale"] == pytest.approx(0.060, abs=1e-6)
    oracles = _full_oracles()
    oracles["assert_growth_zone_was_blank"] = rd.assert_growth_zone_was_blank  # the product's gates on the real page
    res = _run(case, scene, tmp_path, oracles=oracles)
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert res.provenance_verified is True
    assert res.at_head["committed"] is True
    assert res.oracles_run["assert_growth_zone_was_blank"] is None


# ==========================================================================
# 8. report hygiene, the after-ink bound and honest unverifiable closure
# ==========================================================================
SENTINEL = "ZqSentinelAcme"


def test_report_and_stderr_never_carry_bundle_words(tmp_path, capsys):
    """Reports may be committed: a word planted in a bundle (or a document tag) is printed as a digest or not at all."""
    oc, _ = _structured_pages(tmp_path)
    scene = _scene(tmp_path, slug="oc", tail=None, prepare=oc)
    honest = _experiment_record(scene, class_id="F1", variant="grow")
    planted = _edit(
        honest,
        ("/text_state/before/wrapper_stack/0/tag", SENTINEL),
        ("/text_state/before/wrapper_stack/0/props_keys", [SENTINEL]),
        ("/text_state/before/Tf/resource", SENTINEL),
        ("/corpus_case/font_resource", SENTINEL),
        ("/source/slug", SENTINEL.lower()),
        ("/probe/max_tier_1/exception_type", SENTINEL),
    )
    rejected = _edit(honest, ("/case_id", SENTINEL))
    refused_scene = _scene(tmp_path, slug="tailpage")
    refused = _product_record(
        refused_scene, tb.REPLACEMENT_LONGER, kind="negative", variant="neg", expected_reason="growth_region_not_blank"
    )
    refused = _edit(refused, ("/probe/max_tier_1/reason", SENTINEL))
    batch = _write_batch(tmp_path, [planted, rejected, refused])
    public = tmp_path / "public.json"
    listing = {
        "schema": "public-corpus-sha256/1",
        "files": [
            {"relative_path": scene.rel, "sha256": scene.sha, "origin": "sample-files-main", "lineage_id": "oc"},
            {"relative_path": refused_scene.rel, "sha256": refused_scene.sha, "origin": "sample-files-main", "lineage_id": "tailpage"},
        ],
    }
    public.write_text(json.dumps(listing), encoding="utf-8")
    violation = {"code": "schema_required", "file": SENTINEL + ".json", "pointer": "/x", "detail": SENTINEL, "case_id": SENTINEL}
    validation = tmp_path / "validation.json"
    validation.write_text(
        json.dumps(_complete({"violations": [violation], "unverifiable": [{"code": SENTINEL, "case_id": SENTINEL}]}, batch)),
        encoding="utf-8",
    )
    out = tmp_path / "out" / "rederive_report.json"
    argv = ["rederive", str(batch), "--validation", str(validation), "--out", str(out)]
    code = rd.main([*argv, "--repo-root", str(tmp_path), "--public-list", str(public), "--no-acc"])
    seen = capsys.readouterr()
    text = out.read_text(encoding="utf-8")
    assert code == 1
    assert SENTINEL not in text and SENTINEL.lower() not in text
    assert SENTINEL not in seen.out + seen.err and SENTINEL.lower() not in seen.out + seen.err
    report = json.loads(text)
    by_id = {r["case_id"]: r for r in report["results"]}
    mine = by_id[planted["case_id"]]
    assert mine["outcome"] == "quarantined"
    wanted = {"wrapper.tag", "props_keys", "text_state.before.Tf.resource", "font_resource"}
    assert wanted <= {d["field"] for d in mine["divergences"]}
    assert mine["resolved_slug"] == "oc"  # the registry's slug, never the bundle's
    digests = [d["record"] for d in by_id[refused["case_id"]]["divergences"] if d["field"] == "reason"]
    assert digests and re.fullmatch(r"#[0-9a-f]{12}", digests[0])
    rejected_rows = [r for r in report["results"] if r["outcome"] == "validator_rejected"]
    assert len(rejected_rows) == 1 and re.fullmatch(r"#[0-9a-f]{12}", rejected_rows[0]["case_id"])
    closure = report["unverifiable_closure"]
    assert all(re.fullmatch(r"#[0-9a-f]{12}", i["code"]) for i in closure["open"] + closure["closed"])


def test_product_detail_is_templated_for_non_public_sources(tmp_path):
    scene = _scene(tmp_path, provenance="proprietary")
    case = _product_record(
        scene, tb.REPLACEMENT_LONGER, kind="negative", variant="neg", expected_reason="growth_region_not_blank", provenance="proprietary"
    )
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    detail = res.at_head["max_tier_1"]["detail"]
    assert re.fullmatch(r"glyphs: #[0-9a-f]{12}", detail), detail
    public = _scene(tmp_path, slug="pub")
    case = _product_record(public, tb.REPLACEMENT_LONGER, kind="negative", variant="neg", expected_reason="growth_region_not_blank")
    verbatim = _run(case, public, tmp_path, oracles=_full_oracles()).at_head["max_tier_1"]["detail"]
    assert verbatim.startswith("glyphs:") and "character" in verbatim


def test_after_ink_outrunning_the_verify_strip_is_a_divergence(tmp_path):
    """H1 bound on the MEASURED after box: the dominant-edge amount, not the strip's longer side (the cross axis)."""
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    doc = fitz.open(str(scene.path))
    sc = rd._Scene(case, doc)
    direction = case["growth_zone"]["direction"]

    def raw_after(extra: float):
        box = list(case["target"]["after_bbox_visual"])
        if direction == "right":
            box[2] += extra
        elif direction == "left":
            box[0] -= extra
        elif direction == "down":
            box[3] += extra
        else:
            box[1] -= extra
        return list(fitz.Rect(box) * ~sc.frame.quarter_turn)

    def run(extra: float):
        res = rd.RederiveResult(case_id="x")
        res.remeasured = dict(sc.adv[0])
        rd._after_bound(sc, raw_after(extra), res)
        return [d.field for d in res.divergences]

    assert run(0.0) == []
    assert run(0.4) == []
    assert run(1.0) == ["after_bbox_extent"]
    sc.close()
    doc.close()


def test_a_rev3_after_box_past_the_verify_strip_is_remeasured_not_quarantined(tmp_path):
    """V10 mirror: under brief v3 the spill is the validator's growth_zone fail (``after_exceeds_verify``), so rederive
    records the remeasured extents and adds no divergence; a lying ``after_bbox_raw`` is still the ``after_bbox_raw``
    comparison.  A rev-2 row keeps the quarantine (the test above)."""
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    case["brief_revision"] = 3
    doc = fitz.open(str(scene.path))
    sc = rd._Scene(case, doc)
    direction = case["growth_zone"]["direction"]
    box = list(case["target"]["after_bbox_visual"])
    box[{"right": 2, "left": 0, "down": 3, "up": 1}[direction]] += 1.0 if direction in ("right", "down") else -1.0
    raw_after = list(fitz.Rect(box) * ~sc.frame.quarter_turn)
    res = rd.RederiveResult(case_id="x")
    res.remeasured = dict(sc.adv[0])
    rd._after_bound(sc, raw_after, res)
    assert [d.field for d in res.divergences] == []
    assert res.remeasured["after_bbox_extent"] == pytest.approx(res.remeasured["verify_bbox_extent"] + 1.0, abs=1e-6)
    sc.close()
    doc.close()


def test_closure_lists_only_checks_that_ran(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    honest = _run(case, scene, tmp_path, oracles=_full_oracles())
    ran = {
        "user_unit",
        "token_aligned",
        "old_stream_sha256",
        "operator_count_before",
        "region_dict",
        "background_bbox",
        "probe_regions_px_96dpi",
        "type0_cid_unbound",
        "growth_applicable_mismatch",
    }
    assert ran <= set(honest.closed_unverifiable)
    assert "fragment_prefix_mismatch" not in honest.closed_unverifiable  # not an F3 row

    # an F3 splice kind without its ranges is a divergence, and the fragment check is not reported as run
    frag = _run(_edit(case, ("/mutation/splice_kind", "string_fragment")), scene, tmp_path, oracles=_full_oracles())
    assert "fragment_ranges" in _fields(frag)
    assert "fragment_prefix_mismatch" not in frag.closed_unverifiable

    # a null strip field on an applicable row never passes and is not closed
    null_regions = _run(_edit(case, ("/growth_zone/probe_regions_px_96dpi", None)), scene, tmp_path, oracles=_full_oracles())
    assert "probe_regions_px_96dpi" in _fields(null_regions)
    assert "probe_regions_px_96dpi" not in null_regions.closed_unverifiable
    null_region = _run(_edit(case, ("/growth_zone/region_dict", None)), scene, tmp_path, oracles=_full_oracles())
    assert "region_dict" in _fields(null_region)
    null_bg = _run(_edit(case, ("/growth_zone/background_bbox_visual", None)), scene, tmp_path, oracles=_full_oracles())
    assert "background_bbox_visual" in _fields(null_bg)

    # an unsupported page frame: the frame-bound codes stay open
    def tilt(fx):
        fx.doc.xref_set_key(fx.page.xref, "Rotate", "45")

    odd = _scene(tmp_path, slug="tilted", tail=None, rotate=0, prepare=tilt)
    moved = _edit(case, ("/source/sha256", odd.sha), ("/source/relative_path", odd.rel))
    res = _run(moved, odd, tmp_path, oracles=_full_oracles())
    assert "frame" in _fields(res)
    assert res.quarantine == ["remeasure"]
    assert not {"user_unit", "region_dict", "background_bbox", "probe_regions_px_96dpi"} & set(res.closed_unverifiable)


# ==========================================================================
# fix round 1: forgeries that rederived clean, each written red first
# ==========================================================================
def _set_status(result, status):
    """What the CLI does with the validator's recomputed status: carry it on the result."""
    result.validated_status = status
    return result


def _equal_advance_with_k(scene: Scene, k: float, **fields) -> dict:
    """An equal-advance replacement whose bytes carry a K token ``k`` (honest K would be 0): the tail glyphs move."""
    codes = tb.encode_cids(tb.REPLACEMENT_EQUAL_ADVANCE)
    new_op = f"[<{codes.hex().upper()}> {k:.6f}] TJ".encode("ascii")
    case = _experiment_record(scene, replacement=tb.REPLACEMENT_EQUAL_ADVANCE, new_op=new_op, **fields)
    adv = case["mutation"]["advance"]
    assert adv["K_written"] == pytest.approx(0.0)
    adv["K_written"] = k
    return case


NULL_COMPONENTS = (
    ("/mutation/advance/K_sum", None),
    ("/mutation/advance/K_disp_engine", None),
    ("/mutation/advance/K_disp_hand", None),
    ("/mutation/advance/abs_diff_written_vs_sum_engine", None),
    ("/mutation/advance/abs_diff_engine_hand", None),
)


def test_a_k_token_with_null_components_is_quarantined(tmp_path):
    """A K of 400 on an equal-advance replacement shifts the tail by 5 pt; with K_sum and K_disp_* null nothing tied it to the displacement."""
    scene = _scene(tmp_path)
    case = _edit(_equal_advance_with_k(scene, 400.0), *NULL_COMPONENTS)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"], res.divergences
    assert {"K_sum", "K_disp_engine"} <= set(_fields(res))


def test_a_k_written_that_does_not_follow_the_displacement_is_quarantined_by_its_abs_diff(tmp_path):
    scene = _scene(tmp_path, tail=None)
    honest = _experiment_record(scene)
    k = honest["mutation"]["advance"]["K_written"]
    res = _run(_edit(honest, ("/mutation/advance/K_written", k + 1e-3)), scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "abs_diff_written_vs_sum_engine" in _fields(res)


def test_a_fabricated_k_sum_on_a_proprietary_row_is_quarantined(tmp_path):
    """Brief 5.4 forces old_operand_bytes_hex to null on a non-public row, so only the registry file can tell."""
    scene = _scene(tmp_path, provenance="proprietary", tail=None)
    case = _experiment_record(scene, provenance="proprietary", k_sum=400.0)
    adv = case["mutation"]["advance"]
    assert adv["K_sum"] == 400.0 and adv["abs_diff_written_vs_sum_engine"] == pytest.approx(0.0)
    case["mutation"]["changes"][0]["old_operand_bytes_hex"] = None
    assert eb.check_operand_grammar(case).violations == [] and eb.check_advance(case).violations == []  # the validator cannot see it
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"], res.divergences
    assert "K_sum" in _fields(res)


def test_expected_kerns_are_the_internal_numbers_of_a_tj_run_only():
    old = b"(a) -20 (b) 5 (c)"
    assert rd._expected_kerns("tj_run", old) == (pytest.approx(-15.0), [-20.0, 5.0])
    assert rd._expected_kerns("whole_operator", old) == (0.0, [])
    assert rd._expected_kerns("string_token", b"<0102>") == (0.0, [])


def test_a_ksign_canary_keeps_its_wrong_sign_k_without_a_quarantine(tmp_path):
    """The flipped K is the fault the canary exists to show: its recorded abs_diff states it, so it is not a divergence."""
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene, class_id="CANARY_KSIGN", kind="canary", variant="can", path="canary", method_id="CANARY", splice_kind="canary", k_sign=-1.0)
    adv = case["mutation"]["advance"]
    assert adv["abs_diff_written_vs_sum_engine"] == pytest.approx(2000.0)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == [], res.divergences


# ---- emit_rows: the validator's recomputed status gates every row ----------
def _emit_inputs(tmp_path):
    scene = _scene(tmp_path)
    positive = _product_record(scene, tb.REPLACEMENT_LONGER, kind="positive", variant="grow", class_id="F2G")
    negative = _product_record(scene, tb.REPLACEMENT_LONGER, kind="negative", variant="neg", expected_reason="growth_region_not_blank")
    return scene, positive, negative


def _emit(case, scene, tmp_path, status):
    res = _set_status(_run(case, scene, tmp_path, oracles=_full_oracles()), status)
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    report = rd.build_report("batch", [res], head="deadbeef", validation_sha256="0" * 64)
    return rd.emit_rows([case], report, {"F30B": {}, "F2G": {}})


def test_emit_rows_needs_a_passing_recomputed_status_for_a_positive(tmp_path):
    scene, positive, _negative = _emit_inputs(tmp_path)
    for status in ("save_reopen_pass", "splice_pass"):
        rows, findings = _emit(positive, scene, tmp_path, status)
        assert [r["state"] for r in rows] == ["candidate"] and findings == [], status
    for status in ("insufficient_evidence", "probe_rejected", "blocked", None):
        rows, findings = _emit(positive, scene, tmp_path, status)
        assert rows == [], status
        assert findings == [{"kind": "status_not_emittable", "case_id": positive["case_id"]}], status


def test_emit_rows_needs_probe_rejected_for_a_negative(tmp_path):
    scene, _positive, negative = _emit_inputs(tmp_path)
    rows, findings = _emit(negative, scene, tmp_path, "probe_rejected")
    assert [r["state"] for r in rows] == ["engine_active"] and findings == []
    for status in ("save_reopen_pass", "insufficient_evidence", None):
        rows, findings = _emit(negative, scene, tmp_path, status)
        assert rows == [] and [f["kind"] for f in findings] == ["status_not_emittable"], status


def test_a_failed_growth_experiment_is_not_a_candidate_positive(tmp_path):
    """Probe D of the forger round: the record says growth_zone failed (status probe_rejected) and still became a candidate."""
    scene = _scene(tmp_path)  # the tail page: a glyph occupies the growth strip, so the gate truly fails
    case = _edit(_experiment_record(scene, replacement=tb.REPLACEMENT_LONGER), ("/growth_zone/raster_proof", "fail"))
    assert case["growth_zone"]["before_glyph_bboxes_intersecting"] == 1
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)  # the record is honest about its own failure
    report = rd.build_report("batch", [_set_status(res, "probe_rejected")], head="deadbeef", validation_sha256="0" * 64)
    rows, findings = rd.emit_rows([case], report, {"F30B": {}})
    assert rows == [] and findings == [{"kind": "status_not_emittable", "case_id": case["case_id"]}]
    report = rd.build_report("batch", [_set_status(res, "splice_pass")], head="deadbeef", validation_sha256="0" * 64)
    # a passing status cannot launder the failed growth oracle either (V4)
    rows, findings = rd.emit_rows([case], report, {"F30B": {}})
    assert rows == [] and findings == [{"kind": "remeasure_oracle_failed", "case_id": case["case_id"], "oracle": "assert_growth_zone_was_blank"}]


# ---- experiment rows wait for the same six oracles a committed product row waits for -------------
def test_an_experiment_row_is_deferred_until_the_oracles_exist(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    res = _run(case, scene, tmp_path)  # DEFAULT_ORACLES: only the growth helper exists
    assert res.outcome == "deferred" and res.deferred == "oracles_incomplete"
    assert res.divergences == [] and res.quarantine == []
    assert set(res.oracles_run) == {"assert_growth_zone_was_blank"}
    report = rd.build_report("batch", [_set_status(res, "save_reopen_pass")], head="deadbeef", validation_sha256="0" * 64)
    assert rd.emit_rows([case], report, {"F30B": {}}) == ([], [])
    full = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert full.outcome == "rederived" and set(full.oracles_run) == set(SIX_ORACLES)


def test_an_experiment_oracle_failure_is_recorded_not_quarantined(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    res = _run(case, scene, tmp_path, oracles=_full_oracles(fail="assert_neighbour_glyphs_unchanged"))
    assert res.quarantine == []
    assert res.oracles_run["assert_neighbour_glyphs_unchanged"] == "forced failure detail"


def _raising_oracle(ctx):
    raise RuntimeError("oracle blew up")


def test_emit_rows_drops_an_experiment_row_whose_oracle_failed(tmp_path):
    """V4: a failed or raised experiment oracle is a finding; the rejected branch may not turn it into a candidate."""
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)

    def rejected_report(res):
        assert res.outcome == "rederived", (res.quarantine, res.divergences)
        report = rd.build_report("batch", [_set_status(res, "splice_pass")], head="deadbeef", validation_sha256="0" * 64)
        result = report["results"][0]
        assert result["at_head"]["committed"] is None
        # HEAD refuses the edit the experiment proved: the rejected branch decides the row
        result["at_head"]["max_tier_1"] = {**result["at_head"]["max_tier_1"], "result": "rejected", "reason": "growth_region_not_blank"}
        return report

    # all six oracles pass: the row is emitted as before
    report = rejected_report(_run(case, scene, tmp_path, oracles=_full_oracles()))
    assert all(v is None for v in report["results"][0]["oracles_run"].values())
    rows, findings = rd.emit_rows([case], report, {"F30B": {}})
    assert [r["state"] for r in rows] == ["candidate"] and findings == []
    # one oracle fails: no row, one finding naming case and oracle
    report = rejected_report(_run(case, scene, tmp_path, oracles=_full_oracles(fail="assert_neighbour_glyphs_unchanged")))
    rows, findings = rd.emit_rows([case], report, {"F30B": {}})
    assert rows == []
    assert findings == [{"kind": "remeasure_oracle_failed", "case_id": case["case_id"], "oracle": "assert_neighbour_glyphs_unchanged"}]
    # one oracle raises: same refusal
    report = rejected_report(_run(case, scene, tmp_path, oracles={**_full_oracles(), "assert_glyph_identity": _raising_oracle}))
    assert report["results"][0]["oracles_run"]["assert_glyph_identity"] == "oracle raised RuntimeError"
    rows, findings = rd.emit_rows([case], report, {"F30B": {}})
    assert rows == []
    assert findings == [{"kind": "remeasure_oracle_failed", "case_id": case["case_id"], "oracle": "assert_glyph_identity"}]


def test_a_null_mutation_negative_stays_rederived_without_the_oracles(tmp_path):
    scene, _positive, negative = _emit_inputs(tmp_path)
    res = _run(negative, scene, tmp_path)
    assert res.outcome == "rederived" and res.deferred is None


# ---- the CLI: attribution of validator violations ---------------------------------------------------
def _public_list(tmp_path, scene) -> Path:
    public = tmp_path / "public.json"
    public.write_text(json.dumps({"schema": "public-corpus-sha256/1", "files": [{"relative_path": scene.rel, "sha256": scene.sha, "origin": "sample-files-main", "lineage_id": scene.slug}]}), encoding="utf-8")
    return public


def _cli(tmp_path, scene, batch, validation: dict):
    path = tmp_path / "validation.json"
    path.write_text(json.dumps(_complete(validation, batch)), encoding="utf-8")
    out = tmp_path / "out" / "rederive_report.json"
    code = rd.main(["rederive", str(batch), "--validation", str(path), "--out", str(out), "--repo-root", str(tmp_path), "--public-list", str(_public_list(tmp_path, scene)), "--no-acc"])
    return code, out


def test_cli_matches_a_validator_rejection_reported_under_a_digest(tmp_path):
    """The real validator prints a case id outside the r2 shape as a digest, in case_id and in the file path."""
    scene = _scene(tmp_path)
    ok = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    bad = _edit(ok, ("/case_id", "evil_case"))
    batch = _write_batch(tmp_path, [ok, bad])
    found = eb.validate_batch(batch)["violations"]
    mine = [v for v in found if v["file"].startswith("cases/#")]
    assert mine and all(v["case_id"] == eb._show_id("evil_case") for v in mine)
    # the hand-made batch lacks its batch files and carries a code-revision block: keep what the validator pins on a case
    case_level = [v for v in found if (v["case_id"] is not None or v["file"].startswith("cases/")) and not rd._is_batch_level(v)]
    code, out = _cli(tmp_path, scene, batch, {"violations": case_level, "unverifiable": []})
    assert code in (0, 1)
    by_id = {r["case_id"]: r for r in json.loads(out.read_text(encoding="utf-8"))["results"]}
    assert by_id[eb._show_id("evil_case")]["outcome"] == "validator_rejected"
    assert by_id[eb._show_id("evil_case")]["at_head"] == {}


def test_cli_refuses_a_violation_that_belongs_to_no_case(tmp_path):
    scene = _scene(tmp_path)
    ok = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    batch = _write_batch(tmp_path, [ok])
    for code_word, file in (
        ("calibration_mismatch", "PARENT_SUMMARY.json"),
        ("class_state_overclaim", "PARENT_SUMMARY.json"),
        ("growth_canary_site", "PARENT_SUMMARY.json"),
        ("denylist_hit", "README.md"),
        ("machine_path", "run_pilot.py"),
        ("png_name", "cases/elsewhere/foo.png"),
        ("pdf_location", "stray.pdf"),
        ("unexpected_file", "notes.txt"),
        ("lineage_mismatch", "cases.json"),
    ):
        code, out = _cli(tmp_path, scene, batch, {"violations": [{"code": code_word, "file": file, "pointer": "", "detail": "", "case_id": None}], "unverifiable": []})
        assert code == 2, code_word
        assert not out.exists(), code_word


def test_cli_carries_the_recomputed_status_into_the_report(tmp_path):
    scene = _scene(tmp_path)
    ok = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    batch = _write_batch(tmp_path, [ok])
    validation = {"violations": [], "unverifiable": [], "recomputed": {"statuses": {ok["case_id"]: "save_reopen_pass"}}}
    code, out = _cli(tmp_path, scene, batch, validation)
    assert code in (0, 1)
    results = json.loads(out.read_text(encoding="utf-8"))["results"]
    assert [r["validated_status"] for r in results] == ["save_reopen_pass"]


# ---- self-reported fields that rederive can read off the file --------------------------------------
def test_page_rotation_page_count_and_char_count_old_are_recomputed(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    for pointer, value, field in (
        ("/source/page_rotation", 0, "source.page_rotation"),
        ("/source/page_count", 9, "source.page_count"),
        ("/mutation/advance/char_count_old", 9, "char_count_old"),
    ):
        res = _run(_edit(case, (pointer, value)), scene, tmp_path, oracles=_full_oracles())
        assert res.quarantine == ["remeasure"], pointer
        assert field in _fields(res), (pointer, _fields(res))


def test_a_refusal_detail_that_is_not_the_products_is_a_divergence(tmp_path):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_LONGER, kind="negative", variant="neg", expected_reason="growth_region_not_blank")
    res = _run(_edit(case, ("/probe/max_tier_1/detail", "glyphs: 0 character(s) already occupy the growth zone")), scene, tmp_path, oracles=_full_oracles())
    assert res.quarantine == ["remeasure"]
    assert "detail" in _fields(res)


# ---- F3: the two-string fragment split ---------------------------------------------------------------
def _fragment_scene_case(tr: Truth, new_op: bytes, byte_range: list[int]) -> dict:
    item = [tr.show.string_start, tr.show.string_end]
    changes = _changes(tr, tr.show.op_start, tr.show.op_end, new_op)
    return {
        "mutation": {"splice_kind": "fragment_split", "changes": changes},
        "corpus_case": {"font_kind": "type0"},
        "glyph_identity": _glyphs("再"),
        "target": {"item_range": item, "byte_range_in_item": byte_range},
    }


def _fragment_divergences(tmp_path, build) -> list[str]:
    scene = _scene(tmp_path)
    tr = Truth(scene.path)
    try:
        old = tr.show.decoded_bytes
        mid = tb.encode_cids("再")
        new_op = build(old, mid)
        case = _fragment_scene_case(tr, new_op, build.byte_range)
        doc = fitz.open(str(scene.path))
        fake = type("S", (), {})()
        fake.case, fake.doc, fake.closed = case, doc, set()
        divs: list = []
        rd._check_changes(fake, divs)
        doc.close()
        return [d.field for d in divs]
    finally:
        tr.close()


def _split_head(old: bytes, mid: bytes) -> bytes:  # bytes [0, 2) replaced: (middle)(suffix)
    return b"[<" + mid.hex().upper().encode() + b"> <" + old[2:].hex().upper().encode() + b">] TJ"


_split_head.byte_range = [0, 2]  # type: ignore[attr-defined]


def _split_tail(old: bytes, mid: bytes) -> bytes:  # the last two bytes replaced: (prefix)(middle)
    return b"[<" + old[:-2].hex().upper().encode() + b"> <" + mid.hex().upper().encode() + b">] TJ"


_split_tail.byte_range = [6, 8]  # type: ignore[attr-defined]


def _split_head_wrong_suffix(old: bytes, mid: bytes) -> bytes:
    return b"[<" + mid.hex().upper().encode() + b"> <" + old[4:].hex().upper().encode() + b"0000>] TJ"


_split_head_wrong_suffix.byte_range = [0, 2]  # type: ignore[attr-defined]


def test_an_honest_two_string_fragment_split_is_not_a_prefix_mismatch(tmp_path):
    assert "fragment_prefix_mismatch" not in _fragment_divergences(tmp_path, _split_head)
    assert "fragment_prefix_mismatch" not in _fragment_divergences(tmp_path / "tail", _split_tail)


def test_a_two_string_fragment_split_with_the_wrong_suffix_is_a_prefix_mismatch(tmp_path):
    assert "fragment_prefix_mismatch" in _fragment_divergences(tmp_path, _split_head_wrong_suffix)


# ---- R1-2: the simple-font (F30) remeasure branch ------------------------------------------------------
_HELV = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


def _helv_doc(stream: bytes) -> fitz.Document:
    """One page, /F1 = Helvetica (the ``test_text_commit_decision_chain._stream_doc`` recipe, copied: that module is a test file)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    content = doc.get_new_xref()
    doc.update_object(content, "<<>>")
    doc.update_stream(content, stream)
    doc.xref_set_key(page.xref, "Contents", f"{content} 0 R")
    font = doc.get_new_xref()
    doc.update_object(font, _HELV)
    doc.xref_set_key(page.xref, "Resources", f"<< /Font << /F1 {font} 0 R >> >>")
    return doc


def _helv_case(doc: fitz.Document):
    """``iii`` -> ``iiii`` in Helvetica (i = 222/1000 em): 7.992 -> 10.656 at 12 pt, the Slice 1 escalation shape."""
    replay = replay_page_streams([(x, doc.xref_stream(x)) for x in doc[0].get_contents()])
    show = replay.shows[0]
    stream = doc.xref_stream(show.stream_xref)
    cap = DocumentFontRegistry(doc).capability(doc[0], show.font_resource)
    adv_old, adv_new = _plan_advance(cap, "iii", 12.0, 0.0, 0.0), _plan_advance(cap, "iiii", 12.0, 0.0, 0.0)
    eng = kern_for_displacement(show, adv_old - adv_new)
    new_op = b"[(iiii) %.6f] TJ" % eng
    hand = 1000.0 * (adv_new - adv_old) / 12.0
    source = {"widths": "Widths", "face": "face"}[cap.advance_source]
    tol = max(1e-3 * 12.0, 1e-4) if source == "face" else max(1e-9 * 12.0, 1e-9)
    case = {
        "class_id": "F30B",
        "corpus_case": {"page_index": 0, "show_seq": 0, "font_kind": "simple"},
        "glyph_identity": [{"index": i, "char": "i", "is_space": False, "code_bytes_hex": "69"} for i in range(4)],
        "target": {},
        "mutation": {
            "splice_kind": "whole_operator",
            "changes": _changes_of(show, stream, new_op),
            "advance": {
                "K_written": eng,
                "K_sum": 0.0,
                "K_disp_engine": eng,
                "K_disp_hand": hand,
                "abs_diff_written_vs_sum_engine": 0.0,
                "abs_diff_engine_hand": abs(eng - hand),
                "displacement": adv_old - adv_new,
                "adv_old_text_space": adv_old,
                "adv_new_text_space": adv_new,
                "advance_tolerance": tol,
                "Tfs": 12.0,
                "Th": 1.0,
                "Tc": 0.0,
                "Tw": 0.0,
                "char_count_old": 3,
                "char_count_new": 4,
                "advance_source": source,
                "advance_function": "plan._advance/FontCapability.string_width",
                "internal_kerns_dropped": [],
            },
        },
    }
    return case, show, source


def _changes_of(show, stream: bytes, new_op: bytes) -> list[dict]:
    return [{"stream_xref": show.stream_xref, "start": show.op_start, "end_old": show.op_end, "old_operand_bytes_hex": None, "new_operand_bytes_hex": new_op.hex().upper()}]


def test_simple_font_remeasure_agrees_with_the_independent_helvetica_widths():
    doc = _helv_doc(b"BT /F1 12 Tf 72 700 Td (iii) Tj /F1 9 Tf (            tail) Tj ET")
    try:
        case, show, _source = _helv_case(doc)
        measured, divs = rd.remeasure_advances(case, doc, show)
        assert [d.field for d in divs if d.field in ("adv_old_text_space", "adv_new_text_space", "advance_source", "K_disp_engine", "K_sum", "abs_diff_written_vs_sum_engine")] == []
        assert measured["adv_old"] == pytest.approx(7.992, abs=1e-3)  # 3 x 222 x 12 / 1000
        assert measured["adv_new"] == pytest.approx(10.656, abs=1e-3)
    finally:
        doc.close()


def test_simple_font_k_and_advance_source_forgeries_are_divergences():
    doc = _helv_doc(b"BT /F1 12 Tf 72 700 Td (iii) Tj /F1 9 Tf (            tail) Tj ET")
    try:
        case, show, source = _helv_case(doc)
        bumped = copy.deepcopy(case)
        bumped["mutation"]["advance"]["K_written"] += 1e-3
        _, divs = rd.remeasure_advances(bumped, doc, show)
        assert "abs_diff_written_vs_sum_engine" in [d.field for d in divs]
        other = copy.deepcopy(case)
        other["mutation"]["advance"]["advance_source"] = "face" if source == "Widths" else "Widths"
        _, divs = rd.remeasure_advances(other, doc, show)
        assert "advance_source" in [d.field for d in divs]
        wide = copy.deepcopy(case)
        wide["mutation"]["advance"]["adv_new_text_space"] += 1.0
        _, divs = rd.remeasure_advances(wide, doc, show)
        assert "adv_new_text_space" in [d.field for d in divs]
    finally:
        doc.close()


# ==========================================================================
# fix round 2: reviewer findings on the rederive half, each written red first
# ==========================================================================
def _hscale_prepare(fx):
    stream = fx.content_bytes()
    assert b" Tf " in stream
    fx.doc.update_stream(fx.content_xref, stream.replace(b" Tf ", b" Tf 110 Tz ", 1))


def test_a_tier1_row_with_a_non_identity_hscale_agrees_with_the_built_in_growth_oracle(tmp_path):
    """Tz 110, size 13.9, x 200: ``adv_old * show.hscale / 100`` and the product's ``source_advance * (hscale / 100)`` differ in the last bit."""
    scene = _scene(tmp_path, tail=None, fontsize=13.9, origin=(200.0, 700.0), prepare=_hscale_prepare)
    case = _product_record(scene, tb.REPLACEMENT_LONGER, variant="grow")
    assert case["probe"]["max_tier_1"]["tier"] == 1
    assert case["text_state"]["before"]["Tz"] == 110.0
    oracles = _full_oracles()
    oracles["assert_growth_zone_was_blank"] = rd.assert_growth_zone_was_blank
    res = _run(case, scene, tmp_path, oracles=oracles)
    assert res.outcome == "rederived", (res.quarantine, res.divergences, res.oracles_run)
    assert res.oracles_run["assert_growth_zone_was_blank"] is None


def test_parse_array_keeps_the_index_of_every_entry():
    assert rd._parse_array("[5 0 R null 7 0 R]") == [("ref", 5), None, ("ref", 7)]
    got = rd._parse_array("[5 0 R /Foo (a 3 0 R) 7 0 R]")
    assert [e[1] if isinstance(e, tuple) and e[0] == "ref" else None for e in got] == [5, None, None, 7]
    got = rd._parse_array("[ 1 (a \\) b (nested) 9 0 R) <aabb> << /K 4 0 R /N [ 6 0 R ] >> true 8 0 R ]")
    assert [e[1] if isinstance(e, tuple) and e[0] == "ref" else None for e in got] == [None, None, None, None, None, 8]
    assert len(got) == 6


def _null_tree_prepare(fx):
    doc = fx.doc
    tb.wrap_content_in_marked_content(fx, "/P <</MCID 1>> BDC")
    root = doc.get_new_xref()
    parent_tree = doc.get_new_xref()
    elem = doc.get_new_xref()
    doc.update_object(elem, f"<< /Type /StructElem /S /P /P {root} 0 R /K 1 /Lang (en) >>")
    doc.update_object(parent_tree, f"<< /Nums [ 0 [ null {elem} 0 R ] ] >>")
    doc.update_object(root, f"<< /Type /StructTreeRoot /K {elem} 0 R /ParentTree {parent_tree} 0 R >>")
    doc.xref_set_key(doc.pdf_catalog(), "StructTreeRoot", f"{root} 0 R")
    doc.xref_set_key(fx.page.xref, "StructParents", "0")


def test_a_null_parent_tree_entry_does_not_shift_the_mcid_lookup(tmp_path):
    scene = _scene(tmp_path, slug="nulltree", tail=None, prepare=_null_tree_prepare)
    case = _experiment_record(scene, class_id="F1", variant="grow")
    honest = _edit(case, ("/text_state/before/wrapper_stack/0/structelem_keys", ["Lang"]))
    res = _run(honest, scene, tmp_path, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    for keys in ([], None, ["ActualText"]):
        bad = _edit(case, ("/text_state/before/wrapper_stack/0/structelem_keys", keys))
        res = _run(bad, scene, tmp_path, oracles=_full_oracles())
        assert "structelem_keys" in _fields(res), keys


def test_a_fragment_item_range_outside_the_change_is_a_divergence(tmp_path):
    """The H1 remeasure reads the item the record points at; a pointer outside the edited operator steers it."""
    scene = _scene(tmp_path)  # the tail page: a second show follows the target

    def run(pick_item):
        tr = Truth(scene.path)
        try:
            tail = tr.replay.shows[1]
            mid = tb.encode_cids("再")
            new_op = _split_head(tr.show.decoded_bytes, mid)
            case = _fragment_scene_case(tr, new_op, [0, 2])
            case["target"]["item_range"] = pick_item(tr, tail)
            doc = fitz.open(str(scene.path))
            fake = type("S", (), {})()
            fake.case, fake.doc, fake.closed = case, doc, set()
            divs: list = []
            rd._check_changes(fake, divs)
            doc.close()
            return [d.field for d in divs], fake.closed
        finally:
            tr.close()

    honest, closed = run(lambda tr, tail: [tr.show.string_start, tr.show.string_end])
    assert "fragment_item_range" not in honest
    assert "fragment_prefix_mismatch" in closed
    moved, closed = run(lambda tr, tail: [tail.string_start, tail.string_end])
    assert "fragment_item_range" in moved
    assert "fragment_prefix_mismatch" not in closed
    not_a_token, _ = run(lambda tr, tail: [tr.show.string_start + 1, tr.show.string_end])
    assert "fragment_item_range" in not_a_token


def _complete(validation: dict, batch: Path) -> dict:
    """Tie a hand-made validation report to ``batch`` the way the validator does."""
    out = {"schema": "evidence-validation/1", "batch": batch.name, "cases_json_sha256": _sha((batch / "cases.json").read_bytes())}
    out.update(validation)
    return out


def test_a_validation_report_must_belong_to_the_batch(tmp_path):
    scene = _scene(tmp_path)
    ok = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    batch = _write_batch(tmp_path, [ok])
    good = _complete({"violations": [], "unverifiable": [], "recomputed": {"statuses": {}}}, batch)
    out = tmp_path / "out" / "rederive_report.json"
    base = ["rederive", str(batch), "--out", str(out), "--repo-root", str(tmp_path), "--public-list", str(_public_list(tmp_path, scene)), "--no-acc"]

    def attempt(validation: dict) -> int:
        path = tmp_path / "validation.json"
        path.write_text(json.dumps(validation), encoding="utf-8")
        return rd.main([*base, "--validation", str(path)])

    assert attempt(good) in (0, 1)
    out.unlink()
    for label, bad in (
        ("empty", {}),
        ("other schema", {**good, "schema": "evidence-validation/0"}),
        ("other batch", {**good, "batch": "20250101_0000_r2"}),
        ("stale cases", {**good, "cases_json_sha256": "0" * 64}),
        ("no cases digest", {k: v for k, v in good.items() if k != "cases_json_sha256"}),
    ):
        assert attempt(bad) == 2, label
        assert not out.exists(), label


def test_a_fixture_registered_proprietary_but_claimed_public_never_prints_details_verbatim(tmp_path):
    """The detail text is templated unless the REGISTRY says the source is public (the bundle's claim is not evidence)."""
    scene = _scene(tmp_path, provenance="proprietary")
    case = _product_record(scene, tb.REPLACEMENT_LONGER, kind="negative", variant="neg", expected_reason="growth_region_not_blank", provenance="public")
    assert case["source"]["provenance"] == "public"
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert "provenance_unverified" in res.quarantine
    detail = res.at_head["max_tier_1"]["detail"]
    assert re.fullmatch(r"glyphs: #[0-9a-f]{12}", detail), detail


def test_rederive_without_a_work_dir_removes_its_scratch_copies(tmp_path, monkeypatch):
    import tempfile

    scratch = tmp_path / "tmproot"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    batch = tmp_path / "batch"
    batch.mkdir()
    _write_records(batch, case)
    res = rd.rederive_case(case, batch, scene.registry, oracles=_full_oracles())
    assert res.outcome == "rederived", (res.quarantine, res.divergences)
    assert list(scratch.iterdir()) == []
    other = _scene(tmp_path, slug="fx-b", tail=None)
    other_case = _experiment_record(other)
    _write_records(batch, other_case)
    rd.replay_experiment(other_case, batch, other.registry, oracles=_full_oracles())
    assert list(scratch.iterdir()) == []


def test_the_raw_to_visual_after_box_frame_is_a_closed_unverifiable(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    honest = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert "after_bbox_frame" in honest.closed_unverifiable
    raw = list(case["target"]["after_bbox_raw"])
    raw[2] += 10.0
    res = _run(_edit(case, ("/target/after_bbox_raw", raw)), scene, tmp_path, oracles=_full_oracles())
    assert "after_bbox_visual" in _fields(res)
    assert res.quarantine == ["remeasure"]


def test_denylist_missing_is_classified_batch_level():
    """V6: a missing redaction denylist is owned by no case and must refuse the whole batch."""
    assert rd._is_batch_level({"code": "denylist_missing", "file": "", "pointer": "", "case_id": None})


def test_rederive_refuses_a_self_check_validation(tmp_path, capsys):
    """V8: a --self-check VALIDATION skipped the DONE/self-validation presence rules, so it never gates a rederive."""
    batch = _write_batch(tmp_path, [])
    out = tmp_path / "out" / "rederive_report.json"
    base = ["rederive", str(batch), "--out", str(out), "--repo-root", str(ROOT)]
    for flag in (True, "true", 1, None):
        path = tmp_path / "validation.json"
        path.write_text(json.dumps(_complete({"violations": [], "unverifiable": [], "self_check": flag}, batch)), encoding="utf-8")
        assert rd.main([*base, "--validation", str(path)]) == 2, flag
        assert "validation_is_self_check" in capsys.readouterr().err, flag
        assert not out.exists(), flag
    path.write_text(json.dumps(_complete({"violations": [], "unverifiable": [], "self_check": False}, batch)), encoding="utf-8")
    assert rd.main([*base, "--validation", str(path)]) in (0, 1)
    assert "validation_is_self_check" not in capsys.readouterr().err


def _hvac_stand_in(tmp_path) -> tuple[Path, str]:
    """A synthetic PDF under ``tmp_path/test_files`` standing in for the proprietary hvac file."""
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "hvac stand-in")
    path = tmp_path / "test_files" / "hvac-dwg.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()
    return path, _sha(path.read_bytes())


def test_rederive_refuses_synthetic_only_when_hvac_resolves(tmp_path, monkeypatch, capsys):
    """V2: calibration synthetic_only is the fallback for a missing hvac file only; a resolvable hvac entry refuses."""
    _path, sha = _hvac_stand_in(tmp_path)
    monkeypatch.setattr(eb, "HVAC_SHA256", sha)
    batch = _write_batch(tmp_path, [])
    (batch / "PARENT_SUMMARY.json").write_text(json.dumps({"calibration": {"status": "synthetic_only"}}), encoding="utf-8")
    validation = tmp_path / "validation.json"
    validation.write_text(json.dumps(_complete({"violations": [], "unverifiable": []}, batch)), encoding="utf-8")
    out = tmp_path / "out" / "rederive_report.json"
    argv = ["rederive", str(batch), "--validation", str(validation), "--out", str(out), "--repo-root", str(tmp_path)]

    def registry_with(*entries):
        return lambda *_a, **_k: rd.CorpusRegistry(root=tmp_path, entries=tuple(entries))

    hvac = rd.RegistryEntry(slug="hvac", relative_path="test_files/hvac-dwg.pdf", sha256=sha, provenance="proprietary", lineage_id="hvac")
    renamed = rd.RegistryEntry(slug="other", relative_path="test_files/hvac-dwg.pdf", sha256=sha, provenance="proprietary", lineage_id="other")
    for entry in (hvac, renamed):
        monkeypatch.setattr(rd, "load_registry", registry_with(entry))
        assert rd.main(argv) == 2, entry.slug
        assert "synthetic_only_with_hvac_resolvable" in capsys.readouterr().err, entry.slug
        assert not out.exists(), entry.slug
    assert rd._is_batch_level({"code": "synthetic_only_with_hvac_resolvable", "file": "PARENT_SUMMARY.json", "case_id": None})
    # no hvac entry, or an hvac entry whose file is absent: this rule does not refuse
    absent = rd.RegistryEntry(slug="hvac", relative_path="test_files/missing.pdf", sha256=sha, provenance="proprietary", lineage_id="hvac")
    for entries in ((), (absent,)):
        monkeypatch.setattr(rd, "load_registry", registry_with(*entries))
        assert rd.main(argv) in (0, 1), entries
        assert "synthetic_only_with_hvac_resolvable" not in capsys.readouterr().err, entries
    # hvac resolves but the batch did not claim synthetic_only: this rule does not refuse
    monkeypatch.setattr(rd, "load_registry", registry_with(hvac))
    (batch / "PARENT_SUMMARY.json").write_text(json.dumps({"calibration": {"status": "pass"}}), encoding="utf-8")
    assert rd.main(argv) in (0, 1)
    assert "synthetic_only_with_hvac_resolvable" not in capsys.readouterr().err


# ---- V3: neighbours.glyphs_total is recounted from the before page ----------------------------------
def _page_glyphs(scene: Scene, page_index: int = 0) -> int:
    doc = fitz.open("pdf", scene.data)
    try:
        meas = fitz.open("pdf", doc.tobytes(encryption=fitz.PDF_ENCRYPT_KEEP))
        try:
            return sum(len(span["chars"]) for span in meas[page_index].get_texttrace())
        finally:
            meas.close()
    finally:
        doc.close()


def _total_divs(res) -> list:
    return [d for d in res.divergences if d.field == "neighbours_glyphs_total_mismatch"]


def test_a_records_file_of_only_the_target_glyphs_is_a_glyphs_total_divergence(tmp_path):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    page_total = _page_glyphs(scene)
    n_old = case["neighbours"]["target_glyphs_before"]
    assert page_total > n_old > 0  # the tail glyphs are real neighbours
    assert case["neighbours"]["glyphs_total"] == page_total - n_old
    honest = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert _total_divs(honest) == [] and honest.outcome == "rederived", honest.divergences
    forged = _edit(case, ("/neighbours/glyphs_total", n_old))
    targets_only = [{"role": "target", "trace_index_before": j, "trace_index_after": j} for j in range(n_old)]
    res = _run(forged, scene, tmp_path, oracles=_full_oracles(), records=targets_only)
    divs = _total_divs(res)
    assert len(divs) == 1, res.divergences
    assert divs[0].record == [n_old, 0]
    assert divs[0].recomputed == page_total - n_old
    assert res.outcome == "quarantined" and "remeasure" in res.quarantine


def test_an_honest_glyphs_total_with_a_short_records_file_is_a_divergence(tmp_path):
    scene = _scene(tmp_path, tail=None)
    case = _experiment_record(scene)
    page_total = _page_glyphs(scene)
    n_old = case["neighbours"]["target_glyphs_before"]
    short = [{"role": "target", "trace_index_before": j, "trace_index_after": j} for j in range(n_old)]
    if page_total == n_old:  # no neighbour on the page: one fabricated extra glyph is the short-count shape
        case = _edit(case, ("/neighbours/glyphs_total", 1))
    res = _run(case, scene, tmp_path, oracles=_full_oracles(), records=short)
    assert [d.record for d in _total_divs(res)] == [[case["neighbours"]["glyphs_total"], 0]], res.divergences
    assert "remeasure" in res.quarantine


def test_a_missing_or_misplaced_records_file_is_a_glyphs_total_divergence(tmp_path):
    scene = _scene(tmp_path)
    case = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    batch = tmp_path / "batch"
    res = _run(_edit(case, ("/neighbours/records_file", "cases/elsewhere/neighbours.json")), scene, tmp_path, oracles=_full_oracles())
    assert [d.record for d in _total_divs(res)] == [[case["neighbours"]["glyphs_total"], None]], res.divergences
    (batch / "cases" / case["case_id"] / "neighbours.json").write_text("{}", encoding="utf-8")
    res = rd.rederive_case(case, batch, scene.registry, oracles=_full_oracles(), work_dir=tmp_path / "work")
    assert [d.record for d in _total_divs(res)] == [[case["neighbours"]["glyphs_total"], None]], res.divergences
    no_block = {k: v for k, v in case.items() if k != "neighbours"}
    res = rd.rederive_case(no_block, batch, scene.registry, oracles=_full_oracles(), work_dir=tmp_path / "work")
    assert [d.recomputed for d in _total_divs(res)] == [None], res.divergences


def test_a_null_mutation_row_may_carry_an_empty_records_file(tmp_path):
    scene, _positive, negative = _emit_inputs(tmp_path)
    assert negative["mutation"] is None
    res = _run(negative, scene, tmp_path, records=[])
    assert _total_divs(res) == [] and res.outcome == "rederived", res.divergences
    forged = _edit(negative, ("/neighbours/glyphs_total", negative["neighbours"]["glyphs_total"] + 1))
    res = _run(forged, scene, tmp_path, records=[])
    assert [d.record for d in _total_divs(res)] == [[forged["neighbours"]["glyphs_total"], 0]], res.divergences


# --------------------------------------------------------------------------
# R7-1: a brief v3 tj_run's verify strip is re-measured from the INK displacement
# --------------------------------------------------------------------------
F2G_KERN = 30.0
F2G_TFS = 24.0


def _kerned_tj(fx) -> None:
    """Respell the hex ``Tj`` as ``[<first three CIDs> 30 <last CID>] TJ``: a tightening internal kern."""
    codes = tb.encode_cids(fx.text)
    stream = fx.content_bytes()
    plain = b"<" + codes.hex().upper().encode("ascii") + b"> Tj"
    split = f"[<{codes[:-2].hex().upper()}> {F2G_KERN:g} <{codes[-2:].hex().upper()}>] TJ".encode("ascii")
    assert stream.count(plain) == 1
    fx.doc.update_stream(fx.content_xref, stream.replace(plain, split))


def _in_array_range(case: dict, stream: bytes) -> None:
    """Re-point the first change from the whole ``[...] TJ`` operator to the in-array run inside the brackets.

    The spliced stream is byte-identical; only the recorded range and operands become the real tj_run shape
    (old ``<..> 30 <..>``, new ``<..> K``) the validator's grammar expects.
    """
    change = case["mutation"]["changes"][0]
    start, end_old = change["start"], change["end_old"]
    old_op, new_op = stream[start:end_old], bytes.fromhex(change["new_operand_bytes_hex"])
    inner_start = start + old_op.index(b"[") + 1
    inner_end = start + old_op.rindex(b"]")
    new_inner = new_op[new_op.index(b"[") + 1 : new_op.rindex(b"]")]
    assert stream[:inner_start] + new_inner + stream[inner_end:] == stream[:start] + new_op + stream[end_old:]
    change.update(
        {
            "start": inner_start,
            "end_old": inner_end,
            "end_new": inner_start + len(new_inner),
            "old_operand_bytes_hex": stream[inner_start:inner_end].hex().upper(),
            "old_operand_sha256": _sha(stream[inner_start:inner_end]),
            "new_operand_bytes_hex": new_inner.hex().upper(),
            "new_operand_token_kinds": [t.kind.name for t in lex_content_stream(new_inner) if t.kind is not TokenKind.WHITESPACE],
        }
    )


def _f2g_record(tmp_path, *, rev: int, replacement: str = tb.REPLACEMENT_LONGER, in_array: bool = False):
    """An honest F2G tj_run at Tf 24 whose recorded verify strip is sized by delta + K_sum * Tfs / 1000.

    Under rev 3 the advance carries ``displacement_ink`` and the ink-sized ``growth_pt`` (brief 3.3 R7-1).
    """
    scene = _scene(tmp_path, slug="kerned", tail=None, fontsize=F2G_TFS, prepare=_kerned_tj)
    case = _experiment_record(
        scene, replacement=replacement, class_id="F2G", method_id="E_F2G", splice_kind="tj_run", k_sum=F2G_KERN
    )
    adv = case["mutation"]["advance"]
    adv["internal_kerns_dropped"] = [F2G_KERN]
    tr = Truth(scene.path)
    try:
        assert tr.show.font_size == F2G_TFS and tr.show.operator == "TJ"
        if in_array:
            _in_array_range(case, tr.stream)
        ink = eb._ink_displacement(adv["adv_new_text_space"] - adv["adv_old_text_space"], F2G_KERN, F2G_TFS)
        verify_vis = _grown_verify_bbox(tr.page, tr.show, tuple(tr.bbox_vis), ink * tr.th, frame=tr.frame)
        case["target"]["verify_bbox_visual"] = _box(verify_vis)
        case["growth_zone"] = _growth_block(tr, verify_vis, adv["adv_old_text_space"])
        if rev == 3:
            adv["displacement_ink"] = ink
            adv["growth_pt"] = max(0.0, ink) * tr.th * tr.trm * tr.frame.user_unit
    finally:
        tr.close()
    case["brief_revision"] = rev
    return scene, case


def test_an_honest_v3_tj_run_with_tightening_kerns_remeasures_within_the_bound(tmp_path):
    scene, case = _f2g_record(tmp_path, rev=3)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    fields = _fields(res)
    assert "verify_bbox_visual" not in fields and "after_bbox_extent" not in fields, res.divergences
    assert "K_sum" not in fields and "abs_diff_written_vs_sum_engine" not in fields, res.divergences
    assert "k_sum_unverified" in res.closed_unverifiable


def test_the_same_tj_run_at_rev2_is_still_remeasured_by_the_delta(tmp_path):
    """The ink sizing is gated on the row's own brief_revision: a rev2 row keeps the delta-sized strip."""
    scene, case = _f2g_record(tmp_path, rev=2)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert {"verify_bbox_visual", "after_bbox_extent"} <= set(_fields(res)), res.divergences
    assert "k_sum_unverified" not in res.closed_unverifiable  # the validator never emits it on a rev 2 row


def test_a_v3_tj_run_whose_old_operand_cannot_be_read_is_not_sized_by_a_guess(tmp_path, monkeypatch):
    scene, case = _f2g_record(tmp_path, rev=3)
    monkeypatch.setattr(rd, "_first_change_old", lambda _scene: None)
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert "displacement_ink" in _fields(res), res.divergences
    assert res.quarantine and "remeasure" in res.quarantine


def test_an_f2r_shaped_v3_tj_run_with_equal_advances_remeasures_within_the_bound(tmp_path):
    """Equal advances, +30 kern at Tf 24: the 0.72 pt ink growth is applicable and its strip is re-measured from it."""
    scene, case = _f2g_record(tmp_path, rev=3, replacement=tb.REPLACEMENT_EQUAL_ADVANCE)
    adv = case["mutation"]["advance"]
    assert abs(adv["adv_new_text_space"] - adv["adv_old_text_space"]) <= adv["advance_tolerance"]
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    fields = _fields(res)
    assert "verify_bbox_visual" not in fields and "after_bbox_extent" not in fields, res.divergences
    assert "displacement_ink" not in fields, res.divergences
    assert res.remeasured["displacement_ink"] == pytest.approx(F2G_KERN * F2G_TFS / 1000.0, abs=1e-9)


def test_a_forged_v3_displacement_ink_is_a_divergence(tmp_path):
    scene, case = _f2g_record(tmp_path, rev=3)
    case["mutation"]["advance"]["displacement_ink"] += 0.5
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    assert "displacement_ink" in _fields(res), res.divergences


def test_an_in_array_v3_tj_run_range_remeasures_within_the_bound(tmp_path):
    """The real tj_run shape: the change covers ``<..> 30 <..>`` inside the brackets, not the whole operator."""
    scene, case = _f2g_record(tmp_path, rev=3, in_array=True)
    old = bytes.fromhex(case["mutation"]["changes"][0]["old_operand_bytes_hex"])
    assert not old.startswith(b"[") and f" {F2G_KERN:g} ".encode("ascii") in old
    assert eb.check_operand_grammar(case).violations == []
    res = _run(case, scene, tmp_path, oracles=_full_oracles())
    fields = _fields(res)
    assert "verify_bbox_visual" not in fields and "after_bbox_extent" not in fields, res.divergences
    assert "displacement_ink" not in fields and "K_sum" not in fields, res.divergences
    assert res.remeasured["displacement_ink"] == pytest.approx(case["mutation"]["advance"]["displacement_ink"], abs=1e-9)


# ---- V11: a plan-row violation attributed by the validator rejects only its case ------------------
def _plan_block(cases: list[dict]) -> dict:
    rows = []
    for case in cases:
        rows.append(
            {
                "class_id": case["class_id"],
                "slug": case["source"]["slug"],
                "page_index": case["corpus_case"]["page_index"],
                "show_seq": case["corpus_case"]["show_seq"],
                "variant": re.sub(r"[0-9]+$", "", case["case_id"].rsplit("-", 1)[1]),
                "method_id": case["mutation"]["method_id"] if case["mutation"] else None,
                "expected_reason": case["corpus_case"]["expected_reason"],
                "hypotheses": [],
            }
        )
    return {"pre_registration": "true-text-plan/2", "cases": rows}


def test_cli_a_plan_row_violation_rejects_only_the_case_that_cites_the_row(tmp_path):
    """End to end: the real validator attributes the row defect, so the rest of the batch is measured, not refused."""
    scene = _scene(tmp_path)
    ok = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    bad = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE, variant="grow")  # a different registration key from ok
    batch = _write_batch(tmp_path, [ok, bad])
    plan = _plan_block([ok, bad])
    plan["cases"][1]["hypotheses"] = ["a", "b", "c", "d"]
    (batch / "METHODS_AND_EVIDENCE_PLAN.md").write_text("# Plan\n\n```json\n" + json.dumps(plan) + "\n```\n", encoding="utf-8")
    found = eb.validate_batch(batch)["violations"]
    plan_level = [v for v in found if v["file"] == "METHODS_AND_EVIDENCE_PLAN.md"]
    assert [(v["code"], v["pointer"]) for v in plan_level] == [("schema_max_items", "/cases/1/hypotheses")]
    code, out = _cli(tmp_path, scene, batch, {"violations": plan_level, "unverifiable": []})
    assert code in (0, 1), "the batch was refused although the row defect belongs to one case"
    by_id = {r["case_id"]: r for r in json.loads(out.read_text(encoding="utf-8"))["results"]}
    assert by_id[bad["case_id"]]["outcome"] == "validator_rejected"
    assert by_id[bad["case_id"]]["at_head"] == {}
    assert by_id[ok["case_id"]]["outcome"] in {"rederived", "deferred", "quarantined"}


def test_cli_still_refuses_a_plan_violation_that_names_no_case(tmp_path):
    """Lock (green before V11): a plan-file violation with case_id None is batch-level, whatever its code."""
    scene = _scene(tmp_path)
    ok = _product_record(scene, tb.REPLACEMENT_EQUAL_ADVANCE)
    batch = _write_batch(tmp_path, [ok])
    for code_word, pointer in (("schema_pattern", "/cases/0/slug"), ("schema_enum", "/cases/0/variant"), ("schema_const", "/pre_registration")):
        code, out = _cli(tmp_path, scene, batch, {"violations": [{"code": code_word, "file": "METHODS_AND_EVIDENCE_PLAN.md", "pointer": pointer, "detail": "", "case_id": None}], "unverifiable": []})
        assert code == 2, code_word
        assert not out.exists(), code_word
