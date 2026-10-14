"""Object-ops engine (R3.4 god-module decomposition seam).

App-object / native-image manipulation extracted out of PDFModel as free functions
(``def fn(model: PDFModel, ...)``), mirroring ``model/pdf_optimizer.py``. PDFModel keeps
1-line delegating wrappers for the public verbs. The controller owns undo snapshots;
destructive operations additionally use a private snapshot for atomic rollback. There are
no direct ``.save``/``.tobytes`` calls on the live doc (the encryption AST guard scans
all of model/).
"""

from __future__ import annotations

import difflib
import html as _html_mod
import functools
import hashlib
import json
import logging
import math
import unicodedata
import uuid
from collections import Counter
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, NamedTuple

import fitz

from model.annot_geometry import annot_page_rect, set_annot_page_rect
from model.font_stream_compaction import font_compaction_scope, insert_htmlbox_tracked
from model.geometry import (
    clamp_rect_to_page,
    rect_from_points,
    unrotated_to_visual_rect,
    visual_to_unrotated_point,
    visual_to_unrotated_rect,
)
from model.object_requests import (
    DeleteObjectRequest,
    MoveObjectRequest,
    ObjectHitInfo,
    ResizeObjectRequest,
    RotateObjectRequest,
)
from model.object_op_refusal import ObjectOpRefusal, ObjectOpRefused
from model.page_content_text import content_text
from model.pdf_content_ops import (
    NativeImageInvocation,
    ParsedOperator,
    _cm_values_from_operands,
    affine_invert,
    affine_point,
    decompose_image_cm,
    discover_native_image_invocations,
    fitz_rect_to_stream_cm,
    form_rect_to_stream_cm,
    page_user_space_matrix,
    parse_operators,
    remove_operator_range,
    replace_operator_operands,
    rotated_image_stream_cm,
)
from model.text_commit.transforms import page_visual_frame_or_none, shift_rect_for_pymupdf_writers
from model.text_normalization import strip_unrenderable_controls
from utils.cjk_ext_b_font import FONT_NAME_PREFIX as EXT_B_FONT_NAME_PREFIX

if TYPE_CHECKING:
    from model.pdf_model import PDFModel

logger = logging.getLogger(__name__)

_APP_OBJECT_SUBJECT_PREFIX = "pdf_editor_"
_TEXTBOX_OBJECT_SUBJECT = "pdf_editor_textbox_object"
_RECT_OBJECT_SUBJECT = "pdf_editor_rect_object"
_IMAGE_OBJECT_SUBJECT = "pdf_editor_image_object"
_APP_OBJECT_VERSION = 1


def _dump_app_object_payload(model: PDFModel, payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

def _load_app_object_payload(model: PDFModel, annot: fitz.Annot) -> dict | None:
    try:
        info = annot.info or {}
        subject = info.get("subject") or ""
        if not subject.startswith(_APP_OBJECT_SUBJECT_PREFIX):
            return None
        content = info.get("content") or ""
        payload = json.loads(content)
        if not isinstance(payload, dict):
            return None
        if payload.get("version") != _APP_OBJECT_VERSION:
            return None
        if payload.get("kind") not in {"textbox", "rect", "image"}:
            return None
        return payload
    except Exception:
        return None

def _payload_rect(payload: dict) -> fitz.Rect | None:
    """``payload["rect"]`` as a non-empty finite rect, or ``None`` when unusable."""
    raw = payload.get("rect")
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            values = [float(v) for v in raw]
        except (TypeError, ValueError):
            values = []
        if len(values) == 4 and all(math.isfinite(v) for v in values):
            rect = fitz.Rect(*values)
            if not rect.is_empty:
                return rect
    return None


def _image_payload_unrotated_rect(annot: fitz.Annot, payload: dict) -> fitz.Rect:
    """An app image's drawn placement in UNROTATED page space (F14-MM-1b).

    Unlike a textbox or ``rect`` payload, an image payload's ``rect`` is NOT visual: it
    is the placement as ``discover_native_image_invocations`` reports it (unrotated page
    space), which is what resolution matches against (2 pt) and what every build has
    written (older builds handed their numbers straight to ``insert_image``, which takes
    unrotated space; F15-4 records the discovered bbox). Keeping that space makes markers
    saved by older builds on /Rotate pages resolve unchanged. Every public value (hit
    test, ``ObjectHitInfo.bbox``) is mapped to visual space by ``_app_object_true_rect``.
    The hidden marker annotation sits on the image: PyMuPDF's annotation rects
    (``add_rect_annot`` / ``set_rect`` / ``annot.rect``) are unrotated page space too, so
    its /Rect (1 pt inflated) is the fallback for a payload without a usable rect.
    """
    rect = _payload_rect(payload)
    if rect is not None:
        return rect
    return annot_page_rect(annot.parent, annot)


def _app_object_true_rect(annot: fitz.Annot, payload: dict) -> fitz.Rect:
    """The object's real visual rect, as the user placed it (F14-MM-2).

    ``payload["rect"]`` is the truth. ``annot.rect`` is the marker's OUTER /Rect:
    PyMuPDF/MuPDF inflates a square annotation by its /RD inset (>= 1 pt per side, and
    ``set_border(width=0)`` does not shrink it back; ``update()`` re-applies it). Using
    the outer rect as the object's bbox made every drag re-feed the inflated rect, so each
    move grew the box 2 pt and shifted its text (-1,-1). Fall back to the annotation rect
    only for a payload without a usable rect. A ``rect`` object's annotation IS the
    drawn rectangle, so its ``/Rect`` is in unrotated page space (see
    ``_marker_pick_rect``) and is mapped to the visual space the payload speaks. An
    image payload holds UNROTATED numbers (``_image_payload_unrotated_rect``), mapped to
    visual here.
    """
    if payload.get("kind") == "image":
        return unrotated_to_visual_rect(annot.parent, _image_payload_unrotated_rect(annot, payload))
    rect = _payload_rect(payload)
    if rect is not None:
        return rect
    return _marker_pick_rect(annot, payload)


def _marker_pick_rect(annot: fitz.Annot, payload: dict) -> fitz.Rect:
    """The marker's pick rect in VISUAL page space (F15-3, F14-MM-1b).

    The hit point, ``destination_rect`` and a textbox/``rect`` ``payload["rect"]`` are
    visual. A textbox marker is a hidden stand-in created from the visual numbers, so its
    /Rect is already in that space. A ``rect`` object's annotation is the drawn rectangle,
    which ``AnnotationTool.add_rect`` places in unrotated space (``derotation_matrix``); on
    a /Rotate 90/180/270 page its /Rect must be mapped back before it meets a visual
    point, or the object can only be picked where nothing is drawn. An image marker's
    /Rect is unrotated as well (it sits on the image); the image is picked where it is
    DRAWN, i.e. its payload placement mapped to visual, with the same 1 pt tolerance the
    inflated marker /Rect gives the other kinds (F14-MM-1b).
    """
    if payload.get("kind") == "image":
        return _app_object_true_rect(annot, payload) + (-1, -1, 1, 1)
    if payload.get("kind") == "textbox" and _annot_rect_is_scaled_wrong(annot.parent):
        # F15-G1-UU-ROT: on a rotated /UserUnit != 1 page MuPDF's ``Annot.rect`` does not
        # read back what ``add_rect_annot(visual_rect)`` wrote (a marker created at
        # y 150 reads back at y -250), so the textbox is picked where it is stored:
        # its payload rect is visual by contract, with the marker's 1 pt tolerance.
        stored = _payload_rect(payload)
        if stored is not None:
            return stored + (-1, -1, 1, 1)
    if payload.get("kind") == "rect":
        # TRUE unrotated space through the page frame (F15-G1-UU-ANNOT): ``Annot.rect``
        # is PyMuPDF's /UserUnit-less derotated space, not the one ``add_rect_annot``
        # (hence ``AnnotationTool.add_rect``) wrote the rectangle in.
        return unrotated_to_visual_rect(annot.parent, annot_page_rect(annot.parent, annot))
    return fitz.Rect(annot.rect)


def _rect_center(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)


def _refuse(model: PDFModel, reason: ObjectOpRefusal) -> bool:
    """Record why an object op changes nothing and return ``False`` (D-OLD-MARKERS).

    The public verb (``_record_outcome``) adds the object's kind and id; the Controller
    shows the code as one zh-TW sentence. Never a silent ``False``.
    """
    model.last_object_op_refusal = ObjectOpRefused(reason)
    return False


def _record_outcome(model: PDFModel, ok: bool, object_kind: object, object_id: object) -> bool:
    """Finish a public object verb: clear the refusal on success, else make sure one is
    recorded (``OPERATION_FAILED`` when no site named a reason) for this object."""
    if ok:
        model.last_object_op_refusal = None
        return True
    recorded = getattr(model, "last_object_op_refusal", None)
    reason = recorded.reason if isinstance(recorded, ObjectOpRefused) else ObjectOpRefusal.OPERATION_FAILED
    model.last_object_op_refusal = ObjectOpRefused(reason, str(object_kind), str(object_id))
    logger.info("object op refused: kind=%s id=%s reason=%s", object_kind, object_id, reason.value)
    return False


def _annot_rect_is_scaled_wrong(page: fitz.Page) -> bool:
    """``True`` on a ``/Rotate``d page with ``/UserUnit != 1``, where ``Annot.rect`` is unusable.

    MEASURED (1.27.1, F15-G2-ANNOT): ``Annot.rect`` / ``set_rect`` map through
    ``page.derotation_matrix``, which drops ``/UserUnit``, so the rect a marker
    reads back is not the one it was created with.
    """
    if int(page.rotation) % 360 == 0:
        return False
    frame = page_visual_frame_or_none(page)
    return frame is not None and abs(frame.user_unit - 1.0) > 1e-9

def _iter_page_annots(model: PDFModel, page_num: int) -> Iterator[fitz.Annot]:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return iter(())
    page = model.doc[page_num - 1]
    try:
        return iter(list(page.annots() or []))
    except Exception:
        return iter(())

def _find_app_object_annot(model: PDFModel, page_num: int, object_id: str, expected_kind: str | None = None) -> tuple[fitz.Page, fitz.Annot, dict] | None:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return None
    page = model.doc[page_num - 1]
    try:
        annots = list(page.annots() or [])
    except Exception:
        return None
    for annot in annots:
        payload = _load_app_object_payload(model, annot)
        if payload is None:
            continue
        if payload.get("object_id") != object_id:
            continue
        if expected_kind is not None and payload.get("kind") != expected_kind:
            continue
        return page, annot, payload
    return None

def _find_native_image_invocation(model: PDFModel, page_num: int, object_id: str) -> NativeImageInvocation | None:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return None
    prefix = f"native_image:{page_num}:"
    if not str(object_id).startswith(prefix):
        return None
    try:
        occurrence_index = int(str(object_id).split(":")[-1])
    except Exception:
        return None
    invocations = discover_native_image_invocations(model.doc, page_num)
    for invocation in invocations:
        if invocation.occurrence_index == occurrence_index:
            return invocation
    return None

def _rewrite_native_image_matrix(
    model: PDFModel,
    invocation: NativeImageInvocation,
    destination_rect: fitz.Rect,
    rotation: float,
) -> bool:
    """Rewrite the image's ``cm`` so it is drawn into ``destination_rect``.

    ``destination_rect`` is UNROTATED page space, like ``invocation.bbox`` (the space of
    ``discover_native_image_invocations`` and of every ``cm`` writer); a caller holding a
    visual rect (a move's destination) maps it with ``visual_to_unrotated_rect`` first
    (F14-MM-1b). ``rotation`` is the stored (raw-cm) angle.
    """
    # typed bind; callers guarantee an open doc here (native image rewrite path) - runtime behavior identical if None
    doc: fitz.Document = model.doc
    page = doc[invocation.page_num - 1]
    if invocation.cm_operator_index is None:
        return False
    stream = doc.xref_stream(invocation.stream_xref)
    tokens, operators = parse_operators(stream)
    if invocation.cm_operator_index >= len(operators):
        return False
    cm_operator = operators[invocation.cm_operator_index]
    if cm_operator.name != "cm":
        return False
    rot = float(rotation) % 360.0
    if invocation.is_form_nested:
        current_cm = _cm_values_from_operands(cm_operator.operands)
        if current_cm is None:
            return False
        new_operands = form_rect_to_stream_cm(
            fitz.Rect(destination_rect),
            current_cm,
            fitz.Rect(invocation.bbox),
            rot,
        )
        if new_operands is None:
            return False
    elif abs(rot - round(rot / 90.0) * 90.0) > 0.5:
        # Free (non-cardinal) rotation: place the image rotated about its
        # centre. On a pure move the destination AABB has the same size as
        # the current one, so preserve the un-rotated size (and thus the
        # angle) rather than squashing the image into the new AABB.
        current_cm = _cm_values_from_operands(cm_operator.operands)
        if current_cm is None:
            return False
        user_to_page = page_user_space_matrix(page)
        if user_to_page is None:
            return False
        # The cm sizes are user units; the destination is page space. Work in
        # page space and map the centre and sizes back to user space once
        # (F15-G2/G3: CropBox/MediaBox origin and /UserUnit).
        page_per_user = math.hypot(user_to_page[0], user_to_page[1])
        user_w, user_h, _ang, _cx, _cy = decompose_image_cm(current_cm)
        cur_w, cur_h = user_w * page_per_user, user_h * page_per_user
        dest = fitz.Rect(destination_rect)
        cur_bbox = fitz.Rect(invocation.bbox)
        if abs(dest.width - cur_bbox.width) < 0.5 and abs(dest.height - cur_bbox.height) < 0.5:
            # Pure move: preserve the un-rotated size (and thus the angle).
            unrotated_w, unrotated_h = cur_w, cur_h
        else:
            # Resize: the destination is the new axis-aligned bounding box of
            # the rotated image. Recover the un-rotated size so the rendered
            # AABB matches the request, instead of treating the AABB as the
            # image size (which would inflate it by |cos|+|sin|).
            cos_t = abs(math.cos(math.radians(rot)))
            sin_t = abs(math.sin(math.radians(rot)))
            det = cos_t * cos_t - sin_t * sin_t
            if abs(det) > 1e-3:
                unrotated_w = max(1.0, (dest.width * cos_t - dest.height * sin_t) / det)
                unrotated_h = max(1.0, (dest.height * cos_t - dest.width * sin_t) / det)
            else:
                # Near 45°/135° the inversion is singular; keep current size.
                unrotated_w, unrotated_h = cur_w, cur_h
        centre_x_user, centre_y_user = affine_point(
            affine_invert(user_to_page), (dest.x0 + dest.x1) / 2.0, (dest.y0 + dest.y1) / 2.0
        )
        new_operands = rotated_image_stream_cm(
            centre_x_user,
            centre_y_user,
            unrotated_w / page_per_user,
            unrotated_h / page_per_user,
            rot,
        )
    else:
        cardinal_operands = fitz_rect_to_stream_cm(
            fitz.Rect(destination_rect), page, rot
        )
        if cardinal_operands is None:
            return False
        new_operands = cardinal_operands
    new_stream = replace_operator_operands(tokens, cm_operator, new_operands)
    doc.update_stream(invocation.stream_xref, new_stream)
    model.mark_page_content_dirty(invocation.page_num - 1, fitz.Rect(destination_rect))
    model.edit_count += 1
    return True

def _find_app_image_invocation(
    model: PDFModel,
    page_num: int,
    xref: int,
    expected_rect: fitz.Rect,
    *,
    image_digest: str | None = None,
    expected_rotation: float = 0.0,
) -> NativeImageInvocation | None:
    """Resolve an app image without treating its garbage-collectable xref as identity."""
    invocations = discover_native_image_invocations(model.doc, page_num)
    usable = [inv for inv in invocations if inv.cm_operator_index is not None]
    er = fitz.Rect(expected_rect)

    def _rect_dist(inv: NativeImageInvocation) -> float:
        b = inv.bbox
        return sum(abs(a - b_) for a, b_ in zip([b.x0, b.y0, b.x1, b.y1], [er.x0, er.y0, er.x1, er.y1]))

    def _rotation_matches(inv: NativeImageInvocation) -> bool:
        delta = (float(inv.rotation) - float(expected_rotation) + 180.0) % 360.0 - 180.0
        return abs(delta) <= 1.0

    xref_candidates = [inv for inv in usable if inv.xref == xref]
    if xref_candidates:
        if image_digest:
            verified = [
                inv for inv in xref_candidates
                if _image_xref_digest(model, inv.xref) == image_digest
            ]
            positioned = [
                inv for inv in verified
                if _rect_dist(inv) <= 2.0 and _rotation_matches(inv)
            ]
            if positioned:
                return min(positioned, key=_rect_dist)
        else:
            positioned = [
                inv for inv in xref_candidates
                if _rect_dist(inv) <= 2.0 and _rotation_matches(inv)
            ]
            if positioned:
                return min(positioned, key=_rect_dist)

    geometric = [inv for inv in usable if _rect_dist(inv) <= 2.0 and _rotation_matches(inv)]
    if image_digest:
        matches = [inv for inv in geometric if _image_xref_digest(model, inv.xref) == image_digest]
        return matches[0] if len(matches) == 1 else None
    return geometric[0] if len(geometric) == 1 else None


def _image_xref_digest(model: PDFModel, xref: int) -> str | None:
    try:
        # typed bind inside the try; the except still swallows AttributeError if doc is None - reachable-shape identical
        doc: fitz.Document = model.doc
        stream = doc.xref_stream(int(xref))
    except Exception:
        return None
    return hashlib.sha256(stream).hexdigest() if stream else None


def _marker_xref(payload: dict) -> int:
    """The marker payload's recorded image xref, or 0 when absent/unusable.

    Single parse chokepoint: a corrupt or third-party payload (`"xref": "abc"`) used to
    raise `ValueError` straight through `delete_objects_atomic`'s re-raise and into an
    uncaught Qt slot. 0 is the right degraded value — `_find_app_image_invocation` treats it
    as "no recorded xref" and falls back to geometry + digest.
    """
    try:
        return int(payload.get("xref", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _app_image_invocation_candidates(
    model: PDFModel,
    page_num: int,
    payload: dict,
    expected_rect: fitz.Rect,
) -> list[NativeImageInvocation]:
    """Invocations that could plausibly be this marker's image.

    A deliberate *superset* of what `_find_app_image_invocation` will accept, used only to
    tell two failures apart when resolution returns None:

      * **zero** candidates — nothing on the page renders this image any more (an external
        editor stripped the XObject and left our hidden marker behind). The marker is
        orphaned and must be cleaned up, or it becomes an undeletable zombie.
      * **more than one** — the pixels exist but we cannot say which placement is ours.
        Fail safe; deleting the marker alone would orphan visible content.
    """
    er = fitz.Rect(expected_rect)
    candidates: list[NativeImageInvocation] = []
    for inv in discover_native_image_invocations(model.doc, page_num):
        if inv.cm_operator_index is None:
            continue
        b = inv.bbox
        rect_distance = sum(
            abs(a - c)
            for a, c in zip(
                [b.x0, b.y0, b.x1, b.y1],
                [er.x0, er.y0, er.x1, er.y1],
            )
        )
        expected_rotation = float(payload.get("rotation", 0)) % 360
        rotation_delta = (float(inv.rotation) - expected_rotation + 180.0) % 360.0 - 180.0
        if rect_distance <= 2.0 and abs(rotation_delta) <= 1.0:
            candidates.append(inv)
    return candidates


# D-OLD-MARKERS: how far (pt, per axis) a drawing's centre may sit from the marker's and
# still be "the same centre". Rotation about the centre and letterboxing both keep the
# centre exactly; this only absorbs rounding.
_SAME_CENTRE_TOLERANCE = 1.5


def _angle_delta(a: float, b: float) -> float:
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0)


def _same_centre(a: fitz.Rect, b: fitz.Rect) -> bool:
    ca, cb = _rect_center(fitz.Rect(a)), _rect_center(fitz.Rect(b))
    return abs(ca.x - cb.x) <= _SAME_CENTRE_TOLERANCE and abs(ca.y - cb.y) <= _SAME_CENTRE_TOLERANCE


def _marker_image_digest(model: PDFModel, payload: dict) -> str | None:
    """The digest the marker's image must have: the recorded one, else (markers written
    before it was recorded) the digest of the recorded xref's stream."""
    digest = payload.get("image_digest")
    if isinstance(digest, str) and digest:
        return digest
    xref = _marker_xref(payload)
    return _image_xref_digest(model, xref) if xref > 0 else None


def _image_slots_claimed_by_other_markers(
    model: PDFModel, page_num: int, object_id: object
) -> set[tuple[int, int, int]]:
    """Placements another app-image marker on the page resolves to directly."""
    claimed: set[tuple[int, int, int]] = set()
    for annot in _iter_page_annots(model, page_num):
        other = _load_app_object_payload(model, annot)
        if other is None or other.get("kind") != "image" or other.get("object_id") == object_id:
            continue
        found = _find_app_image_invocation(
            model,
            page_num,
            _marker_xref(other),
            _image_payload_unrotated_rect(annot, other),
            image_digest=other.get("image_digest"),
            expected_rotation=float(other.get("rotation", 0)) % 360,
        )
        if found is not None:
            claimed.add(_invocation_slot(found))
    return claimed


def _repair_image_marker(
    model: PDFModel,
    page_num: int,
    annot: fitz.Annot,
    payload: dict,
    expected_rect: fitz.Rect,
) -> NativeImageInvocation | None:
    """Re-resolve a marker an older build saved (D-OLD-MARKERS, F15-4 follow-up a).

    Builds before F15-4 stored the pre-rotation rect with the rotated angle, or the 4:3
    insert rect around a letterboxed picture, so the 2 pt match never finds the drawing.
    Both keep the drawing's CENTRE and angle. The marker is re-resolved only when
    exactly ONE drawn placement has the marker's digest, its angle (1 degree) and its
    centre (``_SAME_CENTRE_TOLERANCE``), and no other marker on the page resolves to it;
    the marker then records that drawing (``_sync_image_marker_to_drawn``) so every
    later verb resolves directly. Several candidates (twins drawn at one centre) or none
    stay unresolved: never a guess.
    """
    digest = _marker_image_digest(model, payload)
    if digest is None:
        return None
    rotation = float(payload.get("rotation", 0)) % 360
    candidates = [
        inv
        for inv in discover_native_image_invocations(model.doc, page_num)
        if inv.cm_operator_index is not None
        and _angle_delta(inv.rotation, rotation) <= 1.0
        and _same_centre(fitz.Rect(inv.bbox), expected_rect)
        and _image_xref_digest(model, inv.xref) == digest
    ]
    if len(candidates) != 1:
        if candidates:
            logger.warning(
                "image object %s: %d same-centre drawings of its picture; marker left unresolved",
                payload.get("object_id"),
                len(candidates),
            )
        return None
    (invocation,) = candidates
    if _invocation_slot(invocation) in _image_slots_claimed_by_other_markers(
        model, page_num, payload.get("object_id")
    ):
        return None
    payload["xref"] = int(invocation.xref)
    payload["image_digest"] = digest
    _sync_image_marker_to_drawn(model, page_num, annot, payload, invocation, rotation)
    logger.info("image object %s: old marker re-resolved to its drawing", payload.get("object_id"))
    return invocation


def _image_drawing_may_remain(
    model: PDFModel, page_num: int, payload: dict, expected_rect: fitz.Rect
) -> bool:
    """True when an unresolved image marker may still have its picture drawn on the page.

    Delete must then refuse rather than remove the hidden marker alone (D-OLD-MARKERS
    rule 3): any placement of the marker's picture (same digest; any picture when the
    digest is unknown) that touches the marker's rect, or shares its centre, and that no
    other marker claims. Only a marker with nothing of its picture left near it is an
    orphan that Delete cleans up.
    """
    digest = _marker_image_digest(model, payload)
    claimed: set[tuple[int, int, int]] | None = None
    for inv in discover_native_image_invocations(model.doc, page_num):
        bbox = fitz.Rect(inv.bbox)
        if not (bbox.intersects(expected_rect) or _same_centre(bbox, expected_rect)):
            continue
        if digest is not None and _image_xref_digest(model, inv.xref) != digest:
            continue
        if claimed is None:
            claimed = _image_slots_claimed_by_other_markers(model, page_num, payload.get("object_id"))
        if _invocation_slot(inv) not in claimed:
            return True
    return False


def _resolve_marker_image_invocation(
    model: PDFModel,
    page_num: int,
    payload: dict,
    expected_rect: fitz.Rect,
    annot: fitz.Annot | None = None,
) -> NativeImageInvocation | None:
    """The placement an app-image marker stands for, or ``None``.

    With ``annot`` an unresolved marker is repaired when it has exactly one clear
    candidate (``_repair_image_marker``); the marker and ``payload`` then hold the
    drawn placement.
    """
    recorded_xref = _marker_xref(payload)
    invocation = _find_app_image_invocation(
        model,
        page_num,
        recorded_xref,
        expected_rect,
        image_digest=payload.get("image_digest"),
        expected_rotation=float(payload.get("rotation", 0)) % 360,
    )
    if invocation is None:
        if annot is None:
            return None
        return _repair_image_marker(model, page_num, annot, payload, expected_rect)
    if invocation.xref != recorded_xref or not payload.get("image_digest"):
        digest = _image_xref_digest(model, invocation.xref)
        if digest is None:
            return None
        payload["xref"] = int(invocation.xref)
        payload["image_digest"] = digest
    return invocation


def _invocation_slot(invocation: NativeImageInvocation) -> tuple[int, int, int]:
    """Identity of one drawn placement: rewriting its ``cm`` operands keeps it."""
    return (int(invocation.stream_xref), int(invocation.do_operator_index), int(invocation.xref))


def _sync_image_marker_to_drawn(
    model: PDFModel,
    page_num: int,
    annot: fitz.Annot,
    payload: dict,
    rewritten: NativeImageInvocation,
    rotation: float,
) -> None:
    """Record the placement just rewritten, as drawn, in its marker (F15-4).

    Chokepoint for every app-image rewrite. The marker's rect and rotation are what
    ``_find_app_image_invocation`` matches (2 pt / 1 degree) on every later verb, so they
    must be the DRAWN axis-aligned bbox and angle, never the requested rect: an absolute
    rotation grows the AABB, a resize near 45 degrees keeps the old size, a delta rotation
    from a free angle changes the AABB. A marker holding the request stops resolving, so
    Move/Rotate return False and Delete takes the orphaned-marker branch (marker removed,
    image left drawn). The placement is re-read by identity (stream, ``Do`` slot, xref),
    which an operand rewrite does not change, never by the stale geometry. Callers have
    already rewritten the stream, so a miss (not reachable: the operand count is kept) is
    logged rather than failed: a False return would leave that rewrite without an undo
    entry, because the controller records undo only on success.
    """
    slot = _invocation_slot(rewritten)
    drawn = next(
        (
            inv
            for inv in discover_native_image_invocations(model.doc, page_num)
            if _invocation_slot(inv) == slot
        ),
        None,
    )
    if drawn is None:
        logger.warning(
            "image object %s: rewritten placement not found again; marker left unchanged",
            payload.get("object_id"),
        )
        return
    # payload["rect"] and the marker /Rect are both UNROTATED page space, where the image
    # is drawn (``_image_payload_unrotated_rect``; annotation rects are unrotated too).
    bbox = fitz.Rect(drawn.bbox)
    payload["rotation"] = float(rotation) % 360
    payload["rect"] = [float(bbox.x0), float(bbox.y0), float(bbox.x1), float(bbox.y1)]
    set_annot_page_rect(annot.parent, annot, bbox)
    annot.set_info(content=_dump_app_object_payload(model, payload), subject=_IMAGE_OBJECT_SUBJECT)
    annot.update()

# PDF name tokens end at whitespace or a delimiter (PDF 1.7 §7.2.2, Tables 1-2).
_PDF_NAME_TERMINATORS = frozenset(b"\x00\t\n\x0c\r ()<>[]{}/%")


def _stream_references_xobject(stream: bytes, xobject_name: str) -> bool:
    """True when ``stream`` invokes ``/<xobject_name>`` as a whole name token.

    A raw substring test is wrong: ``b"/fzImg1" in stream`` is satisfied by the token
    ``/fzImg10``, so deleting the 2nd of 11+ images would leave its resource entry behind.
    Match only where the name is followed by a delimiter or the end of the stream.
    """
    token = f"/{xobject_name}".encode("latin-1")
    start = 0
    while True:
        index = stream.find(token, start)
        if index < 0:
            return False
        end = index + len(token)
        if end == len(stream) or stream[end] in _PDF_NAME_TERMINATORS:
            return True
        start = end


def _effective_page_xobject_binding(
    doc: fitz.Document,
    page: fitz.Page,
    xobject_name: str,
) -> tuple[int, int] | None:
    """Return the effective resource owner and xref for a page-level XObject name."""
    key = f"Resources/XObject/{xobject_name}"
    node = page.xref
    seen: set[int] = set()
    while node not in seen:
        seen.add(node)
        if doc.xref_get_key(node, "Resources")[0] != "null":
            kind, value = doc.xref_get_key(node, key)
            if kind != "xref":
                return None
            try:
                return node, int(str(value).split()[0])
            except (ValueError, IndexError):
                return None
        kind, value = doc.xref_get_key(node, "Parent")
        if kind != "xref":
            return None
        try:
            node = int(str(value).split()[0])
        except (ValueError, IndexError):
            return None
    return None


def _resolve_xobject_resource_owner(
    doc: fitz.Document, page: fitz.Page, invocation: NativeImageInvocation
) -> int | None:
    """The xref of the dict that actually holds ``Resources/XObject/<name>``.

    ``/Resources`` is inheritable: a page may have none of its own and resolve it through
    its ``/Parent`` chain, in which case PyMuPDF's ``insert_image`` registers the XObject
    in that *ancestor* dict. Nulling the key on the page would not remove it — worse,
    ``xref_set_key`` creates every missing link in the path, fabricating a direct
    ``/Resources`` on the page that SHADOWS the inherited one, so the page's fonts and
    other XObjects stop resolving. Returns ``None`` when the owner cannot be located.
    """
    if invocation.is_form_nested:
        return invocation.resource_owner_xref or invocation.stream_xref

    binding = _effective_page_xobject_binding(doc, page, invocation.xobject_name)
    if binding is None or binding[1] != invocation.xref:
        return None
    return binding[0]


# Operators that change graphics state or build a path/clip but paint nothing. A q..Q
# block made of these plus one image Do is that image's placement and nothing else.
_NON_PAINTING_OPERATORS = frozenset(
    {
        "q", "Q", "cm", "gs", "w", "J", "j", "M", "d", "ri", "i",
        "CS", "cs", "SC", "SCN", "sc", "scn", "G", "g", "RG", "rg", "K", "k",
        "m", "l", "c", "v", "y", "h", "re", "W", "W*", "n",
    }
)


def _q_block_paints_only_the_do(
    operators: list[ParsedOperator], q_index: int, q_end_index: int, do_index: int
) -> bool:
    """True when the ``q``..``Q`` block draws nothing but its ``Do`` at ``do_index``.

    F13-VF-2b class: removing the whole block of an image that shares it with text,
    vector art or marked content erased that content too.
    """
    return all(
        index == do_index or operators[index].name in _NON_PAINTING_OPERATORS
        for index in range(q_index + 1, q_end_index)
    )


def _remove_native_image_invocation(model: PDFModel, invocation: NativeImageInvocation) -> bool:
    # typed bind; callers guarantee an open doc here (native image removal path) - runtime behavior identical if None
    doc: fitz.Document = model.doc
    page = doc[invocation.page_num - 1]
    stream = doc.xref_stream(invocation.stream_xref)
    tokens, operators = parse_operators(stream)
    if invocation.do_operator_index >= len(operators):
        return False
    # Only the Do by default: it draws nothing but this image, and leaving the cm in
    # place keeps the CTM of whatever the same scope draws after it.
    start_token = operators[invocation.do_operator_index].operand_start
    end_token = operators[invocation.do_operator_index].operator_index
    if (
        invocation.q_operator_index is not None
        and invocation.q_end_operator_index is not None
        and invocation.q_operator_index < len(operators)
        and invocation.q_end_operator_index < len(operators)
        and invocation.q_image_invocation_count == 1
        and _q_block_paints_only_the_do(
            operators, invocation.q_operator_index, invocation.q_end_operator_index, invocation.do_operator_index
        )
    ):
        # The whole q..Q block is this image's placement (q cm /Im Do Q): drop it all.
        start_token = operators[invocation.q_operator_index].operand_start
        end_token = operators[invocation.q_end_operator_index].operator_index
    new_stream = remove_operator_range(tokens, start_token, end_token)
    doc.update_stream(invocation.stream_xref, new_stream)

    owner_xref = _resolve_xobject_resource_owner(doc, page, invocation)
    if owner_xref is not None:
        # A form-nested image is named in the form's own resources and drawn from the
        # form's single stream. A page-level image may be drawn from several of the
        # page's content streams; and when the owner is an *inherited* resources dict,
        # sibling pages share it, so every page must be cleared before pruning.
        if invocation.is_form_nested:
            scan_streams = [invocation.stream_xref]
        else:
            scan_streams = [
                int(xref)
                for other in doc
                if _effective_page_xobject_binding(
                    doc, other, invocation.xobject_name
                ) == (owner_xref, invocation.xref)
                for xref in other.get_contents()
                if int(xref) > 0
            ]
        still_referenced = any(
            _stream_references_xobject(doc.xref_stream(int(xref)), invocation.xobject_name)
            for xref in scan_streams
        )
        if not still_referenced:
            try:
                doc.xref_set_key(owner_xref, f"Resources/XObject/{invocation.xobject_name}", "null")
            except Exception:
                logger.debug(
                    "Could not prune XObject resource %s from xref %s",
                    invocation.xobject_name,
                    owner_xref,
                )
    model.mark_page_content_dirty(invocation.page_num - 1, fitz.Rect(invocation.bbox))
    model.edit_count += 1
    return True

def _delete_app_object_annots(
    model: PDFModel,
    page_num: int,
    object_id: str,
    expected_kind: str | None = None,
) -> int:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return 0
    page = model.doc[page_num - 1]
    deleted = 0
    try:
        annots = list(page.annots() or [])
    except Exception:
        return 0
    for annot in annots:
        payload = _load_app_object_payload(model, annot)
        if payload is None:
            continue
        if payload.get("object_id") != object_id:
            continue
        if expected_kind is not None and payload.get("kind") != expected_kind:
            continue
        try:
            page.delete_annot(annot)
            deleted += 1
        except Exception:
            continue
    return deleted

def _create_textbox_object_marker(
    model: PDFModel,
    page_num: int,
    visual_rect: fitz.Rect,
    *,
    text: str,
    font: str,
    size: float,
    color: tuple[float, float, float],
    rotation: int,
    object_id: str | None = None,
) -> str:
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        raise ValueError(f"無效頁碼: {page_num}")
    page = model.doc[page_num - 1]
    marker = page.add_rect_annot(fitz.Rect(visual_rect))
    payload: dict[str, Any] = {
        "version": _APP_OBJECT_VERSION,
        "kind": "textbox",
        "object_id": object_id or str(uuid.uuid4()),
        "page_num": int(page_num),
        "rect": [float(visual_rect.x0), float(visual_rect.y0), float(visual_rect.x1), float(visual_rect.y1)],
        "text": text,
        "font": font,
        "size": float(size),
        "color": [float(c) for c in color[:3]],
        "rotation": int(rotation) % 360,
    }
    marker.set_border(width=0)
    marker.set_colors(stroke=None, fill=None)
    marker.set_opacity(0.0)
    marker.set_flags(marker.flags | fitz.PDF_ANNOT_IS_HIDDEN)
    marker.set_info(
        content=_dump_app_object_payload(model, payload),
        subject=_TEXTBOX_OBJECT_SUBJECT,
    )
    marker.update()
    return payload["object_id"]

def _create_image_object_marker(
    model: PDFModel,
    page_num: int,
    placement: fitz.Rect,
    *,
    xref: int,
    image_digest: str,
    rotation: int,
    object_id: str | None = None,
) -> str:
    """Hidden marker for an app image drawn at ``placement`` (UNROTATED page space).

    The payload keeps the unrotated placement (``_image_payload_unrotated_rect``) and the
    annotation is created on the image (``add_rect_annot`` takes unrotated page space).
    ``rotation`` is the stored (raw-cm) angle.
    """
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        raise ValueError(f"無效頁碼: {page_num}")
    page = model.doc[page_num - 1]
    placement = fitz.Rect(placement)
    marker = page.add_rect_annot(placement)
    payload: dict[str, Any] = {
        "version": _APP_OBJECT_VERSION,
        "kind": "image",
        "object_id": object_id or str(uuid.uuid4()),
        "page_num": int(page_num),
        "rect": [float(placement.x0), float(placement.y0), float(placement.x1), float(placement.y1)],
        "rotation": int(rotation) % 360,
        "xref": int(xref),
        "image_digest": image_digest,
    }
    marker.set_border(width=0)
    marker.set_colors(stroke=None, fill=None)
    marker.set_opacity(0.0)
    marker.set_flags(marker.flags | fitz.PDF_ANNOT_IS_HIDDEN)
    marker.set_info(
        content=_dump_app_object_payload(model, payload),
        subject=_IMAGE_OBJECT_SUBJECT,
    )
    marker.update()
    return payload["object_id"]

def add_image_object(
    model: PDFModel,
    page_num: int,
    visual_rect: fitz.Rect,
    image_bytes: bytes,
    *,
    rotation: int = 0,
) -> str:
    """Draw ``image_bytes`` into ``visual_rect`` (VISUAL page space) and mark it.

    ``rotation`` turns the picture relative to upright ON SCREEN. ``insert_image`` and
    the image ``cm`` speak UNROTATED page space (F14-MM-1b): the visual rect is mapped
    with ``visual_to_unrotated_rect``, then moved by ``shift_rect_for_pymupdf_writers``
    (PyMuPDF's writer matrix drops the CropBox/MediaBox origin on a /Rotate page,
    F15-G4-IMG), and the picture is turned by the page's /Rotate so it is upright on
    screen. The stored angle (marker, ``ObjectHitInfo.rotation``) is the raw-cm angle,
    the convention a textbox's stored rotation also uses.
    """
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        raise ValueError(f"無效頁碼: {page_num}")
    page = model.doc[page_num - 1]
    rect = visual_to_unrotated_rect(page, fitz.Rect(visual_rect))
    stored_rotation = (int(rotation) + int(page.rotation)) % 360
    slots_before = {
        _invocation_slot(inv) for inv in discover_native_image_invocations(model.doc, page_num)
    }
    xref = int(
        page.insert_image(
            shift_rect_for_pymupdf_writers(page, rect),
            stream=image_bytes,
            rotate=stored_rotation,
            overlay=True,
        )
    )
    image_digest = _image_xref_digest(model, xref)
    if image_digest is None:
        raise RuntimeError("Inserted image stream could not be fingerprinted")
    # F15-4: insert_image keeps the image's aspect ratio, so an image whose aspect differs
    # from ``rect`` (the UI's default insert rect is always 4:3) is letterboxed inside it.
    # The marker must hold the drawn placement or no later verb resolves it. Identify the
    # new placement by the slot it added (not by xref: identical bytes reuse one xref).
    added = [
        inv
        for inv in discover_native_image_invocations(model.doc, page_num)
        if _invocation_slot(inv) not in slots_before and inv.xref == xref
    ]
    if len(added) == 1:
        drawn_rect = fitz.Rect(added[0].bbox)
    else:
        logger.warning(
            "add_image_object: %d new placements of xref %d; marker keeps the requested rect",
            len(added),
            xref,
        )
        drawn_rect = rect
    object_id = _create_image_object_marker(model,
        page_num,
        drawn_rect,
        xref=xref,
        image_digest=image_digest,
        rotation=stored_rotation,
    )
    model.mark_page_content_dirty(page_num - 1, fitz.Rect(rect))
    model.edit_count += 1
    return object_id

def _textbox_markup(
    text: str, font_name: str, font_size: float, color_rgb: tuple[float, float, float]
) -> tuple[str, str]:
    """``(html, css)`` an app textbox is drawn with by ``insert_htmlbox``.

    The one source of the markup: the insert and the text-layer reference of the
    textbox object ops (``_textbox_layer_chars``, F16-1) must lay out the same story.
    """
    # Idempotent: the insert, the marker and this reference all see the same story
    # even for a marker an older build stored with control characters (F16-PASTE-1).
    escaped_text = _html_mod.escape(strip_unrenderable_controls(text)).replace("\n", "<br>")
    html_content = f'<span style="font-family: {font_name};">{escaped_text}</span>'
    css = f"""
                    span {{
                        font-size: {font_size}pt;
                        white-space: pre-wrap;
                        word-break: break-all;
                        overflow-wrap: anywhere;
                        color: rgb({int(color_rgb[0]*255)}, {int(color_rgb[1]*255)}, {int(color_rgb[2]*255)});
                    }}
                """
    return html_content, css


def _insert_textbox_visual_content(
    model: PDFModel,
    page_num: int,
    visual_rect: fitz.Rect,
    text: str,
    *,
    font: str = "cjk",
    size: int | float = 12,
    color: tuple = (0.0, 0.0, 0.0),
    rotation: int | None = None,
) -> dict:
    # F16-PASTE-1: MuPDF stops at an embedded NUL and draws every other control code
    # as a replacement glyph; neither is visible text, so drop them BEFORE drawing and
    # before the marker stores the string (add, move and rotate all enter here).
    text = strip_unrenderable_controls(text)
    if not text.strip():
        logger.warning("新增文字框內容為空，略過")
        raise ValueError("新增文字框內容為空")
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        raise ValueError(f"無效頁碼: {page_num}")

    page_idx = page_num - 1
    font_name = model._resolve_add_text_font(font)
    font_size = max(0.1, float(size))
    if len(color) >= 3:
        color_rgb = (
            max(0.0, min(1.0, float(color[0]))),
            max(0.0, min(1.0, float(color[1]))),
            max(0.0, min(1.0, float(color[2]))),
        )
    else:
        color_rgb = (0.0, 0.0, 0.0)

    last_err: Exception | None = None
    bounded_visual = fitz.Rect(visual_rect)
    insert_rect = fitz.Rect(visual_rect)
    repaired_once = False
    effective_rotation = int(rotation) % 360 if rotation is not None else 0

    for _ in range(2):
        page = model.doc[page_idx]
        page_visual_rect = fitz.Rect(page.rect)
        bounded_visual = clamp_rect_to_page(fitz.Rect(visual_rect), page_visual_rect)

        if bounded_visual.width < 4:
            bounded_visual.x1 = min(page_visual_rect.x1, bounded_visual.x0 + 4)
        if bounded_visual.height < 4:
            bounded_visual.y1 = min(page_visual_rect.y1, bounded_visual.y0 + 4)

        unrot_rect = model._visual_rect_to_unrotated_rect(page, bounded_visual)
        insert_rect = clamp_rect_to_page(unrot_rect, model._unrotated_page_rect(page))
        if rotation is None:
            effective_rotation = int(page.rotation) % 360

        try:
            tiny_canvas = (
                min(float(page.rect.width), float(page.rect.height)) < 12.0
                or min(float(insert_rect.width), float(insert_rect.height)) < 12.0
            )
            if tiny_canvas and not model._needs_cjk_font(text):
                model._insert_tiny_plain_text(page, text, color_rgb, font_size)
            else:
                html_content, css = _textbox_markup(text, font_name, font_size, color_rgb)
                # One scope per attempt, opened on THIS iteration's document:
                # the repair retry below swaps the live handle, so a scope
                # opened before the loop would belong to a closed document.
                # add_textbox / textbox move / textbox rotate all insert here,
                # so the font streams are compacted before the caller's
                # command captures its after-snapshot.
                with font_compaction_scope(page.parent):
                    insert_htmlbox_tracked(
                        page,
                        insert_rect,
                        html_content,
                        css=css,
                        rotate=effective_rotation,
                        scale_low=0,
                    )
            last_err = None
            break
        except Exception as e:
            last_err = e
            if repaired_once:
                break
            repaired_once = model._repair_active_doc_in_memory(garbage=1)
            if not repaired_once:
                break
            if not model.doc or page_idx >= len(model.doc):
                break
            continue

    if last_err is not None:
        raise RuntimeError(f"新增文字框失敗: {model._safe_exc_message(last_err)}") from last_err

    return {
        "page_idx": page_idx,
        "text": text,
        "bounded_visual": fitz.Rect(bounded_visual),
        "insert_rect": fitz.Rect(insert_rect),
        "rotation": effective_rotation,
        "font_name": font_name,
        "font_size": font_size,
        "color_rgb": color_rgb,
    }


def add_textbox(
    model: PDFModel,
    page_num: int,
    visual_rect: fitz.Rect,
    text: str,
    font: str = "cjk",
    size: int = 12,
    color: tuple = (0.0, 0.0, 0.0),
) -> None:
    """
    Add new page text anchored in visual page coordinates.

    visual_rect uses current viewer orientation coordinates. The method maps
    it to unrotated page space and inserts with rotate=page.rotation so text
    appears at the clicked visual location for rotation 0/90/180/270.
    """
    insert_state = _insert_textbox_visual_content(model, 
        page_num,
        visual_rect,
        text,
        font=font,
        size=size,
        color=color,
    )
    page_idx = insert_state["page_idx"]
    _create_textbox_object_marker(model, 
        page_num,
        insert_state["bounded_visual"],
        text=insert_state["text"],
        font=insert_state["font_name"],
        size=insert_state["font_size"],
        color=insert_state["color_rgb"],
        rotation=insert_state["rotation"],
    )
    model.block_manager.rebuild_page(page_idx, model.doc)
    model.mark_page_content_dirty(page_idx, fitz.Rect(insert_state["insert_rect"]))
    model.edit_count += 1
    logger.debug(
        "add_textbox page=%s visual_rect=%s insert_rect=%s rotate=%s font=%s",
        page_num,
        insert_state["bounded_visual"],
        insert_state["insert_rect"],
        insert_state["rotation"],
        insert_state["font_name"],
    )

def get_object_info_at_point(model: PDFModel, page_num: int, point: fitz.Point) -> ObjectHitInfo | None:
    """The topmost object under ``point``; ``point`` and the returned ``bbox`` are VISUAL.

    Native image placements are discovered in UNROTATED page space, so the point is mapped
    into that space for the test and the bbox back out (F14-MM-1b); ``rotation`` is the
    stored (raw-cm) angle.
    """
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return None
    page = model.doc[page_num - 1]
    try:
        annots = list(page.annots() or [])
    except Exception:
        annots = []
    candidates: list[tuple[fitz.Annot, dict]] = []
    for annot in annots:
        payload = _load_app_object_payload(model, annot)
        if payload is None:
            continue
        # Hit-test on the marker's outer rect (the 1 pt inflation is a harmless pick
        # tolerance); report the TRUE rect as bbox below.
        if point in _marker_pick_rect(annot, payload):
            candidates.append((annot, payload))
    if candidates:
        annot, payload = candidates[-1]
        kind = payload["kind"]
        return ObjectHitInfo(
            object_kind=kind,
            object_id=str(payload["object_id"]),
            page_num=page_num,
            bbox=_app_object_true_rect(annot, payload),
            rotation=float(payload.get("rotation", 0)) % 360,
            supports_move=True,
            supports_delete=True,
            supports_rotate=kind in ("textbox", "image"),
        )
    unrotated_point = visual_to_unrotated_point(page, fitz.Point(point))
    native_hits = [
        invocation
        for invocation in discover_native_image_invocations(model.doc, page_num)
        if unrotated_point in fitz.Rect(invocation.bbox)
    ]
    if not native_hits:
        return None
    native_hit = native_hits[-1]
    return ObjectHitInfo(
        object_kind="native_image",
        object_id=f"native_image:{page_num}:{native_hit.occurrence_index}",
        page_num=page_num,
        bbox=unrotated_to_visual_rect(page, fitz.Rect(native_hit.bbox)),
        rotation=float(native_hit.rotation) % 360,
        supports_move=True,
        supports_delete=True,
        # Form-nested images are repositioned in the form's coordinate space,
        # which only supports axis-aligned move/resize — not rotation.
        supports_rotate=not native_hit.is_form_nested,
    )

# F13-VF-2b: how many Form XObjects one textbox op tries as "the box's own drawing".
_TEXTBOX_FORM_TRIALS = 16


def _content_chars(page: fitz.Page) -> Counter[str]:
    """The compared characters (``_compared_chars``) of all page CONTENT text."""
    return _compared_chars(content_text(page, "text"))


def _page_form_placements(page: fitz.Page) -> list[tuple[int, str, fitz.Rect | None]]:
    """``(xref, name, placed)`` of the Form XObjects the page content invokes directly;
    ``placed`` is where the form's /BBox lands in UNROTATED page space (``None`` when
    the page's user space cannot be mapped)."""
    doc = page.parent
    user_to_page = page_user_space_matrix(page)
    try:
        rows = list(page.get_xobjects())
    except Exception:
        return []
    placements: list[tuple[int, str, fitz.Rect | None]] = []
    for xref, name, invoker, bbox in rows:
        if int(invoker) != 0:
            continue
        try:
            if doc.xref_get_key(int(xref), "Subtype")[1] != "/Form":
                continue
        except Exception:
            continue
        placed: fitz.Rect | None = None
        if user_to_page is not None:
            # get_xobjects reports the form's /BBox through its /Matrix, in PDF user space.
            user = fitz.Rect(bbox)
            corners = ((user.x0, user.y0), (user.x1, user.y0), (user.x0, user.y1), (user.x1, user.y1))
            placed = fitz.Rect(
                rect_from_points([fitz.Point(*affine_point(user_to_page, x, y)) for x, y in corners])
            )
        placements.append((int(xref), str(name), placed))
    return placements


def _textbox_form_candidates(page: fitz.Page, box: fitz.Rect) -> list[tuple[int, str]]:
    """``(xref, name)`` of the Form XObjects the page content invokes directly and
    whose placement meets ``box`` (UNROTATED page space), best overlap first.

    ``insert_htmlbox`` draws a textbox as one such form (``q /fzFrmN Do Q``). The
    ranking only orders the trials; ``_empty_textbox_form`` decides.
    """
    ranked: list[tuple[float, int, str]] = []
    for xref, name, placed in _page_form_placements(page):
        score = 0.0
        if placed is not None:
            overlap = fitz.Rect(placed) & box
            if overlap.is_empty:
                continue
            score = abs(overlap) / max(abs(placed), abs(box), 1e-6)
        ranked.append((score, xref, name))
    ranked.sort(key=lambda row: -row[0])
    return [(xref, name) for _, xref, name in ranked[:_TEXTBOX_FORM_TRIALS]]


def _form_matrix_angle(doc: fitz.Document, xref: int) -> float | None:
    """The turn (degrees) of a Form XObject's ``/Matrix``: the ``rotate`` htmlbox drew
    the box with (no matrix: 0). ``None`` when the matrix cannot be read."""
    try:
        kind, value = doc.xref_get_key(int(xref), "Matrix")
    except Exception:
        return None
    if kind == "null":
        return 0.0
    if kind != "array":
        return None
    try:
        numbers = [float(v) for v in value.strip("[] ").split()]
    except ValueError:
        return None
    if len(numbers) != 6 or (abs(numbers[0]) < 1e-9 and abs(numbers[1]) < 1e-9):
        return None
    return math.degrees(math.atan2(numbers[1], numbers[0])) % 360.0


def _swap_form_stream(doc: fitz.Document, xref: int) -> tuple[bytes, bool] | None:
    """Empty Form ``xref``'s stream; returns what ``_restore_form_stream`` needs, or
    ``None`` when the form has nothing to empty."""
    try:
        original = doc.xref_stream(xref)
    except Exception:
        return None
    if not original or not original.strip():
        return None
    # Put a rejected candidate back as it was stored: htmlbox writes the outer form
    # unfiltered, and update_stream would otherwise Flate it.
    try:
        compressed = doc.xref_get_key(xref, "Filter")[0] != "null"
    except Exception:
        compressed = True
    doc.update_stream(xref, b" ")
    return original, compressed


def _restore_form_stream(doc: fitz.Document, xref: int, saved: tuple[bytes, bool]) -> None:
    original, compressed = saved
    doc.update_stream(xref, original, compress=compressed)


def _region_lines(page: fitz.Page, region: fitz.Rect) -> list[str]:
    """The page CONTENT lines centred in ``region`` (UNROTATED), in extraction order."""
    lines: list[str] = []
    for block in content_text(page, "dict").get("blocks", ()):
        for line in block.get("lines", ()):
            if region.contains(_rect_center(fitz.Rect(line["bbox"]))):
                text = "".join(span.get("text", "") for span in line.get("spans", ()))
                if text.strip():
                    lines.append(text.rstrip())
    return lines


def _region_word_chars(page: fitz.Page, region: fitz.Rect) -> Counter[str]:
    drawn: Counter[str] = Counter()
    for word in content_text(page, "words"):
        if region.contains(_rect_center(fitz.Rect(word[:4]))):
            drawn.update(_compared_chars(word[4]))
    return drawn


def _single_form_drawing(
    page: fitz.Page, xref: int, region: fitz.Rect
) -> tuple[str, Counter[str], Counter[tuple[str, int]], int] | None:
    """What Form ``xref`` draws when it is ALL the page content drawn in ``region``:
    ``(text, compared chars, inked glyphs, line count)``, else ``None``.

    The form is emptied for the measurement and put back. It qualifies only when
    emptying it removes characters, adds none, and removes exactly the characters of
    the words centred in ``region`` -- so nothing else (a loose word an edit drew, page
    text under the box, a second box) is drawn there, and the form draws nothing
    outside it.
    """
    doc = page.parent
    lines = _region_lines(page, region)
    in_region = _region_word_chars(page, region)
    page_before = _content_chars(page)
    glyphs_before = _texttrace_glyph_keys(page, region)
    saved = _swap_form_stream(doc, xref)
    if saved is None:
        return None
    try:
        page_after = _content_chars(page)
        glyphs_after = _texttrace_glyph_keys(page, region)
    finally:
        _restore_form_stream(doc, xref, saved)
    removed = page_before - page_after
    if not removed or (page_after - page_before) or removed != in_region or not lines:
        return None
    # get_texttrace also reads annotation appearances: they cancel out in the difference.
    return "\n".join(lines), removed, glyphs_before - glyphs_after, len(lines)


def _textbox_boxes_claimed_by_other_markers(
    model: PDFModel, page: fitz.Page, object_id: object
) -> list[fitz.Rect]:
    """The boxes (UNROTATED) of the other textbox markers on the page whose stored text
    the page draws: their drawings belong to them."""
    boxes: list[fitz.Rect] = []
    try:
        annots = list(page.annots() or [])
    except Exception:
        return boxes
    for annot in annots:
        other = _load_app_object_payload(model, annot)
        if other is None or other.get("kind") != "textbox" or other.get("object_id") == object_id:
            continue
        rect = _payload_rect(other)
        if rect is not None and _textbox_payload_drawn_on_page(model, page, other):
            boxes.append(model._visual_rect_to_unrotated_rect(page, rect))
    return boxes


def _repair_textbox_marker(model: PDFModel, page: fitz.Page, annot: fitz.Annot, payload: dict) -> bool:
    """Re-resolve a textbox marker the page no longer matches (D-OLD-MARKERS, F15-2
    follow-up a); ``True`` when ``payload`` and the marker were rewritten.

    A file saved by a build without the marker sync (or an older geometry) carries a
    marker whose text or rect the page no longer draws. The marker is re-resolved only
    when exactly ONE htmlbox drawing is the clear candidate: a Form XObject the page
    invokes directly, drawn by nothing else, whose placement shares the marker's centre
    (``_SAME_CENTRE_TOLERANCE``) and whose ``/Matrix`` angle is the marker's rotation,
    and which is ALL the content drawn in its box (``_single_form_drawing``). The
    marker then takes that drawing's text (its lines joined with ``\\n``) and box. The
    text is accepted only when htmlbox, given it with the marker's font, size and
    rotation, writes the same characters, the same inked glyphs and the same number of
    lines (``_textbox_layer``): a lossy text layer (emoji, shaped scripts, Ext-B; F16-1)
    is never written back as the box's text. A marker flagged ``content_unsynced`` is
    this build's own record that an edit could not be placed, and is not repaired.
    """
    if payload.get(_TEXTBOX_UNSYNCED_KEY):
        return False
    rect = _payload_rect(payload)
    if rect is None:
        return False
    doc = page.parent
    box = model._visual_rect_to_unrotated_rect(page, rect)
    rotation = int(payload.get("rotation", 0)) % 360
    claimed = _textbox_boxes_claimed_by_other_markers(model, page, payload.get("object_id"))
    clear: list[tuple[fitz.Rect, tuple[str, Counter[str], Counter[tuple[str, int]], int]]] = []
    for xref, _name, placed in _page_form_placements(page):
        if placed is None or not _same_centre(placed, box):
            continue
        if any(_same_centre(placed, other) for other in claimed):
            # Another textbox marker that resolves draws here: never take its drawing.
            continue
        angle = _form_matrix_angle(doc, xref)
        if angle is None or _angle_delta(angle, rotation) > 1.0:
            continue
        if _form_drawn_by_another_page_or_form(doc, page, xref):
            continue
        drawing = _single_form_drawing(page, xref, fitz.Rect(placed) + (-1, -1, 1, 1))
        if drawing is not None:
            clear.append((fitz.Rect(placed), drawing))
    if len(clear) != 1:
        return False
    placed, (text, chars, glyphs, line_count) = clear[0]
    if all(abs(a - b) <= 1.0 for a, b in zip(placed, box)):
        visual = fitz.Rect(rect)
    else:
        visual = unrotated_to_visual_rect(page, placed)
    accepted: dict | None = None
    # The stored text first: when it is what the drawing shows (only the rect is stale)
    # it keeps its own line breaks; else the drawing's lines.
    for candidate_text in dict.fromkeys((str(payload.get("text") or ""), text)):
        candidate = dict(payload)
        candidate["text"] = candidate_text
        candidate["rect"] = [float(visual.x0), float(visual.y0), float(visual.x1), float(visual.y1)]
        layer = _textbox_layer(model, page, candidate)
        if (
            layer is not None
            and layer.chars == chars
            and layer.glyphs == glyphs
            and layer.line_count == line_count
            and _textbox_payload_drawn_on_page(model, page, candidate)
        ):
            accepted = candidate
            break
    if accepted is None:
        return False
    candidate = accepted
    if candidate["rect"] != payload.get("rect"):
        annot.set_rect(visual)
    payload.clear()
    payload.update(candidate)
    _rewrite_textbox_payload(model, annot, payload)
    logger.info("textbox object %s: old marker re-resolved to its drawing", payload.get("object_id"))
    return True


def _resolve_textbox_marker(model: PDFModel, page: fitz.Page, annot: fitz.Annot, payload: dict) -> bool:
    """True when the page draws the marker's stored text in its box, after repairing a
    marker with one clear drawing (``_repair_textbox_marker``)."""
    if _textbox_payload_drawn_on_page(model, page, payload):
        return True
    return _repair_textbox_marker(model, page, annot, payload)


def _form_drawn_by_another_page_or_form(doc: fitz.Document, page: fitz.Page, xref: int) -> bool:
    """True when anything but ``page``'s own content invokes Form ``xref``.

    Emptying the form must change this page only: a form nested in another form, or
    invoked by another page (shared resources, a shallow page copy), is not the
    textbox's private drawing.
    """
    for pno in range(len(doc)):
        try:
            rows = doc.get_page_xobjects(pno)
        except Exception:
            return True
        for row_xref, name, invoker, _bbox in rows:
            if int(row_xref) != xref:
                continue
            if int(invoker) != 0:
                return True
            if pno == page.number:
                continue
            if any(
                _stream_references_xobject(doc.xref_stream(int(c)), str(name))
                for c in doc[pno].get_contents()
                if int(c) > 0
            ):
                return True
    return False


def _empty_textbox_form(model: PDFModel, page: fitz.Page, payload: dict) -> bool:
    """Remove an app textbox's drawing by emptying its own htmlbox Form XObject.

    F13-VF-2b: the rect redaction this replaces is geometric and erased every glyph
    under the box. A candidate form (``_textbox_form_candidates``) is the box's drawing
    only when emptying it takes exactly the stored text's characters off the page
    content and adds none, and nothing else draws it; otherwise its stream is put back
    and the next candidate is tried. "The stored text's characters" is the raw string
    or, where htmlbox's text layer is lossy (emoji, shaped scripts), that layer
    (``_textbox_layer_chars``, F16-1). On success the form also loses its ``/Resources``,
    so the fonts it embedded become unreachable (the save-time garbage pass frees
    them). The page content keeps its ``/Name Do``, which now draws nothing, so no
    content stream is re-tokenized. ``False`` (page unchanged) when no form qualifies:
    a box a text edit drew partly as loose glyphs, a tiny-canvas insert, a box another
    tool rewrote.
    """
    doc: fitz.Document = model.doc
    expected = _compared_chars(str(payload.get("text") or ""))
    rect = _payload_rect(payload)
    if not expected or rect is None:
        return False
    box = model._visual_rect_to_unrotated_rect(page, rect) + (-1, -1, 1, 1)
    candidates = _textbox_form_candidates(page, box)
    if not candidates:
        return False
    before = _content_chars(page)
    layer: list[Counter[str] | None] = []

    def owned(removed: Counter[str]) -> bool:
        if removed == expected:
            return True
        if not layer:
            layer.append(_textbox_layer_chars(model, page, payload))
        return bool(layer[0]) and removed == layer[0]

    for xref, _name in candidates:
        saved = _swap_form_stream(doc, xref)
        if saved is None:
            continue
        after = _content_chars(page)
        if not (after - before) and owned(before - after):
            if _form_drawn_by_another_page_or_form(doc, page, xref):
                _restore_form_stream(doc, xref, saved)
                continue
            try:
                doc.xref_set_key(xref, "Resources", "<<>>")
            except Exception:
                logger.debug("textbox form %s: could not drop its resources", xref)
            return True
        _restore_form_stream(doc, xref, saved)
    return False


def _chars_in_rect(page: fitz.Page, rect: fitz.Rect) -> Counter[str]:
    """The compared characters of the page CONTENT a redaction of ``rect`` (UNROTATED)
    would erase: every glyph box touching it."""
    held: Counter[str] = Counter()
    raw = content_text(page, "rawdict")
    for block in raw.get("blocks", ()):
        for line in block.get("lines", ()):
            for span in line.get("spans", ()):
                for ch in span.get("chars", ()):
                    if fitz.Rect(ch["bbox"]).intersects(rect):
                        held.update(_compared_chars(ch.get("c", "")))
    return held


def _foreign_chars_in_rect(
    model: PDFModel, page: fitz.Page, rect: fitz.Rect, payload: dict
) -> Counter[str]:
    """Characters a redaction of ``rect`` (UNROTATED) would erase that the textbox does
    not own: beyond its stored text and, only when that leaves any, beyond what htmlbox's
    lossy text layer writes for it too (``_textbox_layer_chars``, F16-1)."""
    held = _chars_in_rect(page, rect)
    own = _compared_chars(str(payload.get("text") or ""))
    foreign = held - own
    if foreign:
        layer = _textbox_layer_chars(model, page, payload)
        if layer:
            foreign = held - (own | layer)
    return foreign


def _redact_and_restore_textbox_region(
    model: PDFModel, page: fitz.Page, payload: dict, object_id: str
) -> bool:
    """Fallback erase of an app textbox at its VISUAL ``payload["rect"]``.

    Only for a box whose drawing is not one Form XObject (``_empty_textbox_form``).
    The redaction is geometric, so it refuses (``False``, page unchanged) when the rect
    holds page text that is not the box's own (``_foreign_chars_in_rect``; F13-VF-2b; F15-2 follow-up
    b: a box grown over a longer edit can cover page text between the old rect and the
    new words). ``add_redact_annot`` and the annotation/link snapshot both work in
    UNROTATED page space (F14-MM-1): on a /Rotate 90/180/270 page the visual rect, used
    as is, misses the textbox's own htmlbox glyphs (a second copy stays drawn) and
    erases whatever sits at those numbers in unrotated space. Map it once, with the
    same helper the insert uses (``_insert_textbox_visual_content``), so redaction and
    insert agree.
    """
    redact_rect = model._visual_rect_to_unrotated_rect(page, fitz.Rect(payload["rect"]))
    foreign = _foreign_chars_in_rect(model, page, redact_rect, payload)
    if foreign:
        logger.warning(
            "textbox %s: its drawing is not one XObject and the box holds other page text "
            "(%r); refusing rather than redact it",
            object_id,
            "".join(sorted(foreign.elements()))[:40],
        )
        return _refuse(model, ObjectOpRefusal.TEXTBOX_OVER_PAGE_TEXT)
    saved_annots = model.tools.annotation._save_overlapping_annots(page, redact_rect)
    filtered_annots: list[dict] = []
    for saved in saved_annots:
        info = dict(saved.get("info") or {})
        subject = info.get("subject") or ""
        if subject == _TEXTBOX_OBJECT_SUBJECT:
            try:
                saved_payload = json.loads(info.get("content") or "{}")
            except Exception:
                saved_payload = {}
            if saved_payload.get("object_id") == object_id:
                continue
        filtered_annots.append(saved)
    page.add_redact_annot(redact_rect)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    if filtered_annots:
        model.tools.annotation._restore_annots(page, filtered_annots)
    return True


def _erase_textbox_drawing(model: PDFModel, page: fitz.Page, payload: dict, object_id: str) -> bool:
    """Remove what an app textbox draws and nothing else; ``False`` leaves the page as is.

    Its own htmlbox Form XObject when that is the whole drawing, else the guarded rect
    redaction (F13-VF-2b).
    """
    if _empty_textbox_form(model, page, payload):
        return True
    return _redact_and_restore_textbox_region(model, page, payload, object_id)


# F15-2: payload flag set when a text edit touched a textbox but its new words could
# not be placed in the stored text (ambiguous or not found). Sticky: move/rotate refuse.
_TEXTBOX_UNSYNCED_KEY = "content_unsynced"
# Unicode categories the drawn-text check compares; marks, controls, format chars
# (ZWJ, soft hyphen) and separators may not survive htmlbox shaping + extraction.
_COMPARED_CATEGORIES = ("L", "N", "P", "S")


def _occurrences_ignoring_whitespace(text: str, old: str) -> int:
    """How often ``old`` occurs in ``text`` (overlaps counted), whitespace ignored; 0 for an empty ``old``."""
    haystack = "".join((text or "").split())
    needle = "".join((old or "").split())
    if not needle:
        return 0
    count, start = 0, haystack.find(needle)
    while start >= 0:
        count += 1
        start = haystack.find(needle, start + 1)
    return count


def _replace_ignoring_whitespace(text: str, old: str, new: str) -> str | None:
    """Replace the one occurrence of ``old`` in ``text``, comparing without whitespace.

    The index joins a textbox's lines and runs differently from the stored text (wraps,
    ``\\n``), so the match ignores whitespace; the whitespace around the match is kept.
    ``None`` when ``old`` is empty, absent, or occurs more than once.
    """
    positions = [i for i, ch in enumerate(text) if not ch.isspace()]
    haystack = "".join(text[i] for i in positions)
    needle = "".join((old or "").split())
    if not needle:
        return None
    first = haystack.find(needle)
    if first < 0 or haystack.find(needle, first + 1) >= 0:
        return None
    return _splice_replacement(text, positions[first], positions[first + len(needle) - 1] + 1, new)


def _splice_replacement(text: str, start: int, end: int, new: str) -> str:
    """``text`` with ``[start, end)`` replaced by ``new``; stripped when ``new`` is empty."""
    replaced = text[:start] + new + text[end:]
    return replaced.strip() if not new else replaced


def _lossy_raw_boundary(
    opcodes: Sequence[tuple[str, int, int, int, int]], ref_pos: int, ref_len: int, raw_len: int
) -> int | None:
    """The one position in the raw (whitespace-free) text that ``ref_pos`` of its text
    layer corresponds to, or ``None`` when the alignment leaves it open (inside a lossy
    stretch, or next to characters the text layer dropped)."""
    if ref_pos == 0:
        return 0
    if ref_pos == ref_len:
        return raw_len
    found: set[int] = set()
    for tag, i1, i2, j1, j2 in opcodes:
        if not j1 <= ref_pos <= j2:
            continue
        if tag == "equal":
            found.add(i1 + ref_pos - j1)
            continue
        if ref_pos == j1:
            found.add(i1)
        if ref_pos == j2:
            found.add(i2)
    return next(iter(found)) if len(found) == 1 else None


def _lossy_span_ignoring_whitespace(text: str, old: str, reference: str) -> tuple[int, int] | None:
    """Indices ``(start, end)`` in ``text`` of the characters whose htmlbox text layer is ``old``.

    ``reference`` is the text layer htmlbox writes for ``text`` (``_textbox_layer``); the
    index text of an edited run is read from it (U+1F600 reads back as U+1F60), so it
    never occurs in the raw stored text (F16-1-LOSSY). ``old`` must occur exactly once in
    ``reference`` (whitespace ignored); the raw text is aligned with ``reference`` and
    both ends of that occurrence must map to one raw position each. ``None`` when ``old``
    is absent or ambiguous, or the alignment cannot place an end: the caller flags the
    marker rather than guess.
    """
    positions = [i for i, ch in enumerate(text) if not ch.isspace()]
    raw = "".join(text[i] for i in positions)
    ref = "".join((reference or "").split())
    needle = "".join((old or "").split())
    if not raw or not needle:
        return None
    first = ref.find(needle)
    if first < 0 or ref.find(needle, first + 1) >= 0:
        return None
    opcodes = difflib.SequenceMatcher(None, raw, ref, autojunk=False).get_opcodes()
    start = _lossy_raw_boundary(opcodes, first, len(ref), len(raw))
    end = _lossy_raw_boundary(opcodes, first + len(needle), len(ref), len(raw))
    if start is None or end is None or start >= end:
        return None
    return positions[start], positions[end - 1] + 1


def _rewrite_textbox_payload(model: PDFModel, annot: fitz.Annot, payload: dict) -> None:
    annot.set_info(content=_dump_app_object_payload(model, payload), subject=_TEXTBOX_OBJECT_SUBJECT)
    annot.update()


def sync_textbox_markers_after_text_edit(
    model: PDFModel,
    page_num: int,
    *,
    member_rects: list[fitz.Rect],
    source_text: str,
    new_text: str,
    destination_rect: fitz.Rect | None = None,
    style: tuple[str, float, tuple] | None = None,
    words_before: list | None = None,
) -> None:
    """Keep app textbox markers in step with a committed text edit (F15-2).

    The marker payload is what Move / Rotate Object re-insert, so a stale ``text``
    silently reverts the user's edit. Called once per successful ``edit_text`` with the
    edit's member runs (``member_rects``, UNROTATED page space like the text index) and
    the text they held (``source_text``). For every textbox whose rect holds a member
    run, ``source_text`` is replaced by ``new_text`` in the stored text (a box whose
    stored text does not contain it at all, e.g. page text under the box was edited,
    is left alone). A drag that
    lands outside the box (``destination_rect``, unrotated) takes the text out of it. A
    box left empty loses its marker (the object is gone, as after Delete). ``style``
    (font token, size, colour) is the legacy rebuild's insert style; it is stored only
    when the edit replaced the whole box text (one payload holds one style). When the
    words cannot be placed unambiguously the marker is flagged unsynced and Move /
    Rotate refuse it rather than guess. ``words_before`` (``textbox_page_words`` taken
    before the commit) lets the box grow over the new words the edit drew outside it,
    so a longer text stays inside the object Move / Rotate erase and re-insert.
    """
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return
    centres = [_rect_center(fitz.Rect(r)) for r in member_rects if r is not None]
    if not centres:
        return
    page = model.doc[page_num - 1]
    try:
        annots = list(page.annots() or [])
    except Exception:
        return
    for annot in annots:
        payload = _load_app_object_payload(model, annot)
        if payload is None or payload.get("kind") != "textbox":
            continue
        box = model._visual_rect_to_unrotated_rect(page, _app_object_true_rect(annot, payload)) + (-1, -1, 1, 1)
        if not any(box.contains(c) for c in centres):
            continue
        stored = str(payload.get("text") or "")
        moved_out = destination_rect is not None and not box.contains(
            _rect_center(fitz.Rect(destination_rect))
        )
        replacement = "" if moved_out else (new_text or "")
        occurrences = _occurrences_ignoring_whitespace(stored, source_text)
        lossy_span: tuple[int, int] | None = None
        if occurrences == 0:
            # The index text of a run holding emoji / a shaped cluster is htmlbox's LOSSY
            # text layer, not the raw string (F16-1-LOSSY): look for it there.
            reference = "" if stored.isascii() else _textbox_reference_text(model, page, payload, stored)
            reference_hits = _occurrences_ignoring_whitespace(reference, source_text)
            if reference_hits == 0:
                # The edited run is not this box's text (page text under the box): the
                # box's words did not change. If that is ever wrong, the move/rotate
                # guard still sees the stored words missing from the page and refuses.
                continue
            lossy_span = _lossy_span_ignoring_whitespace(stored, source_text, reference)
            synced = (
                None
                if lossy_span is None
                else _splice_replacement(stored, lossy_span[0], lossy_span[1], replacement)
            )
        else:
            synced = _replace_ignoring_whitespace(stored, source_text, replacement)
        if synced is None:
            logger.warning(
                "textbox marker %s: edited text occurs more than once in the stored text; "
                "move/rotate will refuse it",
                payload.get("object_id"),
            )
            payload[_TEXTBOX_UNSYNCED_KEY] = True
            _rewrite_textbox_payload(model, annot, payload)
            continue
        if not synced.strip():
            page.delete_annot(annot)
            continue
        if lossy_span is None:
            whole_box = "".join(stored.split()) == "".join((source_text or "").split())
        else:
            whole_box = not stored[: lossy_span[0]].strip() and not stored[lossy_span[1] :].strip()
        payload["text"] = synced
        if style is not None and whole_box and not moved_out:
            font, size, color = style
            payload["font"] = font
            payload["size"] = float(size)
            payload["color"] = [float(c) for c in tuple(color)[:3]]
        if words_before is not None and not moved_out:
            # The words the edit drew read back through htmlbox's text layer: an emoji
            # in the new text is "U+1F60" on the page (F16-1-LOSSY).
            drawn_text = new_text or ""
            if not drawn_text.isascii():
                drawn_text = _textbox_reference_text(model, page, payload, drawn_text) or drawn_text
            grown = _grow_box_over_new_words(page, box, words_before, drawn_text)
            if grown is not None:
                visual = fitz.Rect(_app_object_true_rect(annot, payload)) | unrotated_to_visual_rect(page, grown)
                payload["rect"] = [float(visual.x0), float(visual.y0), float(visual.x1), float(visual.y1)]
                annot.set_rect(visual)
        _rewrite_textbox_payload(model, annot, payload)


def _word_key(word: tuple) -> tuple:
    return (word[4], *(round(float(v), 1) for v in word[:4]))


def textbox_page_words(model: PDFModel, page_num: int) -> list | None:
    """The page's words, or ``None`` when the page holds no app textbox (nothing to sync).

    Taken before a text edit commits, so the sync can tell which words the edit drew.
    """
    if not model.doc or page_num < 1 or page_num > len(model.doc):
        return None
    page = model.doc[page_num - 1]
    try:
        annots = list(page.annots() or [])
    except Exception:
        return None
    if not any((annot.info or {}).get("subject") == _TEXTBOX_OBJECT_SUBJECT for annot in annots):
        return None
    return list(content_text(page, "words"))


def _grow_box_over_new_words(
    page: fitz.Page, box: fitz.Rect, words_before: list, new_text: str
) -> fitz.Rect | None:
    """Unrotated union of the words the edit drew (even partly) outside ``box``.

    A drawn word is one that is on the page now but was not before the commit (same
    text and position) and is a word of ``new_text``, at most as often as ``new_text``
    has it; words a push-down or replay merely redrew in place do not count, and
    unrelated page text never joins the object. ``None`` when nothing lies outside.
    """
    remaining = Counter(new_text.split())
    before = Counter(_word_key(word) for word in words_before)
    grown: fitz.Rect | None = None
    for word in content_text(page, "words"):
        key = _word_key(word)
        if before[key] > 0:
            before[key] -= 1
            continue
        if remaining[word[4]] <= 0:
            continue
        remaining[word[4]] -= 1
        rect = fitz.Rect(word[:4])
        if box.contains(rect):
            # Wholly inside; a word that only straddles the edge still grows the box
            # (its centre inside left its tail outside the object Move / Rotate erase).
            continue
        grown = rect if grown is None else grown | rect
    return grown


def _compared_chars(text: str) -> Counter[str]:
    normalized = unicodedata.normalize("NFKC", text or "")
    return Counter(ch for ch in normalized if unicodedata.category(ch)[0] in _COMPARED_CATEGORIES)


def _texttrace_glyph_keys(page: fitz.Page, rect: fitz.Rect | None = None) -> Counter[tuple[str, int]]:
    """``(font name, glyph id)`` of the inked glyphs ``page`` draws (centre in ``rect``,
    UNROTATED, when given): what is DRAWN, read from ``get_texttrace``, not from the
    text layer. Whitespace codes are skipped except in an Ext-B subset font, whose
    codes are htmlbox's 16-bit cut (U+20000 -> U+2000, a space) -- as the edit path's
    ``_texttrace_glyphs``."""
    glyphs: Counter[tuple[str, int]] = Counter()
    for span in page.get_texttrace():
        font = str(span.get("font", ""))
        ext_b_font = font.startswith(EXT_B_FONT_NAME_PREFIX)
        for ch in span.get("chars", ()):
            code, gid = int(ch[0]), int(ch[1])
            if gid == 0:
                continue
            if not ext_b_font and 0 <= code < 0x110000 and chr(code).isspace():
                continue
            if rect is not None and not rect.contains(_rect_center(fitz.Rect(ch[3]))):
                continue
            glyphs[(font, gid)] += 1
    return glyphs


@functools.lru_cache(maxsize=32)
def _htmlbox_layer(
    html: str, css: str, width: float, height: float, rotate: int
) -> tuple[str, tuple[tuple[tuple[str, int], int], ...]]:
    """The text layer ``insert_htmlbox`` writes for ``html`` / ``css`` laid out in a
    ``width`` x ``height`` box turned by ``rotate``, and the glyphs it draws (as sorted
    ``((font, glyph id), count)`` pairs), read back from a throwaway page."""
    doc = fitz.open()
    try:
        page = doc.new_page(width=width, height=height)
        insert_htmlbox_tracked(page, page.rect, html, css=css, rotate=rotate, scale_low=0, scratch=True)
        return content_text(page, "text"), tuple(sorted(_texttrace_glyph_keys(page).items()))
    finally:
        doc.close()


class _TextboxLayer(NamedTuple):
    """What htmlbox writes for a textbox's stored text (``_textbox_layer``)."""

    chars: Counter[str]  # compared characters (``_compared_chars``) of its text layer
    glyphs: Counter[tuple[str, int]]  # inked glyphs, (font name, glyph id)
    line_count: int  # non-blank lines of its text layer
    text: str = ""  # the text layer itself (F16-1-LOSSY: what a text edit's index text reads)


def _textbox_layer(model: PDFModel, page: fitz.Page, payload: dict) -> _TextboxLayer | None:
    """The text layer and glyphs htmlbox writes for the box's stored text, or ``None``
    when that cannot be measured (F16-1).

    PyMuPDF 1.27's htmlbox draws emoji, other non-BMP characters and shaped clusters
    (Indic conjuncts, Arabic lam-lam) correctly but writes a wrong ToUnicode for them:
    U+1F600 reads back as U+1F60, a conjunct as its glyph id, CJK Ext-B as a space.
    That loss is accepted (OD-UNI1-COMMIT), so the object ops must compare the page
    with what htmlbox's own text layer carries for ``payload["text"]`` -- the edit
    path's ``reference.text`` -- not with the raw string. The story is the live
    insert's (``_textbox_markup``, same font resolution, box size and rotate), laid
    out on a scratch page, so a wrap that splits a shaped cluster reads back the same
    way.
    """
    text = str(payload.get("text") or "")
    rect = _payload_rect(payload)
    if not text.strip() or rect is None:
        return None
    try:
        box = clamp_rect_to_page(
            model._visual_rect_to_unrotated_rect(page, rect), model._unrotated_page_rect(page)
        )
        if min(float(box.width), float(box.height)) < 1.0:
            return None
        raw_color = [float(c) for c in (payload.get("color") or (0.0, 0.0, 0.0))][:3]
        color = tuple(max(0.0, min(1.0, c)) for c in (raw_color + [0.0, 0.0, 0.0])[:3])
        html, css = _textbox_markup(
            text,
            model._resolve_add_text_font(str(payload.get("font") or "")),
            max(0.1, float(payload.get("size") or 12)),
            (color[0], color[1], color[2]),
        )
        layer_text, glyph_items = _htmlbox_layer(
            html, css, float(box.width), float(box.height), int(payload.get("rotation", 0)) % 360
        )
    except Exception as exc:
        logger.debug("textbox %s: text-layer reference failed: %s", payload.get("object_id"), exc)
        return None
    line_count = sum(1 for line in layer_text.splitlines() if line.strip())
    return _TextboxLayer(_compared_chars(layer_text), Counter(dict(glyph_items)), line_count, layer_text)


def _textbox_reference_text(model: PDFModel, page: fitz.Page, payload: dict, text: str) -> str:
    """The text layer htmlbox writes for ``text`` set the way ``payload``'s box sets its
    own (font, size, rotation, box size), or ``""`` when that cannot be measured."""
    layer = _textbox_layer(model, page, {**payload, "text": text})
    return "" if layer is None else layer.text


def _textbox_layer_chars(model: PDFModel, page: fitz.Page, payload: dict) -> Counter[str] | None:
    """The compared characters of the text layer htmlbox writes for the box's stored
    text (``_textbox_layer``), or ``None`` when that cannot be measured (F16-1)."""
    layer = _textbox_layer(model, page, payload)
    return None if layer is None else layer.chars


def _textbox_payload_drawn_on_page(model: PDFModel, page: fitz.Page, payload: dict) -> bool:
    """True when the page still draws the marker's stored text inside its rect (F15-2).

    Move / Rotate erase the box and re-insert ``payload["text"]``; if the page no
    longer draws that text (a text edit by a build without the marker sync, another
    tool, a push-down that moved the glyphs) the re-insert would revert or duplicate
    content. Every stored character must be among the characters of the words centred
    in the box (extra page text under the box is fine) -- or, for text whose htmlbox
    text layer is lossy (emoji, shaped scripts; F16-1), every character of that layer
    (``_textbox_layer``), or, when that layer holds none of them (CJK Ext-B only), every
    glyph htmlbox draws for it. The tiny-canvas insert draws outside the rect, so tiny
    boxes are not checked.
    """
    if payload.get(_TEXTBOX_UNSYNCED_KEY):
        return False
    expected = _compared_chars(str(payload.get("text") or ""))
    if not expected:
        return True
    visual = fitz.Rect(payload["rect"])
    if min(float(page.rect.width), float(page.rect.height)) < 12.0 or min(visual.width, visual.height) < 12.0:
        return True
    box = model._visual_rect_to_unrotated_rect(page, visual) + (-1, -1, 1, 1)
    drawn: Counter[str] = Counter()
    for word in content_text(page, "words"):
        if box.contains(_rect_center(fitz.Rect(word[:4]))):
            drawn.update(_compared_chars(word[4]))
    missing = expected - drawn
    if missing:
        # F16-1: characters htmlbox draws but cannot encode (emoji, shaped clusters) are
        # missing from every text layer; the box is drawn when the page carries all
        # that htmlbox's own text layer writes for the stored text.
        layer = _textbox_layer(model, page, payload)
        if layer is not None:
            if layer.chars and not (layer.chars - drawn):
                return True
            # Nothing of the text survives in ANY htmlbox text layer (e.g. CJK Ext-B
            # only: its codes are spaces): the glyphs are the evidence.
            if not layer.chars and layer.glyphs and not (layer.glyphs - _texttrace_glyph_keys(page, box)):
                return True
        logger.warning(
            "textbox %s: the page no longer draws its stored text (missing %r); refusing move/rotate",
            payload.get("object_id"),
            "".join(sorted(missing.elements()))[:40],
        )
        return False
    return True


def _register_mutation(model: PDFModel, page_idx: int, rect: fitz.Rect) -> None:
    """Track a rewrite without performing a live full-document GC."""
    model.mark_page_content_dirty(page_idx, fitz.Rect(rect))
    model.edit_count += 1


def move_object(model: PDFModel, request: MoveObjectRequest) -> bool:
    """Move (or resize) one object; ``False`` changes nothing and records why on
    ``model.last_object_op_refusal`` (D-OLD-MARKERS)."""
    model.last_object_op_refusal = None
    return _record_outcome(model, _move_object_impl(model, request), request.object_kind, request.object_id)


def _move_object_impl(model: PDFModel, request: MoveObjectRequest) -> bool:
    if request.destination_page != request.source_page:
        return _refuse(model, ObjectOpRefusal.NOT_SUPPORTED)
    if request.object_kind == "native_image":
        invocation = _find_native_image_invocation(model, request.source_page, request.object_id)
        if invocation is None:
            return _refuse(model, ObjectOpRefusal.OBJECT_NOT_FOUND)
        # The destination is visual; the cm writers take unrotated space (F14-MM-1b).
        # typed bind; _find_native_image_invocation returned non-None, so the doc is open
        doc: fitz.Document = model.doc
        return _rewrite_native_image_matrix(model,
            invocation,
            visual_to_unrotated_rect(
                doc[request.source_page - 1], fitz.Rect(request.destination_rect)
            ),
            invocation.rotation,
        )
    found = _find_app_object_annot(model, request.source_page, request.object_id, request.object_kind)
    if found is None:
        return _refuse(model, ObjectOpRefusal.OBJECT_NOT_FOUND)
    page, annot, payload = found
    if payload["kind"] == "rect":
        # destination_rect is visual; the annotation's /Rect is unrotated (F15-3). The
        # same mapping add_rect uses, so create and move place the drawing alike.
        set_annot_page_rect(page, annot, visual_to_unrotated_rect(page, fitz.Rect(request.destination_rect)))
        payload["rect"] = [
            float(request.destination_rect.x0),
            float(request.destination_rect.y0),
            float(request.destination_rect.x1),
            float(request.destination_rect.y1),
        ]
        annot.set_info(content=_dump_app_object_payload(model, payload), subject=_RECT_OBJECT_SUBJECT)
        annot.update()
        return True
    if payload["kind"] == "image":
        # Resolution and the cm rewrite are UNROTATED page space; the destination is
        # visual (F14-MM-1b).
        # A marker without a recorded xref resolves by digest + geometry (and is
        # repaired when old; D-OLD-MARKERS), so it is not refused up front.
        old_rect = _image_payload_unrotated_rect(annot, payload)
        dest_rect = visual_to_unrotated_rect(page, fitz.Rect(request.destination_rect))
        rotation = float(payload.get("rotation", 0)) % 360
        invocation = _resolve_marker_image_invocation(
            model, request.source_page, payload, old_rect, annot=annot
        )
        if invocation is None:
            return _refuse(model, ObjectOpRefusal.IMAGE_NOT_LOCATED)
        if not _rewrite_native_image_matrix(model, invocation, dest_rect, rotation):
            return False
        _sync_image_marker_to_drawn(model, request.source_page, annot, payload, invocation, rotation)
        return True
    if payload["kind"] != "textbox":
        return _refuse(model, ObjectOpRefusal.NOT_SUPPORTED)
    if not _resolve_textbox_marker(model, page, annot, payload):
        return _refuse(model, ObjectOpRefusal.TEXTBOX_TEXT_CHANGED)
    old_rect = fitz.Rect(payload["rect"])
    if not _erase_textbox_drawing(model, page, payload, request.object_id):
        return False
    _delete_app_object_annots(model, request.source_page, request.object_id, expected_kind="textbox")
    insert_state = _insert_textbox_visual_content(model, 
        request.destination_page,
        fitz.Rect(request.destination_rect),
        payload["text"],
        font=payload["font"],
        size=payload["size"],
        color=tuple(payload["color"]),
        rotation=int(payload.get("rotation", 0)),
    )
    _create_textbox_object_marker(model, 
        request.destination_page,
        insert_state["bounded_visual"],
        text=insert_state["text"],
        font=payload["font"],
        size=payload["size"],
        color=tuple(payload["color"]),
        rotation=int(payload.get("rotation", 0)),
        object_id=request.object_id,
    )
    model.block_manager.rebuild_page(request.destination_page - 1, model.doc)
    # R6-01: redact+reinsert orphaned the prior content stream; register the mutation so
    # the batched garbage=4 round-trip reclaims it (bounds file growth over repeats).
    _register_mutation(model, request.destination_page - 1, old_rect | fitz.Rect(request.destination_rect))
    return True

def _rotate_native_image_absolute(
    model: PDFModel,
    invocation: NativeImageInvocation,
    angle: float,
) -> bool:
    """Rotate a (non-form) native image to an absolute angle about its centre."""
    if invocation.is_form_nested or invocation.cm_operator_index is None:
        return False
    # typed bind; callers guarantee an open doc here (native image rotate path) - runtime behavior identical if None
    doc: fitz.Document = model.doc
    stream = doc.xref_stream(invocation.stream_xref)
    tokens, operators = parse_operators(stream)
    if invocation.cm_operator_index >= len(operators):
        return False
    cm_operator = operators[invocation.cm_operator_index]
    if cm_operator.name != "cm":
        return False
    current_cm = _cm_values_from_operands(cm_operator.operands)
    if current_cm is None:
        return False
    # Rotation about the image's own centre needs no page geometry: the
    # decomposed centre and sizes are already user space (F15-G2).
    width, height, _ang, centre_x, centre_y_user = decompose_image_cm(current_cm)
    new_operands = rotated_image_stream_cm(
        centre_x,
        centre_y_user,
        width,
        height,
        float(angle) % 360.0,
    )
    new_stream = replace_operator_operands(tokens, cm_operator, new_operands)
    doc.update_stream(invocation.stream_xref, new_stream)
    model.mark_page_content_dirty(invocation.page_num - 1, fitz.Rect(invocation.bbox))
    model.edit_count += 1
    return True

def _turned_textbox_rect(
    old_rect: fitz.Rect, old_rotation: int, new_rotation: int, page_rect: fitz.Rect
) -> fitz.Rect:
    """The visual box a textbox occupies after turning from ``old_rotation`` to ``new_rotation``.

    The text's layout box (its width and height along the text direction) never changes; a
    quarter turn swaps the visual width and height about the box centre, so the same lines
    fit and nothing re-flows. Half turns and no-ops keep the rect. The turned box is slid
    back inside ``page_rect`` rather than cropped (a cropped box would re-flow the text);
    only a box larger than the page is left for the caller's clamp.
    """
    rect = fitz.Rect(old_rect)
    if (int(new_rotation) - int(old_rotation)) % 180 != 90:
        return rect
    centre_x = (rect.x0 + rect.x1) / 2.0
    centre_y = (rect.y0 + rect.y1) / 2.0
    half_w = rect.height / 2.0
    half_h = rect.width / 2.0
    turned = fitz.Rect(centre_x - half_w, centre_y - half_h, centre_x + half_w, centre_y + half_h)
    shift_x = 0.0
    shift_y = 0.0
    if turned.width <= page_rect.width:
        shift_x = max(page_rect.x0 - turned.x0, 0.0) or min(page_rect.x1 - turned.x1, 0.0)
    if turned.height <= page_rect.height:
        shift_y = max(page_rect.y0 - turned.y0, 0.0) or min(page_rect.y1 - turned.y1, 0.0)
    return turned + (shift_x, shift_y, shift_x, shift_y)


def rotate_object(model: PDFModel, request: RotateObjectRequest) -> bool:
    """Rotate one object; ``False`` changes nothing and records why on
    ``model.last_object_op_refusal`` (D-OLD-MARKERS)."""
    model.last_object_op_refusal = None
    return _record_outcome(model, _rotate_object_impl(model, request), request.object_kind, request.object_id)


def _rotate_object_impl(model: PDFModel, request: RotateObjectRequest) -> bool:
    if request.object_kind == "native_image":
        invocation = _find_native_image_invocation(model, request.page_num, request.object_id)
        if invocation is None:
            return _refuse(model, ObjectOpRefusal.OBJECT_NOT_FOUND)
        if request.absolute_rotation is not None:
            if invocation.is_form_nested:
                # Free rotation turns about the cm centre in page space; a form-nested
                # image is placed in the form's space (the hit info does not offer it).
                return _refuse(model, ObjectOpRefusal.NOT_SUPPORTED)
            return _rotate_native_image_absolute(model, invocation, request.absolute_rotation)
        new_rotation = (float(invocation.rotation) + float(request.rotation_delta)) % 360
        return _rewrite_native_image_matrix(model, 
            invocation,
            fitz.Rect(invocation.bbox),
            new_rotation,
        )
    found = _find_app_object_annot(model, request.page_num, request.object_id, request.object_kind)
    if found is None:
        return _refuse(model, ObjectOpRefusal.OBJECT_NOT_FOUND)
    page, annot, payload = found
    if payload["kind"] != "textbox":
        if payload.get("kind") != "image":
            return _refuse(model, ObjectOpRefusal.NOT_SUPPORTED)
        invocation = _resolve_marker_image_invocation(
            model, request.page_num, payload, _image_payload_unrotated_rect(annot, payload), annot=annot
        )
        if invocation is None:
            return _refuse(model, ObjectOpRefusal.IMAGE_NOT_LOCATED)
        # Re-read after resolution: a repaired old marker now holds the drawn placement.
        rect = _image_payload_unrotated_rect(annot, payload)
        if request.absolute_rotation is not None:
            if not _rotate_native_image_absolute(model, invocation, request.absolute_rotation):
                return False
            _sync_image_marker_to_drawn(
                model, request.page_num, annot, payload, invocation, float(request.absolute_rotation)
            )
            return True
        old_rotation = float(payload.get("rotation", 0)) % 360
        new_rotation = (old_rotation + float(request.rotation_delta)) % 360
        if not _rewrite_native_image_matrix(model, invocation, rect, new_rotation):
            return False
        _sync_image_marker_to_drawn(model, request.page_num, annot, payload, invocation, new_rotation)
        return True
    if not _resolve_textbox_marker(model, page, annot, payload):
        return _refuse(model, ObjectOpRefusal.TEXTBOX_TEXT_CHANGED)
    old_rect = fitz.Rect(payload["rect"])
    if request.absolute_rotation is not None:
        new_rotation = int(round(float(request.absolute_rotation))) % 360
    else:
        new_rotation = (int(payload.get("rotation", 0)) + int(request.rotation_delta)) % 360
    # F15-6: the htmlbox rect is the FINAL (visual) box of the rotated content, so a quarter
    # turn must turn the box too; re-inserting into the unturned rect squeezes the same text
    # into the wrong aspect and htmlbox shrinks it (scale_low=0) to fit.
    new_rect = _turned_textbox_rect(
        old_rect, int(payload.get("rotation", 0)), new_rotation, fitz.Rect(page.rect)
    )
    if not _erase_textbox_drawing(model, page, payload, request.object_id):
        return False
    _delete_app_object_annots(model, request.page_num, request.object_id, expected_kind="textbox")
    insert_state = _insert_textbox_visual_content(model, 
        request.page_num,
        new_rect,
        payload["text"],
        font=payload["font"],
        size=payload["size"],
        color=tuple(payload["color"]),
        rotation=new_rotation,
    )
    _create_textbox_object_marker(model, 
        request.page_num,
        insert_state["bounded_visual"],
        text=insert_state["text"],
        font=payload["font"],
        size=payload["size"],
        color=tuple(payload["color"]),
        rotation=new_rotation,
        object_id=request.object_id,
    )
    model.block_manager.rebuild_page(request.page_num - 1, model.doc)
    # R6-01: redact+reinsert orphaned the prior content stream; register for batched GC.
    _register_mutation(model, request.page_num - 1, old_rect | fitz.Rect(insert_state["bounded_visual"]))
    return True

def _delete_object_impl(model: PDFModel, request: DeleteObjectRequest) -> bool:
    if request.object_kind == "native_image":
        invocation = _find_native_image_invocation(model, request.page_num, request.object_id)
        if invocation is None:
            return _refuse(model, ObjectOpRefusal.OBJECT_NOT_FOUND)
        if not _remove_native_image_invocation(model, invocation):
            return False
        return True
    found = _find_app_object_annot(model, request.page_num, request.object_id, request.object_kind)
    if found is None:
        return _refuse(model, ObjectOpRefusal.OBJECT_NOT_FOUND)
    page, annot, payload = found
    if payload["kind"] == "rect":
        marker_rect = annot_page_rect(page, annot)
        page.delete_annot(annot)
        _register_mutation(model, request.page_num - 1, marker_rect)
        return True
    if payload["kind"] == "image":
        # Strip only this image's own content-stream invocation. The old path redacted
        # the image's rectangle, and apply_redactions is *geometric*: it destroys every
        # image, glyph and stroke the rectangle touches, not the one object the user
        # selected. Resolution mirrors move/rotate exactly (UNROTATED page space).
        old_rect = _image_payload_unrotated_rect(annot, payload)
        invocation = _resolve_marker_image_invocation(
            model, request.page_num, payload, old_rect, annot=annot
        )
        if invocation is None:
            # Two very different failures land here, and they want opposite handling.
            if _app_image_invocation_candidates(
                model, request.page_num, payload, old_rect
            ) or _image_drawing_may_remain(model, request.page_num, payload, old_rect):
                # Ambiguous, or an old marker whose picture is still drawn near it with
                # no single clear candidate (D-OLD-MARKERS): the pixels exist but we
                # cannot say which placement is ours. Fail safe — deleting the marker
                # alone would orphan visible content, and redacting is the data-loss
                # vector this whole path exists to remove.
                return _refuse(model, ObjectOpRefusal.IMAGE_NOT_LOCATED)
            # Orphaned: nothing renders this image any more (e.g. an external editor
            # stripped the XObject and left our hidden marker). Clean the marker up rather
            # than leaving a hit-detectable object that no verb can touch.
            if not _delete_app_object_annots(model, request.page_num, request.object_id, expected_kind="image"):
                return False
            _register_mutation(model, request.page_num - 1, old_rect)
            return True
        # _remove_native_image_invocation registers the pending edit + edit_count itself,
        # so no _register_mutation here (that would double-count).
        if not _remove_native_image_invocation(model, invocation):
            return False
        if not _delete_app_object_annots(model, request.page_num, request.object_id, expected_kind="image"):
            # The stream was already rewritten; a surviving marker would be a phantom
            # selectable object. Fail the transaction so the snapshot rollback restores it.
            return False
        return True
    if payload["kind"] != "textbox":
        return _refuse(model, ObjectOpRefusal.NOT_SUPPORTED)
    # An old marker with one clear drawing is repaired first, so the box's own form is
    # emptied; a stale one is still deleted when the guarded erase can remove exactly
    # its drawing (nothing drawn under it: an orphaned marker is cleaned up).
    stale = not _resolve_textbox_marker(model, page, annot, payload)
    old_rect = fitz.Rect(payload["rect"])
    if not _erase_textbox_drawing(model, page, payload, request.object_id):
        if stale:
            return _refuse(model, ObjectOpRefusal.TEXTBOX_TEXT_CHANGED)
        return False
    restored = _find_app_object_annot(model, request.page_num, request.object_id, "textbox")
    if restored is not None:
        restored[0].delete_annot(restored[1])
    model.block_manager.rebuild_page(request.page_num - 1, model.doc)
    _register_mutation(model, request.page_num - 1, old_rect)
    return True


def _restore_delete_transaction(
    model: PDFModel,
    snapshot: bytes,
    pending_edits: list,
    edit_count: int,
    secure_save_required: bool,
) -> None:
    # Also reinstates the snapshot's maintenance book (fidelity protection and the
    # pending entries), so a protected page stays protected after a failed batch.
    # A restore that fails here leaves the batch's half-applied deletions:
    # the session is latched damaged (no in-place save) and the error propagates.
    model._restore_doc_after_failed_mutation(snapshot)
    model.pending_edits = pending_edits
    model.edit_count = edit_count
    model.secure_save_required = secure_save_required
    try:
        model.block_manager.build_index(model.doc)
    except Exception:
        logger.exception("Failed to refresh text index after delete transaction rollback")


def _ordered_delete_requests(requests: list[DeleteObjectRequest]) -> list[DeleteObjectRequest]:
    """Keep native-image occurrence IDs stable by deleting highest occurrences first."""
    native: list[DeleteObjectRequest] = []
    others: list[DeleteObjectRequest] = []
    for request in requests:
        (native if request.object_kind == "native_image" else others).append(request)

    def _native_key(request: DeleteObjectRequest) -> tuple[int, int]:
        try:
            occurrence = int(str(request.object_id).rsplit(":", 1)[-1])
        except ValueError:
            occurrence = -1
        return (int(request.page_num), occurrence)

    native.sort(key=_native_key, reverse=True)
    return [*native, *others]


def delete_objects_atomic(model: PDFModel, requests: list[DeleteObjectRequest]) -> bool:
    """Delete all requested objects as one document-and-bookkeeping transaction.

    ``False`` (nothing deleted: the batch is rolled back) records the refusing object
    and why on ``model.last_object_op_refusal`` (D-OLD-MARKERS)."""
    model.last_object_op_refusal = None
    if not requests:
        return _refuse(model, ObjectOpRefusal.OBJECT_NOT_FOUND)
    snapshot = model._capture_doc_snapshot()
    pending_edits = list(model.pending_edits)
    edit_count = int(model.edit_count)
    secure_save_required = bool(model.secure_save_required)
    try:
        for request in _ordered_delete_requests(list(requests)):
            if not _record_outcome(
                model, _delete_object_impl(model, request), request.object_kind, request.object_id
            ):
                refused = model.last_object_op_refusal
                # Only roll back if the document was actually touched. `_restore_doc_from_snapshot`
                # closes and reopens `model.doc`, so running it on a pure no-op (resolution failed
                # before any stream was rewritten) would swap the live handle for nothing: cached
                # `fitz.Page` objects would point at a closed document, and the restored doc's empty
                # `doc.name` silently degrades the next save from incremental to full. Every mutating
                # path bumps `edit_count`, so comparing against the transaction's opening value
                # witnesses a mutation by this request *or* by any earlier one in the batch.
                if int(model.edit_count) != edit_count:
                    _restore_delete_transaction(
                        model, snapshot, pending_edits, edit_count, secure_save_required
                    )
                model.last_object_op_refusal = refused
                return False
    except Exception:
        _restore_delete_transaction(model, snapshot, pending_edits, edit_count, secure_save_required)
        raise
    model.secure_save_required = True
    model.last_object_op_refusal = None
    return True


def delete_object(model: PDFModel, request: DeleteObjectRequest) -> bool:
    return delete_objects_atomic(model, [request])


def resize_object(model: PDFModel, request: ResizeObjectRequest) -> bool:
    # Resize is modeled as a move with a new destination rect on the same page.
    return move_object(model, 
        MoveObjectRequest(
            object_id=request.object_id,
            object_kind=request.object_kind,
            source_page=request.page_num,
            destination_page=request.page_num,
            destination_rect=fitz.Rect(request.destination_rect),
        )
    )
