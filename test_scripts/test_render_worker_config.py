from __future__ import annotations

import sys

from src.render_worker.config import render_worker_mode


def test_modes_and_frozen_default(monkeypatch, caplog):
    monkeypatch.delenv("PDF_EDITOR_RENDER_WORKER", raising=False)
    assert render_worker_mode() == "thread"
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "process")
    assert render_worker_mode() == "process"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert render_worker_mode() == "thread"
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "invalid")
    assert render_worker_mode() == render_worker_mode() == "thread"
    assert len([r for r in caplog.records if "render worker" in r.message]) == 1
