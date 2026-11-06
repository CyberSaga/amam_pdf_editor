from __future__ import annotations

import os
from contextlib import contextmanager
from queue import Queue
import subprocess
import sys
import time
from threading import Thread

import fitz
import pytest

from model.page_raster import rasterize_page
from src.render_worker.protocol import FrameDecoder, encode_prefix


# communicate's deadline bounds every read, including startup and shutdown.
# Child processes run in their own supervised run_suite job.
def _run(commands, timeout=10, bootstrap=None):
    wire = b"".join(encode_prefix(header, len(body)) + body for header, body in commands)
    command = ([sys.executable, "-c", bootstrap] if bootstrap is not None else
               [sys.executable, "-m", "src.render_worker.worker_main"])
    proc = subprocess.run(command,
                          input=wire, capture_output=True, timeout=timeout)
    assert proc.returncode == 0, proc.stderr
    decoder = FrameDecoder()
    frames = decoder.feed(proc.stdout)
    assert not decoder.incomplete
    return frames, proc.stderr


def _pdf():
    with fitz.open() as doc:
        page = doc.new_page(width=120, height=160)
        page.insert_text((10, 30), "Child pixels")
        page.add_rect_annot(fitz.Rect(10, 50, 70, 90)).update()
        return doc.tobytes()


@contextmanager
def _live_child():
    """Bound every interactive read; cleanup also has a hard deadline."""
    proc = subprocess.Popen([sys.executable, "-m", "src.render_worker.worker_main"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    replies = Queue()
    decoder = FrameDecoder()

    def read_frames():
        try:
            while chunk := proc.stdout.read1(65536):
                for frame in decoder.feed(chunk):
                    replies.put(frame)
        except Exception as exc:
            replies.put(exc)

    reader = Thread(target=read_frames, daemon=True)
    reader.start()

    def receive():
        result = replies.get(timeout=10)
        if isinstance(result, Exception):
            raise result
        return result

    def send(header, body=b""):
        proc.stdin.write(encode_prefix(header, len(body)))
        proc.stdin.write(body)
        proc.stdin.flush()
        return receive()

    try:
        assert receive().header["type"] == "ready"
        yield send
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)
        reader.join(timeout=2)
        proc.stdout.close()
        proc.stderr.close()


@pytest.mark.parametrize("profile", ["srgb", "gray", "cmyk"])
def test_child_ready_and_exact_pixels(profile):
    data = _pdf()
    frames, _ = _run([
        ({"type": "load_bytes", "doc_key": "d"}, data),
        ({"type": "render", "job": "j", "doc_key": "d", "page": 0,
          "scale": 1.25, "profile": profile, "kind": "page"}, b""),
        ({"type": "quit"}, b""),
    ])
    assert frames[0].header["type"] == "ready"
    assert frames[0].header["pid"] > 0
    assert frames[0].header["fitz_version"] == fitz.VersionBind
    assert [f.header["type"] for f in frames] == ["ready", "doc_ready", "image"]
    with fitz.open(stream=data, filetype="pdf") as doc:
        expected = rasterize_page(doc, 0, 1.25, profile)
    assert frames[-1].body == expected.samples
    assert frames[-1].header["stride"] == expected.stride


def test_child_eof_and_bad_document_keep_stdout_framed():
    frames, stderr = _run([({"type": "load_bytes", "doc_key": "d"}, b"not a PDF")])
    assert frames[-1].header == {"type": "doc_failed", "doc_key": "d", "reason": "open"}
    assert b"Traceback" not in stderr
    assert _run([], timeout=2)[0][0].header["type"] == "ready"


def test_child_native_repair_warnings_do_not_corrupt_stdout():
    broken = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
              b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
              b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 100 100]>>endobj\n"
              b"trailer<</Root 1 0 R>>\n%%EOF")
    bootstrap = (
        "from src.render_worker import worker_main as w; "
        "w.fitz.TOOLS.mupdf_display_warnings(True); "
        "original=w.Worker.load; "
        "w.Worker.load=lambda self, frame: (w.os.write(1, b'native diagnostic\\n'), "
        "original(self, frame)); "
    )
    commands = [({"type": "load_bytes", "doc_key": "d"}, broken)]
    frames, stderr = _run(commands, bootstrap=bootstrap + "raise SystemExit(w.main())")
    assert frames[-1].header["type"] == "doc_ready"
    assert b"repair" in stderr.lower()
    assert b"native diagnostic" in stderr
    # Negative control: removing native fd redirection must break the decoder.
    from src.render_worker.protocol import ProtocolError
    with pytest.raises(ProtocolError):
        _run(commands, bootstrap=bootstrap +
             "w.os.dup2=lambda *args: None; raise SystemExit(w.main())")


def test_child_path_load_changed_stat_and_handle_release(tmp_path):
    path = tmp_path / "doc.pdf"
    path.write_bytes(_pdf())
    stat = path.stat()
    header = {"type": "load_path", "doc_key": "d", "path": str(path),
              "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    with _live_child() as send:
        assert send(dict(header, size=stat.st_size + 1)).header["reason"] == "changed"
        assert send(header).header["type"] == "doc_ready"
        replacement = tmp_path / "replacement.pdf"
        replacement.write_bytes(_pdf())
        # Must succeed while the child is alive and still owns its fitz doc.
        os.replace(replacement, path)
        assert send({"type": "render", "job": "j", "doc_key": "d", "page": 0,
                     "scale": 1, "profile": "srgb", "kind": "page"}).header["type"] == "image"


def test_child_password_body_is_not_echoed(tmp_path):
    path = tmp_path / "secret.pdf"
    with fitz.open(stream=_pdf(), filetype="pdf") as doc:
        doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256,
                 owner_pw="owner-secret", user_pw="s3cret")
    stat = path.stat()
    header = {"type": "load_path", "doc_key": "d", "path": str(path),
              "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    frames, stderr = _run([(header, b"wrong-s3cret"), (header, b"s3cret")])
    assert frames[1].header["reason"] == "auth"
    assert frames[2].header["type"] == "doc_ready"
    assert b"s3cret" not in stderr
    assert all("s3cret" not in str(frame.header) for frame in frames)


def test_child_refuses_oversize_before_raster():
    with fitz.open() as doc:
        doc.new_page(width=200000, height=200000)
        data = doc.tobytes()
    with _live_child() as send:
        assert send({"type": "load_bytes", "doc_key": "d"}, data).header["type"] == "doc_ready"
        started = time.monotonic()
        reply = send({"type": "render", "job": "j", "doc_key": "d", "page": 0,
                      "scale": 2, "profile": "srgb", "kind": "page"})
        assert time.monotonic() - started < 1
        assert reply.header["reason"] == "oversize"


def test_child_has_no_qt_or_pdf_model_imports():
    result = subprocess.run([sys.executable, "-c",
        "import src.render_worker.worker_main, sys; "
        "assert 'PySide6' not in sys.modules; assert 'model.pdf_model' not in sys.modules"],
        capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_child_tests_are_isolated():
    from scripts.run_suite import classify
    assert classify("", "test_scripts/test_render_worker_child.py") == "qt"


def test_suite_pins_thread():
    assert os.environ["PDF_EDITOR_RENDER_WORKER"] == "thread"


def test_benchmark_selects_explicit_mode(monkeypatch):
    from argparse import Namespace
    from scripts import benchmark_ui_perf as benchmark
    monkeypatch.setenv("PDF_EDITOR_RENDER_WORKER", "process")
    assert benchmark._child_env(Namespace(render_worker="thread"))["PDF_EDITOR_RENDER_WORKER"] == "thread"
    assert benchmark._child_env(Namespace(render_worker="process"))["PDF_EDITOR_RENDER_WORKER"] == "process"
    modes = []
    monkeypatch.setattr(benchmark, "_parent_main", lambda args: modes.append(args.render_worker) or 0)
    assert benchmark.main([]) == benchmark.main(["--render-worker", "process"]) == 0
    assert modes == ["thread", "process"]
