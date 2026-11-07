from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

import controller.print_coordinator as print_module

pytest_plugins = ('test_scripts.test_search_jump_highlight',)
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('activate', [False, True])
def test_cold_controller_does_not_load_print_runtime(activate):
    script = '''
import json, sys
from controller.pdf_controller import PDFController
if int(sys.argv[1]):
    from PySide6.QtWidgets import QApplication
    from model.pdf_model import PDFModel
    from view.pdf_view import PDFView
    from test_scripts.qt_teardown import dispose_pdf_view
    app = QApplication([])
    model, view = PDFModel(), PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    controller.activate()
    dispose_pdf_view(view, controller, model)
print(json.dumps(sorted(m for m in sys.modules if m.startswith('src.printing'))))
'''
    result = subprocess.run([sys.executable, '-c', script, str(int(activate))],
                            cwd=ROOT, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    modules = json.loads(result.stdout.strip().splitlines()[-1])
    forbidden = {'src.printing.dispatcher', 'src.printing.print_dialog',
                 'src.printing.subprocess_runner'}
    assert not forbidden.intersection(modules), modules
    assert not any(name.startswith('src.printing.platforms') for name in modules)


def test_activation_leaves_print_bridge_and_dispatcher_uninitialized(mvc):
    model, view, controller = mvc
    controller.activate()
    coordinator = controller._print_coordinator
    assert coordinator.print_dispatcher is None
    assert coordinator._print_worker_bridge is None


def test_first_print_initializes_bridge_and_preserves_injected_dispatcher(mvc, pdf_path, monkeypatch):
    model, view, controller = mvc
    model.open_pdf(str(pdf_path))
    calls = []

    class Dispatcher:
        def list_printers(self):
            calls.append('list')
            return []

    dispatcher = Dispatcher()
    coordinator = controller._print_coordinator
    coordinator.print_dispatcher = dispatcher
    monkeypatch.setattr(print_module, 'show_error', lambda *args: calls.append('no printers'))
    controller.print_document()
    bridge = coordinator._print_worker_bridge
    assert bridge is not None
    assert calls == ['list', 'no printers']
    coordinator.connect_bridge()
    assert coordinator._print_worker_bridge is bridge
    assert coordinator.print_dispatcher is dispatcher


def test_print_exports_remain_real_classes_and_functions():
    import src.printing as package
    from src.printing import dispatcher, print_dialog, subprocess_runner

    assert package.PrintDispatcher is dispatcher.PrintDispatcher
    assert package.get_printer_driver is dispatcher.get_printer_driver
    assert print_module.PrintDispatcher is dispatcher.PrintDispatcher
    assert print_module.UnifiedPrintDialog is print_dialog.UnifiedPrintDialog
    assert print_module.PrintSubprocessRunner is subprocess_runner.PrintSubprocessRunner
