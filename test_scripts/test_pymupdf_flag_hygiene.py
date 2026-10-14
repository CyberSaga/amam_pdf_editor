"""GATE16-1: every test runs under the app's production PyMuPDF text flags.

``fitz.TOOLS.set_small_glyph_heights`` is process-global and ``PDFModel.__init__``
turns it on for good, so a test used to see ``False`` or ``True`` depending on
which tests ran before it in the same interpreter.  ``test_scripts/conftest.py``
now pins the production values before collection and around every test.  The
two tests below run in file order: the first leaks the wrong values on purpose,
the second must not see them.

GATE16-1a is the same class for ``logging.disable``: it is process-global too,
five script-style modules called ``logging.disable(logging.CRITICAL)`` at import
(i.e. at collection) and never restored it, so ``caplog`` stayed empty for every
later test in the process.  ``conftest.py`` now restores ``NOTSET`` around every
test and a source guard keeps scripts from disabling logging outside
``if __name__ == "__main__"``.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path

import fitz


def test_a_test_may_change_the_flags_without_restoring_them() -> None:
    assert bool(fitz.TOOLS.set_small_glyph_heights()) is True
    assert bool(fitz.TOOLS.unset_quad_corrections()) is False
    fitz.TOOLS.set_small_glyph_heights(False)
    fitz.TOOLS.unset_quad_corrections(True)
    assert bool(fitz.TOOLS.set_small_glyph_heights()) is False


def test_the_next_test_still_starts_under_the_production_flags() -> None:
    assert bool(fitz.TOOLS.set_small_glyph_heights()) is True
    assert bool(fitz.TOOLS.unset_quad_corrections()) is False


_SCRIPTS = Path(__file__).resolve().parent


def test_a_test_may_disable_logging_without_restoring_it() -> None:
    assert logging.root.manager.disable == logging.NOTSET
    logging.disable(logging.CRITICAL)
    assert logging.root.manager.disable == logging.CRITICAL


def test_the_next_test_still_starts_with_logging_enabled(caplog) -> None:
    assert logging.root.manager.disable == logging.NOTSET
    with caplog.at_level(logging.WARNING):
        logging.getLogger("gate16_1a_probe").warning("probe-record")
    assert "probe-record" in caplog.text


def _is_logging_disable(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if not (isinstance(fn, ast.Attribute) and fn.attr == "disable"
            and isinstance(fn.value, ast.Name) and fn.value.id == "logging"):
        return False
    # ``logging.disable(logging.NOTSET)`` RESTORES logging; only a disable leaks.
    arg = node.args[0] if node.args else None
    restores = (isinstance(arg, ast.Attribute) and arg.attr == "NOTSET") or (
        isinstance(arg, ast.Constant) and arg.value == 0)
    return not restores


def _is_main_guard(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    t = node.test
    return (isinstance(t, ast.Compare) and isinstance(t.left, ast.Name)
            and t.left.id == "__name__" and len(t.comparators) == 1
            and isinstance(t.comparators[0], ast.Constant)
            and t.comparators[0].value == "__main__")


def _unguarded_logging_disables(tree: ast.AST) -> list[int]:
    hits: list[int] = []

    def visit(node: ast.AST) -> None:
        if _is_main_guard(node):
            return
        if _is_logging_disable(node):
            hits.append(node.lineno)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return hits


def test_no_test_module_disables_logging_outside_a_main_guard() -> None:
    """A module-level ``logging.disable`` runs at collection and silences caplog."""
    offenders = {}
    for path in sorted(_SCRIPTS.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        hits = _unguarded_logging_disables(tree)
        if hits:
            offenders[path.name] = hits
    assert offenders == {}


def test_the_source_guard_sees_unguarded_calls_and_allows_main_guarded_ones() -> None:
    bad = ast.parse("import logging\nlogging.disable(logging.CRITICAL)\n")
    assert _unguarded_logging_disables(bad) == [2]
    nested = ast.parse("import logging\ndef f():\n    logging.disable(50)\n")
    assert _unguarded_logging_disables(nested) == [3]
    ok = ast.parse('import logging\nif __name__ == "__main__":\n    logging.disable(50)\n')
    assert _unguarded_logging_disables(ok) == []
    restore = ast.parse("import logging\nlogging.disable(logging.NOTSET)\n")
    assert _unguarded_logging_disables(restore) == []
