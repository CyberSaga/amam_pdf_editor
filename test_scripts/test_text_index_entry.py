"""Card A6.3: the pure/install halves of the text index and the entry JSON round trip (Qt-free)."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import fitz
import pytest

from model import text_block
from model.text_block import (
    PageIndexEntry,
    TextBlockManager,
    extract_page_entry,
    page_entry_from_json,
    page_entry_to_json,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _text_doc(rotation: int = 0) -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "Hello world, plain text line", fontsize=12.5)
    page.insert_text((72, 130), "Second line of the paragraph", fontsize=12.5, color=(0.2, 0.4, 0.6))
    page.insert_text((72, 300), "Another block far below", fontsize=9.25, fontname="tiro")
    if rotation:
        page.set_rotation(rotation)
    return doc


def _cjk_doc() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((72, 100), "你好，世界 PDF 編輯器", fontsize=14, fontname="china-t")
    page.insert_text((72, 140), "日本語のテキスト", fontsize=14, fontname="japan")
    return doc


def _bullet_doc() -> fitz.Document:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(72, 72, 400, 400),
        "• first bullet item that is long enough to wrap onto a second line of text\n"
        "• second bullet\n1. numbered item\nA plain wrapped paragraph that continues for a while and wraps.",
        fontsize=11,
    )
    return doc


def _open_or_skip(rel: str) -> fitz.Document:
    path = REPO_ROOT / rel
    if not path.exists():
        pytest.skip(f"{rel} not present")
    return fitz.open(str(path))


CASES = {
    "text": lambda: (_text_doc(), 0),
    "rot90": lambda: (_text_doc(90), 0),
    "rot180": lambda: (_text_doc(180), 0),
    "rot270": lambda: (_text_doc(270), 0),
    "rot0_explicit": lambda: (_text_doc(0), 0),
    "cjk": lambda: (_cjk_doc(), 0),
    "bullets": lambda: (_bullet_doc(), 0),
    "cad": lambda: (_open_or_skip("test_files/cad_vector/before.pdf"), 1),
    "hvac": lambda: (_open_or_skip("test_files/hvac-dwg.pdf"), 1),
}


def _strict_equal(a, b, path="") -> None:
    assert type(a) is type(b), f"{path}: {type(a).__name__} != {type(b).__name__}"
    if dataclasses.is_dataclass(a):
        for f in dataclasses.fields(a):
            _strict_equal(getattr(a, f.name), getattr(b, f.name), f"{path}.{f.name}")
    elif isinstance(a, dict):
        assert list(a) == list(b), path
        for k in a:
            _strict_equal(a[k], b[k], f"{path}[{k!r}]")
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)):
            _strict_equal(x, y, f"{path}[{i}]")
    else:
        assert a == b, f"{path}: {a!r} != {b!r}"
        if isinstance(a, float):
            assert repr(a) == repr(b), path


def _stores(mgr: TextBlockManager, page: int) -> dict:
    return {name: getattr(mgr, name)[page] for name in text_block._PAGE_STORES} | {
        "state": mgr.page_state(page)
    }


@pytest.mark.parametrize("case", list(CASES))
def test_install_of_round_tripped_entry_equals_build_page_index(case):
    doc, page_no = CASES[case]()
    with doc:
        page_idx = page_no - 1 if case in ("cad", "hvac") else page_no
        page_idx = max(page_idx, 0)
        built = TextBlockManager()
        built._build_page_index(page_idx, doc[page_idx])

        entry = extract_page_entry(page_idx, doc[page_idx])
        wire = json.loads(json.dumps(page_entry_to_json(entry)))
        installed = TextBlockManager()
        installed.install_page_entry(page_idx, page_entry_from_json(wire))

    _strict_equal(_stores(installed, page_idx), _stores(built, page_idx), case)
    assert installed.page_state(page_idx) == "clean"


def test_text_pages_are_not_trivially_empty():
    with _text_doc() as doc:
        entry = extract_page_entry(0, doc[0])
    assert isinstance(entry, PageIndexEntry)
    assert entry.blocks and entry.spans and entry.paragraphs and entry.fallback_rows and entry.plain_lines
    assert entry.run_map


def test_extract_does_not_touch_a_manager():
    with _text_doc() as doc:
        extract_page_entry(0, doc[0])
    assert TextBlockManager().page_state(0) == "missing"


def test_entry_is_frozen():
    with _text_doc() as doc:
        entry = extract_page_entry(0, doc[0])
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry.blocks = ()  # type: ignore[misc]


def test_json_rebuilds_geometry_and_tuples():
    with _text_doc() as doc:
        entry = page_entry_from_json(json.loads(json.dumps(page_entry_to_json(extract_page_entry(0, doc[0])))))
    span = entry.spans[0]
    assert isinstance(span.bbox, fitz.Rect) and isinstance(span.origin, fitz.Point)
    assert isinstance(span.color, tuple) and isinstance(span.dir_vec, tuple)
    assert isinstance(entry.paragraphs[0].run_ids, list)
    assert isinstance(entry.blocks[0].rect, fitz.Rect) and isinstance(entry.blocks[0].color, tuple)
    assert isinstance(entry.fallback_rows[0].bbox, tuple)


def test_json_is_declaration_ordered_and_omits_is_vertical():
    with _text_doc(90) as doc:
        wire = page_entry_to_json(extract_page_entry(0, doc[0]))
    block = wire["blocks"][0]
    assert "is_vertical" not in block
    assert list(block)[:3] == ["block_id", "page_num", "rect"]
    assert list(wire["spans"][0])[0] == "span_id"


def test_to_json_fails_loudly_on_an_unknown_field(monkeypatch):
    with _text_doc() as doc:
        entry = extract_page_entry(0, doc[0])

    @dataclasses.dataclass
    class Extra(type(entry.spans[0])):  # type: ignore[misc]
        surprise: int = 1

    base = entry.spans[0]
    extra = Extra(**{f.name: getattr(base, f.name) for f in dataclasses.fields(base)})
    bad = dataclasses.replace(entry, spans=(extra,))
    with pytest.raises(ValueError):
        page_entry_to_json(bad)


def test_from_json_rejects_a_missing_or_extra_key():
    with _text_doc() as doc:
        wire = page_entry_to_json(extract_page_entry(0, doc[0]))
    wire["spans"][0]["surprise"] = 1
    with pytest.raises((ValueError, KeyError, TypeError)):
        page_entry_from_json(wire)


# ---- Astra A6.3 review: untrusted answers, atomic install, independent expectations ----


def _wire(page: int = 0) -> dict:
    with _text_doc() as doc:
        return json.loads(json.dumps(page_entry_to_json(extract_page_entry(page, doc[0]))))


def _untouched(mgr: TextBlockManager, page: int) -> None:
    for name in text_block._PAGE_STORES:
        assert page not in getattr(mgr, name), name
    assert mgr.page_state(page) == "missing"


def test_other_pages_entry_is_refused_and_leaves_the_manager_untouched():
    with _text_doc() as doc:
        entry = extract_page_entry(7, doc[0])
    mgr = TextBlockManager()
    with pytest.raises(ValueError):
        mgr.install_page_entry(0, entry)
    _untouched(mgr, 0)
    _untouched(mgr, 7)


def test_astra_input_infinity_size_and_string_plain_lines_never_become_clean():
    wire = _wire(7)
    wire["spans"][0]["size"] = float("inf")
    wire["plain_lines"] = "abc"
    text = json.dumps(wire)  # json.dumps emits Infinity; json.loads accepts it
    mgr = TextBlockManager()
    with pytest.raises(ValueError):
        mgr.install_page_entry(0, page_entry_from_json(json.loads(text)))
    _untouched(mgr, 0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda w: w["spans"][0].__setitem__("size", float("nan")),
        lambda w: w["spans"][0].__setitem__("size", "12"),
        lambda w: w["spans"][0].__setitem__("size", True),
        lambda w: w["spans"][0].__setitem__("rotation", 1.5),
        lambda w: w["spans"][0].__setitem__("bbox", [0.0, 0.0, 1.0]),
        lambda w: w["spans"][0].__setitem__("origin", [0.0, 0.0, 1.0]),
        lambda w: w["spans"][0].__setitem__("bbox", [0.0, 0.0, 1.0, float("inf")]),
        lambda w: w["spans"][0].__setitem__("dir_vec", [1.0]),
        lambda w: w["spans"][0].__setitem__("text", 5),
        lambda w: w["blocks"][0].__setitem__("rect", None),
        lambda w: w["paragraphs"][0].__setitem__("run_ids", "abc"),
        lambda w: w["paragraphs"][0].__setitem__("run_ids", [1]),
        lambda w: w["fallback_rows"][0].__setitem__("bbox", [1.0, 2.0]),
        lambda w: w.__setitem__("plain_lines", "abc"),
        lambda w: w.__setitem__("plain_lines", [1]),
        lambda w: w.__setitem__("run_map", {"a": 1}),
        lambda w: w.__setitem__("run_map", []),
        lambda w: w.__setitem__("blocks", None),
        lambda w: w["spans"][0].pop("size"),
    ],
)
def test_decoder_refuses_malformed_values(mutate):
    wire = _wire()
    mutate(wire)
    with pytest.raises(ValueError):
        page_entry_from_json(wire)


def test_run_map_naming_a_missing_run_or_paragraph_is_refused():
    entry = page_entry_from_json(_wire())
    bad = dataclasses.replace(entry, run_map={"nope": entry.paragraphs[0].paragraph_id})
    mgr = TextBlockManager()
    with pytest.raises(ValueError):
        mgr.install_page_entry(0, bad)
    bad = dataclasses.replace(entry, run_map={entry.spans[0].span_id: "pg0_missing"})
    with pytest.raises(ValueError):
        mgr.install_page_entry(0, bad)
    _untouched(mgr, 0)


def test_key_order_is_irrelevant_on_receipt():
    with _text_doc() as doc:
        entry = extract_page_entry(0, doc[0])
    wire = json.loads(json.dumps(page_entry_to_json(entry), sort_keys=True))
    assert list(wire) != list(page_entry_to_json(entry))
    _strict_equal(page_entry_from_json(wire), entry)


def test_independent_expectations_on_a_multi_run_page():
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 100), "alpha beta", fontsize=12)
        page.insert_text((72, 200), "gamma", fontsize=10)
        entry = extract_page_entry(0, page)
    texts = [s.text for s in entry.spans]
    assert "alpha beta" in " ".join(texts) and "gamma" in texts
    assert len(entry.spans) == len(texts) >= 2
    assert len({s.span_id for s in entry.spans}) == len(entry.spans)
    # Expected map recomputed from the paragraphs alone: every run of a paragraph maps to it.
    expected = {rid: p.paragraph_id for p in entry.paragraphs for rid in p.run_ids}
    assert entry.run_map == expected and expected
    assert set(entry.run_map) <= {s.span_id for s in entry.spans}
    assert {p.paragraph_id for p in entry.paragraphs} == set(entry.run_map.values())
    assert [b.text for b in entry.blocks] == [r.text for r in entry.fallback_rows]


def test_a_failure_inside_extract_leaves_the_stores_untouched(monkeypatch):
    mgr = TextBlockManager()
    with _text_doc() as doc:
        mgr._build_page_index(0, doc[0])
        before = {n: dict(getattr(mgr, n)) for n in text_block._PAGE_STORES}

        def boom(*_a, **_k):
            raise RuntimeError("boom")

        monkeypatch.setattr(text_block._tbp, "_build_paragraphs", boom)
        with pytest.raises(RuntimeError):
            mgr._build_page_index(0, doc[0])
    for name, snap in before.items():
        assert getattr(mgr, name) == snap
    assert mgr.page_state(0) == "clean"