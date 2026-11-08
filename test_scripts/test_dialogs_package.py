from __future__ import annotations

import os


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_password_dialog_importable():
    from view.dialogs import PDFPasswordDialog

    assert PDFPasswordDialog is not None


def test_merge_dialog_importable():
    from view.dialogs import MergePdfDialog

    assert MergePdfDialog is not None


def test_optimize_dialog_importable():
    from view.dialogs import OptimizePdfDialog

    assert OptimizePdfDialog is not None


def test_watermark_dialog_importable():
    from view.dialogs import WatermarkDialog

    assert WatermarkDialog is not None


def test_export_dialog_importable():
    from view.dialogs import ExportPagesDialog

    assert ExportPagesDialog is not None


def test_audit_classes_importable():
    from view.dialogs import AuditStackedBar, PdfAuditReportDialog

    assert AuditStackedBar and PdfAuditReportDialog


def test_legacy_import_path_still_works(qapp):
    from view.pdf_view import (
        ExportPagesDialog,
        MergePdfDialog,
        OptimizePdfDialog,
        PDFPasswordDialog,
        PdfAuditReportDialog,
        WatermarkDialog,
    )

    assert OptimizePdfDialog is not None
    assert MergePdfDialog is not None
    assert PDFPasswordDialog is not None
    assert ExportPagesDialog is not None
    assert WatermarkDialog is not None
    assert PdfAuditReportDialog is not None


def test_password_dialog_basic(qapp):
    from view.dialogs import PDFPasswordDialog

    dlg = PDFPasswordDialog()
    assert dlg.get_password() == ""


def test_password_dialog_starts_masked_and_toggle_reveals(qapp):
    from PySide6.QtWidgets import QLineEdit

    from view.dialogs import PDFPasswordDialog

    dlg = PDFPasswordDialog(file_path="locked.pdf")
    # The credential must be masked before the user types anything (CWE-549).
    assert dlg.password_edit.echoMode() == QLineEdit.EchoMode.Password
    # The checkbox is a "hide" toggle: checked == masked, so it starts checked.
    assert dlg.hide_password_cb.isChecked() is True

    dlg.hide_password_cb.setChecked(False)
    assert dlg.password_edit.echoMode() == QLineEdit.EchoMode.Normal
    dlg.hide_password_cb.setChecked(True)
    assert dlg.password_edit.echoMode() == QLineEdit.EchoMode.Password

    dlg.password_edit.setText("  secret  ")
    assert dlg.get_password() == "secret"


def test_export_dialog_basic(qapp):
    from view.dialogs import ExportPagesDialog

    dlg = ExportPagesDialog(total_pages=10, current_page=3)
    pages, dpi, as_image = dlg.get_values()
    assert pages == [3]
    assert dpi == 300
    assert as_image is False
