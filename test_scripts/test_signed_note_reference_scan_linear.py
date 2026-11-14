from __future__ import annotations

import re
from types import SimpleNamespace

import fitz
import pytest

from model.tools.annotation_tool import AnnotationTool


def _digit_run_work(size: int) -> tuple[int, int]:
    """Count body entries and initial digit visits, without running quadratic regex.

    On digits followed by `` x``, every admitted start greedily consumes the
    remaining run before the whitespace fails. Summing those suffix lengths is
    a lower bound on engine work. Evaluate the actual pattern's leading guard
    at every position; pin the body so this model cannot silently go stale.
    """
    prefix, separator, body = AnnotationTool._RE_INDIRECT_REF.pattern.partition(r"(\d+)")
    assert separator and body == r"\s+\d+\s+R(?![A-Za-z0-9])"
    entry = re.compile(prefix + r"(?=\d)")
    text = "1" * size + " x"
    starts = [pos for pos in range(size) if entry.match(text, pos)]
    return len(starts), sum(size - pos for pos in starts)


def test_signed_note_reference_scan_has_linear_digit_work() -> None:
    small = _digit_run_work(256)
    large = _digit_run_work(512)
    assert (small, large) == ((1, 256), (1, 512)), (
        f"digit-body attempts/work: n=256 {small}, n=512 {large}"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        ("<< /A 12 0 R /B [3 65535 R] >>", ["12", "3"]),
        ("(12 0 R) /Name7 0 R x8 0 R", ["12", "7", "8"]),
        ("[10\t0\r\nR 11   2 R]", ["10", "11"]),
        ("1 0 RG 2 0 Rx 3 0 R9 4 0 R/Next", ["4"]),
        ("5 6 7 0 R", ["7"]),
        ("(1234567890 0 R)", ["1234567890"]),
        ("(１２ 0 R)", ["１２"]),
    ],
)
def test_reference_results_preserved(text: str, expected: list[str]) -> None:
    assert AnnotationTool._RE_INDIRECT_REF.findall(text) == expected


@pytest.mark.parametrize("tail", [" x", " 0 X", " 0 R9"])
def test_malformed_digit_run_has_no_reference(tail: str) -> None:
    assert AnnotationTool._RE_INDIRECT_REF.findall("1" * 4096 + tail) == []


@pytest.mark.parametrize("container_type", ["ObjStm", "XRef"])
def test_signed_note_traversal_preserves_protected_objects(container_type: str) -> None:
    # A real MuPDF graph, including refs embedded in /Contents. Only the model's
    # opened-file watermark is supplied; reachability and writes are real.
    with fitz.open() as doc:
        page = doc.new_page()

        def add(source: str) -> int:
            xref = doc.get_new_xref()
            doc.update_object(xref, source)
            return xref

        saved = add("<< /Keep (signed revision) >>")
        floor = doc.xref_length()
        shared = add("<< /Keep (reachable) >>")
        doc.xref_set_key(page.xref, "Shared", f"{shared} 0 R")
        container = add(f"<< /Type /{container_type} /Keep (container) >>")
        leaf = add("<< /Secret (embedded reference target) >>")
        stream = add("<< >>")
        doc.update_stream(stream, b"private appearance")
        root = add(
            f"<< /Contents ({'1' * 4096} x {leaf} 0 R) "
            f"/AP {stream} 0 R /Old {saved} 0 R /Shared {shared} 0 R "
            f"/Container {container} 0 R >>"
        )
        tool = AnnotationTool(SimpleNamespace(opened_xref_length=floor))
        protected = {xref: doc.xref_object(xref) for xref in (saved, shared, container)}
        assert tool._null_unsaved_note_objects(doc, []) == []
        assert tool._null_unsaved_note_objects(doc, [saved]) == []
        assert tool._null_unsaved_note_objects(doc, [root]) == sorted([root, leaf, stream])
        for xref in (root, leaf):
            assert doc.xref_object(xref, compressed=True) == "<<>>"
        assert doc.xref_is_stream(stream)
        assert doc.xref_stream(stream) == b""
        assert protected == {xref: doc.xref_object(xref) for xref in protected}
