from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SessionTransferPayload:
    snapshot_bytes: bytes = field(repr=False)
    source_path: str
    saved_path: str | None
    display_name: str
    dirty: bool
    current_page: int
    scale: float
    color_profile: str
    password: str | None = field(default=None, repr=False)
    auth_level: int | None = None
    # The sending session's on-disk baseline (F11-OPEN-2): ``(size, mtime_ns, edge
    # digest)`` of ``disk_fingerprint_path`` as it opened or last wrote it.  It
    # travels with the payload because the receiver cannot measure it: whatever a
    # foreign writer did to the file before the detach would become its baseline.
    # ``None`` = the sender had none (the file was unreadable at open).
    disk_fingerprint: tuple[int, int, str] | None = None
    disk_fingerprint_path: str | None = None
    # The sending session was latched damaged (a failed edit whose rollback also
    # failed): its snapshot holds the half-rewritten page, so the receiving
    # window must refuse in-place saves too (S13-DLG5-DAMAGED).
    damaged: bool = False
    # Canonical paths the damaged sender protects (the files it was bound to
    # when latched): after a Save As ``source_path`` is the new file, so the
    # original would otherwise lose its protection in the receiving window
    # (F14-DMG-1).  Empty for an undamaged session.
    damaged_protected_paths: tuple[str, ...] = ()

    @classmethod
    def from_model(
        cls,
        model,
        session_id: str | None,
        *,
        current_page: int,
        scale: float,
        color_profile: str,
    ) -> SessionTransferPayload:
        if not session_id or model.get_active_session_id() != session_id:
            raise ValueError("the transferred session must be active")
        session = model._sessions_by_id[session_id]
        dirty = bool(
            model.session_has_unsaved_changes(session_id)
            or session.edit_count
            or session.pending_edits
        )
        return cls(
            # KEEPS the source encryption (F11-OPEN-1); the worker snapshot is
            # decrypted and must never become a live session.
            snapshot_bytes=model.capture_session_transfer_bytes(),
            source_path=session.original_path,
            saved_path=session.saved_path,
            display_name=session.display_name,
            dirty=dirty,
            current_page=max(0, int(current_page)),
            scale=max(0.1, float(scale)),
            color_profile=str(color_profile),
            password=session.password,
            auth_level=session.auth_level,
            disk_fingerprint=session.disk_fingerprint,
            disk_fingerprint_path=session.disk_fingerprint_path,
            damaged=bool(session.damaged),
            damaged_protected_paths=tuple(sorted(model.damaged_protected_paths(session_id))),
        )
