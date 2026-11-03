"""The sfnt table directory, read once: ``model/text_commit/sfnt.py`` and the two readers that use it.

Two product readers walk the same TrueType table directory: the simple-font reader (``simple_font_programs``,
``builtin_glyph_proof``, "R1") and the Type0 reader (``cid_fonts.parse_truetype_glyph_program``, "R2").  They used to
disagree four ways (repeated tag, minimum ``head`` length, ``ttcf``, a table past the end of the program); the rulings
in ``plans/archive/sfnt-directory.md`` replace both walks with one.  Every ruling is the measured MuPDF/FreeType behaviour
(or a refusal), so the tests run the SAME shape through BOTH readers and compare with what the loader does.

Shapes are rebuilt from the fixture builders by ``test_scripts/sfnt_variants.py`` (no stored font bytes).  A test
reports every reader/base pair that fails, not just the first.
"""
from __future__ import annotations

import ast
import functools
import gc
import struct
import sys
import types
from pathlib import Path

import fitz
import pytest

from model.text_commit import cid_fonts
from model.text_commit.simple_font_programs import builtin_glyph_proof
from test_scripts import simple_font_fixture_builder as sfb
from test_scripts.sfnt_variants import (
    Entry,
    Variants,
    directory_entries,
    face_fatal_shapes,
    last_word_offset,
    lenient_shapes,
    loca_format_of,
    past_eof_length,
    past_eof_offset,
    type0_program,
    with_loca_format,
    with_num_glyphs,
)

_ROOT = Path(__file__).resolve().parents[1]
_TRUETYPE_KINDS = tuple(kind for kind in sfb.KINDS if kind not in sfb.TYPE1_KINDS)


# ----------------------------------------------------------------------------------------------- readers


def _r1_proof(program: bytes):
    return builtin_glyph_proof(program, "FontFile2")


def r1_facts(program: bytes) -> tuple[int, bool] | None:
    """``(num_glyphs, long loca)`` when the simple-font reader reads the program, else None."""
    proof = _r1_proof(program)
    if proof.program_kind != "truetype":
        return None
    return proof.num_glyphs, bool(proof._impl._long_loca)


def r2_facts(program: bytes) -> tuple[int, bool] | None:
    """``(num_glyphs, long loca)`` when the Type0 reader reads the program, else None."""
    parsed = cid_fonts.parse_truetype_glyph_program(program)
    return None if parsed is None else (parsed.num_glyphs, parsed.index_to_loc_format == 1)


READERS = {"R1": r1_facts, "R2": r2_facts}


@functools.cache
def _bases() -> dict[str, tuple[Variants, int]]:
    """``name -> (variants of the base program, a gid with a real outline)``: a simple-font kind and a Type0 subset."""
    from test_scripts import type0_fixture_builder as t0

    return {
        "simple": (Variants(sfb.build_font_program("winansi")), sfb.glyph_id("A")),
        "type0": (Variants(type0_program()), t0.cid_for(t0.CJK_TEXT[0])),
    }


def _pairs():
    for name, (variants, _gid) in _bases().items():
        for reader_name, reader in READERS.items():
            yield name, variants, reader_name, reader


def _no_failures(failures: list[str]) -> None:
    assert not failures, "\n".join(failures)


# ----------------------------------------------------------------------------------------------- D1: repeated tag


def test_first_in_range_entry_wins():
    """MuPDF reads the FIRST directory entry of a repeated tag (not the last, not the lowest offset): v1a/b/i/j/k/n."""
    failures: list[str] = []
    for name, variants in ((n, v) for n, (v, _g) in _bases().items()):
        real_maxp = variants.table(b"maxp")
        real_head = variants.table(b"head")
        cases = {
            b"maxp": (real_maxp, with_num_glyphs(real_maxp, 2)),
            b"head": (real_head, with_loca_format(real_head, 1 - loca_format_of(real_head))),
        }
        for tag, (real, other) in cases.items():
            for reader_name, reader in READERS.items():
                # the two single-entry programs must read differently, or the test cannot tell first from last
                assert reader(variants.with_table(tag, real)) != reader(variants.with_table(tag, other)), (name, tag)
            for first, last in ((real, other), (other, real)):
                for reader_name, reader in READERS.items():
                    want = reader(variants.with_table(tag, first))
                    got = reader(variants.duplicated(tag, first, last))
                    if got != want:
                        order = "real,other" if first is real else "other,real"
                        failures.append(f"{reader_name}/{name} {tag!r} [{order}]: first entry reads {want}, repeated tag reads {got}")
    # R1 also reads cmap: the first of two cmap entries decides what a code maps to
    right = Variants(sfb.build_font_program("symbolic_mac10"))
    wrong = Variants(sfb.build_font_program("symbolic_mac10_wrongglyph"))
    assert right.table(b"glyf") == wrong.table(b"glyf"), "the two kinds must differ only in the cmap"
    good_cmap, bad_cmap = right.table(b"cmap"), wrong.table(b"cmap")
    assert _r1_proof(right.with_table(b"cmap", good_cmap)).proves(0x41, "A")
    assert not _r1_proof(right.with_table(b"cmap", bad_cmap)).proves(0x41, "A")
    for first, last in ((good_cmap, bad_cmap), (bad_cmap, good_cmap)):
        want = _r1_proof(right.with_table(b"cmap", first)).proves(0x41, "A")
        got = _r1_proof(right.duplicated(b"cmap", first, last)).proves(0x41, "A")
        if got != want:
            failures.append(f"R1/cmap: first entry proves A={want}, repeated tag proves A={got}")
    _no_failures(failures)


def test_a_zero_length_first_glyf_wins():
    """A zero-length FIRST entry wins and the table is empty: MuPDF paints nothing (v1f glyf)."""
    failures: list[str] = []
    for name, (variants, gid) in _bases().items():
        real = variants.table(b"glyf")
        control = cid_fonts.parse_truetype_glyph_program(variants.roundtrip())
        assert control is not None and (control.glyph_data_length(gid) or 0) > 0, name  # the real glyf has an outline
        parsed = cid_fonts.parse_truetype_glyph_program(variants.duplicated(b"glyf", None, real))
        if parsed is not None and parsed.glyph_data_length(gid) is not None:
            failures.append(f"R2/{name}: reads {parsed.glyph_data_length(gid)} outline bytes from a glyf whose first entry is empty")
    simple, _gid = _bases()["simple"]
    assert _r1_proof(simple.roundtrip()).proves(0x41, "A")
    if _r1_proof(simple.duplicated(b"glyf", None, simple.table(b"glyf"))).proves(0x41, "A"):
        failures.append("R1/simple: proves A from a glyf whose first entry is empty")
    _no_failures(failures)


def test_an_out_of_range_first_entry_is_skipped():
    """A first entry past the end of the file is skipped and the next one is used (v1l offset, v1m length)."""
    right = Variants(sfb.build_font_program("symbolic_mac10"))
    wrong = Variants(sfb.build_font_program("symbolic_mac10_wrongglyph"))
    good_cmap, bad_cmap = right.table(b"cmap"), wrong.table(b"cmap")
    failures: list[str] = []
    for label, position in (("offset", past_eof_offset), ("length", past_eof_length)):
        spec = Entry(b"cmap", bad_cmap, **{f"dir_{'off' if label == 'offset' else 'len'}": position})
        proof = _r1_proof(right.duplicated(b"cmap", spec, good_cmap))
        if proof.program_kind != "truetype":
            failures.append(f"R1: a first cmap entry with its {label} past the end makes the program {proof.program_kind}")
        elif not proof.proves(0x41, "A"):
            failures.append(f"R1: a first cmap entry with its {label} past the end was read (A no longer proves)")
    _no_failures(failures)


# ----------------------------------------------------------------------------------------------- D2: head length


def test_head_52_and_53_refuse():
    """``head`` shorter than 54 bytes refuses the face (v2a/v2b directory length, v2c truly truncated); 54 at EOF loads (v2d)."""
    failures: list[str] = []
    for name, variants, reader_name, reader in _pairs():
        assert reader(variants.head_at_eof()) is not None, (name, reader_name)  # v2d control: a 54-byte head at EOF reads
        shapes = {
            "head length 52": variants.modified(b"head", dir_len=52),
            "head length 53": variants.modified(b"head", dir_len=53),
            "head truncated to 52 at EOF": variants.head_truncated_at_eof(52),
        }
        for label, program in shapes.items():
            if reader(program) is not None:
                failures.append(f"{reader_name}/{name}: reads a program with {label}")
    _no_failures(failures)


def test_any_short_head_entry_refuses():
    """A real ``head`` followed by a zero-length ``head`` refuses the face even though the first entry wins (v1g)."""
    failures: list[str] = []
    for name, variants, reader_name, reader in _pairs():
        program = variants.duplicated(b"head", variants.table(b"head"), None)
        if reader(program) is not None:
            failures.append(f"{reader_name}/{name}: reads a program whose second head entry is zero-length")
    _no_failures(failures)


# ----------------------------------------------------------------------------------------------- D4: out of range


def test_hmtx_offset_past_eof_refuses():
    """An ``hmtx`` whose OFFSET is past the end refuses the face ("horizontal metrics (hmtx) table missing", v4o_hmtx)."""
    failures: list[str] = []
    for name, variants, reader_name, reader in _pairs():
        assert reader(variants.roundtrip()) is not None, (name, reader_name)
        if reader(variants.modified(b"hmtx", dir_off=past_eof_offset)) is not None:
            failures.append(f"{reader_name}/{name}: reads a program whose hmtx offset is past the end")
    _no_failures(failures)


def test_hmtx_length_past_eof_is_clipped():
    """An ``hmtx`` whose LENGTH runs past the end is clipped to the end of the file and loads (v4f)."""
    failures: list[str] = []
    for name, (variants, _gid) in _bases().items():
        program = variants.modified(b"hmtx", dir_len=past_eof_length)
        (offset, stated) = next((o, n) for t, o, n in directory_entries(program) if t == b"hmtx")
        assert offset + stated > len(program)
        if r1_facts(program) is None:
            failures.append(f"R1/{name}: refuses a program whose hmtx is merely too long")
        parsed = cid_fonts.parse_truetype_glyph_program(program)
        if parsed is None:
            failures.append(f"R2/{name}: refuses a program whose hmtx is merely too long")
        elif (parsed.hmtx_offset, parsed.hmtx_length) != (offset, (len(program) - offset) & ~3):
            failures.append(
                f"R2/{name}: hmtx slot is ({parsed.hmtx_offset}, {parsed.hmtx_length}), "
                f"want ({offset}, {(len(program) - offset) & ~3})"
            )
    _no_failures(failures)


def test_hmtx_is_clipped_to_whole_words():
    """FreeType clips an overflowing ``hmtx`` to ``(size - offset) & ~3`` ("a multiple of 4"), not to ``size - offset``.

    The 2 bytes it leaves out are not metrics: reading them as the last glyph's side bearing moves its ink box."""
    failures: list[str] = []
    for name, (variants, _gid) in _bases().items():
        program = variants.hmtx_at_eof(2, dir_len=past_eof_length)
        offset = next(o for t, o, _n in directory_entries(program) if t == b"hmtx")
        assert (len(program) - offset) % 4 == 2, name  # the shape tells the two clip rules apart
        assert r1_facts(program) is not None, name
        parsed = cid_fonts.parse_truetype_glyph_program(program)
        if parsed is None:
            failures.append(f"R2/{name}: refuses a program whose hmtx is merely too long")
        elif (parsed.hmtx_offset, parsed.hmtx_length) != (offset, (len(program) - offset) & ~3):
            failures.append(f"R2/{name}: hmtx slot is ({parsed.hmtx_offset}, {parsed.hmtx_length}), want a whole number of words")
    _no_failures(failures)


def test_an_empty_hmtx_refuses_both():
    """A zero-length ``hmtx`` is a missing one ("horizontal metrics (hmtx) table missing"): both readers refuse it."""
    failures: list[str] = []
    for name, variants, reader_name, reader in _pairs():
        for label, program in (
            ("stated length 0", variants.modified(b"hmtx", dir_len=0)),
            ("empty first entry", variants.duplicated(b"hmtx", None, variants.table(b"hmtx"))),
        ):
            if reader(program) is not None:
                failures.append(f"{reader_name}/{name}: reads a program with an empty hmtx ({label})")
    _no_failures(failures)


def test_hmtx_clipped_to_nothing_refuses_both():
    """An ``hmtx`` starting in the last word with an overflowing length clips to 0 bytes: a missing hmtx, which refuses the face."""
    failures: list[str] = []
    for name, variants, reader_name, reader in _pairs():
        program = variants.hmtx_at_eof(0, dir_off=last_word_offset, dir_len=past_eof_length)
        if reader(program) is not None:
            failures.append(f"{reader_name}/{name}: reads a program whose hmtx clips to zero bytes")
    _no_failures(failures)


def test_out_of_range_cmap_and_post_are_absent():
    """R1: a ``cmap`` or ``post`` past the end is ABSENT, as MuPDF treats it (v4c/v4k cmap, v4a/v4j post), not a refusal."""
    variants, _gid = _bases()["simple"]
    failures: list[str] = []
    for label, field in (("offset", "dir_off"), ("length", "dir_len")):
        value = past_eof_offset if label == "offset" else past_eof_length
        cmap_gone = _r1_proof(variants.modified(b"cmap", **{field: value}))
        if cmap_gone.program_kind != "truetype":
            failures.append(f"R1: cmap {label} past the end makes the program {cmap_gone.program_kind}")
        elif any(cmap_gone.present(code) for code in range(256)):
            failures.append(f"R1: cmap {label} past the end still maps a code")
        post_gone = _r1_proof(variants.modified(b"post", **{field: value}))
        if post_gone.program_kind != "truetype":
            failures.append(f"R1: post {label} past the end makes the program {post_gone.program_kind}")
        else:
            if post_gone._impl.has_names:
                failures.append(f"R1: post {label} past the end still names glyphs")
            if not post_gone.proves(0x41, "A"):
                failures.append(f"R1: post {label} past the end: A no longer proves through (3,1) and its outline")
        # the Type0 reader never reads cmap or post: unchanged
        if r2_facts(variants.modified(b"post", **{field: value})) is None:
            failures.append(f"R2: post {label} past the end is refused")
    _no_failures(failures)


# ----------------------------------------------------------------------------------------------- D3: ttcf


def test_ttcf_is_refused_by_both():
    """A TrueType collection is refused by both readers (the member-relative shape is the control the Type0 reader took)."""
    failures: list[str] = []
    for name, variants, reader_name, reader in _pairs():
        shapes = {
            "member-relative offsets": variants.ttcf_member_relative(),
            "file-absolute offsets, one member": variants.ttcf_file_absolute(1),
            "file-absolute offsets, two members": variants.ttcf_file_absolute(2),
        }
        for label, program in shapes.items():
            assert program[:4] == b"ttcf"
            if reader(program) is not None:
                failures.append(f"{reader_name}/{name}: reads a ttcf collection ({label})")
    _no_failures(failures)


# ----------------------------------------------------------------------------------------------- edge inputs (refactor guards)


def _directory_only(count: int, entries: int) -> bytes:
    """A 12-byte header claiming ``count`` tables followed by ``entries`` all-zero directory entries."""
    return b"\x00\x01\x00\x00" + count.to_bytes(2, "big") + b"\x00" * 6 + b"\x00" * (16 * entries)


EDGE_INPUTS = {
    "empty": b"",
    "11 bytes": b"\x00\x01\x00\x00" + b"\x00" * 7,
    "numTables 0": _directory_only(0, 0),
    "directory ends exactly at EOF": _directory_only(2, 2),
    "directory claims more entries than the file holds": _directory_only(3, 2),
    "CFF container tag": b"OTTO" + _directory_only(0, 0)[4:],
}


@pytest.mark.parametrize("label", list(EDGE_INPUTS))
def test_edge_inputs_are_refused_by_both(label):
    program = EDGE_INPUTS[label]
    assert r1_facts(program) is None, label
    assert r2_facts(program) is None, label


# ----------------------------------------------------------------------------------------------- the module is stdlib-only


def _imports(path: Path) -> list[tuple[str, tuple[str, ...]]]:
    """``(module, imported names)`` of every import statement in ``path`` (``from . import x`` has module ``"."``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(alias.name, ()) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            found.append(("." * node.level + (node.module or ""), tuple(alias.name for alias in node.names)))
    return found


def test_sfnt_is_fitz_and_fonttools_free():
    """``sfnt.py`` is stdlib-only; ``simple_font_programs.py`` imports nothing from the project but ``sfnt``."""
    sfnt_path = _ROOT / "model" / "text_commit" / "sfnt.py"
    assert sfnt_path.is_file(), "model/text_commit/sfnt.py does not exist"
    sfp_path = _ROOT / "model" / "text_commit" / "simple_font_programs.py"
    offenders: list[str] = []
    for path, project_ok in ((sfnt_path, False), (sfp_path, True)):
        for module, names in _imports(path):
            root = module.split(".")[0]
            if root in sys.stdlib_module_names:
                continue
            if project_ok and (module == "model.text_commit.sfnt" or (module == "model.text_commit" and names == ("sfnt",))):
                continue
            offenders.append(f"{path.name}: imports {module} {names}")
    _no_failures(offenders)


# ----------------------------------------------------------------------------------------------- release the program


def _holds(root: object, target: object) -> str | None:
    """A description of the first reference path from ``root`` to ``target``; None when ``root`` cannot reach it.

    Walks containers, instance dicts / slots, closure cells, defaults and bound methods.  It never enters a module, a
    class, a code object or a function's globals (that would reach every module the process has loaded)."""
    seen: set[int] = set()
    stack: list[tuple[object, str]] = [(root, type(root).__name__)]
    while stack:
        obj, path = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        if obj is target:
            return path
        if isinstance(obj, (types.ModuleType, type, types.CodeType, str, bytes, int, float, bool, type(None))):
            continue
        if isinstance(obj, types.FunctionType):
            children = [(cell, f"{path}.__closure__") for cell in obj.__closure__ or ()]
            children += [(value, f"{path}.__defaults__") for value in obj.__defaults__ or ()]
        elif isinstance(obj, types.CellType):
            try:
                children = [(obj.cell_contents, f"{path}[cell]")]
            except ValueError:  # an empty cell
                children = []
        elif isinstance(obj, types.MethodType):
            children = [(obj.__self__, f"{path}.__self__"), (obj.__func__, f"{path}.__func__")]
        else:
            children = [(child, f"{path}>{type(child).__name__}") for child in gc.get_referents(obj)]
        stack.extend(children)
    return None


def test_a_truetype_proof_keeps_no_reference_to_the_program():
    """After the proof is built nothing it holds (tables, closures, memo) may still point at the font program bytes."""
    program = sfb.build_font_program("winansi")
    assert len(program) < 1 << 20
    proof = _r1_proof(program)
    assert proof.program_kind == "truetype"
    for code in range(0x20, 0x7F):  # exercise the lazy memos: names, outlines, lookups
        proof.present(code)
        proof.proves(code, chr(code))
    assert _holds(proof, program) is None, f"the proof still reaches the program bytes via {_holds(proof, program)}"


# ----------------------------------------------------------------------------------------------- anchors (green from the start)


@pytest.fixture
def quiet_mupdf():
    fitz.TOOLS.mupdf_display_errors(False)
    try:
        yield
    finally:
        fitz.TOOLS.mupdf_display_errors(True)


_SIMPLE = Variants(sfb.build_font_program("winansi"))
#: ``name -> (program, does the pinned loader load it)``: the control, the shapes the rulings refuse, the shapes they keep
_LOADER_CASES = {
    "control": (_SIMPLE.roundtrip(), True),
    **{shape.name: (shape.data, False) for shape in face_fatal_shapes(_SIMPLE)},
    **{shape.name: (shape.data, True) for shape in lenient_shapes(_SIMPLE)},
}


def _loads(program: bytes) -> bool:
    try:
        fitz.Font(fontbuffer=program)
    except Exception:  # noqa: BLE001 - the loader raises RuntimeError for a face it refuses
        return False
    return True


@pytest.mark.parametrize("name", list(_LOADER_CASES))
def test_face_fatal_rules_match_freetype(name, quiet_mupdf):
    """The directory shapes the rulings REFUSE are the ones the pinned PyMuPDF 1.27 loader raises on; the rest load.

    Anchors the rulings to the loader.  The reader half, "sfnt refuses exactly these", is
    ``test_sfnt_refuses_exactly_the_face_fatal_shapes`` below."""
    program, loads = _LOADER_CASES[name]
    assert _loads(program) is loads, f"fitz.Font {'refused' if loads else 'loaded'} the shape {name}"


@pytest.mark.parametrize("source", [*_TRUETYPE_KINDS, "type0_subset"])
def test_readers_agree_on_shared_facts(source):
    """On every fixture the two readers agree on glyph count, loca format and the glyf slot."""
    program = type0_program() if source == "type0_subset" else sfb.build_font_program(source)
    proof = _r1_proof(program)
    parsed = cid_fonts.parse_truetype_glyph_program(program)
    assert proof.program_kind == "truetype" and parsed is not None
    tables = _sfnt().read_glyph_tables(program)  # R1 keeps the glyf slot only inside its construction-time outline pass
    assert (proof.num_glyphs, proof._impl._long_loca, (tables.glyf.offset, tables.glyf.length)) == (
        parsed.num_glyphs,
        parsed.index_to_loc_format == 1,
        (parsed.glyf_offset, parsed.glyf_length),
    )


# ----------------------------------------------------------------------------------------------- sfnt.py itself (unit level)


def _sfnt():
    """``model.text_commit.sfnt``, imported inside each test so one missing module reddens only the tests that need it."""
    from model.text_commit import sfnt

    return sfnt


#: ``shape name -> (reason read_directory raises | None, reason read_glyph_tables raises | None, tag that must be dropped | None)``
_SFNT_RULES = {
    "head_len_52": ("head", "head", None),
    "head_len_53": ("head", "head", None),
    "head_truncated_52_at_eof": ("head", "head", None),
    "head_dup_zero_last": ("head", "head", None),
    "head_dup_zero_first": ("head", "head", None),
    "head_length_past_eof": ("head", "head", None),
    "head_offset_past_eof": ("head", "head", None),
    "loca_length_past_eof": (None, "required_table_missing", b"loca"),
    "loca_offset_past_eof": (None, "required_table_missing", b"loca"),
    "hmtx_offset_past_eof": ("hmtx_out_of_range", "hmtx_out_of_range", None),
    "hmtx_length_zero": ("hmtx_empty", "hmtx_empty", None),
    "hmtx_dup_zero_first": ("hmtx_empty", "hmtx_empty", None),
    "hmtx_last_word_length_past_eof": ("hmtx_out_of_range", "hmtx_out_of_range", None),
    "head_54_at_eof": (None, None, None),
    "post_length_past_eof": (None, None, b"post"),
    "post_offset_past_eof": (None, None, b"post"),
    "name_length_past_eof": (None, None, b"name"),
    "name_offset_past_eof": (None, None, b"name"),
    "os2_length_past_eof": (None, None, b"OS/2"),
    "os2_offset_past_eof": (None, None, b"OS/2"),
    "hmtx_length_past_eof": (None, None, None),
    "hmtx_unaligned_length_past_eof": (None, None, None),
    "glyf_length_past_eof": (None, "required_table_missing", b"glyf"),
    "glyf_offset_past_eof": (None, "required_table_missing", b"glyf"),
    "maxp_length_past_eof": (None, "required_table_missing", b"maxp"),
    "maxp_offset_past_eof": (None, "required_table_missing", b"maxp"),
    "cmap_length_past_eof": (None, None, b"cmap"),
    "cmap_offset_past_eof": (None, None, b"cmap"),
}


def _raised(function, program: bytes) -> str | None:
    """The ``SfntError.reason`` ``function(program)`` raises, or None when it returns."""
    try:
        function(program)
    except _sfnt().SfntError as error:
        return error.reason
    return None


def test_sfnt_rules_cover_every_loader_shape():
    """The table above names every shape of ``face_fatal_shapes`` / ``lenient_shapes`` (a new shape cannot be forgotten)."""
    shapes = {shape.name for shape in (*face_fatal_shapes(_SIMPLE), *lenient_shapes(_SIMPLE))}
    assert shapes == set(_SFNT_RULES)


@pytest.mark.parametrize("name", list(_SFNT_RULES))
def test_sfnt_refuses_exactly_the_face_fatal_shapes(name):
    """The reader half of ``test_face_fatal_rules_match_freetype``: sfnt refuses what the loader raises on, and no more.

    glyf / maxp / loca / cmap out of range are DROPPED by ``read_directory``; ``read_glyph_tables`` then refuses the
    three tables a glyph proof needs (a cmap is optional for the directory)."""
    sfnt = _sfnt()
    shape = next(s for s in (*face_fatal_shapes(_SIMPLE), *lenient_shapes(_SIMPLE)) if s.name == name)
    directory_reason, tables_reason, dropped = _SFNT_RULES[name]
    assert _raised(sfnt.read_directory, shape.data) == directory_reason
    assert _raised(sfnt.read_glyph_tables, shape.data) == tables_reason
    if directory_reason is None:
        directory = sfnt.read_directory(shape.data)
        assert directory.dropped == (frozenset() if dropped is None else frozenset({dropped}))
        if dropped is not None:
            assert directory.slot(dropped) is None
    loader_loads = _LOADER_CASES[name][1]
    if not loader_loads:  # a face the loader refuses is a program sfnt refuses
        assert tables_reason is not None


def test_sfnt_reads_the_control_program_like_its_directory():
    """On the re-assembled control: one slot per directory entry at its stated offset and length, nothing dropped."""
    sfnt = _sfnt()
    program = _SIMPLE.roundtrip()
    directory = sfnt.read_directory(program)
    entries = directory_entries(program)
    assert directory.size == len(program)
    assert directory.dropped == frozenset()
    assert list(directory.slots) == [tag for tag, _o, _n in entries]
    for tag, offset, length in entries:
        slot = directory.slot(tag)
        assert slot is not None and (slot.offset, slot.length) == (offset, length), tag
        assert slot.copy(program) == program[offset : offset + length]
    assert directory.slot(b"zzzz") is None


def test_a_table_slot_copy_adds_the_tail_and_stays_inside_the_data():
    sfnt = _sfnt()
    data = bytes(range(64))
    slot = sfnt.TableSlot(offset=8, length=4)
    assert slot.copy(data) == data[8:12]
    assert slot.copy(data, tail=5) == data[8:17]
    assert slot.copy(data, tail=1000) == data[8:]  # a tail never reads past the end
    assert sfnt.TableSlot(offset=0, length=0).copy(data) == b""
    with pytest.raises(AttributeError):
        slot.offset = 1  # frozen
    with pytest.raises(TypeError):
        sfnt.TableSlot(offset=0)  # type: ignore[call-arg]


def test_read_directory_takes_the_first_in_range_entry_by_position():
    sfnt = _sfnt()
    real, other = _SIMPLE.table(b"maxp"), with_num_glyphs(_SIMPLE.table(b"maxp"), 2)
    for first, last in ((real, other), (other, real)):
        program = _SIMPLE.duplicated(b"maxp", first, last)
        slot = sfnt.read_directory(program).slot(b"maxp")
        assert slot is not None and slot.copy(program) == first
    empty_first = _SIMPLE.duplicated(b"glyf", None, _SIMPLE.table(b"glyf"))
    slot = sfnt.read_directory(empty_first).slot(b"glyf")
    assert slot is not None and slot.length == 0  # a zero-length first entry wins
    mapped = Variants(sfb.build_font_program("symbolic_mac10"))
    right = mapped.table(b"cmap")
    program = mapped.duplicated(b"cmap", Entry(b"cmap", b"\0" * 16, dir_off=past_eof_offset), right)
    directory = sfnt.read_directory(program)
    slot = directory.slot(b"cmap")
    assert slot is not None and slot.copy(program) == right  # an out-of-range first entry is skipped
    assert directory.dropped == frozenset({b"cmap"})  # but it is remembered as out of range


def test_read_directory_clips_hmtx_and_keeps_it_out_of_dropped():
    sfnt = _sfnt()
    program = _SIMPLE.modified(b"hmtx", dir_len=past_eof_length)
    offset = next(o for t, o, _n in directory_entries(program) if t == b"hmtx")
    directory = sfnt.read_directory(program)
    slot = directory.slot(b"hmtx")
    assert slot is not None and (slot.offset, slot.length) == (offset, (len(program) - offset) & ~3)
    assert b"hmtx" not in directory.dropped
    unaligned = _SIMPLE.hmtx_at_eof(2, dir_len=past_eof_length)
    slot = sfnt.read_directory(unaligned).slot(b"hmtx")
    assert slot is not None and slot.length == (len(unaligned) - slot.offset) & ~3 != len(unaligned) - slot.offset
    # a clip to zero bytes is a missing hmtx, but only when no other hmtx entry wins
    gone = _SIMPLE.hmtx_at_eof(0, dir_off=last_word_offset, dir_len=past_eof_length)
    assert _raised(sfnt.read_directory, gone) == "hmtx_out_of_range"
    # an hmtx entry whose offset is past the end is fatal only when no other hmtx entry survives
    lost_first = _SIMPLE.duplicated(b"hmtx", Entry(b"hmtx", b"\0" * 8, dir_off=past_eof_offset), _SIMPLE.table(b"hmtx"))
    assert sfnt.read_directory(lost_first).slot(b"hmtx") is not None


@pytest.mark.parametrize(
    ("label", "program", "reason"),
    [
        ("empty", b"", "not_truetype"),
        ("11 bytes", EDGE_INPUTS["11 bytes"], "not_truetype"),
        ("OTTO", EDGE_INPUTS["CFF container tag"], "not_truetype"),
        ("ttcf", _SIMPLE.ttcf_file_absolute(1), "ttcf"),
        ("ttcf member-relative", _SIMPLE.ttcf_member_relative(), "ttcf"),
        ("directory longer than the file", EDGE_INPUTS["directory claims more entries than the file holds"], "truncated_directory"),
    ],
)
def test_read_directory_refuses_with_a_reason(label, program, reason):
    assert _raised(_sfnt().read_directory, program) == reason, label


def test_sfnt_error_is_a_value_error_with_a_reason():
    sfnt = _sfnt()
    assert issubclass(sfnt.SfntError, ValueError)  # R1's `except Exception` -> unproven:unreadable stays as is
    with pytest.raises(sfnt.SfntError) as caught:
        sfnt.read_directory(b"")
    assert caught.value.reason == "not_truetype"
    assert "not_truetype" in str(caught.value)


def test_a_directory_with_no_tables_reads_but_has_no_glyph_tables():
    sfnt = _sfnt()
    program = EDGE_INPUTS["numTables 0"]
    directory = sfnt.read_directory(program)
    assert (directory.size, dict(directory.slots), directory.dropped) == (len(program), {}, frozenset())
    assert _raised(sfnt.read_glyph_tables, program) == "required_table_missing"
    assert _raised(sfnt.read_glyph_tables, EDGE_INPUTS["directory ends exactly at EOF"]) == "required_table_missing"


def test_read_glyph_tables_refuses_a_short_maxp_and_a_short_loca():
    sfnt = _sfnt()
    short_maxp = _SIMPLE.with_table(b"maxp", _SIMPLE.table(b"maxp")[:5])
    assert _raised(sfnt.read_glyph_tables, short_maxp) == "required_table_missing"
    loca = _SIMPLE.table(b"loca")
    assert _raised(sfnt.read_glyph_tables, _SIMPLE.roundtrip()) is None
    assert _raised(sfnt.read_glyph_tables, _SIMPLE.with_table(b"loca", loca[:-2])) == "loca_short"
    assert _raised(sfnt.read_glyph_tables, _SIMPLE.with_table(b"loca", loca[:2])) == "loca_short"


def _with_long_loca(variants: Variants) -> Variants:
    """The program with a 4-byte-entry ``loca`` and ``indexToLocFormat`` 1 (the same glyph spans; already so for a long base)."""
    head, loca = variants.table(b"head"), variants.table(b"loca")
    if loca_format_of(head) == 0:
        offsets = struct.unpack(f">{len(loca) // 2}H", loca)
        loca = struct.pack(f">{len(offsets)}I", *(value * 2 for value in offsets))
    long_loca = Variants(variants.with_table(b"loca", loca))
    return Variants(long_loca.with_table(b"head", with_loca_format(head, 1)))


def _ink_of_a(program: bytes) -> bytes:
    """The pixels FreeType paints for the simple fixture's "A" from ``program`` (a blank page if nothing draws)."""
    page = fitz.open().new_page(width=100, height=100)
    writer = fitz.TextWriter(page.rect)
    writer.append((10, 80), "A", font=fitz.Font(fontbuffer=program), fontsize=60)
    writer.write_text(page)
    return page.get_pixmap(dpi=72, alpha=False).samples


@pytest.mark.parametrize("loca_format", [2, -1, 256])
def test_an_index_to_loc_format_other_than_0_is_read_as_a_long_loca(loca_format, quiet_mupdf):
    """FreeType takes any nonzero ``indexToLocFormat`` as a long loca (4-byte entries): both readers read it that way.

    Anchored to the loader: ``fitz.Font`` loads the face and paints the same pixels as the same program with format 1
    (and not the pixels of the 2-byte reading, format 0).  ``GlyphProgram.index_to_loc_format`` stays the normalised
    0/1 the glyph-box code compares."""
    sfnt = _sfnt()
    for name, (variants, _gid) in _bases().items():
        long_base = _with_long_loca(variants)
        program = long_base.with_table(b"head", with_loca_format(long_base.table(b"head"), loca_format))
        tables = sfnt.read_glyph_tables(program)
        assert tables.long_loca is True, name
        assert tables.loca.length == len(long_base.table(b"loca")) >= (tables.num_glyphs + 1) * 4, name
        reference = r2_facts(long_base.roundtrip())
        assert reference is not None and reference[1] is True, name
        assert r2_facts(program) == reference, name
        assert r1_facts(program) == reference, name
        parsed, expected = cid_fonts.parse_truetype_glyph_program(program), cid_fonts.parse_truetype_glyph_program(
            long_base.roundtrip()
        )
        assert parsed is not None and expected is not None and parsed.loca == expected.loca, name
        assert parsed.index_to_loc_format == 1, name
        if name == "simple":
            assert _r1_proof(program).program_kind == "truetype"
            assert _loads(program), "the claim above: the loader accepts this face"
            ink = _ink_of_a(program)
            assert ink == _ink_of_a(long_base.roundtrip()) != _ink_of_a(
                long_base.with_table(b"head", with_loca_format(long_base.table(b"head"), 0))
            ), "the loader paints the long reading, not the 2-byte one"


def test_a_nonzero_index_to_loc_format_checks_the_loca_length_in_four_byte_entries():
    """A 2-byte-entry ``loca`` under format 2 / -1 / 256 is too short for ``numGlyphs + 1`` 4-byte entries: refused."""
    sfnt = _sfnt()
    head = _SIMPLE.table(b"head")
    for loca_format in (2, -1, 256):
        program = _SIMPLE.with_table(b"head", with_loca_format(head, loca_format))
        assert _raised(sfnt.read_glyph_tables, program) == "loca_short", loca_format
        assert r2_facts(program) is None and r1_facts(program) is None, loca_format
    assert _raised(sfnt.read_glyph_tables, _SIMPLE.roundtrip()) is None  # 0 and 1 stay readable
    for good in (0, 1):
        program = _SIMPLE.with_table(b"head", with_loca_format(head, good))
        assert _raised(sfnt.read_directory, program) is None


@pytest.mark.parametrize("source", [*_TRUETYPE_KINDS, "type0_subset"])
def test_read_glyph_tables_reads_the_shared_facts(source):
    """``GlyphTables`` carries what both readers need and agrees with them on every fixture (the step-3/4 parity anchor)."""
    sfnt = _sfnt()
    program = type0_program() if source == "type0_subset" else sfb.build_font_program(source)
    tables = sfnt.read_glyph_tables(program)
    proof = _r1_proof(program)
    parsed = cid_fonts.parse_truetype_glyph_program(program)
    assert proof.program_kind == "truetype" and parsed is not None
    assert tables.num_glyphs == parsed.num_glyphs == proof.num_glyphs
    assert tables.long_loca == (parsed.index_to_loc_format == 1)
    assert tables.units_per_em == parsed.units_per_em
    assert (tables.glyf.offset, tables.glyf.length) == (parsed.glyf_offset, parsed.glyf_length)
    assert tables.loca.length >= (tables.num_glyphs + 1) * (4 if tables.long_loca else 2)
    assert tables.directory.slot(b"glyf") == tables.glyf and tables.directory.slot(b"loca") == tables.loca


def test_sfnt_constants_are_the_values_the_readers_already_use():
    from model.text_commit import simple_font_programs as sfp

    sfnt = _sfnt()
    assert sfnt.HEAD_MIN_LENGTH == 54
    assert sfnt.MAX_FONT_PROGRAM_BYTES == 64 << 20 == sfp._MAX_FONT_PROGRAM_BYTES == cid_fonts._MAX_FONT_PROGRAM_BYTES


def test_the_size_cap_has_one_home():
    """Both readers take the cap from ``sfnt`` instead of writing the number again (the module global stays patchable)."""
    for name in ("simple_font_programs.py", "cid_fonts.py"):
        tree = ast.parse((_ROOT / "model" / "text_commit" / name).read_text(encoding="utf-8"))
        assigns = [
            node
            for node in tree.body
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_MAX_FONT_PROGRAM_BYTES" for t in node.targets)
        ]
        assert len(assigns) == 1, name
        assert ast.unparse(assigns[0].value) == "sfnt.MAX_FONT_PROGRAM_BYTES", name
