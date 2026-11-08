from __future__ import annotations

import sys

from src.render_worker.config import render_worker_mode


def test_modes_and_frozen_default(monkeypatch, caplog):
    monkeypatch.delenv("PDF_EDITOR_RENDER_WORKER", raising=False)
    assert render_worker_mode() == "process", "the raster child is the normal default"
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "thread")
    assert render_worker_mode() == "thread", "thread stays the supported fallback"
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "process")
    assert render_worker_mode() == "process"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert render_worker_mode() == "thread"
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "invalid")
    assert render_worker_mode() == render_worker_mode() == "process"
    assert len([r for r in caplog.records if "render worker" in r.message]) == 1


def test_explicit_worker_count_wins_and_anything_else_means_the_core_based_default(monkeypatch):
    from src.render_worker import config

    monkeypatch.setattr(config.os, "cpu_count", lambda: 4)
    for value, expected in (("1", 1), ("2", 2), ("3", 3), ("4", 2), ("x", 2), ("", 2)):
        monkeypatch.setenv("PDF_EDITOR_RENDER_WORKERS", value)
        assert config.render_worker_count() == expected


def test_default_worker_count_follows_the_core_count(monkeypatch):
    from src.render_worker import config

    monkeypatch.delenv("PDF_EDITOR_RENDER_WORKERS", raising=False)
    for cpus, expected in ((None, 1), (1, 1), (2, 1), (3, 1), (4, 2), (7, 2), (8, 3), (22, 3)):
        monkeypatch.setattr(config.os, "cpu_count", lambda cpus=cpus: cpus)
        assert config.render_worker_count() == expected
