from __future__ import annotations

import argparse
import functools
import logging
import os
import sys
from typing import Any

# Frozen builds re-run the app exe as their own children (src.render_worker.launch). Dispatch
# before any Qt or app import: a child must never construct a GUI or enter single-instance handoff.
# A windowed frozen child that raises would open PyInstaller's modal error dialog and hang the
# parent's wait, so any escaping exception becomes a stderr traceback plus a plain exit code.
_CHILD_FAILURE_EXIT = 70


def _run_child(entry) -> None:
    try:
        code = entry()
    except SystemExit:
        raise
    except BaseException:
        if sys.stderr is not None:
            import traceback

            traceback.print_exc(file=sys.stderr)
        raise SystemExit(_CHILD_FAILURE_EXIT) from None
    raise SystemExit(code)


def _render_worker_entry() -> int:
    from src.render_worker.worker_main import main

    return main()


def _print_helper_entry() -> int:
    from src.printing.helper_main import main

    return main(sys.argv[2:])


def _recent_probe_entry() -> int:
    from utils.recent_file_worker import main

    main()
    return 0


def _object_probe_entry() -> int:
    from src.object_probe.helper_main import main

    return main()


if __name__ == "__main__" and sys.argv[1:2] == ["--render-worker"]:
    _run_child(_render_worker_entry)
if __name__ == "__main__" and sys.argv[1:2] == ["--print-helper"]:
    _run_child(_print_helper_entry)
if __name__ == "__main__" and sys.argv[1:2] == ["--recent-probe"]:
    _run_child(_recent_probe_entry)
if __name__ == "__main__" and sys.argv[1:2] == ["--object-probe"]:
    _run_child(_object_probe_entry)

from utils import timeline  # noqa: E402

# PDF_EDITOR_TIMELINE=<file>: opt-in first-sharp-paint timeline (children above never reach this).
# A spawned multiprocessing worker (ProcessPoolExecutor) re-imports this file as __mp_main__: it must not write.
if __name__ != "__mp_main__":
    timeline.start()

from utils.app_identity import APP_USER_MODEL_ID, ARGPARSE_PROG  # noqa: E402


def _configure_logging() -> logging.Logger:
    # Default to WARNING for shipped builds so absolute file paths and full
    # tracebacks are not emitted to the console; opt into DEBUG via the
    # PDF_EDITOR_DEBUG environment variable (any non-empty value).
    level = logging.DEBUG if os.environ.get("PDF_EDITOR_DEBUG") else logging.WARNING
    logging.basicConfig(level=level, format="%(asctime)s - %(levelname)s - %(message)s")
    return logging.getLogger(__name__)


def parse_cli(argv: list[str] | None = None) -> argparse.Namespace:
    cli_args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog=ARGPARSE_PROG)
    parser.add_argument("files", nargs="*", help="PDF files to open")
    parser.add_argument("--merge", dest="merge_output", metavar="OUTPUT", help="Merge inputs into OUTPUT and exit")
    args = parser.parse_args(cli_args)
    if args.merge_output and not args.files:
        parser.error("--merge requires at least one input file")
    return args


def run_merge_and_exit(args: argparse.Namespace) -> int:
    from model.headless_merge import headless_merge

    headless_merge(args.files, args.merge_output)
    return 0


def _set_windows_app_user_model_id() -> None:
    """Give Windows an explicit AppUserModelID so the taskbar uses the app's own
    window icon and grouping instead of inheriting the host python(w).exe
    identity. No-op off Windows. Must run before the first window is shown.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (OSError, AttributeError):  # pragma: no cover - Windows-only shell call
        pass


_REJECTED_CLI_FILES_SHOWN = 10


def _rejected_cli_files_message(rejected: list[str]) -> str:
    """Traditional Chinese text naming the command-line files that cannot be opened."""
    shown = rejected[:_REJECTED_CLI_FILES_SHOWN]
    lines = ["以下檔案無法開啟（檔案不存在、無法存取，或副檔名不是 .pdf）：", ""]
    lines.extend(f"• {name}" for name in shown)
    hidden = len(rejected) - len(shown)
    if hidden > 0:
        lines.append(f"…以及另外 {hidden} 個檔案")
    return "\n".join(lines)


def _show_rejected_cli_files_dialog(rejected: list[str]) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from view.message_boxes import plain_text

    app = QApplication.instance()
    if app is None:
        # A hand-off runs before any application exists; the box needs one, with the identity and
        # icon the (window-first) launch used to give it.
        from view.icons import load_app_icon

        _set_windows_app_user_model_id()
        app = QApplication([sys.argv[0]])
        app.setWindowIcon(load_app_icon())
    QMessageBox.warning(None, "無法開啟檔案", plain_text(_rejected_cli_files_message(rejected)))


def _hand_off_to_running_instance(cli_args: list[str]) -> int:
    """Second launch: forward the files to the running instance (exit code).

    The receiver rejects a whole message if any token fails its filter, which
    used to drop the valid files with no message (F11-3). The same per-token
    predicate runs here first: the valid tokens go as ONE message so they open,
    and the rejected ones are named in a dialog (shown after the hand-off so the
    valid files are not held up by a modal box). Nothing is forwarded only when
    every token was rejected; a bare launch forwards the empty message, which
    raises the running window. The receiver's own filter is unchanged."""
    from utils.single_instance import partition_forwardable_argv, send_to_running_instance

    valid, rejected = partition_forwardable_argv(cli_args)
    forwarded = send_to_running_instance(valid) if valid or not rejected else False
    if rejected:
        _show_rejected_cli_files_dialog(rejected)
    return 0 if forwarded else 1


class _ForwardedPaths:
    """Hand-offs that arrive before the window exists.

    The single-instance server is up before the view is built, so a message can land while the
    view is still being constructed. It is held and replayed, in order, on the first event-loop
    turn after ``bind`` (as a socket backlog would be); delivery is direct afterwards."""

    def __init__(self) -> None:
        self._handler: Any = None
        self._held: list[list[str]] = []
        self._live = False

    def deliver(self, paths: list[str]) -> None:
        if self._live:
            self._handler(paths)
        else:
            self._held.append(list(paths))

    def bind(self, handler: Any) -> None:
        from PySide6.QtCore import QTimer

        self._handler = handler
        QTimer.singleShot(0, self._replay)

    def _replay(self) -> None:
        # One failing message must cost only itself (as a throwing callback always did), and the
        # buffer must go live regardless, or every later hand-off would be acked and dropped.
        try:
            while self._held:
                paths = self._held.pop(0)
                try:
                    self._handler(paths)
                except Exception:
                    logging.getLogger(__name__).exception("held hand-off could not be delivered")
        finally:
            self._live = True


def run(argv: list[str] | None = None, start_event_loop: bool = True) -> int | dict[str, Any]:
    args = parse_cli(argv)
    cli_args = list(args.files)

    _configure_logging()

    if args.merge_output:
        return run_merge_and_exit(args)

    if start_event_loop:
        # A second launch never builds a window: with a live primary it hands off before any Qt
        # application, QtWidgets import or view construction (the probe needs only QtNetwork).
        from utils.single_instance import running_instance_alive

        if running_instance_alive():
            return _hand_off_to_running_instance(cli_args)

    _set_windows_app_user_model_id()

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0], *cli_args])

    forwarded = _ForwardedPaths()
    server = None
    if start_event_loop:
        # Become the server (or lose the race and hand off) before the heavy view imports and the
        # window build; hand-offs that arrive meanwhile are held by ``forwarded``.
        from utils.single_instance import try_become_server

        server = try_become_server(forwarded.deliver)
        if server is None:
            return _hand_off_to_running_instance(cli_args)

    from view.icons import load_app_icon
    from view.pdf_view import PDFView

    # App-wide default icon so dialogs/secondary windows inherit it too.
    app.setWindowIcon(load_app_icon())

    view = PDFView(defer_heavy_panels=not cli_args)
    # Apply the saved theme once here, at the composition root, so the view
    # constructor stays free of global side effects and the switcher is live
    # even on the empty shell (before any controller exists).
    view.apply_initial_theme()
    timeline.mark("view_built")
    startup_ctx: dict[str, Any] = {
        "app": app,
        "model": None,
        "view": view,
        "controller": None,
        "single_instance_server": server,
        "secondary_windows": [],
    }

    def create_detached_window(payload, global_pos) -> bool:
        from controller.pdf_controller import PDFController
        from model.pdf_model import PDFModel
        from model.text_commit.dto import TextCommitSettings

        detached_view = PDFView()
        detached_view.apply_initial_theme()
        detached_model = PDFModel(
            text_commit_settings=TextCommitSettings.from_env(os.environ)
        )
        session_id = detached_model.import_session_transfer(payload)
        detached_controller = PDFController(detached_model, detached_view, render_client=startup_ctx.get('render_client'))
        detached_view.controller = detached_controller
        detached_controller.activate()
        detached_controller.set_session_handoff_callback(functools.partial(hand_off_session, detached_view))
        state = detached_controller._get_ui_state(session_id)
        state.current_page = min(payload.current_page, len(detached_model.doc) - 1)
        state.scale = payload.scale
        state.color_profile = payload.color_profile
        detached_controller._refresh_document_tabs()
        detached_controller._render_active_session(initial_page_idx=state.current_page)
        context = {
            "model": detached_model,
            "view": detached_view,
            "controller": detached_controller,
        }
        startup_ctx["secondary_windows"].append(context)

        def release_context() -> None:
            detached_controller.retire_background()
            detached_controller.release_render_owner()
            detached_model.close()
            if context in startup_ctx["secondary_windows"]:
                startup_ctx["secondary_windows"].remove(context)

        detached_view.destroyed.connect(release_context)
        if hasattr(global_pos, "x") and hasattr(global_pos, "y"):
            detached_view.move(global_pos)
        detached_view.show()
        detached_view.raise_()
        detached_view.activateWindow()
        from PySide6.QtCore import Qt

        detached_view.graphics_view.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        return True

    def _window_contexts() -> list[tuple[Any, Any]]:
        """(view, controller) of every editor window, primary first."""
        contexts = [(startup_ctx["view"], startup_ctx["controller"])]
        contexts.extend((ctx["view"], ctx["controller"]) for ctx in startup_ctx["secondary_windows"])
        return contexts

    def _drop_target_window(source_view: Any, global_pos: Any) -> tuple[Any, Any] | None:
        """The other editor window under ``global_pos`` (topmost), if any."""
        from PySide6.QtWidgets import QApplication

        if not (hasattr(global_pos, "x") and hasattr(global_pos, "y")):
            return None
        widget = QApplication.widgetAt(global_pos)
        window = widget.window() if widget is not None else None
        if window is None or window is source_view or not window.isVisible():
            return None
        for target_view, target_controller in _window_contexts():
            if target_view is window:
                if target_controller is None and target_view is startup_ctx["view"]:
                    target_controller = attach_and_activate_controller()
                    target_view.ensure_heavy_panels_initialized()
                return (target_view, target_controller) if target_controller is not None else None
        return None

    def _close_if_emptied_secondary(source_view: Any) -> None:
        if source_view is startup_ctx["view"]:
            return  # the primary keeps its empty shell, as after Ctrl+W
        for ctx in startup_ctx["secondary_windows"]:
            if ctx["view"] is source_view and not ctx["model"].session_ids:
                source_view.close()
                return

    def hand_off_session(source_view: Any, payload: Any, global_pos: Any) -> bool:
        """A tab dragged out of ``source_view``: released over another editor
        window it moves there (to_Update line 25), anywhere else it opens a
        new window. ``True`` lets the sender drop its copy of the tab."""
        target = _drop_target_window(source_view, global_pos)
        if target is None:
            return create_detached_window(payload, global_pos)
        target_view, target_controller = target
        if not target_controller.adopt_transferred_session(payload):
            return False
        if target_view.isMinimized():
            target_view.showNormal()
        target_view.raise_()
        target_view.activateWindow()
        from PySide6.QtCore import Qt, QTimer

        target_view.graphics_view.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        # After the sender has closed its copy of the session.
        QTimer.singleShot(0, functools.partial(_close_if_emptied_secondary, source_view))
        return True

    def attach_and_activate_controller() -> Any:
        controller = startup_ctx["controller"]
        if controller is not None:
            return controller
        from controller.pdf_controller import PDFController
        from model.pdf_model import PDFModel
        from model.text_commit.dto import TextCommitSettings

        model = PDFModel(
            text_commit_settings=TextCommitSettings.from_env(os.environ)
        )
        controller = PDFController(model, view, render_client=startup_ctx.get('render_client'))
        view.destroyed.connect(controller.release_render_owner)
        view.controller = controller
        controller.activate()
        controller.set_session_handoff_callback(functools.partial(hand_off_session, view))
        startup_ctx["model"] = model
        startup_ctx["controller"] = controller
        for path in view.drain_pending_open_paths():
            controller.open_pdf(path)
        return controller

    def handle_forwarded_paths(paths: list[str]) -> None:
        controller = startup_ctx["controller"]
        if controller is not None:
            controller.handle_forwarded_cli(paths)
            return
        if paths:
            view._queue_or_open_paths(paths)
        if view.isMinimized():
            view.showNormal()
        view.raise_()
        view.activateWindow()

    def _try_promote_secondary() -> None:
        primary_view = startup_ctx["view"]
        if primary_view.isVisible():
            return
        secondaries = startup_ctx["secondary_windows"]
        if not secondaries:
            return
        promoted = secondaries.pop(0)
        old_model = startup_ctx["model"]
        old_controller = startup_ctx['controller']
        if old_controller is not None:
            # Its workers leave the window contexts here but stay in the worker registry until
            # finished, so the final quit still waits for them.
            old_controller.retire_background()
            old_controller.release_render_owner()
        if old_model is not None:
            old_model.close()
        startup_ctx["view"] = promoted["view"]
        startup_ctx["model"] = promoted["model"]
        startup_ctx["controller"] = promoted["controller"]
        _install_close_promotion(promoted["view"])

    def _install_close_promotion(target_view: Any) -> None:
        from PySide6.QtCore import QEvent, QObject, QTimer

        class _CloseWatcher(QObject):
            def eventFilter(self, obj: Any, event: Any) -> bool:
                if event.type() == QEvent.Close:
                    QTimer.singleShot(0, _try_promote_secondary)
                return False

        watcher = _CloseWatcher(target_view)
        target_view.installEventFilter(watcher)

    _install_close_promotion(view)

    view.sig_backend_bootstrap_requested.connect(attach_and_activate_controller)

    if start_event_loop:
        forwarded.bind(handle_forwarded_paths)

    from src.render_worker.config import render_worker_mode
    if render_worker_mode() == 'process':
        from src.render_worker.admission import (
            OPTIONAL_MAX_DOC_BYTES,
            OPTIONAL_RENDER_CHARGE,
            REQUIRED_RENDER_CHARGE,
            app_ledger,
            expansion_allowed,
        )
        from src.render_worker.config import render_worker_count
        from src.render_worker.process_pool import RenderProcessPool

        ledger = app_ledger(app)
        client = RenderProcessPool(
            app,
            resource_ledger=ledger,
            required_charge=REQUIRED_RENDER_CHARGE,
            optional_charge=OPTIONAL_RENDER_CHARGE,
            optional_max_doc_bytes=OPTIONAL_MAX_DOC_BYTES,
            max_children=max(2, render_worker_count()),
            expansion_allowed=expansion_allowed,
        )
        startup_ctx['render_client'] = client
        startup_ctx['resource_ledger'] = ledger
        # Keep the event loop alive to reap the owned raster child. The normal
        # last-window close must not destroy a running QProcess on the GUI thread.
        # QProcess.start is asynchronous: overlap interpreter/worker imports
        # with native window creation and CLI document initialization.
        client.start()

    from PySide6.QtCore import QTimer
    from controller.object_probe_runner import ObjectProbeRunner
    from controller.worker_registry import DEFAULT_DRAIN_TIMEOUT_MS
    from controller.worker_registry import get_registry as get_worker_registry
    from controller.recent_file_probe import RecentFileProbe

    recent_probe = RecentFileProbe.for_app(app, ledger=startup_ctx.get('resource_ledger'))
    startup_ctx['recent_probe'] = recent_probe
    # Nothing is started here: the child launches on the first cold table analysis.
    object_probe = ObjectProbeRunner.for_app(app, ledger=startup_ctx.get('resource_ledger'))
    app.setQuitOnLastWindowClosed(False)
    previous_shutdown = getattr(app, '_pdf_owned_shutdown', None)
    if previous_shutdown is not None:
        app.lastWindowClosed.disconnect(previous_shutdown)
        app.aboutToQuit.disconnect(previous_shutdown)
    generation = object()
    app._pdf_shutdown_generation = generation
    services = [service for service in getattr(app, '_pdf_owned_services', ())
                if service._process is not None]
    for service in (recent_probe, object_probe, startup_ctx.get('render_client')):
        if service is not None and service not in services:
            services.append(service)
    app._pdf_owned_services = services
    services_shutdown_started = False
    draining = False  # re-entrancy guard of ONE pass (quit() emits aboutToQuit synchronously)
    quit_requested = False

    def finish_owned_shutdown() -> None:
        nonlocal quit_requested
        # A timer from a previous run on the same QApplication must not quit a
        # replacement run. Retiring services are carried into the new registry.
        if app._pdf_shutdown_generation is not generation:
            return
        if all(service._process is None for service in services):
            if not quit_requested:
                # aboutToQuit is synchronous: mark before quit can emit it.
                quit_requested = True
                app.quit()
        else:
            QTimer.singleShot(10, finish_owned_shutdown)

    def shutdown_owned_processes() -> None:
        nonlocal services_shutdown_started, draining
        if draining:
            return
        draining = True
        try:
            if not services_shutdown_started:
                services_shutdown_started = True
                if server is not None:
                    from utils.single_instance import release_server

                    release_server(server)
            # Controller worker threads: the registry, not the window contexts, owns them (a retired
            # primary's worker is in no context).  Cancel and wait, bounded; a survivor is logged
            # and stays registered, so the next pass (lastWindowClosed, then aboutToQuit) waits again.
            survivors = get_worker_registry().shutdown_all(DEFAULT_DRAIN_TIMEOUT_MS)
            if survivors:
                logging.getLogger(__name__).warning(
                    "quitting with %d background worker(s) still running after %d ms: %r",
                    len(survivors), DEFAULT_DRAIN_TIMEOUT_MS, survivors,
                )
            for service in services:
                service.shutdown()
            finish_owned_shutdown()
        finally:
            draining = False

    app._pdf_owned_shutdown = shutdown_owned_processes
    app.lastWindowClosed.connect(shutdown_owned_processes)
    app.aboutToQuit.connect(shutdown_owned_processes)

    view.show()
    timeline.mark("shown")

    if cli_args:
        attach_and_activate_controller()
        view.ensure_heavy_panels_initialized()
        for path in cli_args:
            startup_ctx["controller"].open_pdf(path)
    if not start_event_loop:
        return startup_ctx

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
