"""Shared message-box helpers (moved from utils/helpers.py in PR-8).

utils/ must stay Qt-widget-free and below every layer; a QMessageBox helper
belongs to the View layer. Controller importing view helpers is legal
(Controller coordinates View and Model).
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


def show_error(parent, message: str) -> None:
    """Show an error message."""
    QMessageBox.critical(parent, "錯誤", message)


def confirm_degraded_fallback(parent, message: str) -> bool:
    """Ask the user to confirm a legacy-fidelity fallback commit before it
    happens. Defaults to No (Esc/close = decline, never a silent proceed)."""
    result = QMessageBox.question(
        parent,
        "確認改用重建文字",
        message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes


def _confirm_warning(
    parent, title: str, text: str, accept_label: str, informative: str | None = None
) -> bool:
    """A warning box with ``accept_label`` and "取消"; the default and Esc are
    取消, so only an explicit click on the accept button returns True."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    if informative is not None:
        box.setInformativeText(informative)
    accept_btn = box.addButton(accept_label, QMessageBox.ButtonRole.AcceptRole)
    cancel_btn = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel_btn)
    box.setEscapeButton(cancel_btn)
    box.exec()
    return box.clickedButton() is accept_btn


def confirm_place_anyway(parent, message: str) -> bool:
    """Ask, for ONE dragged edit, whether to place it where the user dropped it
    although it would be drawn over untouched text (S17 / TODOS F13-VF-4c).

    Two buttons, "仍要放在這裡" and "取消"; the default and Esc are 取消, so only
    an explicit click lifts the overprint guard.  The choice is per edit; no
    setting remembers it."""
    return _confirm_warning(parent, "文字會蓋到旁邊的文字", message, "仍要放在這裡")


def confirm_signature_loss(parent, text: str, informative: str) -> bool:
    """Ask before a save invalidates a digital signature (SIG-DIALOG).

    Two buttons, "仍要儲存" and "取消"; the default and Esc are 取消, so only an
    explicit click writes the file."""
    return _confirm_warning(parent, "數位簽章將失效", text, "仍要儲存", informative)
