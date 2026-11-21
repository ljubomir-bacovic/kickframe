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
| `horizon` | perspective floor rushing toward a sliced polygon sun; kicks surge the travel, a ceiling closes in during peaks, the sun turns red |
| `scope` | radial oscilloscope: a closed trace shaped by bass, mids and hats, with fading echoes; Lissajous in peaks |
| `field` | a lattice of crosses; each kick sends a wave from the centre that lifts and turns them, hats sparkle at random |
| `sphere` | wireframe globe stepping 15° per beat, a scan line sweeps pole to pole on every kick, red equator and an orbit in peaks |
| `moire` | two sets of concentric rings that slide apart on the kick into moiré interference; hexagons in breakdowns |
| `branches` | fractal: a radial tree forking level by level; generations grow with intensity, the kick pulses from trunk to tips, mids open the branches in breaks |
| `sierpinski` | fractal: an endless, seamless zoom into six Sierpinski triangles meeting at the centre; kicks push the zoom, finer levels fade in with intensity |

Options: `--size 1080p | 4k | 720p | vertical | square | WxH`, `--hud / --no-hud` (bar counter and labels; on by default except for `tunnel`, `subtle`, `horizon`, `moire` and `branches`), `--fps`, `--crf`, `--preset`, `--jobs`.

Many styles expose their look as class attributes, so a variant is a two-line subclass, e.g. `class TunnelMono(Tunnel): red_every = 0` or `class HorizonTri(Horizon): SUN_SIDES = [3]`.

No audio yet? `--synthetic --bpm 136 --bars 32` gives a 4-section arrangement on a beat grid, useful for loops:

```bash
kickframe video --synthetic --bpm 136 --bars 32 --style bold -o loop.mp4
```

## Combining styles

`--style` also takes combinations, for both `video` and `stills`.

**Layers:** join styles with `+` to draw them in the same frame. An optional `@opacity` dims a layer. Layers combine with *screen* by default, so lines brighten and never hide each other (`--blend add|over` for alternatives).

```bash
kickframe video track.mp3 --style "tunnel@0.3+scope" -o a.mp4         # dimmed tunnel behind a bright scope
kickframe video track.mp3 --style "horizon+sphere@0.9" -o b.mp4       # a globe rising over the floor
kickframe video track.mp3 --style "sierpinski@0.45+branches" -o c.mp4 # tree over the endless zoom
```

**Sequences:** separate styles with `,` to switch between them over the track. Items can be layered too.

```bash
kickframe video track.mp3 --style tunnel,sphere,branches --switch 32 -o d.mp4       # every 32 bars (default)
kickframe video track.mp3 --style "tunnel,sierpinski+field@0.4" --switch drops -o e.mp4  # at each drop
kickframe video track.mp3 --style geometric,subtle --switch sections -o f.mp4       # breakdowns vs grooves
kickframe video track.mp3 --timeline "0=subtle, 1:52=tunnel, b129=sphere+scope@0.5, 12:40=branches" -o g.mp4
```

- `--switch N | drops | sections`: every N bars, when the kick returns, or whenever the kick stops or returns. The list repeats as needed.
- `--timeline`: entries are `WHEN=STYLE`. WHEN is seconds, `m:ss`, or `bN` for bar N (as the HUD counts). Times snap to the nearest bar line, so switches land on a downbeat.
- `--transition fade` (default) crossfades over `--fade-beats` (default 4, one bar), finishing on the downbeat. `--transition cut` cuts hard on the downbeat.
- Combinations render without the HUD unless you pass `--hud`. A combination costs about the sum of its parts to render.

## File size and render time

Dense line art that moves every frame compresses poorly. Rough figures at 1080p30:

| style | full 17-min track, `--crf 24` | render time (2 cores) |
|---|---|---|
| `subtle` | ~50 MB | ~10 min |
| `bold` | ~500 MB | ~10 min |
| `atom` / `geometric` | ~500 MB | ~15 min |
| `tunnel` | ~1.5 GB | ~25 min |

The newer styles have not been measured on a full track yet. Drawing cost per 1080p frame on one core: `bold` 11 ms, `geometric` 19, `atom` 21, `sphere` 26, `scope` 28, `subtle` 28, `field` 34, `horizon` 36, `tunnel` 49, `branches` 41, `sierpinski` 77, `moire` 108. `moire` is the densest picture and will likely produce the largest files.

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
kickframe cover tree -o e.png --param arms=3 --param spread=0.6 --param depth=11
kickframe cover sierpinski -o f.png --param hexagon=False --param depth=8 --param red_every=0
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
  combine.py    layering and sequencing styles (timeline, switch, crossfade)
  covers.py     square cover art
  cli.py        command line
```
