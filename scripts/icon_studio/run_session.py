"""Replay an icon-studio session from its batch scripts and export the results.

    python scripts/icon_studio/run_session.py save_03 --step 14            # draw: run one batch + previews
    python scripts/icon_studio/run_session.py save_03 --no-render --export   # replay all, write the SVG
    python scripts/icon_studio/run_session.py save_03 --no-render --video    # replay, player, MP4

A session lives in sessions/<name>/ (session.json + b01.py ... bNN.py). Every
batch reads the state left by the previous one, so replaying from scratch is
deterministic (seeded RNGs) and reproduces the committed SVG byte-for-byte.
"""
from __future__ import annotations

import argparse
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session")
    ap.add_argument("--no-render", action="store_true", help="skip per-batch preview renders (fast replay)")
    ap.add_argument("--upto", type=int, default=0, help="stop after batch N (0 = all)")
    ap.add_argument("--step", type=int, default=0,
                    help="run only batch N on the current state (re-running N restores the snapshot taken before it)")
    ap.add_argument("--export", action="store_true", help="write the final SVG to the session's output path")
    ap.add_argument("--player", action="store_true", help="build the replay player HTML")
    ap.add_argument("--video", action="store_true", help="capture the player to MP4 (needs node + playwright + ffmpeg)")
    args = ap.parse_args()

    sess = HERE / "sessions" / args.session
    cfg = json.loads((sess / "session.json").read_text(encoding="utf-8"))
    work = HERE / "work" / args.session
    os.environ["ICON_STUDIO_WORK"] = str(work)
    os.environ["ICON_STUDIO_REF"] = str(REPO / cfg["reference"])
    os.environ["ICON_STUDIO_REF_MAP"] = ",".join(str(v) for v in cfg["ref_map"])
    if args.no_render:
        os.environ["ICON_STUDIO_NO_RENDER"] = "1"
    sys.path[:0] = [str(HERE), str(sess)]

    if args.step:
        import studio

        snap = studio.SNAP / f"b{args.step:02d}_before.json"
        if snap.exists():
            studio.restore(args.step)
        runpy.run_path(str(sess / f"b{args.step:02d}.py"), run_name="__main__")
        return 0
    if work.exists():
        shutil.rmtree(work)
    batches = sorted(sess.glob("b[0-9][0-9].py"))
    for f in batches:
        n = int(f.stem[1:])
        if args.upto and n > args.upto:
            break
        runpy.run_path(str(f), run_name="__main__")

    from studio import Studio  # imported after the env/path setup above

    s = Studio.open()
    out_svg = work / "final.svg"
    out_svg.write_text(s.svg(process=False, title=cfg["title"]) + "\n", encoding="utf-8")
    print("counts:", s.count())
    if args.export:
        target = REPO / cfg["output"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out_svg, target)
        print("exported", target)
    if args.player or args.video:
        from build_player import build

        html = build(work / "player.html", title=cfg["title"])
        print("player", html)
        if args.video:
            mp4 = work / f"{args.session}_drawing_process.mp4"
            subprocess.run(["node", str(HERE / "capture.js"), str(html), str(mp4)], check=True)
            print("video", mp4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
