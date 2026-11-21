# Kickframe

Beat-synced geometric visualizers and cover art for techno tracks.
Everything is drawn with code (Cairo vector graphics → H.264 via ffmpeg), so the output is crisp at any resolution and fully reproducible.

## Install

1. Install ffmpeg:
   - Windows: `winget install Gyan.FFmpeg`
   - macOS: `brew install ffmpeg`
   - Debian/Ubuntu: `sudo apt install ffmpeg libcairo2-dev pkg-config`
2. From this folder, in an activated virtual environment:
   ```bash
   pip install -e .
   ```

That installs the `kickframe` command, so you can run it from any folder (for example, the one with your tracks). With `-e`, edits to the code take effect immediately with no reinstall. `python -m kickframe …` also works.

## Quick start

```bash
# 1. Look first: a few frames take seconds, a full render takes a while
kickframe stills track.mp3 --style tunnel --at 60 300 480 763

# 2. A short preview with sound
kickframe video track.mp3 --style tunnel --start 480 --duration 30 --with-audio -o preview.mp4

# 3. The whole track (silent; add --with-audio to include the track)
kickframe video track.mp3 --style tunnel -o berlin_1_tunnel.mp4 --workdir work_tunnel

# Cover art, 3000x3000 (the size streaming platforms ask for)
kickframe cover ngons -o cover.png
kickframe cover ngons -o cover_title.png --title BERLIN_1 --subtitle "136 BPM"
```

`kickframe styles` lists everything.

## What it does with your track

`analyze` (run automatically the first time and cached as `<track>.30fps.controls.npz`):

- **Tempo and beat grid.** It detects the BPM (or takes `--bpm 136` as a hint), then fits the exact tempo and phase to the kick attacks on the waveform. Masters are rarely exactly on the nominal tempo: berlin_1 is 136.026. It also measures the grid error every 8 s and follows it, because edited arrangements shift. berlin_1 jumps 75 ms at the breakdown, and the grid holds within ~1 ms across all 17 minutes.
- **Bands per video frame:** kick (35–120 Hz), bass, mids and highs (hat onsets).
- **Structure:** overall intensity (drives how busy the picture is), kick present or absent (breakdowns), and kick re-entries (flashes). The first re-entry also sets which beat is "1" of the bar.

## Video styles

| style | look |
|---|---|
| `tunnel` | the n-gon spiral as an endless tunnel: triangles are born in the centre and flow outward through squares, pentagons, hexagons and octagons; kick surges, twist follows energy, red layers |
| `atom` | electron shells with comet-trail electrons, phyllotaxis nucleus, morphing polygons, Lissajous in peaks, rose curve in breaks |
| `geometric` | morphing n-gons (sides change every 16 bars), kick ripples, spokes, orbiting triangles/squares |
| `bold` | nested squares stepping 22.5° per beat, grid, sweeping bars, red downbeats in peaks |
| `subtle` | four thin squares, slow rotation, soft breath on the kick |

Options: `--size 1080p | 4k | 720p | vertical | square | WxH`, `--hud / --no-hud` (bar counter and labels; on by default except for `tunnel` and `subtle`), `--fps`, `--crf`, `--preset`, `--jobs`.

No audio yet? `--synthetic --bpm 136 --bars 32` gives a 4-section arrangement on a beat grid, useful for loops:

```bash
kickframe video --synthetic --bpm 136 --bars 32 --style bold -o loop.mp4
```

## File size and render time

Dense line art that moves every frame compresses poorly. Rough figures at 1080p30:

| style | full 17-min track, `--crf 24` | render time (2 cores) |
|---|---|---|
| `subtle` | ~50 MB | ~10 min |
| `bold` | ~500 MB | ~10 min |
| `atom` / `geometric` | ~500 MB | ~15 min |
| `tunnel` | ~1.5 GB | ~25 min |

- Raise `--crf` (27–28) to shrink the file. Above ~30 the thin red lines start to smear.
- `--preset medium` gives ~15% smaller files for ~2× the encode time.
- YouTube re-encodes anyway, so uploading the big file is fine.
- `--workdir DIR` keeps finished 60-second chunks. If a render is interrupted, run the same command again and it resumes.

## Covers

```bash
kickframe cover ngons -o a.png --param layers=50 --param "sides=(3,4,6,8)" --param twist=0.1
kickframe cover atom -o b.png --param shells=4 --param sides=8
kickframe cover lissajous -o c.png --param a=7 --param b=6 --param "inner=(5,4)"
kickframe cover ripple -o d.png --param rings=18
```

Parameters are the keyword arguments of the functions in `kickframe/covers.py`.

## Adding your own style

Subclass `Style` in `kickframe/styles.py`, implement `draw(self, ctx, s)` and add it to `STYLES`.

- **Canvas:** you draw on a canvas 1080 units tall, centred at `(self.CX, self.CY)`. The same code then renders at any size or aspect ratio.
- **Frame state `s`:**
  - Track energy: `s.I` (intensity), `s.K` (kick present), `s.kick` (decaying kick pulse).
  - Bands and events: `s.bass`, `s.mid`, `s.hat`, `s.flash`.
  - Timing: `s.beat`, `s.ph` (phase within the beat), `s.bib` (beat in bar), `s.bar`.
  - Peaks: `s.peak`, `s.pk`.
- **Running state:** anything that accumulates over time (rotation, flow) belongs in `prepare()`, integrated over all frames. Rendering is split across processes, and this keeps the chunks seamless.
- **Shared layers:** `layer_grid`, `layer_ripples`, `layer_lissajous`, `layer_rose`, `layer_ticks`, `layer_brackets`, `layer_hud`.

## Layout

```
kickframe/
  analysis.py   audio decode, beat grid, bands, per-frame controls
  styles.py     video styles and shared drawing layers
  render.py     parallel chunked rendering, concat, audio mux, stills
  covers.py     square cover art
  cli.py        command line
```
