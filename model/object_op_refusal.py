"""Stable reason codes for an object operation the Model refuses (D-OLD-MARKERS).

Owner decision after adversarial round 15 ("old unresolved object markers: REPAIR +
MESSAGE"): Move / Resize / Rotate / Delete of an object never fail silently.  The
object ops in ``model/pdf_object_ops.py`` keep their ``bool`` return and record WHY a
``False`` happened on ``PDFModel.last_object_op_refusal`` as an ``ObjectOpRefused``;
the Controller maps the code to one plain Traditional Chinese sentence
(``controller/object_op_refusals.py``).  Add a member here, add its sentence there (a
test pins that every member has one).

Qt-free by construction (CLAUDE.md layer rules), like ``model/text_edit_refusal.py``.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass


class ObjectOpRefusal(str, enum.Enum):
    """Why an object operation changed nothing."""

    # The object is no longer on the page (marker or image placement gone; a selection
    # older than the page).
    OBJECT_NOT_FOUND = "object_not_found"
    # An app image's marker does not resolve to exactly one drawn placement, even after
    # the repair (same digest, same angle, same centre): none, or several equally good.
    IMAGE_NOT_LOCATED = "image_not_located"
    # An app textbox's stored text is not what the page draws in its box and no single
    # drawing can be taken as the box (stale marker of an older build, an edit the
    # marker sync could not place, an edit of a lossy glyph run).
    TEXTBOX_TEXT_CHANGED = "textbox_text_changed"
    # The textbox's drawing is not one Form XObject and its rect holds page text it does
    # not own: removing it would erase that text too (F13-VF-2b).
    TEXTBOX_OVER_PAGE_TEXT = "textbox_over_page_text"
    # The operation does not apply to this object (cross-page move, rotating a kind
    # that cannot turn, a form-nested image).
    NOT_SUPPORTED = "not_supported"
    # Anything else (a content-stream rewrite that could not be applied).
    OPERATION_FAILED = "operation_failed"


@dataclass(frozen=True)
class ObjectOpRefused:
    """One refused object operation: the code and the object it concerned."""

    reason: ObjectOpRefusal
    object_kind: str | None = None
    object_id: str | None = None
