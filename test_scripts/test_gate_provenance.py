"""D24 guard (handoff H12): a gate table records, per number, the callable that was actually called.

``check_gate_table`` fails on an empty cell, on a gate with no row, and on a recorded name that does
not resolve to a callable by import plus ``getattr`` (the M9 class: a label such as
``serialize_document_bytes`` recorded while ``tobytes`` ran).  The real gate table is produced by the
measuring scripts of later cards (B3 onward); where it lives is an open question reported with card
B1, so this file tests the guard on synthetic tables only.
"""

from __future__ import annotations

import importlib
import math
import re
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from test_scripts.vector_gate_recorder import (  # noqa: E402
    _PATH_LIKE,
    TABLE_PATH as TABLE_FILE,
    gate_row,
    mentions_machine_name,
    record_call,
    write_gate_table,
)

# The gates of design plan section 11 (B0 is the 100 ms click limit of D25).
GATES = ("B0", "B1", "B2", "B3", "B4", "B5", "B6")
CELLS = ("number", "unit", "callable", "calls", "commit", "sample_digest")
PRODUCT_PREFIXES = ("model.", "controller.", "utils.")
STATUSES = frozenset({"pending", "measured"})
_COMMIT = re.compile(r"[0-9a-f]{7,40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
# Ratchet: the gates whose real row is still pending.  Each measuring card (B3 onward) removes its gate
# here in the same commit that records its row; B8's acceptance is the empty set.
EXPECTED_PENDING: frozenset[str] = frozenset(GATES)


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


def _reads_back(qualname: str) -> bool:
    """The resolved callable carries exactly this name (module + qualname): no alias, no re-export."""
    obj = _resolve(qualname)
    return callable(obj) and f"{getattr(obj, '__module__', None)}.{getattr(obj, '__qualname__', None)}" == qualname


def _check_row(gate: str, row: Mapping[str, object]) -> list[str]:
    status = row.get("status")
    if status not in STATUSES:
        return [f"{gate}.status: {status!r} is not one of {sorted(STATUSES)}"]
    if status == "pending":  # pending is a bare marker: no number, no provenance cells (the ratchet owns when)
        return [
            f"{gate}.{key}: a pending row carries only status (and a note)" for key in sorted(set(row) - {"status", "note"})
        ]
    problems: list[str] = []
    for cell in CELLS:
        value = row.get(cell)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.append(f"{gate}.{cell}: empty cell")
    number = row.get("number")
    if number is not None and (
        isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number)
    ):
        problems.append(f"{gate}.number: {number!r} is not a finite int or float")
    calls = row.get("calls")
    if calls is not None and (isinstance(calls, bool) or not isinstance(calls, int) or calls < 1):
        problems.append(f"{gate}.calls: {calls!r} is not an int >= 1")
    for cell in ("unit", "commit", "sample_digest"):
        value = row.get(cell)
        if value is not None and not isinstance(value, str):
            problems.append(f"{gate}.{cell}: {value!r} is not a string")
    commit, digest = row.get("commit"), row.get("sample_digest")
    if isinstance(commit, str) and commit.strip() and not _COMMIT.fullmatch(commit):
        problems.append(f"{gate}.commit: {commit!r} is not a 7 to 40 digit hex commit id")
    if isinstance(digest, str) and digest.strip() and not _DIGEST.fullmatch(digest):
        problems.append(f"{gate}.sample_digest: {digest!r} is not a 64 digit hex SHA-256")
    name = row.get("callable")
    if name is not None and not isinstance(name, str):
        problems.append(f"{gate}.callable: {name!r} is not a string (provenance must be a qualified name)")
    elif isinstance(name, str) and name.strip() and not name.startswith(PRODUCT_PREFIXES):
        problems.append(f"{gate}.callable: {name!r} is not a product entry point (model./controller./utils.)")
    elif isinstance(name, str) and name.strip() and not _resolves(name):
        problems.append(f"{gate}.callable: {name!r} does not resolve to a callable defined in a product module (a label, not the function that ran)")
    elif isinstance(name, str) and name.strip() and not _reads_back(name):
        problems.append(f"{gate}.callable: {name!r} does not read back as the callable's own module and qualname (an alias or a re-export)")
    return problems


def check_gate_table(table: Mapping[str, Mapping[str, object]], gates: tuple[str, ...] = GATES) -> list[str]:
    problems: list[str] = []
    for gate in gates:
        row = table.get(gate)
        if row is None:
            problems.append(f"{gate}: no row")
            continue
        problems += _check_row(gate, row)
    return problems


def _full_table() -> dict[str, dict[str, object]]:
    return {
        g: {
            "number": 1.5,
            "unit": "ms",
            "callable": "model.vector_paths.commit_state.digest_table",
            "calls": 2,
            "commit": "0123abc",
            "sample_digest": "ab" * 32,
            "status": "measured",
        }
        for g in GATES
    }


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


# --------------------------------------------------------------------------- strict guard (card B1 completion)


def _measured(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "number": 1.5,
        "unit": "ms",
        "callable": "model.vector_paths.commit_state.digest_table",
        "calls": 3,
        "commit": "0123abc",
        "sample_digest": "ab" * 32,
        "status": "measured",
    }
    row.update(over)
    return row


def _table_of(row: dict[str, object]) -> dict[str, dict[str, object]]:
    return {g: dict(row) for g in GATES}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_rejected(bad: float) -> None:
    problems = check_gate_table(_table_of(_measured(number=bad)))
    assert len(problems) == len(GATES) and all(".number" in p for p in problems)


@pytest.mark.parametrize("calls", [0, -1, None, True, 1.0, "2"])
def test_a_measured_row_needs_at_least_one_call(calls: object) -> None:
    problems = check_gate_table(_table_of(_measured(calls=calls)))
    assert len(problems) == len(GATES) and all(".calls" in p for p in problems)


def test_a_measured_row_needs_every_cell() -> None:
    for cell in ("unit", "commit", "sample_digest"):
        problems = check_gate_table({"B0": _measured(**{cell: ""}), **{g: _measured() for g in GATES[1:]}})
        assert [p.split(":")[0] for p in problems] == [f"B0.{cell}"]


def test_a_re_export_alias_is_rejected_because_the_name_does_not_read_back() -> None:
    """The recorded name must be the one the function itself carries (module and qualname)."""
    alias = "model.vector_paths.digest_table"  # re-exported from commit_state
    assert _resolves(alias)  # the alias resolves by getattr and is a product callable ...
    problems = check_gate_table(_table_of(_measured(callable=alias)))
    assert len(problems) == len(GATES) and all("read back" in p for p in problems)


def test_a_pending_row_counts_as_ok_and_carries_no_number() -> None:
    assert check_gate_table({g: {"status": "pending"} for g in GATES}) == []
    problems = check_gate_table({**{g: {"status": "pending"} for g in GATES[1:]}, "B0": {"status": "pending", "number": 2.0}})
    assert [p.split(":")[0] for p in problems] == ["B0.number"]  # a pending row carries no number


def test_a_stub_labelled_y_that_calls_x_records_x() -> None:
    """M9: the recorder writes the function that ran (X), whatever the measuring script labels it (Y)."""
    from model.doc_bytes import keep_snapshot_in_memory as label_y  # noqa: F401 - the label, never called
    from model.vector_paths.commit_state import digest_table as x

    recorded = record_call(x)

    def stub_labelled_y() -> object:  # claims to measure Y, actually calls X
        import fitz

        doc = fitz.open()
        doc.new_page()
        return recorded(doc)

    stub_labelled_y()
    row = gate_row(1.0, "ms", recorded, "0123abc", "cd" * 32)
    assert row["callable"] == "model.vector_paths.commit_state.digest_table"
    assert row["calls"] == 1
    assert row["callable"] != f"{label_y.__module__}.{label_y.__qualname__}"
    assert check_gate_table(_table_of({**row, "status": "measured"})) == []


def test_the_writer_round_trips_and_refuses_machine_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    _as_machine(monkeypatch, "someuser", "somehost")
    recorded = record_call(len)
    rows = {g: _measured() for g in GATES}
    path = write_gate_table(rows, tmp_path / "t.json")
    assert json.loads(path.read_text(encoding="utf-8"))["gates"] == rows
    with pytest.raises(ValueError):
        write_gate_table({"B0": _measured(commit="C:" + chr(92) + "work" + chr(92) + "x")}, tmp_path / "u.json")
    with pytest.raises(ValueError):
        write_gate_table({"B0": _measured(unit="/home/someone")}, tmp_path / "u.json")
    with pytest.raises(ValueError):
        write_gate_table({"B0": _measured(unit="someuser-box")}, tmp_path / "u.json")
    with pytest.raises(ValueError):
        write_gate_table({"B0": _measured(number=float("nan"))}, tmp_path / "u.json")
    assert recorded.name == "builtins.len"


def _real_table() -> dict[str, dict[str, object]]:
    import json

    data = json.loads(TABLE_FILE.read_text(encoding="utf-8"))
    assert data["schema"] == 1
    return data["gates"]


def test_the_real_gate_table_file_passes_the_guard() -> None:
    """All rows may be pending until B8; any measured row must satisfy the strict guard."""
    assert check_gate_table(_real_table()) == []


def test_the_real_gate_table_file_has_no_machine_data() -> None:
    from test_scripts.vector_gate_recorder import _machine_strings

    text = TABLE_FILE.read_text(encoding="utf-8")
    assert not _PATH_LIKE.search(text)
    assert not mentions_machine_name(text, _machine_strings())


def _as_machine(monkeypatch: pytest.MonkeyPatch, user: str, host: str) -> None:
    import getpass
    import socket

    monkeypatch.setattr(getpass, "getuser", lambda: user)
    monkeypatch.setattr(socket, "gethostname", lambda: host)


def test_a_short_machine_name_does_not_reject_ordinary_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """B1 review finding 6: a 3-character name such as ``mod`` is not matched at all (too common)."""
    _as_machine(monkeypatch, "mod", "box")
    rows = {g: _measured(unit="model ms", callable="model.vector_paths.commit_state.digest_table") for g in GATES}
    write_gate_table(rows, tmp_path / "t.json")  # must not raise


def test_a_machine_name_matches_as_a_whole_token_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _as_machine(monkeypatch, "wilsonx", "buildhost")
    write_gate_table({"B0": _measured(unit="wilsonxy ms")}, tmp_path / "a.json")  # inside a longer word: fine
    write_gate_table({"B0": _measured(unit="mywilsonx")}, tmp_path / "b.json")
    for bad in ("wilsonx", "wilsonx-box", "run on BuildHost", "x/wilsonx/y", "a_buildhost.local"):
        with pytest.raises(ValueError):
            write_gate_table({"B0": _measured(unit=bad)}, tmp_path / "c.json")


def test_the_pending_set_of_the_real_table_is_exactly_the_ratchet() -> None:
    """A measuring card removes its gate from EXPECTED_PENDING when it records the row; B8's acceptance is
    the empty set.  A row that turns measured (or pending) without the ratchet moving fails here."""
    pending = {g for g, row in _real_table().items() if row.get("status") == "pending"}
    assert pending == EXPECTED_PENDING, f"pending {sorted(pending)} != expected {sorted(EXPECTED_PENDING)}"


def test_a_pending_row_is_a_bare_marker_with_an_optional_note() -> None:
    ok = {g: {"status": "pending"} for g in GATES}
    assert check_gate_table({**ok, "B1": {"status": "pending", "note": "B3 measures it"}}) == []
    for extra in ("callable", "calls", "commit", "unit", "sample_digest", "number"):
        problems = check_gate_table({**ok, "B2": {"status": "pending", extra: "x"}})
        assert [p.split(":")[0] for p in problems] == [f"B2.{extra}"], extra


@pytest.mark.parametrize("status", [None, "", "done", "Measured", 1, True])
def test_an_unknown_status_fails(status: object) -> None:
    problems = check_gate_table({**{g: _measured() for g in GATES}, "B3": _measured(status=status)})
    assert [p.split(":")[0] for p in problems] == ["B3.status"]


@pytest.mark.parametrize("commit", ["abc12", "g" * 7, "0123abc" * 7, "0123ABC", "HEAD"])
def test_a_measured_commit_must_be_7_to_40_hex(commit: str) -> None:
    problems = check_gate_table({**{g: _measured() for g in GATES}, "B4": _measured(commit=commit)})
    assert [p.split(":")[0] for p in problems] == ["B4.commit"]


@pytest.mark.parametrize("digest", ["ab" * 16, "ab" * 33, "zz" * 32, "AB" * 32])
def test_a_measured_sample_digest_must_be_64_hex(digest: str) -> None:
    problems = check_gate_table({**{g: _measured() for g in GATES}, "B5": _measured(sample_digest=digest)})
    assert [p.split(":")[0] for p in problems] == ["B5.sample_digest"]


def test_the_real_pending_row_shape_passes_only_when_bare() -> None:
    assert all(set(row) <= {"status", "note"} for row in _real_table().values() if row.get("status") == "pending")
