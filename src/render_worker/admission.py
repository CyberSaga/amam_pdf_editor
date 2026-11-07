"""Qt-free admission policy for owned renderer processes.

Charges are constants taken from controlled external-memory runs (the largest
observed child working set plus its ``conhost.exe``, rounded up), not live
measurements: a live peak cannot qualify a reservation. The OS reading only ever
refuses; it never enlarges a charge, and ledger-reserved bytes are never
subtracted from it (resident children are already in the OS figure).
"""
from __future__ import annotations

from src.render_worker.memory import SystemMemory

MIB = 1024 * 1024
GIB = 1024 * MIB

# heavy one-worker child 367 MiB + conhost 8 MiB (entry-heavy-process-external)
REQUIRED_RENDER_CHARGE = 384 * MIB
# trimmed second worker, per-PID maximum 215 MiB + conhost 8 MiB (entry-hvac-two-trim)
OPTIONAL_RENDER_CHARGE = 224 * MIB
# metadata probe python 12 MiB + conhost 8 MiB
PROBE_CHARGE = 20 * MIB
# measured process-versus-thread one-worker increment, rounded up
PROCESS_MODE_BASE_INCREMENT = 64 * MIB
# release gate: App + all children at most baseline + 300 MiB
OPTIONAL_ALLOWANCE = 300 * MIB - PROCESS_MODE_BASE_INCREMENT


def _floor(memory: SystemMemory) -> int:
    # Headroom the OS must keep after an optional worker: 1 GiB, or 1/16 of RAM on big machines.
    return max(GIB, memory.total_phys // 16)


def _headroom(memory: SystemMemory) -> int:
    return min(memory.avail_phys, memory.avail_commit) - _floor(memory)


def byte_limit(memory: SystemMemory | None) -> int:
    """Ledger byte limit; 0 when the OS reading is unknown, so nothing optional fits."""
    if memory is None:
        return 0
    return max(0, min(_headroom(memory), REQUIRED_RENDER_CHARGE + OPTIONAL_ALLOWANCE))


def optional_headroom_ok(memory: SystemMemory | None, charge: int) -> bool:
    """Live re-check before optional work starts: the OS floor must survive the charge."""
    if memory is None:
        return False
    return _headroom(memory) - charge >= 0


def app_ledger(app, *, read=None):
    """The one App-wide ledger, reused by every ``run()`` on the same application.

    Retiring children carried across runs keep their leases, so a per-run ledger
    would not see them. The byte limit is read once, when the ledger is built.
    """
    from src.render_worker.memory import read_system_memory
    from src.render_worker.resource_ledger import ResourceLedger

    ledger = getattr(app, '_pdf_resource_ledger', None)
    if ledger is None:
        ledger = ResourceLedger(byte_limit=byte_limit((read or read_system_memory)()), slot_limit=2)
        app._pdf_resource_ledger = ledger
    return ledger


expansion_stats = {'checks': 0, 'denied_flag': 0, 'denied_os': 0, 'allowed': 0}


def expansion_allowed() -> bool:
    """Eligibility for a second renderer: explicitly enabled and OS headroom survives it.

    Counted, so a run can show whether a missing second worker was policy or pressure.
    """
    from src.render_worker.config import render_worker_count
    from src.render_worker.memory import read_system_memory

    expansion_stats['checks'] += 1
    if render_worker_count() < 2:
        expansion_stats['denied_flag'] += 1
        return False
    if not optional_headroom_ok(read_system_memory(), OPTIONAL_RENDER_CHARGE):
        expansion_stats['denied_os'] += 1
        return False
    expansion_stats['allowed'] += 1
    return True
