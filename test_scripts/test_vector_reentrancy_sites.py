"""Card B7 class check: the entry set is derived from the code, not hand-listed (pure; the Qt cases are in
test_vector_reentrancy_<group>.py)."""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---- the entry set is derived, not hand-listed ---------------------------------------------------------------
# Every deferred call (QTimer.singleShot) in the controller layer and main.py is an entry a pump can deliver into a
# transaction.  A new one must be added here on purpose: decide whether it writes (then it needs the gate and an
# ENTRIES case above) or only reads published state, and say so in the commit.
PINNED_DEFERRED_SITES = frozenset(
    {
    ("main.py", "run._release_window"),  # the retry itself; guarded by _write_busy, nothing is torn down while held
    ("controller/pdf_controller.py", "PDFController._refuse_busy"),
    ("controller/pdf_controller.py", "PDFController._release_thumbnail_pause"),
    ("controller/pdf_controller.py", "PDFController._start_open_background_loading"),
    ("controller/pdf_controller.py", "PDFController._refresh_recent_files"),
    ("controller/pdf_controller.py", "PDFController._schedule_restore_viewport_anchor"),
    ("controller/pdf_controller.py", "PDFController._consume_page_render_image"),
    ("controller/pdf_controller.py", "PDFController._on_page_render_failed"),
    ("controller/pdf_controller.py", "PDFController._schedule_visible_render"),
    ("controller/pdf_controller.py", "PDFController._process_visible_render_batch"),
    ("controller/pdf_controller.py", "PDFController._schedule_deferred_sidebar_scans"),
    ("controller/pdf_controller.py", "PDFController.exit_fullscreen"),
    ("controller/pdf_controller.py", "PDFController._render_active_session"),
    ("controller/pdf_controller.py", "PDFController._run_when_session_activation_allowed"),
    ("controller/pdf_controller.py", "PDFController._schedule_deferred_session_activation_retry"),
    ("controller/pdf_controller.py", "PDFController._save_with_signature_consent"),
    ("controller/pdf_controller.py", "PDFController._on_object_image_scan_ready"),
    ("controller/pdf_controller.py", "PDFController._commit_text_edit"),
    ("controller/pdf_controller.py", "PDFController._refresh_after_command"),
    ("controller/pdf_controller.py", "PDFController._invalidate_thumbnails"),
    ("controller/pdf_controller.py", "PDFController._schedule_index_batch"),
    ("controller/pdf_controller.py", "PDFController._schedule_stale_index_drain"),
    ("controller/pdf_controller.py", "PDFController._drain_stale_index_batch"),
    ("controller/thumbnail_coordinator.py", "ThumbnailCoordinator.request"),
    ("controller/thumbnail_coordinator.py", "ThumbnailCoordinator._process_image_revoked"),
    ("controller/thumbnail_coordinator.py", "ThumbnailCoordinator._complete_process_page"),
    ("controller/thumbnail_coordinator.py", "ThumbnailCoordinator._render_live_page"),
    ("controller/thumbnail_coordinator.py", "ThumbnailCoordinator._worker_failed"),
    ("controller/thumbnail_coordinator.py", "ThumbnailCoordinator._worker_finished"),
    ("controller/page_render_coordinator.py", "PageRenderCoordinator._consume_process_reply"),
    ("controller/scan_verifier.py", "ScanVerifier.request"),
    ("controller/worker_registry.py", "WorkerRegistry._connect_reaper._Reaper.sweep"),
    ("main.py", "_ForwardedPaths.bind"),
    ("main.py", "run.hand_off_session"),
    ("main.py", "run._install_close_promotion._CloseWatcher.eventFilter"),
    ("main.py", "run.finish_owned_shutdown"),
    }
)


def _deferred_sites() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    files = [*sorted(p.as_posix() for p in (REPO_ROOT / "controller").glob("*.py")), "main.py"]
    for rel in files:
        path = REPO_ROOT / rel if not rel.startswith(str(REPO_ROOT).replace("\\", "/")) else Path(rel)
        tree = ast.parse(path.read_text(encoding="utf-8"))

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.stack: list[str] = []

            def _scope(self, node) -> None:
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()

            visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _scope  # noqa: N815

            def visit_Call(self, node: ast.Call) -> None:
                if isinstance(node.func, ast.Attribute) and node.func.attr == "singleShot":
                    found.add((Path(rel).relative_to(REPO_ROOT).as_posix() if Path(rel).is_absolute() else rel, ".".join(self.stack)))
                self.generic_visit(node)

        Visitor().visit(tree)
    return found


def test_every_deferred_call_site_is_a_known_entry():
    assert _deferred_sites() == PINNED_DEFERRED_SITES


def test_every_group_of_the_harness_has_its_own_test_file():
    tree = ast.parse((REPO_ROOT / "test_scripts" / "vector_reentrancy_harness.py").read_text(encoding="utf-8"))
    groups = next(
        ast.literal_eval(node.value) for node in tree.body
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "GROUPS" for t in node.targets)
    )
    for key in groups:
        text = (REPO_ROOT / "test_scripts" / f"test_vector_reentrancy_{key}.py").read_text(encoding="utf-8")
        assert f'GROUPS["{key}"]' in text, key
