"""Card B3 follow-up (H21): the one-shot ``vector-scan`` child kind.

Covers the file transport of a ``VectorIndex`` (one ``numpy.save`` file), the child side
(``src.object_probe.helper_main`` kind ``vector-scan``), the runner's acceptance of its answer shape,
and the coordinator's child path (done / refused / cancel / crash / corrupt / missing / late answer,
temp directory always deleted, admission closed).  A fake runner drives the protocol; one test runs the
real child process."""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QObject, QProcess, Signal

from controller.object_probe_runner import ObjectProbeRunner
from controller.vector_edit_coordinator import VectorEditCoordinator
from controller.worker_registry import get_registry
from model.vector_paths import VectorPageRefused, scan_page
from model.vector_paths import transport
from src.object_probe import helper_main

REPO_ROOT = Path(__file__).resolve().parents[1]
FRAME = (1.0, 0.0, 0.0, -1.0, 0.0, 100.0)
STREAM = b"q 1 0 0 1 5 5 cm 10 10 m 90 90 l S Q\n0 0 m 50 0 50 50 0 50 c f\n"


def _index():
    return scan_page((STREAM,), FRAME)


def _same(a, b) -> None:
    for name in ("paths", "cubics", "segments", "blocks", "streams"):
        assert getattr(a, name).dtype == getattr(b, name).dtype, name
        assert getattr(a, name).tobytes() == getattr(b, name).tobytes(), name
    assert (a.indexed_end, a.stopped_at_inline_image, a.frame, a.stream_digests, a.nbytes, a.block_resources) == (
        b.indexed_end, b.stopped_at_inline_image, b.frame, b.stream_digests, b.nbytes, b.block_resources,
    )


# ------------------------------------------------------------------------------------ the file


def test_an_index_round_trips_through_one_npy_file(tmp_path):
    index = _index()
    path = tmp_path / "index.npy"
    transport.save_index(index, path)
    assert [p.name for p in tmp_path.iterdir()] == ["index.npy"]
    arr = np.load(path, allow_pickle=False)
    assert arr.dtype == np.uint8 and arr.ndim == 1
    _same(index, transport.load_index(path))


def test_a_loaded_index_is_writable_and_independent_of_the_file(tmp_path):
    path = tmp_path / "index.npy"
    transport.save_index(_index(), path)
    loaded = transport.load_index(path)
    os.remove(path)  # no memory map holds the file
    loaded.paths["flags"][0] = 1


def test_a_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        transport.load_index(tmp_path / "nope.npy")


@pytest.mark.parametrize("damage", ["truncate", "garbage", "wrong_dtype", "object_array", "empty", "trailing"])
def test_a_corrupt_file_raises_value_error(tmp_path, damage):
    path = tmp_path / "index.npy"
    transport.save_index(_index(), path)
    raw = path.read_bytes()
    if damage == "truncate":
        path.write_bytes(raw[: len(raw) - 50])
    elif damage == "garbage":
        path.write_bytes(b"this is not a numpy file at all" * 10)
    elif damage == "wrong_dtype":
        np.save(path, np.zeros(400, dtype=np.float64), allow_pickle=False)
    elif damage == "object_array":
        np.save(path, np.array([{"a": 1}], dtype=object), allow_pickle=True)
    elif damage == "empty":
        np.save(path, np.zeros(0, dtype=np.uint8), allow_pickle=False)
    else:  # extra bytes after the last table
        arr = np.load(path, allow_pickle=False)
        np.save(path, np.concatenate([arr, np.zeros(7, dtype=np.uint8)]), allow_pickle=False)
    with pytest.raises(ValueError):
        transport.load_index(path)


def test_a_file_with_an_inflated_count_is_corrupt(tmp_path):
    path = tmp_path / "index.npy"
    transport.save_index(_index(), path)
    arr = np.load(path, allow_pickle=False)
    meta_len = int.from_bytes(arr[:8].tobytes(), "little")
    meta = json.loads(arr[8 : 8 + meta_len].tobytes())
    meta["counts"]["paths"] += 5
    new_meta = json.dumps(meta).encode("utf-8")
    forged = np.concatenate(
        [np.frombuffer(len(new_meta).to_bytes(8, "little") + new_meta, dtype=np.uint8), arr[8 + meta_len :]]
    )
    np.save(path, forged, allow_pickle=False)
    with pytest.raises(ValueError):
        transport.load_index(path)


def test_bytes_after_the_npy_record_are_corrupt(tmp_path):
    path = tmp_path / "index.npy"
    transport.save_index(_index(), path)
    with open(path, "ab") as handle:
        handle.write(b"\x00" * 9)  # outside the array the NPY header describes
    with pytest.raises(ValueError):
        transport.load_index(path)


def _forge_header(path: Path, length: int) -> None:
    """An NPY file whose header claims ``length`` uint8 values, with (almost) no data behind it."""
    with open(path, "wb") as handle:
        np.lib.format.write_array_header_1_0(handle, {"descr": "|u1", "fortran_order": False, "shape": (length,)})
        handle.write(b"\x00" * 64)


def test_a_claimed_payload_over_the_budget_is_refused_before_any_allocation(tmp_path, monkeypatch):
    path = tmp_path / "index.npy"
    _forge_header(path, 1 << 40)
    monkeypatch.setattr(np, "load", lambda *a, **k: pytest.fail("np.load must not run"))
    monkeypatch.setattr(np, "empty", lambda *a, **k: pytest.fail("no allocation before the checks"))
    with pytest.raises(ValueError):
        transport.load_index(path)


def test_a_claimed_size_within_the_budget_but_longer_than_the_file_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "index.npy"
    _forge_header(path, 100 * 1024 * 1024)
    monkeypatch.setattr(np, "empty", lambda *a, **k: pytest.fail("no allocation before the checks"))
    with pytest.raises(ValueError):
        transport.load_index(path)


def test_the_payload_budget_is_a_named_constant(tmp_path, monkeypatch):
    path = tmp_path / "index.npy"
    transport.save_index(_index(), path)
    assert transport.MAX_PAYLOAD_BYTES == 512 * 1024 * 1024
    monkeypatch.setattr(transport, "MAX_PAYLOAD_BYTES", path.stat().st_size - 200)
    with pytest.raises(ValueError):
        transport.load_index(path)


def test_the_metadata_length_is_bounded_before_it_is_parsed(tmp_path, monkeypatch):
    path = tmp_path / "index.npy"
    transport.save_index(_index(), path)
    monkeypatch.setattr(transport, "MAX_META_BYTES", 16)
    monkeypatch.setattr(transport.json, "loads", lambda *a, **k: pytest.fail("json.loads must not run"))
    with pytest.raises(ValueError):
        transport.load_index(path)


def test_a_directory_is_not_a_regular_file(tmp_path):
    with pytest.raises((OSError, ValueError)):
        transport.load_index(tmp_path)


def _two_stream_index():
    return scan_page((STREAM, b"5 5 m 20 20 l S\n"), FRAME)


def _mutate_digests(index):
    index.stream_digests = (*index.stream_digests, b"\x00" * 32)


def _mutate(field, name, value, row=0):
    def apply(index):
        getattr(index, field)[name][row] = value

    return apply


@pytest.mark.parametrize(
    ("mutation", "label"),
    [
        (lambda index: setattr(index, "nbytes", index.nbytes + 1), "nbytes"),
        (_mutate_digests, "digest_count"),
        (_mutate("segments", "path", 999), "segment_path_range"),
        (_mutate("segments", "subpath", -1), "segment_subpath_negative"),
        (_mutate("paths", "seg_count", 10**6), "path_segment_range"),
        (_mutate("paths", "seg_start", -1), "path_segment_start_negative"),
        (_mutate("paths", "block", 50), "path_block_range"),
        (_mutate("cubics", "seg_start", 10**6), "cubic_segment_range"),
        (_mutate("cubics", "path", 77), "cubic_path_range"),
        (_mutate("blocks", "q_start", 10**5), "block_order"),
        (_mutate("streams", "global_start", 0, row=1), "stream_offsets_not_monotonic"),
        (_mutate("streams", "length", 1, row=0), "stream_lengths_not_contiguous"),
        (lambda index: setattr(index, "indexed_end", 10**9), "indexed_end"),
    ],
)
def test_a_size_preserving_inconsistency_is_corrupt(tmp_path, mutation, label):
    index = _two_stream_index()
    mutation(index)
    path = tmp_path / "index.npy"
    transport.save_index(index, path)  # the file is exactly as long as its header says
    with pytest.raises(ValueError):
        transport.load_index(path)


def test_a_richer_valid_index_passes_the_structure_checks(tmp_path):
    streams = (
        b"q 1 0 0 1 5 5 cm 10 10 m 90 90 l S Q\n",
        b"q 0 0 m 50 0 50 50 0 50 c f Q 1 0 0 RG 0 0 10 10 re S\n",
        b"q q 2 w 1 1 m 9 9 l S Q Q\n",
    )
    index = scan_page(streams, FRAME)
    path = tmp_path / "index.npy"
    transport.save_index(index, path)
    _same(index, transport.load_index(path))


def test_the_scanner_that_produced_the_index_travels_with_the_file(tmp_path):
    path = tmp_path / "index.npy"
    transport.save_index(_index(), path)
    loaded = transport.load_index(path)
    assert (loaded.scanner, loaded.accelerated) == ("G", False)


def test_importing_the_package_or_the_model_source_does_not_load_numpy_or_the_scanner():
    code = (
        "import sys, json\n"
        "import model.vector_paths as pkg\n"
        "from model.vector_paths import limits\n"
        "bad = [m for m in ('numpy', 'model.vector_paths.scan', 'model.vector_paths.transport') if m in sys.modules]\n"
        "print(json.dumps(bad))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
    assert proc.returncode == 0, proc.stderr[-400:]
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []


# ------------------------------------------------------------------------------- the child side


def _request(payloads, kind="vector-scan", mem=1 << 30) -> bytes:
    header = {"v": 2, "kind": kind, "sizes": [len(p) for p in payloads], "mem": mem}
    return json.dumps(header).encode("utf-8") + b"\n" + b"".join(payloads)


def _job_payloads(directory: Path, frame=FRAME, streams=(STREAM,)):
    head = json.dumps(
        {
            "frame": list(frame) if frame is not None else None,
            "dir": str(directory),
            "lengths": [len(s) for s in streams],
        }
    ).encode("ascii")
    return [head, b"".join(streams)]


def _run_main(monkeypatch, data: bytes):
    out = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(data)))
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=out))
    monkeypatch.setattr(helper_main, "apply_job_memory_limit", lambda mem: None)
    code = helper_main.main()
    return code, [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def test_the_child_writes_the_index_file_and_prints_its_name(monkeypatch, tmp_path):
    code, answers = _run_main(monkeypatch, _request(_job_payloads(tmp_path)))
    assert code == 0
    assert answers == [{"v": 2, "status": "complete", "scan_file": "index.npy"}]
    assert [p.name for p in tmp_path.iterdir()] == ["index.npy"]
    _same(_index(), transport.load_index(tmp_path / "index.npy"))


@pytest.mark.parametrize(
    ("frame", "streams", "code"),
    [
        ((0.0, 0.0, 0.0, 0.0, 0.0, 0.0), (STREAM,), "NO_FRAME"),
        (None, (STREAM,), "NO_FRAME"),
        (FRAME, (b"[ 1 2",), "SCAN_ERROR"),
    ],
)
def test_the_child_answers_a_scanner_refusal_with_its_code_and_no_file(monkeypatch, tmp_path, frame, streams, code):
    exit_code, answers = _run_main(monkeypatch, _request(_job_payloads(tmp_path, frame, streams)))
    assert exit_code == 0
    assert answers == [{"v": 2, "status": "refused", "code": code}]
    assert list(tmp_path.iterdir()) == []


def test_the_child_answers_analysis_failed_for_a_malformed_job_header(monkeypatch, tmp_path):
    exit_code, answers = _run_main(monkeypatch, _request([b"not json", STREAM]))
    assert exit_code == 0
    assert answers == [{"v": 2, "status": "analysis_failed"}]


@pytest.mark.parametrize(
    "lengths", [None, "x", [True], [-1], [3, 4], [len(STREAM) + 1], [len(STREAM) - 1], [0] * 200_001]
)
def test_the_child_rejects_a_manifest_that_does_not_describe_the_blob(monkeypatch, tmp_path, lengths):
    head = json.dumps({"frame": list(FRAME), "dir": str(tmp_path), "lengths": lengths}).encode("ascii")
    exit_code, answers = _run_main(monkeypatch, _request([head, STREAM]))
    assert exit_code == 0
    assert answers == [{"v": 2, "status": "analysis_failed"}]
    assert list(tmp_path.iterdir()) == []


def test_five_thousand_small_streams_fit_the_wire_header_and_scan_like_the_in_process_scan(monkeypatch, tmp_path):
    streams = tuple(b"%d 0 m 5 5 l S\n" % (k % 90) for k in range(5000))
    payloads = _job_payloads(tmp_path, FRAME, streams)
    request = _request(payloads)
    header = request.split(b"\n", 1)[0]
    assert len(header) < helper_main._MAX_HEADER_BYTES  # two payload sizes, whatever the stream count
    code, answers = _run_main(monkeypatch, request)
    assert code == 0 and answers == [{"v": 2, "status": "complete", "scan_file": "index.npy"}]
    _same(scan_page(streams, FRAME), transport.load_index(tmp_path / "index.npy"))


def test_the_child_refuses_a_missing_target_directory(monkeypatch, tmp_path):
    exit_code, answers = _run_main(monkeypatch, _request(_job_payloads(tmp_path / "absent")))
    assert exit_code == 0
    assert answers == [{"v": 2, "status": "analysis_failed"}]


def test_a_memory_error_while_scanning_is_resource_limited(monkeypatch, tmp_path):
    import model.vector_paths.scan as scan_mod

    def boom(*args, **kwargs):
        raise MemoryError

    monkeypatch.setattr(scan_mod, "scan_page", boom)
    exit_code, answers = _run_main(monkeypatch, _request(_job_payloads(tmp_path)))
    assert answers == [{"v": 2, "status": "resource_limited"}]
    assert list(tmp_path.iterdir()) == []


def test_the_real_child_process_answers_the_vector_scan_kind(tmp_path):
    from src.render_worker.launch import child_launch

    program, args = child_launch("object-probe")
    proc = subprocess.run(
        [program, *args], input=_request(_job_payloads(tmp_path), mem=1500 * 1024 * 1024),
        capture_output=True, timeout=120, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-400:]
    answer = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip().startswith(b"{")][-1]
    assert answer == {"v": 2, "status": "complete", "scan_file": "index.npy"}
    _same(_index(), transport.load_index(tmp_path / "index.npy"))


def test_the_child_never_imports_qt_for_this_kind():
    # PyMuPDF is imported incidentally (model.pdf_content_ops, model.vector_paths.commit_state); Qt never.
    code = (
        "import sys, json, io\n"
        "from src.object_probe import helper_main\n"
        "import model.vector_paths.transport\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6')]\n"
        "print(json.dumps(bad))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
    assert proc.returncode == 0, proc.stderr[-400:]
    assert json.loads(proc.stdout.strip().splitlines()[-1]) == []


# ----------------------------------------------------------------------- the runner's acceptance


def test_the_runner_accepts_the_vector_scan_answer_shapes():
    ok = {"v": 2, "status": "complete", "scan_file": "index.npy"}
    assert ObjectProbeRunner._answer_of(json.dumps(ok).encode(), "vector-scan") == ok
    refused = {"v": 2, "status": "refused", "code": "CHORD_CAP"}
    assert ObjectProbeRunner._answer_of(json.dumps(refused).encode(), "vector-scan") == refused


@pytest.mark.parametrize(
    ("answer", "kind"),
    [
        ({"v": 2, "status": "complete", "scan_file": "index.npy"}, "scan"),  # another kind's key shape
        ({"v": 2, "status": "complete", "scans": []}, "vector-scan"),
        ({"v": 2, "status": "complete", "scan_file": 7}, "vector-scan"),
        ({"v": 2, "status": "complete"}, "vector-scan"),
        ({"v": 2, "status": "refused", "code": "X", "scan_file": "index.npy"}, "vector-scan"),
        ({"v": 2, "status": "refused", "code": 4}, "vector-scan"),
        ({"v": 2, "status": "refused"}, "vector-scan"),
    ],
)
def test_the_runner_rejects_malformed_vector_scan_answers(answer, kind):
    assert ObjectProbeRunner._answer_of(json.dumps(answer).encode(), kind) is None


# --------------------------------------------------------------------------- the coordinator


class _FakeRunner(QObject):
    finished = Signal(int, object)
    failed = Signal(int)
    retired = Signal(int)

    def __init__(self, auto=None) -> None:
        super().__init__()
        self.jobs: dict[int, tuple[object, str, tuple[bytes, ...]]] = {}
        self.cancelled: list[int] = []
        self.waiting: set[int] = set()  # jobs queued behind another owner's running job
        self.auto = auto  # called inside submit once the job exists (a synchronous answer)
        self._next = 1
        self.idle = True

    def submit(self, owner, kind, payloads, *, front=False) -> int:
        job_id = self._next
        self._next += 1
        self.jobs[job_id] = (owner, kind, tuple(payloads))
        if self.auto is not None:
            self.auto(self, job_id)
        return job_id

    def cancel(self, job_id: int) -> None:
        self.cancelled.append(job_id)
        if job_id in self.waiting:  # a queued job leaves the queue and is retired at once
            self.waiting.discard(job_id)
            self.retired.emit(job_id)

    def is_waiting(self, job_id: int) -> bool:
        return job_id in self.waiting

    def directory(self, job_id: int) -> Path:
        return Path(json.loads(self.jobs[job_id][2][0])["dir"])

    def answer_complete(self, job_id: int, index=None, name: str = "index.npy") -> None:
        transport.save_index(index or _index(), self.directory(job_id) / "index.npy")
        self.finished.emit(job_id, {"v": 2, "status": "complete", "scan_file": name})


class _Model:
    def __init__(self, result=None, raises: BaseException | None = None) -> None:
        self.result = result if result is not None else ((STREAM,), FRAME)
        self.raises = raises
        self.calls: list[int] = []

    def vector_page_source(self, page_num: int):
        self.calls.append(page_num)
        if self.raises is not None:
            raise self.raises
        return self.result


class _Recorder:
    def __init__(self, coordinator: VectorEditCoordinator) -> None:
        self.done: list[tuple[int, object]] = []
        self.refused: list[tuple[int, str]] = []
        coordinator.index_done.connect(lambda page, index: self.done.append((page, index)))
        coordinator.index_refused.connect(lambda page, code: self.refused.append((page, code)))


@pytest.fixture(autouse=True)
def _admission_open():
    get_registry().open_admission()
    yield
    get_registry().open_admission()


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    """The app temp directory of the test: every job directory must be gone when the test ends."""
    import tempfile

    root = tmp_path / "apptemp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def _make(runner, model=None):
    model = model or _Model()
    return VectorEditCoordinator(SimpleNamespace(model=model), runner=runner), model


def _pump(qapp, until, timeout_s: float = 20.0) -> None:
    """Run the event loop until ``until()`` (the index file is loaded on a worker thread)."""
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        qapp.processEvents()
        if until():
            qapp.processEvents()
            return
        time.sleep(0.005)
    raise AssertionError("condition not reached")


def _settled(coordinator, rec) -> bool:
    return (bool(rec.done) or bool(rec.refused)) and not coordinator.busy


def test_the_job_carries_the_streams_the_frame_and_a_fresh_directory_in_the_app_temp(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, model = _make(runner)
    assert coordinator.ensure_index(4) is True
    assert model.calls == [4]
    ((owner, kind, payloads),) = runner.jobs.values()
    assert owner is coordinator and kind == "vector-scan"
    head = json.loads(payloads[0])
    assert head["frame"] == list(FRAME)
    assert head["lengths"] == [len(STREAM)]
    assert payloads[1:] == (STREAM,)  # one concatenated payload, boundaries in the manifest
    assert Path(head["dir"]).parent == temp_root and Path(head["dir"]).is_dir()
    assert coordinator.busy
    coordinator.cancel()


def test_a_complete_answer_loads_the_file_announces_the_index_and_deletes_the_directory(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(3)
    runner.answer_complete(1)
    assert coordinator.busy  # the file is being read on a worker, not inside the slot
    _pump(qapp, lambda: _settled(coordinator, rec))
    assert rec.refused == [] and len(rec.done) == 1
    page, index = rec.done[0]
    assert page == 3
    _same(_index(), index)
    assert list(temp_root.iterdir()) == []
    assert not coordinator.busy


def test_the_index_file_is_loaded_and_validated_off_the_gui_thread(qapp, temp_root, monkeypatch):
    import threading

    seen: list[int] = []
    real = transport.load_index

    def spy(path):
        seen.append(threading.get_ident())
        return real(path)

    monkeypatch.setattr(transport, "load_index", spy)
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(1)
    runner.answer_complete(1)
    _pump(qapp, lambda: _settled(coordinator, rec))
    assert seen and seen[0] != threading.get_ident()
    assert len(rec.done) == 1


def test_a_request_superseded_while_its_file_loads_is_discarded_and_its_directory_deleted(
    qapp, temp_root, monkeypatch
):
    import threading

    gate = threading.Event()
    entered = threading.Event()
    real = transport.load_index

    def slow(path):
        entered.set()
        assert gate.wait(20.0)
        return real(path)

    monkeypatch.setattr(transport, "load_index", slow)
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(1)
    runner.answer_complete(1)
    _pump(qapp, entered.is_set)
    coordinator.cancel()  # a newer request / a cancel while the worker holds the file
    assert coordinator.busy  # still reading
    gate.set()
    _pump(qapp, lambda: not coordinator.busy)
    assert rec.done == [] and rec.refused == []  # the generation check dropped the answer
    assert list(temp_root.iterdir()) == []


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        ({"v": 2, "status": "refused", "code": "CHORD_CAP"}, "CHORD_CAP"),
        ({"v": 2, "status": "refused", "code": "NO_FRAME"}, "NO_FRAME"),
        ({"v": 2, "status": "refused", "code": "SOMETHING_ELSE"}, "SCAN_ERROR"),
        ({"v": 2, "status": "resource_limited"}, "TOO_LARGE"),
        ({"v": 2, "status": "analysis_failed"}, "SCAN_ERROR"),
        ({"v": 2, "status": "containment_failed"}, "SCAN_ERROR"),
        ({"v": 2, "status": "no_headroom"}, "SCAN_ERROR"),
        ({"v": 2, "status": "unsupported_platform"}, "SCAN_ERROR"),
    ],
)
def test_every_non_complete_answer_is_a_refusal_and_the_directory_is_deleted(qapp, temp_root, answer, code):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(2)
    runner.finished.emit(1, answer)
    assert rec.done == [] and rec.refused == [(2, code)]
    assert list(temp_root.iterdir()) == []
    assert not coordinator.busy


def test_a_crashed_child_is_a_scan_error_and_the_directory_is_deleted(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(2)
    # a half-written file the killed child left behind
    (runner.directory(1) / "index.npy").write_bytes(b"partial")
    runner.failed.emit(1)
    assert rec.done == [] and rec.refused == [(2, "SCAN_ERROR")]
    assert list(temp_root.iterdir()) == []


def test_a_corrupt_file_is_a_scan_error_and_deleted(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(2)
    (runner.directory(1) / "index.npy").write_bytes(b"garbage" * 20)
    runner.finished.emit(1, {"v": 2, "status": "complete", "scan_file": "index.npy"})
    _pump(qapp, lambda: _settled(coordinator, rec))
    assert rec.done == [] and rec.refused == [(2, "SCAN_ERROR")]
    assert list(temp_root.iterdir()) == []


def test_a_structurally_inconsistent_file_is_a_scan_error_not_an_index(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(2)
    index = _index()
    index.segments["path"][0] = 999
    transport.save_index(index, runner.directory(1) / "index.npy")
    runner.finished.emit(1, {"v": 2, "status": "complete", "scan_file": "index.npy"})
    _pump(qapp, lambda: _settled(coordinator, rec))
    assert rec.done == [] and rec.refused == [(2, "SCAN_ERROR")]
    assert list(temp_root.iterdir()) == []


def test_a_missing_file_is_a_scan_error(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(2)
    runner.finished.emit(1, {"v": 2, "status": "complete", "scan_file": "index.npy"})
    _pump(qapp, lambda: _settled(coordinator, rec))
    assert rec.done == [] and rec.refused == [(2, "SCAN_ERROR")]
    assert list(temp_root.iterdir()) == []


def test_a_printed_name_other_than_the_expected_one_is_never_opened_or_deleted(qapp, temp_root, tmp_path):
    victim = tmp_path / "victim.npy"
    transport.save_index(_index(), victim)
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(2)
    runner.finished.emit(1, {"v": 2, "status": "complete", "scan_file": "../../victim.npy"})
    runner.finished.emit(1, {"v": 2, "status": "complete", "scan_file": str(victim)})
    assert rec.done == [] and rec.refused == [(2, "SCAN_ERROR")]
    assert victim.exists()
    assert list(temp_root.iterdir()) == []


def test_cancel_kills_the_job_drops_a_late_answer_and_deletes_the_directory(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(2)
    directory = runner.directory(1)
    coordinator.cancel()
    assert runner.cancelled == [1]
    assert not directory.exists()
    transport.save_index(_index(), temp_root / "stray.npy")  # a late child cannot reach the cancelled job
    runner.finished.emit(1, {"v": 2, "status": "complete", "scan_file": "index.npy"})
    runner.failed.emit(1)
    assert rec.done == [] and rec.refused == []


def test_a_directory_that_cannot_be_removed_yet_is_swept_by_the_next_request(qapp, temp_root, monkeypatch):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    coordinator.ensure_index(1)
    directory = runner.directory(1)
    real = shutil.rmtree
    state = {"fail": True}

    def flaky(path, *args, **kwargs):
        if state["fail"] and Path(path) == directory:
            return None  # silently leaves it: the killed child still holds a file
        return real(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", flaky)
    coordinator.cancel()
    assert directory.exists()
    state["fail"] = False
    coordinator.ensure_index(2)
    assert not directory.exists()
    coordinator.cancel()


def test_a_runner_that_retires_a_job_without_an_answer_releases_the_job_and_its_directory(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(1)
    directory = runner.directory(1)
    assert coordinator.busy and directory.exists()
    runner.retired.emit(1)  # runner shutdown: no finished, no failed
    assert not coordinator.busy
    assert not directory.exists() and list(temp_root.iterdir()) == []
    assert rec.done == [] and rec.refused == []


def test_a_cancelled_job_whose_directory_is_held_is_retried_when_the_child_exits(qapp, temp_root, monkeypatch):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    coordinator.ensure_index(1)
    directory = runner.directory(1)
    real = shutil.rmtree
    state = {"fail": True}

    def flaky(path, *args, **kwargs):
        if state["fail"] and Path(path) == directory:
            return None  # the killed child still holds a file
        return real(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", flaky)
    coordinator.cancel()
    assert directory.exists() and coordinator.busy  # cancelled, but the child has not exited
    state["fail"] = False
    runner.retired.emit(1)  # the runner reports the child gone: no new request is needed
    assert not directory.exists()
    assert not coordinator.busy


def test_cancelling_a_queued_job_is_not_busy_while_another_owner_runs(qapp, temp_root):
    runner = _FakeRunner()
    runner.idle = False  # somebody else's job runs in the shared runner
    coordinator, _ = _make(runner)
    coordinator.ensure_index(1)
    runner.waiting.add(1)  # ours never started
    coordinator.cancel()
    assert runner.cancelled == [1]
    assert not coordinator.busy
    assert list(temp_root.iterdir()) == []


def test_a_cancelled_running_job_keeps_busy_until_the_runner_retires_it(qapp, temp_root):
    runner = _FakeRunner()
    runner.idle = False
    coordinator, _ = _make(runner)
    coordinator.ensure_index(1)
    coordinator.cancel()
    assert coordinator.busy
    runner.retired.emit(1)
    assert not coordinator.busy


def test_shutdown_of_the_real_runner_while_the_child_runs_retires_the_job_and_deletes_the_directory(
    qapp, temp_root, monkeypatch
):
    from test_scripts.test_object_probe_runner import OK_MEMORY, FakeProcess

    FakeProcess.instances = []
    monkeypatch.setattr("controller.object_probe_runner.read_system_memory", lambda: OK_MEMORY)
    runner = ObjectProbeRunner(qapp, process_factory=FakeProcess)
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(1) is True
    proc = FakeProcess.instances[0]
    proc.started.emit()
    directory = next(temp_root.iterdir())
    runner.shutdown()
    assert proc.killed and coordinator.busy
    proc.finished.emit(1, QProcess.ExitStatus.CrashExit)
    assert not coordinator.busy
    assert not directory.exists()
    assert rec.done == [] and rec.refused == []
    FakeProcess.instances = []


def test_a_job_submitted_to_a_closing_real_runner_is_retired_inside_submit(qapp, temp_root, monkeypatch):
    runner = ObjectProbeRunner(qapp)
    runner.shutdown()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(1)
    assert not coordinator.busy
    assert list(temp_root.iterdir()) == []
    assert rec.done == [] and rec.refused == []


def test_a_page_with_too_many_streams_is_refused_before_any_job_or_directory(qapp, temp_root):
    runner = _FakeRunner()
    streams = (b"",) * 100_001
    coordinator, _ = _make(runner, _Model(result=(streams, FRAME)))
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(1) is False
    assert rec.refused == [(1, "TOO_LARGE")]
    assert runner.jobs == {} and list(temp_root.iterdir()) == []


def test_five_thousand_streams_become_one_payload_and_a_bounded_manifest(qapp, temp_root):
    runner = _FakeRunner()
    streams = tuple(b"%d 0 m 5 5 l S\n" % (k % 90) for k in range(5000))
    coordinator, _ = _make(runner, _Model(result=(streams, FRAME)))
    assert coordinator.ensure_index(1) is True
    ((_, _, payloads),) = runner.jobs.values()
    assert len(payloads) == 2 and payloads[1] == b"".join(streams)
    assert json.loads(payloads[0])["lengths"] == [len(s) for s in streams]
    wire_header = json.dumps({"v": 2, "kind": "vector-scan", "sizes": [len(p) for p in payloads], "mem": 1 << 30})
    assert len(wire_header) < helper_main._MAX_HEADER_BYTES
    coordinator.cancel()


def test_a_newer_request_cancels_the_older_job_and_only_it_is_announced(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(1)
    coordinator.ensure_index(2)
    assert runner.cancelled == [1]
    runner.retired.emit(1)  # the killed first child has exited
    runner.answer_complete(2)
    _pump(qapp, lambda: _settled(coordinator, rec))
    assert [p for p, _ in rec.done] == [2]
    assert list(temp_root.iterdir()) == []


def test_answers_of_other_jobs_on_the_shared_runner_are_ignored(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    coordinator.ensure_index(1)
    runner.finished.emit(99, {"v": 2, "status": "complete", "rects": []})
    runner.failed.emit(98)
    assert rec.done == [] and rec.refused == [] and coordinator.busy
    coordinator.cancel()


def test_an_answer_given_inside_submit_is_delivered_after_the_job_is_registered(qapp, temp_root):
    def refuse_at_once(runner, job_id):
        runner.finished.emit(job_id, {"v": 2, "status": "no_headroom"})

    runner = _FakeRunner(auto=refuse_at_once)
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(5) is True
    assert rec.refused == [(5, "SCAN_ERROR")]
    assert list(temp_root.iterdir()) == []
    assert not coordinator.busy


def test_closed_admission_submits_nothing_reads_no_model_and_creates_no_directory(qapp, temp_root):
    runner = _FakeRunner()
    model = _Model(raises=IndexError("page"))
    coordinator, _ = _make(runner, model)
    rec = _Recorder(coordinator)
    get_registry().close_admission()
    assert coordinator.ensure_index(1) is False
    assert model.calls == [] and runner.jobs == {}
    assert rec.done == [] and rec.refused == []
    assert list(temp_root.iterdir()) == []


def test_a_refusal_of_the_model_creates_no_job_or_directory(qapp, temp_root):
    runner = _FakeRunner()
    coordinator, _ = _make(runner, _Model(raises=VectorPageRefused("NO_FRAME", "x")))
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(1) is False
    assert rec.refused == [(1, "NO_FRAME")]
    assert runner.jobs == {} and list(temp_root.iterdir()) == []


def test_a_runner_that_cannot_be_made_refuses_without_a_directory(qapp, temp_root, monkeypatch):
    coordinator = VectorEditCoordinator(SimpleNamespace(model=_Model()))  # no runner, no QApplication hook
    monkeypatch.setattr(VectorEditCoordinator, "_child_runner", lambda self: None)
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(1) is False
    assert rec.refused == [(1, "SCAN_ERROR")]
    assert list(temp_root.iterdir()) == []


def test_the_real_runner_and_child_deliver_an_index_to_the_gui_thread(qapp, temp_root):
    from utils import object_probe_platform

    if not object_probe_platform.contained_probe_supported():
        pytest.skip("no contained child on this platform")
    runner = ObjectProbeRunner(qapp)
    coordinator, _ = _make(runner)
    rec = _Recorder(coordinator)
    assert coordinator.ensure_index(1) is True
    end = time.monotonic() + 90.0
    while time.monotonic() < end and not (rec.done or rec.refused):
        qapp.processEvents()
        time.sleep(0.01)
    assert rec.refused == [] and len(rec.done) == 1
    _same(_index(), rec.done[0][1])
    assert list(temp_root.iterdir()) == []
    runner.shutdown()


# ------------------------------------------------------------------------------------ the p20 gate


def _gate():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "p20_scan_gate", REPO_ROOT / "plans" / "cad-vector-object-editing-probes" / "p20_scan_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _good_run(gate) -> dict:
    return {
        "status": "done", "finished": True, "child_exit_code": 0,
        "cold": {"numpy_loaded": False, "scan_loaded": False, "transport_loaded": False},
        "sum_ws_mib": 100.0, "paths": gate.EXPECTED_PATHS, "scanner": "G", "accelerated": False,
    }


def test_the_gate_accepts_a_run_that_reports_the_expected_scanner_and_path_count():
    gate = _gate()
    assert gate._run_failure(1, _good_run(gate)) is None


@pytest.mark.parametrize(
    ("key", "value"),
    [("paths", 12), ("paths", None), ("scanner", "F"), ("scanner", None), ("accelerated", True), ("accelerated", None)],
)
def test_the_gate_rejects_a_run_that_cannot_prove_which_scanner_produced_the_expected_paths(key, value):
    gate = _gate()
    run = _good_run(gate)
    run[key] = value
    assert gate._run_failure(1, run) is not None
