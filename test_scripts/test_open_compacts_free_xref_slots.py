"""Open-time compaction of a cross-reference table full of free slots (round 8 LS-3, owner option B).

Non-secure full saves serialize with ``garbage=1`` so the live document keeps
its xref numbering (page-snapshot undo survives a save).  The price is that a
freed object leaves a free slot (20 bytes) in the file, and nothing in a plain
edit / undo / save session ever reclaims it: the table grows across sessions
without bound (13 slots per edit -> undo -> save cycle in the round-8 repro).
``PDFModel.open_pdf`` therefore compacts the IN-MEMORY document (``garbage=2``
round trip, before any undo history exists) when the file's free-slot count and
ratio both exceed ``model.xref_compaction`` thresholds, skipping signed and
encrypted files.  The file on disk stays byte-identical until the next real
save; the session is not dirty.  Model layer only, no Qt.

Every PDF is built in ``tmp_path``; no repository fixture is modified.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from model.pdf_model import PDFModel  # noqa: E402
from test_save_prunes_orphans import _make_signed_pdf  # noqa: E402

PAGE_TEXT = "Price 2024 | Downstream line stays"
USER_PW = "user-secret"


# ---------------------------------------------------------------- helpers


def _free_slots(doc: fitz.Document) -> int:
    """Free (``null``) entries in ``doc``'s table, slot 0 excluded."""
    return sum(1 for x in range(1, doc.xref_length()) if doc.xref_object(x) == "null")


def _add_free_slots(path: Path, free: int, *, live: int = 0) -> Path:
    """Leave ``free`` free slots (and ``live`` extra reachable objects) in ``path``.

    Junk objects nothing references are freed by the ``garbage=1`` rewrite the
    editor's own saves use, so the file gets exactly the shape a long run of
    edit -> undo -> save cycles leaves behind.
    """
    doc = fitz.open(str(path))
    if live:
        refs = []
        for _ in range(live):
            xref = doc.get_new_xref()
            doc.update_object(xref, "<< /Live 1 >>")
            refs.append(f"{xref} 0 R")
        doc.xref_set_key(doc.pdf_catalog(), "LiveObjects", f"[{' '.join(refs)}]")
    for _ in range(free):
        doc.update_object(doc.get_new_xref(), "<< /Junk 1 >>")
    staged = path.with_name(path.stem + ".staged.pdf")
    doc.save(str(staged), garbage=1)
    doc.close()
    staged.replace(path)
    return path


def _make_pdf(path: Path, *, free: int = 0, live: int = 0, blank: bool = False) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    if not blank:
        page.insert_text((72, 100), PAGE_TEXT, fontsize=12.0)
    doc.save(str(path))
    doc.close()
    if free or live:
        _add_free_slots(path, free, live=live)
    return path


def _encrypt(path: Path) -> Path:
    doc = fitz.open(str(path))
    staged = path.with_name(path.stem + ".enc.pdf")
    doc.save(
        str(staged),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw=USER_PW,
        permissions=fitz.PDF_PERM_PRINT,
    )
    doc.close()
    staged.replace(path)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_stats(path: Path) -> tuple[int, int, str, bool]:
    """(xref_length, free slots, page-1 text, is_repaired) of the file at ``path``."""
    doc = fitz.open(str(path))
    try:
        return int(doc.xref_length()), _free_slots(doc), doc[0].get_text(), bool(doc.is_repaired)
    finally:
        doc.close()


def _open(path: Path, *, password: str | None = None, append: bool = False) -> PDFModel:
    model = PDFModel()
    model.open_pdf(str(path), password=password, append=append)
    return model


# The chosen thresholds, pinned here on purpose: a change to the numbers in
# ``model/xref_compaction.py`` must be deliberate (and re-measured), so the
# fixtures below are sized from these literals and one test checks the module.
MIN_FREE_SLOTS = 512
MIN_FREE_RATIO = 0.5


def _thresholds() -> tuple[int, float]:
    return MIN_FREE_SLOTS, MIN_FREE_RATIO


def test_the_module_thresholds_match_the_pinned_numbers() -> None:
    from model import xref_compaction

    assert int(xref_compaction.MIN_FREE_SLOTS) == MIN_FREE_SLOTS
    assert float(xref_compaction.MIN_FREE_RATIO) == MIN_FREE_RATIO
    assert xref_compaction.MAX_FILE_BYTES == 64 * 1024 * 1024
    assert xref_compaction.MAX_CENSUS_SLOTS == 200_000


# ---------------------------------------------------------------- not compacted


def test_a_blank_single_page_file_stays_file_backed(tmp_path) -> None:
    path = _make_pdf(tmp_path / "blank.pdf", blank=True)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert model.persisted_xref_length == model.doc.xref_length()
        assert not model.session_has_unsaved_changes(model.get_active_session_id())
    finally:
        model.close()


def test_a_healthy_file_with_no_free_slots_stays_file_backed(tmp_path) -> None:
    path = _make_pdf(tmp_path / "healthy.pdf")
    length, free, _, _ = _file_stats(path)
    assert free == 0
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert model.doc.xref_length() == length
        assert model.doc.can_save_incrementally()
    finally:
        model.close()


def test_under_the_free_slot_count_threshold_stays_file_backed(tmp_path) -> None:
    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "few.pdf", free=min_count - 1)
    length, free, _, _ = _file_stats(path)
    assert free == min_count - 1 and free / (length - 1) > 0.9
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert _free_slots(model.doc) == free
    finally:
        model.close()


def test_under_the_free_slot_ratio_threshold_stays_file_backed(tmp_path) -> None:
    min_count, min_ratio = _thresholds()
    # Many free slots, but the live table is bigger still: the waste is a
    # minority of the table and the session keeps its incremental saves.
    path = _make_pdf(tmp_path / "big_live.pdf", free=min_count + 100, live=3 * (min_count + 100))
    length, free, _, _ = _file_stats(path)
    assert free >= min_count and free / (length - 1) < min_ratio
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert _free_slots(model.doc) == free
    finally:
        model.close()


def test_a_signed_file_is_never_compacted(tmp_path) -> None:
    min_count, _ = _thresholds()
    path = _make_signed_pdf(tmp_path / "signed.pdf")
    _add_free_slots(path, 4 * min_count)
    from model.text_commit.inspect import document_has_a_signed_signature

    length, free, _, _ = _file_stats(path)
    assert free >= 4 * min_count
    model = _open(path)
    try:
        assert document_has_a_signed_signature(model.doc)
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert model.doc.xref_length() == length
    finally:
        model.close()


def test_an_encrypted_file_is_never_compacted_and_stays_readable(tmp_path) -> None:
    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "enc.pdf", free=4 * min_count)
    _encrypt(path)
    before = _sha(path)
    model = _open(path, password=USER_PW)
    try:
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert (model.doc.metadata or {}).get("encryption")
        # Usability is "content reads"; never read ``needs_pass`` on this handle.
        assert PAGE_TEXT in model.doc[0].get_text()
        assert _free_slots(model.doc) >= 4 * min_count
    finally:
        model.close()
    assert _sha(path) == before


# ---------------------------------------------------------------- compacted


def test_over_both_thresholds_compacts_the_session_in_memory(tmp_path) -> None:
    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=min_count)
    length, free, text, _ = _file_stats(path)
    assert free == min_count
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) is None, "the compacted document lives in memory"
        assert _free_slots(model.doc) == 0
        assert model.doc.xref_length() < length - min_count + 1 + 2
        assert model.doc[0].get_text() == text
        assert len(model.doc) == 1
        # The session still belongs to the user's file.
        assert Path(model.original_path).resolve() == path.resolve()
        assert model.find_session_by_path(str(path)) == model.get_active_session_id()
        # A memory-backed handle has no persisted table to append to.
        assert model.persisted_xref_length is None
    finally:
        model.close()


def test_the_file_bytes_are_untouched_and_the_session_is_clean_after_a_compacting_open(
    tmp_path,
) -> None:
    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    before = _sha(path)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) is None
        sid = model.get_active_session_id()
        assert not model.session_has_unsaved_changes(sid)
        assert not model.has_any_unsaved_changes()
        assert model.get_session_meta(sid)["dirty"] is False
        assert not model.command_manager.can_undo()
        assert _sha(path) == before, "open must not write the user's file"
    finally:
        model.close()
    assert _sha(path) == before, "close without a save must not write the user's file either"


def test_ctrl_s_after_a_compacting_open_writes_a_compact_file_with_identical_text(tmp_path) -> None:
    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    length, free, text, _ = _file_stats(path)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) is None
        # Ctrl+S: the controller saves back to original_path through save_as.
        model.save_as(model.saved_path or model.original_path)
        sid = model.get_active_session_id()
        assert not model.session_has_unsaved_changes(sid)
        new_length, new_free, new_text, repaired = _file_stats(path)
        assert new_text == text
        assert new_free == 0
        assert new_length <= length - free + 1
        assert not repaired
        assert path.read_bytes().count(b"%%EOF") == 1, "a full rewrite, not an append"
        # The fingerprint chokepoint recorded our own write: a second Ctrl+S is not refused.
        model.doc[0].insert_text((72, 140), "second save", fontsize=12.0)
        model.save_as(str(path))
        _, free2, text2, _ = _file_stats(path)
        assert "second save" in text2 and free2 == 0
    finally:
        model.close()


def test_undo_works_for_edits_made_after_the_compact(tmp_path) -> None:
    from test_save_prunes_orphans import _highlight_count, _record_highlight

    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    before = _sha(path)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) is None
        _record_highlight(model)
        assert model.session_has_unsaved_changes(model.get_active_session_id())
        assert sum(1 for a in model.doc[0].annots() or []) == 1
        model.command_manager.undo()
        assert sum(1 for a in model.doc[0].annots() or []) == 0
        assert not model.session_has_unsaved_changes(model.get_active_session_id())
        model.command_manager.redo()
        assert sum(1 for a in model.doc[0].annots() or []) == 1
        assert _sha(path) == before
        model.save_as(str(path))
        assert _highlight_count(path) == 1
        _, free, text, _ = _file_stats(path)
        assert free == 0 and PAGE_TEXT in text
    finally:
        model.close()


def test_two_tabs_one_compacted_one_file_backed(tmp_path) -> None:
    min_count, _ = _thresholds()
    grown = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    healthy = _make_pdf(tmp_path / "healthy.pdf")
    model = _open(grown)
    try:
        sid_grown = model.get_active_session_id()
        sid_healthy = model.open_pdf(str(healthy), append=True)
        assert sid_healthy != sid_grown
        assert PDFModel._backing_file(model.doc) == healthy.resolve()
        assert model.activate_session(sid_grown)
        assert PDFModel._backing_file(model.doc) is None
        assert _free_slots(model.doc) == 0
        assert model.find_session_by_path(str(grown)) == sid_grown
        assert model.find_session_by_path(str(healthy)) == sid_healthy
        assert not model.has_any_unsaved_changes()
        # Re-opening the compacted file focuses the existing tab (no second session).
        assert model.open_pdf(str(grown), append=True) == sid_grown
    finally:
        model.close()


# ---------------------------------------------------------------- bounds and fallbacks


def test_a_file_above_the_size_cap_is_not_compacted_and_walked_only_once(tmp_path, monkeypatch) -> None:
    """Above the compaction size cap nothing is compacted.  Since OD-FS1-READALL
    the open reads every object once anyway (lazy-damage repair at open, own
    slot cap ``MAX_READ_ALL_SLOTS``); the compaction census adds no second walk."""
    from collections import Counter

    from model import xref_compaction

    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    length = _file_stats(path)[0]
    monkeypatch.setattr(xref_compaction, "MAX_FILE_BYTES", path.stat().st_size - 1)
    probes: list[int] = []
    original = fitz.Document.xref_object

    def _counting(self, xref, *args, **kwargs):
        probes.append(xref)
        return original(self, xref, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "xref_object", _counting)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert model.doc.xref_length() == length
        assert Counter(probes) == Counter(range(1, length)), "one read-all walk, no census walk"
    finally:
        model.close()


def test_a_compacting_open_walks_the_table_only_once(tmp_path, monkeypatch) -> None:
    """The compaction verdict reuses the read-all walk's free-slot count."""
    from collections import Counter

    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    length = _file_stats(path)[0]
    probes: list[int] = []
    original = fitz.Document.xref_object

    def _counting(self, xref, *args, **kwargs):
        if PDFModel._backing_file(self) is not None:
            probes.append(xref)  # only the file-backed handle, not the compacted copy
        return original(self, xref, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "xref_object", _counting)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) is None, "compacted"
        assert Counter(probes) == Counter(range(1, length))
    finally:
        model.close()


def test_a_table_too_large_to_walk_is_not_compacted(tmp_path, monkeypatch) -> None:
    from model import xref_compaction

    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    length = _file_stats(path)[0]
    monkeypatch.setattr(xref_compaction, "MAX_CENSUS_SLOTS", length - 1)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert model.doc.xref_length() == length
    finally:
        model.close()


def test_a_failing_census_walk_skips_compaction_and_still_opens(tmp_path, monkeypatch) -> None:
    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    length = _file_stats(path)[0]

    def _boom(self, xref, *args, **kwargs):
        raise RuntimeError("walk failed")

    monkeypatch.setattr(fitz.Document, "xref_object", _boom)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert model.doc.xref_length() == length
        assert PAGE_TEXT in model.doc[0].get_text()
    finally:
        model.close()


def test_a_failed_in_memory_rewrite_falls_back_to_a_fresh_file_handle(tmp_path, monkeypatch) -> None:
    """``tobytes(garbage=2)`` renumbers the SOURCE handle in place; a failure after
    it must not leave that renumbered handle on the file (its next incremental
    save would write numbers the file does not have)."""
    from model import xref_compaction

    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    length, free, text, _ = _file_stats(path)
    before = _sha(path)
    original = xref_compaction.compact_in_memory

    def _renumber_then_fail(doc):
        doc.tobytes(garbage=2)
        assert doc.xref_length() < length, "precondition: the handle was renumbered in place"
        raise RuntimeError("reopen failed")

    monkeypatch.setattr(xref_compaction, "compact_in_memory", _renumber_then_fail)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) == path.resolve()
        assert model.doc.xref_length() == length, "a fresh handle, not the renumbered one"
        assert _free_slots(model.doc) == free
        assert model.doc[0].get_text() == text
        assert model.persisted_xref_length == length
    finally:
        model.close()
    assert _sha(path) == before
    assert original is not _renumber_then_fail


# ---------------------------------------------------------------- the verdict itself


def test_verdict_thresholds_are_inclusive_and_both_required(tmp_path) -> None:
    from model import xref_compaction

    min_count, min_ratio = _thresholds()
    cases = {
        "exact_count_high_ratio": (min_count, 0),
        "one_below_count": (min_count - 1, 0),
        "count_ok_ratio_low": (min_count, 2 * min_count),
        "big_both": (4 * min_count, min_count),
    }
    for name, (free, live) in cases.items():
        path = _make_pdf(tmp_path / f"{name}.pdf", free=free, live=live)
        doc = fitz.open(str(path))
        try:
            total = doc.xref_length() - 1
            actual_free = _free_slots(doc)
            verdict = xref_compaction.open_compaction_verdict(doc, path.stat().st_size)
            expected = actual_free >= min_count and actual_free / total >= min_ratio
            assert verdict.compact is expected, (name, verdict)
            if verdict.compact:
                assert verdict.free_slots >= min_count and verdict.total_slots == total
        finally:
            doc.close()


def test_verdict_walk_stops_early_on_a_healthy_table(tmp_path, monkeypatch) -> None:
    """A healthy file (the common case) must not pay for a full walk: once the
    remaining slots cannot reach the threshold the census stops."""
    from model import xref_compaction

    min_count, min_ratio = _thresholds()
    path = _make_pdf(tmp_path / "healthy_big.pdf", live=4 * min_count)
    probes: list[int] = []
    original = fitz.Document.xref_object

    def _counting(self, xref, *args, **kwargs):
        probes.append(xref)
        return original(self, xref, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "xref_object", _counting)
    doc = fitz.open(str(path))
    try:
        total = doc.xref_length() - 1
        verdict = xref_compaction.open_compaction_verdict(doc, path.stat().st_size)
        assert verdict.compact is False
        assert 0 < len(probes) <= total - int(total * min_ratio) + 2
    finally:
        doc.close()


def test_verdict_walk_stops_early_once_the_threshold_is_reached(tmp_path, monkeypatch) -> None:
    from model import xref_compaction

    min_count, _ = _thresholds()
    # Free slots first (low numbers), one live object: the walk may stop as soon
    # as the count and ratio are both satisfied, well before the table's end.
    path = _make_pdf(tmp_path / "front_loaded.pdf", free=8 * min_count)
    probes: list[int] = []
    original = fitz.Document.xref_object

    def _counting(self, xref, *args, **kwargs):
        probes.append(xref)
        return original(self, xref, *args, **kwargs)

    monkeypatch.setattr(fitz.Document, "xref_object", _counting)
    doc = fitz.open(str(path))
    try:
        total = doc.xref_length() - 1
        verdict = xref_compaction.open_compaction_verdict(doc, path.stat().st_size)
        assert verdict.compact is True
        assert len(probes) < total
    finally:
        doc.close()


def test_verdict_skips_an_unbacked_declared_table(tmp_path) -> None:
    """H10-2 class: a tiny file declaring millions of slots is never walked."""
    from model import xref_compaction

    class _Declares:
        def xref_length(self) -> int:
            return 5_000_000

        def xref_object(self, xref, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("walked an unbacked table")

    verdict = xref_compaction.open_compaction_verdict(_Declares(), 28 * 1024)
    assert verdict.compact is False


@pytest.mark.parametrize("size_over_cap", [0, 1])
def test_verdict_size_cap_boundary(tmp_path, monkeypatch, size_over_cap) -> None:
    from model import xref_compaction

    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    size = path.stat().st_size
    monkeypatch.setattr(xref_compaction, "MAX_FILE_BYTES", size - size_over_cap)
    doc = fitz.open(str(path))
    try:
        verdict = xref_compaction.open_compaction_verdict(doc, size)
        assert verdict.compact is (size_over_cap == 0)
    finally:
        doc.close()


def test_compact_in_memory_drops_every_free_slot_and_keeps_the_content_stream(tmp_path) -> None:
    from model import xref_compaction

    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    doc = fitz.open(str(path))
    contents = doc[0].read_contents()
    compacted = xref_compaction.compact_in_memory(doc)
    try:
        assert compacted is not doc
        assert PDFModel._backing_file(compacted) is None
        assert _free_slots(compacted) == 0
        assert compacted[0].read_contents() == contents
        assert not compacted.is_repaired
    finally:
        compacted.close()
        doc.close()


# ---------------------------------------------------------------- damaged files


def _shift_xref_entry(path: Path, *, which: str) -> int:
    """Damage one in-use entry of a classic xref table by +3 bytes; returns its xref.

    ``which="last"`` picks an object MuPDF loads lazily (the damage surfaces only
    when something walks the table), ``"first"`` one it loads at open (MuPDF
    repairs the table on open and sets ``is_repaired``).
    """
    import re

    data = path.read_bytes()
    match = re.search(rb"xref\r?\n0 (\d+)\r?\n", data)
    assert match, "classic xref table expected"
    start = match.end()
    count = int(match.group(1))
    entries = [data[start + 20 * i : start + 20 * i + 20] for i in range(count)]
    in_use = [i for i, e in enumerate(entries) if e[17:18] == b"n"]
    victim = in_use[-1] if which == "last" else in_use[0]
    entry = entries[victim]
    shifted = f"{int(entry[:10]) + 3:010d}".encode() + entry[10:]
    pos = start + 20 * victim
    path.write_bytes(data[:pos] + shifted + data[pos + 20 :])
    return victim


@pytest.mark.parametrize("which", ["last", "first"])
def test_a_damaged_file_with_many_free_slots_opens_clean_and_saves_a_readable_file(
    tmp_path, which
) -> None:
    """The census loads objects, so a lazily damaged file can be repaired by MuPDF
    in the middle of the walk; whichever step (compaction or repair) ends up
    installing the document, the session must be memory-backed and clean, and
    Ctrl+S must write a readable, compact file."""
    min_count, _ = _thresholds()
    path = _make_pdf(tmp_path / "grown.pdf", free=2 * min_count)
    _shift_xref_entry(path, which=which)
    before = _sha(path)
    model = _open(path)
    try:
        assert PDFModel._backing_file(model.doc) is None
        assert not model.doc.is_repaired
        assert model.persisted_xref_length is None
        assert PAGE_TEXT in model.doc[0].get_text()
        assert not model.session_has_unsaved_changes(model.get_active_session_id())
        assert _sha(path) == before
        model.save_as(str(path))
        _, free, text, repaired = _file_stats(path)
        assert PAGE_TEXT in text and free == 0 and not repaired
    finally:
        model.close()
