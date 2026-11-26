"""Document write gate (card B7 step 1, plans/b7-design-astra.md section 1).  No Qt.

One lease per model while a multi-step write (a vector delete pass, later undo/redo of one) is in flight.  Every
other write entry refuses with WriteGateBusy before it touches anything; an OCR result is queued instead
(plan A: OCR stays out of the undo history, so it must never land between a transaction's capture and its record).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any


class WriteGateBusy(RuntimeError):
    """A write entry was called while another transaction holds the document."""


class Lease:
    """The holder's proof of ownership; a context manager that releases on exit."""

    def __init__(self, gate: DocumentWriteGate, kind: str, session_id: Any) -> None:
        self._gate = gate
        self.published = False  # set by CommandManager.record(cmd, lease=): the history record is the publish
        self.kind = kind
        self.session_id = session_id

    @property
    def live(self) -> bool:
        return self._gate._lease is self

    def release(self) -> None:
        if self._gate._lease is self:
            self._gate._lease = None

    def __enter__(self) -> Lease:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


class DocumentWriteGate:
    def __init__(self) -> None:
        self._lease: Lease | None = None

    @property
    def active(self) -> bool:
        return self._lease is not None

    @property
    def kind(self) -> str | None:
        return None if self._lease is None else self._lease.kind

    @property
    def session_id(self) -> Any:
        return None if self._lease is None else self._lease.session_id

    def begin(self, kind: str, session_id: Any = None) -> Lease:
        if self._lease is not None:
            raise WriteGateBusy(f"document is busy: {self._lease.kind}")
        self._lease = Lease(self, kind, session_id)
        return self._lease

    def holds(self, lease: Lease | None) -> bool:
        return lease is not None and self._lease is lease

    def check(self, lease: Lease | None = None) -> None:
        """Pass when free, or when the given lease is the live one (the holder's own calls)."""
        if lease is not None and self._lease is not lease:
            raise WriteGateBusy("the lease is not the live one")  # released, or issued by another gate
        if self._lease is not None and self._lease is not lease:
            raise WriteGateBusy(f"document is busy: {self._lease.kind}")


@dataclass(frozen=True)
class Applied:
    count: int


@dataclass(frozen=True)
class Deferred:
    queued: int


@dataclass(frozen=True)
class Stale:
    reason: str


# Every PDFModel method that writes the document through a public entry.  Wrapped by install(); the
# inventory test (test_vector_write_gate.py) fails when a method that bumps edit_count is in neither table.
GATED_MODEL_METHODS: tuple[str, ...] = (
    "insert_blank_page",
    "insert_pages_from_file",
    "delete_pages",
    "rotate_pages",
    "straighten_page",
    "move_page",
    "set_editable_metadata",
    "set_toc",
    "apply_pending_redactions",
    "apply_ocr_spans",
    "add_textbox",
    "add_image_object",
    "edit_text",
    "move_object",
    "resize_object",
    "rotate_object",
    "delete_object",
    "delete_objects_atomic",
    "replace_active_document_from_snapshot",
    "save_as",
    "save_session_as",
    "open_pdf",
    "close",
    "close_session",
    "close_all_sessions",
    "import_session_transfer",
)

# edit_count bumpers that are not entries of their own (name -> why).
NOT_A_WRITE_ENTRY: dict[str, str] = {
    "compose_merged_document": "builds a NEW document; the live one is only read",
    "compose_merged_document_with_origins": "builds a NEW document; the live one is only read",
    "export_pages": "writes a copy file; the live document is not changed",
    "save_external_document": "saves a document the caller owns (not the live handle)",
    "write_pruned_live_copy": "writes a copy file; the live document is not changed",
    "build_pdf_audit_report": "read-only report",
    "build_preview_insert_css": "pure string builder",
    "capture_optimize_source": "reads the live document into bytes",
    "get_object_info_at_point": "read-only hit test",
    "refresh_structural_indexes": "rebuilds derived indexes, not document content",
    "save_optimized_copy": "writes a copy file from a snapshot",
    "save_optimized_copy_from_snapshot": "writes a copy file from a snapshot",
    "commit_vector_plan": "takes its own lease (see write_transaction)",
    "doc": "property: the live handle accessor (retires dead handles), not a writer",
}


# ToolManager extensions that write the document (class name -> methods); their gate is model.write_gate.
GATED_TOOL_METHODS: dict[str, tuple[str, ...]] = {
    "AnnotationTool": (
        "add_highlight",
        "add_underline",
        "add_strikeout",
        "add_rect",
        "add_annotation",
        "update_annotation",
        "move_annotation",
        "delete_annotation",
        "toggle_annotations_visibility",
    ),
    "WatermarkTool": ("add_watermark", "remove_watermark", "update_watermark"),
}


def gated(fn: Any) -> Any:
    @functools.wraps(fn)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        lease = kwargs.pop("write_lease", None)
        gate = getattr(self, "write_gate", None) or getattr(getattr(self, "_model", None), "write_gate", None)
        if isinstance(gate, DocumentWriteGate):
            gate.check(lease)
        return fn(self, *args, **kwargs)

    wrapper.__write_gated__ = True  # type: ignore[attr-defined]
    return wrapper


def install_tools(classes: dict[str, type]) -> None:
    for cls_name, names in GATED_TOOL_METHODS.items():
        for name in names:
            setattr(classes[cls_name], name, gated(getattr(classes[cls_name], name)))


def install(cls: type) -> None:
    for name in GATED_MODEL_METHODS:
        setattr(cls, name, gated(getattr(cls, name)))
