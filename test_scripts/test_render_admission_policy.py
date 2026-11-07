from __future__ import annotations

import subprocess
import sys

import pytest

from src.render_worker import admission
from src.render_worker.memory import SystemMemory

MIB = 1024 * 1024
GIB = 1024 * MIB


def memory(total=16 * GIB, avail=8 * GIB, commit=12 * GIB):
    return SystemMemory(total_phys=total, avail_phys=avail, avail_commit=commit)


def test_unknown_system_memory_admits_nothing_optional():
    assert admission.byte_limit(None) == 0
    assert not admission.optional_headroom_ok(None, admission.OPTIONAL_RENDER_CHARGE)


def test_limit_is_required_charge_plus_allowance_when_memory_is_plentiful():
    assert admission.byte_limit(memory()) == admission.REQUIRED_RENDER_CHARGE + admission.OPTIONAL_ALLOWANCE


def test_commit_headroom_below_physical_headroom_is_what_counts():
    limit = admission.byte_limit(memory(avail=8 * GIB, commit=GIB + 100 * MIB))
    assert limit == 0 or limit < admission.REQUIRED_RENDER_CHARGE
    assert admission.byte_limit(memory(avail=8 * GIB, commit=GIB)) == 0


def test_headroom_never_goes_negative_and_keeps_an_os_floor():
    assert admission.byte_limit(memory(total=4 * GIB, avail=GIB // 2, commit=GIB)) == 0
    floor = max(GIB, 16 * GIB // 16)
    assert admission.byte_limit(memory(avail=floor + 50 * MIB, commit=16 * GIB)) == 50 * MIB


def test_optional_headroom_check_is_live_and_floor_based():
    ok = memory(avail=4 * GIB, commit=8 * GIB)
    assert admission.optional_headroom_ok(ok, admission.OPTIONAL_RENDER_CHARGE)
    tight = memory(avail=GIB + 10 * MIB, commit=8 * GIB)  # 16 GiB machine: floor is 1 GiB
    assert not admission.optional_headroom_ok(tight, admission.OPTIONAL_RENDER_CHARGE)


def test_charges_are_pinned_so_changing_one_is_deliberate():
    assert admission.REQUIRED_RENDER_CHARGE == 384 * MIB
    assert admission.OPTIONAL_RENDER_CHARGE == 224 * MIB
    assert admission.PROBE_CHARGE == 20 * MIB
    assert admission.OPTIONAL_ALLOWANCE == 236 * MIB


def test_reader_returns_none_off_windows_or_on_failure(monkeypatch):
    from src.render_worker import memory as memory_module

    monkeypatch.setattr(memory_module.sys, 'platform', 'linux')
    assert memory_module.read_system_memory() is None


def test_policy_modules_have_no_qt_dependency():
    result = subprocess.run([sys.executable, '-c',
        "import src.render_worker.admission, sys; assert 'PySide6' not in sys.modules"],
        capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_live_reader_reports_consistent_numbers_on_this_machine():
    if sys.platform != 'win32':
        pytest.skip('Windows API')
    from src.render_worker.memory import read_system_memory

    value = read_system_memory()
    assert value is not None
    assert 0 < value.avail_phys <= value.total_phys
    assert value.avail_commit > 0


def test_expansion_decisions_are_counted_by_cause(monkeypatch):
    from src.render_worker import memory as memory_module

    for key in admission.expansion_stats:
        admission.expansion_stats[key] = 0
    monkeypatch.delenv('PDF_EDITOR_RENDER_WORKERS', raising=False)
    assert admission.expansion_allowed() is False
    monkeypatch.setenv('PDF_EDITOR_RENDER_WORKERS', '2')
    monkeypatch.setattr(memory_module, 'read_system_memory', lambda: None)
    assert admission.expansion_allowed() is False
    monkeypatch.setattr(memory_module, 'read_system_memory', lambda: memory())
    assert admission.expansion_allowed() is True
    assert admission.expansion_stats == {'checks': 3, 'denied_flag': 1, 'denied_os': 1, 'allowed': 1}
