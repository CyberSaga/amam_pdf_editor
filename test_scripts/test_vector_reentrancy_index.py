"""Card B7 class check, group index: the page-index timer, also for a page whose index is gone (harness: vector_reentrancy_harness.py)."""

from __future__ import annotations

import pytest

from vector_reentrancy_harness import FAULTS, GROUPS, check_fault, check_serial

ENTRIES = GROUPS["index"]


@pytest.mark.parametrize("phase", ["T0", "T1"])
@pytest.mark.parametrize("entry", ENTRIES)
def test_vector_transaction_matches_serial_outcome_under_reentrant_delivery(qapp, monkeypatch, tmp_path, entry, phase):
    check_serial(qapp, monkeypatch, tmp_path, entry, phase)


@pytest.mark.parametrize("fault", [f for f in FAULTS if f != "none"])
@pytest.mark.parametrize("entry", ENTRIES)
def test_a_failure_at_every_publish_step_ends_as_the_serial_rollback_does(qapp, monkeypatch, tmp_path, entry, fault):
    check_fault(qapp, monkeypatch, tmp_path, entry, fault)
