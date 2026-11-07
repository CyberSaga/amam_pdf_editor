from __future__ import annotations

from dataclasses import replace

import pytest

from scripts.perf_completion import CompletionContract, CompletionEvidence


def complete():
    return CompletionEvidence(
        session='document', revision=2, page=4, scale=1.25,
        visible=frozenset({4, 5}), high=frozenset({4, 5}),
        painted=frozenset({4, 5}), thumbnails=frozenset(range(8)),
        indexed=frozenset(range(8)), idle=True, metadata_ready=True,
    )


@pytest.mark.parametrize('change', [
    {'session': 'old'}, {'revision': 1}, {'page': 3}, {'scale': 1.},
    {'visible': frozenset()}, {'high': frozenset({4})},
    {'painted': frozenset({4})},
])
def test_stale_partial_or_unpainted_quality_is_not_visible_completion(change):
    contract = CompletionContract('document', 2, 4, 1.25, 8)
    assert contract.visible_complete(complete())
    assert not contract.visible_complete(replace(complete(), **change))


@pytest.mark.parametrize('change', [
    {'thumbnails': frozenset(range(7))}, {'indexed': frozenset(range(7))},
    {'idle': False}, {'session': 'old'}, {'revision': 1},
    {'thumbnails': frozenset(range(1, 9))},
    {'metadata_ready': False},
])
def test_empty_queues_never_replace_expected_background_work(change):
    contract = CompletionContract('document', 2, 4, 1.25, 8)
    assert contract.background_complete(complete())
    assert not contract.background_complete(replace(complete(), **change))


def test_background_requires_current_visible_paint_too():
    contract = CompletionContract('document', 2, 4, 1.25, 8)
    assert not contract.background_complete(replace(complete(), painted=frozenset()))


def test_frozen_lazy_index_obligation_is_not_invented_full_document_work():
    contract = CompletionContract('document', 2, 4, 1.25, 8,
                                  required_indexed=frozenset({4}))
    assert contract.background_complete(replace(complete(), indexed=frozenset({4})))
    assert not contract.background_complete(replace(complete(), indexed=frozenset()))
