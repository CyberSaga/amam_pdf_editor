"""Red-light tests for the supervised whole-suite runner (plans/test-suite-never-hangs.md, 1.5).

Pure lane: no Qt, no qapp. Fake children are small python scripts written under
``tmp_path``; a ``command_factory`` substitutes them for pytest and records every
call so the tests can assert what the runner passed (``--deselect <culprit>``,
``--collect-only``, the job's ``-m`` / passthrough).

Two guard tests (``test_guard_*``) stayed red until stage S3 edited ``ci.yml`` and
``CLAUDE.md``; that is intended.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import _pytest_env, pytest_heartbeat, run_suite
from scripts.pytest_heartbeat import HEARTBEAT_ENV, pending_culprit, read_heartbeat
from scripts.run_suite import JobResult, JobSpec, SupervisedExit

pytest_plugins = ("pytester",)

REPO_ROOT = Path(__file__).resolve().parents[1]

# Short thresholds for the fake hang children (plan 1.5).
STALL = 1.0
CEILING = 3.0
POLL = 0.1
# Generous thresholds for children that must NOT be killed.
SLOW_STALL = 60.0
SLOW_CEILING = 120.0

FIRST = "fake_mod.py::test_first"
SECOND = "fake_mod.py::test_second"
THIRD = "fake_mod.py::test_third"

FAKE_CHILD = r'''
import json
import os
import subprocess
import sys
import time

mode = sys.argv[1]
args = sys.argv[2:]


def opt(name):
    return args[args.index(name) + 1] if name in args else None


junit = opt("--junitxml")
pidfile = opt("--pidfile")
envfile = opt("--envfile")
hb = os.environ.get("PDF_EDITOR_TEST_HEARTBEAT")
HANG_NODE = "fake_mod.py::test_third" if "--deselect" in args else "fake_mod.py::test_second"


def beat(nodeid, phase):
    if not hb:
        return
    with open(hb, "a", encoding="utf-8") as f:
        f.write(json.dumps({"nodeid": nodeid, "phase": phase, "t": time.time()}) + "\n")
        f.flush()


def first():
    beat("fake_mod.py::test_first", "start")
    beat("fake_mod.py::test_first", "finish")


def write_junit(passed=0, failed=0):
    if not junit:
        return
    cases = "".join(
        '<testcase classname="fake_mod" name="test_ok%d" time="0.01"/>' % i for i in range(passed)
    )
    cases += "".join(
        '<testcase classname="fake_mod" name="test_bad%d" time="0.01">'
        '<failure message="boom">boom</failure></testcase>' % i
        for i in range(failed)
    )
    with open(junit, "w", encoding="utf-8") as f:
        f.write(
            '<?xml version="1.0" encoding="utf-8"?><testsuites>'
            '<testsuite name="pytest" errors="0" failures="%d" skipped="0" tests="%d" time="0.1">'
            "%s</testsuite></testsuites>" % (failed, passed + failed, cases)
        )


def sleep_forever():
    while True:
        time.sleep(60)


if envfile:
    with open(envfile, "w", encoding="utf-8") as f:
        json.dump(
            {
                "PYTEST_ADDOPTS": os.environ.get("PYTEST_ADDOPTS"),
                "PYTEST_PLUGINS": os.environ.get("PYTEST_PLUGINS"),
                "PYTEST_CURRENT_TEST": os.environ.get("PYTEST_CURRENT_TEST"),
                "QT_QPA_PLATFORM": os.environ.get("QT_QPA_PLATFORM"),
                "HEARTBEAT": os.environ.get("PDF_EDITOR_TEST_HEARTBEAT"),
                "KEEP_ME": os.environ.get("RUN_SUITE_TEST_KEEP_ME"),
            },
            f,
        )

if mode == "ok":
    first()
    print("hello-from-child", flush=True)
    write_junit(passed=2)
    sys.exit(0)
elif mode == "fail":
    first()
    write_junit(passed=1, failed=1)
    sys.exit(1)
elif mode == "rc2":
    sys.exit(2)
elif mode == "rc5":
    sys.exit(5)
elif mode == "collect_zero":
    print("no tests collected in 0.01s")
    sys.exit(5)
elif mode == "collect_one":
    print("fake_mod.py::test_a\n\n1 test collected in 0.01s")
    sys.exit(0)
elif mode == "collect_two":
    print("fake_mod.py::test_a\nfake_mod.py::test_b\n\n2 tests collected in 0.01s")
    sys.exit(0)
elif mode == "collect_partial":
    print("fake_mod.py::test_a\nfake_mod.py::test_b\n\n2/5 tests collected (3 deselected) in 0.01s")
    sys.exit(0)
elif mode == "collect_all_deselected":
    print("no tests collected (5 deselected) in 0.01s")
    sys.exit(5)
elif mode == "hang":
    first()
    beat(HANG_NODE, "start")
    sleep_forever()
elif mode == "hang_with_grandchild":
    first()
    gcfile = pidfile + ".gc"
    # The grandchild reports its own os.getpid(): on a venv Popen().pid is the launcher
    # redirector, whose real python child is a different process.
    gc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\nwhile True: time.sleep(60)",
            gcfile,
        ]
    )
    deadline = time.time() + 30
    while not os.path.exists(gcfile) and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.3)
    with open(gcfile, encoding="utf-8") as f:
        gc_real = int(f.read())
    tmp = pidfile + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"main": os.getpid(), "grandchild": gc.pid, "grandchild_real": gc_real}, f)
    os.replace(tmp, pidfile)
    beat(HANG_NODE, "start")
    sleep_forever()
elif mode == "abort":
    import faulthandler

    faulthandler.enable()  # pytest always does; on Windows a native abort then exits rc 3, not 0xC0000409
    first()
    beat(HANG_NODE, "start")
    os.abort()
elif mode == "exit_in_flight":
    first()
    beat(HANG_NODE, "start")
    os._exit(1)  # faulthandler_exit_on_timeout shape: rc 1, no junit, an unmatched start
elif mode == "hang_between_tests":
    first()
    sleep_forever()  # every start has a finish, so no culprit exists at the kill instant
elif mode == "hang_after_finish":
    first()
    write_junit(passed=1)
    sleep_forever()
elif mode == "hang_no_heartbeat":
    sleep_forever()
elif mode == "chatty":
    while True:
        beat("fake_mod.py::test_chatty", "start")
        beat("fake_mod.py::test_chatty", "finish")
        time.sleep(0.2)
else:
    sys.exit(99)
'''


# --------------------------------------------------------------------------- helpers


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # access denied means it exists
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:  # a zombie is gone for our purposes
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat.rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return True


def _wait_gone(pid: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return not _pid_alive(pid)


def _reap(pidfile: Path) -> None:
    """Test-owned cleanup: terminate fake children this test spawned, if still alive."""
    if not pidfile.exists():
        return
    try:
        pids = list(json.loads(pidfile.read_text()).values())
    except (OSError, ValueError):
        return
    for pid in pids:
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass


class Factory:
    """command_factory substitute: records every call, runs the fake child."""

    def __init__(
        self,
        script: Path,
        main_mode: str,
        *,
        probe_mode: str = "collect_zero",
        rerun_mode: str = "ok",
        pidfile: Path | None = None,
        envfile: Path | None = None,
    ) -> None:
        self.script = script
        self.main_mode = main_mode
        self.probe_mode = probe_mode
        self.rerun_mode = rerun_mode
        self.pidfile = pidfile
        self.envfile = envfile
        self.calls: list[dict] = []

    def __call__(self, spec, junit, python=sys.executable, extra=()):
        extra = list(extra)
        probe = "--collect-only" in extra
        if probe:
            mode = self.probe_mode
        elif spec.deselect:
            mode = self.rerun_mode
        else:
            mode = self.main_mode
        self.calls.append(
            {
                "probe": probe,
                "mode": mode,
                "name": spec.name,
                "marker_expr": spec.marker_expr,
                "passthrough": list(spec.passthrough),
                "deselect": list(spec.deselect),
                "files": list(spec.files),
                "extra": extra,
            }
        )
        cmd = [python, str(self.script), mode, "--junitxml", str(junit)]
        for d in spec.deselect:
            cmd += ["--deselect", d]
        if self.pidfile is not None:
            cmd += ["--pidfile", str(self.pidfile)]
        if self.envfile is not None:
            cmd += ["--envfile", str(self.envfile)]
        return cmd + extra

    @property
    def runs(self) -> list[dict]:
        return [c for c in self.calls if not c["probe"]]

    @property
    def probes(self) -> list[dict]:
        return [c for c in self.calls if c["probe"]]


@pytest.fixture
def fake_script(tmp_path: Path) -> Path:
    script = tmp_path / "fake_child.py"
    script.write_text(FAKE_CHILD, encoding="utf-8")
    return script


def _spec(name: str = "job", **kw) -> JobSpec:
    return JobSpec(name=name, files=[Path("test_scripts/test_fake.py")], lane="qt", **kw)


def _run(factory: Factory, tmp_path: Path, spec: JobSpec | None = None, **kw) -> JobResult:
    kw.setdefault("stall_seconds", STALL)
    kw.setdefault("file_ceiling", CEILING)
    kw.setdefault("poll_seconds", POLL)
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    return run_suite.run_job(spec or _spec(), out, cwd=tmp_path, command_factory=factory, **kw)


_HUNG_CACHE: dict = {}


@pytest.fixture
def hung_job(tmp_path_factory):
    """One real hang (+ ok rerun), run once and shared by several tests to keep the file fast.

    Memoised by hand (not a module-scoped fixture) so a failing run_job reports a test
    failure, not a fixture error, in every test that uses it.
    """

    def get():
        if "v" not in _HUNG_CACHE:
            tmp = tmp_path_factory.mktemp("hung_job")
            script = tmp / "fake_child.py"
            script.write_text(FAKE_CHILD, encoding="utf-8")
            factory = Factory(script, "hang", rerun_mode="ok")
            _HUNG_CACHE["v"] = (_run(factory, tmp), factory, tmp)
        return _HUNG_CACHE["v"]

    return get


def _write_junit(path: Path, passed=0, failed=0, errors=0, skipped=0, xfailed=0) -> Path:
    cases = [f'<testcase classname="m" name="p{i}"/>' for i in range(passed)]
    cases += [
        f'<testcase classname="m" name="f{i}"><failure message="x">x</failure></testcase>'
        for i in range(failed)
    ]
    cases += [
        f'<testcase classname="m" name="e{i}"><error message="x">x</error></testcase>'
        for i in range(errors)
    ]
    cases += [
        f'<testcase classname="m" name="s{i}"><skipped type="pytest.skip" message="r"/></testcase>'
        for i in range(skipped)
    ]
    cases += [
        f'<testcase classname="m" name="x{i}"><skipped type="pytest.xfail" message="r"/></testcase>'
        for i in range(xfailed)
    ]
    n = len(cases)
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        f'<testsuite name="pytest" errors="{errors}" failures="{failed}" skipped="{skipped + xfailed}" '
        f'tests="{n}" time="0.1">{"".join(cases)}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return path


def _hand_result(
    tmp_path: Path,
    name: str,
    status: str,
    *,
    junit: Path | None = None,
    culprit: str | None = None,
    rerun: JobResult | None = None,
    rc: int | None = 0,
) -> JobResult:
    log = tmp_path / f"{name}.log"
    log.write_text("log tail line\n", encoding="utf-8")
    hb = tmp_path / f"{name}.heartbeat"
    hb.write_text(
        json.dumps({"nodeid": "m.py::t", "phase": "start", "t": 1.0}) + "\n", encoding="utf-8"
    )
    ev = tmp_path / f"{name}.evidence.txt"
    ev.write_text("evidence\n", encoding="utf-8")
    return JobResult(
        spec=_spec(name),
        status=status,
        returncode=rc,
        culprit=culprit,
        junit=junit,
        log=log,
        heartbeat=hb,
        evidence=[ev],
        elapsed=1.0,
        rerun=rerun,
    )


# --------------------------------------------------------------------------- _pytest_env


def test_clean_pytest_env_strips_exactly_the_blocklist() -> None:
    assert _pytest_env.PYTEST_ENV_BLOCKLIST == frozenset(
        {"PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_CURRENT_TEST"}
    )
    base = {
        "PYTEST_ADDOPTS": "-x",
        "PYTEST_PLUGINS": "evil",
        "PYTEST_CURRENT_TEST": "t",
        "PYTEST_DEBUG": "1",
        "KEEP": "1",
        "PATH": "p",
    }
    cleaned = _pytest_env.clean_pytest_env(base)
    assert cleaned == {"PYTEST_DEBUG": "1", "KEEP": "1", "PATH": "p"}
    assert cleaned is not base
    assert "PYTEST_ADDOPTS" in base  # the input is never mutated


def test_clean_pytest_env_defaults_to_os_environ(monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "-x")
    monkeypatch.setenv("RUN_SUITE_TEST_KEEP_ME", "yes")
    cleaned = _pytest_env.clean_pytest_env()
    assert "PYTEST_ADDOPTS" not in cleaned
    assert cleaned["RUN_SUITE_TEST_KEEP_ME"] == "yes"
    assert os.environ["PYTEST_ADDOPTS"] == "-x"


def test_verify_no_jump_reuses_shared_env_helpers() -> None:
    import scripts.verify_no_jump as vnj

    assert vnj._PYTEST_ENV_BLOCKLIST is _pytest_env.PYTEST_ENV_BLOCKLIST
    assert vnj._clean_pytest_env is _pytest_env.clean_pytest_env


# --------------------------------------------------------------------------- heartbeat helpers


def _ev(nodeid: str, phase: str, t: float = 0.0) -> dict:
    return {"nodeid": nodeid, "phase": phase, "t": t}


@pytest.mark.parametrize(
    "events, expected",
    [
        ([], None),
        ([_ev("a", "start"), _ev("a", "finish")], None),
        ([_ev("a", "start"), _ev("a", "finish"), _ev("b", "start")], "b"),
        ([_ev("a", "start"), _ev("b", "start"), _ev("a", "finish")], "b"),
        ([_ev("a", "start"), _ev("b", "start"), _ev("b", "finish")], "a"),
        ([_ev("a", "start"), _ev("a", "finish"), _ev("a", "start")], "a"),
        ([_ev("a", "start"), _ev("b", "start"), _ev("b", "finish"), _ev("a", "finish")], None),
    ],
)
def test_pending_culprit(events: list[dict], expected: str | None) -> None:
    assert pending_culprit(events) == expected


def test_read_heartbeat_tolerates_truncated_last_line(tmp_path: Path) -> None:
    hb = tmp_path / "hb.jsonl"
    hb.write_text(
        json.dumps(_ev("a", "start", 1.0))
        + "\n"
        + json.dumps(_ev("a", "finish", 2.0))
        + '\n{"nodeid": "b", "ph',
        encoding="utf-8",
    )
    events = read_heartbeat(hb)
    assert [(e["nodeid"], e["phase"]) for e in events] == [("a", "start"), ("a", "finish")]


def test_heartbeat_plugin_writes_start_and_finish_lines(pytester, monkeypatch, tmp_path) -> None:
    hb = tmp_path / "nested" / "dir" / "hb.jsonl"  # parent dir must be created by the plugin
    monkeypatch.setenv(HEARTBEAT_ENV, str(hb))
    pytester.makepyfile(
        test_mini="def test_a():\n    assert True\n\n\ndef test_b():\n    assert True\n"
    )
    result = pytester.runpytest_inprocess("-p", "scripts.pytest_heartbeat", "-p", "no:cacheprovider")
    result.assert_outcomes(passed=2)
    events = read_heartbeat(hb)
    assert [(e["nodeid"], e["phase"]) for e in events] == [
        ("test_mini.py::test_a", "start"),
        ("test_mini.py::test_a", "finish"),
        ("test_mini.py::test_b", "start"),
        ("test_mini.py::test_b", "finish"),
    ]
    assert all(isinstance(e["t"], float) for e in events)
    assert pending_culprit(events) is None


def test_heartbeat_plugin_is_inert_without_the_env_var(pytester, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(HEARTBEAT_ENV, raising=False)
    monkeypatch.chdir(tmp_path)  # a cwd-relative fallback write would land here and be caught
    # The chdir moves away from pytester.path, so the test file is passed explicitly.
    test_file = pytester.makepyfile(test_mini="def test_a():\n    assert True\n")
    result = pytester.runpytest_inprocess(
        str(test_file), "-p", "scripts.pytest_heartbeat", "-p", "no:cacheprovider"
    )
    result.assert_outcomes(passed=1)
    created = [p.name for p in pytester.path.iterdir()] + [p.name for p in tmp_path.iterdir()]
    assert not [n for n in created if "heartbeat" in n.lower() or n.endswith(".jsonl")]
    assert hasattr(pytest_heartbeat, "pytest_runtest_logstart")


# --------------------------------------------------------------------------- classify / jobs


@pytest.mark.parametrize(
    "source",
    [
        "import PySide6.QtCore\n",
        "from PySide6.QtWidgets import QWidget\n",
        "import json\nfrom view import x\n",
        "import controller\n",
        "import os\nfrom controller.pdf_controller import PDFController\n",
        "from main import run\n",
        "import main\n",
        "from src.printing import x\n",
        "import qt_teardown\n",
        "def test_a():\n    app = QApplication([])\n",
        # S4-07: Qt reached through an indented import or a Qt-providing fixture is still Qt.
        "def test_a():\n    from view import main_window\n",
        "def test_a():\n    import controller\n",
        "def test_a():\n\tfrom controller.pdf_controller import PDFController\n",
        "def test_a():\n    from src.printing import x\n",
        "def test_a(qapp):\n    assert qapp\n",
        "def test_a(tmp_path, qapp, monkeypatch):\n    pass\n",
        "def test_a(qtbot):\n    pass\n",
    ],
)
def test_classify_qt_sources(source: str) -> None:
    assert run_suite.classify(source, "test_scripts/test_x.py") == "qt"


@pytest.mark.parametrize(
    "source",
    [
        "import json\nfrom model.pdf_model import PDFModel\n\ndef test_a():\n    assert 1\n",
        "from maintenance import x\n",
        "",
        "def test_a():\n    from model import pdf_model\n",
        "def test_snapped(mapped_value):\n    pass\n",  # 'qapp' / 'qtbot' only as whole words
    ],
)
def test_classify_pure_sources(source: str) -> None:
    assert run_suite.classify(source, "test_scripts/test_x.py") == "pure"


def test_classify_overrides_win_over_the_pattern(monkeypatch) -> None:
    import re

    assert run_suite.QT_PATTERN.flags & re.MULTILINE
    qt_src = "from PySide6 import QtCore\n"
    pure_src = "import json\n"
    monkeypatch.setattr(run_suite, "_FORCE_PURE", {"test_scripts/test_forced.py"})
    monkeypatch.setattr(run_suite, "_FORCE_QT", {"test_scripts/test_forced_qt.py"})
    assert run_suite.classify(qt_src, "test_scripts/test_forced.py") == "pure"
    assert run_suite.classify(pure_src, "test_scripts/test_forced_qt.py") == "qt"
    assert run_suite.classify(qt_src, "test_scripts/test_other.py") == "qt"
    assert run_suite.classify(pure_src, "test_scripts/test_other.py") == "pure"


def _make_tree(root: Path) -> list[Path]:
    tdir = root / "test_scripts"
    tdir.mkdir()
    sources = {
        "test_qt_a.py": "from PySide6 import QtCore\n",
        "test_qt_b.py": "from view import main_window\n",
        "test_pure_a.py": "import json\n",
        "test_pure_b.py": "from model import pdf_model\n",
    }
    paths = []
    for name, src in sources.items():
        p = tdir / name
        p.write_text(src, encoding="utf-8")
        paths.append(p)
    return paths


def test_discover_returns_sorted_test_files(tmp_path: Path) -> None:
    for name in ("test_b.py", "test_a.py", "helper.py", "conftest.py", "notes.txt"):
        (tmp_path / name).write_text("", encoding="utf-8")
    assert run_suite.discover(tmp_path) == [tmp_path / "test_a.py", tmp_path / "test_b.py"]


def test_build_jobs_shapes_per_lane(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_suite, "REPO_ROOT", tmp_path)
    files = _make_tree(tmp_path)
    jobs = run_suite.build_jobs(files, "all", "not slow", ["--durations=5"])
    by_name = {j.name: j for j in jobs}
    assert set(by_name) == {"test_qt_a", "test_qt_b", "pure"}
    assert by_name["test_qt_a"].lane == "qt" and by_name["test_qt_a"].files == [files[0]]
    assert by_name["test_qt_b"].lane == "qt" and by_name["test_qt_b"].files == [files[1]]
    assert by_name["pure"].lane == "pure" and set(by_name["pure"].files) == {files[2], files[3]}
    assert all(j.marker_expr == "not slow" and j.passthrough == ["--durations=5"] for j in jobs)

    qt_only = run_suite.build_jobs(files, "qt", None, [])
    assert {j.name for j in qt_only} == {"test_qt_a", "test_qt_b"}
    pure_only = run_suite.build_jobs(files, "pure", None, [])
    assert [j.name for j in pure_only] == ["pure"]
    assert all(j.marker_expr is None and j.passthrough == [] for j in qt_only + pure_only)


def test_build_jobs_without_pure_files_has_no_empty_pure_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_suite, "REPO_ROOT", tmp_path)
    files = _make_tree(tmp_path)
    jobs = run_suite.build_jobs(files[:2], "all", None, [])
    assert {j.name for j in jobs} == {"test_qt_a", "test_qt_b"}


# --------------------------------------------------------------------------- pytest_command / verdict


def test_pytest_command_layout(tmp_path: Path) -> None:
    f1, f2 = tmp_path / "test_one.py", tmp_path / "test_two.py"
    spec = JobSpec(
        "job",
        [f1, f2],
        "qt",
        marker_expr="not local_only",
        passthrough=["--durations=5"],
        deselect=["a.py::t1", "a.py::t2"],
    )
    junit = tmp_path / "j.xml"
    cmd = run_suite.pytest_command(spec, junit, "PY", ["--collect-only", "-q"])
    assert cmd == [
        "PY", "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider",
        "--junitxml", str(junit),
        "-m", "not local_only",
        "--deselect", "a.py::t1", "--deselect", "a.py::t2",
        str(f1), str(f2),
        "--durations=5",
        "--collect-only", "-q",
    ]  # fmt: skip


def test_pytest_command_without_optionals(tmp_path: Path) -> None:
    f1 = tmp_path / "test_one.py"
    cmd = run_suite.pytest_command(JobSpec("job", [f1], "pure"), tmp_path / "j.xml", "PY")
    assert cmd == [
        "PY", "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider",
        "--junitxml", str(tmp_path / "j.xml"), str(f1),
    ]  # fmt: skip


@pytest.mark.parametrize(
    "rc, killed, expected_status",
    [
        (None, True, "HUNG"),
        (0, False, "OK"),
        (1, False, "FAIL"),
        (2, False, "COLLECT_ERROR"),
        (3, False, "COLLECT_ERROR"),
        (4, False, "COLLECT_ERROR"),
        (5, False, "RC5"),
        (6, False, "CRASH"),
        (-6, False, "CRASH"),
        (255, False, "CRASH"),
        (3221226505, False, "CRASH"),
    ],
)
def test_verdict_by_return_code(rc, killed, expected_status) -> None:
    events = [_ev("a", "start"), _ev("a", "finish"), _ev("b", "start")]
    ex = SupervisedExit(rc, killed, "stall" if killed else None, 1.0, [])
    status, culprit = run_suite.verdict(ex, events, junit_exists=True)
    assert status == expected_status
    if expected_status in ("HUNG", "CRASH"):
        assert culprit == "b"
    else:
        assert culprit is None


@pytest.mark.parametrize(
    "rc, events, expected_status, expected_culprit",
    [
        # S4-01: the in-process faulthandler exit (rc 1, no junit, an unmatched start) is a hang.
        (1, [_ev("a", "start"), _ev("a", "finish"), _ev("b", "start")], "HUNG", "b"),
        # S4-02: pytest enables faulthandler, so a native abort exits rc 3 on Windows.
        (3, [_ev("a", "start"), _ev("b", "start")], "CRASH", "b"),
        (2, [_ev("a", "start"), _ev("b", "start")], "CRASH", "b"),
        (4, [_ev("a", "start"), _ev("b", "start")], "CRASH", "b"),
        # Nothing in flight, or no heartbeat at all: the plain rc mapping stands.
        (1, [_ev("a", "start"), _ev("a", "finish")], "FAIL", None),
        (1, [], "FAIL", None),
        (3, [_ev("a", "start"), _ev("a", "finish")], "COLLECT_ERROR", None),
        (2, [], "COLLECT_ERROR", None),
        (4, [], "COLLECT_ERROR", None),
        (0, [_ev("a", "start")], "OK", None),
        (5, [_ev("a", "start")], "RC5", None),
        (-6, [_ev("a", "start")], "CRASH", "a"),
    ],
)
def test_verdict_without_a_junit_names_the_test_in_flight(rc, events, expected_status, expected_culprit) -> None:
    ex = SupervisedExit(rc, False, None, 1.0, [])
    assert run_suite.verdict(ex, events, junit_exists=False) == (expected_status, expected_culprit)


def test_verdict_with_a_junit_keeps_the_plain_return_code_mapping() -> None:
    """A junit proves sessionfinish ran, so rc 1/2/3 are ordinary failures even with a pending start."""
    pending = [_ev("a", "start")]
    for rc, expected in ((1, "FAIL"), (2, "COLLECT_ERROR"), (3, "COLLECT_ERROR")):
        ex = SupervisedExit(rc, False, None, 1.0, [])
        assert run_suite.verdict(ex, pending, junit_exists=True) == (expected, None)


# --------------------------------------------------------------------------- supervise


def test_supervise_clean_exit_is_not_killed(fake_script: Path, tmp_path: Path) -> None:
    hb, log = tmp_path / "hb.jsonl", tmp_path / "child.log"
    env = {**os.environ, HEARTBEAT_ENV: str(hb)}
    ex = run_suite.supervise(
        [sys.executable, str(fake_script), "ok"],
        cwd=tmp_path,
        env=env,
        heartbeat=hb,
        log=log,
        stall_seconds=SLOW_STALL,
        file_ceiling=SLOW_CEILING,
        poll_seconds=POLL,
    )
    assert ex.returncode == 0 and ex.killed is False and ex.reason is None
    assert "hello-from-child" in log.read_text(encoding="utf-8")


def test_supervise_stall_kills_and_collects_evidence(fake_script: Path, tmp_path: Path) -> None:
    hb, log, ev_dir = tmp_path / "hb.jsonl", tmp_path / "child.log", tmp_path / "evidence"
    env = {**os.environ, HEARTBEAT_ENV: str(hb)}
    t0 = time.monotonic()
    ex = run_suite.supervise(
        [sys.executable, str(fake_script), "hang"],
        cwd=tmp_path,
        env=env,
        heartbeat=hb,
        log=log,
        stall_seconds=STALL,
        file_ceiling=SLOW_CEILING,
        poll_seconds=POLL,
        evidence_dir=ev_dir,
    )
    assert time.monotonic() - t0 < 30
    assert ex.killed is True and ex.reason == "stall"
    assert ex.evidence, "evidence must be collected before the kill"
    assert all(p.exists() and ev_dir in p.parents for p in ex.evidence)
    blob = "".join(p.read_text(encoding="utf-8", errors="replace") for p in ex.evidence)
    assert SECOND in blob  # the heartbeat copy names the pending test


def test_supervise_ceiling_kills_a_child_that_keeps_beating(fake_script: Path, tmp_path: Path) -> None:
    hb, log = tmp_path / "hb.jsonl", tmp_path / "child.log"
    env = {**os.environ, HEARTBEAT_ENV: str(hb)}
    ex = run_suite.supervise(
        [sys.executable, str(fake_script), "chatty"],
        cwd=tmp_path,
        env=env,
        heartbeat=hb,
        log=log,
        stall_seconds=SLOW_STALL,
        file_ceiling=2.0,
        poll_seconds=POLL,
    )
    assert ex.killed is True and ex.reason == "ceiling"
    assert 2.0 <= ex.elapsed < 30


def test_supervise_credits_heartbeat_progress_against_the_stall(fake_script: Path, tmp_path: Path) -> None:
    """A beating child outlives the stall threshold; only the ceiling ends it."""
    hb, log = tmp_path / "hb.jsonl", tmp_path / "child.log"
    env = {**os.environ, HEARTBEAT_ENV: str(hb)}
    ex = run_suite.supervise(
        [sys.executable, str(fake_script), "chatty"],
        cwd=tmp_path,
        env=env,
        heartbeat=hb,
        log=log,
        stall_seconds=1.0,
        file_ceiling=4.0,
        poll_seconds=POLL,
    )
    assert ex.killed is True and ex.reason == "ceiling"
    assert ex.elapsed >= 4.0, "killed before the ceiling: progress was not credited against the stall"


def test_supervise_collects_evidence_before_it_kills(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    hb, log, ev_dir = tmp_path / "hb.jsonl", tmp_path / "child.log", tmp_path / "evidence"
    seen: list[list[str]] = []
    real_kill = run_suite._kill_tree

    def spy(proc, members):
        seen.append(sorted(p.name for p in ev_dir.glob("*")))
        return real_kill(proc, members)

    monkeypatch.setattr(run_suite, "_kill_tree", spy)
    env = {**os.environ, HEARTBEAT_ENV: str(hb)}
    ex = run_suite.supervise(
        [sys.executable, str(fake_script), "hang"],
        cwd=tmp_path,
        env=env,
        heartbeat=hb,
        log=log,
        stall_seconds=STALL,
        file_ceiling=SLOW_CEILING,
        poll_seconds=POLL,
        evidence_dir=ev_dir,
    )
    assert ex.killed is True
    assert len(seen) == 1
    assert any(n.endswith(".heartbeat") for n in seen[0]) and any(n.endswith(".tail.log") for n in seen[0])


# --------------------------------------------------------------------------- run_job: hang


def test_hang_is_killed_and_culprit_is_last_unmatched_start(hung_job) -> None:
    result, factory, _ = hung_job()
    assert result.status == "HUNG"
    assert result.culprit == SECOND
    assert result.elapsed < 30
    assert result.evidence and all(p.exists() for p in result.evidence)
    assert result.log.exists()
    events = read_heartbeat(result.heartbeat)
    assert pending_culprit(events) == SECOND


def test_hang_rerun_deselects_the_culprit(hung_job) -> None:
    result, factory, _ = hung_job()
    assert result.rerun is not None
    assert result.rerun.status == "OK"
    assert result.rerun.spec.deselect == [SECOND]
    assert result.rerun.spec.name == "job-rerun"
    assert result.rerun.rerun is None
    runs = factory.runs
    assert len(runs) == 2
    assert runs[0]["deselect"] == []
    assert runs[1]["deselect"] == [SECOND]


def test_aggregate_adds_synthetic_failure_for_hung_job(hung_job, tmp_path: Path) -> None:
    result, _, _ = hung_job()
    out = tmp_path / "merged.xml"
    summary = run_suite.aggregate([result], out, elapsed=5.0)
    root = ET.parse(out).getroot()
    assert root.tag == "testsuites"
    synth = [tc for tc in root.iter("testcase") if tc.get("classname") == "run_suite"]
    assert len(synth) == 1
    assert SECOND in synth[0].get("name")
    failure = synth[0].find("failure")
    assert failure is not None
    text = (failure.get("message") or "") + "".join(failure.itertext())
    assert "HUNG" in text and SECOND in text
    assert result.evidence[0].name in text
    assert summary.hung == 1
    assert summary.passed == 2  # the ok rerun's two tests are merged in
    assert run_suite.exit_code(summary) == 1


def test_hang_kills_the_whole_process_tree(fake_script: Path, tmp_path: Path) -> None:
    pidfile = tmp_path / "pids.json"
    factory = Factory(fake_script, "hang_with_grandchild", pidfile=pidfile)
    try:
        result = _run(factory, tmp_path, rerun=False)
        assert result.status == "HUNG"
        assert pidfile.exists(), "child never reached the point of spawning its grandchild"
        pids = json.loads(pidfile.read_text())
        assert _wait_gone(pids["main"]), "hung child still alive after the kill"
        assert _wait_gone(pids["grandchild"]), "grandchild survived the kill (orphan)"
        # On a venv Popen().pid is the launcher redirector; the real interpreter is another pid.
        assert _wait_gone(pids["grandchild_real"]), "the grandchild's real python process survived (orphan)"
    finally:
        _reap(pidfile)


def test_no_rerun_flag_skips_recovery(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "hang")
    result = _run(factory, tmp_path, rerun=False)
    assert result.status == "HUNG" and result.culprit == SECOND
    assert result.rerun is None
    assert len(factory.runs) == 1


def test_second_hang_in_the_rerun_stops_the_job(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "hang", rerun_mode="hang")
    result = _run(factory, tmp_path)
    assert result.status == "HUNG" and result.culprit == SECOND
    assert result.rerun is not None
    assert result.rerun.status == "HUNG" and result.rerun.culprit == THIRD
    assert result.rerun.rerun is None
    assert len(factory.runs) == 2
    assert factory.runs[1]["deselect"] == [SECOND]


def test_hang_without_any_heartbeat_is_a_collection_hang(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "hang_no_heartbeat")
    result = _run(factory, tmp_path)
    assert result.status == "HUNG"
    assert result.culprit is None
    assert result.rerun is None
    assert "collection hang" in result.note.lower()
    assert len(factory.runs) == 1


def test_hang_after_every_test_finished_is_a_teardown_hang(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "hang_after_finish")
    result = _run(factory, tmp_path)
    assert result.status == "HUNG"
    assert result.culprit is None
    assert result.rerun is None
    assert "teardown hang" in result.note.lower()
    assert result.junit is not None and result.junit.exists()  # the junit is kept
    assert len(factory.runs) == 1


def test_abort_is_a_crash_by_status_and_gets_the_same_recovery(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "abort")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "CRASH"  # asserted by category, never by the exit code value
    assert result.status != "HUNG"
    assert result.returncode != 0
    assert result.culprit == SECOND
    assert result.rerun is not None
    assert result.rerun.spec.deselect == [SECOND]
    assert result.rerun.status == "OK"


def test_in_process_exit_without_a_junit_is_a_hang_with_the_normal_recovery(
    fake_script: Path, tmp_path: Path
) -> None:
    """S4-01: faulthandler_exit_on_timeout ends the child with rc 1 and no junit; the test in flight is named."""
    factory = Factory(fake_script, "exit_in_flight", rerun_mode="ok")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "HUNG"
    assert result.returncode == 1
    assert result.culprit == SECOND
    assert "without a junit" in result.note
    assert result.junit is None
    assert result.evidence and all(p.exists() for p in result.evidence)
    assert any(p.name.endswith(".tail.log") for p in result.evidence)
    assert result.rerun is not None and result.rerun.status == "OK"
    assert result.rerun.spec.deselect == [SECOND]
    summary = run_suite.aggregate([result], tmp_path / "merged.xml", elapsed=1.0)
    assert summary.hung == 1 and run_suite.exit_code(summary) == 1


def test_rerun_with_rc5_probes_with_the_culprit_deselected(fake_script: Path, tmp_path: Path) -> None:
    """S4-04: a hung one-test file reruns to rc 5; the probe must keep the --deselect, or one hang reads as hung + error."""
    factory = Factory(fake_script, "hang", rerun_mode="rc5", probe_mode="collect_all_deselected")
    result = _run(factory, tmp_path)
    assert result.status == "HUNG" and result.culprit == SECOND
    assert result.rerun is not None
    assert result.rerun.status == "RC5_OK"
    (probe,) = factory.probes
    assert probe["deselect"] == [SECOND]
    summary = run_suite.aggregate([result], tmp_path / "merged.xml", elapsed=1.0)
    assert (summary.hung, summary.errors) == (1, 0)


def test_ceiling_kill_between_tests_is_not_called_a_teardown_hang(fake_script: Path, tmp_path: Path) -> None:
    """S4-05: the ceiling can fire while nothing is in flight; that is not a teardown hang."""
    factory = Factory(fake_script, "hang_between_tests")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=2.0)
    assert result.status == "HUNG" and result.culprit is None
    assert result.rerun is None
    assert "ceiling" in result.note.lower()
    assert "teardown" not in result.note.lower()
    assert len(factory.runs) == 1


# --------------------------------------------------------------------------- run_job: ordinary exits


def test_ok_job(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "ok")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "OK" and result.returncode == 0
    assert result.culprit is None and result.rerun is None
    assert result.junit is not None and result.junit.exists()
    assert len(factory.calls) == 1


def test_failing_job_is_fail_without_rerun(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "fail")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "FAIL" and result.returncode == 1
    assert result.rerun is None
    assert result.junit is not None and result.junit.exists()
    assert len(factory.calls) == 1


def test_rc2_is_a_collect_error_without_probe_or_rerun(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "rc2")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "COLLECT_ERROR" and result.returncode == 2
    assert result.rerun is None
    assert len(factory.calls) == 1


def test_rc5_with_nothing_collected_is_rc5_ok(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "rc5", probe_mode="collect_zero")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "RC5_OK" and result.returncode == 5
    assert len(factory.probes) == 1


def test_rc5_with_collected_tests_is_a_failure(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "rc5", probe_mode="collect_two")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "FAIL"
    assert result.note
    assert len(factory.probes) == 1


def test_collect_probe_gets_the_jobs_marker_and_passthrough(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "rc5", probe_mode="collect_zero")
    spec = _spec(marker_expr="not local_only", passthrough=["--durations=3"])
    result = _run(factory, tmp_path, spec, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "RC5_OK"
    (probe,) = factory.probes
    assert probe["extra"] == ["--collect-only", "-q"]
    assert probe["marker_expr"] == "not local_only"
    assert probe["passthrough"] == ["--durations=3"]
    assert probe["files"] == spec.files
    assert probe["deselect"] == []
    run = factory.runs[0]
    assert run["marker_expr"] == "not local_only" and run["passthrough"] == ["--durations=3"]


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("collect_zero", 0),
        ("collect_one", 1),
        ("collect_two", 2),
        ("collect_partial", 2),
        ("collect_all_deselected", 0),
    ],
)
def test_collect_probe_counts_selected_items(
    fake_script: Path, tmp_path: Path, monkeypatch, mode: str, expected: int
) -> None:
    factory = Factory(fake_script, "unused", probe_mode=mode)
    monkeypatch.setattr(run_suite, "pytest_command", factory)
    spec = _spec(marker_expr="not slow", passthrough=["--durations=1"])
    n = run_suite.collect_probe(
        spec, python=sys.executable, cwd=tmp_path, env=dict(os.environ), log=tmp_path / "probe.log"
    )
    assert n == expected
    (call,) = factory.calls
    assert call["extra"] == ["--collect-only", "-q"]
    assert call["marker_expr"] == "not slow" and call["passthrough"] == ["--durations=1"]


def test_collect_probe_that_hangs_returns_minus_one(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "unused", probe_mode="hang_no_heartbeat")
    n = run_suite.collect_probe(
        _spec(),
        python=sys.executable,
        cwd=tmp_path,
        env=dict(os.environ),
        log=tmp_path / "probe.log",
        command_factory=factory,
        timeout=1.0,
    )
    assert n == -1


def test_collect_probe_with_unparsable_output_returns_minus_one(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "unused", probe_mode="ok")  # prints a line, no "N tests collected"
    n = run_suite.collect_probe(
        _spec(),
        python=sys.executable,
        cwd=tmp_path,
        env=dict(os.environ),
        log=tmp_path / "probe.log",
        command_factory=factory,
        timeout=SLOW_STALL,
    )
    assert n == -1


def test_rc5_with_a_failed_probe_is_a_failure(fake_script: Path, tmp_path: Path) -> None:
    factory = Factory(fake_script, "rc5", probe_mode="ok")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "FAIL"
    assert "probe" in result.note.lower()


def test_run_job_builds_a_clean_child_environment(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "-x")
    monkeypatch.setenv("PYTEST_PLUGINS", "evil")
    monkeypatch.setenv("RUN_SUITE_TEST_KEEP_ME", "yes")
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    envfile = tmp_path / "env.json"
    factory = Factory(fake_script, "ok", envfile=envfile)
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "OK"
    seen = json.loads(envfile.read_text())
    assert seen["PYTEST_ADDOPTS"] is None and seen["PYTEST_PLUGINS"] is None
    assert seen["QT_QPA_PLATFORM"] == "offscreen"
    assert seen["KEEP_ME"] == "yes"
    assert Path(seen["HEARTBEAT"]) == result.heartbeat


# --------------------------------------------------------------------------- aggregate / summary


def test_aggregate_counts_and_exit_code_for_failing_run(tmp_path: Path) -> None:
    ok = _hand_result(
        tmp_path,
        "okjob",
        "OK",
        junit=_write_junit(tmp_path / "ok.xml", passed=3, failed=1, errors=1, skipped=1, xfailed=1),
    )
    rc5 = _hand_result(tmp_path, "rc5job", "RC5_OK", rc=5)
    s = run_suite.aggregate([ok, rc5], tmp_path / "merged.xml", elapsed=12.5)
    assert (s.passed, s.failed, s.skipped, s.xfailed, s.errors) == (3, 1, 1, 1, 1)
    assert (s.hung, s.crashed, s.rc5_ok) == (0, 0, 1)
    assert s.elapsed == 12.5
    root = ET.parse(tmp_path / "merged.xml").getroot()
    assert root.tag == "testsuites"
    assert len(list(root.iter("testcase"))) == 7
    assert run_suite.exit_code(s) == 1  # failures and errors present


def test_aggregate_all_green_exits_zero(tmp_path: Path) -> None:
    ok = _hand_result(tmp_path, "okjob", "OK", junit=_write_junit(tmp_path / "ok.xml", passed=2, skipped=1))
    rc5 = _hand_result(tmp_path, "rc5job", "RC5_OK", rc=5)
    s = run_suite.aggregate([ok, rc5], tmp_path / "merged.xml", elapsed=1.0)
    assert (s.passed, s.failed, s.errors, s.hung, s.crashed, s.skipped, s.rc5_ok) == (2, 0, 0, 0, 0, 1, 1)
    assert run_suite.exit_code(s) == 0


def test_aggregate_synthesizes_failures_for_hung_and_crashed_jobs(tmp_path: Path) -> None:
    hung = _hand_result(tmp_path, "hungjob", "HUNG", culprit="m.py::t", rc=None)
    crash = _hand_result(tmp_path, "crashjob", "CRASH", rc=-6)
    s = run_suite.aggregate([hung, crash], tmp_path / "merged.xml", elapsed=2.0)
    assert (s.hung, s.crashed) == (1, 1)
    assert s.failed == 2  # the synthetic testcases carry <failure>
    root = ET.parse(tmp_path / "merged.xml").getroot()
    synth = {tc.get("name"): tc for tc in root.iter("testcase") if tc.get("classname") == "run_suite"}
    assert set(synth) == {"hungjob::m.py::t", "crashjob::qt"}
    text = "".join(synth["hungjob::m.py::t"].find("failure").itertext())
    assert "HUNG" in text and "m.py::t" in text
    assert "hungjob.evidence.txt" in text
    assert "CRASH" in "".join(synth["crashjob::qt"].find("failure").itertext())
    assert run_suite.exit_code(s) == 1


@pytest.mark.parametrize("status", ["FAIL", "COLLECT_ERROR"])
def test_aggregate_is_never_green_for_a_non_passing_job_without_junit(tmp_path: Path, status: str) -> None:
    """Not pinned by the interface text: a job that did not pass must not exit 0 even with no junit."""
    bad = _hand_result(tmp_path, "badjob", status, rc=2)
    s = run_suite.aggregate([bad], tmp_path / "merged.xml", elapsed=1.0)
    assert run_suite.exit_code(s) == 1


def test_summary_line_is_one_exact_line() -> None:
    s = run_suite.Summary(
        passed=7556, failed=0, skipped=12, xfailed=3, errors=0, hung=0, crashed=0, rc5_ok=13, elapsed=3812.4
    )
    line = run_suite.summary_line(s)
    assert "\n" not in line
    assert line == (
        "run_suite: 7556 passed, 0 failed, 12 skipped, 3 xfailed, 0 errors, 0 hung, 0 crashed, "
        "13 rc5-ok in 3812.4s"
    )


@pytest.mark.parametrize(
    "field, value, expected",
    [
        ("failed", 1, 1),
        ("errors", 1, 1),
        ("hung", 1, 1),
        ("crashed", 1, 1),
        ("skipped", 5, 0),
        ("xfailed", 5, 0),
        ("rc5_ok", 5, 0),
        ("passed", 100, 0),
    ],
)
def test_exit_code_by_summary_field(field: str, value: int, expected: int) -> None:
    base = dict(passed=1, failed=0, skipped=0, xfailed=0, errors=0, hung=0, crashed=0, rc5_ok=0, elapsed=1.0)
    base[field] = value
    assert run_suite.exit_code(run_suite.Summary(**base)) == expected


# --------------------------------------------------------------------------- main()


def _fake_job_runner(calls: list):
    """run_job substitute: records (spec, kwargs), writes a passing junit, never spawns a process."""

    def fake(spec, out_dir, **kw):
        calls.append((spec, kw))
        out_dir.mkdir(parents=True, exist_ok=True)
        log = out_dir / f"{spec.name}.log"
        log.write_text("", encoding="utf-8")
        hb = out_dir / f"{spec.name}.heartbeat"
        hb.write_text("", encoding="utf-8")
        junit = _write_junit(out_dir / f"{spec.name}.xml", passed=1)
        return JobResult(spec, "OK", 0, None, junit, log, hb, [], 0.1)

    return fake


@pytest.fixture
def main_env(tmp_path: Path, monkeypatch):
    """A fake repo root with one Qt and one pure test file, a recording run_job and subprocess.run."""
    monkeypatch.setattr(run_suite, "REPO_ROOT", tmp_path)
    tdir = tmp_path / "test_scripts"
    tdir.mkdir()
    qt_file = tdir / "test_qt_x.py"
    qt_file.write_text("from PySide6 import QtCore\n", encoding="utf-8")
    pure_file = tdir / "test_pure_x.py"
    pure_file.write_text("import json\n", encoding="utf-8")
    jobs: list = []
    monkeypatch.setattr(run_suite, "run_job", _fake_job_runner(jobs))
    runs: list = []
    result = {"rc": 0}

    def fake_run(cmd, **kw):
        runs.append(list(cmd))

        class Done:
            returncode = result["rc"] if cmd[-1] == "report" else 0

        return Done()

    monkeypatch.setattr(run_suite.subprocess, "run", fake_run)
    return {
        "root": tmp_path,
        "qt": qt_file,
        "pure": pure_file,
        "jobs": jobs,
        "runs": runs,
        "report_rc": result,
        "out": tmp_path / "out",
    }


def test_main_runs_both_lanes_and_merges_one_junit(main_env, capsys) -> None:
    rc = run_suite.main(["--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])])
    assert rc == 0
    names = [spec.name for spec, _ in main_env["jobs"]]
    assert names == ["pure", "test_qt_x"]  # the pure job first, then one job per Qt file
    merged = ET.parse(main_env["out"] / "junit.xml").getroot()
    assert merged.tag == "testsuites" and len(list(merged.iter("testcase"))) == 2
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1].startswith("run_suite: 2 passed, 0 failed")
    assert sum(1 for line in out if line.startswith("run_suite: ") and " passed, " in line) == 1
    assert main_env["runs"] == []  # no coverage commands without --cov


def test_main_passes_marker_durations_and_double_dash_args_to_every_child(main_env) -> None:
    rc = run_suite.main(
        [
            "-m", "not local_only",
            "--durations", "7",
            "--lane", "qt",
            "--no-rerun",
            "--stall-seconds", "12",
            "--file-ceiling", "34",
            "--files", str(main_env["qt"]), str(main_env["pure"]),
            "--out", str(main_env["out"]),
            "--junit", str(main_env["root"] / "report.xml"),
            "--", "-x", "-k", "needle",
        ]
    )  # fmt: skip
    assert rc == 0
    ((spec, kw),) = main_env["jobs"]
    assert spec.name == "test_qt_x" and spec.lane == "qt"
    assert spec.marker_expr == "not local_only"
    assert spec.passthrough == ["--durations=7", "-x", "-k", "needle"]
    assert kw["rerun"] is False and kw["stall_seconds"] == 12 and kw["file_ceiling"] == 34
    assert (main_env["root"] / "report.xml").exists()


def test_main_with_a_missing_file_or_no_jobs_returns_one(main_env, capsys) -> None:
    assert run_suite.main(["--files", str(main_env["root"] / "test_nope.py"), "--out", str(main_env["out"])]) == 1
    assert run_suite.main(["--lane", "pure", "--files", str(main_env["qt"]), "--out", str(main_env["out"])]) == 1
    assert main_env["jobs"] == []
    assert "no such test file" in capsys.readouterr().out


def test_main_cov_gives_children_the_floor_override_and_gates_on_the_final_report(main_env) -> None:
    """S4-03: each child covers a slice, so only the final `coverage report` may enforce fail_under."""
    stale = main_env["root"] / ".coverage"
    stale.write_text("stale", encoding="utf-8")
    argv = ["--cov", "--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]
    rc = run_suite.main(argv)
    assert rc == 0
    assert not stale.exists(), ".coverage must be deleted before the children start"
    for spec, _ in main_env["jobs"]:
        assert spec.passthrough == ["--cov", "--cov-append", "--cov-report=", "--cov-fail-under=0"]
    cov_cmds = [cmd[1:] for cmd in main_env["runs"]]
    assert cov_cmds == [["-m", "coverage", "xml"], ["-m", "coverage", "report"]]

    main_env["jobs"].clear()
    main_env["runs"].clear()
    main_env["report_rc"]["rc"] = 2  # coverage's own fail_under exit code
    assert run_suite.main(argv) == 1, "a failing coverage report must force exit 1"


# --------------------------------------------------------------------------- guards (red until S3)


def _step_text(workflow: str, step_name: str) -> str:
    _, sep, tail = workflow.partition(f"- name: {step_name}")
    assert sep, f"step {step_name!r} not found"
    nxt = tail.find("\n      - name:")
    return tail if nxt == -1 else tail[:nxt]


def test_guard_ci_functional_step_uses_run_suite() -> None:
    """RED until S3 rewrites the functional step of ci.yml to call scripts/run_suite.py."""
    ci = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    if not ci.exists():
        pytest.skip("no .github/workflows/ci.yml in this checkout")
    step = _step_text(ci.read_text(encoding="utf-8"), "Run functional suite")
    assert "scripts/run_suite.py" in step


def test_guard_claude_md_names_run_suite() -> None:
    """RED until S3 documents the runner as the whole-suite command in CLAUDE.md."""
    text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "scripts/run_suite.py" in text

# --------------------------------------------------------------------------- S4-10: nested pytest runs


def test_heartbeat_line_carries_the_writer_pid(monkeypatch, tmp_path) -> None:
    """Each line names the process that wrote it, so a nested pytest (a test that
    runs pytest in a subprocess inherits the env var) can be told apart from the
    session the supervisor is watching."""
    import os

    from scripts import pytest_heartbeat as hb

    target = tmp_path / "hb.jsonl"
    monkeypatch.setenv(HEARTBEAT_ENV, str(target))
    hb.pytest_runtest_logstart("t.py::test_a", None)
    events = read_heartbeat(target)
    assert len(events) == 1
    assert events[0]["pid"] == os.getpid()


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        # outer test a in flight; a nested pytest (pid 2) started and never finished b
        ([{"nodeid": "a", "phase": "start", "pid": 1}, {"nodeid": "b", "phase": "start", "pid": 2}], "a"),
        # outer a finished; a nested run's c is still open: nothing of OURS is in flight
        (
            [
                {"nodeid": "a", "phase": "start", "pid": 1},
                {"nodeid": "a", "phase": "finish", "pid": 1},
                {"nodeid": "c", "phase": "start", "pid": 2},
            ],
            None,
        ),
        # a nested run finishing the same nodeid must not close the outer one
        (
            [
                {"nodeid": "a", "phase": "start", "pid": 1},
                {"nodeid": "a", "phase": "start", "pid": 2},
                {"nodeid": "a", "phase": "finish", "pid": 2},
            ],
            "a",
        ),
        # lines without a pid (older format) still count
        ([{"nodeid": "a", "phase": "start"}, {"nodeid": "b", "phase": "start", "pid": 2}], "a"),
    ],
)
def test_pending_culprit_only_counts_the_first_writer_pid(events: list[dict], expected: str | None) -> None:
    assert pending_culprit(events) == expected

