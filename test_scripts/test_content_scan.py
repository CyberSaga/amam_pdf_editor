"""Card A5: ``model/content_scan.py`` is a pure, cached, derivable scan of a decoded stream (H17, H18)."""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from model import content_scan, pdf_content_ops
from model.content_scan import (
    DoRecord,
    clear_scan_cache,
    content_key,
    iter_token_spans,
    scan_stream,
)
from model.object_requests import DeleteObjectRequest, MoveObjectRequest, ResizeObjectRequest, RotateObjectRequest
from model.pdf_content_ops import (
    _CONTENT_OPERATORS,
    ContentToken,
    ParsedOperator,
    parse_operators,
    tokenize_content_stream,
)
from model.pdf_model import PDFModel

ROOT = Path(__file__).resolve().parent.parent


# ---- references: copies of the code the scanner replaces, kept here verbatim --------------------


def _reference_tokens(stream: bytes) -> list[bytes]:
    ws = b" \t\r\n\x0c\x00"
    delim = b"()<>[]{}/%"
    tokens: list[bytes] = []
    i = 0
    n = len(stream)
    while i < n:
        c = stream[i]
        if c in ws:
            i += 1
            continue
        if c == ord("%"):
            i += 1
            while i < n and stream[i] not in (ord("\r"), ord("\n")):
                i += 1
            continue
        if c == ord("/"):
            s = i
            i += 1
            while i < n and stream[i] not in ws and stream[i] not in delim:
                i += 1
            tokens.append(stream[s:i])
            continue
        if c == ord("("):
            s = i
            i += 1
            depth = 1
            while i < n and depth > 0:
                b = stream[i]
                if b == ord("\\"):
                    i += 2
                    continue
                if b == ord("("):
                    depth += 1
                elif b == ord(")"):
                    depth -= 1
                i += 1
            tokens.append(stream[s:i])
            continue
        if c == ord("<"):
            s = i
            if i + 1 < n and stream[i + 1] == ord("<"):
                tokens.append(b"<<")
                i += 2
                continue
            i += 1
            while i < n and stream[i] != ord(">"):
                i += 1
            if i < n:
                i += 1
            tokens.append(stream[s:i])
            continue
        if c == ord(">") and i + 1 < n and stream[i + 1] == ord(">"):
            tokens.append(b">>")
            i += 2
            continue
        if c in (ord("["), ord("]"), ord("{"), ord("}")):
            tokens.append(stream[i : i + 1])
            i += 1
            continue
        s = i
        i += 1
        while i < n and stream[i] not in ws and stream[i] not in delim:
            i += 1
        tokens.append(stream[s:i])
    return tokens


def _cm_values(operands: tuple[ContentToken, ...]):
    if len(operands) < 6:
        return None
    try:
        return tuple(float(t.raw.decode("latin-1")) for t in operands[-6:])
    except Exception:
        return None


def _reference_dos(stream: bytes) -> tuple[int, list[DoRecord]]:
    """Today's ``discover_native_image_invocations`` loop and ``_q_bounds_by_operator_index``,
    with spans taken from the token offsets."""
    tokens, operators = parse_operators(stream)
    spans = list(iter_token_spans(stream))
    assert [stream[a:b] for a, b in spans] == [t.raw for t in tokens]
    q_to_end: dict[int, int | None] = {}
    counts: dict[int, int] = {}
    stack: list[int] = []
    for op_index, op in enumerate(operators):
        if op.name == "q":
            stack.append(op_index)
            q_to_end[op_index] = None
            counts[op_index] = 0
        elif op.name == "Q":
            if stack:
                q_to_end[stack.pop()] = op_index
        elif op.name == "Do" and stack:
            for q in stack:
                counts[q] += 1
    last_cm: list[int | None] = [None]
    q_stack: list[int] = []
    records: list[DoRecord] = []

    def first(op: ParsedOperator) -> int:
        return spans[op.operand_start][0]

    for op_index, op in enumerate(operators):
        if op.name == "q":
            q_stack.append(op_index)
            last_cm.append(None)
            continue
        if op.name == "Q":
            if q_stack:
                q_stack.pop()
            if len(last_cm) > 1:
                last_cm.pop()
            continue
        if op.name == "cm":
            last_cm[-1] = op_index
            continue
        if op.name != "Do":
            continue
        name = op.operands[-1].raw.decode("latin-1").lstrip("/") if op.operands else ""
        cm_index = last_cm[-1]
        q_index = q_stack[-1] if q_stack else None
        q_end = q_to_end.get(q_index) if q_index is not None else None
        cm_op = operators[cm_index] if cm_index is not None else None
        records.append(
            DoRecord(
                name=name,
                do_operator_index=op_index,
                do_span=(first(op), spans[op.operator_index][1]),
                cm_operator_index=cm_index,
                cm_span=None if cm_op is None else (first(cm_op), spans[cm_op.operator_index][0]),
                cm_values=None if cm_op is None else _cm_values(cm_op.operands),
                q_operator_index=q_index,
                q_end_operator_index=q_end,
                q_span=None
                if q_index is None or q_end is None
                else (first(operators[q_index]), spans[operators[q_end].operator_index][1]),
                q_do_count=counts.get(q_index, 0) if q_index is not None else 0,
            )
        )
    return len(operators), records


SYNTHETIC = {
    "plain": b"q 100 0 0 70 20 150 cm /Im0 Do Q",
    "nested": b"q q 1 0 0 1 5 5 cm /A Do Q 1 0 0 1 7 7 cm /B Do Q",
    "shared_cm": b"q 10 0 0 10 1 1 cm /A Do /B Do /A Do Q",
    "no_cm": b"q /Im0 Do Q /Im1 Do",
    "unclosed_q": b"q 1 0 0 1 0 0 cm /A Do q /B Do",
    "unbalanced_Q": b"Q Q 1 0 0 1 0 0 cm /A Do",
    "strings_comments": b"q (a Do q) Tj % /X Do\n<4446> Tj [(Do)] TJ 1 0 0 1 0 0 cm /A Do Q",
    "cm_garbage": b"1 0 0 abc 0 0 cm /A Do 1 2 cm /B Do",
    "no_operand_do": b"Do q Do Q",
    "dict_operand": b"/X <</K 1>> BDC 1 0 0 1 0 0 cm /A Do EMC",
    "slashes": b"1 0 0 1 0 0 cm //A Do",
    "truncated_string": b"1 0 0 1 0 0 cm /A Do (abc \\",
    "empty": b"",
}


@pytest.mark.parametrize("name", sorted(SYNTHETIC))
def test_scan_equals_reference_on_synthetic_streams(name):
    stream = SYNTHETIC[name]
    operator_count, records = _reference_dos(stream)
    scan = scan_stream(stream)
    assert scan.length == len(stream)
    assert scan.operator_count == operator_count
    assert list(scan.dos) == records


@pytest.mark.parametrize("name", sorted(SYNTHETIC))
def test_tokenize_content_stream_is_unchanged(name):
    stream = SYNTHETIC[name]
    assert [t.raw for t in tokenize_content_stream(stream)] == _reference_tokens(stream)


def test_content_operators_are_shared_with_content_ops():
    assert _CONTENT_OPERATORS is content_scan._CONTENT_OPERATORS


def _fixture_streams() -> list[tuple[str, bytes]]:
    streams: list[tuple[str, bytes]] = []
    for path in sorted((ROOT / "test_files").glob("*.pdf"))[:40]:
        try:
            doc = fitz.open(path)
        except Exception:
            continue
        with doc:
            for page in doc:
                if not page.get_images(full=True):
                    continue
                for xref in page.get_contents():
                    streams.append((f"{path.name}:{xref}", doc.xref_stream(int(xref)) or b""))
                for xobj in page.get_xobjects():
                    try:
                        if doc.xref_get_key(int(xobj[0]), "Subtype")[1] == "/Form":
                            streams.append((f"{path.name}:form{xobj[0]}", doc.xref_stream(int(xobj[0])) or b""))
                    except Exception:
                        continue
                break
    return streams


def test_scan_equals_reference_on_fixture_streams():
    streams = [s for s in _fixture_streams() if len(s[1]) < 400_000]
    if not streams:
        pytest.skip("no image-bearing fixture pages")
    for label, stream in streams:
        operator_count, records = _reference_dos(stream)
        scan = scan_stream(stream)
        assert (scan.operator_count, list(scan.dos)) == (operator_count, records), label


# ---- derive_* after every edit scenario --------------------------------------------------------


def _png(rgb=(255, 0, 0)) -> bytes:
    pix = fitz.Pixmap(fitz.csRGB, (0, 0, 8, 8), 0)
    pix.clear_with(rgb[0])
    return pix.tobytes("png")


_SCENARIOS = {
    "q_block": "q 100 0 0 70 20 150 cm /{a} Do Q",
    "bare_do_shared_cm": "100 0 0 70 20 150 cm /{a} Do",
    "two_in_one_q": "q 100 0 0 70 20 150 cm /{a} Do /{b} Do Q",
    "nested": "q q 100 0 0 70 20 150 cm /{a} Do Q 100 0 0 70 150 120 cm /{b} Do Q",
    "text_in_q": "q BT /helv 12 Tf 40 200 Td (K) Tj ET 100 0 0 70 20 150 cm /{a} Do Q",
}


def _open_scenario(tmp_path, key: str) -> tuple[PDFModel, int]:
    doc = fitz.open()
    page = doc.new_page(width=320, height=240)
    page.insert_image(fitz.Rect(20, 20, 120, 90), stream=_png((255, 0, 0)))
    page.insert_image(fitz.Rect(150, 120, 250, 190), stream=_png((0, 255, 0)))
    page.insert_text(fitz.Point(40, 230), "x", fontsize=12, fontname="helv")
    names = [str(i[7]) for i in page.get_images(full=True)]
    xrefs = [int(x) for x in page.get_contents()]
    doc.update_stream(xrefs[0], _SCENARIOS[key].format(a=names[0], b=names[1]).encode("ascii"))
    for extra in xrefs[1:]:
        doc.update_stream(extra, b" ")
    path = tmp_path / f"{key}.pdf"
    doc.save(path)
    doc.close()
    model = PDFModel()
    model.open_pdf(str(path))
    return model, xrefs[0]


def _assert_derived_cache(model: PDFModel, xref: int) -> None:
    stream = model.doc.xref_stream(xref)
    derived = content_scan.cached_scan(content_key(stream))
    assert derived is not None, "the edit stored no derived scan"
    assert derived == scan_stream(stream)


@pytest.mark.parametrize("key", sorted(_SCENARIOS))
@pytest.mark.parametrize("verb", ["move", "resize", "rotate_delta", "rotate_abs", "delete"])
def test_derived_scan_equals_scan_of_the_new_bytes(tmp_path, key, verb):
    model, xref = _open_scenario(tmp_path, key)
    try:
        hit = model.get_object_info_at_point(1, fitz.Point(70, 55))
        assert hit is not None and hit.object_kind == "native_image"
        clear_scan_cache()
        if verb == "move":
            ok = model.move_object(MoveObjectRequest(hit.object_id, hit.object_kind, 1, 1, fitz.Rect(30, 40, 130, 110)))
        elif verb == "resize":
            ok = model.resize_object(ResizeObjectRequest(hit.object_id, hit.object_kind, 1, fitz.Rect(20, 20, 160, 120)))
        elif verb == "rotate_delta":
            ok = model.rotate_object(RotateObjectRequest(hit.object_id, hit.object_kind, 1, 90))
        elif verb == "rotate_abs":
            ok = model.rotate_object(RotateObjectRequest(hit.object_id, hit.object_kind, 1, 0, absolute_rotation=30.0))
        else:
            ok = model.delete_object(DeleteObjectRequest(hit.object_id, hit.object_kind, 1))
        assert ok is True
        _assert_derived_cache(model, xref)
    finally:
        model.close()


# ---- cache -------------------------------------------------------------------------------------


def test_cache_keeps_at_most_the_record_cap_and_evicts_least_recently_used(monkeypatch):
    clear_scan_cache()
    monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 5)
    one = scan_stream(b"/A Do /B Do /C Do")
    assert content_scan.store_scan(b"k1", one) is True
    assert content_scan.store_scan(b"k2", one) is True
    assert content_scan.cached_scan(b"k1") is None  # 6 records > 5: the older one went
    assert content_scan.cached_scan(b"k2") == one
    clear_scan_cache()
    assert content_scan.cached_scan(b"k2") is None


def test_single_scan_over_cap_is_refused_not_kept_alone(monkeypatch):
    clear_scan_cache()
    monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 2)
    small = scan_stream(b"/A Do")
    assert content_scan.store_scan(b"small", small) is True
    big = scan_stream(b"/A Do /B Do /C Do")  # 3 records > 2
    assert content_scan.store_scan(b"big", big) is False
    assert content_scan.cached_scan(b"big") is None
    assert content_scan.cached_scan(b"small") == small  # nothing was evicted for a refused store


def test_a_scan_without_records_still_costs_one(monkeypatch):
    clear_scan_cache()
    monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 2)
    empty = scan_stream(b"0 0 m 1 1 l S")
    assert content_scan.store_scan(b"a", empty) is True
    assert content_scan.store_scan(b"b", empty) is True
    assert content_scan.store_scan(b"c", empty) is True  # 3 > 2: the oldest went
    assert content_scan.cached_scan(b"a") is None


def test_store_with_keep_never_evicts_a_kept_key_and_refuses_when_it_cannot_fit(monkeypatch):
    clear_scan_cache()
    monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 2)
    one = scan_stream(b"/A Do")
    content_scan.store_scan(b"sibling", one)
    content_scan.store_scan(b"other", one)
    assert content_scan.store_scan(b"new", one, keep=frozenset({b"sibling"})) is True
    assert content_scan.cached_scan(b"sibling") == one and content_scan.cached_scan(b"other") is None
    # Both remaining entries are kept: the new one cannot fit and nothing is evicted.
    assert content_scan.store_scan(b"newer", one, keep=frozenset({b"sibling", b"new"})) is False
    assert content_scan.cached_scan(b"sibling") == one and content_scan.cached_scan(b"new") == one


def test_over_cap_set_stores_nothing_and_evicts_nothing(monkeypatch):
    clear_scan_cache()
    monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 3)
    one = scan_stream(b"/A Do")
    content_scan.store_scan(b"x", one)
    members = {b"a": scan_stream(b"/A Do /B Do"), b"b": scan_stream(b"/A Do /B Do")}  # 4 > 3
    assert content_scan.admit_set(members) is False
    assert content_scan.cached_scan(b"a") is None and content_scan.cached_scan(b"b") is None
    assert content_scan.cached_scan(b"x") == one


def test_fitting_set_evicts_other_pages_never_its_own_members(monkeypatch):
    clear_scan_cache()
    monkeypatch.setattr(content_scan, "SCAN_CACHE_MAX_RECORDS", 5)
    two = scan_stream(b"/A Do /B Do")
    content_scan.store_scan(b"member_a", two)  # the oldest entry: a member of the set
    content_scan.store_scan(b"other", scan_stream(b"/A Do /B Do /C Do"))  # 2 + 3 = 5
    assert content_scan.admit_set({b"member_a": two, b"member_b": two}) is True  # 4 <= 5
    assert content_scan.cached_scan(b"member_a") == two
    assert content_scan.cached_scan(b"member_b") == two
    assert content_scan.cached_scan(b"other") is None


def test_failed_sets_are_an_lru_of_max_failed_sets():
    clear_scan_cache()
    keys = [(7, 1, (i.to_bytes(4, "big"),)) for i in range(content_scan.MAX_FAILED_SETS + 1)]
    for generation, page, set_key in keys:
        content_scan.mark_set_failed(generation, page, set_key)
    assert content_scan.set_failed(*keys[0]) is False  # the oldest went
    assert content_scan.set_failed(*keys[1]) is True
    assert content_scan.set_failed(*keys[-1]) is True
    assert len(content_scan._failed_sets) == content_scan.MAX_FAILED_SETS


def test_retire_failed_sets_drops_only_dead_generations():
    clear_scan_cache()
    content_scan.mark_set_failed(1, 1, (b"a",), "crashed")
    content_scan.mark_set_failed(2, 1, (b"a",), "resource_limited")
    content_scan.retire_failed_sets(frozenset({2}))
    assert content_scan.set_failed(1, 1, (b"a",)) is False
    assert content_scan.set_failed(2, 1, (b"a",)) is True
    assert content_scan.failure_reason(2, 1, (b"a",)) == "resource_limited"
    assert content_scan.failure_reason(1, 1, (b"a",)) is None
    content_scan.retire_failed_sets(frozenset())
    assert content_scan._failed_sets == {}


def test_json_round_trip():
    scan = scan_stream(SYNTHETIC["nested"] + b" " + SYNTHETIC["unclosed_q"])
    assert content_scan.from_json(content_scan.to_json(scan)) == scan


# ---- stream_scan, alias ------------------------------------------------------------------------


def _one_stream_doc(data: bytes, dict_extra: str = "") -> tuple[fitz.Document, int]:
    doc = fitz.open()
    doc.new_page()
    xref = doc.get_new_xref()
    doc.update_object(xref, f"<< {dict_extra} >>")
    doc.update_stream(xref, data)
    return doc, xref


def test_stream_scan_decodes_scans_and_caches_by_content():
    clear_scan_cache()
    data = b"q 1 0 0 1 0 0 cm /A Do Q"
    doc, xref = _one_stream_doc(data)
    with doc:
        scan = pdf_content_ops.stream_scan(doc, xref)
        assert scan == scan_stream(data)
        assert content_scan.cached_scan(content_key(data)) == scan


def test_alias_skips_decoding_when_the_dictionary_has_no_reference(monkeypatch):
    clear_scan_cache()
    data = b"q 1 0 0 1 0 0 cm /A Do Q"
    doc, xref = _one_stream_doc(data)
    with doc:
        pdf_content_ops.stream_scan(doc, xref)
        calls = []
        monkeypatch.setattr(content_scan, "scan_stream", lambda s: calls.append(1) or scan_stream(s))
        monkeypatch.setattr(doc.__class__, "xref_stream", lambda self, x: pytest.fail("decoded despite alias"), raising=False)
        assert pdf_content_ops.stream_scan(doc, xref) == scan_stream(data)
        assert calls == []


def test_alias_is_not_used_when_the_dictionary_holds_a_reference():
    assert content_scan.alias_usable("<< /Length 12 >>") is True
    assert content_scan.alias_usable("<< /Length 7 0 R >>") is False
    assert content_scan.alias_usable("<< /Filter /FlateDecode /DecodeParms 12 0 R >>") is False
