"""Combining styles in one video.

Layering:   "tunnel+scope@0.5"   draws styles on top of each other (optional opacity after @).
Switching:  "tunnel,sphere,branches" changes style over the track, every N bars, at drops, at every
            section change, or on an explicit timeline. Transitions are a crossfade that lands on
            the downbeat, or a hard cut.

The schedule (which style is on screen, and the crossfade) is computed once for all frames in
prepare(), so parallel chunks stay seamless like every other running state.
"""
from __future__ import annotations

import math
import re

import cairo
import numpy as np

from .analysis import Controls
from .styles import STYLES, Style, ease

BLEND = {"screen": cairo.OPERATOR_SCREEN, "add": cairo.OPERATOR_ADD, "over": cairo.OPERATOR_OVER}


def parse_layers(item: str) -> list[tuple[str, float]]:
    """'tunnel+scope@0.5' -> [('tunnel', 1.0), ('scope', 0.5)]"""
    out = []
    for part in item.split("+"):
        name, _, op = part.strip().partition("@")
        if name not in STYLES:
            raise ValueError(f"unknown style {name!r}; `kickframe styles` lists them")
        out.append((name, float(op) if op else 1.0))
    return out


def parse_timeline(text: str) -> list[tuple[str, str]]:
    """'0=tunnel, 4:48=sphere+scope@0.4, b129=branches' -> [('0', 'tunnel'), ...]"""
    out = []
    for entry in text.split(","):
        if entry.strip():
            when, sep, item = entry.partition("=")
            if not sep:
                raise ValueError(f"timeline entry {entry.strip()!r} needs WHEN=STYLE")
            parse_layers(item)
            out.append((when.strip(), item.strip()))
    return out


def is_simple(spec: str, timeline: str | None = None) -> bool:
    return not timeline and re.fullmatch(r"[a-z_]+", spec.strip()) is not None


class Combo(Style):
    """Several styles layered in one frame and/or switched over the track."""
    name = "combo"

    def __init__(self, ctl: Controls, width: int, height: int, hud: bool = False, items=(),
                 timeline=None, switch=None, transition="fade", fade_beats=4.0, blend="screen"):
        self.items_spec = list(items)
        self.timeline_spec = timeline
        self.switch = switch
        self.transition = transition
        self.fade_beats = fade_beats
        self.blend = BLEND[blend]
        super().__init__(ctl, width, height, hud)

    # -- schedule --------------------------------------------------------
    def prepare(self):
        c = self.c
        fps = c.fps
        spb = 60.0 / c.bpm
        self.bar_f = np.floor((np.floor(c.beat) - c.bar_shift) / 4).astype(int)
        self.bar_starts = np.nonzero(np.diff(self.bar_f) > 0)[0] + 1

        if self.timeline_spec:
            entries = [(self._when(w), it) for w, it in self.timeline_spec]
            entries.sort(key=lambda e: e[0])
            specs = [it for _, it in entries]
            bounds = [f for f, _ in entries[1:]]
            seg_spec = specs
        else:
            specs = self.items_spec
            bounds = self._switch_frames() if len(specs) > 1 else []
            seg_spec = [specs[k % len(specs)] for k in range(len(bounds) + 1)]

        # one instance per distinct item, each a list of (style, opacity)
        self.items, index = [], {}
        for sp in dict.fromkeys(seg_spec):
            index[sp] = len(self.items)
            self.items.append([(STYLES[n](c, self.W, self.H, hud=False), op) for n, op in parse_layers(sp)])
        self.labels = list(index)
        seg_item = np.array([index[sp] for sp in seg_spec])

        nf = c.nf
        bounds = np.array(sorted(set(int(b) for b in bounds if 0 < b < nf)), dtype=int)
        seg = np.searchsorted(bounds, np.arange(nf), side="right")
        self.cur = seg_item[np.minimum(seg, len(seg_item) - 1)]
        self.nxt = self.cur.copy()
        self.mix = np.zeros(nf)
        L = 0 if self.transition == "cut" else int(round(self.fade_beats * spb * fps))
        for k, fb in enumerate(bounds):
            if L <= 0:
                break
            start = max(bounds[k - 1] if k else 0, fb - L)
            fr = np.arange(start, fb)
            self.nxt[fr] = seg_item[min(k + 1, len(seg_item) - 1)]
            self.mix[fr] = [ease((f - (fb - L)) / L) for f in fr]  # lands fully on the downbeat
        self.bounds = bounds

    def _snap(self, f: int) -> int:
        """Nearest bar line, so switches land on a downbeat."""
        if not len(self.bar_starts):
            return int(f)
        return int(self.bar_starts[np.argmin(np.abs(self.bar_starts - f))])

    def _when(self, w: str) -> int:
        c = self.c
        if w.lower().startswith("b"):  # bar number, as the HUD counts (1-based)
            n = int(w[1:]) - 1
            hits = np.nonzero(self.bar_f >= n)[0]
            return int(hits[0]) if len(hits) else c.nf
        secs = 0.0
        for part in w.split(":"):
            secs = secs * 60 + float(part)
        return self._snap(int(round(secs * c.fps)))

    def _switch_frames(self) -> list[int]:
        c, sw = self.c, (self.switch or "32")
        if sw in ("drops", "sections"):
            on = c.K >= 0.5
            change = np.nonzero(on[1:] != on[:-1])[0] + 1
            if sw == "drops":
                change = change[on[change]]
            return [self._snap(f) for f in change]
        n = int(sw)
        return [int(f) for f in self.bar_starts if self.bar_f[f] > 0 and self.bar_f[f] % n == 0]

    # -- drawing ---------------------------------------------------------
    def draw_item(self, ctx, f, item, weight):
        for i, (st, op) in enumerate(self.items[item]):
            ctx.push_group()
            st.draw(ctx, st.state(f))
            ctx.pop_group_to_source()
            ctx.set_operator(cairo.OPERATOR_OVER if i == 0 else self.blend)
            ctx.paint_with_alpha(op * weight)
        ctx.set_operator(cairo.OPERATOR_OVER)

    def draw(self, ctx, s):
        a, b, m = int(self.cur[s.f]), int(self.nxt[s.f]), float(self.mix[s.f])
        if m <= 0 or a == b:
            self.draw_item(ctx, s.f, a, 1.0)
        else:  # crossfade: old fades out, new screens in on top
            ctx.push_group(); self.draw_item(ctx, s.f, a, 1.0); ctx.pop_group_to_source()
            ctx.paint_with_alpha(1 - m)
            ctx.push_group(); self.draw_item(ctx, s.f, b, 1.0); ctx.pop_group_to_source()
            ctx.set_operator(cairo.OPERATOR_SCREEN); ctx.paint_with_alpha(m)
            ctx.set_operator(cairo.OPERATOR_OVER)
        label = self.labels[b if m >= 0.5 else a]
        self.layer_hud(ctx, s, f"   {label}")


def make_style(spec: str, ctl: Controls, width: int, height: int, hud: bool = True, timeline=None,
               switch=None, transition="fade", fade_beats=4.0, blend="screen") -> Style:
    """A plain style name gives that style; anything with + , @ or a timeline gives a Combo."""
    if is_simple(spec, timeline):
        if spec not in STYLES:
            raise ValueError(f"unknown style {spec!r}; `kickframe styles` lists them")
        return STYLES[spec](ctl, width, height, hud=hud)
    items = [it.strip() for it in spec.split(",") if it.strip()]
    for it in items:
        parse_layers(it)
    return Combo(ctl, width, height, hud=hud, items=items,
                 timeline=parse_timeline(timeline) if timeline else None,
                 switch=switch, transition=transition, fade_beats=fade_beats, blend=blend)
