"""R2.1 — Layer-boundary AST guard: the structural net for the R-series.

Locks the MVC import invariants that CLAUDE.md §2 makes load-bearing, so an
accidental cross-layer import or a stray document handle introduced during the
R3 god-module decomposition fails CI instead of regressing silently:

  - ``model/`` never imports Qt (PySide6/PyQt) and never imports ``view``/``controller``.
  - ``view/`` never calls ``fitz.open(...)`` outside a small sanctioned allowlist.

Geometry value-types (``fitz.Rect``/``Point``/``Quad``/``Matrix``) and the typed
request channels (``model/edit_requests.py``, ``model/object_requests.py``) are
deliberately allowed — they are data, not live document handles, so a view may
import them. Only ``fitz.open`` (a document handle) is forbidden in the view.

This guard lands green against current code and stays live for every subsequent
R2/R3 edit.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _py_files(rel_dir: str) -> list[Path]:
    return sorted(p for p in (REPO_ROOT / rel_dir).rglob("*.py") if "__pycache__" not in p.parts)


def test_model_layer_imports_no_qt_and_no_view_or_controller() -> None:
    forbidden_tops = {"PySide6", "PyQt5", "PyQt6", "view", "controller"}
    offenders: list[str] = []
    for path in _py_files("model"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden_tops:
                        offenders.append(f"{rel}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                # Ignore relative imports (node.level > 0 stays within model/).
                if node.level == 0 and (node.module or "").split(".")[0] in forbidden_tops:
                    offenders.append(f"{rel}:{node.lineno} from {node.module}")
    assert not offenders, (
        "model/ must never import Qt or the view/controller layers (CLAUDE.md §2). "
        f"Offending imports: {offenders}"
    )


def test_model_layer_imports_no_spike_scripts_and_no_fonttools() -> None:
    """``scripts/`` is measurement-and-spike code.  Geometry that a spike
    proved out is RE-HOMED into ``model/`` by copying; importing it back
    across the boundary would make a production path depend on a directory
    no packaging step ships.  ``fontTools`` became a runtime dependency for
    one job only (EXTB-SUBSET: subsetting a Windows CJK Ext-B font, owner
    decision C), which lives in ``utils/cjk_ext_b_font.py`` -- see
    ``test_fonttools_is_imported_only_by_the_ext_b_subsetter``; ``model/``
    still never imports it (the glyph-box arithmetic stays re-homed).  No
    import-linter contract names either, so this AST guard is the only
    enforcement."""
    forbidden_tops = {"scripts", "fontTools", "fonttools"}
    offenders: list[str] = []
    for path in _py_files("model"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in forbidden_tops:
                        offenders.append(f"{rel}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and (node.module or "").split(".")[0] in forbidden_tops:
                    offenders.append(f"{rel}:{node.lineno} from {node.module}")
    assert not offenders, (
        "model/ must never import from scripts/ or fontTools — re-home the "
        f"pure arithmetic instead. Offending imports: {offenders}"
    )


def _fonttools_imports(path: Path) -> list[tuple[int, bool]]:
    """``(line, at_module_level)`` of every fontTools import in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    module_level = {id(node) for node in tree.body}
    found: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names = [node.module or ""]
        if any(name.split(".")[0].lower() == "fonttools" for name in names):
            found.append((node.lineno, id(node) in module_level))
    return found


def test_fonttools_is_imported_only_by_the_ext_b_subsetter() -> None:
    """EXTB-SUBSET: the one production module allowed to import fontTools is
    ``utils/cjk_ext_b_font.py``, and only lazily (inside a function), so the
    editor still launches and every non-Ext-B path still runs when the
    package is broken or missing."""
    allowed = "utils/cjk_ext_b_font.py"
    offenders: list[str] = []
    allowed_hits: list[tuple[int, bool]] = []
    for layer in ("model", "controller", "view", "utils"):
        for path in _py_files(layer):
            rel = path.relative_to(REPO_ROOT).as_posix()
            hits = _fonttools_imports(path)
            if rel == allowed:
                allowed_hits = hits
            elif hits:
                offenders.extend(f"{rel}:{line}" for line, _top in hits)
    assert not offenders, f"fontTools imported outside {allowed}: {offenders}"
    assert allowed_hits, f"{allowed} must exist and import fontTools"
    assert not [line for line, top in allowed_hits if top], (
        f"{allowed} imports fontTools at module level: {allowed_hits}"
    )


# view/ fitz.open allowlist: file -> the EXACT number of sanctioned fitz.open
# calls in it. An exact count catches a *new* fitz.open sneaking into an
# allowlisted file while staying robust to line-number drift.
_VIEW_FITZ_OPEN_ALLOWLIST: dict[str, int] = {
    # Empty scratch doc for the no-jump inline-editor preview — sanctioned,
    # permanent (it never touches a real/user document). This is the ONLY
    # fitz.open permitted anywhere in view/; R2.3 removed the merge-dialog leak.
    "view/text_editing.py": 1,
}


def _count_fitz_open(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "fitz"
        ):
            count += 1
    return count


def test_view_layer_has_no_unsanctioned_fitz_open() -> None:
    offenders: list[str] = []
    for path in _py_files("view"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        found = _count_fitz_open(ast.parse(path.read_text(encoding="utf-8-sig")))
        allowed = _VIEW_FITZ_OPEN_ALLOWLIST.get(rel, 0)
        if found != allowed:
            offenders.append(f"{rel}: {found} fitz.open( call(s), allowlist expects {allowed}")
    assert not offenders, (
        "view/ must not call fitz.open(...) outside the sanctioned allowlist "
        "(geometry value-types are fine; document handles are not). Update R2.3 "
        f"and the allowlist together if intentional. Mismatches: {offenders}"
    )


# PR-9 (2026-07-04, codex review follow-up): import-linter's view-no-model
# `ignore_imports` allowlist is MODULE-edge based, so a future behavior import
# from a permitted module (e.g. `from model.pdf_optimizer import
# save_optimized_copy` in a dialog) would slip through the contract silently.
# This guard pins the permitted edges down to the exact NAMES a view file may
# import from model — anything new must be added here deliberately.
_VIEW_MODEL_IMPORT_NAME_ALLOWLIST: dict[tuple[str, str], frozenset[str]] = {
    ("view/dialogs/optimize.py", "model.pdf_optimizer"): frozenset({"PdfOptimizeOptions"}),
    ("view/dialogs/audit.py", "model.pdf_optimizer"): frozenset({"PdfAuditReport"}),
    ("view/object_selection.py", "model.object_requests"): frozenset(
        {"BatchDeleteObjectsRequest", "DeleteObjectRequest", "ObjectRef", "RotateObjectRequest"}
    ),
    ("view/pdf_view.py", "model.object_requests"): frozenset(
        {"BatchMoveObjectsRequest", "InsertImageObjectRequest", "MoveObjectRequest", "ResizeObjectRequest"}
    ),
    ("view/text_editing.py", "model.edit_requests"): frozenset(
        {"EditTextRequest", "MoveTextRequest", "StyleOverrides"}
    ),
    ("view/text_editing.py", "model.edit_commands"): frozenset({"EditTextResult"}),
}


def test_view_model_imports_are_dto_names_only() -> None:
    offenders: list[str] = []
    for path in _py_files("view"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "model":
                        offenders.append(f"{rel}:{node.lineno} import {alias.name} (bare module import)")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level == 0 and module.split(".")[0] == "model":
                    allowed = _VIEW_MODEL_IMPORT_NAME_ALLOWLIST.get((rel, module))
                    if allowed is None:
                        offenders.append(f"{rel}:{node.lineno} from {module} (module edge not allowlisted)")
                        continue
                    for alias in node.names:
                        if alias.name not in allowed:
                            offenders.append(f"{rel}:{node.lineno} from {module} import {alias.name}")
    assert not offenders, (
        "view/ may import only the pinned DTO names from model (CLAUDE.md §2; "
        "pyproject view-no-model ignore_imports is module-edge based, this guard "
        f"adds name granularity). Offenders: {offenders}"
    )
