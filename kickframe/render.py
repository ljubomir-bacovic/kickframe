"""Rendering: frames -> H.264 chunks in parallel -> one MP4 (optionally with audio)."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from multiprocessing import Pool

from .analysis import Controls
from .combine import make_style

_style = None


def _init(ctl_path, style, width, height, hud, combo):
    global _style
    _style = make_style(style, Controls.load(ctl_path), width, height, hud=hud, **combo)


def _render_chunk(job):
    f0, f1, out, fps, crf, preset = job
    tmp = out + ".part.mp4"
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgra",
         "-s", f"{_style.W}x{_style.H}", "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-tune", "animation",
         "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
    for f in range(f0, f1):
        p.stdin.write(bytes(_style.frame(f).get_data()))
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg failed on frames {f0}-{f1}")
    os.replace(tmp, out)  # a stopped render never leaves a playable short chunk
    return f1 - f0


def render_video(ctl: Controls, style: str, out: str, width=1920, height=1080, crf=24,
                 preset="veryfast", jobs=None, start=0.0, duration=None, audio=None,
                 hud=True, chunk_seconds=60, workdir=None, combo=None):
    """Render [start, start+duration) of the track to `out`.

    style: a style name, or a combination ("tunnel+scope@0.5", "tunnel,sphere"; see combine.py).
    audio: path to the track to mux in (cut to the same range), or None for silent.
    combo: options for combinations (timeline, switch, transition, fade_beats, blend).
    """
    combo = combo or {}
    fps = ctl.fps
    f_start = max(0, int(round(start * fps)))
    f_end = ctl.nf if duration is None else min(ctl.nf, f_start + int(round(duration * fps)))
    jobs = jobs or os.cpu_count() or 2
    work = workdir or tempfile.mkdtemp(prefix="kickframe_")
    os.makedirs(work, exist_ok=True)
    ctl_path = os.path.join(work, "controls.npz")
    ctl.save(ctl_path)

    step = max(1, int(chunk_seconds * fps))
    chunks = []
    for i, f0 in enumerate(range(f_start, f_end, step)):
        chunks.append((f0, min(f_end, f0 + step), os.path.join(work, f"chunk_{i:04d}.mp4"), fps, crf, preset))
    todo = [c for c in chunks if not os.path.exists(c[2])]  # resume: finished chunks are kept

    t0 = time.time()
    done = len(chunks) - len(todo)
    print(f"rendering {f_end - f_start} frames in {len(chunks)} chunks ({done} already done) on {jobs} processes")
    with Pool(jobs, initializer=_init, initargs=(ctl_path, style, width, height, hud, combo)) as pool:
        for n in pool.imap_unordered(_render_chunk, todo):
            done += 1
            print(f"  chunk {done}/{len(chunks)}  ({time.time() - t0:.0f}s)", flush=True)

    lst = os.path.join(work, "list.txt")
    with open(lst, "w") as fh:
        for c in chunks:
            fh.write(f"file '{os.path.abspath(c[2])}'\n")
    video_only = os.path.join(work, "video.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", video_only], check=True)
    if audio:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video_only, "-ss", f"{f_start / fps:.3f}",
               "-i", audio, "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
               "-shortest", "-movflags", "+faststart", out]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video_only, "-c", "copy",
               "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)
    if workdir is None:
        shutil.rmtree(work, ignore_errors=True)
    print(f"wrote {out}  ({os.path.getsize(out) / 1e6:.1f} MB, {time.time() - t0:.0f}s)")


def render_stills(ctl: Controls, style: str, times, prefix: str, width=1920, height=1080, hud=True,
                  combo=None):
    st = make_style(style, ctl, width, height, hud=hud, **(combo or {}))
    paths = []
    for t in times:
        f = min(ctl.nf - 1, max(0, int(round(t * ctl.fps))))
        p = f"{prefix}_{t:07.2f}s.png"
        st.frame(f).write_to_png(p)
        paths.append(p)
        print("wrote", p)
    return paths
