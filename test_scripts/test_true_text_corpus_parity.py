"""Parity of the manifest-backed corpus table with the acceptance literals (slice I0a, stage 2).

``load_manifest().corpus_specs()`` must describe exactly the corpora and cases that
``test_text_commit_real_corpus_acceptance.CORPORA`` hard-codes, so the click-path loops
and the acceptance suite can switch to the manifest (stage 3 then deletes the literals).

The comparison is field by field: the loader's ``CorpusCase`` and acc's are different
classes until acc re-exports the loader's.  Only the digest-versus-fixture test needs the
gitignored PDFs; it fails (never skips) when a present fixture decodes to a different text.
"""
from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from test_scripts import true_text_corpus as ttc  # noqa: E402

CASE_FIELDS = ("page_index", "show_seq", "replacement", "font_resource", "basefont", "expected_tj_compensation")


def _acc():
    import test_text_commit_real_corpus_acceptance as acc

    return acc


def _historic(specs) -> tuple:
    """The specs restricted to the ``historic`` rows (the acc literals' scope); rows ingested later are not in acc."""
    out = []
    for spec in specs:
        cases = tuple(c for c in spec.cases if c.class_id == "historic")
        if cases:
            out.append(dataclasses.replace(spec, cases=cases))
    return tuple(out)


def _case_tuple(case) -> tuple:
    return tuple(getattr(case, name) for name in CASE_FIELDS)


def _assert_same_spec(new, old) -> None:
    assert (new.slug, new.relative_path, new.sha256) == (old.slug, old.relative_path, old.sha256)
    assert len(new.cases) == len(old.cases), new.slug
    for index, (n, o) in enumerate(zip(new.cases, old.cases, strict=True)):
        assert _case_tuple(n) == _case_tuple(o), (new.slug, index)
        assert type(n.expected_tj_compensation) is type(o.expected_tj_compensation), (new.slug, index)


def test_corpus_specs_equal_the_acceptance_literals_field_by_field():
    acc = _acc()
    specs = _historic(ttc.load_manifest().corpus_specs())
    assert len(specs) == len(acc.CORPORA) == 2
    for new, old in zip(specs, acc.CORPORA, strict=True):
        _assert_same_spec(new, old)
    assert sum(len(spec.cases) for spec in specs) == 14


def test_spec_by_slug_equals_hvac_and_ecc():
    acc = _acc()
    manifest = ttc.load_manifest()
    _assert_same_spec(_historic([manifest.spec_by_slug("hvac")])[0], acc.HVAC)
    _assert_same_spec(_historic([manifest.spec_by_slug("ecc")])[0], acc.ECC)


def test_click_path_specs_equal_the_acceptance_literals():
    """The three click-path loops switch to ``click_reachable_specs()``: today that is all fourteen."""
    acc = _acc()
    manifest = ttc.load_manifest()
    specs = _historic(manifest.click_reachable_specs())
    assert len(specs) == len(acc.CORPORA)
    for new, old in zip(specs, acc.CORPORA, strict=True):
        _assert_same_spec(new, old)
    assert sum(1 for c in manifest.click_reachable_positives() if c.class_id == "historic") == 14
    assert len(manifest.click_reachable_positives()) >= ttc.MIN_ACTIVE_POSITIVES


def test_manifest_digests_match_the_acceptance_originals_and_tiers():
    """Where acc still carries a plaintext original, the manifest's digest is its sha256 (the
    ``_resolve_cases`` convention: sha256 of the UTF-8 text); an acc digest is copied verbatim."""
    acc = _acc()
    manifest = ttc.load_manifest()
    for new, old in zip(_historic(manifest.corpus_specs()), acc.CORPORA, strict=True):
        for n, o in zip(new.cases, old.cases, strict=True):
            assert n.original is None
            if o.original is not None:
                assert n.original_sha256 == hashlib.sha256(o.original.encode("utf-8")).hexdigest(), (new.slug, n.page_index, n.show_seq)
            else:
                assert n.original_sha256 == o.original_sha256
            assert n.expected_tier == (0 if o.expected_tj_compensation is None else 1)
            assert (n.class_id, n.font_kind, n.state, n.click_reachable) == ("historic", "type0", "active", True)


def test_calibration_strings_equal_the_acceptance_literals():
    acc = _acc()
    hvac = acc.HVAC.cases
    expected = {hvac[0].original, hvac[0].replacement, hvac[5].original, hvac[5].replacement, acc._MISSING_GLYPH_REPLACEMENT}
    assert set(ttc.CALIBRATION_STRINGS) == expected and len(expected) == 5


def test_historic_fourteen_matches_the_acceptance_table():
    acc = _acc()
    rows = [
        (spec.slug, case.page_index, case.show_seq, case.replacement, case.expected_tj_compensation)
        for spec in acc.CORPORA
        for case in spec.cases
    ]
    assert rows == [t[:5] for t in ttc.HISTORIC_FOURTEEN]


@pytest.mark.needs_fixtures
def test_manifest_original_sha256_matches_the_fixture_text():
    """The digest of every manifest row is what ``acc._resolve_cases`` verifies against the show text
    the hash-pinned fixture decodes to.  Every present fixture is checked and a mismatch fails; the test
    skips once, at the end, only if some fixture was absent (naming them)."""
    fitz = pytest.importorskip("fitz")
    acc = _acc()
    manifest = ttc.load_manifest()
    missing: list[str] = []
    verified_historic = 0
    for spec in manifest.corpus_specs():
        if not (ROOT / spec.relative_path).exists():
            missing.append(spec.relative_path)
            continue
        source = acc._fixture(spec)  # asserts the file's own sha256
        with fitz.open(str(source)) as doc:
            try:
                resolved = acc._resolve_cases(spec, doc)  # asserts sha256(text) == original_sha256 per row
            except AssertionError as exc:
                pytest.fail(f"{spec.slug}: manifest original_sha256 does not match the fixture text: {exc}")
        old = next((s for s in acc.CORPORA if s.slug == spec.slug), None)
        if old is not None:
            with fitz.open(str(source)) as old_doc:
                old_resolved = acc._resolve_cases(old, old_doc)
            historic = [c.original for c in resolved if c.class_id == "historic"]
            assert historic == [c.original for c in old_resolved], spec.slug
            verified_historic += len(historic)
    if missing:
        pytest.skip(f"missing optional real-corpus fixture(s): {', '.join(missing)}")
    assert verified_historic == 14
