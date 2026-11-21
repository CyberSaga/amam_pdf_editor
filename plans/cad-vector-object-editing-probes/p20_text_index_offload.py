"""A6.0 measurements M1-M6 (product functions only). Run with the venv python: <this> [out.json]"""
from __future__ import annotations

import cProfile
import hashlib
import json
import pstats
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "test_scripts"))

from model import table_objects  # noqa: E402
from model.pdf_model import PDFModel  # noqa: E402
from model.text_block import TextBlockManager  # noqa: E402

CAD = ROOT / "test_files" / "cad_vector" / "before.pdf"
HVAC = ROOT / "test_files" / "hvac-dwg.pdf"
OUT: dict = {}


def ms(fn, n=1):
    xs = []
    for _ in range(n):
        t = time.perf_counter()
        r = fn()
        xs.append((time.perf_counter() - t) * 1000)
    return statistics.median(xs), r


def fixtures(tmp: Path) -> dict[str, Path]:
    import test_gui_stall as g

    out = {}
    for k, b in g.BUILDERS.items():
        p = tmp / f"{k}.pdf"
        b(p)
        out[k] = p
    return out


def extract(page_num0: int, page):
    mgr = TextBlockManager()
    mgr._build_page_index(page_num0, page)
    return mgr


def snap(mgr, n):
    def norm(o):
        return asdict(o) if is_dataclass(o) else repr(o)

    return json.dumps(
        [
            [norm(b) for b in mgr._index[n]],
            [norm(s) for s in mgr._span_index[n]],
            [norm(p) for p in mgr._paragraph_index[n]],
            mgr._run_to_paragraph[n],
            mgr._page_plain_lines[n],
        ],
        default=repr,
        sort_keys=True,
    )


def cost_bytes(doc, pno):
    seen, total, stack = set(), 0, []
    page = doc[pno]
    for x in page.get_contents():
        total += len(doc.xref_stream_raw(x) or b"")
    stack.append(page.xref)
    forms = 0
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        try:
            res = doc.xref_get_key(x, "Resources")
        except Exception:
            continue
        # Form XObjects reachable from the page resources (shallow object scan)
        for xr in range(1, 1):
            pass
        del res
    for xr in range(1, doc.xref_length()):
        if doc.xref_get_key(xr, "Subtype")[1] == "/Form":
            forms += 1
            if forms > 256:
                break
            total += len(doc.xref_stream_raw(xr) or b"")
    return total


def m1():
    model = PDFModel()
    model.open_pdf(str(CAD))
    page = model.doc[0]
    pt = fitz.Point(page.rect.width / 2, page.rect.height / 2)
    res = {}
    for label in ("cold", "warm"):
        pr = cProfile.Profile()
        t = time.perf_counter()
        pr.enable()
        model.get_text_info_at_point(1, pt)
        pr.disable()
        wall = (time.perf_counter() - t) * 1000
        st = pstats.Stats(pr)
        calls = {}
        for (f, ln, fn), (cc, nc, tt, ct, callers) in st.stats.items():
            if fn in ("content_textpage", "content_text", "_build_page_index", "ensure_page_index_built"):
                calls[fn] = (nc, round(ct * 1000, 1))
        res[label] = {"wall_ms": round(wall, 1), "calls(n, cum_ms)": calls}
    # the fallback share on the warm gesture
    ct_warm = res["warm"]["calls(n, cum_ms)"].get("content_text", (0, 0))[1]
    res["fallback_share_of_warm"] = round(ct_warm / max(res["warm"]["wall_ms"], 1e-9), 2)
    OUT["M1"] = res
    OUT["_model"] = model


def m2():
    model = OUT["_model"]
    data = table_objects.scratch_page_bytes(model.doc, 1)
    gaps = []
    done = threading.Event()

    errors: list[BaseException] = []

    def worker():
        try:
            d = fitz.open("pdf", data)
            extract(0, d[0])
            d.close()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            done.set()

    th = threading.Thread(target=worker)
    th.start()
    last = time.perf_counter()
    t0 = last
    while not done.is_set():
        time.sleep(0.005)
        now = time.perf_counter()
        gaps.append((now - last) * 1000)
        last = now
    th.join()
    if errors:
        raise errors[0]
    OUT["M2"] = {"total_ms": round((last - t0) * 1000, 1), "max_gap_ms": round(max(gaps), 1), "ticks": len(gaps)}


def m3(paths):
    res = {}
    cases = dict(paths)
    cases["cad_p1"] = CAD
    if HVAC.exists():
        cases["hvac_p29"] = HVAC
    for k, p in cases.items():
        with fitz.open(p) as d:
            pn = 29 if k == "hvac_p29" and d.page_count >= 29 else 1
            ins, _ = ms(lambda: table_objects.scratch_page_bytes(d, pn), 5)
            b = table_objects.scratch_page_bytes(d, pn)
            sha, _ = ms(lambda: hashlib.sha256(b).digest(), 5)
            sc = fitz.open()
            sc.insert_pdf(d, from_page=pn - 1, to_page=pn - 1, annots=False, links=False, widgets=False)
            tb, _ = ms(lambda: sc.tobytes(), 5)
            res[k] = {"scratch_total_ms": round(ins, 1), "tobytes_only_ms": round(tb, 1),
                      "sha256_ms": round(sha, 2), "bytes": len(b)}
    OUT["M3"] = res


def m4():
    with fitz.open(ROOT / "test_files" / "office-report-23p.pdf") as d:
        mgr = extract(0, d[0])
    n = 0
    payload = json.dumps(
        [[asdict(b) for b in mgr._index[n]], [asdict(s) for s in mgr._span_index[n]],
         [asdict(p) for p in mgr._paragraph_index[n]], mgr._run_to_paragraph[n], mgr._page_plain_lines[n]],
        default=lambda o: list(o) if hasattr(o, "__iter__") else repr(o),
    )
    loads, _ = ms(lambda: json.loads(payload), 5)
    import subprocess

    t = time.perf_counter()
    subprocess.run([sys.executable, "-I", "-c", "import fitz"], check=True)
    spawn = (time.perf_counter() - t) * 1000
    OUT["M4"] = {"answer_bytes(approx)": len(payload), "json_loads_ms": round(loads, 1),
                 "spawn_import_fitz_ms": round(spawn, 1),
                 "note": "from_json/install not built yet; asdict+loads is a lower bound for the GUI side"}


def m5(paths):
    res = {}
    cases = dict(paths)
    cases["cad_p1"] = CAD
    if HVAC.exists():
        cases["hvac_p1"] = HVAC
    for k, p in cases.items():
        with fitz.open(p) as d:
            c = cost_bytes(d, 0)
            t, _ = ms(lambda: extract(0, d[0]), 1)
            res[k] = {"cost_bytes": c, "build_ms": round(t, 1)}
    OUT["M5"] = res


def m6():
    res = {}
    # OC-off group
    with fitz.open() as d:
        pg = d.new_page(width=300, height=300)
        pg.insert_text((20, 50), "visible text")
        oc = d.add_ocg("hidden", on=False)
        pg.insert_text((20, 100), "hidden text", oc=oc)
        buf = d.tobytes()
    cases = {"oc_off": (buf, 0)}
    for rot in (0, 90, 180, 270):
        with fitz.open() as d:
            pg = d.new_page(width=300, height=400)
            pg.insert_text((30, 60), f"rot {rot} Hello world", fontsize=14)
            pg.set_rotation(rot)
            cases[f"rot{rot}"] = (d.tobytes(), 0)
    with fitz.open() as d:
        pg = d.new_page()
        pg.insert_text((40, 80), "中文 CID 測試", fontname="china-t", fontsize=14)
        cases["cjk"] = (d.tobytes(), 0)
    for k, (b, pn) in cases.items():
        with fitz.open("pdf", b) as d:
            live = snap(extract(0, d[pn]), 0)
            sc = table_objects.scratch_page_bytes(d, pn + 1)
        with fitz.open("pdf", sc) as d2:
            cp = snap(extract(0, d2[0]), 0)
        res[k] = live == cp
    for k, p in (("cad_p1", CAD), ("hvac_p1", HVAC)):
        if not p.exists():
            continue
        with fitz.open(p) as d:
            live = snap(extract(0, d[0]), 0)
            sc = table_objects.scratch_page_bytes(d, 1)
        with fitz.open("pdf", sc) as d2:
            res[k] = live == snap(extract(0, d2[0]), 0)
    OUT["M6"] = res


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp())
    paths = fixtures(tmp)
    for name, fn in (("M1", m1), ("M2", m2), ("M3", lambda: m3(paths)), ("M4", m4), ("M5", lambda: m5(paths)), ("M6", m6)):
        try:
            fn()
        except Exception:  # noqa: BLE001
            import traceback

            OUT[name] = "ERROR " + traceback.format_exc()[-600:]
    OUT.pop("_model", None)
    text = json.dumps(OUT, indent=1, default=repr, ensure_ascii=False)
    print(text)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding="utf-8")
