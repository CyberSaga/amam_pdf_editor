"""Slice I1, stage C: the manifest takes PUBLIC corpora and the real-corpus acceptance proves simple-font rows.

Stage D wrote the real rows into the tracked manifest at the committed head d69117d (19 rows, 16 public corpora).
This module keeps proving, with a TEMPORARY manifest in ``tmp_path`` built from the tracked file with its public
corpora stripped (the tracked file is only read), that the public-row mechanism is green on its own:

* the loader and the registry admit a ``public`` corpora entry that IS a public-list row (``artofwar``,
  ``bug1946953``) and register nothing for it;
* the SAME commit / reopen / oracle body the hvac and ecc acceptance runs (``run_corpus_acceptance``) passes end to
  end on those two simple-font F30B rows, with the independent glyph leg ``glyph_name_agl``;
* the aggregate prepare helper visits them, and a missing PUBLIC fixture only skips its own corpus.

The two rows are the ``engine_active`` rows of ingest batch 20261031_1628_r2 (``emit`` output), reduced to the manifest
shape: ``original`` is null (the show text is hash-pinned by ``original_sha256``), the extra emit keys
(``show_text_sha256``, ``item_range``, ``byte_range_in_item``) are dropped.  The pure tests run everywhere; the
tests that open the public PDFs carry ``needs_fixtures`` and self-skip without ``test_files/``.
"""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import evidence_rederive as rd  # noqa: E402
from test_scripts import true_text_corpus as ttc  # noqa: E402

acc = importlib.import_module("test_scripts.test_text_commit_real_corpus_acceptance")

PUBLIC_LIST = ROOT / "test_scripts" / "fixtures" / "public_corpus_sha256.json"
SLUGS = ("artofwar", "bug1946953")
SIMPLE_LEGS = ("glyph_name_agl", "cmap_31_reverse", "standard_14_table")

_PROVENANCE_BATCH = {
    "batch": "20261031_1628_r2",
    "rederive_head": "f0713a28864a4c329cfbbf57da718be1b0c9dcca",
    "rederive_report_sha256": "9b757496d2f0301637ca36019550d593366ce5564bb7ce4de0f4562739760982",
    "rederive_date": "2026-10-31T08:42:16Z",
}


def _emit_row(key: str, slug: str, show: int, original_sha256: str, replacement: str, resource: str, basefont: str, case_id: str) -> dict:
    return {
        "key": key, "slug": slug, "page_index": 0, "show_seq": show,
        "original": None, "original_sha256": original_sha256, "replacement": replacement,
        "font_resource": resource, "basefont": basefont, "font_kind": "simple", "class_id": "F30B",
        "kind": "positive", "expected_tier": 0, "expected_tj_compensation": None,
        "expected_reason": None, "expected_reason_at_head": None, "click_reachable": False,
        "state": "engine_active", "owned_until_slice": None, "false_safe_oracle": None,
        "twin": None, "twin_waiver": None, "provenance": {**_PROVENANCE_BATCH, "case_id": case_id},
    }


ROWS = (
    _emit_row("artofwar/p0/show73#eq", "artofwar", 73, "b344d80e24a3679999fa964450b34bc24d1578a35509f934c1418b0a20d21a67", "ehT", "F2", "CoronationScot", "r2-F30B-c31a14e4-p0-s73-eq1"),
    _emit_row("bug1946953/p0/show1#eq", "bug1946953", 1, "baaddf70fb5d432b8bd948ef91d6f910124a6d138edae4d5f000c4610ddc8eae", "epyT", "F1.0", "633ba2+ArialUnicodeMS", "r2-F30B-e1b06150-p0-s1-eq1"),
)


def _public_item(slug: str) -> dict:
    listed = json.loads(PUBLIC_LIST.read_text(encoding="utf-8"))["files"]
    return next(item for item in listed if Path(item["relative_path"]).stem == slug)


def _write_manifest(path: Path, slugs: tuple[str, ...] = SLUGS, *, relative_path: dict[str, str] | None = None) -> Path:
    """The tracked manifest plus a public corpora entry and the engine_active row per slug, written to ``path``."""
    data = json.loads(ttc.MANIFEST.read_text(encoding="utf-8"))
    public = {c["slug"] for c in data["corpora"] if c.get("provenance") == "public"}  # stage D's rows: stripped, re-added below
    data["corpora"] = [c for c in data["corpora"] if c["slug"] not in public]
    data["cases"] = [c for c in data["cases"] if c["slug"] not in public]
    for slug in slugs:
        item = _public_item(slug)
        data["corpora"].append(
            {
                "slug": slug,
                "relative_path": (relative_path or {}).get(slug, item["relative_path"]),
                "sha256": item["sha256"],
                "provenance": "public",
                "lineage_id": item["lineage_id"],
                "ui_shard": 0,
            }
        )
        data["cases"].extend(copy.deepcopy(row) for row in ROWS if row["slug"] == slug)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    return _write_manifest(tmp_path / "manifest.json")


def test_the_tracked_manifest_is_not_the_temporary_one(manifest_path: Path) -> None:
    """The proof never writes the tracked manifest.  Since stage D (2026-11-01) the tracked file carries public corpora:
    every one is a public-list row, and the two F30B rows this module proves are there with the shape ``ROWS`` pins
    (``provenance`` differs only by the rederive run that wrote them)."""
    assert manifest_path.parent != ttc.MANIFEST.parent
    tracked = json.loads(ttc.MANIFEST.read_text(encoding="utf-8"))
    public = [c for c in tracked["corpora"] if c["provenance"] == "public"]
    assert public, "stage D wrote public corpora"
    listed = {item["relative_path"]: item["sha256"] for item in json.loads(PUBLIC_LIST.read_text(encoding="utf-8"))["files"]}
    for entry in public:  # the slug is the slugified stem, so the list is joined on the relative path
        assert listed.get(entry["relative_path"]) == entry["sha256"], entry["slug"]
    by_key = {c["key"]: c for c in tracked["cases"]}
    for row in ROWS:
        got = dict(by_key[row["key"]])
        provenance = got.pop("provenance")
        assert got == {k: v for k, v in row.items() if k != "provenance"}, row["key"]
        assert provenance["case_id"] == row["provenance"]["case_id"]
        assert len(provenance["rederive_head"]) == 40


def test_the_loader_and_the_registry_admit_the_public_corpora(manifest_path: Path) -> None:
    manifest = ttc.load_manifest(manifest_path)
    specs = {spec.slug: spec for spec in manifest.corpus_specs()}
    assert set(SLUGS) <= set(specs)
    registry = rd.load_registry(ROOT, manifest=manifest_path)
    base = rd.load_registry(ROOT)
    assert registry.entries == base.entries  # a public reference registers nothing
    for slug in SLUGS:
        spec = specs[slug]
        item = _public_item(slug)
        assert (spec.provenance, spec.relative_path, spec.sha256, spec.lineage_id) == ("public", item["relative_path"], item["sha256"], item["lineage_id"])
        assert [(c.font_kind, c.state, c.original) for c in spec.cases] == [("simple", "engine_active", None)]
        assert len(spec.cases[0].original_sha256 or "") == 64  # the digest-pinned shape test_true_text_corpus_fixture_digests.py demands
        entry = registry.by_sha(spec.sha256, spec.provenance)
        assert entry is not None and (entry.relative_path, entry.lineage_id) == (spec.relative_path, spec.lineage_id)


def test_a_public_corpus_that_is_not_a_public_list_row_is_refused_by_the_registry(tmp_path: Path) -> None:
    wrong = _write_manifest(tmp_path / "wrong.json", ("artofwar",), relative_path={"artofwar": "test_files/mozilla-pdf/elsewhere.pdf"})
    ttc.load_manifest(wrong)  # the loader only parses; the registry is the gate
    with pytest.raises(ValueError, match="does not match the public list"):
        rd.load_registry(ROOT, manifest=wrong)


def test_a_missing_public_fixture_skips_only_its_corpus(tmp_path: Path) -> None:
    """A missing PUBLIC fixture: the parametrized run skips that one item, the aggregate leaves the corpus unvisited and
    names it; a missing PROPRIETARY fixture keeps skipping the whole test."""
    gone = _write_manifest(tmp_path / "gone.json", ("artofwar",), relative_path={"artofwar": "test_files/mozilla-pdf/not-on-this-machine.pdf"})
    manifest = ttc.load_manifest(gone)
    spec = manifest.spec_by_slug("artofwar")
    assert acc.fixture_or_none(spec) is None
    with pytest.raises(pytest.skip.Exception):
        acc.run_corpus_acceptance(spec, tmp_path, manifest)
    result = acc.prepare_positive_edits((spec,))
    assert (result.skipped_public, result.visited, result.prepared_count, result.refusals) == (["artofwar"], set(), 0, [])
    proprietary = ttc.CorpusSpec(slug="gone-prop", relative_path="test_files/not-on-this-machine.pdf", sha256="0" * 64, cases=(), provenance="proprietary")
    with pytest.raises(pytest.skip.Exception):
        acc.fixture_or_none(proprietary)


@pytest.mark.needs_fixtures
@pytest.mark.parametrize("slug", SLUGS)
def test_the_acceptance_body_passes_end_to_end_on_a_simple_font_public_row(slug: str, manifest_path: Path, tmp_path: Path) -> None:
    manifest = ttc.load_manifest(manifest_path)
    summary = acc.run_corpus_acceptance(manifest.spec_by_slug(slug), tmp_path, manifest)
    assert summary["legs"] == ["glyph_name_agl"], summary
    assert summary["glyphs_checked"] >= 1 and summary["glyphs_paired"] > 0 and summary["target_glyphs_ink_checked"] >= 1, summary


@pytest.mark.needs_fixtures
def test_the_aggregate_prepare_helper_visits_the_public_rows(manifest_path: Path) -> None:
    manifest = ttc.load_manifest(manifest_path)
    result = acc.prepare_positive_edits(manifest.corpus_specs())
    assert result.refusals == [] and result.skipped_public == []
    assert {("artofwar", 0, 73), ("bug1946953", 0, 1)} <= result.visited
    assert result.prepared_count == len(result.visited)
    assert {t[:3] for t in ttc.HISTORIC_FOURTEEN} <= result.visited
