"""Pure invariants of the true-text corpus manifest (frontier design 2a, slice I0a).

No fixture PDFs, no fitz, no Qt: this module runs in the CI lane and pins the
tracked ``test_scripts/fixtures/true_text_corpus/manifest.json`` and the loader
``test_scripts/true_text_corpus.py``.

Every invariant is a ``check_*`` function over the parsed JSON.  The test that
runs it on the tracked manifest is paired with a mutation test that runs the
same function on a small synthetic manifest and proves it can fail, so a
manifest that happens to hold no row of some shape (no refusal rows, no
frontier rows yet) cannot turn an invariant into a vacuous green.
"""
from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model.text_commit.dto import RejectReason  # noqa: E402
from scripts.hooks.pre_commit_device_guard import PATTERNS  # noqa: E402
from test_scripts import true_text_corpus as ttc  # noqa: E402

MANIFEST = ROOT / "test_scripts" / "fixtures" / "true_text_corpus" / "manifest.json"
PUBLIC_LIST = ROOT / "test_scripts" / "fixtures" / "public_corpus_sha256.json"
BRIEF_V5 = ROOT / "plans" / "grok-briefs" / "brief-v5.md"

NON_PUBLIC = ("local_unrecorded", "proprietary")
REASONS = {value for name, value in vars(RejectReason).items() if name.isupper() and isinstance(value, str)}

#: brief v5 names these local sources; slug -> (provenance, sha256).  The first four are the G2
#: ``local_unrecorded`` files, then the three ``proprietary`` registrations (acceptance corpora
#: and decision 7).
BRIEF_CORPORA = {
    "test-colored-background": ("local_unrecorded", "00640a01cecf0bfdf58bf72d6cbd20957ef98dcfc87b32f7f8b9e4a42eb36dba"),
    "test-horizontal-texts": ("local_unrecorded", "e1c4920a310de4c894b70b037b6f935668405f41858800419c541c9e0028e3c4"),
    "test-hierarchy-bookmarks": ("local_unrecorded", "f93ba509283b805c629a48d2adc0b3a3a21412b8437fde1de28a5ae773fa5a78"),
    "test-complexed-layout": ("local_unrecorded", "faefb744200aad617504802b72fd20c7525bab203f849f22a38af07f127bedf3"),
    "office-report-23p": ("proprietary", "880a637fe94734411fda89043e7abbe060b938b7a6dd09c04292bca19f8b320f"),
    "hvac": ("proprietary", "9da93de982145c46af0d34a978b4bbaa1167f0937327dedb44ecad4d50fca0a2"),
    "ecc": ("proprietary", "0f75dd10ed77214c5cf159d40f909cd402231761886cb0ed3821368ac0ab1853"),
}
#: A sha the brief names that is neither public nor registered: census-only (F4, "page content has
#: no show", brief v5 3.2), so it needs no manifest row.
BRIEF_CENSUS_ONLY = {"2cdee708c3a8ff01b3e7e7ebad500323a879f3a9d82ac369fcf6b87094564347"}


def _data() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _brief_revision() -> int:
    numbers = [int(m.group(1)) for p in (ROOT / "plans" / "grok-briefs").glob("brief-v*.md") if (m := re.fullmatch(r"brief-v(\d+)\.md", p.name))]
    return max(numbers)


def _provenance_by_slug(data: dict) -> dict[str, str]:
    return {c["slug"]: c["provenance"] for c in data["corpora"]}


def _sha_by_slug(data: dict) -> dict[str, str]:
    return {c["slug"]: c["sha256"] for c in data["corpora"]}


# ----------------------------------------------------------------------------------------------
# invariants (data -> list of violation strings; [] = holds)
# ----------------------------------------------------------------------------------------------
def check_historic_fourteen(data: dict) -> list[str]:
    rows = [r for r in data["cases"] if r["class_id"] == "historic"]
    got = Counter(
        (r["slug"], r["page_index"], r["show_seq"], r["replacement"], r["expected_tj_compensation"], r["original_sha256"])
        for r in rows
    )
    out: list[str] = []
    if got != Counter(ttc.HISTORIC_FOURTEEN):
        out.append(f"historic rows differ from HISTORIC_FOURTEEN: {len(rows)} rows")
    for r in rows:
        want = ttc.HISTORIC_FONTS.get((r["slug"], r["page_index"], r["show_seq"]))
        if want != (r["font_resource"], r["basefont"], r["font_kind"]):
            out.append(f"{r['key']}: font identity differs from HISTORIC_FONTS")
    for r in rows:
        if r["state"] != "active" or r["kind"] != "positive":
            out.append(f"{r['key']}: historic row must be an active positive")
        if r["provenance"].get("batch") != "historic-acc-table":
            out.append(f"{r['key']}: historic row must carry provenance.batch historic-acc-table")
    return out


def check_active_floor(data: dict) -> list[str]:
    active = [r for r in data["cases"] if r["state"] == "active" and r["kind"] == "positive" and r["click_reachable"]]
    if len(active) < ttc.MIN_ACTIVE_POSITIVES:
        return [f"{len(active)} active click-reachable positives < floor {ttc.MIN_ACTIVE_POSITIVES}"]
    return []


def check_unique_per_show(data: dict) -> list[str]:
    sha = _sha_by_slug(data)
    out: list[str] = []
    keys = Counter(r["key"] for r in data["cases"])
    out += [f"duplicate key {k}" for k, n in keys.items() if n > 1]
    positives = Counter(
        (sha[r["slug"]], r["page_index"], r["show_seq"])
        for r in data["cases"]
        if r["kind"] == "positive" and r["state"] in ("active", "engine_active")
    )
    out += [f"two active positives on one show {k[1:]}" for k, n in positives.items() if n > 1]
    refusals = Counter(
        (sha[r["slug"]], r["page_index"], r["show_seq"], r["replacement"]) for r in data["cases"] if r["kind"] == "refusal"
    )
    out += [f"two refusals on one show+replacement {k[1:3]}" for k, n in refusals.items() if n > 1]
    return out


def check_refusal_reasons(data: dict) -> list[str]:
    out: list[str] = []
    for r in data["cases"]:
        reason, at_head = r["expected_reason"], r["expected_reason_at_head"]
        false_safe = at_head == "COMMITTED"
        if r["kind"] == "positive":
            if reason is not None:
                out.append(f"{r['key']}: a positive carries expected_reason {reason!r}")
            continue
        if reason is None:
            if not false_safe:
                out.append(f"{r['key']}: null expected_reason on a row that is not false-safe")
        elif reason not in REASONS:
            out.append(f"{r['key']}: expected_reason {reason!r} is not a RejectReason value")
        if at_head is not None and not false_safe and at_head not in REASONS:
            out.append(f"{r['key']}: expected_reason_at_head {at_head!r} is not a RejectReason value")
    return out


def check_no_originals_on_non_public(data: dict) -> list[str]:
    provenance = _provenance_by_slug(data)
    out: list[str] = []
    for r in data["cases"]:
        if provenance[r["slug"]] in NON_PUBLIC:
            if r["original"] is not None:
                out.append(f"{r['key']}: non-public row carries a plaintext original")
            if r["kind"] == "positive" and not (isinstance(r["original_sha256"], str) and len(r["original_sha256"]) == 64):
                out.append(f"{r['key']}: non-public positive lacks original_sha256")
    return out


def check_tier_agrees_with_compensation(data: dict) -> list[str]:
    out: list[str] = []
    for r in data["cases"]:
        if r["kind"] != "positive" or r["state"] not in ("active", "engine_active"):
            continue
        tier, comp = r["expected_tier"], r["expected_tj_compensation"]
        if tier not in (0, 1):
            out.append(f"{r['key']}: expected_tier {tier!r} must be 0 or 1")
        elif (tier == 1) != (comp is not None):
            out.append(f"{r['key']}: tier {tier} disagrees with compensation {comp!r}")
    return out


def check_active_rows_click_reachable(data: dict) -> list[str]:
    return [f"{r['key']}: active but not click_reachable" for r in data["cases"] if r["state"] == "active" and not r["click_reachable"]]


def check_retired_rows_name_slice(data: dict) -> list[str]:
    return [
        f"{r['key']}: retired without owned_until_slice"
        for r in data["cases"]
        if r["state"] == "retired" and not (isinstance(r["owned_until_slice"], str) and r["owned_until_slice"])
    ]


def check_plaintext_originals_are_calibration(data: dict) -> list[str]:
    """Policy: plaintext ``original`` only on ``public`` rows; never on proprietary or local_unrecorded ones (the
    calibration literals included: they live only in ``CALIBRATION_STRINGS``)."""
    provenance = _provenance_by_slug(data)
    return [
        f"{r['key']}: plaintext original on a {provenance[r['slug']]} corpus"
        for r in data["cases"]
        if r["original"] is not None and provenance[r["slug"]] != "public"
    ]


def machine_path_hits(data_or_text: object) -> list[str]:
    """Device-guard patterns plus any drive-letter or user-profile path, on raw text and on every decoded JSON string."""
    text = data_or_text if isinstance(data_or_text, str) else json.dumps(data_or_text)
    strings: list[str] = [text]

    def walk(node: object) -> None:
        if isinstance(node, str):
            strings.append(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                walk(key)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    try:
        walk(json.loads(text))
    except ValueError:
        pass
    extra = re.compile(r"\b[A-Za-z]:[\\/]|/Users/|/home/")
    hits: list[str] = []
    for chunk in strings:
        hits += [label for label, pattern in PATTERNS if pattern.search(chunk)]
        if extra.search(chunk):
            hits.append("drive-letter or home path")
    return hits


def check_false_safe_rows(data: dict) -> list[str]:
    out: list[str] = []
    for r in data["cases"]:
        shaped = (
            r["kind"] == "refusal"
            and r["state"] == "candidate"
            and r["expected_reason"] is None
            and isinstance(r["false_safe_oracle"], str)
            and r["false_safe_oracle"]
            and isinstance(r["owned_until_slice"], str)
            and r["owned_until_slice"]
        )
        if r["expected_reason_at_head"] == "COMMITTED" and not shaped:
            out.append(f"{r['key']}: a row that commits at HEAD must be a candidate refusal with null reason, oracle and owner")
        if r["false_safe_oracle"] is not None and r["expected_reason_at_head"] != "COMMITTED":
            out.append(f"{r['key']}: false_safe_oracle on a row that is not false-safe")
    return out


def check_no_synthetic_sources(data: dict) -> list[str]:
    out = [f"corpus {c['slug']}: synthetic provenance" for c in data["corpora"] if "synthetic" in str(c["provenance"]).lower()]
    out += [
        f"{r['key']}: synthetic provenance"
        for r in data["cases"]
        if "synthetic" in json.dumps(r["provenance"]).lower() or "_SYN_" in f"_{r['class_id'].upper()}_"
    ]
    return out


def check_frontier_provenance(data: dict) -> list[str]:
    """Manifest-internal only (never opens INGEST): every non-historic row names its batch, case and rederive report."""
    out: list[str] = []
    for r in data["cases"]:
        if r["class_id"] == "historic":
            continue
        prov = r["provenance"]
        ok = (
            isinstance(prov, dict)
            and all(isinstance(prov.get(k), str) and prov[k] for k in ("batch", "case_id", "rederive_head", "rederive_date"))
            and isinstance(prov.get("rederive_report_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", prov["rederive_report_sha256"]) is not None
        )
        if not ok:
            out.append(f"{r['key']}: frontier row lacks batch, case_id, rederive_head, rederive_report_sha256 or rederive_date")
    return out


def check_twin_or_waiver(data: dict, current_round: int) -> list[str]:
    out: list[str] = []
    for r in data["cases"]:
        if r["state"] != "active" or r["class_id"] == "historic":
            continue
        waiver = r["twin_waiver"]
        has_twin = isinstance(r["twin"], str) and bool(r["twin"])
        waived = (
            isinstance(waiver, dict)
            and isinstance(waiver.get("reason"), str)
            and bool(waiver["reason"])
            and isinstance(waiver.get("expires_round"), int)
            and not isinstance(waiver["expires_round"], bool)
            and waiver["expires_round"] >= current_round
        )
        if not (has_twin or waived):
            out.append(f"{r['key']}: active row without a twin or an unexpired waiver")
    return out


# ----------------------------------------------------------------------------------------------
# synthetic manifest for the mutation tests
# ----------------------------------------------------------------------------------------------
def _row(slug: str, page: int, show: int, **over: object) -> dict:
    row: dict = {
        "key": f"{slug}/p{page}/show{show}",
        "slug": slug,
        "page_index": page,
        "show_seq": show,
        "original": None,
        "original_sha256": "a" * 64,
        "replacement": "R",
        "font_resource": "F1",
        "basefont": "BaseFont",
        "font_kind": "type0",
        "class_id": "F1",
        "kind": "positive",
        "expected_tier": 0,
        "expected_tj_compensation": None,
        "expected_reason": None,
        "expected_reason_at_head": None,
        "click_reachable": True,
        "state": "active",
        "owned_until_slice": None,
        "false_safe_oracle": None,
        "twin": "twin-a",
        "twin_waiver": None,
        "provenance": {"batch": "b1", "case_id": "c1", "rederive_head": "abc1234", "rederive_report_sha256": "b" * 64, "rederive_date": "2026-10-26"},
    }
    row.update(over)
    return row


def _sample() -> dict:
    return {
        "schema": "true-text-corpus/1",
        "corpora": [
            {"slug": "alpha", "relative_path": "test_files/alpha.pdf", "sha256": "1" * 64, "provenance": "proprietary", "lineage_id": "alpha", "ui_shard": 0},
            {"slug": "beta", "relative_path": "test_files/beta.pdf", "sha256": "2" * 64, "provenance": "local_unrecorded", "lineage_id": "beta", "ui_shard": 1},
        ],
        "cases": [
            _row("alpha", 0, 1),
            _row("alpha", 0, 2, expected_tier=1, expected_tj_compensation=-12.5),
            _row("alpha", 1, 1, state="engine_active", kind="positive"),
            _row("beta", 0, 3, kind="refusal", state="engine_active", expected_reason="no_source_match", expected_reason_at_head="no_source_match", twin=None),
            _row(
                "beta", 0, 4, kind="refusal", state="candidate", expected_reason=None, expected_reason_at_head="COMMITTED",
                false_safe_oracle="assert_neighbour_glyphs_unchanged", owned_until_slice="I5", twin=None,
            ),
            _row("beta", 0, 5, kind="refusal", state="retired", expected_reason="font_custom_differences", owned_until_slice="I8", twin=None),
        ],
    }


def _write(tmp_path: Path, data: object, name: str = "manifest.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ----------------------------------------------------------------------------------------------
# the tracked manifest
# ----------------------------------------------------------------------------------------------
def test_manifest_contains_the_historic_fourteen():
    """Red first: the manifest had no ``cases`` at all.  The fourteen are pinned against the literal
    ``HISTORIC_FOURTEEN`` (outside the manifest), so deleting or editing a row cannot shrink the floor."""
    assert len(ttc.HISTORIC_FOURTEEN) == 14 == len(set(ttc.HISTORIC_FOURTEEN))
    assert {t[:3] for t in ttc.HISTORIC_FOURTEEN} == set(ttc.HISTORIC_FONTS) and len(ttc.HISTORIC_FONTS) == 14
    data = _data()
    assert check_historic_fourteen(data) == []
    assert sum(1 for r in data["cases"] if r["class_id"] == "historic") == 14
    manifest = ttc.load_manifest()
    historic = {s.slug: sum(1 for c in s.cases if c.class_id == "historic") for s in manifest.corpus_specs()}
    assert {slug: n for slug, n in historic.items() if n} == {"hvac": 10, "ecc": 4}  # later ingested rows may add cases, never remove these


def test_historic_check_fails_when_a_row_is_dropped_or_edited():
    data = _data()
    dropped = copy.deepcopy(data)
    dropped["cases"] = [r for r in dropped["cases"] if r["class_id"] == "historic"][1:]  # one historic row gone, whatever else is ingested
    edited = copy.deepcopy(data)
    edited["cases"] = copy.deepcopy([r for r in edited["cases"] if r["class_id"] == "historic"])
    edited["cases"][0]["original_sha256"] = "0" * 64
    for bad in (dropped, edited):
        assert check_historic_fourteen(bad)
    # the font identity of a historic row is pinned too (HISTORIC_FONTS), not only its text digest
    for field, value in (("font_resource", "C2_0"), ("basefont", "NotAFont"), ("font_kind", "simple")):
        mutated = copy.deepcopy(data)
        row = next(r for r in mutated["cases"] if r["key"] == "hvac/p4/show11")
        row[field] = value
        assert check_historic_fourteen(mutated), field


def test_active_positive_floor():
    assert ttc.MIN_ACTIVE_POSITIVES == 14
    data = _data()
    assert check_active_floor(data) == []
    manifest = ttc.load_manifest()
    assert len(manifest.click_reachable_positives()) >= ttc.MIN_ACTIVE_POSITIVES
    assert sum(len(spec.cases) for spec in manifest.corpus_specs()) >= ttc.MIN_ACTIVE_POSITIVES
    short = copy.deepcopy(data)
    short["cases"] = [r for r in short["cases"] if r["class_id"] == "historic"][:-1]  # 13 historic rows and nothing else
    assert check_active_floor(short)
    assert check_active_floor({"cases": []})


def test_positive_keys_unique_per_show():
    data = _data()
    assert data["cases"], "the manifest holds no cases"
    assert check_unique_per_show(data) == []
    sample = _sample()
    assert check_unique_per_show(sample) == []
    dup_key = copy.deepcopy(sample)
    dup_key["cases"].append(copy.deepcopy(dup_key["cases"][0]))
    same_show = copy.deepcopy(sample)
    same_show["cases"].append(_row("alpha", 0, 1, key="alpha/p0/show1#v2"))
    same_refusal = copy.deepcopy(sample)
    same_refusal["cases"].append(_row("beta", 0, 3, kind="refusal", state="candidate", expected_reason="no_source_match", key="beta/p0/show3#v2"))
    for bad in (dup_key, same_show, same_refusal):
        assert check_unique_per_show(bad)


def test_refusal_reasons_are_reject_reason_values():
    """The tracked manifest has no refusal row yet (the first arrive from ingest), so this holds for the
    historic positives only; the synthetic manifest below proves the vocabulary and the null rule can fail."""
    assert "no_source_match" in REASONS and "font_custom_differences" in REASONS and "COMMITTED" not in REASONS
    assert check_refusal_reasons(_data()) == []
    sample = _sample()
    assert check_refusal_reasons(sample) == []
    bad_reason = copy.deepcopy(sample)
    bad_reason["cases"][3]["expected_reason"] = "not_a_reject_reason"
    null_not_false_safe = copy.deepcopy(sample)
    null_not_false_safe["cases"][3]["expected_reason"] = None
    bad_at_head = copy.deepcopy(sample)
    bad_at_head["cases"][3]["expected_reason_at_head"] = "made_up"
    positive_with_reason = copy.deepcopy(sample)
    positive_with_reason["cases"][0]["expected_reason"] = "no_source_match"
    for bad in (bad_reason, null_not_false_safe, bad_at_head, positive_with_reason):
        assert check_refusal_reasons(bad)


def test_proprietary_rows_have_no_original():
    data = _data()
    assert data["cases"]
    assert check_no_originals_on_non_public(data) == []
    historic = [r for r in data["cases"] if r["class_id"] == "historic"]
    assert len(historic) == 14
    assert all(r["original"] is None and len(r["original_sha256"]) == 64 for r in historic)
    sample = _sample()
    assert check_no_originals_on_non_public(sample) == []
    leaked = copy.deepcopy(sample)
    leaked["cases"][0]["original"] = "client text"
    no_digest = copy.deepcopy(sample)
    no_digest["cases"][0]["original_sha256"] = None
    for bad in (leaked, no_digest):
        assert check_no_originals_on_non_public(bad)


def test_expected_tier_agrees_with_compensation():
    data = _data()
    tiers = Counter((r["expected_tier"], r["expected_tj_compensation"] is not None) for r in data["cases"] if r["class_id"] == "historic")
    assert tiers == Counter({(0, False): 11, (1, True): 3})  # hvac p4 s26 (333.0), hvac p5 s58 (-79.0), ecc p0 s60 (-500.0)
    assert check_tier_agrees_with_compensation(data) == []
    sample = _sample()
    assert check_tier_agrees_with_compensation(sample) == []
    tier1_no_comp = copy.deepcopy(sample)
    tier1_no_comp["cases"][1]["expected_tj_compensation"] = None
    tier0_with_comp = copy.deepcopy(sample)
    tier0_with_comp["cases"][0]["expected_tj_compensation"] = 1.0
    tier_none = copy.deepcopy(sample)
    tier_none["cases"][0]["expected_tier"] = None
    for bad in (tier1_no_comp, tier0_with_comp, tier_none):
        assert check_tier_agrees_with_compensation(bad)


def test_active_rows_are_click_reachable():
    data = _data()
    assert any(r["state"] == "active" for r in data["cases"])
    assert check_active_rows_click_reachable(data) == []
    bad = _sample()
    bad["cases"][0]["click_reachable"] = False
    assert check_active_rows_click_reachable(bad)


def test_engine_active_rows_never_in_a_shard(tmp_path):
    """engine_active is acceptance-green only: it joins ``corpus_specs()`` but never the click-path
    specs, the click-reachable positives or any UI shard."""
    for manifest in (ttc.load_manifest(), ttc.load_manifest(_write(tmp_path, _sample()))):
        engine_active = {r["key"] for r in manifest.rows if r["state"] == "engine_active"}
        shards = {c.ui_shard for c in manifest.corpora}
        in_shards = {c.key for shard in shards for c in manifest.ui_cases(shard)}
        in_click = {c.key for spec in manifest.click_reachable_specs() for c in spec.cases}
        in_click |= {c.key for c in manifest.click_reachable_positives()}
        assert engine_active.isdisjoint(in_shards | in_click)
        in_specs = {c.key for spec in manifest.corpus_specs() for c in spec.cases}
        assert {r["key"] for r in manifest.rows if r["state"] == "engine_active" and r["kind"] == "positive"} <= in_specs
    sample = ttc.load_manifest(_write(tmp_path, _sample(), "again.json"))
    assert sample.rows and {r["key"] for r in sample.rows if r["state"] == "engine_active"} == {"alpha/p1/show1", "beta/p0/show3"}
    assert [c.key for c in sample.ui_cases(0)] == ["alpha/p0/show1", "alpha/p0/show2"]
    assert sample.ui_cases(1) == () and sample.ui_cases(7) == ()


def test_active_rows_have_twin_or_unexpired_waiver():
    """A historic row is waived by ``class_id == "historic"``: the fourteen are covered by the hash-pinned
    real fixtures themselves and ``frontier_twins.py`` (I0b) builds twins for frontier classes, so no twin
    or waiver is invented for them.  Every other active row needs a twin or a waiver whose
    ``expires_round`` has not passed (the current round is the highest archived brief revision)."""
    data = _data()
    current = _brief_revision()
    assert current >= 5
    assert check_twin_or_waiver(data, current) == []
    assert all(r["twin"] is None and r["twin_waiver"] is None for r in data["cases"] if r["class_id"] == "historic")
    sample = _sample()
    assert check_twin_or_waiver(sample, current) == []
    none = copy.deepcopy(sample)
    none["cases"][0]["twin"] = None
    expired = copy.deepcopy(none)
    expired["cases"][0]["twin_waiver"] = {"reason": "no builder yet", "expires_round": current - 1}
    no_reason = copy.deepcopy(none)
    no_reason["cases"][0]["twin_waiver"] = {"reason": "", "expires_round": current}
    for bad in (none, expired, no_reason):
        assert check_twin_or_waiver(bad, current)
    waived = copy.deepcopy(none)
    waived["cases"][0]["twin_waiver"] = {"reason": "no builder yet", "expires_round": current}
    assert check_twin_or_waiver(waived, current) == []


def test_frontier_rows_carry_rederive_provenance():
    """The historic rows are exempt (batch ``historic-acc-table``, no rederive); no frontier row exists yet,
    so the synthetic rows prove each missing field is caught."""
    data = _data()
    assert any(r["class_id"] == "historic" for r in data["cases"])
    assert check_frontier_provenance(data) == []
    sample = _sample()
    assert check_frontier_provenance(sample) == []
    for field, value in (("batch", None), ("case_id", None), ("rederive_head", ""), ("rederive_report_sha256", "xyz"), ("rederive_report_sha256", None), ("rederive_date", None)):
        bad = copy.deepcopy(sample)
        bad["cases"][0]["provenance"][field] = value
        assert check_frontier_provenance(bad), field
    not_a_dict = copy.deepcopy(sample)
    not_a_dict["cases"][0]["provenance"] = None
    assert check_frontier_provenance(not_a_dict)


def test_validator_calibration_strings_equal_the_loaders():
    """The validator imports the loader's five calibration literals (stage 3); there is no second copy to drift."""
    from scripts import evidence_bundle as eb

    assert len(eb.CALIBRATION_STRINGS) == len(ttc.CALIBRATION_STRINGS) == 5
    assert set(eb.CALIBRATION_STRINGS) == set(ttc.CALIBRATION_STRINGS)
    assert eb.CALIBRATION_STRINGS is ttc.CALIBRATION_STRINGS  # stage 3: one tuple, no second copy to drift


def test_retired_rows_name_their_opening_slice():
    data = _data()
    assert check_retired_rows_name_slice(data) == []
    sample = _sample()
    assert check_retired_rows_name_slice(sample) == []
    bad = copy.deepcopy(sample)
    bad["cases"][5]["owned_until_slice"] = None
    assert check_retired_rows_name_slice(bad)


def test_calibration_strings_are_the_only_plaintext_originals():
    assert len(ttc.CALIBRATION_STRINGS) == 5 == len(set(ttc.CALIBRATION_STRINGS))
    assert "Drawing List" in ttc.CALIBRATION_STRINGS and "Drawing Title" in ttc.CALIBRATION_STRINGS
    data = _data()
    assert data["cases"]
    assert check_plaintext_originals_are_calibration(data) == []
    # one policy: a row on a proprietary or local_unrecorded corpus never carries a plaintext original, calibration
    # literals included (they live only in the loader constant); plaintext is tolerated on public rows only
    sample = _sample()
    sample["cases"][0]["original"] = ttc.CALIBRATION_STRINGS[2]
    assert check_plaintext_originals_are_calibration(sample)
    sample["cases"][0]["original"] = "some client string"
    assert check_plaintext_originals_are_calibration(sample)
    sample["corpora"][0]["provenance"] = "public"  # the manifest reader rejects it; the policy check only reads the label
    assert check_plaintext_originals_are_calibration(sample) == []
    beta = _sample()
    beta["cases"][3]["original"] = ttc.CALIBRATION_STRINGS[0]  # local_unrecorded corpus
    assert check_plaintext_originals_are_calibration(beta)


def test_manifest_has_no_machine_paths():
    sample = "C:" + "\\" + "Users" + "\\" + "x" + "\\" + "doc.pdf"  # built at run time: no literal path in this file
    assert machine_path_hits(sample)
    assert machine_path_hits({"relative_path": sample})
    assert machine_path_hits(json.dumps({"relative_path": sample}))
    assert machine_path_hits({"p": "/" + "home" + "/x/y"})
    assert machine_path_hits({"p": "D:" + "/" + "work"})
    assert machine_path_hits({"relative_path": "test_files/ok.pdf"}) == []
    text = MANIFEST.read_text(encoding="utf-8")
    assert machine_path_hits(text) == []
    assert machine_path_hits(_data()) == []


def test_false_safe_rows_are_candidates_with_owner():
    """No false-safe row exists yet (they arrive from ingest); the synthetic rows prove each way a
    commits-at-HEAD row can be mis-shaped.  The name in ``false_safe_oracle`` is checked against
    ``true_text_acceptance_helpers`` once I0b creates it."""
    assert check_false_safe_rows(_data()) == []
    sample = _sample()
    assert check_false_safe_rows(sample) == []
    false_safe = sample["cases"][4]
    mutations = [
        {"state": "engine_active"},
        {"kind": "positive"},
        {"expected_reason": "no_source_match"},
        {"false_safe_oracle": None},
        {"owned_until_slice": None},
        {"false_safe_oracle": ""},
    ]
    for mutation in mutations:
        bad = copy.deepcopy(sample)
        bad["cases"][4].update(mutation)
        assert check_false_safe_rows(bad), mutation
    stray = copy.deepcopy(sample)
    stray["cases"][3]["false_safe_oracle"] = "assert_x"
    assert check_false_safe_rows(stray)
    assert false_safe["expected_reason_at_head"] == "COMMITTED"


def test_synthetic_sources_never_in_manifest():
    data = _data()
    assert data["corpora"] and check_no_synthetic_sources(data) == []
    assert {c["provenance"] for c in data["corpora"]} <= set(NON_PUBLIC)
    sample = _sample()
    assert check_no_synthetic_sources(sample) == []
    corpus = copy.deepcopy(sample)
    corpus["corpora"][0]["provenance"] = "synthetic"
    row = copy.deepcopy(sample)
    row["cases"][0]["provenance"]["batch"] = "synthetic-builder"
    klass = copy.deepcopy(sample)
    klass["cases"][0]["class_id"] = "CTRL_SYN_T0"
    for bad in (corpus, row, klass):
        assert check_no_synthetic_sources(bad)


def test_manifest_corpora_cover_the_brief_sources():
    """Every sha brief v5 names with provenance local_unrecorded or proprietary is registered in
    ``corpora``; any other sha in the brief must be in the public list or marked census-only here."""
    data = _data()
    corpora = {c["slug"]: c for c in data["corpora"]}
    for slug, (provenance, sha) in BRIEF_CORPORA.items():
        assert slug in corpora, slug
        assert (corpora[slug]["provenance"], corpora[slug]["sha256"]) == (provenance, sha)
        assert corpora[slug]["lineage_id"] == slug
        assert corpora[slug]["relative_path"].startswith("test_files/")
    order = [c["slug"] for c in data["corpora"]]
    assert order.index("office-report-23p") < order.index("hvac") < order.index("ecc")  # registry order stays as before acc.CORPORA moved in
    brief = BRIEF_V5.read_text(encoding="utf-8")
    named = set(re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", brief))
    assert {sha for _p, sha in BRIEF_CORPORA.values()} <= named
    public = {item["sha256"] for item in json.loads(PUBLIC_LIST.read_text(encoding="utf-8"))["files"]}
    registered = {c["sha256"] for c in data["corpora"]}
    assert named - registered - public - BRIEF_CENSUS_ONLY == set()
    assert len(registered) == len(data["corpora"])


# ----------------------------------------------------------------------------------------------
# the loader
# ----------------------------------------------------------------------------------------------
def test_load_manifest_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        ttc.load_manifest(tmp_path / "nope.json")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("cases"),
        lambda d: d.update(cases={}),
        lambda d: d.pop("corpora"),
        lambda d: d.update(schema="true-text-corpus/2"),
        lambda d: d["cases"][0].update(page_index="0"),
        lambda d: d["cases"][0].update(page_index=True),
        lambda d: d["cases"][0].update(state="active-ish"),
        lambda d: d["cases"][0].update(kind="census"),
        lambda d: d["cases"][0].update(slug="nowhere"),
        lambda d: d["cases"][0].update(key="alpha/p9/show9"),
        lambda d: d["cases"][0].update(click_reachable="yes"),
        lambda d: d["cases"][0].update(original_sha256="xyz"),
        lambda d: d["cases"][0].update(expected_tier=2),
        lambda d: d["cases"][0].pop("twin_waiver"),
        lambda d: d["cases"].append(copy.deepcopy(d["cases"][0])),
        lambda d: d["corpora"][0].update(sha256="short"),
        lambda d: d["corpora"][0].pop("ui_shard"),
        lambda d: d["corpora"].append(copy.deepcopy(d["corpora"][0])),
    ],
    ids=[
        "no_cases", "cases_not_a_list", "no_corpora", "bad_schema", "page_index_str", "page_index_bool", "bad_state",
        "bad_kind", "unknown_slug", "key_disagrees", "click_reachable_str", "bad_digest", "bad_tier", "missing_key",
        "duplicate_key", "bad_corpus_sha", "no_ui_shard", "duplicate_corpus",
    ],
)
def test_load_manifest_rejects_an_invalid_file(tmp_path, mutate):
    data = _sample()
    mutate(data)
    with pytest.raises(ValueError):
        ttc.load_manifest(_write(tmp_path, data))


def test_load_manifest_never_skips_a_bad_row(tmp_path):
    good = ttc.load_manifest(_write(tmp_path, _sample()))
    assert len(good.rows) == 6 and len(good.corpora) == 2
    bad = _sample()
    bad["cases"][-1]["state"] = "unknown"
    with pytest.raises(ValueError):
        ttc.load_manifest(_write(tmp_path, bad, "bad.json"))
    empty = _sample()
    empty["cases"] = []
    manifest = ttc.load_manifest(_write(tmp_path, empty, "empty.json"))
    assert manifest.rows == () and manifest.corpus_specs() == () and manifest.click_reachable_positives() == ()


def test_spec_by_slug_raises_on_unknown_slug(tmp_path):
    manifest = ttc.load_manifest()
    with pytest.raises(KeyError):
        manifest.spec_by_slug("nope")
    with pytest.raises(KeyError):
        manifest.spec_by_slug("")
    for slug, count in (("hvac", 10), ("ecc", 4)):
        spec = manifest.spec_by_slug(slug)
        assert spec.slug == slug
        assert sum(1 for c in spec.cases if c.class_id == "historic") == count  # ingested rows may add more
    # a registered corpus with no active or engine_active row is a spec with no cases, not an error (beta below)
    sample = ttc.load_manifest(_write(tmp_path, _sample()))
    assert [c.key for c in sample.spec_by_slug("alpha").cases] == ["alpha/p0/show1", "alpha/p0/show2", "alpha/p1/show1"]
    assert sample.spec_by_slug("beta").cases == ()  # beta holds refusal rows only


def test_refusal_cases_exclude_false_safe_rows(tmp_path):
    manifest = ttc.load_manifest(_write(tmp_path, _sample()))
    refusals = manifest.refusal_cases()
    assert [(r.slug, r.page_index, r.show_seq, r.expected_reason) for r in refusals] == [("beta", 0, 3, "no_source_match")]
    # the false-safe candidate has no exact reason to assert whatever states are asked for
    every_state = manifest.refusal_cases(states=ttc.STATES)
    assert [(r.show_seq, r.expected_reason, r.owned_until_slice) for r in every_state] == [
        (3, "no_source_match", None),
        (5, "font_custom_differences", "I8"),
    ]
    assert manifest.refusal_cases(states=("candidate",)) == ()
    # a false-safe row mis-filed as engine_active is still never yielded
    data = _sample()
    data["cases"][4]["state"] = "engine_active"
    mis_filed = ttc.load_manifest(_write(tmp_path, data, "mis_filed.json"))
    assert [r.show_seq for r in mis_filed.refusal_cases()] == [3]
    assert [r["key"] for r in manifest.candidates()] == ["beta/p0/show4"]  # the candidates watch still sees it
    assert manifest.candidates()[0]["false_safe_oracle"] == "assert_neighbour_glyphs_unchanged"


def test_corpus_specs_filter_by_state_and_keep_new_fields(tmp_path):
    manifest = ttc.load_manifest(_write(tmp_path, _sample()))
    default = manifest.corpus_specs()
    assert [(s.slug, [c.key for c in s.cases]) for s in default] == [("alpha", ["alpha/p0/show1", "alpha/p0/show2", "alpha/p1/show1"])]
    only_active = manifest.corpus_specs(states=("active",))
    assert [c.state for c in only_active[0].cases] == ["active", "active"]
    assert manifest.corpus_specs(states=("candidate",)) == ()
    tier1 = default[0].cases[1]
    assert (tier1.expected_tier, tier1.expected_tj_compensation, tier1.class_id, tier1.font_kind) == (1, -12.5, "F1", "type0")
    assert isinstance(tier1.expected_tj_compensation, float)
    assert (default[0].provenance, default[0].lineage_id, default[0].ui_shard) == ("proprietary", "alpha", 0)


def test_corpus_case_and_spec_keep_positional_construction():
    case = ttc.CorpusCase(4, 11, None, "R", "C2_1", "PMingLiU")
    assert (case.class_id, case.font_kind, case.expected_tier, case.click_reachable, case.key, case.state) == ("historic", "type0", None, True, None, "active")
    assert case.expected_tj_compensation is None and case.original_sha256 is None
    with_comp = ttc.CorpusCase(4, 26, None, "R", "C2_0", "ArialMT", 333.0, "d" * 64)
    assert (with_comp.expected_tj_compensation, with_comp.original_sha256) == (333.0, "d" * 64)
    spec = ttc.CorpusSpec("s", "test_files/s.pdf", "e" * 64, (case,))
    assert spec.cases == (case,) and (spec.provenance, spec.ui_shard) == ("proprietary", 0)
