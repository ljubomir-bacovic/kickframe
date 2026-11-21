"""Audio analysis: tempo, beat grid, frequency bands and per-frame control signals.

Everything a style needs is computed once here and stored per video frame, so
rendering can be split across processes without any shared state.
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field, asdict

import numpy as np

SR = 22050


def load_audio(path: str, sr: int = SR) -> np.ndarray:
    """Decode any audio file ffmpeg understands to mono float64."""
    import os
    import shutil
    import sys
    if not os.path.isfile(path):
        sys.exit(f"audio file not found: {os.path.abspath(path)}")
    if shutil.which("ffmpeg") is None:
        sys.exit("ffmpeg not found on PATH: install it and reopen the terminal")
    r = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True)
    if r.returncode != 0:
        sys.exit(f"ffmpeg could not read {path}:\n{r.stderr.decode(errors='replace')}")
    raw = r.stdout
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def _stft_mag(x: np.ndarray, centers: np.ndarray, n: int) -> np.ndarray:
    win = np.hanning(n)
    xp = np.pad(x, (n, n))
    out = np.empty((len(centers), n // 2 + 1))
    step = 4096  # chunk to keep memory bounded on long tracks
    for i in range(0, len(centers), step):
        c = centers[i:i + step] + n
        idx = c[:, None] + np.arange(-n // 2, n // 2)[None, :]
        out[i:i + step] = np.abs(np.fft.rfft(xp[idx] * win, axis=1))
    return out


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    k = np.ones(n) / n
    return np.convolve(np.pad(x, (n, n), mode="edge"), k, mode="same")[n:-n]


def _follow(x: np.ndarray, decay: float) -> np.ndarray:
    """Peak follower: instant attack, exponential release."""
    y = np.empty_like(x)
    p = 0.0
    for i, v in enumerate(x):
        p = max(v, p * decay)
        y[i] = p
    return y


def _norm(e: np.ndarray, lo_pct=5, hi_pct=99) -> np.ndarray:
    lo, hi = np.percentile(e, lo_pct), np.percentile(e, hi_pct)
    return np.clip((e - lo) / (hi - lo + 1e-9), 0, 1)


def estimate_beat_grid(x: np.ndarray, sr: int = SR, bpm: float | None = None,
                       bpm_range=(110.0, 160.0)):
    """Return (bpm, offset_seconds, (window_times, phase_corrections_seconds)).

    Uses a low-band onset envelope at ~86 Hz. If bpm is given it is refined
    within +-0.3 BPM (masters are rarely exactly on the nominal tempo).
    """
    hop, n = 256, 1024
    centers = np.arange(0, len(x), hop)
    mag = _stft_mag(x, centers, n)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    low = np.log1p(mag[:, (freqs >= 35) & (freqs < 150)].sum(1))
    onset = np.maximum(np.diff(low, prepend=low[0]), 0)
    rate = sr / hop
    t = np.arange(len(onset)) / rate

    def score(b):
        spb = 60.0 / b
        bins = 240
        ph = ((t % spb) / spb * bins).astype(int) % bins
        hist = np.bincount(ph, weights=onset, minlength=bins)
        hist = np.convolve(np.r_[hist[-2:], hist, hist[:2]], np.ones(5) / 5, "valid")
        k = int(hist.argmax())
        return hist[k], (k + 0.5) / bins * spb

    if bpm is None:
        # coarse: autocorrelation of onset envelope
        o = onset - onset.mean()
        ac = np.correlate(o[: int(rate * 120)], o[: int(rate * 120)], "full")[len(o[: int(rate * 120)]) - 1:]
        lags = np.arange(len(ac))
        cand = []
        for b in np.arange(bpm_range[0], bpm_range[1], 0.5):
            lag = rate * 60 / b
            i = int(round(lag))
            if i < len(ac):
                cand.append((ac[i] + 0.5 * ac[min(len(ac) - 1, int(round(lag * 2)))], b))
        bpm = max(cand)[1]
        search = np.arange(bpm - 1.0, bpm + 1.0, 0.01)
    else:
        search = np.arange(bpm - 0.3, bpm + 0.3, 0.005)
    best = max((score(b) + (b,) for b in search), key=lambda s: s[0])
    bpm = best[2]

    # Phase from the waveform: STFT onsets fire a frame or two before the
    # attack, so fold the rise of a low-passed amplitude envelope instead.
    lp = np.convolve(x, np.ones(40) / 40, "same")            # ~550 Hz low-pass
    env = np.convolve(np.abs(lp), np.ones(110) / 110, "same")  # 5 ms envelope
    rise = np.maximum(np.diff(env, prepend=env[0]), 0)
    dec = 10                                                   # ~2.2 kHz is plenty
    rise = rise[: len(rise) // dec * dec].reshape(-1, dec).sum(1)
    ts = (np.arange(len(rise)) + 0.5) * dec / sr
    bins = 441

    def fold(b):
        spb = 60.0 / b
        hist = np.bincount(((ts % spb) / spb * bins).astype(int) % bins, weights=rise, minlength=bins)
        k = int(hist.argmax())
        return hist[k], (k + 0.5) / bins * spb

    # joint fine search: the sharpest fold wins (a wrong tempo smears the phase)
    best = max((fold(b) + (b,) for b in np.arange(bpm - 0.06, bpm + 0.06, 0.002)), key=lambda s: s[0])
    _, offset, bpm = best
    spb = 60.0 / bpm

    # Local phase corrections: arrangements are often edited (a break shortened,
    # a section nudged), so measure the grid error in 16 s windows and let the
    # grid follow it. Windows without a clear kick (breaks) are interpolated.
    wt, wd = [], []
    for w0 in np.arange(0, ts[-1], 8.0):
        m = (ts >= w0) & (ts < w0 + 16)
        if m.sum() < 100:
            continue
        ph = ((ts[m] - offset) / spb) % 1.0
        h = np.bincount((ph * 200).astype(int) % 200, weights=rise[m], minlength=200)
        h = np.convolve(np.r_[h[-2:], h, h[:2]], np.ones(5) / 5, "valid")
        if h.max() < 4 * (h.mean() + 1e-12):   # no clear beat here
            continue
        d = (h.argmax() + 0.5) / 200
        wt.append(w0 + 8)
        wd.append((d - 1 if d > 0.5 else d) * spb)
    if len(wd) >= 3:
        wd = np.array(wd)
        med = np.array([np.median(wd[max(0, i - 2):i + 3]) for i in range(len(wd))])  # drop outliers
        return float(bpm), float(offset), (np.array(wt), med)
    return float(bpm), float(offset), (np.array([0.0]), np.array([0.0]))


@dataclass
class Controls:
    """Per-video-frame control signals (all arrays have length nf)."""
    fps: int
    bpm: float
    offset: float
    duration: float
    bar_shift: int
    I: np.ndarray        # overall intensity 0..1 (smoothed over ~2 bars)
    K: np.ndarray        # kick present 0..1
    flash: np.ndarray    # decaying pulse when the kick returns after a break
    hat: np.ndarray      # high-band onset follower 0..1
    bass: np.ndarray     # bass level 0..1
    mid: np.ndarray      # mid level 0..1
    beat: np.ndarray     # continuous beat position on the fitted grid
    fade: np.ndarray     # fade in/out multiplier
    extra: dict = field(default_factory=dict)

    @property
    def nf(self) -> int:
        return len(self.I)

    def save(self, path: str) -> None:
        d = {k: v for k, v in asdict(self).items() if k != "extra"}
        np.savez(path, **d)

    @classmethod
    def load(cls, path: str) -> "Controls":
        d = np.load(path)
        kw = {k: d[k] for k in d.files}
        for k in ("fps", "bar_shift"):
            kw[k] = int(kw[k])
        for k in ("bpm", "offset", "duration"):
            kw[k] = float(kw[k])
        return cls(**kw)


def analyze(path: str, fps: int = 30, bpm: float | None = None, verbose: bool = True) -> Controls:
    x = load_audio(path)
    dur = len(x) / SR
    bpm, offset, (wt, wd) = estimate_beat_grid(x, SR, bpm)
    spb = 60.0 / bpm
    nf = int(dur * fps)
    t = np.arange(nf) / fps
    local_off = offset + np.interp(t, wt, wd)   # grid follows local corrections

    n = 2048
    centers = (t * SR).astype(int)
    mag = _stft_mag(x, centers, n)
    freqs = np.fft.rfftfreq(n, 1 / SR)

    def band(lo, hi):
        return np.log1p(mag[:, (freqs >= lo) & (freqs < hi)].sum(1))

    kick = _norm(band(35, 120))
    bass = _norm(band(120, 400))
    mid = _norm(band(400, 2500))
    high_e = band(2500, min(10000, SR / 2))
    high_on = np.maximum(np.diff(high_e, prepend=high_e[0]), 0)
    high_on = np.clip(high_on / (np.percentile(high_on, 99.5) + 1e-9), 0, 1)

    kick_lvl = _smooth(kick, spb * 2 * fps)
    K = np.clip((kick_lvl - 0.12) / 0.2, 0, 1)

    I = _smooth((bass + mid + _norm(high_e)) / 3, spb * 8 * fps)
    I = _norm(I, 8, 97)

    beat = (t - local_off) / spb

    # kick re-entries (after a break) -> flashes, and the first one sets the downbeat
    re = [i for i in range(1, nf) if K[i] >= 0.5 > K[i - 1] and t[i] > 4 * spb * 2]
    bar_shift = int(round(beat[re[0]])) % 4 if re else 0
    flash = np.zeros(nf)
    for i in re:
        f0 = int(round((local_off[i] + round(beat[i]) * spb) * fps))
        for j in range(f0, min(nf, f0 + int(spb * 2 * fps))):
            flash[j] = max(flash[j], math.exp(-(j - f0) / fps / spb * 2.5))

    hat = np.clip((_follow(high_on, 0.80) - 0.12) / 0.45, 0, 1)
    fade = np.clip(t / 2.0, 0, 1) * np.clip((t[-1] - t) / 3.0, 0, 1)

    if verbose:
        print(f"duration {dur:.1f}s  bpm {bpm:.3f}  offset {offset:.3f}s  "
              f"grid corrections {1000 * wd.min():+.0f}..{1000 * wd.max():+.0f} ms  frames {nf}  "
              f"breaks/re-entries at {[round(t[i], 1) for i in re]}")
    return Controls(fps=fps, bpm=bpm, offset=offset, duration=dur, bar_shift=bar_shift,
                    I=I, K=K, flash=flash, hat=hat, bass=_smooth(bass, 0.1 * fps),
                    mid=_smooth(mid, 0.15 * fps), beat=beat, fade=fade)


def synthetic(bpm: float = 136.0, bars: int = 32, fps: int = 30) -> Controls:
    """A beat grid with no audio: a 4-section arrangement (intro, groove, build, peak)."""
    spb = 60.0 / bpm
    dur = bars * 4 * spb
    nf = int(round(dur * fps))
    t = np.arange(nf) / fps
    beat = t / spb
    sec = np.minimum((beat / 4 / (bars / 4)).astype(int), 3)
    I = _smooth(np.array([0.2, 0.5, 0.65, 0.9])[sec], spb * 4 * fps)
    ph8 = (beat * 2) % 1.0
    hat = np.exp(-((beat + 0.5) % 1.0) * 14)
    return Controls(fps=fps, bpm=bpm, offset=0.0, duration=dur, bar_shift=0, I=I, K=np.ones(nf),
                    flash=np.zeros(nf), hat=hat, bass=0.5 + 0.3 * np.exp(-ph8 * 5),
                    mid=np.full(nf, 0.4), beat=beat, fade=np.clip(t / 1.0, 0, 1))
