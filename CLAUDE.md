# Kickframe

Beat-synced geometric visualizers and cover art for techno tracks. Python 3.10+, numpy, pycairo; ffmpeg must be on PATH.

## Run

- Install for development: `pip install -e .` (in an activated venv), then use the `kickframe` command.
- `kickframe styles`: list video styles and cover kinds.
- Check a visual change with stills first; full renders take minutes:
  `kickframe stills track.wav --style tunnel --at 300 480 763`
- With no track at hand: `kickframe video --synthetic --bpm 136 --bars 4 --style <style> --size 720p -o test.mp4`
- Covers: `kickframe cover ngons -o out.png --size 1000 --param twist=0.1`

## Architecture

- `analysis.py`: decodes audio, fits the beat grid and builds a `Controls` dataclass of per-video-frame arrays (`I` intensity, `K` kick present, `flash`, `hat`, `bass`, `mid`, `beat`, `fade`). Cached as `<track>.<fps>fps.controls.npz`.
  - Beat grid: tempo and phase are fitted on the low-passed waveform envelope, not on STFT onsets, which fire 1–2 frames early.
  - The grid then follows local phase corrections measured every 8 s, because arrangements get edited.
  - Don't simplify this to a single fixed grid: berlin_1 shifts 75 ms at its breakdown.
- `styles.py`: one class per video style, all subclassing `Style`.
  - Draw in a virtual canvas 1080 units tall, centred at `(self.CX, self.CY)`, so every output size works.
  - `state(f)` gives the per-frame values (`s.kick`, `s.ph`, `s.bib`, `s.peak`, ...).
  - Reuse the shared `layer_*` helpers.
- `render.py`: renders 60 s chunks in a multiprocessing Pool, each worker piping raw BGRA frames to its own ffmpeg. Chunks are joined with the concat demuxer (`-c copy`), then audio is muxed in.
- `combine.py`: combinations of styles. `make_style(spec, ...)` returns a plain style for a bare name, or a `Combo` for layers (`a+b@0.5`), sequences (`a,b`) or a `--timeline`. The schedule (current item, next item, crossfade mix) is computed per frame in `Combo.prepare()`, like any running state. `render.py` builds every style through `make_style`.
- `covers.py`: square covers authored on a 3000-unit canvas. The keyword arguments of each cover function are its `--param` options.
- `cli.py`: the argparse front end. `__main__.py` keeps the `if __name__ == "__main__"` guard: on Windows, multiprocessing re-imports the main module.

## Rules

- Anything that accumulates over time (rotation, flow position, drift) must be integrated over all frames in `prepare()`, never inside `draw()`. Chunks render in separate processes, so running state inside `draw()` breaks continuity at chunk boundaries.
- `draw()` must depend only on the frame index and precomputed arrays. That keeps it deterministic and parallel-safe.
- Visual language: background `BG` near-black, lines `INK` off-white, a single accent `RED`. Thin lines, no gradients except vignettes. The owner asked for no filled dots and no star/pentagram shapes.
- A new style needs: a docstring (its first line shows in `kickframe styles`), an entry in `STYLES`, and a row in the README table.
- Don't commit audio, renders, `*.controls.npz` or `work*/` folders.
