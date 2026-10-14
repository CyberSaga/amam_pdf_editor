"""Runs the app wrote for ONE text edit reopen as ONE edit box (S17-ANCHOR-JOIN).

A legacy rebuild re-inserts the edited text through ``insert_htmlbox``, which
splits it into several runs on one baseline as soon as the glyphs come from
more than one font (a Latin word plus a CJK tail).  Left alone, every fragment
reopens by itself: the user sees half a heading in the edit box.  The owner
decided (ANCHOR-FRAGMENTS): runs the app itself wrote for one edit, on one
baseline, reopen as one box and commit back as one edit.

Only provenance justifies the join -- two source runs that merely share a line
(a bold word inside a sentence) are NOT one edit.  So the edit records
``JoinedEditRun`` (the text it wrote and where) and every later use re-proves
the record against the live runs: the runs of ONE line inside the rect whose
texts concatenate to exactly the recorded text.  A record that no longer
proves (undo, a later edit, a page shift) simply stops joining; it never
joins anything the live page does not show as that text.

Qt-free; shared by ``pdf_model`` (hit-test) and ``pdf_text_edit`` (commit).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import fitz

from model.text_block_parsing import EditableSpan
from model.text_normalization import normalize_text

# A recorded rect is the union of the fragments' own boxes; extraction drift of
# a re-parse is well below this.
_RECT_TOL = 1.0


@dataclass(frozen=True)
class JoinedEditRun:
    """The single-line text one app edit wrote, and the union rect of its runs."""

    text: str
    norm_text: str
    rect: fitz.Rect

    def region(self) -> fitz.Rect:
        r = fitz.Rect(self.rect)
        return fitz.Rect(r.x0 - _RECT_TOL, r.y0 - _RECT_TOL, r.x1 + _RECT_TOL, r.y1 + _RECT_TOL)


@dataclass(frozen=True)
class JoinedEditGroup:
    """A ``JoinedEditRun`` proven against the live runs: its member runs in reading order."""

    record: JoinedEditRun
    members: tuple[EditableSpan, ...]

    @property
    def text(self) -> str:
        return self.record.text

    @property
    def first_span_id(self) -> str:
        return self.members[0].span_id

    @property
    def member_span_ids(self) -> tuple[str, ...]:
        return tuple(m.span_id for m in self.members)

    def rect(self) -> fitz.Rect:
        union = fitz.Rect(self.members[0].bbox)
        for member in self.members[1:]:
            union |= fitz.Rect(member.bbox)
        return union

    def dominant(self) -> EditableSpan:
        """The member that carries most of the text: its style is the group's."""
        return max(self.members, key=lambda m: len(normalize_text(m.text or "")))


def find_joined_fragments(
    runs: Iterable[EditableSpan], norm_text: str, region: fitz.Rect
) -> list[EditableSpan] | None:
    """The runs of ONE line, inside ``region``, whose texts concatenate to
    ``norm_text`` (already ``normalize_text``-ed), in reading order; ``None``
    when there are fewer than two or no exact window exists.

    A line is MuPDF's own notion of "one baseline" (``block_idx``/``line_idx``
    of the run index).  Whitespace-only runs between members ride along;
    a foreign run between them breaks the window.
    """
    if not norm_text:
        return None
    lines: dict[tuple[int, int], list[EditableSpan]] = {}
    for run in runs:
        if not fitz.Rect(run.bbox).intersects(region):
            continue
        lines.setdefault((run.block_idx, run.line_idx), []).append(run)
    for key in sorted(lines):
        ordered = sorted(lines[key], key=lambda r: r.span_idx)
        for start in range(len(ordered)):
            first_norm = normalize_text(ordered[start].text or "")
            if not first_norm or not norm_text.startswith(first_norm):
                continue
            window = [ordered[start]]
            acc = first_norm
            for nxt in ordered[start + 1:]:
                piece = normalize_text(nxt.text or "")
                window.append(nxt)
                acc += piece
                if acc == norm_text and piece:
                    if len(window) >= 2:
                        return window
                    break
                if not norm_text.startswith(acc):
                    break
    return None


def prove_joined_group(record: JoinedEditRun, runs: Sequence[EditableSpan]) -> JoinedEditGroup | None:
    """``record`` re-proven against the live ``runs`` of its page, or ``None``."""
    members = find_joined_fragments(runs, record.norm_text, record.region())
    if members is None:
        return None
    return JoinedEditGroup(record=record, members=tuple(members))


def joined_record_for(text: str, members: Sequence[EditableSpan]) -> JoinedEditRun:
    union = fitz.Rect(members[0].bbox)
    for member in members[1:]:
        union |= fitz.Rect(member.bbox)
    return JoinedEditRun(text=text, norm_text=normalize_text(text), rect=union)
