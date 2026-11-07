from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True, eq=False)
class ResourceLease:
    """Opaque identity held in the parent; never sent over worker IPC."""


@dataclass
class _Entry:
    owner: str
    kind: str
    byte_count: int
    compute_slots: int
    retiring: bool = False


class ResourceLedger:
    """Single-owner-thread ledger for EXPLICIT reservations, not an OS cap.

    Unknown native allocation cannot be inferred from pixels, file size or a
    sampled peak. Callers must qualify their reservation separately. A zero-
    slot metadata process still owns a process lifetime and a byte charge.
    Logical cancellation never releases a process lease: the exit observer
    must confirm actual exit. This foundation does not itself admit App work.
    """

    def __init__(self, *, byte_limit: int, slot_limit: int = 2) -> None:
        self._check_count(byte_limit, 'byte_limit')
        self._check_count(slot_limit, 'slot_limit')
        self._byte_limit = byte_limit
        self._slot_limit = slot_limit
        self._entries: dict[ResourceLease, _Entry] = {}
        self._bytes = 0
        self._slots = 0
        self._owner_thread = threading.get_ident()
        self._refusals: dict[tuple[str, str], int] = {}
        self._overcommits = 0
        self._peak_bytes = 0
        self._peak_slots = 0

    def _check_thread(self) -> None:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError('ResourceLedger is single-owner-thread')

    def _refuse(self, kind: str, reason: str) -> None:
        self._refusals[(kind, reason)] = self._refusals.get((kind, reason), 0) + 1

    def stats(self) -> dict[str, object]:
        return {'reserved_bytes': self._bytes, 'compute_slots': self._slots,
                'peak_bytes': self._peak_bytes, 'peak_slots': self._peak_slots,
                'overcommits': self._overcommits, 'refusals': dict(self._refusals),
                'byte_limit': self._byte_limit, 'slot_limit': self._slot_limit}

    def would_fit(self, byte_count: int | None, *, compute_slots: int = 0) -> bool:
        """Side-effect-free eligibility; a later reservation can still race."""
        if byte_count is None:
            return False
        self._check_count(byte_count, 'byte_count')
        self._check_count(compute_slots, 'compute_slots')
        return (self._bytes + byte_count <= self._byte_limit
                and self._slots + compute_slots <= self._slot_limit)

    @staticmethod
    def _check_count(value: int, label: str) -> None:
        if type(value) is not int:
            raise TypeError(f'{label} must be an integer')
        if value < 0:
            raise ValueError(f'{label} must be nonnegative')

    @staticmethod
    def _check_owner(owner: str) -> None:
        if not isinstance(owner, str):
            raise TypeError('owner must be a string')
        if not owner.strip():
            raise ValueError('owner must not be empty')

    @property
    def reserved_bytes(self) -> int:
        return self._bytes

    @property
    def compute_slots(self) -> int:
        return self._slots

    @property
    def retiring_slots(self) -> int:
        return sum(entry.compute_slots for entry in self._entries.values() if entry.retiring)

    def try_reserve(self, owner: str, kind: str, byte_count: int | None, *,
                    compute_slots: int = 0, required: bool = False) -> ResourceLease | None:
        """Reserve explicit bytes and slots.

        ``required`` work (the first renderer, a print helper) skips the byte
        limit but never the slot limit and is counted as an overcommit: refusing
        it would only move the same native work into the App.
        """
        self._check_thread()
        self._check_owner(owner)
        if kind not in {'process', 'snapshot', 'image', 'cache', 'ipc'}:
            raise ValueError('unknown resource category')
        self._check_count(compute_slots, 'compute_slots')
        if kind != 'process' and compute_slots:
            raise ValueError('only a process may reserve compute slots')
        if byte_count is None:
            self._refuse(kind, 'unknown_size')
            return None
        self._check_count(byte_count, 'byte_count')
        if self._slots + compute_slots > self._slot_limit:
            self._refuse(kind, 'slots')
            return None
        over = self._bytes + byte_count > self._byte_limit
        if over and not required:
            self._refuse(kind, 'bytes')
            return None
        if over:
            self._overcommits += 1
        lease = ResourceLease()
        self._entries[lease] = _Entry(owner, kind, byte_count, compute_slots)
        self._bytes += byte_count
        self._slots += compute_slots
        self._peak_bytes = max(self._peak_bytes, self._bytes)
        self._peak_slots = max(self._peak_slots, self._slots)
        return lease

    def _entry(self, lease: ResourceLease) -> _Entry | None:
        if not isinstance(lease, ResourceLease):
            raise TypeError('invalid resource lease')
        return self._entries.get(lease)

    def owner_of(self, lease: ResourceLease) -> str | None:
        entry = self._entry(lease)
        return entry.owner if entry is not None else None

    def transfer(self, lease: ResourceLease, new_owner: str) -> None:
        self._check_thread()
        self._check_owner(new_owner)
        entry = self._entry(lease)
        if entry is None:
            raise ValueError('lease is not active in this ledger')
        entry.owner = new_owner

    def reactivate(self, lease: ResourceLease) -> bool:
        """A retiring process lease becomes active again for its own restart.

        The charge stays continuous across the exit/restart gap, so no rival can
        take the slot between a confirmed exit and the replacement's start.
        """
        self._check_thread()
        entry = self._entry(lease)
        if entry is None:
            return False
        if entry.kind != 'process':
            raise ValueError('not a process lease')
        if not entry.retiring:
            return False
        entry.retiring = False
        return True

    def retire_process(self, lease: ResourceLease) -> bool:
        self._check_thread()
        entry = self._entry(lease)
        if entry is None:
            return False
        if entry.kind != 'process':
            raise ValueError('not a process lease')
        entry.retiring = True
        return True

    def _release(self, lease: ResourceLease, *, process: bool) -> bool:
        self._check_thread()
        entry = self._entry(lease)
        if entry is None:
            return False
        if (entry.kind == 'process') != process:
            raise ValueError('process charges require confirmed exit; buffers require consumption/discard')
        del self._entries[lease]
        self._bytes -= entry.byte_count
        self._slots -= entry.compute_slots
        return True

    def release_buffer(self, lease: ResourceLease) -> bool:
        return self._release(lease, process=False)

    def process_exited(self, lease: ResourceLease) -> bool:
        return self._release(lease, process=True)
