"""Stable reason codes for a text edit the Model refuses by raising.

Owner decision (adversarial round 11, "Refusal UI"): every refused text edit
reaches the user as ONE plain Traditional Chinese message per refusal reason,
never as the exception's English technical text.  The Model therefore raises
``TextEditRefused`` carrying a ``TextEditRefusal`` code; the Controller maps
the code to a fixed sentence (``controller/text_edit_refusals.py``) and logs
the technical ``detail``.  The code values are the contract between the two
layers: add a member here, add its sentence there (a test pins that every
member has one).

Qt-free by construction (CLAUDE.md layer rules).  Results that are not
exceptions (``EditTextResult`` values, ``CommitOutcome.degraded_reason``)
already have their own zh-TW mapping and are not repeated here.
"""
from __future__ import annotations

import enum


class TextEditRefusal(str, enum.Enum):
    """Why a text edit was refused (or failed) after the Model began it."""

    # The redaction left the original glyphs on the page (vertical text,
    # Type3, text MuPDF cannot clip): the replacement would stack over them.
    REDACTION_LEFT_SOURCE = "redaction_left_source"
    # The new text does not fit the box at any scale the strategies allow.
    TEXT_DOES_NOT_FIT = "text_does_not_fit"
    # Requested characters are missing from the page after the insert.
    CHARACTERS_LOST = "characters_lost"
    # Untouched glyphs the rebuild cannot keep (no Unicode identity) were not
    # acknowledged by the user (F11-UNI-1), or were typed.
    UNIDENTIFIABLE_GLYPHS_NOT_ACKNOWLEDGED = "unidentifiable_glyphs_not_acknowledged"
    # CJK Ext-B characters, no Ext-B font installed on Windows (installing the
    # system fonts can fix it; any other Ext-B case is NO_FONT_FOR_CHARACTERS).
    EXT_B_FONT_MISSING = "ext_b_font_missing"
    # CJK Ext-B characters, an Ext-B font IS installed but the fontTools
    # library cannot be imported: a broken install, so "reinstall the program"
    # (F13-ENV-3), not "use other characters" and not "install fonts".
    EXT_B_COMPONENT_MISSING = "ext_b_component_missing"
    # No font draws some requested character (a .notdef box would show).
    NO_FONT_FOR_CHARACTERS = "no_font_for_characters"
    # The reference glyphs are not drawn on the page after the insert.
    GLYPHS_NOT_DRAWN = "glyphs_not_drawn"
    # The edited text is not found where it was inserted.
    TARGET_NOT_PRESENT = "target_not_present"
    # Erasing the edited text would also erase glyphs of text the rewrite
    # does not re-draw (they overlap the edited glyphs), F13-VF-2.
    UNTOUCHED_TEXT_WOULD_BE_LOST = "untouched_text_would_be_lost"
    # A neighbouring run that had to be replayed did not come back intact.
    PROTECTED_SPAN_CHANGED = "protected_span_changed"
    # The inserted text differs too much from what was asked.
    VERIFICATION_FAILED = "verification_failed"
    # A user-dragged box (``new_rect``) would draw the edited text over
    # untouched text (TODOS F13-VF-4c).  A dragged box is never capped, but it
    # is guarded; this code lets the Controller offer, for that one edit,
    # "place anyway" (``place_anyway=True``: neither cap nor guard).
    DRAGGED_BOX_OVERPRINTS = "dragged_box_overprints"
    # The text the rebuild writes again (the edited runs, a replayed
    # neighbour, a pushed block) is painted in a state its writers cannot
    # reproduce -- a clipping render mode, a Pattern colour, outline text under
    # a scaled CTM, a soft mask on text that moves, glyphs whose state cannot
    # be established -- or a cross-page move would re-create styled text as a
    # plain text box (F17-COL-1..4).  Refused before anything is written:
    # never a silent conversion to plain RGB fill.
    TEXT_STATE_NOT_REPRODUCIBLE = "text_state_not_reproducible"
    # The edit failed and the page could NOT be put back.
    ROLLBACK_FAILED = "rollback_failed"
    # Any other unexpected failure inside the edit (page rolled back).
    EDIT_FAILED = "edit_failed"


class TextEditRefused(RuntimeError):
    """A text edit that did not commit, with a stable reason code.

    ``str(exc)`` is the technical detail (English/diagnostic, for the log
    only); the user-facing sentence is the Controller's job.  Subclasses
    ``RuntimeError`` so every existing ``except RuntimeError`` still holds.
    """

    def __init__(self, reason: TextEditRefusal, detail: str = "") -> None:
        super().__init__(detail or reason.value)
        self.reason = reason
        self.detail = detail or reason.value
