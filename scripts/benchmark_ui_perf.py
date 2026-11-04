"""UI performance harness -- startup, open, zoom, F5 fit, scroll, tab switch.

Drives the real app in-process (``main.run(start_event_loop=False)`` + the
View's own user-facing entry points) under ``QT_QPA_PLATFORM=offscreen``, one
child interpreter per (file, run) so every run pays a cold start.  The parent
aggregates median and nearest-rank p90 per scenario and writes raw JSON to
``--out-dir`` (default: ``<TEMP>/pdf_editor_perf``; never inside the repo).

Scenarios (all wall clock, milliseconds):

* ``startup_wall``      parent spawn -> first window shown (includes interpreter start)
* ``startup_inproc``    child's first line -> first window shown
* ``open_first_paint``  ``view._queue_or_open_paths`` (cold: controller bootstrap
                        included) -> initial page quality ``low``
* ``open_high``         same start -> initial page quality ``high``
* ``zoom_sync``         ``view._zoom_relative`` call (signal -> ``change_scale``)
* ``zoom_settle``       same start -> every visible page quality ``high``
* ``f5_enter`` / ``f5_exit``  toggle fullscreen -> visible pages ``high``
                        (+ ``_rebuild_continuous_scene`` call counts)
* ``scroll_step_sync``  one scrollbar ``setValue`` (fast sweep, 40 steps)
* ``scroll_step_content`` same start -> every visible page at least ``low``
* ``tab_switch_low`` / ``tab_switch_high``  tab bar ``setCurrentIndex`` -> page ready

``--repo-root`` runs the children against another source tree (e.g. a
pre-change snapshot) so baseline and patched builds interleave in one session.
``--profile SCENARIO`` wraps that scenario in cProfile (main thread only) and
writes ``.prof`` + a text summary next to the JSON.

Run:  .venv\\Scripts\\python.exe scripts/benchmark_ui_perf.py --runs 5
"""
from __future__ import annotations

import time

_CHILD_T_START = time.time()

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import statistics  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILES = [
    "test_files/1.pdf",
    "test_files/mozilla-pdf/artofwar.pdf",
    "test_files/mozilla-pdf/bpl13210.pdf",
    "test_files/mozilla-pdf/22060_A1_01_Plans.pdf",
]
SECOND_TAB_FILE = "test_files/test-horizontal-texts.pdf"
ZOOM_FACTORS = (1.1, 1.2, 1.3, 0.75, 0.6)
SCROLL_STEPS = 40
TAB_ROUND_TRIPS = 3
WAIT_TIMEOUT_S = 30.0
SCENARIOS = (
    "startup_wall",
    "startup_inproc",
    "open_first_paint",
    "open_high",
    "zoom_sync",
    "zoom_settle",
    "f5_enter",
    "f5_exit",
    "scroll_step_sync",
    "scroll_step_content",
    "scroll_sweep_total",
    "tab_switch_sync",
    "tab_switch_low",
    "tab_switch_high",
    "bg_after_open",
    "bg_after_zoom",
    "bg_after_f5_enter",
    "bg_after_f5_exit",
    "bg_after_scroll",
    "bg_after_tab_switch",
)


# ---------------------------------------------------------------- statistics


def _summary(samples: list[float]) -> dict:
    ordered = sorted(s for s in samples if s is not None)
    n = len(ordered)
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "median_ms": round(statistics.median(ordered), 2),
        "p90_ms": round(ordered[min(n - 1, max(0, math.ceil(n * 0.90) - 1))], 2),
        "min_ms": round(ordered[0], 2),
        "max_ms": round(ordered[-1], 2),
    }


# ---------------------------------------------------------------- child side


class _MemoryStore:
    """In-memory QSettings stand-in: the harness never writes the user's prefs."""

    def __init__(self, *_args) -> None:
        self._data: dict = {}

    def value(self, key, default=None, type=None):  # noqa: A002 - QSettings signature
        return self._data.get(key, default)

    def setValue(self, key, value) -> None:
        self._data[key] = value

    def remove(self, key) -> None:
        self._data.pop(key, None)

    def contains(self, key) -> bool:
        return key in self._data

    def sync(self) -> None:
        return None


class _Child:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.result: dict = {"file": Path(args.file).name, "samples": {}, "counts": {}}
        self.app = self.view = self.controller = self.model = None
        self.profiler = None

    # -- helpers --------------------------------------------------------

    def _add(self, scenario: str, value_ms: float | None) -> None:
        self.result["samples"].setdefault(scenario, []).append(
            None if value_ms is None else round(value_ms, 3)
        )

    def _pump(self) -> None:
        self.app.processEvents()
        time.sleep(0.0005)

    def _wait(self, predicate, timeout_s: float = WAIT_TIMEOUT_S) -> bool:
        deadline = time.perf_counter() + timeout_s
        while time.perf_counter() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.0005)
        return False

    def _quality(self, page_idx: int) -> str | None:
        sid = self.model.get_active_session_id()
        if not sid:
            return None
        return self.controller._page_quality_map(sid).get(page_idx)

    def _visible_pages(self) -> list[int]:
        start, end = self.view.visible_page_range(prefetch=0)
        return list(range(start, end + 1)) if end >= start else []

    def _all_visible(self, qualities: set[str]) -> bool:
        pages = self._visible_pages()
        return bool(pages) and all(self._quality(p) in qualities for p in pages)

    def _settle_background(self, max_s: float = 10.0) -> float:
        """Let thumbnails / background loading drain (bounded) between scenarios.

        Returns the ms the drain took: background work a scenario left behind."""
        coord = getattr(self.controller, "_thumbnail_coordinator", None)
        t0 = time.perf_counter()
        deadline = t0 + max_s
        for _ in range(5):
            self._pump()
        while time.perf_counter() < deadline:
            self._pump()
            if coord is None or not getattr(coord, "has_active_job", False):
                break
        elapsed = (time.perf_counter() - t0) * 1000.0
        for _ in range(20):
            self._pump()
        return elapsed

    def _profile_start(self, scenario: str) -> None:
        if self.args.profile == scenario:
            import cProfile

            self.profiler = cProfile.Profile()
            self.profiler.enable()

    def _profile_stop(self, scenario: str) -> None:
        if self.profiler is None or self.args.profile != scenario:
            return
        import io
        import pstats

        self.profiler.disable()
        stem = Path(self.args.json_out).with_suffix("")
        prof_path = Path(f"{stem}.{scenario}.prof")
        self.profiler.dump_stats(str(prof_path))
        buf = io.StringIO()
        stats = pstats.Stats(self.profiler, stream=buf).sort_stats("cumulative")
        stats.print_stats(60)
        buf.write("\n\n==== tottime ====\n")
        stats.sort_stats("tottime").print_stats(40)
        Path(f"{stem}.{scenario}.txt").write_text(buf.getvalue(), encoding="utf-8")
        self.profiler = None

    def _install_counters(self) -> None:
        counts = self.result["counts"]

        def wrap(owner, name: str, key: str) -> None:
            original = getattr(owner, name)

            def counted(*a, **kw):
                counts[key] = counts.get(key, 0) + 1
                return original(*a, **kw)

            setattr(owner, name, counted)

        wrap(self.controller, "_rebuild_continuous_scene", "rebuild_continuous_scene")
        wrap(self.controller, "load_toc", "load_toc")
        wrap(self.view, "initialize_continuous_placeholders", "initialize_placeholders")
        wrap(self.controller, "_schedule_thumbnail_batch", "thumbnail_batch_requests")
        wrap(self.view, "_update_thumbnail_layout_metrics", "thumbnail_layout_passes")
        original_consume = self.controller._consume_thumbnail_images

        def consume(start, images):
            counts["thumbnail_images_consumed"] = counts.get("thumbnail_images_consumed", 0) + len(images)
            return original_consume(start, images)

        # The coordinator holds the bound method; patch its consumer reference too.
        self.controller._consume_thumbnail_images = consume
        coord = getattr(self.controller, "_thumbnail_coordinator", None)
        if coord is not None and hasattr(coord, "_batch_consumer"):
            coord._batch_consumer = consume

    def _snapshot_counts(self) -> dict:
        return dict(self.result["counts"])

    def _delta_counts(self, before: dict) -> dict:
        after = self.result["counts"]
        return {k: after.get(k, 0) - before.get(k, 0) for k in after if after.get(k, 0) != before.get(k, 0)}

    # -- scenarios ------------------------------------------------------

    def startup(self) -> None:
        t_in = time.perf_counter()
        self._profile_start("startup")
        import main  # noqa: PLC0415 - timed on purpose
        import utils.preferences as preferences

        preferences._make_default_store = _MemoryStore
        self.result["main_file"] = str(Path(main.__file__).resolve())
        startup = main.run(argv=[], start_event_loop=False)
        self.app, self.view = startup["app"], startup["view"]
        self._startup = startup
        self.app.processEvents()
        t_shown = time.time()
        self._profile_stop("startup")
        self._add("startup_inproc", (t_shown - _CHILD_T_START) * 1000.0)
        self._add("startup_wall", (t_shown - self.args.t0) * 1000.0)
        self.result["startup_main_run_ms"] = round((time.perf_counter() - t_in) * 1000.0, 3)
        self.result["window_size"] = [self.view.width(), self.view.height()]

    def open_document(self) -> None:
        path = str(Path(self.args.file).resolve())
        self._profile_start("open")
        t0 = time.perf_counter()
        self.view._queue_or_open_paths([path])
        self.controller = self._startup["controller"]
        self.model = self._startup["model"]
        if self.controller is None:
            # Bootstrap runs on the signal; it is synchronous today.
            raise RuntimeError("controller not bootstrapped by the open path")
        self._install_counters()
        page = max(0, self.view.current_page)
        ok_low = self._wait(lambda: self._quality(page) in {"low", "high"})
        self._add("open_first_paint", (time.perf_counter() - t0) * 1000.0 if ok_low else None)
        ok_high = self._wait(lambda: self._quality(page) == "high")
        self._add("open_high", (time.perf_counter() - t0) * 1000.0 if ok_high else None)
        self._profile_stop("open")
        self.result["pages"] = len(self.model.doc)
        self._add("bg_after_open", self._settle_background())
        self.result["open_counts"] = dict(self.result["counts"])

    def zoom(self) -> None:
        before = self._snapshot_counts()
        self._profile_start("zoom")
        for factor in ZOOM_FACTORS:
            t0 = time.perf_counter()
            self.view._zoom_relative(factor)
            self._add("zoom_sync", (time.perf_counter() - t0) * 1000.0)
            ok = self._wait(lambda: self._all_visible({"high"}))
            self._add("zoom_settle", (time.perf_counter() - t0) * 1000.0 if ok else None)
        self._profile_stop("zoom")
        self._add("bg_after_zoom", self._settle_background())
        self.result["zoom_counts"] = self._delta_counts(before)

    def fullscreen(self) -> None:
        for phase in ("f5_enter", "f5_exit"):
            before = self._snapshot_counts()
            size_before = [self.view.graphics_view.width(), self.view.graphics_view.height()]
            self._profile_start(phase)
            t0 = time.perf_counter()
            self.view.sig_toggle_fullscreen.emit()
            ok = self._wait(lambda: self._all_visible({"high"}))
            # Let any trailing resize/fit settle so its rebuild is counted too.
            for _ in range(30):
                self._pump()
            self._add(phase, (time.perf_counter() - t0) * 1000.0 if ok else None)
            self._profile_stop(phase)
            self._add(f"bg_after_{phase}", self._settle_background())
            self.result[f"{phase}_counts"] = self._delta_counts(before)
            self.result[f"{phase}_viewport"] = [
                size_before,
                [self.view.graphics_view.width(), self.view.graphics_view.height()],
            ]

    def scroll(self) -> None:
        if len(self.model.doc) < 3:
            return
        sb = self.view.graphics_view.verticalScrollBar()
        self.view.scroll_to_page(0)
        self._wait(lambda: self._all_visible({"high"}))
        self._settle_background()
        lo, hi = sb.minimum(), sb.maximum()
        before = self._snapshot_counts()
        self._profile_start("scroll")
        t_sweep = time.perf_counter()
        for step in range(1, SCROLL_STEPS + 1):
            value = lo + (hi - lo) * step // SCROLL_STEPS
            t0 = time.perf_counter()
            sb.setValue(value)
            self._add("scroll_step_sync", (time.perf_counter() - t0) * 1000.0)
            ok = self._wait(lambda: self._all_visible({"low", "high"}))
            self._add("scroll_step_content", (time.perf_counter() - t0) * 1000.0 if ok else None)
        self._add("scroll_sweep_total", (time.perf_counter() - t_sweep) * 1000.0)
        self._profile_stop("scroll")
        self._add("bg_after_scroll", self._settle_background())
        self.result["scroll_counts"] = self._delta_counts(before)

    def tabs(self) -> None:
        second = str((ROOT / SECOND_TAB_FILE).resolve())
        self.view._queue_or_open_paths([second])
        self._wait(lambda: self.view.document_tab_bar.count() == 2)
        self._wait(lambda: self._quality(max(0, self.view.current_page)) == "high")
        self._settle_background()
        bar = self.view.document_tab_bar
        before = self._snapshot_counts()
        self._profile_start("tabs")
        for _ in range(TAB_ROUND_TRIPS):
            for target in (0, 1):
                t0 = time.perf_counter()
                bar.setCurrentIndex(target)
                self._add("tab_switch_sync", (time.perf_counter() - t0) * 1000.0)
                page = max(0, self.view.current_page)
                ok_low = self._wait(lambda p=page: self._quality(p) in {"low", "high"})
                self._add("tab_switch_low", (time.perf_counter() - t0) * 1000.0 if ok_low else None)
                ok_high = self._wait(lambda p=page: self._quality(p) == "high")
                self._add("tab_switch_high", (time.perf_counter() - t0) * 1000.0 if ok_high else None)
                self._add("bg_after_tab_switch", self._settle_background())
        self._profile_stop("tabs")
        self.result["tabs_counts"] = self._delta_counts(before)

    def run(self) -> None:
        self.startup()
        if not self.args.startup_only:
            self.open_document()
            self.zoom()
            self.fullscreen()
            self.scroll()
            self.tabs()
        Path(self.args.json_out).write_text(json.dumps(self.result, indent=1), encoding="utf-8")


def _child_main(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    child = _Child(args)
    child.result["child_import_ms"] = round((time.time() - _CHILD_T_START) * 1000.0, 3)
    child.run()
    sys.stdout.flush()
    # Teardown is not a target; skip it so a slow worker join cannot stall the sweep.
    os._exit(0)


# ---------------------------------------------------------------- parent side


def _spawn(args: argparse.Namespace, root: str, file: str, run_idx: int, out_dir: Path, label: str) -> dict | None:
    stem = f"{label}.{Path(file).stem}.r{run_idx}"
    json_out = out_dir / f"{stem}.json"
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env.pop("PDF_EDITOR_DEBUG", None)
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--file", str((ROOT / file).resolve()),
        "--repo-root", str(Path(root).resolve()),
        "--json-out", str(json_out),
        "--t0", repr(time.time()),
    ]
    if args.profile:
        cmd += ["--profile", args.profile]
    if args.startup_only:
        cmd += ["--startup-only"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(Path(root).resolve()),
            env=env,
            capture_output=True,
            text=True,
            timeout=args.child_timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT {stem}", flush=True)
        return None
    if proc.returncode != 0 or not json_out.is_file():
        print(f"  FAILED {stem} rc={proc.returncode}\n{proc.stderr[-2000:]}", flush=True)
        return None
    return json.loads(json_out.read_text(encoding="utf-8"))


def _summarize(runs: dict[str, list[dict]]) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for name, results in runs.items():
        per: dict[str, dict] = {}
        for scenario in SCENARIOS:
            samples = [v for r in results for v in r["samples"].get(scenario, [])]
            missing = sum(1 for v in samples if v is None)
            if samples:
                per[scenario] = {**_summary(samples), "timeouts": missing}
        per["counts_last_run"] = {
            k: results[-1].get(k)
            for k in ("open_counts", "zoom_counts", "f5_enter_counts", "f5_exit_counts", "scroll_counts", "tabs_counts")
        }
        per["pages"] = results[-1].get("pages")
        per["main_file"] = results[-1].get("main_file")
        summary[name] = per
    return summary


def _parent_main(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.gettempdir()) / "pdf_editor_perf"
    out_dir.mkdir(parents=True, exist_ok=True)
    label = args.label or time.strftime("%Y%m%d_%H%M%S")
    files = args.files or DEFAULT_FILES
    # --ab-root: children alternate A (that tree, e.g. a pre-change snapshot)
    # and B (--repo-root) per (run, file) so machine drift hits both alike.
    roots = [("A", args.ab_root), ("B", args.repo_root)] if args.ab_root else [("", args.repo_root)]
    runs: dict[str, dict[str, list[dict]]] = {tag: {} for tag, _root in roots}
    for run_idx in range(args.runs):
        for file in files:
            for tag, root in roots:
                sub = f"{label}.{tag}" if tag else label
                print(f"[{sub}] run {run_idx + 1}/{args.runs} {Path(file).name}", flush=True)
                res = _spawn(args, root, file, run_idx, out_dir, sub)
                if res is not None:
                    runs[tag].setdefault(Path(file).name, []).append(res)
    summaries = {tag: _summarize(by_file) for tag, by_file in runs.items()}
    report = {
        "harness": "benchmark_ui_perf",
        "label": label,
        "roots": {tag: str(Path(root).resolve()) for tag, root in roots},
        "runs": args.runs,
        "profile": args.profile,
        "summary": summaries,
        "raw": runs,
    }
    report_path = out_dir / f"{label}.summary.json"
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    first = summaries[roots[0][0]]
    for name, per in first.items():
        print(f"\n{name} ({per.get('pages')} pages)")
        for scenario in SCENARIOS:
            cells = []
            for tag, _root in roots:
                s = summaries[tag].get(name, {}).get(scenario)
                if s and s.get("n"):
                    cells.append(
                        f"{tag or 'median'} {s['median_ms']:>9.1f} (p90 {s['p90_ms']:>8.1f}, n={s['n']}, to={s['timeouts']})"
                    )
            if cells:
                print(f"  {scenario:22s} " + "  |  ".join(cells))
        for tag, _root in roots:
            print(f"  counts {tag}: {summaries[tag].get(name, {}).get('counts_last_run')}")
    print(f"\nreport: {report_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--files", nargs="*", help="repo-relative PDFs (default: four sizes)")
    parser.add_argument("--out-dir", help="raw JSON directory (default <TEMP>/pdf_editor_perf)")
    parser.add_argument("--label", help="report label (default: timestamp)")
    parser.add_argument("--repo-root", default=str(ROOT), help="source tree the children import")
    parser.add_argument("--ab-root", help="interleave children against this second tree (reported as A; --repo-root is B)")
    parser.add_argument("--profile", choices=("startup", "open", "zoom", "f5_enter", "f5_exit", "scroll", "tabs"))
    parser.add_argument("--startup-only", action="store_true")
    parser.add_argument("--child-timeout", type=float, default=300.0)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--file", help=argparse.SUPPRESS)
    parser.add_argument("--json-out", help=argparse.SUPPRESS)
    parser.add_argument("--t0", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.child:
        return _child_main(args)
    return _parent_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
