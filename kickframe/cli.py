"""Command line: kickframe <command> ..."""
from __future__ import annotations

import argparse
import ast
import os
import sys

from .analysis import Controls, analyze, synthetic
from .covers import COVERS, make_cover
from .render import render_stills, render_video
from .styles import STYLES

NO_HUD_BY_DEFAULT = {"tunnel", "subtle"}


def _controls(args) -> Controls:
    if getattr(args, "synthetic", False):
        return synthetic(bpm=args.bpm or 136.0, bars=args.bars, fps=args.fps)
    if not args.audio:
        sys.exit("give an audio file, or --synthetic")
    path = args.controls or f"{os.path.splitext(os.path.basename(args.audio))[0]}.{args.fps}fps.controls.npz"
    if os.path.exists(path) and not args.reanalyze:
        print(f"using cached analysis {path} (--reanalyze to redo)")
        return Controls.load(path)
    ctl = analyze(args.audio, fps=args.fps, bpm=args.bpm)
    ctl.save(path)
    print(f"saved analysis to {path}")
    return ctl


def _hud(args) -> bool:
    if args.hud is not None:
        return args.hud
    return args.style not in NO_HUD_BY_DEFAULT


def _parse_size(s: str):
    presets = {"1080p": (1920, 1080), "4k": (3840, 2160), "720p": (1280, 720),
               "vertical": (1080, 1920), "square": (1080, 1080)}
    if s in presets:
        return presets[s]
    w, h = s.lower().split("x")
    return int(w), int(h)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kickframe", description="Kickframe: beat-synced geometric visuals and cover art.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("audio", nargs="?", help="track (mp3/wav/flac/...)")
        p.add_argument("--bpm", type=float, help="nominal tempo; detected if omitted, always fine-tuned")
        p.add_argument("--fps", type=int, default=30)
        p.add_argument("--controls", help="analysis cache file (default: <track>.<fps>fps.controls.npz)")
        p.add_argument("--reanalyze", action="store_true")
        p.add_argument("--synthetic", action="store_true", help="no audio: a beat grid at --bpm")
        p.add_argument("--bars", type=int, default=32, help="length for --synthetic")
        p.add_argument("--style", choices=sorted(STYLES), default="tunnel")
        p.add_argument("--size", default="1080p", help="1080p, 4k, 720p, vertical, square or WxH")
        g = p.add_mutually_exclusive_group()
        g.add_argument("--hud", dest="hud", action="store_true", default=None, help="show bar counter/labels")
        g.add_argument("--no-hud", dest="hud", action="store_false")

    p = sub.add_parser("analyze", help="detect tempo/beat grid and save the analysis")
    p.add_argument("audio")
    p.add_argument("--bpm", type=float)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--controls")
    p.add_argument("--reanalyze", action="store_true", default=True)

    p = sub.add_parser("video", help="render a video")
    common(p)
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--start", type=float, default=0.0, help="seconds")
    p.add_argument("--duration", type=float, help="seconds (default: to the end)")
    p.add_argument("--crf", type=int, default=24, help="quality: lower = better/bigger (18-30)")
    p.add_argument("--preset", default="veryfast", help="x264 preset (slower = smaller files)")
    p.add_argument("--jobs", type=int, help="parallel processes (default: all cores)")
    p.add_argument("--with-audio", action="store_true", help="mux the track into the video")
    p.add_argument("--workdir", help="keep chunks here; rerunning resumes an interrupted render")

    p = sub.add_parser("stills", help="render single frames to PNG to check a look quickly")
    common(p)
    p.add_argument("--at", type=float, nargs="+", required=True, help="times in seconds")
    p.add_argument("--prefix", default="still")

    p = sub.add_parser("cover", help="square cover art")
    p.add_argument("kind", choices=sorted(COVERS))
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--size", type=int, default=3000)
    p.add_argument("--title")
    p.add_argument("--subtitle")
    p.add_argument("--font", default="monospace")
    p.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                   help="e.g. --param layers=48 --param 'sides=(3,4,6,8)' --param twist=0.1")

    sub.add_parser("styles", help="list video styles and cover kinds")

    args = ap.parse_args(argv)

    if args.cmd == "styles":
        for name, cls in STYLES.items():
            print(f"  video  {name:10s} {cls.__doc__.split(chr(10))[0]}")
        for name, fn in COVERS.items():
            print(f"  cover  {name}")
        return

    if args.cmd == "analyze":
        path = args.controls or f"{os.path.splitext(os.path.basename(args.audio))[0]}.{args.fps}fps.controls.npz"
        analyze(args.audio, fps=args.fps, bpm=args.bpm).save(path)
        print(f"saved analysis to {path}")
        return

    if args.cmd == "cover":
        params = {}
        for kv in args.param:
            k, v = kv.split("=", 1)
            try:
                params[k] = ast.literal_eval(v)
            except (ValueError, SyntaxError):
                params[k] = v
        make_cover(args.kind, args.out, size=args.size, title=args.title, subtitle=args.subtitle,
                   font=args.font, **params)
        return

    ctl = _controls(args)
    w, h = _parse_size(args.size)
    if args.cmd == "stills":
        render_stills(ctl, args.style, args.at, f"{args.prefix}_{args.style}", w, h, hud=_hud(args))
    elif args.cmd == "video":
        render_video(ctl, args.style, args.out, w, h, crf=args.crf, preset=args.preset, jobs=args.jobs,
                     start=args.start, duration=args.duration,
                     audio=args.audio if args.with_audio and not args.synthetic else None,
                     hud=_hud(args), workdir=args.workdir)


if __name__ == "__main__":
    main()
