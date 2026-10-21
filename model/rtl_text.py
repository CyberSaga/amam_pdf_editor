"""Right-to-left script detection shared by the text index and the edit paths.

The text index contract (F15-RTL-ORDER): a run's ``text`` is LOGICAL order (the
order the word is typed and read; MuPDF's extraction already hands it back that
way) while its ``bbox`` / ``origin`` stay VISUAL page geometry.  Anything that
needs to know whether a string holds such text asks :func:`contains_rtl`.
"""

from __future__ import annotations

import unicodedata

#: Hebrew starts at U+0590; every code point below it has a left-to-right,
#: weak or neutral bidi class, so the common (Latin/CJK) case never calls
#: ``unicodedata``.
_FIRST_RTL_CODE_POINT = 0x0590


def is_rtl_char(ch: str) -> bool:
    """True for a strong right-to-left character (bidi class ``R`` or ``AL``:
    Hebrew, Arabic, Syriac, Thaana, N'Ko, ...)."""
    return ord(ch) >= _FIRST_RTL_CODE_POINT and unicodedata.bidirectional(ch) in ("R", "AL")


def contains_rtl(text: str | None) -> bool:
    """True when ``text`` holds at least one strong right-to-left character."""
    if not text or text.isascii():
        return False
    return any(is_rtl_char(ch) for ch in text)


def first_strong_is_rtl(text: str | None) -> bool | None:
    """UAX#9 P2/P3 on ``text``: ``True`` when its first strong character
    (bidi class ``L``, ``R`` or ``AL``) is right-to-left, ``False`` when it is
    left-to-right, ``None`` when it has none (digits, punctuation, spaces)."""
    for ch in text or "":
        bidi = unicodedata.bidirectional(ch)
        if bidi == "L":
            return False
        if bidi in ("R", "AL"):
            return True
    return None


def grows_right_to_left(text: str | None, paragraph: str | None = None) -> bool:
    """Does an edited run holding ``text`` keep its RIGHT edge and grow to the
    left (D-RTL-GROW, owner decision after round 15)?

    The one direction rule for every route that redraws a run:

    * no right-to-left letter (Latin, CJK, digits or punctuation only): no --
      left-to-right, the behaviour before the decision;
    * right-to-left letters and no left-to-right letter (neutrals such as
      spaces, digits and punctuation do not count): yes;
    * both (a mixed run): the base direction of ``paragraph`` -- its first
      strong character (UAX#9 P2/P3) -- or, when ``paragraph`` has none, the
      run's own first strong character.
    """
    if not contains_rtl(text):
        return False
    if not any(unicodedata.bidirectional(ch) == "L" for ch in text or ""):
        return True
    base = first_strong_is_rtl(paragraph)
    if base is None:
        base = first_strong_is_rtl(text)
    return bool(base)
