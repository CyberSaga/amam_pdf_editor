from __future__ import annotations

from unittest.mock import MagicMock

from controller.print_coordinator import PrintCoordinator
from src.render_worker import admission
from src.render_worker.resource_ledger import ResourceLedger


def _coordinator(monkeypatch):
    class _FakeController:
        view = None

    pc = PrintCoordinator(_FakeController())
    monkeypatch.setattr(pc, '_create_print_runner', lambda job: MagicMock())
    monkeypatch.setattr(pc, '_update_print_progress_dialog', lambda *_: None)
    monkeypatch.setattr(pc, '_complete_active_print_submission_if_idle', lambda: None)
    return pc


def test_charge_is_pinned_from_the_measured_helper_peak():
    # Peak working set of the helper's render loop (300 dpi): HVAC 1033 MiB, heavy 1299 MiB.
    assert admission.PRINT_HELPER_CHARGE == 1344 * admission.MIB


def test_print_helper_is_required_work_charged_until_the_runner_finishes(qapp, monkeypatch):
    ledger = ResourceLedger(byte_limit=admission.REQUIRED_RENDER_CHARGE, slot_limit=2)
    monkeypatch.setattr(qapp, '_pdf_resource_ledger', ledger, raising=False)
    pc = _coordinator(monkeypatch)
    pc._on_print_job_prepared(object())
    assert ledger.reserved_bytes == admission.PRINT_HELPER_CHARGE
    assert ledger.compute_slots == 0
    assert ledger.stats()['overcommits'] == 1, 'a user print is never refused, only counted'
    assert pc._print_runner is not None
    pc._on_print_runner_finished()
    assert ledger.reserved_bytes == 0


def test_a_running_print_keeps_a_second_renderer_from_fitting(qapp, monkeypatch):
    ledger = ResourceLedger(byte_limit=admission.REQUIRED_RENDER_CHARGE + admission.OPTIONAL_ALLOWANCE,
                            slot_limit=2)
    monkeypatch.setattr(qapp, '_pdf_resource_ledger', ledger, raising=False)
    pc = _coordinator(monkeypatch)
    assert ledger.would_fit(admission.OPTIONAL_RENDER_CHARGE, compute_slots=1)
    pc._on_print_job_prepared(object())
    assert not ledger.would_fit(admission.OPTIONAL_RENDER_CHARGE, compute_slots=1)
    pc._on_print_runner_finished()
    assert ledger.would_fit(admission.OPTIONAL_RENDER_CHARGE, compute_slots=1)


def test_without_a_ledger_printing_is_unchanged(qapp, monkeypatch):
    monkeypatch.delattr(qapp, '_pdf_resource_ledger', raising=False)
    pc = _coordinator(monkeypatch)
    pc._on_print_job_prepared(object())
    assert pc._print_runner is not None and pc._print_lease is None
    pc._on_print_runner_finished()


def test_a_second_finish_notification_releases_nothing_twice(qapp, monkeypatch):
    ledger = ResourceLedger(byte_limit=1, slot_limit=2)
    monkeypatch.setattr(qapp, '_pdf_resource_ledger', ledger, raising=False)
    pc = _coordinator(monkeypatch)
    pc._on_print_job_prepared(object())
    assert ledger.reserved_bytes == admission.PRINT_HELPER_CHARGE
    pc._on_print_runner_finished()
    assert ledger.reserved_bytes == 0
    other = ledger.try_reserve('someone-else', 'process', 5, required=True)
    pc._on_print_runner_finished()
    assert ledger.reserved_bytes == 5, 'a repeated notification must not release another charge'
    assert other is not None


def test_a_start_that_raises_releases_the_charge(qapp, monkeypatch):
    import pytest

    ledger = ResourceLedger(byte_limit=1, slot_limit=2)
    monkeypatch.setattr(qapp, '_pdf_resource_ledger', ledger, raising=False)
    pc = _coordinator(monkeypatch)
    runner = MagicMock()
    runner.start.side_effect = OSError('work dir is gone')
    monkeypatch.setattr(pc, '_create_print_runner', lambda job: runner)
    with pytest.raises(OSError):
        pc._on_print_job_prepared(object())
    assert ledger.reserved_bytes == 0 and pc._print_lease is None
