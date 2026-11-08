"""Red-light tests for the supervised whole-suite runner (plans/archive/test-suite-never-hangs.md, 1.5).

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
import types
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


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def wait_for(path, timeout=30):
    deadline = time.time() + timeout
    while not os.path.exists(path) and time.time() < deadline:
        time.sleep(0.02)


def spawn_sleeper(pid_path, exe=None, lifetime=40, **kw):
    # A bounded descendant (mode "sleeper"); even with no std kwargs it holds our stdout, the supervised log.
    cmd = [exe or sys.executable, sys.argv[0], "sleeper", "--pidfile", pid_path, "--lifetime", str(lifetime)]
    return subprocess.Popen(cmd, **kw)


def sleeper_real_pid(pid_path):
    # On a venv Popen().pid is the launcher redirector; the sleeper reports its own os.getpid().
    wait_for(pid_path)
    with open(pid_path, encoding="utf-8") as f:
        return json.load(f)


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
elif mode == "sleeper":
    # Reports its own pid, then ends by itself: an orphan of a red run cannot outlive 40 s.
    write_json(pidfile, os.getpid())
    time.sleep(float(opt("--lifetime") or 40))
elif mode == "exit_leaving_grandchild":
    # Orphan class 1: the root exits 0 (at once, or once --release exists) while its grandchild lives.
    gc = spawn_sleeper(pidfile + ".gc")
    write_json(pidfile, {"main": os.getpid(), "grandchild": gc.pid, "grandchild_real": sleeper_real_pid(pidfile + ".gc")})
    release = opt("--release")
    if release:
        wait_for(release)
    sys.exit(0)
elif mode == "intermediate":
    # Spawns the grandchild, reports it and exits: the grandchild's parent pid then names a dead process.
    gc = spawn_sleeper(pidfile + ".gc")
    write_json(pidfile, {"grandchild": gc.pid, "grandchild_real": sleeper_real_pid(pidfile + ".gc")})
    sys.exit(0)
elif mode == "hang_with_orphaned_grandchild":
    # Orphan class 3: the root stays alive, the intermediate is dead, the grandchild lives behind it.
    inter = subprocess.Popen([sys.executable, sys.argv[0], "intermediate", "--pidfile", pidfile + ".inter"])
    inter.wait(timeout=30)
    with open(pidfile + ".inter", encoding="utf-8") as f:
        orphan = json.load(f)
    write_json(pidfile, {"main": os.getpid(), "intermediate": inter.pid, **orphan})
    beat(HANG_NODE, "start")
    time.sleep(60)
elif mode == "spawn_loop":
    # The spawn race, report E3's spawner: the base interpreter (no venv redirector) with our std handles, one
    # sleeper (--lifetime s) every ~1 ms up to --cap, each Popen pid logged at once in --spawndir/launched.txt.
    spawndir = opt("--spawndir")
    base = getattr(sys, "_base_executable", sys.executable)
    lifetime = opt("--lifetime") or 40
    write_json(pidfile, {"main": os.getpid()})
    with open(os.path.join(spawndir, "launched.txt"), "w", encoding="utf-8") as launched:
        for i in range(int(opt("--cap") or 150)):
            child = spawn_sleeper(
                os.path.join(spawndir, "s%d.pid" % i), base, lifetime,
                stdout=sys.stdout, stderr=sys.stderr, stdin=subprocess.DEVNULL,
            )
            launched.write("%d\n" % child.pid)
            launched.flush()
            time.sleep(0.001)
    time.sleep(60)
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
    # Isolate child configuration even when TEMP lives below the checkout.
    pytester.makefile(".ini", pytest="[pytest]\n")
    pytester.makepyfile(
        test_mini="def test_a():\n    assert True\n\n\ndef test_b():\n    assert True\n"
    )
    result = pytester.runpytest_inprocess(
        "--rootdir", str(pytester.path), "-c", str(pytester.path / "pytest.ini"),
        "-p", "scripts.pytest_heartbeat", "-p", "no:cacheprovider",
    )
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


def test_pytest_command_layout(tmp_path: Path, monkeypatch) -> None:
    # External file paths stay absolute, independent of the host TEMP location.
    monkeypatch.setattr(run_suite, "REPO_ROOT", tmp_path / "fake-repo-root")
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


def test_pytest_command_without_optionals(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_suite, "REPO_ROOT", tmp_path / "fake-repo-root")
    f1 = tmp_path / "test_one.py"
    cmd = run_suite.pytest_command(JobSpec("job", [f1], "pure"), tmp_path / "j.xml", "PY")
    assert cmd == [
        "PY", "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider",
        "--junitxml", str(tmp_path / "j.xml"), str(f1),
    ]  # fmt: skip


def test_repository_test_paths_do_not_overflow_windows_command_line(monkeypatch, tmp_path):
    """The pure lane must fit CreateProcess even from a nested worktree."""
    import subprocess

    root = tmp_path / ("nested-worktree-" * 8)
    monkeypatch.setattr(run_suite, "REPO_ROOT", root)
    files = [root / "test_scripts" / f"test_realistic_module_name_{i:03d}.py" for i in range(300)]
    cmd = run_suite.pytest_command(JobSpec("pure", files, "pure"), tmp_path / "j.xml", "PY")
    assert len(subprocess.list2cmdline(cmd)) < 32767
    assert [root / value for value in cmd[-len(files):]] == files


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
    assert cov_cmds == [["-m", "coverage", "combine"], ["-m", "coverage", "xml"], ["-m", "coverage", "report"]]

    main_env["jobs"].clear()
    main_env["runs"].clear()
    main_env["report_rc"]["rc"] = 2  # coverage's own fail_under exit code
    assert run_suite.main(argv) == 1, "a failing coverage report must force exit 1"


# --------------------------------------------------------------------------- CI-faster: lanes in parallel


def test_main_cov_gives_every_job_its_own_data_file_and_clears_stale_ones(main_env) -> None:
    """Two children appending to one .coverage at once corrupt it, so each job (and its
    rerun, which shares the job's env) writes .coverage.<job>; `coverage combine` merges."""
    stale = main_env["root"] / ".coverage.old_job"
    stale.write_text("stale", encoding="utf-8")
    argv = ["--cov", "--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]
    assert run_suite.main(argv) == 0
    assert not stale.exists(), "a stale .coverage.* would be combined into this run's report"
    files = {spec.name: kw["base_env"]["COVERAGE_FILE"] for spec, kw in main_env["jobs"]}
    assert files == {
        "pure": str(main_env["root"] / ".coverage.pure"),
        "test_qt_x": str(main_env["root"] / ".coverage.test_qt_x"),
    }


def test_main_without_cov_sets_no_coverage_file(main_env, monkeypatch) -> None:
    # Under a --cov suite run this test's own process carries COVERAGE_FILE; only what
    # run_suite adds is under test.
    monkeypatch.delenv("COVERAGE_FILE", raising=False)
    assert run_suite.main(["--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]) == 0
    assert all("COVERAGE_FILE" not in kw["base_env"] for _spec, kw in main_env["jobs"])


def _lane_probe(monkeypatch, calls: list):
    """run_job fake whose pure job waits up to 5 s for the Qt job to have started."""
    import threading

    qt_started = threading.Event()
    inner = _fake_job_runner(calls)
    seen: dict[str, bool] = {}

    def fake(spec, out_dir, **kw):
        if spec.lane == "qt":
            qt_started.set()
        else:
            seen["overlapped"] = qt_started.wait(timeout=5)
        return inner(spec, out_dir, **kw)

    monkeypatch.setattr(run_suite, "run_job", fake)
    return seen


def test_parallel_lanes_runs_the_pure_job_alongside_the_qt_lane(main_env, monkeypatch, capsys) -> None:
    seen = _lane_probe(monkeypatch, main_env["jobs"])
    argv = ["--parallel-lanes", "--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]
    assert run_suite.main(argv) == 0
    assert seen["overlapped"] is True, "the pure job never saw the Qt lane start: lanes ran serially"
    merged = ET.parse(main_env["out"] / "junit.xml").getroot()
    assert len(list(merged.iter("testcase"))) == 2
    out = capsys.readouterr().out.splitlines()
    assert any(line.startswith("[pure 1/1] pure (1 files) ... OK") for line in out)
    assert any(line.startswith("[qt 1/1] test_qt_x.py ... OK") for line in out)
    assert out[-1].startswith("run_suite: 2 passed, 0 failed")


def test_the_lanes_run_in_parallel_by_default(main_env, monkeypatch) -> None:
    seen = _lane_probe(monkeypatch, main_env["jobs"])
    assert run_suite.main(["--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]) == 0
    assert seen["overlapped"] is True, "no flag given: the pure job must still run beside the Qt lane"


def test_no_parallel_lanes_keeps_the_lanes_serial(main_env, monkeypatch) -> None:
    import threading

    order: list[str] = []
    inner = _fake_job_runner(main_env["jobs"])

    def fake(spec, out_dir, **kw):
        order.append(f"{spec.name}:{threading.current_thread() is threading.main_thread()}")
        return inner(spec, out_dir, **kw)

    monkeypatch.setattr(run_suite, "run_job", fake)
    argv = ["--no-parallel-lanes", "--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]
    assert run_suite.main(argv) == 0
    assert order == ["pure:True", "test_qt_x:True"]


def test_parallel_lanes_reports_results_in_job_order_and_fails_on_a_pure_failure(main_env, monkeypatch) -> None:
    inner = _fake_job_runner(main_env["jobs"])

    def fake(spec, out_dir, **kw):
        result = inner(spec, out_dir, **kw)
        if spec.lane == "pure":
            result.status = "FAIL"
            result.junit = _write_junit(out_dir / "pure.xml", passed=0, failed=1)
        return result

    monkeypatch.setattr(run_suite, "run_job", fake)
    argv = ["--parallel-lanes", "--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]
    assert run_suite.main(argv) == 1
    merged = ET.parse(main_env["out"] / "junit.xml").getroot()
    cases = [c.get("name") for c in merged.iter("testcase")]
    assert cases == ["f0", "p0"], "the pure job's results must come first, as in a serial run"


def test_parallel_lanes_reraises_a_crash_in_the_pure_thread(main_env, monkeypatch) -> None:
    inner = _fake_job_runner(main_env["jobs"])

    def fake(spec, out_dir, **kw):
        if spec.lane == "pure":
            raise RuntimeError("supervisor bug")
        return inner(spec, out_dir, **kw)

    monkeypatch.setattr(run_suite, "run_job", fake)
    argv = ["--parallel-lanes", "--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]
    with pytest.raises(RuntimeError, match="supervisor bug"):
        run_suite.main(argv)


def test_parallel_lanes_with_one_lane_only_still_runs(main_env) -> None:
    argv = ["--parallel-lanes", "--lane", "qt", "--files", str(main_env["qt"]), "--out", str(main_env["out"])]
    assert run_suite.main(argv) == 0
    assert [spec.name for spec, _ in main_env["jobs"]] == ["test_qt_x"]


def test_supervise_cancel_kills_the_child_and_raises(fake_script: Path, tmp_path: Path) -> None:
    """--parallel-lanes: when the main thread dies (Ctrl+C), the pure job's supervisor
    must end its child instead of letting it run to the ceiling behind the join."""
    import threading

    hb, log = tmp_path / "hb.jsonl", tmp_path / "child.log"
    env = {**os.environ, HEARTBEAT_ENV: str(hb)}
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    t0 = time.monotonic()
    with pytest.raises(run_suite.JobCancelled):
        run_suite.supervise(
            [sys.executable, str(fake_script), "hang"],
            cwd=tmp_path,
            env=env,
            heartbeat=hb,
            log=log,
            stall_seconds=SLOW_STALL,
            file_ceiling=SLOW_CEILING,
            poll_seconds=POLL,
            cancel=cancel,
        )
    assert time.monotonic() - t0 < 30


def test_parallel_lanes_cancels_the_pure_job_when_the_qt_lane_raises(main_env, monkeypatch) -> None:
    import threading

    inner = _fake_job_runner(main_env["jobs"])
    seen: dict[str, bool] = {}
    pure_started = threading.Event()

    def fake(spec, out_dir, **kw):
        if spec.lane == "pure":
            pure_started.set()
            seen["cancelled"] = kw["cancel"].wait(timeout=10)
            raise run_suite.JobCancelled(spec.name)
        pure_started.wait(timeout=10)
        raise KeyboardInterrupt

    monkeypatch.setattr(run_suite, "run_job", fake)
    argv = ["--parallel-lanes", "--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]
    with pytest.raises(KeyboardInterrupt):  # the main thread's exception wins, the worker's is dropped
        run_suite.main(argv)
    assert seen["cancelled"] is True, "the pure job was never told to stop"
    del inner


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



# ---- characterization (2026-11-03, kill path, owner step 1)
#
# Owner step (i) (TODOS "2026-11-03 /simplify pass"): no code change; every test below passes on today's
# scripts/run_suite.py and locks what the _supervised_pytest / process-tree refactor touches.
# RULE for every real child spawned here: override HEARTBEAT_ENV. FAKE_CHILD's beats carry no pid, so a
# child that inherits the outer run_suite heartbeat would plant an unfinished start in the outer job.

CANCEL_CEILING = 30.0  # cancel / Ctrl+C tests: only the event may end the child; a dropped cancel fails in 30 s
_REAL_RUN_JOB = run_suite.run_job  # main_env swaps run_suite.run_job before a test body runs


def _set_when_exists(path: Path, event, timeout: float = 20.0):
    """Set *event* once *path* exists, or after *timeout*, so no test can wait forever."""
    import threading

    def watch() -> None:
        deadline = time.monotonic() + timeout
        while not event.is_set() and not path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        event.set()

    thread = threading.Thread(target=watch, name="charz-set-when-exists", daemon=True)
    thread.start()
    return thread


def _hang_tree_cmd(fake_script: Path, pidfile: Path) -> list[str]:
    return [sys.executable, str(fake_script), "hang_with_grandchild", "--pidfile", str(pidfile)]


def _assert_tree_gone(pidfile: Path) -> None:
    pids = json.loads(pidfile.read_text())
    for role in ("main", "grandchild", "grandchild_real"):
        assert _wait_gone(pids[role]), f"{role} pid {pids[role]} survived the kill (orphan)"


def _supervise_tree(fake_script: Path, tmp_path: Path, pidfile: Path, **kw) -> SupervisedExit:
    """supervise() on a real child + grandchild that only a cancel / an exception can end before 30 s."""
    hb, log = tmp_path / "hb.jsonl", tmp_path / "child.log"
    return run_suite.supervise(
        _hang_tree_cmd(fake_script, pidfile),
        cwd=tmp_path,
        env={**os.environ, HEARTBEAT_ENV: str(hb)},
        heartbeat=hb,
        log=log,
        stall_seconds=SLOW_STALL,
        file_ceiling=CANCEL_CEILING,
        poll_seconds=POLL,
        **kw,
    )


def _spawn_tree(fake_script: Path, tmp_path: Path, pidfile: Path):
    """The same real tree outside supervise and outside any job (never suspended, no attach), so the Windows
    kill has only its parent-pid walk: the path attach falls back to.  Waits for the pid file."""
    import subprocess

    kw = {} if sys.platform == "win32" else {"start_new_session": True}  # killpg needs pgid == pid
    with open(tmp_path / "spawn.log", "wb") as log_fh:
        proc = subprocess.Popen(
            _hang_tree_cmd(fake_script, pidfile),
            cwd=str(tmp_path),
            env={**os.environ, HEARTBEAT_ENV: str(tmp_path / "spawn_hb.jsonl")},
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            **kw,
        )
    deadline = time.monotonic() + 20
    while not pidfile.exists() and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    return proc


def _end(proc) -> None:
    """Test-owned cleanup of a _spawn_tree root that a failed assertion left running."""
    if proc is not None and proc.poll() is None:
        proc.kill()
        proc.wait(timeout=10)


def test_charz_supervise_cancel_ends_the_whole_tree(fake_script: Path, tmp_path: Path, caplog) -> None:
    """(a) cancel set while a real child + grandchild run: JobCancelled, and main, grandchild, its real python gone."""
    import threading

    pidfile = tmp_path / "pids.json"
    cancel = threading.Event()
    watcher = _set_when_exists(pidfile, cancel)
    try:
        with pytest.raises(run_suite.JobCancelled):
            _supervise_tree(fake_script, tmp_path, pidfile, cancel=cancel)
        assert pidfile.exists(), "cancel fired before the child spawned its grandchild"
        _assert_tree_gone(pidfile)
        # Live since S6 (F2): the except-BaseException handler keeps _kill_tree's survivors and warns on them.
        assert "not gone after the kill" not in caplog.text
    finally:
        cancel.set()
        watcher.join(timeout=5)
        _reap(pidfile)


def test_charz_cancel_reaches_the_rerun_and_ends_its_tree(fake_script: Path, tmp_path: Path) -> None:
    """run_job hands cancel to the rerun's supervisor: a cancel during the rerun raises and leaves no orphan."""
    import threading

    pidfile = tmp_path / "pids.json"
    factory = Factory(fake_script, "exit_in_flight", rerun_mode="hang_with_grandchild", pidfile=pidfile)
    cancel = threading.Event()
    watcher = _set_when_exists(pidfile, cancel)  # only the rerun writes the pid file
    try:
        with pytest.raises(run_suite.JobCancelled):
            _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=CANCEL_CEILING, cancel=cancel)
        assert [run["deselect"] for run in factory.runs] == [[], [SECOND]]
        assert pidfile.exists(), "cancel fired before the rerun spawned its grandchild"
        _assert_tree_gone(pidfile)
    finally:
        cancel.set()
        watcher.join(timeout=5)
        _reap(pidfile)


def test_charz_parallel_lanes_failure_ends_the_pure_jobs_real_tree(
    main_env, fake_script: Path, tmp_path: Path, monkeypatch
) -> None:
    """--parallel-lanes end to end: the Qt lane raises while the pure job's real tree runs; none of it survives."""
    pidfile = tmp_path / "pids.json"
    factory = Factory(fake_script, "hang_with_grandchild", pidfile=pidfile)

    def fake(spec, out_dir, **kw):
        if spec.lane == "qt":
            deadline = time.monotonic() + 20
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            raise KeyboardInterrupt
        return _REAL_RUN_JOB(spec, out_dir, **{**kw, "cwd": tmp_path, "command_factory": factory, "poll_seconds": POLL})

    monkeypatch.setattr(run_suite, "run_job", fake)
    argv = [
        "--parallel-lanes", "--file-ceiling", str(CANCEL_CEILING),
        "--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"]),
    ]  # fmt: skip
    try:
        with pytest.raises(KeyboardInterrupt):
            run_suite.main(argv)
        assert pidfile.exists(), "the Qt lane raised before the pure child spawned its grandchild"
        _assert_tree_gone(pidfile)
    finally:
        _reap(pidfile)


def test_charz_ctrl_c_inside_the_poll_loop_still_ends_the_whole_tree(fake_script: Path, tmp_path: Path) -> None:
    """(b) a KeyboardInterrupt delivered while supervise polls (the real Ctrl+C path) kills the whole tree."""
    import _thread
    import threading

    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler, (
        "SIGINT is not Python's default handler here; interrupt_main() would do nothing"
    )
    pidfile = tmp_path / "pids.json"
    gate, stop, fired = threading.Lock(), threading.Event(), threading.Event()

    def watch() -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with gate:  # never fires once the test set `stop`; fires at most once
                if stop.is_set():
                    return
                if pidfile.exists():
                    fired.set()
                    _thread.interrupt_main()  # what a console Ctrl+C does: KeyboardInterrupt on the main thread
                    return
            time.sleep(0.05)

    watcher = threading.Thread(target=watch, name="charz-ctrl-c", daemon=True)
    watcher.start()
    try:
        with pytest.raises(KeyboardInterrupt):
            _supervise_tree(fake_script, tmp_path, pidfile)
        with gate:
            stop.set()
        assert fired.is_set()
        _assert_tree_gone(pidfile)
    finally:
        with gate:
            stop.set()
        watcher.join(timeout=5)
        _reap(pidfile)


def test_charz_kill_tree_ends_every_member_and_closes_the_callers_handles(fake_script: Path, tmp_path: Path) -> None:
    """(c) Windows: every member arrives pinned by a handle and leaves with handle None; POSIX: no handles, killpg."""
    pidfile = tmp_path / "pids.json"
    proc = None
    members: list = []
    try:
        proc = _spawn_tree(fake_script, tmp_path, pidfile)
        assert pidfile.exists(), "the fake child never spawned its grandchild"
        pids = json.loads(pidfile.read_text())
        members = run_suite._descendants(proc.pid)
        assert {pids["grandchild"], pids["grandchild_real"]} <= {m.pid for m in members}
        if sys.platform == "win32":
            assert all(m.handle for m in members), "every Windows member is pinned by an open handle"
        else:
            assert all(m.handle is None for m in members)
        assert run_suite._kill_tree(proc, members) == []
        assert [m.pid for m in members if m.handle is not None] == [], "a pinned handle outlived _kill_tree"
        assert proc.poll() is not None
        _assert_tree_gone(pidfile)
    finally:
        run_suite._close_members(members)
        _end(proc)
        _reap(pidfile)


def test_charz_kill_tree_without_members_still_ends_the_tree(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    """Windows re-enumerates right before the kill and closes what it opened; POSIX needs no enumeration (killpg)."""
    pidfile = tmp_path / "pids.json"
    proc = None
    opened: list = []
    real_descendants = run_suite._win_descendants  # the platform enumerator stays a module function

    def spy(pid):
        found = real_descendants(pid)
        opened.extend(found)
        return found

    try:
        proc = _spawn_tree(fake_script, tmp_path, pidfile)
        assert pidfile.exists(), "the fake child never spawned its grandchild"
        monkeypatch.setattr(run_suite, "_win_descendants", spy)
        assert run_suite._kill_tree(proc, []) == []
        if sys.platform == "win32":
            assert opened, "Windows must re-enumerate the tree right before the kill"
        assert [m.pid for m in opened if m.handle is not None] == []
        _assert_tree_gone(pidfile)
    finally:
        run_suite._close_members(opened)
        _end(proc)
        _reap(pidfile)


def test_charz_tree_kill_uses_the_platform_primitive(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    """POSIX kills the process group with SIGKILL; Windows terminates only handles it enumerated (never a bare pid).

    Covers a live root with a reachable grandchild only (same group on POSIX, ppid walk on Windows).
    """
    pidfile = tmp_path / "pids.json"
    proc = None
    members: list = []
    calls: list = []
    try:
        proc = _spawn_tree(fake_script, tmp_path, pidfile)
        assert pidfile.exists(), "the fake child never spawned its grandchild"
        members = run_suite._descendants(proc.pid)
        assert members, "the tree has descendants to aim at"
        if sys.platform == "win32":
            real_terminate = run_suite._k32.TerminateProcess

            def spy_terminate(handle, code):
                calls.append(handle)
                return real_terminate(handle, code)

            monkeypatch.setattr(run_suite._k32, "TerminateProcess", spy_terminate)
            pinned = [m.handle for m in members]  # snapshot: _kill_tree sets member.handle to None
            assert all(pinned)
        else:
            real_killpg = run_suite.os.killpg

            def spy_killpg(pgid, sig):
                calls.append((pgid, sig))
                return real_killpg(pgid, sig)

            monkeypatch.setattr(run_suite.os, "killpg", spy_killpg)
        assert run_suite._kill_tree(proc, members) == []
        if sys.platform == "win32":
            assert calls, "Windows must terminate the members by handle"
            assert set(calls) <= set(pinned), "TerminateProcess was called on a handle that is not an enumerated member"
        else:
            assert (proc.pid, signal.SIGKILL) in calls, "POSIX must SIGKILL the process group of the root"
        _assert_tree_gone(pidfile)
    finally:
        run_suite._close_members(members)
        _end(proc)
        _reap(pidfile)


def test_charz_hung_probe_tree_is_killed_with_no_orphan(fake_script: Path, tmp_path: Path) -> None:
    """A collect-only probe that hangs with a grandchild is killed on its stall, tree and all; the job is FAIL.

    Covers a live root with a reachable grandchild only (same group on POSIX, ppid walk on Windows).
    """
    pidfile = tmp_path / "pids.json"
    factory = Factory(fake_script, "rc5", probe_mode="hang_with_grandchild", pidfile=pidfile)
    try:
        # The probe's stall and ceiling are both stall_seconds: long enough for the grandchild to start.
        result = _run(factory, tmp_path, rerun=False, stall_seconds=6.0, file_ceiling=SLOW_CEILING)
        assert result.status == "FAIL" and "probe failed or hung" in result.note
        assert len(factory.probes) == 1
        assert pidfile.exists(), "the probe never spawned its grandchild before it was killed"
        _assert_tree_gone(pidfile)
    finally:
        _reap(pidfile)


def test_charz_supervise_popen_flags_by_platform(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    """(c) POSIX children start a new session (killpg relies on pgid == pid); Windows children start suspended
    (attach puts them in their job before they run, then resumes them) and get no other flag."""
    real_popen = run_suite.subprocess.Popen
    seen: list[dict] = []

    def spy(*args, **kwargs):
        seen.append(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(run_suite.subprocess, "Popen", spy)
    hb, log = tmp_path / "hb.jsonl", tmp_path / "child.log"
    ex = run_suite.supervise(
        [sys.executable, str(fake_script), "ok"],
        cwd=tmp_path,
        env={**os.environ, HEARTBEAT_ENV: str(hb)},
        heartbeat=hb,
        log=log,
        stall_seconds=SLOW_STALL,
        file_ceiling=SLOW_CEILING,
        poll_seconds=POLL,
    )
    assert ex.returncode == 0
    (kw,) = seen
    assert kw["stdin"] == run_suite.subprocess.DEVNULL and kw["stderr"] == run_suite.subprocess.STDOUT
    assert kw["cwd"] == str(tmp_path) and kw["env"][HEARTBEAT_ENV] == str(hb)
    if sys.platform == "win32":
        assert not kw.get("start_new_session")
        # CREATE_SUSPENDED (0x4) only, the Job Object's rewrite of this pin (plans/run-suite-job-object.md):
        # nothing the child spawns can start outside its job.  No CREATE_NEW_PROCESS_GROUP, no breakaway:
        # children still share the runner's console and process group, so a console Ctrl+C reaches them too.
        assert kw.get("creationflags", 0) == 0x00000004
    else:
        assert kw.get("start_new_session") is True


def test_charz_pyspy_targets_by_platform(tmp_path: Path, monkeypatch) -> None:
    """Windows dumps the root and its python members only (never conhost.exe); POSIX dumps every member."""
    calls: list = []

    class Done:
        returncode = 0
        stdout = "stack\n"
        stderr = ""

    class Root:
        pid = 10

    def fake_run(cmd, **kw):
        calls.append((list(cmd), kw))
        return Done()

    monkeypatch.setattr(run_suite.shutil, "which", lambda name, *a, **k: "PYSPY" if name == "py-spy" else None)
    monkeypatch.setattr(run_suite.subprocess, "run", fake_run)
    members = [
        run_suite._TreeMember(11, "python.exe"),
        run_suite._TreeMember(12, "conhost.exe"),
        run_suite._TreeMember(13, "Python3.10"),
    ]
    hb = tmp_path / "job.heartbeat"
    hb.write_text("", encoding="utf-8")
    log = tmp_path / "job.log"
    log.write_text("tail\n", encoding="utf-8")
    evidence = run_suite._collect_evidence(
        Root(), members, heartbeat=hb, log=log, evidence_dir=tmp_path / "ev", reason="stall", elapsed=1.0
    )
    expected = [10, 11, 13] if sys.platform == "win32" else [10, 11, 12, 13]
    assert [cmd for cmd, _ in calls] == [["PYSPY", "dump", "--native", "--pid", str(pid)] for pid in expected]
    assert all(kw["timeout"] == run_suite._PYSPY_TIMEOUT for _, kw in calls)
    assert {p.name for p in evidence} == {"job.pyspy.txt", "job.heartbeat", "job.tail.log"}  # names may move

    calls.clear()
    monkeypatch.setattr(run_suite.shutil, "which", lambda *a, **k: None)
    evidence = run_suite._collect_evidence(
        Root(), members, heartbeat=hb, log=log, evidence_dir=tmp_path / "ev2", reason="stall", elapsed=1.0
    )
    assert calls == []
    assert {p.name for p in evidence} == {"job.heartbeat", "job.tail.log"}
    assert "py-spy not on PATH" in (tmp_path / "ev2" / "job.tail.log").read_text(encoding="utf-8")


def test_charz_an_enumeration_failure_never_stops_the_kill(
    fake_script: Path, tmp_path: Path, monkeypatch, caplog
) -> None:
    """Enumeration is best-effort: its exception is logged and swallowed, and the cancel kill still ends the child."""
    import threading

    def broken(pid):
        raise RuntimeError("enumeration broke")

    monkeypatch.setattr(run_suite, "_win_descendants", broken)
    monkeypatch.setattr(run_suite, "_posix_descendants", broken)
    assert run_suite._descendants(os.getpid()) == []
    assert "could not enumerate" in caplog.text

    real_popen = run_suite.subprocess.Popen
    popened: list = []

    def spy(*args, **kwargs):
        popened.append(real_popen(*args, **kwargs))
        return popened[-1]

    monkeypatch.setattr(run_suite.subprocess, "Popen", spy)
    pidfile = tmp_path / "pids.json"
    cancel = threading.Event()
    watcher = _set_when_exists(pidfile, cancel)
    try:
        with pytest.raises(run_suite.JobCancelled):  # the except handler at the most dangerous site
            _supervise_tree(fake_script, tmp_path, pidfile, cancel=cancel)
        (proc,) = popened
        assert proc.poll() is not None, "the child outlived a kill whose tree enumeration failed"
        assert pidfile.exists()
        assert _wait_gone(json.loads(pidfile.read_text())["main"])
        # No kind needs the enumeration for the kill: POSIX kills the process group, Windows terminates the
        # child's job (the walk used to be the only Windows reach, so the grandchild survived here).
        _assert_tree_gone(pidfile)
    finally:
        cancel.set()
        watcher.join(timeout=5)
        _reap(pidfile)


def test_charz_posix_descendants_from_procfs(monkeypatch) -> None:
    """Linux /proc walk: ppid is the 2nd field after the LAST ')', the name sits between the outer parens."""
    stats = {
        "self": None,
        "100": "100 (python3) S 1 100 100 0",
        "101": "101 (py (x) y) S 100 100 100 0",
        "102": None,  # vanished between the listing and the read
        "103": "103 (sh) S 101 100 100 0",
        "200": "200 (other) S 1 200 200 0",
    }

    class Stat:
        def __init__(self, text):
            self.text = text

        def read_text(self):
            if self.text is None:
                raise OSError("gone")
            return self.text

    class Entry:
        def __init__(self, name):
            self.name = name

        def __truediv__(self, child):
            return Stat(stats[self.name])

    class ProcFs:
        def __init__(self, *args):
            pass

        def is_dir(self):
            return True

        def iterdir(self):
            return [Entry(name) for name in stats]

    monkeypatch.setattr(run_suite, "Path", ProcFs)
    members = run_suite._posix_descendants(100)
    assert sorted((m.pid, m.name, m.handle) for m in members) == [(101, "py (x) y", None), (103, "sh", None)]


def test_charz_posix_descendants_ps_fallback(monkeypatch) -> None:
    """No /proc (macOS): one `ps -A -o pid=,ppid=,comm=`; names may hold spaces; garbage lines and a missing ps are safe."""

    class NoProcFs:
        def __init__(self, *args):
            pass

        def is_dir(self):
            return False

    listing = "\n".join(
        [
            "    1     0 launchd",
            "  100     1 /usr/bin/python3",
            "  101   100 /Library/Frameworks/Python Framework/python3",
            "  102   101 sh",
            "  103   100 conhost",
            "  200     1 unrelated",
            "garbage line",
        ]
    )
    seen: list = []

    class Done:
        stdout = listing

    def fake_run(cmd, **kw):
        seen.append(list(cmd))
        return Done()

    def missing_ps(cmd, **kw):
        raise FileNotFoundError("ps")

    monkeypatch.setattr(run_suite, "Path", NoProcFs)
    monkeypatch.setattr(run_suite.subprocess, "run", fake_run)
    members = run_suite._posix_descendants(100)
    assert seen == [["ps", "-A", "-o", "pid=,ppid=,comm="]]
    assert sorted((m.pid, m.name) for m in members) == [
        (101, "/Library/Frameworks/Python Framework/python3"),
        (102, "sh"),
        (103, "conhost"),
    ]
    monkeypatch.setattr(run_suite.subprocess, "run", missing_ps)
    assert run_suite._posix_descendants(100) == []


def _pytest_ini_value(name: str) -> str:
    """One scalar from pyproject's [tool.pytest.ini_options] (regex: Python 3.10 has no tomllib)."""
    import re

    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    _, sep, tail = text.partition("[tool.pytest.ini_options]")
    assert sep, "pyproject.toml has no [tool.pytest.ini_options] table"
    table = re.split(r"(?m)^\[", tail, maxsplit=1)[0]
    match = re.search(rf"(?m)^{re.escape(name)}\s*=\s*(\S+)", table)
    assert match, f"{name} is not set in [tool.pytest.ini_options]"
    return match.group(1)


def _ci_text() -> str:
    return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _ci_suite_flag(flag: str) -> str | None:
    """The value of *flag* on the functional-suite `run:` line of ci.yml (None when absent)."""
    import re

    step = _step_text(_ci_text(), "Run functional suite")
    (run,) = [ln for ln in step.splitlines() if ln.strip().startswith("run:") and "scripts/run_suite.py" in ln]
    match = re.search(rf"(?:^|\s){re.escape(flag)}[ =](\S+)", run)
    return match.group(1) if match else None


def _effective_timing(main_env) -> tuple[float, float]:
    """(stall, ceiling) main hands every job with no timing flags, read where run_job receives them."""
    argv = ["--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]
    assert run_suite.main(argv) == 0
    stalls = {kw["stall_seconds"] for _spec, kw in main_env["jobs"]}
    ceilings = {kw["file_ceiling"] for _spec, kw in main_env["jobs"]}
    assert len(stalls) == len(ceilings) == 1, "every job must get the same timing"
    return stalls.pop(), ceilings.pop()


def test_charz_hang_layers_fire_in_order(main_env) -> None:
    """(d) GUARD: faulthandler's in-process exit (pyproject) fires before the external stall kill; CI never lifts the ceiling."""
    stall, ceiling = _effective_timing(main_env)
    assert _pytest_ini_value("faulthandler_exit_on_timeout") == "true"
    faulthandler_timeout = float(_pytest_ini_value("faulthandler_timeout"))
    assert 0 < faulthandler_timeout < stall
    ci_stall = _ci_suite_flag("--stall-seconds")
    assert faulthandler_timeout < (float(ci_stall) if ci_stall is not None else stall)
    ci_ceiling = _ci_suite_flag("--file-ceiling")
    assert ci_ceiling is not None, "CI passes --file-ceiling today; drop this line only together with the CI change"
    assert float(ci_ceiling) <= ceiling


def test_charz_effective_timing_defaults_today(main_env) -> None:
    """May move (owner: timing may change): today's defaults, resolved in _parse_args."""
    assert _effective_timing(main_env) == (600.0, 3600.0)


def test_charz_timing_constants_today() -> None:
    """May move: every timing knob outside main, so the one-resolution refactor accounts for each."""
    import inspect

    assert run_suite._KILL_VERIFY_SECONDS == 15.0
    assert run_suite._PYSPY_TIMEOUT == 60.0
    assert inspect.signature(run_suite.supervise).parameters["poll_seconds"].default == 5.0
    assert inspect.signature(run_suite.run_job).parameters["poll_seconds"].default == 5.0
    assert inspect.signature(run_suite.collect_probe).parameters["timeout"].default == 600.0


def test_charz_collect_probe_runs_supervised_beside_the_job(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    """(e) probe: stall == ceiling == the job's stall, its own .collect.* log and heartbeat, the job's evidence dir."""
    real_supervise = run_suite.supervise
    calls: list[dict] = []

    def spy(cmd, **kw):
        calls.append(kw)
        return real_supervise(cmd, **kw)

    monkeypatch.setattr(run_suite, "supervise", spy)
    factory = Factory(fake_script, "rc5", probe_mode="collect_zero")
    result = _run(factory, tmp_path, stall_seconds=7.0, file_ceiling=SLOW_CEILING)
    assert result.status == "RC5_OK"
    out = tmp_path / "out"
    job, probe = calls
    assert (job["stall_seconds"], job["file_ceiling"], job["poll_seconds"]) == (7.0, SLOW_CEILING, POLL)
    assert (job["log"], job["heartbeat"], job["evidence_dir"]) == (out / "job.log", out / "job.heartbeat", out / "evidence")
    assert probe["stall_seconds"] == probe["file_ceiling"] == 7.0  # collect_probe(timeout=stall_seconds)
    assert probe["poll_seconds"] == 0.2  # may move: hard-coded in collect_probe
    assert probe["log"] == out / "job.collect.log" and probe["log"].exists()
    assert probe["heartbeat"] == out / "job.collect.heartbeat"
    assert probe["env"][HEARTBEAT_ENV] == str(out / "job.collect.heartbeat")
    assert probe["evidence_dir"] == out / "evidence"


def test_charz_a_beating_probe_dies_at_the_jobs_stall_with_evidence_beside_the_job(
    fake_script: Path, tmp_path: Path, monkeypatch
) -> None:
    """(e) the probe's ceiling is the job's stall (1 s), not the job's ceiling (120 s); evidence lands in out/evidence."""
    monkeypatch.setattr(run_suite.shutil, "which", lambda *a, **k: None)  # fast: py-spy is pinned in its own test
    factory = Factory(fake_script, "rc5", probe_mode="chatty")
    t0 = time.monotonic()
    result = _run(factory, tmp_path, stall_seconds=STALL, file_ceiling=SLOW_CEILING)
    assert time.monotonic() - t0 < 30
    out = tmp_path / "out"
    assert (out / "job.collect.log").exists()
    assert (out / "evidence" / "job.collect.heartbeat").exists()
    # chatty keeps beating, so only the ceiling can fire (header text may move)
    assert "ceiling" in (out / "evidence" / "job.collect.tail.log").read_text(encoding="utf-8")
    # May move (owner allowed labels / evidence): a killed probe is FAIL today and its evidence is not on the result.
    assert result.status == "FAIL" and "probe" in result.note.lower()
    assert result.evidence == []


def test_charz_run_job_drops_a_stale_junit_first(fake_script: Path, tmp_path: Path) -> None:
    """A junit left by an earlier run in the same out dir must not turn an in-flight exit into a plain FAIL."""
    out = tmp_path / "out"
    out.mkdir()
    _write_junit(out / "job.xml", passed=5)
    factory = Factory(fake_script, "exit_in_flight", rerun_mode="ok")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.status == "HUNG" and result.culprit == SECOND  # kept stale junit -> FAIL, no culprit
    assert result.junit is None and not (out / "job.xml").exists()


def test_charz_run_job_drops_a_stale_heartbeat_first(fake_script: Path, tmp_path: Path) -> None:
    """A heartbeat left by an earlier run must not lend its unfinished start to this run's verdict."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "job.heartbeat").write_text(json.dumps(_ev("stale.py::t", "start", 1.0)) + "\n", encoding="utf-8")
    factory = Factory(fake_script, "rc2")
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING)
    assert result.culprit is None and result.rerun is None  # kept stale start -> CRASH in stale.py::t + a rerun
    assert result.status == "COLLECT_ERROR"
    assert read_heartbeat(result.heartbeat) == []


def test_charz_probe_child_env_is_the_jobs_clean_env_with_its_own_heartbeat(
    fake_script: Path, tmp_path: Path, monkeypatch
) -> None:
    """The probe gets run_job's cleaned base_env (not os.environ), QT offscreen by default, and its own heartbeat."""
    monkeypatch.delenv("RUN_SUITE_TEST_KEEP_ME", raising=False)
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    envfile = tmp_path / "env.json"
    factory = Factory(fake_script, "rc5", probe_mode="collect_zero", envfile=envfile)
    base = {**os.environ, "RUN_SUITE_TEST_KEEP_ME": "from-base", "PYTEST_ADDOPTS": "-x"}
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING, base_env=base)
    assert result.status == "RC5_OK"
    seen = json.loads(envfile.read_text())  # last writer wins: the probe runs after the job, so this is its env
    assert seen["KEEP_ME"] == "from-base" and seen["PYTEST_ADDOPTS"] is None
    assert seen["QT_QPA_PLATFORM"] == "offscreen"
    assert Path(seen["HEARTBEAT"]) == tmp_path / "out" / "job.collect.heartbeat"


def test_charz_rerun_child_env_keeps_the_base_env_and_a_callers_qt_platform(
    fake_script: Path, tmp_path: Path, monkeypatch
) -> None:
    """The rerun gets the same base_env (--cov's COVERAGE_FILE rides it), QT_QPA_PLATFORM is setdefault, own heartbeat."""
    monkeypatch.delenv("RUN_SUITE_TEST_KEEP_ME", raising=False)
    envfile = tmp_path / "env.json"
    factory = Factory(fake_script, "exit_in_flight", rerun_mode="ok", envfile=envfile)
    base = {**os.environ, "RUN_SUITE_TEST_KEEP_ME": "from-base", "QT_QPA_PLATFORM": "minimal"}
    result = _run(factory, tmp_path, stall_seconds=SLOW_STALL, file_ceiling=SLOW_CEILING, base_env=base)
    assert result.rerun is not None and result.rerun.status == "OK"
    seen = json.loads(envfile.read_text())  # last writer wins: the rerun is the last child
    assert seen["KEEP_ME"] == "from-base"
    assert seen["QT_QPA_PLATFORM"] == "minimal"
    assert Path(seen["HEARTBEAT"]) == tmp_path / "out" / "job-rerun.heartbeat"


def test_charz_hung_job_evidence_sits_in_out_evidence_and_ci_uploads_it(hung_job) -> None:
    """Evidence goes to <out>/evidence; every file the runner keeps for a hang matches a CI upload glob."""
    import fnmatch

    result, _, tmp = hung_job()
    assert result.evidence and all(p.parent == tmp / "out" / "evidence" for p in result.evidence)
    assert {"job.heartbeat", "job.tail.log"} <= {p.name for p in result.evidence}  # names may move
    step = _step_text(_ci_text(), "Upload supervisor evidence")
    patterns = [ln.strip().rsplit("/", 1)[-1] for ln in step.splitlines() if ln.strip().startswith(".run_suite/")]
    assert patterns, "the evidence upload step lists no .run_suite/ globs"
    for path in [result.log, result.heartbeat, *result.evidence]:
        assert any(fnmatch.fnmatch(path.name, pat) for pat in patterns), f"CI would not upload {path.name}"


def test_charz_default_out_dir_is_under_dot_run_suite(main_env, monkeypatch) -> None:
    """CI passes no --out and uploads .run_suite/**, so the default out dir must stay under <repo>/.run_suite/."""
    seen: list[Path] = []
    inner = _fake_job_runner(main_env["jobs"])

    def fake(spec, out_dir, **kw):
        seen.append(out_dir)
        return inner(spec, out_dir, **kw)

    monkeypatch.setattr(run_suite, "run_job", fake)
    assert run_suite.main(["--files", str(main_env["qt"]), str(main_env["pure"])]) == 0
    assert seen and all(p.parent == (main_env["root"] / ".run_suite").resolve() for p in seen)


def test_charz_main_joins_the_pure_worker_before_it_reraises(main_env, monkeypatch) -> None:
    """The main thread's exception waits for the pure job's teardown (its kill) before it leaves _run_jobs."""
    import threading

    pure_started, pure_done = threading.Event(), threading.Event()

    def fake(spec, out_dir, **kw):
        if spec.lane == "pure":
            pure_started.set()
            kw["cancel"].wait(timeout=10)
            time.sleep(0.3)  # still killing its tree when the main thread starts to unwind
            pure_done.set()
            raise run_suite.JobCancelled(spec.name)
        pure_started.wait(timeout=10)
        raise KeyboardInterrupt

    monkeypatch.setattr(run_suite, "run_job", fake)
    argv = ["--parallel-lanes", "--files", str(main_env["qt"]), str(main_env["pure"]), "--out", str(main_env["out"])]
    with pytest.raises(KeyboardInterrupt):
        run_suite.main(argv)
    assert pure_done.is_set(), "main re-raised while the pure lane was still tearing down its child"


# --------------------------------------------------------------------------- _supervised_pytest (refactor step S1)


def test_collect_probe_child_gets_the_same_clean_env_as_the_run_child(
    fake_script: Path, tmp_path: Path, monkeypatch
) -> None:
    """A direct collect_probe call gets run_job's child env: blocklist stripped, QT offscreen by default."""
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    envfile = tmp_path / "env.json"
    factory = Factory(fake_script, "unused", probe_mode="collect_zero", envfile=envfile)
    env = {
        **os.environ,
        "PYTEST_ADDOPTS": "-x",
        "PYTEST_PLUGINS": "evil",
        "PYTEST_CURRENT_TEST": "leftover",
        "RUN_SUITE_TEST_KEEP_ME": "yes",
    }
    env.pop("QT_QPA_PLATFORM", None)
    n = run_suite.collect_probe(
        _spec(),
        python=sys.executable,
        cwd=tmp_path,
        env=env,
        log=tmp_path / "probe.log",
        command_factory=factory,
        timeout=SLOW_STALL,
    )
    assert n == 0
    seen = json.loads(envfile.read_text())
    assert seen["PYTEST_ADDOPTS"] is None and seen["PYTEST_PLUGINS"] is None and seen["PYTEST_CURRENT_TEST"] is None
    assert seen["QT_QPA_PLATFORM"] == "offscreen"
    assert seen["KEEP_ME"] == "yes"
    assert Path(seen["HEARTBEAT"]) == tmp_path / "probe.heartbeat"
    assert env["PYTEST_ADDOPTS"] == "-x"  # the caller's mapping is never mutated


@pytest.mark.parametrize(
    "kind, stem, mode",
    [("run", "job", "rc2"), ("probe", "job.collect", "collect_zero")],
)
def test_supervised_pytest_clears_stale_junit_and_heartbeat_for_both_kinds(
    fake_script: Path, tmp_path: Path, kind: str, stem: str, mode: str
) -> None:
    """Both kinds drop a junit and a heartbeat left in the out dir before the child starts."""
    (tmp_path / f"{stem}.xml").write_text("<stale/>", encoding="utf-8")
    (tmp_path / f"{stem}.heartbeat").write_text("stale", encoding="utf-8")
    factory = Factory(fake_script, mode, probe_mode=mode)  # neither mode writes a junit or a beat
    ex, paths = run_suite._supervised_pytest(
        _spec(),
        kind,
        out_dir=tmp_path,
        timing=run_suite.SuiteTiming(SLOW_STALL, SLOW_CEILING, POLL),
        command_factory=factory,
    )
    assert not ex.killed
    assert (paths.log, paths.junit, paths.heartbeat) == (
        tmp_path / f"{stem}.log",
        tmp_path / f"{stem}.xml",
        tmp_path / f"{stem}.heartbeat",
    )
    assert paths.evidence_dir == tmp_path / "evidence"
    assert not paths.junit.exists() and not paths.heartbeat.exists()
    (call,) = factory.calls
    assert call["probe"] is (kind == "probe")


def test_collect_probe_clears_the_stale_junit_and_heartbeat_beside_its_log(fake_script: Path, tmp_path: Path) -> None:
    """collect_probe names its files from *log* (production never uses the default stem) and drops stale ones."""
    stale_xml, stale_beat = tmp_path / "probe.xml", tmp_path / "probe.heartbeat"
    stale_xml.write_text("<stale/>", encoding="utf-8")
    stale_beat.write_text("stale", encoding="utf-8")
    n = run_suite.collect_probe(
        _spec(),
        python=sys.executable,
        cwd=tmp_path,
        env=dict(os.environ),
        log=tmp_path / "probe.log",
        command_factory=Factory(fake_script, "unused", probe_mode="collect_zero"),  # writes no junit, no beat
        timeout=SLOW_STALL,
    )
    assert n == 0
    assert not stale_xml.exists() and not stale_beat.exists()


def test_supervised_pytest_rejects_an_unknown_kind(fake_script: Path, tmp_path: Path) -> None:
    """A bad kind raises ValueError before the factory runs or any file is touched."""
    factory = Factory(fake_script, "ok")
    with pytest.raises(ValueError, match="unknown child kind"):
        run_suite._supervised_pytest(
            _spec(),
            "bogus",
            out_dir=tmp_path / "out",
            timing=run_suite.SuiteTiming(SLOW_STALL, SLOW_CEILING, POLL),
            command_factory=factory,
        )
    assert factory.calls == []
    assert not (tmp_path / "out").exists()


# --------------------------------------------------------------------------- one timing resolution (refactor step S2)


def test_timing_defaults_come_from_three_module_constants() -> None:
    """argparse, supervise, run_job, collect_probe and SuiteTiming share DEFAULT_*; none has its own literal."""
    import inspect

    assert (run_suite.DEFAULT_STALL_SECONDS, run_suite.DEFAULT_FILE_CEILING, run_suite.DEFAULT_POLL_SECONDS) == (
        600.0,
        3600.0,
        5.0,
    )
    args = run_suite._parse_args([])
    assert args.stall_seconds == run_suite.DEFAULT_STALL_SECONDS
    assert args.file_ceiling == run_suite.DEFAULT_FILE_CEILING
    for fn in (run_suite.supervise, run_suite.run_job):
        assert inspect.signature(fn).parameters["poll_seconds"].default == run_suite.DEFAULT_POLL_SECONDS
    assert inspect.signature(run_suite.collect_probe).parameters["timeout"].default == run_suite.DEFAULT_STALL_SECONDS
    assert run_suite.SuiteTiming() == run_suite.SuiteTiming(
        run_suite.DEFAULT_STALL_SECONDS, run_suite.DEFAULT_FILE_CEILING, run_suite.DEFAULT_POLL_SECONDS
    )


def test_default_timing_orders_the_two_hang_layers() -> None:
    """faulthandler 540 + one poll <= stall 600 < CI ceiling 2400 <= default ceiling 3600; CI lifts no stall."""
    import re

    default = run_suite.SuiteTiming.from_args(run_suite._parse_args([]))
    assert default == run_suite.SuiteTiming()
    assert _pytest_ini_value("faulthandler_exit_on_timeout") == "true"
    faulthandler_timeout = float(_pytest_ini_value("faulthandler_timeout"))

    ci_text = _ci_text()
    step = _step_text(ci_text, "Run functional suite")
    (run_line,) = [ln for ln in step.splitlines() if ln.strip().startswith("run:") and "scripts/run_suite.py" in ln]
    assert "--stall-seconds" not in run_line, "CI must keep the default stall; the order below is pinned on it"
    cov_values = re.findall(r"(?m)^\s*cov_args:\s*(.*)$", ci_text)
    assert cov_values, "ci.yml matrix has no cov_args to check"
    assert all("--stall-seconds" not in value for value in cov_values), "a matrix cov_args lifts the stall"
    ci_ceiling = _ci_suite_flag("--file-ceiling")
    assert ci_ceiling is not None
    assert faulthandler_timeout + default.poll_seconds <= default.stall_seconds < float(ci_ceiling)
    assert float(ci_ceiling) <= default.file_ceiling


def test_main_hands_every_job_the_resolved_timing(main_env) -> None:
    """main resolves the timing once; every job gets stall, ceiling and poll as run_job's flat kwargs."""
    argv = [
        "--stall-seconds", "12",
        "--file-ceiling", "34",
        "--files", str(main_env["qt"]), str(main_env["pure"]),
        "--out", str(main_env["out"]),
    ]  # fmt: skip
    assert run_suite.main(argv) == 0
    assert len(main_env["jobs"]) == 2
    for _spec, kw in main_env["jobs"]:
        assert (kw["stall_seconds"], kw["file_ceiling"], kw["poll_seconds"]) == (12, 34, run_suite.DEFAULT_POLL_SECONDS)


def test_suite_timing_from_args_reads_only_stall_and_ceiling() -> None:
    args = run_suite._parse_args(["--stall-seconds", "7", "--file-ceiling", "9"])
    assert run_suite.SuiteTiming.from_args(args) == run_suite.SuiteTiming(7.0, 9.0, run_suite.DEFAULT_POLL_SECONDS)


# --------------------------------------------------------------------------- probe cancellable (refactor step S3)


def _cancel_when_exists(path: Path, event, timeout: float = 20.0):
    """Daemon waiter: set *event* once *path* exists, or after *timeout* anyway.

    Returns ``(thread, stamp)``; ``stamp["set_at"]`` is the monotonic time just before ``event.set()``
    ran, so a test measures how fast the cancel took effect, not how long interpreter start-up took.
    """
    import threading

    stamp: dict[str, float] = {}

    def watch() -> None:
        deadline = time.monotonic() + timeout
        while not event.is_set() and not path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        stamp["set_at"] = time.monotonic()
        event.set()

    thread = threading.Thread(target=watch, name="s3-cancel-when-exists", daemon=True)
    thread.start()
    return thread, stamp


def test_collect_probe_cancel_kills_the_probe_tree_and_raises(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    """A direct collect_probe whose cancel is set mid-flight kills the probe's tree and raises JobCancelled.

    Never returns -1: -1 means "the probe ran and its count is unknown".  Covers a live probe root with a
    reachable grandchild only (same group on POSIX, ppid walk on Windows).
    """
    import threading

    monkeypatch.setattr(run_suite.shutil, "which", lambda *a, **k: None)  # no py-spy dump on the way down
    pidfile = tmp_path / "pids.json"
    factory = Factory(fake_script, "unused", probe_mode="hang_with_grandchild", pidfile=pidfile)
    cancel = threading.Event()
    watcher, stamp = _cancel_when_exists(pidfile, cancel)  # only the probe writes the pid file
    try:
        with pytest.raises(run_suite.JobCancelled):
            run_suite.collect_probe(
                _spec(),
                python=sys.executable,
                cwd=tmp_path,
                env=dict(os.environ),
                log=tmp_path / "probe.log",
                command_factory=factory,
                timeout=30.0,  # bounded: a dropped cancel ends at 30 s, not 600 s
                cancel=cancel,
            )
        ended = time.monotonic()
        assert pidfile.exists(), "the probe never spawned its grandchild before the cancel"
        assert ended - stamp["set_at"] < 5.0, "the probe ran on after the cancel was set"
        assert len(factory.probes) == 1
        _assert_tree_gone(pidfile)
    finally:
        cancel.set()
        watcher.join(timeout=5)
        _reap(pidfile)


def test_run_job_cancel_during_the_rc5_probe_raises_job_cancelled(
    fake_script: Path, tmp_path: Path, monkeypatch
) -> None:
    """run_job hands its cancel to the rc-5 probe: cancel mid-probe raises JobCancelled, not a FAIL result."""
    monkeypatch.setattr(run_suite.shutil, "which", lambda *a, **k: None)
    pidfile = tmp_path / "pids.json"
    factory = Factory(fake_script, "rc5", probe_mode="hang_with_grandchild", pidfile=pidfile)
    import threading

    cancel = threading.Event()
    watcher, stamp = _cancel_when_exists(pidfile, cancel)
    try:
        with pytest.raises(run_suite.JobCancelled):
            _run(factory, tmp_path, stall_seconds=10.0, file_ceiling=SLOW_CEILING, cancel=cancel)
        ended = time.monotonic()
        assert pidfile.exists(), "the probe never spawned its grandchild before the cancel"
        assert ended - stamp["set_at"] < 5.0, "the probe ended at its own timeout, not at the cancel"
        assert len(factory.probes) == 1
        _assert_tree_gone(pidfile)
    finally:
        cancel.set()
        watcher.join(timeout=5)
        _reap(pidfile)


def test_run_job_with_cancel_already_set_spawns_nothing(fake_script: Path, tmp_path: Path) -> None:
    """A torn-down run starts no child: JobCancelled before the factory is called, and no file is written."""
    import threading

    factory = Factory(fake_script, "ok")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(run_suite.JobCancelled):
        _run(factory, tmp_path, cancel=cancel)
    assert factory.calls == []
    assert list((tmp_path / "out").iterdir()) == []


# ---- red until step S3 (2026-11-03): the collect-only probe ignores cancel


def test_red_cancel_ends_a_collect_probe_in_flight(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    # Discriminator: without the cancel plumbing the probe runs to its own 6 s timeout and nothing raises.
    # The bound starts at cancel.set(): the window before it holds several venv interpreter starts.
    import threading

    monkeypatch.setattr(run_suite.shutil, "which", lambda *a, **k: None)  # today's ceiling kill stays fast
    pidfile = tmp_path / "pids.json"
    factory = Factory(fake_script, "rc5", probe_mode="hang_with_grandchild", pidfile=pidfile)
    cancel = threading.Event()
    watcher, stamp = _cancel_when_exists(pidfile, cancel)  # only the probe writes the pid file
    try:
        with pytest.raises(run_suite.JobCancelled):
            _run(factory, tmp_path, stall_seconds=6.0, file_ceiling=SLOW_CEILING, cancel=cancel)
        assert time.monotonic() - stamp["set_at"] < 5.0, "the probe ended at its own 6 s timeout, not at the cancel"
        assert len(factory.probes) == 1 and pidfile.exists()
        _assert_tree_gone(pidfile)
    finally:
        cancel.set()
        watcher.join(timeout=5)
        _reap(pidfile)


# ---- ProcessTree part A (refactor step S4, 2026-11-03): start, enumerate, dump, close ----


def test_process_tree_is_chosen_once_at_import() -> None:
    """One instance, picked from sys.platform when the module loads; two kinds only."""
    if sys.platform == "win32":
        assert type(run_suite._TREE) is run_suite._WindowsTree
        assert run_suite._TREE.kind == "windows"
    else:
        assert type(run_suite._TREE) is run_suite._PosixTree
        assert run_suite._TREE.kind == "posix"
    assert isinstance(run_suite._TREE, run_suite._ProcessTree)


def test_popen_kwargs_by_tree_kind() -> None:
    """Both kinds are instantiated directly, so the POSIX branch is tested on Windows too (and vice versa)."""
    assert run_suite._WindowsTree().popen_kwargs() == {"creationflags": 0x00000004}  # CREATE_SUSPENDED
    assert run_suite._PosixTree().popen_kwargs() == {"start_new_session": True}


def test_pyspy_targets_by_tree_kind() -> None:
    """Windows dumps the root and its python members only; POSIX dumps every member."""
    members = [
        run_suite._TreeMember(11, "python.exe"),
        run_suite._TreeMember(12, "conhost.exe"),
        run_suite._TreeMember(13, "Python3.10"),
    ]
    assert run_suite._WindowsTree().pyspy_targets(10, members) == [10, 11, 13]
    assert run_suite._PosixTree().pyspy_targets(10, members) == [10, 11, 12, 13]
    assert run_suite._PosixTree().pyspy_targets(10, []) == [10]


# ---- ProcessTree part B (refactor step S5, 2026-11-03): the kill moves into the tree ----


def test_platform_is_read_only_at_import_time() -> None:
    """No function or method body of run_suite.py reads sys.platform: the kind is picked once, at import."""
    import ast

    tree = ast.parse(Path(run_suite.__file__).read_text(encoding="utf-8"))
    reads: list[int] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "platform"
                and isinstance(node.value, ast.Name)
                and node.value.id == "sys"
            ):
                reads.append(node.lineno)
    assert sorted(set(reads)) == [], f"sys.platform is read inside a function body at line(s) {sorted(set(reads))}"


class _FakeKillProc:
    """Just enough Popen for _ProcessTree.kill; every call lands in *events*."""

    pid = 4242

    def __init__(self, events: list[str], *, alive_after_kill: bool = False) -> None:
        self.events = events
        self.alive_after_kill = alive_after_kill
        self.killed = False

    def kill(self) -> None:
        self.events.append("proc.kill")
        self.killed = True

    def wait(self, timeout=None) -> int:
        self.events.append("proc.wait")
        if self.alive_after_kill:
            raise run_suite.subprocess.TimeoutExpired("fake", timeout)
        return 0

    def poll(self):
        self.events.append("root.poll")
        return None if (self.alive_after_kill or not self.killed) else 0


class _RecordingTree(run_suite._ProcessTree):
    """Records which template step runs when; the late member is the one it adds."""

    kind = "recording"

    def __init__(self, events: list[str], *, verify_survivors: list[int] | None = None, signal_error=None) -> None:
        self.events = events
        self.verify_survivors = verify_survivors or []
        self.signal_error = signal_error
        self.seen: dict[str, list] = {}
        self.deadline: float | None = None

    def _add_late_members(self, proc, targets) -> None:
        self.events.append("late_members")
        targets.append(run_suite._TreeMember(99, "late"))

    def _signal(self, proc, targets) -> None:
        self.events.append("signal")
        self.seen["signal"] = [m.pid for m in targets]
        if self.signal_error is not None:
            raise self.signal_error

    def _verify(self, proc, targets, deadline) -> list[int]:
        self.events.append("verify")
        self.seen["verify"] = [m.pid for m in targets]
        self.deadline = deadline
        return list(self.verify_survivors)

    def close(self, members) -> None:
        self.events.append("close")
        self.seen["close"] = [m.pid for m in members]


def test_tree_kill_runs_its_steps_in_the_documented_order() -> None:
    """late members, signal, proc.kill, proc.wait, root poll, verify, close; the same order on both kinds."""
    events: list[str] = []
    tree = _RecordingTree(events)
    proc = _FakeKillProc(events)
    before = time.monotonic()
    survivors = tree.kill(proc, [run_suite._TreeMember(7, "known")])
    assert events == ["late_members", "signal", "proc.kill", "proc.wait", "root.poll", "verify", "close"]
    assert survivors == []
    # the caller's member and the late one are both signalled, verified and closed
    assert tree.seen["signal"] == tree.seen["verify"] == tree.seen["close"] == [7, 99]
    assert tree.deadline is not None and tree.deadline >= before


def test_tree_kill_lists_the_root_first_then_the_verify_survivors() -> None:
    events: list[str] = []
    tree = _RecordingTree(events, verify_survivors=[55, -4242])
    proc = _FakeKillProc(events, alive_after_kill=True)
    assert tree.kill(proc, []) == [4242, 55, -4242]
    assert events[-1] == "close"


def test_tree_kill_closes_the_members_even_when_signalling_raises() -> None:
    events: list[str] = []
    tree = _RecordingTree(events, signal_error=KeyboardInterrupt())
    proc = _FakeKillProc(events)
    with pytest.raises(KeyboardInterrupt):
        tree.kill(proc, [run_suite._TreeMember(7, "known")])
    assert events == ["late_members", "signal", "close"]
    assert tree.seen["close"] == [7, 99]


def test_kill_tree_is_a_one_line_delegate_to_the_tree(monkeypatch) -> None:
    """supervise() and the spies call the module name _kill_tree; it forwards (proc, members) to _TREE.kill."""
    seen: list = []
    sentinel = [123]

    class _Tree:
        def kill(self, proc, members):
            seen.append((proc, members))
            return sentinel

    monkeypatch.setattr(run_suite, "_TREE", _Tree())
    proc, members = object(), [run_suite._TreeMember(1, "x")]
    assert run_suite._kill_tree(proc, members) is sentinel
    assert seen == [(proc, members)]


# ---- duplicate-handle fix, survivors on the except path, guarded start (refactor step S6, 2026-11-03) ----


def _count_k32_handles(monkeypatch, kinds: list[str] | None = None) -> dict[int, int]:
    """Windows: a live open-count per handle value for everything run_suite opens through _k32.

    OpenProcess, CreateToolhelp32Snapshot, CreateJobObjectW and OpenThread returns count +1, CloseHandle -1; a
    close of a value the wrappers never saw open is ignored.  Handle values are reused, so a test asserts every
    counter is 0 at the end, never "each opened value was closed once".  Each wrapper calls the saved original
    FuncPtr (it holds argtypes and restype).  *kinds*, when given, records the kind of every handle opened
    ("process", "process_snapshot", "thread_snapshot", "job", "thread").  POSIX has no handles: the dict stays empty.
    """
    live: dict[int, int] = {}
    if sys.platform != "win32":
        return live
    k32 = run_suite._k32
    real_open, real_snapshot, real_close = k32.OpenProcess, k32.CreateToolhelp32Snapshot, k32.CloseHandle
    real_job, real_thread = k32.CreateJobObjectW, k32.OpenThread

    def opened(handle, kind):
        if handle and handle != run_suite._INVALID_HANDLE:
            live[handle] = live.get(handle, 0) + 1
            if kinds is not None:
                kinds.append(kind)
        return handle

    def open_process(*args):
        return opened(real_open(*args), "process")

    def snapshot(*args):
        return opened(real_snapshot(*args), "thread_snapshot" if args[0] & 0x4 else "process_snapshot")

    def create_job(*args):
        return opened(real_job(*args), "job")

    def open_thread(*args):
        return opened(real_thread(*args), "thread")

    def close_handle(handle):
        if handle in live:
            live[handle] -= 1
        return real_close(handle)

    monkeypatch.setattr(k32, "OpenProcess", open_process)
    monkeypatch.setattr(k32, "CreateToolhelp32Snapshot", snapshot)
    monkeypatch.setattr(k32, "CreateJobObjectW", create_job)
    monkeypatch.setattr(k32, "OpenThread", open_thread)
    monkeypatch.setattr(k32, "CloseHandle", close_handle)
    return live


def test_k32_counting_wrappers_restore_the_original_funcptrs(monkeypatch) -> None:
    """The wrappers above are installed with monkeypatch on the WinDLL instance: undone, the cached FuncPtrs are back."""
    if sys.platform != "win32":
        assert not hasattr(run_suite, "_k32")
        return
    names = ("OpenProcess", "CreateToolhelp32Snapshot", "CreateJobObjectW", "OpenThread", "CloseHandle")
    originals = {name: getattr(run_suite._k32, name) for name in names}
    argtypes = {name: originals[name].argtypes for name in names}
    with monkeypatch.context() as inner:
        _count_k32_handles(inner)
        assert all(getattr(run_suite._k32, name) is not originals[name] for name in names)
    for name in names:
        assert getattr(run_suite._k32, name) is originals[name]
        assert getattr(run_suite._k32, name).argtypes == argtypes[name]


def test_tree_kill_leaves_no_open_handle(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    """Windows: after a kill every handle the supervisor opened (snapshot, root, members, fresh ones) is closed.

    The fresh enumeration right before the kill opens a handle per live member; the ones whose pid the caller
    already pinned used to be dropped unclosed.  POSIX pins no handle: no member carries one.
    """
    pidfile = tmp_path / "pids.json"
    proc = None
    members: list = []
    live = _count_k32_handles(monkeypatch)
    try:
        proc = _spawn_tree(fake_script, tmp_path, pidfile)
        assert pidfile.exists(), "the fake child never spawned its grandchild"
        members = run_suite._descendants(proc.pid)
        assert members, "the tree has descendants to pin"
        assert run_suite._kill_tree(proc, members) == []
        if sys.platform == "win32":
            assert live, "the counting wrappers saw no handle at all"
            leaked = {handle: count for handle, count in live.items() if count != 0}
            assert leaked == {}, f"_kill_tree left handle(s) open (value -> open count): {leaked}"
        else:
            assert all(m.handle is None for m in members)
        _assert_tree_gone(pidfile)
    finally:
        run_suite._close_members(members)
        _end(proc)
        _reap(pidfile)


def test_red_kill_tree_closes_the_handles_of_its_own_re_enumeration(
    fake_script: Path, tmp_path: Path, monkeypatch
) -> None:
    """Windows (finding F1): the kill's own fresh enumeration leaves none of its members' handles open.

    Ported from the characterization spec: the tree enumerates through the module function _win_descendants
    (not _descendants), so that is the seam this spy sits on.  Trivially green on POSIX (no enumeration, no handles).
    """
    pidfile = tmp_path / "pids.json"
    proc = None
    members: list = []
    opened: list = []
    real_enumerate = run_suite._win_descendants

    def spy(pid):
        found = real_enumerate(pid)
        opened.extend(found)
        return found

    try:
        proc = _spawn_tree(fake_script, tmp_path, pidfile)
        assert pidfile.exists(), "the fake child never spawned its grandchild"
        members = run_suite._descendants(proc.pid)
        monkeypatch.setattr(run_suite, "_win_descendants", spy)
        assert run_suite._kill_tree(proc, members) == []
        if sys.platform == "win32":
            assert opened, "Windows must re-enumerate the tree right before the kill"
        leaked = [m.pid for m in opened if m.handle is not None]
        assert leaked == [], f"_kill_tree left {len(leaked)} process handle(s) open: {leaked}"
    finally:
        run_suite._close_members(members + opened)
        _end(proc)
        _reap(pidfile)


class _LateTree(run_suite._WindowsTree):
    """_WindowsTree with a scripted fresh enumeration and a recording close that needs no kernel32."""

    def __init__(self, fresh, *, close_error=None) -> None:
        super().__init__()
        self.fresh = fresh
        self.close_error = close_error
        self.closed: list[int] = []

    def descendants(self, root_pid):
        return list(self.fresh)

    def close(self, members) -> None:
        if self.close_error is not None:
            raise self.close_error
        for member in members:
            if member.handle:
                self.closed.append(member.handle)
                member.handle = None


def test_windows_late_members_close_the_duplicate_of_an_already_pinned_pid() -> None:
    """A fresh member whose pid the caller already pins is closed; a genuinely new one stays pinned for the kill."""
    known = run_suite._TreeMember(5, "a", 2005)  # the caller's handle for pid 5
    dup, new = run_suite._TreeMember(5, "a", 1005), run_suite._TreeMember(6, "b", 1006)
    tree = _LateTree([dup, new])
    targets = [known]
    tree._add_late_members(types.SimpleNamespace(pid=77), targets)
    assert tree.closed == [1005], "the duplicate handle of an already-pinned pid must be closed"
    assert known.handle == 2005 and new.handle == 1006
    assert new in targets and known in targets


def test_windows_late_members_are_owned_by_targets_before_anything_can_interrupt() -> None:
    """A second Ctrl+C while the duplicates are closed must still leave every fresh handle in targets.

    The template's finally closes only targets, so a handle that is not yet in it at that moment leaks.
    """
    dup, new = run_suite._TreeMember(5, "a", 1005), run_suite._TreeMember(6, "b", 1006)
    tree = _LateTree([dup, new], close_error=KeyboardInterrupt())
    targets = [run_suite._TreeMember(5, "a", 2005)]
    with pytest.raises(KeyboardInterrupt):
        tree._add_late_members(types.SimpleNamespace(pid=77), targets)
    assert new in targets and dup in targets, "a fresh member escaped targets: the kill's finally would not close it"


def test_supervise_except_path_warns_about_survivors_of_the_kill(
    fake_script: Path, tmp_path: Path, monkeypatch, caplog
) -> None:
    """F2: the Ctrl+C / cancel handler reports what _kill_tree could not end, like the stall path does."""
    import logging
    import threading

    pidfile = tmp_path / "pids.json"
    real_kill = run_suite._kill_tree

    def kill_and_report(proc, members):
        real_kill(proc, members)  # really end the tree: no orphan is left behind
        return [123]

    monkeypatch.setattr(run_suite, "_kill_tree", kill_and_report)
    cancel = threading.Event()
    watcher, _stamp = _cancel_when_exists(pidfile, cancel)
    try:
        with caplog.at_level(logging.WARNING, logger=run_suite.logger.name):
            with pytest.raises(run_suite.JobCancelled):
                _supervise_tree(fake_script, tmp_path, pidfile, cancel=cancel)
        assert "not gone after the kill" in caplog.text
        assert "[123]" in caplog.text
        _assert_tree_gone(pidfile)
    finally:
        cancel.set()
        watcher.join(timeout=5)
        _reap(pidfile)


def test_supervise_kills_the_child_when_the_first_line_after_popen_raises(
    fake_script: Path, tmp_path: Path, monkeypatch
) -> None:
    """F3: nothing between Popen returning and the guarded block may leave the child running.

    time.monotonic raises once, on the main thread, right after the (wrapped) Popen returned: the first call
    supervise() makes there.  The child must be dead when the error reaches the caller.
    """
    import threading

    made: list = []
    state = {"armed": False}
    main_thread = threading.get_ident()
    real_popen = run_suite.subprocess.Popen
    real_monotonic = run_suite.time.monotonic

    def popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        made.append(proc)
        state["armed"] = True
        return proc

    def monotonic():
        if state["armed"] and threading.get_ident() == main_thread:
            state["armed"] = False
            raise RuntimeError("boom right after Popen")
        return real_monotonic()

    monkeypatch.setattr(run_suite.subprocess, "Popen", popen)
    monkeypatch.setattr(run_suite.time, "monotonic", monotonic)
    hb, log = tmp_path / "hb.jsonl", tmp_path / "child.log"
    try:
        with pytest.raises(RuntimeError, match="boom right after Popen"):
            run_suite.supervise(
                [sys.executable, str(fake_script), "hang_no_heartbeat"],
                cwd=tmp_path,
                env={**os.environ, HEARTBEAT_ENV: str(hb)},
                heartbeat=hb,
                log=log,
                stall_seconds=SLOW_STALL,
                file_ceiling=CANCEL_CEILING,
                poll_seconds=POLL,
            )
        assert len(made) == 1
        assert made[0].poll() is not None, "the child was left running after an error right after Popen"
    finally:
        monkeypatch.undo()
        for proc in made:
            if proc.poll() is None:
                run_suite._kill_tree(proc, run_suite._descendants(proc.pid))


# ---- Job Object kill path (plans/run-suite-job-object.md, 2026-11-03): orphan classes 1 and 3, the spawn race ----
# Red-light first: every test below failed before the job existed.  The real-process ones need the Windows job
# (POSIX reaches the process group; a descendant that leaves it, E5, is a TODO) and skip elsewhere.  Every
# grandchild they start is FAKE_CHILD's bounded "sleeper" (40 s), so an orphan of a red run ends by itself.

_NEEDS_JOB = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows Job Object path; POSIX reaches the process group (E5 is a TODO)"
)
_SPAWN_TRIALS = 10
_SPAWN_CAP = 200
_WALK_DELAY = 0.02


def _renamable(path: Path, timeout: float = 2.0) -> bool:
    """True once *path* can be renamed (it is renamed back): no live process still holds it open.

    Windows refuses to rename a file another process holds open (WinError 32).  A survivor holds the inherited
    log for its whole life, so the short retry only absorbs the kernel's handle teardown, never a survivor.
    """
    moved = path.with_name(path.name + ".moved")
    deadline = time.monotonic() + timeout
    while True:
        try:
            path.rename(moved)
        except PermissionError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
            continue
        moved.rename(path)
        return True


def _spawn_attached(fake_script: Path, tmp_path: Path, args: list[str], pidfile: Path):
    """_spawn_tree's shape started like supervise starts it: Popen(**_TREE.popen_kwargs()), then attach.

    Returns (proc, log) once the pid file exists or the root exited.
    """
    import subprocess

    log = tmp_path / "spawn.log"
    with open(log, "wb") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, str(fake_script), *args, "--pidfile", str(pidfile)],
            cwd=str(tmp_path),
            env={**os.environ, HEARTBEAT_ENV: str(tmp_path / "spawn_hb.jsonl")},
            stdin=subprocess.DEVNULL,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            **run_suite._TREE.popen_kwargs(),
        )
    try:
        run_suite._TREE.attach(proc)
    except BaseException:
        _end(proc)
        raise
    deadline = time.monotonic() + 20
    while not pidfile.exists() and proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    return proc, log


def _end_attached(proc) -> None:
    """Test-owned cleanup of a _spawn_attached root: closing its job ends whatever is left (KILL_ON_JOB_CLOSE)."""
    if proc is not None:
        run_suite._TREE.release(proc)
    _end(proc)


def _spy_popen(monkeypatch) -> list:
    """Every child supervise starts, in order (the S2/S3 drivers wait on the root's own Popen)."""
    real_popen = run_suite.subprocess.Popen
    made: list = []

    def spy(*args, **kwargs):
        made.append(real_popen(*args, **kwargs))
        return made[-1]

    monkeypatch.setattr(run_suite.subprocess, "Popen", spy)
    return made


def _leaked(live: dict[int, int]) -> dict[int, int]:
    return {handle: count for handle, count in live.items() if count != 0}


def _exit_leaving_grandchild_cmd(fake_script: Path, pidfile: Path, release: Path | None = None) -> list[str]:
    cmd = [sys.executable, str(fake_script), "exit_leaving_grandchild", "--pidfile", str(pidfile)]
    return cmd + (["--release", str(release)] if release is not None else [])


class _ReleaseRoot:
    """On its first call: wait for the tree, let the --release root exit, and wait until its Popen says so."""

    def __init__(self, pidfile: Path, release: Path, made: list) -> None:
        self.pidfile, self.release, self.made = pidfile, release, made
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        if self.calls > 1:
            return
        deadline = time.monotonic() + 20
        while not self.pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.release.write_text("go", encoding="utf-8")
        if self.made:
            self.made[0].wait(timeout=20)


class _HeartbeatThatReleases:
    """S2 driver: supervise's first os.stat of the heartbeat lets the root exit, so the exit lands between the
    wait and the stall check (a stall threshold below one poll makes that first check a stall)."""

    def __init__(self, path: Path, release_root: _ReleaseRoot) -> None:
        self.path, self.release_root = path, release_root

    def __fspath__(self) -> str:
        self.release_root()
        return str(self.path)

    def exists(self) -> bool:  # what the evidence pass would ask if the kill path ran instead
        return self.path.exists()


class _CancelThatReleases:
    """S3 driver: the first is_set() lets the root exit, then cancels, so the handler sees an exited root."""

    def __init__(self, release_root: _ReleaseRoot) -> None:
        self.release_root = release_root

    def is_set(self) -> bool:
        self.release_root()
        return True


class _CancelWhen:
    """cancel stand-in: set once *ready()* holds or *timeout* passed (supervise asks once per poll)."""

    def __init__(self, ready, timeout: float = 15.0) -> None:
        self.ready = ready
        self.deadline = time.monotonic() + timeout

    def is_set(self) -> bool:
        return self.ready() or time.monotonic() > self.deadline


def _job_facts(proc) -> tuple[bool, bool]:
    """(the job handle is inheritable, the root is in its job) for a root that attach put in a job."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    job = run_suite._TREE._job(proc)
    assert job, "attach put the child in no job"
    flags, inside = wintypes.DWORD(), wintypes.BOOL()
    assert kernel32.GetHandleInformation(job, ctypes.byref(flags))
    assert kernel32.IsProcessInJob(int(proc._handle), job, ctypes.byref(inside))
    return bool(flags.value & 0x1), bool(inside.value)  # HANDLE_FLAG_INHERIT


_SUPERVISOR = r'''
import json, os, sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from scripts import run_suite

tmp, cmd = Path(sys.argv[2]), json.loads(sys.argv[3])
hb = tmp / "hb.jsonl"
run_suite.supervise(
    cmd, cwd=tmp, env={**os.environ, run_suite.HEARTBEAT_ENV: str(hb)}, heartbeat=hb, log=tmp / "child.log",
    stall_seconds=60.0, file_ceiling=30.0, poll_seconds=0.1,
)
'''


def test_tree_kill_releases_the_job_after_closing_the_members() -> None:
    """The template's finally closes the pinned handles, then releases the job (Windows: the job handle last,
    so KILL_ON_JOB_CLOSE ends any straggler), also when signalling raised."""

    class _ReleasingTree(_RecordingTree):
        def release(self, proc) -> None:
            self.events.append("release")

    events: list[str] = []
    _ReleasingTree(events).kill(_FakeKillProc(events), [run_suite._TreeMember(7, "known")])
    assert events[-2:] == ["close", "release"]
    events.clear()
    with pytest.raises(KeyboardInterrupt):
        _ReleasingTree(events, signal_error=KeyboardInterrupt()).kill(_FakeKillProc(events), [])
    assert events == ["late_members", "signal", "close", "release"]


def test_attach_reap_release_by_tree_kind() -> None:
    """The base and POSIX attach, reap and release nothing; a Windows tree that holds no job for the pid reaps
    and releases nothing without touching kernel32, so every kind runs on every platform."""
    proc = types.SimpleNamespace(pid=4242)
    for tree in (run_suite._ProcessTree(), run_suite._PosixTree()):
        assert tree.attach(proc) is None
    for tree in (run_suite._ProcessTree(), run_suite._PosixTree(), run_suite._WindowsTree()):
        assert tree.reap(proc) == []
        assert tree.release(proc) is None


@_NEEDS_JOB
def test_windows_job_that_never_drains_is_reported_as_a_survivor(monkeypatch, caplog) -> None:
    """_verify and reap poll the job's ActiveProcesses up to the bound (terminating it again meanwhile); a job
    that still has members is reported as -pid, the marker POSIX uses for a group that still has members."""
    calls: list = []
    fake_job = 0x7FFFFFF0  # never reaches kernel32: every call that could see it is faked below

    def query(job, info_class, info, size, returned):
        calls.append(("query", job))
        info._obj.ActiveProcesses = 3  # info is ctypes.byref(<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>)
        return 1

    monkeypatch.setattr(run_suite._k32, "QueryInformationJobObject", query)
    monkeypatch.setattr(run_suite._k32, "TerminateJobObject", lambda job, code: calls.append(("terminate", job)) or 1)
    monkeypatch.setattr(run_suite._k32, "CloseHandle", lambda handle: calls.append(("close", handle)) or 1)
    monkeypatch.setattr(run_suite, "_KILL_VERIFY_SECONDS", 0.2)
    tree, proc = run_suite._WindowsTree(), types.SimpleNamespace(pid=4242)
    tree._jobs[proc.pid] = fake_job
    assert tree._verify(proc, [], time.monotonic() + 0.2) == [-4242]
    assert ("query", fake_job) in calls and ("terminate", fake_job) in calls
    assert ("close", fake_job) not in calls, "_verify must leave the job to release()"
    calls.clear()
    assert tree.reap(proc) == [-4242]
    assert "exited and left 3 process(es)" in caplog.text
    assert ("terminate", fake_job) in calls and calls.count(("close", fake_job)) == 1
    assert tree._job(proc) is None, "reap must release the job even when it did not drain"


@_NEEDS_JOB
def test_job_supervise_clean_exit_closes_the_job_and_reports_no_orphan(
    fake_script: Path, tmp_path: Path, monkeypatch, caplog
) -> None:
    """A child that leaves nothing behind: supervise still opened and closed its job, thread snapshot and thread
    handles, and logs no orphan (an exited root's own job count is already 0 when the wait returns)."""
    hb, log = tmp_path / "hb.jsonl", tmp_path / "child.log"
    kinds: list[str] = []
    live = _count_k32_handles(monkeypatch, kinds)
    ex = run_suite.supervise(
        [sys.executable, str(fake_script), "ok"],
        cwd=tmp_path,
        env={**os.environ, HEARTBEAT_ENV: str(hb)},
        heartbeat=hb,
        log=log,
        stall_seconds=SLOW_STALL,
        file_ceiling=CANCEL_CEILING,
        poll_seconds=POLL,
    )
    assert ex.returncode == 0 and ex.killed is False and ex.reason is None
    assert {"job", "thread_snapshot", "thread"} <= set(kinds), f"handles opened: {sorted(set(kinds))}"
    assert _leaked(live) == {}
    assert "exited and left" not in caplog.text and "not gone after the kill" not in caplog.text
    assert _renamable(log)


@_NEEDS_JOB
def test_job_supervise_normal_exit_reaps_the_orphan(fake_script: Path, tmp_path: Path, monkeypatch, caplog) -> None:
    """S1: the root exits 0 by itself while its grandchild lives; the job ends the grandchild before supervise
    returns, the log is free, the orphan is reported, and every handle opened on the way is closed."""
    pidfile, log, hb = tmp_path / "pids.json", tmp_path / "child.log", tmp_path / "hb.jsonl"
    kinds: list[str] = []
    live = _count_k32_handles(monkeypatch, kinds)
    try:
        ex = run_suite.supervise(
            _exit_leaving_grandchild_cmd(fake_script, pidfile),
            cwd=tmp_path,
            env={**os.environ, HEARTBEAT_ENV: str(hb)},
            heartbeat=hb,
            log=log,
            stall_seconds=SLOW_STALL,
            file_ceiling=CANCEL_CEILING,
            poll_seconds=POLL,
        )
        assert ex.returncode == 0 and ex.killed is False and ex.reason is None
        assert pidfile.exists(), "the root exited before it spawned its grandchild"
        _assert_tree_gone(pidfile)
        assert _renamable(log), "a survivor of the exited root still holds its log (WinError 32)"
        assert "exited and left" in caplog.text, "the orphan was ended without a word"
        assert {"job", "thread_snapshot", "thread"} <= set(kinds), f"handles opened: {sorted(set(kinds))}"
        assert _leaked(live) == {}
    finally:
        _reap(pidfile)


@_NEEDS_JOB
def test_job_supervise_stall_after_the_root_exited_reaps_the_orphan(
    fake_script: Path, tmp_path: Path, monkeypatch, caplog
) -> None:
    """S2: the root exits between the wait and the stall check; the result stays killed=False (it exited by
    itself), and its orphan is logged and ended before supervise returns."""
    pidfile, log, release = tmp_path / "pids.json", tmp_path / "child.log", tmp_path / "release"
    made = _spy_popen(monkeypatch)
    release_root = _ReleaseRoot(pidfile, release, made)
    try:
        ex = run_suite.supervise(
            _exit_leaving_grandchild_cmd(fake_script, pidfile, release),
            cwd=tmp_path,
            env={**os.environ, HEARTBEAT_ENV: str(tmp_path / "beats.jsonl")},
            heartbeat=_HeartbeatThatReleases(tmp_path / "never_written.jsonl", release_root),
            log=log,
            stall_seconds=POLL / 2,
            file_ceiling=CANCEL_CEILING,
            poll_seconds=POLL,
        )
        assert release_root.calls == 1
        assert ex.killed is False and ex.reason is None and ex.returncode == 0
        _assert_tree_gone(pidfile)
        assert _renamable(log), "a survivor of the exited root still holds its log (WinError 32)"
        assert "exited and left" in caplog.text, "S2 must log what the exited root left behind"
    finally:
        release.write_text("go", encoding="utf-8")
        _reap(pidfile)
        for proc in made:
            _end(proc)


@_NEEDS_JOB
def test_job_supervise_cancel_after_the_root_exited_reaps_the_orphan(
    fake_script: Path, tmp_path: Path, monkeypatch, caplog
) -> None:
    """S3: JobCancelled reaches the handler after the root exited by itself; the handler still ends its orphan."""
    pidfile, log, hb, release = tmp_path / "pids.json", tmp_path / "child.log", tmp_path / "hb.jsonl", tmp_path / "go"
    made = _spy_popen(monkeypatch)
    release_root = _ReleaseRoot(pidfile, release, made)
    try:
        with pytest.raises(run_suite.JobCancelled):
            run_suite.supervise(
                _exit_leaving_grandchild_cmd(fake_script, pidfile, release),
                cwd=tmp_path,
                env={**os.environ, HEARTBEAT_ENV: str(hb)},
                heartbeat=hb,
                log=log,
                stall_seconds=SLOW_STALL,
                file_ceiling=CANCEL_CEILING,
                poll_seconds=POLL,
                cancel=_CancelThatReleases(release_root),
            )
        assert release_root.calls == 1
        assert made and made[0].poll() is not None, "the root was still running when the handler ran"
        _assert_tree_gone(pidfile)
        assert _renamable(log), "a survivor of the exited root still holds its log (WinError 32)"
        assert "exited and left" in caplog.text
    finally:
        release.write_text("go", encoding="utf-8")
        _reap(pidfile)
        for proc in made:
            _end(proc)


@_NEEDS_JOB
def test_job_reap_ends_the_orphan_of_a_root_that_already_exited(fake_script: Path, tmp_path: Path) -> None:
    """Orphan class 1 at the tree: the root exited and its grandchild lives on, holding the log.  The job still
    holds the grandchild (a post-exit walk does not: a dead venv redirector is not in the Toolhelp table)."""
    pidfile = tmp_path / "pids.json"
    proc = None
    try:
        proc, log = _spawn_attached(fake_script, tmp_path, ["exit_leaving_grandchild"], pidfile)
        assert proc.wait(timeout=20) == 0
        assert pidfile.exists(), "the root exited before it spawned its grandchild"
        assert run_suite._TREE.reap(proc) == []
        _assert_tree_gone(pidfile)
        assert _renamable(log), "the orphan still holds the exited root's log (WinError 32)"
    finally:
        _end_attached(proc)
        _reap(pidfile)


@_NEEDS_JOB
def test_job_kill_ends_a_grandchild_behind_a_dead_intermediate(fake_script: Path, tmp_path: Path) -> None:
    """Orphan class 3: root alive -> intermediate (exited) -> grandchild.  The parent-pid walk cannot reach the
    grandchild (its parent pid names a dead process); the kill still ends it through the job."""
    pidfile = tmp_path / "pids.json"
    proc = None
    members: list = []
    try:
        proc, log = _spawn_attached(fake_script, tmp_path, ["hang_with_orphaned_grandchild"], pidfile)
        assert pidfile.exists(), "the root never reported its orphaned grandchild"
        pids = json.loads(pidfile.read_text())
        members = run_suite._descendants(proc.pid)
        orphan = {pids["grandchild"], pids["grandchild_real"]}
        assert orphan.isdisjoint(m.pid for m in members), "the walk reached the grandchild: this is not class 3"
        assert run_suite._kill_tree(proc, members) == []
        _assert_tree_gone(pidfile)
        assert _renamable(log), "the orphaned grandchild still holds the log (WinError 32)"
    finally:
        run_suite._close_members(members)
        _end_attached(proc)
        _reap(pidfile)


@_NEEDS_JOB
def test_job_leaves_no_survivor_of_the_spawn_race(fake_script: Path, tmp_path: Path, monkeypatch, caplog) -> None:
    """The root spawns a sleeper every ~1 ms while the cancel kill runs, _SPAWN_TRIALS times: no survivor.

    The walk reaches only what existed at its last enumeration: a child created after it (or while its parent's
    asynchronous TerminateProcess lands) survives.  That window is the duration of the late walk, about a
    millisecond on an idle machine (0 of 10 trials here), longer on a loaded runner (16 of 20 in report E3,
    where a busy pinner thread held the GIL); the seam below stretches every walk by _WALK_DELAY so the race
    fires in every trial.  Every process of the tree holds the inherited log, so a renamable log proves that
    none is left, reported or not, with no pid that Windows may have reused meanwhile.  The sleepers end by
    themselves after 5 s, so a red run cannot pile them up.  At least one trial must kill the spawner mid-loop.
    """
    real_walk = run_suite._win_descendants

    def loaded_walk(root_pid: int):
        found = real_walk(root_pid)
        time.sleep(_WALK_DELAY)  # the spawner keeps spawning between this snapshot and its TerminateProcess
        return found

    monkeypatch.setattr(run_suite, "_win_descendants", loaded_walk)
    trials: list[tuple[int, bool]] = []  # (sleepers launched before the kill, log renamable afterwards)
    for trial in range(_SPAWN_TRIALS):
        root = tmp_path / f"trial{trial}"
        spawndir = root / "spawn"
        spawndir.mkdir(parents=True)
        log, hb, launched_file = root / "child.log", root / "hb.jsonl", spawndir / "launched.txt"

        def eight_launched(launched_file: Path = launched_file) -> bool:
            return launched_file.exists() and launched_file.read_text(encoding="utf-8").count("\n") >= 8

        with pytest.raises(run_suite.JobCancelled):
            run_suite.supervise(
                [sys.executable, str(fake_script), "spawn_loop", "--pidfile", str(root / "pids.json"),
                 "--spawndir", str(spawndir), "--cap", str(_SPAWN_CAP), "--lifetime", "5"],
                cwd=root,
                env={**os.environ, HEARTBEAT_ENV: str(hb)},
                heartbeat=hb,
                log=log,
                stall_seconds=SLOW_STALL,
                file_ceiling=CANCEL_CEILING,
                poll_seconds=POLL,
                cancel=_CancelWhen(eight_launched),
            )  # fmt: skip
        launched = launched_file.read_text(encoding="utf-8").split() if launched_file.exists() else []
        trials.append((len(launched), _renamable(log)))
    assert [t for t, (_, free) in enumerate(trials) if not free] == [], f"(launched, log free) per trial: {trials}"
    assert "not gone after the kill" not in caplog.text
    assert any(0 < n < _SPAWN_CAP for n, _ in trials), f"no trial killed the spawner mid-loop: {trials}"


@_NEEDS_JOB
def test_job_assignment_failure_still_resumes_the_child_and_the_walk_kills_it(
    fake_script: Path, tmp_path: Path, monkeypatch, caplog
) -> None:
    """Design item 2's fallback: AssignProcessToJobObject fails -> a warning, the suspended child is resumed all
    the same (it runs and writes its pid file), and the cancel kill ends the live tree by the parent-pid walk."""
    import threading

    refused: list = []

    def refuse(job, process):
        refused.append((job, process))
        return 0

    kinds: list[str] = []
    live = _count_k32_handles(monkeypatch, kinds)
    monkeypatch.setattr(run_suite._k32, "AssignProcessToJobObject", refuse)
    pidfile = tmp_path / "pids.json"
    cancel = threading.Event()
    watcher = _set_when_exists(pidfile, cancel)
    try:
        with pytest.raises(run_suite.JobCancelled):
            _supervise_tree(fake_script, tmp_path, pidfile, cancel=cancel)
        assert len(refused) == 1, "supervise never tried to put its child in a job"
        assert pidfile.exists(), "the child never ran: its suspended primary thread was not resumed"
        _assert_tree_gone(pidfile)
        assert "could not put pid" in caplog.text
        assert "job" in kinds and _leaked(live) == {}, "the job of a failed assignment must be closed at once"
    finally:
        cancel.set()
        watcher.join(timeout=5)
        _reap(pidfile)


@_NEEDS_JOB
def test_job_kill_leaves_no_open_handle(fake_script: Path, tmp_path: Path, monkeypatch) -> None:
    """attach opens a job (non-inheritable, the root inside it), a thread snapshot, a thread handle and a process
    handle; attach plus the kill close every one of them (the live counter of test_tree_kill_leaves_no_open_handle)."""
    pidfile = tmp_path / "pids.json"
    kinds: list[str] = []
    live = _count_k32_handles(monkeypatch, kinds)
    proc = None
    members: list = []
    try:
        proc, _ = _spawn_attached(fake_script, tmp_path, ["hang_with_grandchild"], pidfile)
        assert pidfile.exists(), "the fake child never spawned its grandchild"
        assert _job_facts(proc) == (False, True), "(job handle inheritable, root in the job)"
        members = run_suite._descendants(proc.pid)
        assert run_suite._kill_tree(proc, members) == []
        assert {"job", "thread_snapshot", "thread", "process"} <= set(kinds), f"handles opened: {sorted(set(kinds))}"
        assert _leaked(live) == {}, f"attach + kill left handle(s) open (value -> open count): {_leaked(live)}"
        _assert_tree_gone(pidfile)
    finally:
        run_suite._close_members(members)
        _end_attached(proc)
        _reap(pidfile)


@_NEEDS_JOB
def test_job_hard_kill_of_the_supervisor_ends_the_whole_tree(fake_script: Path, tmp_path: Path) -> None:
    """The net no finally can give: the supervisor process itself is TerminateProcess'd mid-supervise.  Its
    handles close with it, the job's only handle among them, and KILL_ON_JOB_CLOSE ends the supervised tree."""
    import subprocess

    driver_py = tmp_path / "supervisor.py"
    driver_py.write_text(_SUPERVISOR, encoding="utf-8")
    pidfile = tmp_path / "pids.json"
    driver = subprocess.Popen(
        [sys.executable, str(driver_py), str(REPO_ROOT), str(tmp_path), json.dumps(_hang_tree_cmd(fake_script, pidfile))],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while not pidfile.exists() and driver.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pidfile.exists(), "the supervised child never spawned its grandchild"
        driver.kill()  # TerminateProcess: no except handler and no finally of supervise runs
        driver.wait(timeout=10)
        _assert_tree_gone(pidfile)
    finally:
        _end(driver)
        _reap(pidfile)
