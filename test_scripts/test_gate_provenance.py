"""D24 guard (handoff H12): a gate table records, per number, the callable that was actually called.

``check_gate_table`` fails on an empty cell, on a gate with no row, and on a recorded name that does
not resolve to a callable by import plus ``getattr`` (the M9 class: a label such as
``serialize_document_bytes`` recorded while ``tobytes`` ran).  The real gate table is produced by the
measuring scripts of later cards (B3 onward); where it lives is an open question reported with card
B1, so this file tests the guard on synthetic tables only.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The gates of design plan section 11 (B0 is the 100 ms click limit of D25).
GATES = ("B0", "B1", "B2", "B3", "B4", "B5", "B6")
CELLS = ("number", "callable")
PRODUCT_PREFIXES = ("model.", "controller.", "utils.")


def _resolve(qualname: str) -> object | None:
    """``pkg.module.attr`` (or ``pkg.module.Class.attr``): import the longest module prefix, then getattr."""
    parts = qualname.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        try:
            obj: object = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        try:
            for name in parts[cut:]:
                obj = getattr(obj, name)
        except AttributeError:
            return None
        return obj
    return None


def _resolves(qualname: str) -> bool:
    """The name resolves to a callable defined in a product module (``__module__``, not the name path)."""
    obj = _resolve(qualname)
    module = getattr(obj, "__module__", None)
    return callable(obj) and isinstance(module, str) and module.startswith(PRODUCT_PREFIXES)


def check_gate_table(table: Mapping[str, Mapping[str, object]], gates: tuple[str, ...] = GATES) -> list[str]:
    problems: list[str] = []
    for gate in gates:
        row = table.get(gate)
        if row is None:
            problems.append(f"{gate}: no row")
            continue
        for cell in CELLS:
            value = row.get(cell)
            if value is None or (isinstance(value, str) and not value.strip()):
                problems.append(f"{gate}.{cell}: empty cell")
        number = row.get("number")
        if number is not None and (
            isinstance(number, bool) or not isinstance(number, (int, float)) or number != number
        ):
            problems.append(f"{gate}.number: {number!r} is not a finite int or float")
        name = row.get("callable")
        if name is not None and not isinstance(name, str):
            problems.append(f"{gate}.callable: {name!r} is not a string (provenance must be a qualified name)")
        elif isinstance(name, str) and name.strip() and not name.startswith(PRODUCT_PREFIXES):
            problems.append(f"{gate}.callable: {name!r} is not a product entry point (model./controller./utils.)")
        elif isinstance(name, str) and name.strip() and not _resolves(name):
            problems.append(f"{gate}.callable: {name!r} does not resolve to a callable defined in a product module (a label, not the function that ran)")
    return problems


def _full_table() -> dict[str, dict[str, object]]:
    return {g: {"number": 1.5, "callable": "model.vector_paths.commit_state.digest_table"} for g in GATES}


def test_a_complete_table_passes() -> None:
    assert check_gate_table(_full_table()) == []


@pytest.mark.parametrize("cell", CELLS)
@pytest.mark.parametrize("empty", [None, "", "   "])
def test_an_empty_cell_fails(cell: str, empty: object) -> None:
    table = _full_table()
    table["B3"][cell] = empty
    problems = check_gate_table(table)
    assert any(p.startswith(f"B3.{cell}: empty cell") for p in problems)


def test_a_gate_without_a_row_fails() -> None:
    table = _full_table()
    del table["B5"]
    assert check_gate_table(table) == ["B5: no row"]


def test_an_empty_table_fails_on_every_gate() -> None:
    assert len(check_gate_table({})) == len(GATES)


def test_a_label_that_is_not_the_callable_fails() -> None:
    """M9: the recorded name must be the function that ran, resolvable by import plus getattr."""
    table = _full_table()
    table["B1"]["callable"] = "serialize_document_bytes"
    table["B2"]["callable"] = "model.doc_bytes.no_such_function"
    table["B4"]["callable"] = "model.doc_bytes.logger"  # resolves but is not callable
    problems = check_gate_table(table)
    assert {p.split(".")[0] for p in problems} == {"B1", "B2", "B4"}


def test_a_product_entry_point_resolves() -> None:
    assert _resolves("model.doc_bytes.keep_snapshot_in_memory")
    assert _resolves("model.vector_paths.commit_state.digest_table")
    assert not _resolves("")


def test_a_callable_outside_the_product_does_not_satisfy_the_gate() -> None:
    """H12: the callable must be a product entry point, not any importable callable."""
    table = _full_table()
    table["B2"]["callable"] = "builtins.len"
    table["B3"]["callable"] = "json.dumps"
    problems = check_gate_table(table)
    assert {p.split(".")[0] for p in problems} == {"B2", "B3"}
    assert all("product entry point" in p for p in problems)


@pytest.mark.parametrize("bad", [42, 3.5, ["model.doc_bytes.keep_snapshot_in_memory"], True])
def test_a_non_string_callable_fails(bad: object) -> None:
    table = _full_table()
    table["B4"]["callable"] = bad
    assert any(p.startswith("B4.callable") for p in check_gate_table(table))


@pytest.mark.parametrize("bad", [[], True, "1.5", None, float("nan")])
def test_a_non_numeric_number_fails(bad: object) -> None:
    table = _full_table()
    table["B2"]["number"] = bad
    assert any(p.startswith("B2.number") for p in check_gate_table(table))


def test_a_callable_that_resolves_through_a_non_product_module_fails() -> None:
    table = _full_table()
    table["B1"]["callable"] = "model.vector_paths.commit_state.hashlib.sha256"
    assert any(p.startswith("B1.callable") for p in check_gate_table(table))
