"""Card A3b: H24 memory cap formula and its Job Object containment."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.render_worker.admission import GIB, MIB, object_probe_memory_limit
from src.render_worker.memory import SystemMemory

REPO_ROOT = Path(__file__).resolve().parents[1]


def _mem(total_gib: float, free_gib: float) -> SystemMemory:
    return SystemMemory(total_phys=int(total_gib * GIB), avail_phys=int(free_gib * GIB), avail_commit=int(free_gib * GIB))


def test_none_memory_gives_no_limit():
    assert object_probe_memory_limit(None) is None


def test_sixteen_gib_with_twelve_free_gives_the_ceiling():
    assert object_probe_memory_limit(_mem(16, 12)) == 1728 * MIB


def test_eight_gib_total_is_capped_at_one_gib():
    limit = object_probe_memory_limit(_mem(8, 7))
    assert limit is not None and limit <= 1024 * MIB


def test_three_gib_total_with_little_headroom_gives_none():
    assert object_probe_memory_limit(_mem(3, 1.3)) is None


@pytest.mark.parametrize("total,free", [(16, 12), (8, 7), (32, 20), (12, 5), (64, 3)])
def test_every_limit_is_a_multiple_of_64_mib(total, free):
    limit = object_probe_memory_limit(_mem(total, free))
    assert limit is None or limit % (64 * MIB) == 0


def test_commit_headroom_below_physical_is_what_counts():
    memory = SystemMemory(total_phys=32 * GIB, avail_phys=30 * GIB, avail_commit=2 * GIB)
    assert object_probe_memory_limit(memory) is None


def test_old_fixed_charge_is_gone():
    import src.render_worker.admission as admission

    assert not hasattr(admission, "OBJECT_PROBE_CHARGE")
    assert admission.OBJECT_PROBE_MEMORY_CEILING == 1728 * MIB
    assert admission.OBJECT_PROBE_MIN_LIMIT == 256 * MIB


def test_other_platforms_raise_containment_error(monkeypatch):
    from src.object_probe import memory_limit

    monkeypatch.setattr(memory_limit.sys, "platform", "linux")
    with pytest.raises(memory_limit.ContainmentError):
        memory_limit.apply_job_memory_limit(128 * MIB)


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
def test_limit_makes_allocation_fail_with_memory_error(tmp_path):
    script = tmp_path / "alloc.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from src.object_probe.memory_limit import apply_job_memory_limit
            apply_job_memory_limit(128 * 1024 * 1024)
            try:
                bytearray(256 * 1024 * 1024)
            except MemoryError:
                print("MEMORY_ERROR")
            else:
                print("ALLOCATED")
            """
        ),
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(script)], capture_output=True, timeout=60, text=True)
    assert result.stdout.strip() == "MEMORY_ERROR", result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
def test_failed_set_information_raises_containment_error(tmp_path):
    script = tmp_path / "fail.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import ctypes, sys
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from src.object_probe import memory_limit
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            real = memory_limit._kernel32
            class Patched:
                def __getattr__(self, name):
                    if name == "SetInformationJobObject":
                        return lambda *a, **k: 0
                    return getattr(real, name)
            memory_limit._kernel32 = Patched()
            try:
                memory_limit.apply_job_memory_limit(128 * 1024 * 1024)
            except memory_limit.ContainmentError:
                print("CONTAINMENT_ERROR")
            """
        ),
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(script)], capture_output=True, timeout=60, text=True)
    assert result.stdout.strip() == "CONTAINMENT_ERROR", result.stderr
