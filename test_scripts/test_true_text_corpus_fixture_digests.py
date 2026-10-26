"""Fixture digests and the acceptance suite's wiring to the manifest (slice I0a, stage 3).

Stage 2 proved ``load_manifest().corpus_specs()`` equal to the literals in
``test_text_commit_real_corpus_acceptance`` ("acc").  Stage 3 deleted the literals: acc now
re-exports ``CorpusCase``/``CorpusSpec`` from the loader and builds ``CORPORA``/``HVAC``/``ECC``
from the manifest, so a comparison with acc would compare the manifest with itself.  What is
left has an independent oracle:

* the wiring (acc's names are the loader's objects, built from one ``load_manifest()``);
* the hash-pinned fixture: every manifest ``original_sha256`` is what the fixture's own show
  text hashes to (only this test needs the gitignored PDFs; it fails, never skips, on a present
  fixture that mismatches);
* the calibration strings against the manifest digests of the two shows they came from.
"""
from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_scripts import true_text_corpus as ttc  # noqa: E402


def _acc():
    import test_text_commit_real_corpus_acceptance as acc

    return acc


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_acc_reexports_the_loader_classes_and_builds_its_tables_from_the_manifest():
    acc = _acc()
    assert acc.CorpusCase is ttc.CorpusCase
    assert acc.CorpusSpec is ttc.CorpusSpec
    manifest = ttc.load_manifest()
    assert acc.CORPORA == manifest.corpus_specs()
    assert acc.HVAC == manifest.spec_by_slug("hvac")
    assert acc.ECC == manifest.spec_by_slug("ecc")
    by_slug = {spec.slug: spec for spec in acc.CORPORA}
    assert by_slug["hvac"] == acc.HVAC and by_slug["ecc"] == acc.ECC  # lookup by slug: corpus order is not pinned
    assert sum(len(spec.cases) for spec in acc.CORPORA) >= ttc.MIN_ACTIVE_POSITIVES


def test_every_acc_case_is_hash_pinned_with_no_plaintext_original():
    """The acc table carries no client text any more: ``_resolve_cases`` must fill every ``original``."""
    for spec in _acc().CORPORA:
        for case in spec.cases:
            assert case.original is None, (spec.slug, case.page_index, case.show_seq)
            assert isinstance(case.original_sha256, str) and len(case.original_sha256) == 64


def test_calibration_strings_hash_to_the_historic_rows_they_came_from():
    """Independent of the literal: the two calibration originals are the texts of hvac p4 show11 and show26,
    whose digests the manifest holds; the replacements are the manifest rows' replacements."""
    rows = {r["key"]: r for r in ttc.load_manifest().rows}
    show11, show26 = rows["hvac/p4/show11"], rows["hvac/p4/show26"]
    strings = ttc.CALIBRATION_STRINGS
    assert len(strings) == 5 == len(set(strings))
    assert strings[0] != "" and _digest(strings[0]) == show11["original_sha256"]
    assert strings[1] == show11["replacement"]
    assert _digest(strings[2]) == show26["original_sha256"]
    assert strings[3] == show26["replacement"]
    assert strings[4] == _acc()._MISSING_GLYPH_REPLACEMENT  # the one calibration literal acc still carries
    assert _digest(strings[4]) not in {r["original_sha256"] for r in rows.values()}  # a glyph the font lacks: no show has it


@pytest.mark.needs_fixtures
def test_manifest_original_sha256_matches_the_fixture_text():
    """The digest of every manifest row is what ``acc._resolve_cases`` verifies against the show text
    the hash-pinned fixture decodes to.  Every present fixture is checked and a mismatch fails; the test
    skips once, at the end, only if some fixture was absent (naming them)."""
    fitz = pytest.importorskip("fitz")
    acc = _acc()
    manifest = ttc.load_manifest()
    missing: list[str] = []
    expected_historic = Counter(t[0] for t in ttc.HISTORIC_FOURTEEN)
    for spec in manifest.corpus_specs():
        if not (ROOT / spec.relative_path).exists():
            missing.append(spec.relative_path)
            continue
        source = acc._fixture(spec)  # asserts the file's own sha256
        with fitz.open(str(source)) as doc:
            resolved = acc._resolve_cases(spec, doc)  # its AssertionError (sha256(text) != original_sha256 per row) is the failure
        assert all(c.original is not None for c in resolved), spec.slug
        assert sum(1 for c in resolved if c.class_id == "historic") == expected_historic[spec.slug], spec.slug
    if missing:
        pytest.skip(f"missing optional real-corpus fixture(s): {', '.join(missing)}")
