from __future__ import annotations

from dataclasses import dataclass

import fitz


@dataclass(frozen=True)
class StyleOverrides:
    """Style fields the user *explicitly* touched during an edit session.

    A field is non-None only when the user operated that control; merely
    opening the editor never populates anything.  This is how the model
    distinguishes "user typed text" from "user restyled" — with an empty
    overrides object, style truth stays with the source spans and no
    substitute font/size/color may silently replace them.
    """

    font_family: str | None = None
    font_size: float | None = None
    color: tuple[float, float, float] | None = None

    @property
    def changed(self) -> bool:
        return any(
            value is not None
            for value in (self.font_family, self.font_size, self.color)
        )


@dataclass(frozen=True)
class SourceShowRef:
    """Identity of ONE content-stream show operator a text target came from.

    Plain, immutable DTO (the View may carry it; ``view.text_editing ->
    model.edit_requests`` is the allowlisted DTO import).  Produced only by
    the click-time resolver ``model.text_commit.source_run`` after it has
    proven the clicked runs are exactly this show.  ``seq`` is an ordinal
    of the page replay and is NOT identity on its own -- ``stream_xref`` +
    ``op_start`` + ``page_xref`` are; ``origin`` is the show origin in
    VISUAL (displayed/pixmap) page space, the same space as the engine's
    ``expected_origin``.
    """

    page_xref: int
    stream_xref: int
    op_start: int
    seq: int
    origin: tuple[float, float]


@dataclass(frozen=True)
class EditTextRequest:
    page: int
    rect: fitz.Rect
    new_text: str
    font: str
    size: float
    color: tuple
    original_text: str | None = None
    vertical_shift_left: bool = True
    new_rect: fitz.Rect | None = None
    target_span_id: str | None = None
    target_mode: str | None = None
    style_overrides: StyleOverrides | None = None
    plan_token: str | None = None
    # UI step 4: the proven source show the edited target came from (the
    # hit's ``TextHit.source_ref``).  The model RE-DERIVES the group on the
    # commit side and refuses when it differs -- wrong-target protection for
    # twin shows; never trusted as geometry.
    source_ref: SourceShowRef | None = None
    # UI step 5 (apply by token): set ONLY by the inline Apply
    # (``view/text_editing.py``) while plan preview is on.  The model then
    # refuses ``PREVIEW_PENDING`` when ``plan_token`` is None.  Tokenless
    # internal callers (cross-page delete, same-page drag, redo) leave it
    # False and are never gated.
    requires_preview_token: bool = False
    # UI step 7: the explicit rebuild consent, set ONLY by the
    # "改用重建文字…" action.  Without it a tiered refusal is final
    # (``EditTextResult.REJECTED``, zero mutation, never legacy); with it
    # the model still asks the confirm callback (default No) and a missing
    # callback is ``FALLBACK_DECLINED``.  Also exempts the request from the
    # ``requires_preview_token`` gate.  Per request, never sticky.
    allow_rebuild: bool = False
    # UI step 9: the document session the request was made in (the inline
    # editor stamps it when it opens).  The Controller refuses a request
    # whose session is not the active one -- zero mutation -- so an edit can
    # never commit into another document, not even a byte-identical copy
    # (plan tokens are content-derived).  None = an internal caller that
    # acts on the active document by construction.
    session_id: str | None = None

    def to_legacy_args(self) -> tuple:
        return (
            self.page,
            self.rect,
            self.new_text,
            self.font,
            self.size,
            self.color,
            self.original_text,
            self.vertical_shift_left,
            self.new_rect,
            self.target_span_id,
            self.target_mode,
        )


@dataclass(frozen=True)
class MoveTextRequest:
    source_page: int
    source_rect: fitz.Rect
    destination_page: int
    destination_rect: fitz.Rect
    new_text: str
    font: str
    size: float
    color: tuple
    original_text: str | None = None
    target_span_id: str | None = None
    target_mode: str | None = None
    # UI step 7: a move rebuilds text (the destination is a fresh
    # ``add_textbox`` in a chosen font, critique B3), so the WHOLE move --
    # source deletion and destination insert -- needs this explicit consent.
    allow_rebuild: bool = False
    # UI step 9: same document binding as ``EditTextRequest.session_id``.
    session_id: str | None = None
