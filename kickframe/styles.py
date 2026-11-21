"""Visual styles.

Every style draws in a virtual canvas 1080 units tall (width follows the aspect
ratio), so the same code renders 1920x1080, 3840x2160 or 1080x1920.
Colours, layers and parameters live here; add a style by subclassing Style
and registering it in STYLES.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import cairo
import numpy as np

from .analysis import Controls

TAU = 2 * math.pi
INK = (0.94, 0.94, 0.92)
RED = (1.0, 0.16, 0.16)
BG = (0.02, 0.02, 0.025)


def ease(x: float) -> float:
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def poly(ctx, n, r, rot, cx, cy):
    for j in range(n):
        a = rot + TAU * j / n - math.pi / 2
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        ctx.line_to(x, y) if j else ctx.move_to(x, y)
    ctx.close_path()


def stepped_rotation(c: Controls, step_deg=22.5) -> np.ndarray:
    """Rotation that advances step_deg per beat (eased) while the groove runs,
    and drifts slowly in breaks. Integrated once so chunks stay continuous."""
    nf = c.nf
    rot = np.zeros(nf)
    steps = drift = 0.0
    bidx = np.floor(c.beat).astype(int)
    prev_b, active_prev = bidx[0], False
    for i in range(nf):
        ph = c.beat[i] - bidx[i]
        active = c.K[i] > 0.5 and c.I[i] > 0.3
        if bidx[i] != prev_b:
            if active_prev:
                steps += 1
            prev_b = bidx[i]
        if not active:
            drift += 0.004 * (0.3 + c.mid[i])
        e = 1 - (1 - min(ph * 4, 1)) ** 3 if active else 0.0
        rot[i] = math.radians(step_deg) * (steps + e) + drift
        active_prev = active
    return rot


class Style:
    name = "base"
    peak_threshold = 0.72

    def __init__(self, ctl: Controls, width: int, height: int, hud: bool = True):
        self.c = ctl
        self.W, self.H = width, height
        self.u = height / 1080.0
        self.VW, self.VH = width / self.u, 1080.0
        self.CX, self.CY = self.VW / 2, self.VH / 2
        self.hud = hud
        self.prepare()

    # -- override ------------------------------------------------------
    def prepare(self):
        pass

    def draw(self, ctx, s):
        raise NotImplementedError

    # -- plumbing ------------------------------------------------------
    def state(self, f: int) -> SimpleNamespace:
        c = self.c
        beat = float(c.beat[f])
        b = math.floor(beat)
        ph = beat - b
        K = float(c.K[f])
        I = float(c.I[f])
        return SimpleNamespace(
            f=f, t=f / c.fps, I=I, K=K, flash=float(c.flash[f]), hat=float(c.hat[f]),
            bass=float(c.bass[f]), mid=float(c.mid[f]), fade=float(c.fade[f]),
            beat=beat, b=b, ph=ph, bib=(b - c.bar_shift) % 4, bar=max((b - c.bar_shift) // 4, 0),
            kick=math.exp(-ph * 6) * K, peak=I > self.peak_threshold and K > 0.5,
            pk=min(1.0, max(0.0, (I - self.peak_threshold) / 0.1)) if K > 0.5 else 0.0,
            six=math.exp(-((beat * 4) % 1.0) * 18))

    def frame(self, f: int) -> cairo.ImageSurface:
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.W, self.H)
        ctx = cairo.Context(surf)
        ctx.scale(self.u, self.u)
        ctx.set_source_rgb(*BG)
        ctx.paint()
        s = self.state(f)
        ctx.push_group()
        self.draw(ctx, s)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(s.fade)
        return surf

    # -- shared layers -------------------------------------------------
    def layer_flash(self, ctx, s, amount=0.6):
        if s.flash > 0:
            ctx.set_source_rgba(*INK, amount * s.flash)
            ctx.paint()

    def layer_grid(self, ctx, s, kind="square", scroll=0.0, alpha=None):
        a = alpha if alpha is not None else (0.03 + 0.05 * s.I) * (0.6 + 0.4 * s.kick + 0.4 * (1 - s.K))
        ctx.set_line_width(1)
        ctx.set_source_rgba(*INK, a)
        if kind == "square":
            sp = 120
            x = (self.CX % sp) - sp + scroll * sp
            while x < self.VW + sp:
                ctx.move_to(x, 0); ctx.line_to(x, self.VH); x += sp
            y = (self.CY % sp) - sp
            while y < self.VH + sp:
                ctx.move_to(0, y); ctx.line_to(self.VW, y); y += sp
        else:
            sp = 140
            h = sp * math.sqrt(3) / 2
            y = (self.CY % h) - h
            while y < self.VH + h:
                ctx.move_to(0, y); ctx.line_to(self.VW, y); y += h
            reach = self.VW + self.VH
            for ang in (math.pi / 3, 2 * math.pi / 3):
                dx, dy = math.cos(ang), math.sin(ang)
                for i in range(-int(reach / sp) - 2, int(reach / sp) + 2):
                    x0 = self.CX + i * sp + scroll * sp
                    ctx.move_to(x0 - dx * reach, self.CY - dy * reach)
                    ctx.line_to(x0 + dx * reach, self.CY + dy * reach)
        ctx.stroke()

    def layer_sweep(self, ctx, s, amount):
        for i in range(3):
            yy = (ease(s.ph) * self.VH * 1.2 + i * 70) - 140
            ctx.set_source_rgba(*INK, 0.10 * (1 - s.ph) * amount)
            ctx.rectangle(0, yy, self.VW, 18 - i * 5)
            ctx.fill()
        if s.hat > 0.5:
            ctx.set_source_rgba(*INK, 0.03 * s.six * amount)
            ctx.paint()

    def layer_ripples(self, ctx, s):
        if s.K <= 0.3:
            return
        for back in (0, 1):
            p = s.ph + back
            a = 0.22 * (1 - p / 2) * s.K
            if a > 0:
                ctx.set_line_width(1.5)
                ctx.set_source_rgba(*INK, a)
                ctx.arc(self.CX, self.CY, 60 + ease(p / 2) * 950, 0, TAU)
                ctx.stroke()

    def layer_lissajous(self, ctx, s, a, b, amount):
        delta = s.beat * 0.125 * math.pi
        ctx.set_line_width(1.2)
        ctx.set_source_rgba(*INK, (0.08 + 0.12 * s.bass) * amount)
        for j in range(721):
            t = TAU * j / 720
            x = self.CX + 840 * math.sin(a * t + delta)
            y = self.CY + 470 * math.sin(b * t)
            ctx.line_to(x, y) if j else ctx.move_to(x, y)
        ctx.stroke()

    def layer_rose(self, ctx, s, rot):
        kk = 5 + 2 * math.sin(s.t * 0.15)
        R = 420 * (0.9 + 0.15 * s.mid)
        ctx.set_line_width(1.2)
        ctx.set_source_rgba(*INK, 0.15 + 0.3 * s.mid)
        for j in range(1441):
            th = 2 * TAU * j / 1440
            r = R * math.cos(kk * th)
            x, y = self.CX + r * math.cos(th + rot), self.CY + r * math.sin(th + rot)
            ctx.line_to(x, y) if j else ctx.move_to(x, y)
        ctx.stroke()

    def layer_ticks(self, ctx, s, rot, R=500, count=None):
        n = count or (64 if s.I > 0.55 else 32)
        ctx.set_line_width(2)
        for i in range(n):
            a = TAU * i / n + rot * 0.25
            ln = 8 + 26 * s.hat
            ctx.set_source_rgba(*INK, 0.12 + 0.75 * s.hat)
            ctx.move_to(self.CX + math.cos(a) * R, self.CY + math.sin(a) * R)
            ctx.line_to(self.CX + math.cos(a) * (R + ln), self.CY + math.sin(a) * (R + ln))
            ctx.stroke()

    def layer_brackets(self, ctx, s, accent):
        m, L = 40, 46
        ctx.set_line_width(2)
        ctx.set_source_rgba(*accent, 0.35 + 0.5 * (s.kick if s.bib == 0 else 0))
        for (x, y, sx, sy) in ((m, m, 1, 1), (self.VW - m, m, -1, 1), (m, self.VH - m, 1, -1),
                               (self.VW - m, self.VH - m, -1, -1)):
            ctx.move_to(x, y + sy * L); ctx.line_to(x, y); ctx.line_to(x + sx * L, y)
        ctx.stroke()

    def layer_hud(self, ctx, s, extra=""):
        if not self.hud:
            return
        ctx.select_font_face("monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(20)
        ctx.set_source_rgba(*INK, 0.55)
        ctx.move_to(80, self.VH - 80)
        ctx.show_text(f"{self.c.bpm:.0f} BPM   {s.bar + 1:03d}.{s.bib + 1}{extra}")
        if s.K < 0.5:
            label = "BREAKDOWN" if s.t < self.c.duration * 0.9 else "OUTRO"
        elif s.I < 0.3:
            label = "INTRO" if s.t < self.c.duration * 0.1 else "GROOVE"
        else:
            label = "PEAK" if s.peak else "GROOVE"
        te = ctx.text_extents(label)
        ctx.move_to(self.VW - 80 - te.x_advance, self.VH - 80)
        ctx.show_text(label)
        ctx.set_source_rgba(*INK, 0.15)
        ctx.rectangle(self.VW - 280, self.VH - 120, 200, 4); ctx.fill()
        ctx.set_source_rgba(*(RED if s.peak else INK), 0.7)
        ctx.rectangle(self.VW - 280, self.VH - 120, 200 * s.I, 4); ctx.fill()
        for i in range(4):
            on = i == s.bib and s.K > 0.5
            ctx.set_source_rgba(*(RED if (on and s.peak) else INK), 0.8 if on else 0.15)
            ctx.rectangle(80 + i * 22, self.VH - 120, 14, 14); ctx.fill()


# ---------------------------------------------------------------------------
class Bold(Style):
    """Nested squares stepping 22.5 deg per beat, strobe grid, red downbeats."""
    name = "bold"

    def prepare(self):
        self.rot = stepped_rotation(self.c)

    def draw(self, ctx, s):
        rot = self.rot[s.f]
        accent = RED if (s.peak and s.bib == 0) else INK
        self.layer_flash(ctx, s)
        self.layer_grid(ctx, s, "square", scroll=(s.beat * 0.25) % 1.0 if s.peak else 0.0)
        if s.pk > 0:
            self.layer_sweep(ctx, s, s.pk)
        n_f = 3 + 9 * s.I
        n = int(math.ceil(n_f))
        breath = 1 + 0.06 * s.mid * (1 - s.K)
        for i in range(n):
            vis = min(1.0, n_f - i + 1) if i >= 3 else 1.0
            k = math.exp(-max(s.ph - i * 0.035, 0) * 7) * s.K
            size = (90 + i * 72) * (1 + 0.10 * k) * breath
            alpha = (0.22 + 0.25 * (1 - s.K) * s.mid + 0.6 * k) * vis
            r = rot * (1 if i % 2 == 0 else -1) if s.I > 0.5 else rot
            col = INK
            if s.peak and s.bib == 0 and i == n - 1:
                col, alpha = RED, 0.4 + 0.6 * s.kick
            ctx.set_line_width(1.2 + 2.0 * k + 1.5 * s.bass)
            ctx.set_source_rgba(*col, alpha)
            poly(ctx, 4, size / math.sqrt(2), r + math.pi / 4, self.CX, self.CY)
            ctx.stroke()
        c = 14 + 30 * s.kick + 10 * s.bass
        ctx.set_source_rgba(*accent, 0.45 + 0.55 * s.kick)
        poly(ctx, 4, c / math.sqrt(2), rot + math.pi / 4, self.CX, self.CY)
        ctx.fill()
        self.layer_ticks(ctx, s, rot)
        self.layer_hud(ctx, s)


class Geometric(Style):
    """Morphing n-gons (sides change every 16 bars), ripples, spokes,
    Lissajous in peaks, rose curve in breaks, orbiting triangles/squares."""
    name = "geometric"
    SIDES = [4, 3, 6, 5, 8, 3, 4, 6]
    LISS = [(3, 2), (5, 4), (3, 4), (5, 6)]
    max_layers = 12
    orbiters = True

    def prepare(self):
        self.rot = stepped_rotation(self.c)

    def polygons(self, ctx, s, rot, phrase, bar_in_phrase, alpha_scale=1.0, base0=45, step=36):
        n_cur = self.SIDES[phrase % len(self.SIDES)]
        n_prev = self.SIDES[(phrase - 1) % len(self.SIDES)]
        mix = ease((s.bib + s.ph) / 4) if bar_in_phrase == 0 and phrase > 0 else 1.0
        n_f = 3 + (self.max_layers - 3) * s.I
        count = int(math.ceil(n_f))
        for sides, wgt in ((n_cur, mix), (n_prev, 1 - mix)):
            if wgt <= 0.01:
                continue
            circ = 1 / math.cos(math.pi / sides)
            for i in range(count):
                vis = min(1.0, n_f - i + 1) if i >= 3 else 1.0
                base = (base0 + i * step) * circ ** 0.55 * (1.12 if sides == 4 else 1.0)
                k = math.exp(-max(s.ph - i * 0.035, 0) * 7) * s.K
                r = base * (1 + 0.10 * k) * (1 + 0.06 * s.mid * (1 - s.K))
                alpha = (0.22 + 0.25 * (1 - s.K) * s.mid + 0.6 * k) * vis * wgt * alpha_scale
                rr = rot * (1 if i % 2 == 0 else -1) if s.I > 0.5 else rot
                col = INK
                if s.peak and s.bib == 0 and i == count - 1:
                    col, alpha = RED, (0.4 + 0.6 * s.kick) * wgt
                ctx.set_line_width((1.2 + 2.0 * k + 1.5 * s.bass) * (0.8 if alpha_scale < 1 else 1))
                ctx.set_source_rgba(*col, min(alpha, 1.0))
                poly(ctx, sides, r, rr + (math.pi / 4 if sides == 4 else 0), self.CX, self.CY)
                ctx.stroke()
        return n_cur

    def background(self, ctx, s, rot, phrase):
        self.layer_flash(ctx, s)
        self.layer_grid(ctx, s, "tri" if phrase % 2 else "square",
                        scroll=(s.beat * 0.25) % 1.0 if s.peak else 0.0)
        self.layer_ripples(ctx, s)
        if s.pk > 0:
            self.layer_sweep(ctx, s, s.pk)
            a, b = self.LISS[phrase % len(self.LISS)]
            self.layer_lissajous(ctx, s, a, b, s.pk)
        if s.K < 0.5:
            self.layer_rose(ctx, s, rot)

    def draw(self, ctx, s):
        rot = self.rot[s.f]
        phrase, bip = s.bar // 16, s.bar % 16
        accent = RED if (s.peak and s.bib == 0) else INK
        self.background(ctx, s, rot, phrase)
        n_cur = self.polygons(ctx, s, rot, phrase, bip)
        if s.I > 0.4:  # spokes
            a_sp = min(1.0, (s.I - 0.4) / 0.15)
            ns = n_cur * 2
            ctx.set_line_width(1)
            for j in range(ns):
                a = -rot * 0.5 + TAU * j / ns
                L = 150 + 120 * s.kick
                ctx.set_source_rgba(*INK, (0.08 + 0.3 * s.kick) * a_sp)
                ctx.move_to(self.CX + 70 * math.cos(a), self.CY + 70 * math.sin(a))
                ctx.line_to(self.CX + L * math.cos(a), self.CY + L * math.sin(a))
                ctx.stroke()
        if self.orbiters:
            orbits = [(330, 0.42, 5, 1, 1), (560, 0.5, 7, 2, -1), (760, 0.56, 9, 1, 1)]
            for oi, (R, sq, m, shape, d) in enumerate(orbits[:1 + int(round(2 * s.I))]):
                tilt = 0.25 * (oi - 1)
                ctx.set_line_width(1)
                ctx.set_source_rgba(*INK, 0.07 + 0.05 * s.I)
                ctx.save(); ctx.translate(self.CX, self.CY); ctx.rotate(tilt); ctx.scale(1, sq)
                ctx.arc(0, 0, R, 0, TAU); ctx.restore(); ctx.stroke()
                for j in range(m):
                    a = d * rot * (0.5 + 0.2 * oi) + TAU * j / m
                    ex, ey = R * math.cos(a), R * sq * math.sin(a)
                    x = self.CX + ex * math.cos(tilt) - ey * math.sin(tilt)
                    y = self.CY + ex * math.sin(tilt) + ey * math.cos(tilt)
                    depth = 0.55 + 0.45 * math.sin(a)
                    sz = (7 + 7 * s.kick) * (0.7 + 0.6 * depth)
                    ctx.set_source_rgba(*(accent if j == 0 else INK), 0.3 + 0.6 * depth * (0.5 + 0.5 * s.kick))
                    poly(ctx, 3 if shape == 1 else 4, sz, rot * 2 + j, x, y)
                    ctx.set_line_width(1.5); ctx.stroke()
        c = 12 + 26 * s.kick + 8 * s.bass
        ctx.set_source_rgba(*accent, 0.45 + 0.55 * s.kick)
        poly(ctx, n_cur, c * 0.7, rot, self.CX, self.CY); ctx.fill()
        self.layer_ticks(ctx, s, rot)
        self.layer_brackets(ctx, s, accent)
        self.layer_hud(ctx, s, f"   n={n_cur}")


class Atom(Geometric):
    """Geometric base plus electron shells with comet-trail electrons and a
    phyllotaxis nucleus; polygons thinned so the atom reads on top."""
    name = "atom"
    max_layers = 9

    def draw(self, ctx, s):
        rot = self.rot[s.f]
        phrase, bip = s.bar // 16, s.bar % 16
        accent = RED if (s.peak and s.bib == 0) else INK
        self.background(ctx, s, rot, phrase)
        n_cur = self.polygons(ctx, s, rot, phrase, bip, alpha_scale=0.75, base0=85, step=40)
        order = [0, 3, 1, 4, 2, 5]
        n_sh = 2 + 4 * s.I
        prec = s.t * 0.05 + rot * 0.15
        for idx in range(6):
            vis = min(1.0, n_sh - idx) if idx >= 2 else 1.0
            if vis <= 0:
                continue
            k = order[idx]
            tilt = prec + k * math.pi / 6
            A = 580 * (1 + 0.04 * s.kick)
            B = A * 0.28
            ct, st = math.cos(tilt), math.sin(tilt)
            ctx.save(); ctx.translate(self.CX, self.CY); ctx.rotate(tilt); ctx.scale(1, 0.28)
            ctx.arc(0, 0, A, 0, TAU); ctx.restore()
            ctx.set_line_width(1.3)
            ctx.set_source_rgba(*INK, (0.28 + 0.15 * s.I + 0.3 * s.kick) * vis)
            ctx.stroke()
            speed = [1.0, 0.75, 1.5, 0.5, 1.25, 2.0][k]
            dirn = 1 if k % 2 == 0 else -1
            a0 = dirn * s.beat * TAU / 4 * speed + k * 1.1
            segs = 28
            for j in range(segs):
                a1 = a0 - dirn * 1.4 * j / segs
                a2 = a0 - dirn * 1.4 * (j + 1) / segs
                pts = [(self.CX + A * math.cos(a) * ct - B * math.sin(a) * st,
                        self.CY + A * math.cos(a) * st + B * math.sin(a) * ct) for a in (a1, a2)]
                fadeT = (1 - j / segs) ** 2
                depth = 0.6 + 0.4 * math.sin(a1)
                ctx.set_line_width((1.5 + 5.0 * fadeT) * (0.7 + 0.5 * depth))
                col = RED if (s.peak and s.bib == 0 and idx == 0) else INK
                ctx.set_source_rgba(*col, min(1.0, 1.1 * fadeT) * vis * depth)
                ctx.move_to(*pts[0]); ctx.line_to(*pts[1]); ctx.stroke()
        nuc = 7 + int(round(12 * s.I))
        r0 = 12 + 5 * s.kick + 4 * s.bass
        for j in range(nuc):
            rad = r0 * 1.25 * math.sqrt(j + 0.5)
            ang = j * 2.39996 + rot * 0.6
            ctx.set_line_width(1.5)
            ctx.set_source_rgba(*(accent if j % 2 == 0 else INK), 0.45 + 0.5 * s.kick)
            ctx.arc(self.CX + rad * math.cos(ang), self.CY + rad * math.sin(ang), r0 * 0.62, 0, TAU)
            ctx.stroke()
        self.layer_ticks(ctx, s, rot)
        self.layer_brackets(ctx, s, accent)
        self.layer_hud(ctx, s, f"   n={n_cur}")


class Tunnel(Style):
    """The n-gon spiral as an endless tunnel: layers are born at the centre as
    triangles and flow outward through squares, pentagons, hexagons, octagons."""
    name = "tunnel"
    SEQ = [3, 4, 5, 6, 8]
    SP, R0, NL, RING = 12.5, 40.0, 62, 535.0
    red_every = 24

    def prepare(self):
        c = self.c
        self.pos = np.zeros(c.nf)
        self.spin = np.zeros(c.nf)
        p = sp = 0.0
        bps = c.bpm / 60.0
        for f in range(c.nf):
            ph = c.beat[f] % 1.0
            if c.K[f] > 0.5:
                v = (0.35 + 0.9 * c.I[f]) * (0.35 + 1.6 * math.exp(-ph * 4))  # surge on each kick
            else:
                v = 0.12 + 0.2 * c.mid[f]
            p += v / c.fps * bps * 0.8
            sp += (0.0015 + 0.004 * c.I[f]) * (1 if c.K[f] > 0.5 else 0.4)
            self.pos[f], self.spin[f] = p, sp

    def draw(self, ctx, s):
        pos, spin = self.pos[s.f], self.spin[s.f]
        twist = 0.045 + 0.05 * s.I + 0.02 * s.mid * (1 - s.K)
        self.layer_flash(ctx, s, 0.5)
        self.layer_grid(ctx, s, "square", alpha=0.03 + 0.03 * s.I)
        base = math.floor(pos)
        frac = pos - base
        for k in range(self.NL, -1, -1):
            u = k + frac
            g = int(base) - k
            r = self.R0 + u * self.SP
            n = self.SEQ[min(len(self.SEQ) - 1, int(u * len(self.SEQ) / 40))]
            kp = math.exp(-max(s.ph - u * 0.012, 0) * 6) * s.K
            r *= 1 + 0.03 * kp
            if u < 40:
                a = 0.14 + 0.5 * (u / 40)
            else:
                a = 0.6 * max(0.0, 1 - (u - 40) / (self.NL - 40)) * 0.45
            a *= min(1.0, u / 2.5)
            a = min(1.0, a + 0.22 * kp)
            col = INK
            if self.red_every and g % self.red_every == 0:
                col = RED
                a = min(1.0, 0.55 + 0.35 * s.I + 0.3 * kp) * min(1.0, u / 2.5)
            ctx.set_line_width(1.3 + 1.6 * kp + 0.8 * s.bass)
            ctx.set_source_rgba(*col, a)
            poly(ctx, n, r / math.cos(math.pi / n) ** 0.5, g * twist + spin, self.CX, self.CY)
            ctx.stroke()
        ctx.set_line_width(2)
        for i in range(96):
            t = TAU * i / 96 + spin * 0.2
            ln = 10 + 22 * s.hat + (8 * s.kick if i % 8 == 0 else 0)
            ctx.set_source_rgba(*INK, 0.25 + 0.6 * s.hat)
            ctx.move_to(self.CX + self.RING * math.cos(t), self.CY + self.RING * math.sin(t))
            ctx.line_to(self.CX + (self.RING + ln) * math.cos(t), self.CY + (self.RING + ln) * math.sin(t))
        ctx.stroke()
        g2 = cairo.RadialGradient(self.CX, self.CY, 380, self.CX, self.CY, 1150)
        g2.add_color_stop_rgba(0, 0, 0, 0, 0)
        g2.add_color_stop_rgba(1, 0, 0, 0, 0.6)
        ctx.set_source(g2); ctx.paint()
        self.layer_hud(ctx, s)


class Subtle(Style):
    """Four thin squares, slow continuous rotation, soft breath on the kick."""
    name = "subtle"

    def prepare(self):
        self.rot = np.cumsum(0.0012 + 0.0028 * self.c.I)
        rng = np.random.default_rng(7)
        self.dust = [(rng.uniform(0, self.VW), rng.uniform(0, self.VH), rng.uniform(0.3, 1.0),
                      rng.uniform(0, TAU)) for _ in range(70)]

    def draw(self, ctx, s):
        rot = self.rot[s.f]
        ink = (0.86, 0.85, 0.82)
        breath = min(1.0, s.ph / 0.08) * math.exp(-s.ph * 3.0) * s.K
        swell = 1 + 0.8 * s.flash
        for (x, y, sz, p) in self.dust:
            yy = (y - s.t * 6 * sz) % self.VH
            a = (0.03 + 0.08 * s.mid) * (0.5 + 0.5 * math.sin(s.t * 0.4 + p)) * sz
            ctx.set_source_rgba(*ink, a)
            ctx.arc(x, yy, 1.2 * sz, 0, TAU); ctx.fill()
        half = 160 + 520 * s.I
        ctx.set_line_width(1)
        ctx.set_source_rgba(*ink, (0.04 + 0.12 * s.hat) * swell)
        ctx.move_to(self.CX - half, self.CY); ctx.line_to(self.CX + half, self.CY); ctx.stroke()
        for i, base in enumerate([200, 340, 500, 680]):
            d = max(s.ph - i * 0.06, 0)
            b = min(1.0, d / 0.08) * math.exp(-d * 3.0) * s.K
            size = base * (1 + 0.025 * b) * (1 + 0.03 * s.mid * (1 - s.K))
            presence = min(1.0, max(0.0, (s.I * 4 + 1) - i))
            a = (0.15 + 0.12 * s.I + 0.14 * b) * presence * swell
            r = rot * (1 + 0.35 * i) * (1 if i % 2 == 0 else -1)
            ctx.set_line_width(1.0 + 0.6 * s.bass)
            ctx.set_source_rgba(*ink, min(a, 0.6))
            poly(ctx, 4, size / math.sqrt(2), r + math.pi / 4, self.CX, self.CY); ctx.stroke()
        ctx.set_source_rgba(*ink, 0.25 + 0.35 * breath)
        ctx.arc(self.CX, self.CY, 2.5 + 2 * breath, 0, TAU); ctx.fill()
        g = cairo.RadialGradient(self.CX, self.CY, 300, self.CX, self.CY, 1150)
        g.add_color_stop_rgba(0, 0, 0, 0, 0)
        g.add_color_stop_rgba(1, 0, 0, 0, 0.55)
        ctx.set_source(g); ctx.paint()


def vignette(ctx, cx, cy, r0=380, r1=1150, a=0.6):
    g = cairo.RadialGradient(cx, cy, r0, cx, cy, r1)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0, 0, 0, a)
    ctx.set_source(g)
    ctx.paint()


class Horizon(Style):
    """Perspective floor rushing toward a polygon sun on the horizon; kicks surge the travel."""
    name = "horizon"
    SUN_SIDES = [8, 6, 12, 4]
    H_CAM = 300.0  # camera height: row at depth d sits H_CAM/d below the horizon

    def prepare(self):
        c = self.c
        bps = c.bpm / 60.0
        ph = c.beat % 1.0
        v = np.where(c.K > 0.5, (0.4 + 0.8 * c.I) * (0.4 + 1.4 * np.exp(-ph * 5)), 0.15 + 0.2 * c.mid)
        self.z = np.cumsum(v * bps / c.fps)  # distance travelled, in floor rows
        self.rot = np.cumsum(0.001 + 0.003 * c.I)

    def floor(self, ctx, s, HY, sign, amount):
        frac = self.z[s.f] % 1.0
        for k in range(1, 81):
            d = (k - frac) * 0.5
            y = HY + sign * self.H_CAM / d
            if not -10 < y < self.VH + 10:
                continue
            near = min(1.0, 2.0 / d)
            a = ((0.12 + 0.45 * s.I) * min(1.0, 4.0 / d) + 0.4 * s.kick * near) * amount
            ctx.set_line_width(1.0 + 1.2 * near * (0.5 + s.bass))
            ctx.set_source_rgba(*INK, min(a, 1.0))
            ctx.move_to(0, y); ctx.line_to(self.VW, y); ctx.stroke()
        y0 = HY + sign * self.H_CAM / 40
        y1 = self.VH if sign > 0 else 0
        sway = 70 * math.sin(s.t * 0.07)
        ctx.set_line_width(1.0)
        for j in range(-30, 31):
            ctx.set_source_rgba(*INK, (0.16 + 0.3 * s.I) * max(0.0, 1 - abs(j) / 30) * amount)
            xb = self.CX + j * 150 + sway
            ctx.move_to(self.CX + (xb - self.CX) * (y0 - HY) / (y1 - HY), y0)
            ctx.line_to(xb, y1)
            ctx.stroke()

    def draw(self, ctx, s):
        HY = self.CY + 60
        rot = self.rot[s.f]
        self.layer_flash(ctx, s, 0.5)
        self.floor(ctx, s, HY, 1, 1.0)
        # sun, setting behind the horizon
        n = self.SUN_SIDES[(s.bar // 16) % len(self.SUN_SIDES)]
        R = 230 * (1 + 0.05 * s.kick)
        sx, sy = self.CX, HY - 170
        if s.pk > 0:  # ceiling in peaks turns the floor into a corridor
            ctx.save()
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            ctx.rectangle(0, 0, self.VW, HY)
            poly(ctx, n, R * 1.08, rot, sx, sy)
            ctx.clip()
            ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
            self.floor(ctx, s, HY, -1, 0.45 * s.pk)
            ctx.restore()
        col = RED if s.peak else INK
        ctx.save()
        ctx.rectangle(0, 0, self.VW, HY); ctx.clip()
        ctx.set_line_width(2 + 1.5 * s.kick)
        ctx.set_source_rgba(*col, 0.55 + 0.45 * s.kick)
        poly(ctx, n, R, rot, sx, sy); ctx.stroke()
        poly(ctx, n, R, rot, sx, sy); ctx.clip()
        step = 16
        for i in range(-1, int(2 * R / step) + 2):
            y = sy - R + (i + s.ph) * step
            depth = (y - (sy - R)) / (2 * R)
            ctx.set_line_width(1.0 + 2.5 * depth)
            ctx.set_source_rgba(*col, 0.12 + 0.5 * depth * (0.5 + 0.5 * s.I))
            ctx.move_to(sx - R, y); ctx.line_to(sx + R, y); ctx.stroke()
        ctx.restore()
        if s.K < 0.5:  # breakdown: echoes drift out from the sun
            ctx.save(); ctx.rectangle(0, 0, self.VW, HY); ctx.clip()
            for i in range(4):
                e = (s.t * 0.15 + i / 4) % 1.0
                ctx.set_line_width(1)
                ctx.set_source_rgba(*INK, 0.35 * (1 - e) * (0.3 + s.mid) * (1 - s.K))
                poly(ctx, n, R * (1.1 + 1.4 * e), rot * (1 + i * 0.2), sx, sy); ctx.stroke()
            ctx.restore()
        # horizon line with hat ticks
        ctx.set_line_width(1.5)
        ctx.set_source_rgba(*INK, 0.7)
        ctx.move_to(0, HY); ctx.line_to(self.VW, HY); ctx.stroke()
        ctx.set_line_width(1.5)
        ctx.set_source_rgba(*INK, 0.2 + 0.6 * s.hat)
        x = self.CX % 48
        while x < self.VW:
            ctx.move_to(x, HY); ctx.line_to(x, HY - 4 - 16 * s.hat * (0.4 + 0.6 * math.sin(x * 0.05) ** 2))
            x += 48
        ctx.stroke()
        vignette(ctx, self.CX, self.CY, 420, 1200, 0.55)
        self.layer_hud(ctx, s)


class Scope(Style):
    """Radial oscilloscope: a closed trace shaped by bass, mids and hats, leaving fading echoes."""
    name = "scope"
    LOBES = [(3, 8, 24), (4, 10, 32), (5, 7, 28), (6, 12, 36)]  # bass, mid, hat lobes per phrase
    R0 = 250.0

    def prepare(self):
        self.rot = np.cumsum(0.002 + 0.006 * self.c.I)

    def trace(self, ctx, g, lobes, scale):
        st = self.state(g)
        rot = self.rot[g]
        nb, nm, nh = lobes
        base = self.R0 * (1 + 0.15 * st.kick)
        for j in range(361):
            th = TAU * j / 360
            r = (base + 80 * st.bass * math.sin(nb * th + rot) + 35 * st.mid * math.sin(nm * th - 1.7 * rot)
                 + 18 * st.hat * math.sin(nh * th + 3 * rot)) * scale
            x, y = self.CX + r * math.cos(th), self.CY + r * math.sin(th)
            ctx.line_to(x, y) if j else ctx.move_to(x, y)
        ctx.close_path()

    def draw(self, ctx, s):
        lobes = self.LOBES[(s.bar // 16) % len(self.LOBES)]
        self.layer_flash(ctx, s, 0.5)
        # graticule
        ctx.set_line_width(1)
        ctx.set_source_rgba(*INK, 0.06 + 0.04 * s.I)
        for r in range(100, 1100, 100):
            ctx.new_sub_path(); ctx.arc(self.CX, self.CY, r, 0, TAU)
        ctx.move_to(0, self.CY); ctx.line_to(self.VW, self.CY)
        ctx.move_to(self.CX, 0); ctx.line_to(self.CX, self.VH)
        ctx.stroke()
        if s.pk > 0:
            a, b = Geometric.LISS[(s.bar // 16) % len(Geometric.LISS)]
            self.layer_lissajous(ctx, s, a, b, s.pk)
        n_echo = 3 + int(9 * s.I)
        for k in range(n_echo, 0, -1):
            ctx.set_line_width(1.2)
            ctx.set_source_rgba(*INK, 0.4 * (1 - k / (n_echo + 1)) ** 1.5 * (0.4 + 0.6 * s.I))
            self.trace(ctx, max(0, s.f - 2 * k), lobes, 1 + 0.045 * k)
            ctx.stroke()
        red = s.peak and s.bib == 0
        ctx.set_line_width(1.8 + 2.0 * s.kick + s.bass)
        ctx.set_source_rgba(*(RED if red else INK), 0.6 + 0.4 * s.kick)
        self.trace(ctx, s.f, lobes, 1.0)
        ctx.stroke()
        self.layer_ticks(ctx, s, self.rot[s.f], R=490)
        self.layer_brackets(ctx, s, RED if red else INK)
        self.layer_hud(ctx, s, f"   {lobes[0]}:{lobes[1]}:{lobes[2]}")


class Field(Style):
    """A lattice of crosses; every kick sends a wave from the centre that lifts and turns them."""
    name = "field"
    SP = 60.0

    def prepare(self):
        self.rot = np.cumsum(0.0008 + 0.002 * self.c.I)
        nx, ny = int(self.VW / self.SP / 2) + 1, int(self.VH / self.SP / 2) + 1
        ii, jj = np.meshgrid(np.arange(-nx, nx + 1), np.arange(-ny, ny + 1))
        self.ii, self.jj = ii.ravel(), jj.ravel()
        self.gx = self.CX + self.ii * self.SP
        self.gy = self.CY + self.jj * self.SP
        self.d = np.hypot(self.gx - self.CX, self.gy - self.CY)

    def draw(self, ctx, s):
        d = self.d
        w = np.zeros_like(d)
        if s.K > 0.3:
            for back in (0, 1):  # this beat's wave and the last one, still travelling
                p = s.ph + back
                w += s.K * (1 - p / 2) ** 1.5 * np.exp(-((d - (40 + p * 620)) / 70) ** 2)
        w += (1 - s.K) * 0.35 * s.mid * (0.5 + 0.5 * np.sin(d / 90 - s.t * 1.8))
        reach = 250 + 1100 * s.I
        vis = 0.25 + 0.75 * np.clip((reach - d) / 150, 0, 1)
        alpha = np.minimum((0.2 + 0.25 * s.I) * vis + 0.7 * w, 1.0)
        size = 8 + 14 * w + 3 * s.bass
        sixteenth = int(math.floor(s.beat * 4))
        spark = ((self.ii * 7919 + self.jj * 104729 + sixteenth * 1299709) % 997) / 997.0 < 0.06 * s.hat
        alpha = np.where(spark, 0.9, alpha)
        size = np.where(spark, size + 4, size)
        red = (w > 0.5) & (s.peak and s.bib == 0)
        ang = self.rot[s.f] + w * math.pi / 4
        self.layer_flash(ctx, s, 0.5)
        ctx.set_line_width(1.8 + 0.8 * s.bass)
        q = np.round(alpha * 20).astype(int)
        for is_red in (False, True):
            for level in np.unique(q[red == is_red]):
                sel = np.nonzero((q == level) & (red == is_red))[0]
                if level == 0 or len(sel) == 0:
                    continue
                ctx.set_source_rgba(*(RED if is_red else INK), level / 20)
                for i in sel:
                    x, y, r, a = self.gx[i], self.gy[i], size[i], ang[i]
                    c, sn = r * math.cos(a), r * math.sin(a)
                    ctx.move_to(x - c, y - sn); ctx.line_to(x + c, y + sn)
                    ctx.move_to(x + sn, y - c); ctx.line_to(x - sn, y + c)
                ctx.stroke()
        vignette(ctx, self.CX, self.CY, 450, 1200, 0.5)
        self.layer_brackets(ctx, s, RED if (s.peak and s.bib == 0) else INK)
        self.layer_hud(ctx, s)


class Sphere(Style):
    """Wireframe globe turning a step per beat; a scan line sweeps it on each kick, red equator in peaks."""
    name = "sphere"
    N = 96  # points per ring

    def prepare(self):
        self.yaw = stepped_rotation(self.c, 15)
        self.pitch = 0.35 + 0.2 * np.sin(np.cumsum(0.003 + 0.004 * self.c.I))

    def ring(self, ctx, pts, R, a_front, a_back, col, width):
        """pts: (N, 3) unit-sphere points after rotation; front half bright, back half dim."""
        x = self.CX + R * pts[:, 0]
        y = self.CY - R * pts[:, 1]
        z = pts[:, 2]
        for front, a in ((False, a_back), (True, a_front)):
            if a <= 0:
                continue
            for j in range(len(pts) - 1):
                if (z[j] + z[j + 1] >= 0) == front:
                    ctx.move_to(x[j], y[j]); ctx.line_to(x[j + 1], y[j + 1])
            ctx.set_line_width(width if front else 1.0)
            ctx.set_source_rgba(*col, min(a, 1.0))
            ctx.stroke()

    def view(self, p, yaw, pitch):
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        x, z = x * math.cos(yaw) + z * math.sin(yaw), -x * math.sin(yaw) + z * math.cos(yaw)
        y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
        return np.stack([x, y, z], 1)

    def draw(self, ctx, s):
        yaw, pitch = self.yaw[s.f], self.pitch[s.f]
        a = np.linspace(0, TAU, self.N + 1)
        R = 330 * (1 + 0.06 * s.kick) * (1 + 0.04 * s.mid * (1 - s.K))
        self.layer_flash(ctx, s, 0.5)
        self.layer_grid(ctx, s, "tri")
        self.layer_ripples(ctx, s)
        af = 0.25 + 0.3 * s.I + 0.35 * s.kick
        ab = 0.07 + 0.06 * s.I
        lw = 1.2 + 1.2 * s.kick + 0.8 * s.bass
        m = 2 * int(round(3 + 6 * s.I))
        for k in range(m):  # meridians: great circles through the poles
            lon = math.pi * k / m
            p = np.stack([np.cos(a) * math.sin(lon), np.sin(a), np.cos(a) * math.cos(lon)], 1)
            self.ring(ctx, self.view(p, yaw, pitch), R, af, ab, INK, lw)
        n_par = 3 + 2 * int(round(2 * s.I))
        for j in range(1, n_par + 1):  # parallels; the middle one is the equator
            lat = math.pi * j / (n_par + 1) - math.pi / 2
            p = np.stack([math.cos(lat) * np.sin(a), np.full_like(a, math.sin(lat)), math.cos(lat) * np.cos(a)], 1)
            eq = j == (n_par + 1) // 2 and s.peak
            self.ring(ctx, self.view(p, yaw, pitch), R, 0.8 if eq else af, ab, RED if eq else INK,
                      lw + (1 if eq else 0))
        if s.K > 0.3:  # scan line from pole to pole on every beat
            lat = math.pi / 2 - ease(s.ph) * math.pi
            p = np.stack([math.cos(lat) * np.sin(a), np.full_like(a, math.sin(lat)), math.cos(lat) * np.cos(a)], 1)
            self.ring(ctx, self.view(p, yaw, pitch), R * 1.01, 0.9 * s.kick + 0.2, 0.1, INK, 2.5)
        if s.I > 0.5:  # tilted orbit with three markers
            ao = min(1.0, (s.I - 0.5) / 0.15)
            p = np.stack([1.45 * np.cos(a), np.zeros_like(a), 1.45 * np.sin(a)], 1)
            tilt = 1.1
            p = np.stack([p[:, 0], -p[:, 2] * math.sin(tilt), p[:, 2] * math.cos(tilt)], 1)
            q = self.view(p, -yaw * 0.5, pitch)
            self.ring(ctx, q, R, 0.4 * ao, 0.12 * ao, INK, 1.2)
            for i in range(3):
                idx = int((s.beat / 8 + i / 3) % 1.0 * self.N)
                x, y = self.CX + R * q[idx, 0], self.CY - R * q[idx, 1]
                ctx.set_line_width(1.5)
                ctx.set_source_rgba(*(RED if (i == 0 and s.peak) else INK), (0.4 + 0.6 * (q[idx, 2] > 0)) * ao)
                poly(ctx, 3, 10 + 6 * s.kick, yaw * 2 + i, x, y); ctx.stroke()
        self.layer_ticks(ctx, s, yaw, R=520)
        self.layer_brackets(ctx, s, RED if (s.peak and s.bib == 0) else INK)
        self.layer_hud(ctx, s, f"   {m}x{n_par}")


class Moire(Style):
    """Two sets of concentric rings that slide apart on every kick; their interference blooms into moire."""
    name = "moire"
    SP = 16.0

    def prepare(self):
        self.rot = np.cumsum(0.0015 + 0.004 * self.c.I)

    def rings(self, ctx, cx, cy, rmax, alpha, sides=0, rot=0.0):
        ctx.set_line_width(1.5)
        groups = {}  # rings sharing an alpha level go into one stroke
        for i in range(1, int(1200 / self.SP) + 1):
            r = i * self.SP
            lvl = round(alpha * min(1.0, max(0.0, (rmax - r) / 200)) * 40)
            if lvl > 0:
                groups.setdefault(lvl, []).append(r)
        for lvl, radii in groups.items():
            for r in radii:
                if sides:
                    poly(ctx, sides, r, rot, cx, cy)
                else:
                    ctx.new_sub_path(); ctx.arc(cx, cy, r, 0, TAU)
            ctx.set_source_rgba(*INK, lvl / 40)
            ctx.stroke()

    def draw(self, ctx, s):
        rot = self.rot[s.f]
        if s.K > 0.5:
            off = 18 + 70 * s.I + 55 * s.kick
        else:
            off = 18 + 50 * s.mid * (0.5 + 0.5 * math.sin(s.t * 0.4))
        dx, dy = off * math.cos(rot), off * math.sin(rot)
        rmax = 380 + 850 * s.I
        self.layer_flash(ctx, s, 0.5)
        self.rings(ctx, self.CX + dx, self.CY + dy, rmax, 0.5)
        b_alpha = 0.42 + 0.2 * s.hat
        if s.K > 0.02:
            self.rings(ctx, self.CX - dx, self.CY - dy, rmax, b_alpha * s.K)
        if s.K < 0.98:  # breakdown: the second set turns into slowly rotating hexagons
            self.rings(ctx, self.CX - dx, self.CY - dy, rmax, b_alpha * (1 - s.K), sides=6, rot=-rot * 2)
        if s.pk > 0:  # red wavefront on every kick in peaks
            ctx.set_line_width(2.5)
            ctx.set_source_rgba(*RED, (1 - s.ph) * s.pk)
            ctx.new_sub_path(); ctx.arc(self.CX, self.CY, 40 + ease(s.ph) * 900, 0, TAU); ctx.stroke()
        vignette(ctx, self.CX, self.CY, 350, 1150, 0.65)
        self.layer_hud(ctx, s)


# -- fractals ----------------------------------------------------------------
def tree_levels(cx, cy, arms, depth, length, ratio, spread, rot, r0=0.0, asym=0.0, grow=None):
    """Radial binary tree: `arms` trunks from the centre, each forking in two per level.
    spread: branch half-angle, a number or one value per level; grow: optional length factor per level.
    Returns one (N, 4) array of segments (x0, y0, x1, y1) per level."""
    a = rot + TAU * np.arange(arms) / arms
    x, y = cx + r0 * np.cos(a), cy + r0 * np.sin(a)
    out, L = [], length
    for lvl in range(depth):
        g = 1.0 if grow is None else grow[lvl]
        x1, y1 = x + L * g * np.cos(a), y + L * g * np.sin(a)
        out.append(np.stack([x, y, x1, y1], 1))
        sp = spread[lvl] if np.ndim(spread) else spread
        a = np.concatenate([a - sp * (1 + asym), a + sp * (1 - asym)])
        x, y = np.concatenate([x1, x1]), np.concatenate([y1, y1])
        L *= ratio
    return out


def sierpinski_holes(tris, min_size=0.0, bounds=None, max_depth=12):
    """Subdivide (N, 3, 2) triangles Sierpinski-style. Returns [(holes (M, 3, 2), edge length)] per
    level: each level adds only its inverted middle triangles, so drawing all levels plus the outer
    triangles gives the whole fractal. bounds=(x0, y0, x1, y1) culls triangles outside the view."""
    out = []
    size = float(np.linalg.norm(tris[0, 1] - tris[0, 0]))
    for _ in range(max_depth):
        if not len(tris) or size / 2 < min_size:
            break
        v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
        m01, m12, m20 = (v0 + v1) / 2, (v1 + v2) / 2, (v2 + v0) / 2
        out.append((np.stack([m01, m12, m20], 1), size / 2))
        tris = np.concatenate([np.stack([v0, m01, m20], 1), np.stack([m01, v1, m12], 1),
                               np.stack([m20, m12, v2], 1)])
        size /= 2
        if bounds is not None:
            mn, mx = tris.min(1), tris.max(1)
            tris = tris[(mx[:, 0] >= bounds[0]) & (mn[:, 0] <= bounds[2]) &
                        (mx[:, 1] >= bounds[1]) & (mn[:, 1] <= bounds[3])]
    return out


def path_segments(ctx, seg):
    for x0, y0, x1, y1 in seg.tolist():
        ctx.move_to(x0, y0); ctx.line_to(x1, y1)


def path_triangles(ctx, tris):
    for (ax, ay), (bx, by), (cx, cy) in tris.tolist():
        ctx.move_to(ax, ay); ctx.line_to(bx, by); ctx.line_to(cx, cy); ctx.close_path()


class Branches(Style):
    """Radial fractal tree: arms fork level by level, growing generations with intensity; kicks pulse outward."""
    name = "branches"
    ARMS = [6, 3, 4, 5]
    RATIO = 0.7
    L0 = 140.0

    def prepare(self):
        self.rot = np.cumsum(0.0012 + 0.003 * self.c.I)

    def draw(self, ctx, s):
        rot = self.rot[s.f]
        arms = self.ARMS[(s.bar // 16) % len(self.ARMS)]
        depth_f = 4 + 5 * s.I
        D = int(math.ceil(depth_f))
        waves = [math.exp(-max(s.ph - l * 0.05, 0) * 7) * s.K for l in range(D)]  # kick travels to the tips
        grow = [1 + 0.12 * w for w in waves]
        grow[-1] *= depth_f - (D - 1)  # the newest generation grows in as intensity rises
        base = 0.36 + 0.1 * s.I + 0.3 * s.mid * (1 - s.K)
        spread = [base * (1 + 0.25 * math.sin(l * 1.3 + s.t * 0.2)) for l in range(D)]
        asym = 0.15 * math.sin(rot * 3)
        levels = tree_levels(self.CX, self.CY, arms, D, self.L0 * (1 + 0.04 * s.kick), self.RATIO,
                             spread, rot, r0=28, asym=asym, grow=grow)
        self.layer_flash(ctx, s, 0.5)
        self.layer_grid(ctx, s, "tri")
        self.layer_ripples(ctx, s)
        red_tips = s.peak and s.bib == 0
        for l, seg in enumerate(levels):
            last = l == D - 1
            col = RED if (last and red_tips) else INK
            a = 0.85 - 0.05 * l + 0.3 * waves[l]
            ctx.set_line_width(max(1.0, 3.2 * 0.8 ** l) + 1.2 * waves[l] + 0.5 * s.bass)
            ctx.set_source_rgba(*col, min(a, 1.0) * (0.5 + 0.5 * (depth_f - (D - 1)) if last else 1.0))
            path_segments(ctx, seg)
            ctx.stroke()
        ctx.set_line_width(1.5)
        ctx.set_source_rgba(*INK, 0.5 + 0.5 * s.kick)
        poly(ctx, arms, 28, rot, self.CX, self.CY); ctx.stroke()
        self.layer_ticks(ctx, s, rot, R=560)
        vignette(ctx, self.CX, self.CY, 420, 1150, 0.5)
        self.layer_hud(ctx, s, f"   arms={arms} depth={depth_f:.1f}")


class Sierpinski(Style):
    """Endless zoom into six Sierpinski triangles meeting at the centre; kicks push the zoom, detail grows with intensity."""
    name = "sierpinski"
    red_every = 4

    def prepare(self):
        c = self.c
        ph = c.beat % 1.0
        v = np.where(c.K > 0.5, (0.25 + 0.6 * c.I) * (0.3 + 1.6 * np.exp(-ph * 5)), 0.08 + 0.12 * c.mid)
        self.zoom = np.cumsum(v * (c.bpm / 60.0) / c.fps * 0.25)  # in octaves (doublings)
        self.rot = np.cumsum(0.0006 + 0.0015 * c.I)
        # big enough that the hexagon's inner radius covers the frame: zooming x2 is then seamless
        self.S0 = 1.05 * math.hypot(self.VW, self.VH) / 2 / math.cos(math.pi / 6)

    def draw(self, ctx, s):
        z = self.zoom[s.f]
        gen0 = int(math.floor(z))
        S = self.S0 * 2 ** (z - gen0)
        rot = self.rot[s.f]
        tris = np.array([[[self.CX, self.CY],
                          [self.CX + S * math.cos(th - math.pi / 6), self.CY + S * math.sin(th - math.pi / 6)],
                          [self.CX + S * math.cos(th + math.pi / 6), self.CY + S * math.sin(th + math.pi / 6)]]
                         for th in (rot + k * math.pi / 3 for k in range(6))])
        min_size = 16 + 28 * (1 - s.I)
        levels = sierpinski_holes(tris, min_size / 2, bounds=(-20, -20, self.VW + 20, self.VH + 20))
        self.layer_flash(ctx, s, 0.5)
        ctx.set_line_width(1.5)
        ctx.set_source_rgba(*INK, 0.5)
        for t in tris:  # spokes between the six triangles
            ctx.move_to(self.CX, self.CY); ctx.line_to(*t[1])
        ctx.stroke()
        for l, (holes, size) in enumerate(levels):
            fade = min(1.0, max(0.0, (size - min_size / 2) / (min_size / 2)))
            if fade <= 0:
                continue
            pos = math.log2(self.S0 * 2 / size) / 6  # 0 = coarse, 1 = fine
            w = math.exp(-max(s.ph - pos * 0.5, 0) * 7) * s.K
            red = s.peak and self.red_every and (l + gen0) % self.red_every == 0
            a = (0.5 + 0.5 * s.kick) if red else (0.15 + 0.3 * s.I) + 0.5 * w
            ctx.set_line_width(1.0 + 1.5 * w * min(1.0, size / 120) + 0.6 * s.bass)
            ctx.set_source_rgba(*(RED if red else INK), min(a, 1.0) * fade)
            path_triangles(ctx, holes)
            ctx.stroke()
        vignette(ctx, self.CX, self.CY, 380, 1150, 0.55)
        self.layer_brackets(ctx, s, RED if (s.peak and s.bib == 0) else INK)
        self.layer_hud(ctx, s, f"   x{2 ** z:,.0f}")


STYLES = {cls.name: cls for cls in (Bold, Geometric, Atom, Tunnel, Subtle, Horizon, Scope, Field, Sphere, Moire,
                                    Branches, Sierpinski)}
