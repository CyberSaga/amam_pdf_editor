from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from src.render_worker.memory import ProcessMemory, read_process_memory, sample_memory_cohort


def test_cohort_sums_current_values_not_independent_lifetime_peaks():
    reads = []
    values = {1: ProcessMemory(1, 10, 20, 100), 2: ProcessMemory(2, 30, 40, 200)}
    times = iter([1., 1.03])

    def reader(pid):
        reads.append(pid)
        return values[pid]

    cohort = sample_memory_cohort([1, 2, 1], reader=reader, clock=lambda: next(times))
    assert reads == [1, 2]
    assert cohort.working_set_bytes == 40 and cohort.private_commit_bytes == 60
    assert cohort.started_at == 1. and cohort.finished_at == 1.03
    assert cohort.missing_pids == ()


def test_missing_process_invalidates_total_instead_of_becoming_zero():
    cohort = sample_memory_cohort([1, 2], reader=lambda pid: ProcessMemory(1, 10, 20, 30) if pid == 1 else None)
    assert cohort.missing_pids == (2,)
    assert cohort.working_set_bytes is None and cohort.private_commit_bytes is None
    assert len(cohort.samples) == 1


def test_reader_cannot_substitute_another_pid():
    cohort = sample_memory_cohort([1], reader=lambda pid: ProcessMemory(2, 10, 20, 30))
    assert cohort.missing_pids == (1,) and cohort.samples == ()


@pytest.mark.parametrize('pid', [False, -1, 0, 1.5, '1', 2**32])
def test_cohort_rejects_bad_pid_without_query(pid):
    def forbidden_reader(pid):
        pytest.fail('invalid PID must not reach the OS')

    with pytest.raises((TypeError, ValueError)):
        sample_memory_cohort([pid], reader=forbidden_reader)


def test_empty_owner_set_is_explicit_zero():
    cohort = sample_memory_cohort([])
    assert cohort.samples == () and cohort.missing_pids == ()
    assert cohort.working_set_bytes == 0 and cohort.private_commit_bytes == 0


@pytest.mark.parametrize('query_ok', [True, False])
def test_windows_reader_closes_handle_even_when_query_fails(monkeypatch, query_ok):
    from src.render_worker import memory

    closed = []

    def info(handle, pointer, size):
        counter = pointer._obj
        assert counter.cb == size
        counter.WorkingSetSize = 1024
        counter.PrivateUsage = 2048
        counter.PeakWorkingSetSize = 4096
        return query_ok

    kernel = SimpleNamespace(OpenProcess=lambda *args: 77,
                             CloseHandle=lambda handle: closed.append(handle),
                             K32GetProcessMemoryInfo=info)
    monkeypatch.setattr(memory.sys, 'platform', 'win32')
    monkeypatch.setattr(memory.ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    result = read_process_memory(5)
    assert result == (ProcessMemory(5, 1024, 2048, 4096) if query_ok else None)
    assert closed == [77]
    assert memory.peak_working_set_mb(5) == (round(4096 / 1048576, 1) if query_ok else None)
    assert closed == [77, 77]


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows memory API')
def test_real_current_process_has_current_working_set_and_private_commit():
    sample = read_process_memory(os.getpid())
    assert sample is not None and sample.pid == os.getpid()
    assert sample.working_set_bytes > 0 and sample.private_commit_bytes > 0
    assert sample.peak_working_set_bytes >= sample.working_set_bytes
