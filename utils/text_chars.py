from __future__ import annotations

import re

# C0/C1 controls (Unicode category Cc), the BMP noncharacters U+FDD0..U+FDEF, the
# last two code points of every plane and U+FFFC (the object replacement character:
# the anchor an image in pasted HTML leaves in ``toPlainText()``, drawn as a dashed
# "OBJ" box, F16-PASTE-2).  Tab (0x09) and newline (0x0A) are layout and stay.
# Built from code points so the source holds no raw control characters.
#
# ONE definition for both layers (S17-PASTE-NOTICE): the model strips these where user
# text enters a drawn textbox / watermark (``model.text_normalization``), the view's
# inline editor strips and counts them at paste time to tell the user what was removed.
# Qt-free and model-free so each layer may import it.
OBJECT_REPLACEMENT_CHARACTER = "\ufffc"

_UNRENDERABLE_RANGES: tuple[tuple[int, int], ...] = (
    (0x00, 0x08),
    (0x0B, 0x1F),
    (0x7F, 0x9F),
    (0xFDD0, 0xFDEF),
    (0xFFFC, 0xFFFC),  # OBJECT_REPLACEMENT_CHARACTER
    *((plane * 0x10000 + 0xFFFE, plane * 0x10000 + 0xFFFF) for plane in range(17)),
)
RE_UNRENDERABLE = re.compile(
    "["
    + "".join(f"{re.escape(chr(lo))}-{re.escape(chr(hi))}" for lo, hi in _UNRENDERABLE_RANGES)
    + "]"
)


def fold_line_breaks(text: str) -> str:
    """CR LF and a lone CR become LF (the HTML engine already drew them as breaks)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_unrenderable(text: str | None) -> tuple[str, int, int]:
    """``(clean_text, controls_removed, objects_removed)`` for ``text``.

    ``clean_text`` is ``text`` with line breaks folded to LF and every unrenderable
    character removed; ``objects_removed`` counts U+FFFC (an inline image anchor),
    ``controls_removed`` every other removed character.  Folding CR LF is not a
    removal and is not counted.  Idempotent.
    """
    if not text:
        return "", 0, 0
    folded = fold_line_breaks(text)
    objects = folded.count(OBJECT_REPLACEMENT_CHARACTER)
    cleaned = RE_UNRENDERABLE.sub("", folded)
    return cleaned, len(folded) - len(cleaned) - objects, objects


def count_unrenderable(text: str | None) -> tuple[int, int]:
    """``(controls, objects)`` ``split_unrenderable`` would remove from ``text``."""
    _cleaned, controls, objects = split_unrenderable(text)
    return controls, objects
