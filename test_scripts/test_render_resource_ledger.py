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


def test_required_reservation_ignores_the_byte_limit_but_not_slots_and_is_counted():
    ledger = ResourceLedger(byte_limit=100, slot_limit=1)
    first = ledger.try_reserve('first-worker', 'process', 150, compute_slots=1, required=True)
    assert first is not None
    assert ledger.reserved_bytes == 150
    assert ledger.stats()['overcommits'] == 1
    assert ledger.try_reserve('print', 'process', 1, compute_slots=1, required=True) is None
    assert ledger.stats()['refusals'] == {('process', 'slots'): 1}
    assert ledger.try_reserve('probe', 'process', 1) is None
    assert ledger.stats()['refusals'][('process', 'bytes')] == 1


def test_required_reservation_with_unknown_size_is_still_refused():
    ledger = ResourceLedger(byte_limit=100, slot_limit=1)
    assert ledger.try_reserve('worker', 'process', None, compute_slots=1, required=True) is None
    assert ledger.stats()['refusals'] == {('process', 'unknown_size'): 1}


def test_would_fit_changes_nothing():
    ledger = ResourceLedger(byte_limit=100, slot_limit=1)
    assert ledger.would_fit(100, compute_slots=1)
    assert not ledger.would_fit(101)
    assert not ledger.would_fit(10, compute_slots=2)
    assert not ledger.would_fit(None)
    assert ledger.reserved_bytes == ledger.compute_slots == 0
    assert ledger.stats()['refusals'] == {}


def test_reactivate_keeps_the_charge_continuous_across_a_restart():
    ledger = ResourceLedger(byte_limit=100, slot_limit=1)
    lease = ledger.try_reserve('worker', 'process', 60, compute_slots=1)
    ledger.retire_process(lease)
    assert ledger.retiring_slots == 1
    assert ledger.reactivate(lease)
    assert ledger.retiring_slots == 0
    assert ledger.reserved_bytes == 60 and ledger.compute_slots == 1
    assert ledger.try_reserve('rival', 'process', 1, compute_slots=1) is None
    assert not ledger.reactivate(lease), 'only a retiring lease can be reactivated'


def test_reactivate_rejects_buffers_and_foreign_leases():
    ledger = ResourceLedger(byte_limit=100, slot_limit=1)
    other = ResourceLedger(byte_limit=100, slot_limit=1)
    image = ledger.try_reserve('reader', 'image', 10)
    with pytest.raises(ValueError):
        ledger.reactivate(image)
    foreign = other.try_reserve('worker', 'process', 10, compute_slots=1)
    other.retire_process(foreign)
    assert not ledger.reactivate(foreign)


def test_stats_report_peaks():
    ledger = ResourceLedger(byte_limit=100, slot_limit=2)
    a = ledger.try_reserve('a', 'process', 40, compute_slots=1)
    b = ledger.try_reserve('b', 'process', 30, compute_slots=1)
    ledger.process_exited(a)
    ledger.process_exited(b)
    stats = ledger.stats()
    assert stats['peak_bytes'] == 70 and stats['peak_slots'] == 2
    assert stats['reserved_bytes'] == 0 and stats['compute_slots'] == 0


def test_mutation_from_another_thread_is_rejected():
    import threading

    ledger = ResourceLedger(byte_limit=100, slot_limit=1)
    errors = []

    def mutate():
        try:
            ledger.try_reserve('thread', 'image', 1)
        except RuntimeError as exc:
            errors.append(exc)

    thread = threading.Thread(target=mutate)
    thread.start()
    thread.join()
    assert len(errors) == 1 and ledger.reserved_bytes == 0
