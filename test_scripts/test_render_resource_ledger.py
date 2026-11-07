from __future__ import annotations

import subprocess
import sys

import pytest

from src.render_worker.resource_ledger import ResourceLedger


def test_processes_keep_slot_and_bytes_until_actual_exit():
    ledger = ResourceLedger(byte_limit=100, slot_limit=2)
    first = ledger.try_reserve('window-a', 'process', 40, compute_slots=1)
    second = ledger.try_reserve('window-b', 'process', 40, compute_slots=1)
    assert first is not None and second is not None
    ledger.retire_process(first)
    assert ledger.reserved_bytes == 80 and ledger.compute_slots == 2
    assert ledger.try_reserve('print', 'process', 10, compute_slots=1) is None
    with pytest.raises(ValueError):
        ledger.release_buffer(first)
    assert ledger.reserved_bytes == 80
    assert ledger.process_exited(first)
    assert not ledger.process_exited(first), 'exit callbacks may reenter'
    assert ledger.reserved_bytes == 40 and ledger.compute_slots == 1
    assert ledger.try_reserve('print', 'process', 40, compute_slots=1) is not None


def test_buffer_handoff_never_drops_or_doubles_charge():
    ledger = ResourceLedger(byte_limit=64, slot_limit=2)
    image = ledger.try_reserve('reader', 'image', 64)
    assert image is not None
    ledger.transfer(image, 'thumbnail-buffer')
    assert ledger.owner_of(image) == 'thumbnail-buffer'
    assert ledger.reserved_bytes == 64
    assert ledger.try_reserve('another-reader', 'image', 1) is None
    ledger.transfer(image, 'gui-apply')
    assert ledger.reserved_bytes == 64
    assert ledger.release_buffer(image)
    assert not ledger.release_buffer(image)
    assert ledger.reserved_bytes == 0


def test_unknown_bytes_refuse_without_allocating_capacity():
    ledger = ResourceLedger(byte_limit=100, slot_limit=2)
    assert ledger.try_reserve('worker', 'process', None, compute_slots=1) is None
    assert ledger.try_reserve('snapshot', 'snapshot', None) is None
    assert ledger.reserved_bytes == ledger.compute_slots == 0
    assert ledger.try_reserve('snapshot', 'snapshot', 101) is None
    assert ledger.reserved_bytes == 0


def test_foreign_and_duplicate_releases_cannot_free_another_ledger():
    first = ResourceLedger(byte_limit=100, slot_limit=2)
    second = ResourceLedger(byte_limit=100, slot_limit=2)
    image = first.try_reserve('a', 'image', 30)
    other = second.try_reserve('b', 'image', 30)
    assert not second.release_buffer(image)
    assert second.reserved_bytes == 30
    assert first.release_buffer(image)
    assert not first.release_buffer(image)
    assert second.release_buffer(other)


@pytest.mark.parametrize('amount', [-1, True, 1.5, '2'])
def test_invalid_byte_reservations_do_not_change_usage(amount):
    ledger = ResourceLedger(byte_limit=100, slot_limit=2)
    with pytest.raises((TypeError, ValueError)):
        ledger.try_reserve('a', 'image', amount)
    assert ledger.reserved_bytes == ledger.compute_slots == 0


def test_metadata_helper_memory_counts_even_without_compute_slot():
    ledger = ResourceLedger(byte_limit=100, slot_limit=2)
    helper = ledger.try_reserve('history-probe', 'process', 30)
    assert helper is not None
    assert ledger.reserved_bytes == 30 and ledger.compute_slots == 0
    ledger.retire_process(helper)
    assert ledger.try_reserve('renderer', 'process', 80, compute_slots=1) is None
    assert ledger.process_exited(helper)
    assert ledger.try_reserve('renderer', 'process', 80, compute_slots=1) is not None


def test_buffer_cannot_occupy_compute_slot_and_process_exit_is_typed():
    ledger = ResourceLedger(byte_limit=100, slot_limit=2)
    with pytest.raises(ValueError):
        ledger.try_reserve('a', 'image', 10, compute_slots=1)
    image = ledger.try_reserve('a', 'image', 10)
    with pytest.raises(ValueError):
        ledger.process_exited(image)
    assert ledger.reserved_bytes == 10


def test_ledger_has_no_qt_dependency():
    result = subprocess.run([sys.executable, '-c',
        "import src.render_worker.resource_ledger, sys; assert 'PySide6' not in sys.modules"],
        capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
