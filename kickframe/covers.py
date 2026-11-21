"""Square cover art in the same visual language as the video styles."""
from __future__ import annotations

import math

import cairo

from .styles import INK, RED, BG, TAU, poly


class Canvas:
    def __init__(self, size: int):
        self.S = size
        self.C = size / 2
        self.k = size / 3000.0  # all geometry is authored on a 3000 px square
        self.surf = cairo.ImageSurface(cairo.FORMAT_RGB24, size, size)
        self.ctx = cairo.Context(self.surf)
        self.ctx.scale(self.k, self.k)
        self.ctx.set_source_rgb(*BG)
        self.ctx.paint()

    def save(self, path):
        self.surf.write_to_png(path)


C = 1500.0  # centre in authoring units


def _grid_tri(ctx, sp, a):
    ctx.set_line_width(2); ctx.set_source_rgba(*INK, a)
    h = sp * math.sqrt(3) / 2
    y = (C % h) - h
    while y < 3000 + h:
        ctx.move_to(0, y); ctx.line_to(3000, y); y += h
    for ang in (math.pi / 3, 2 * math.pi / 3):
        dx, dy = math.cos(ang), math.sin(ang)
        for i in range(-40, 41):
            x0 = C + i * sp
            ctx.move_to(x0 - dx * 5000, C - dy * 5000); ctx.line_to(x0 + dx * 5000, C + dy * 5000)
    ctx.stroke()


def _grid_sq(ctx, sp, a):
    ctx.set_line_width(2); ctx.set_source_rgba(*INK, a)
    x = C % sp
    while x < 3000:
        ctx.move_to(x, 0); ctx.line_to(x, 3000); ctx.move_to(0, x); ctx.line_to(3000, x); x += sp
    ctx.stroke()


def _ticks(ctx, R, n, ln, a=0.55, w=4):
    ctx.set_line_width(w)
    ctx.set_source_rgba(*INK, a)
    for i in range(n):
        t = TAU * i / n
        ctx.move_to(C + R * math.cos(t), C + R * math.sin(t))
        ctx.line_to(C + (R + ln) * math.cos(t), C + (R + ln) * math.sin(t))
    ctx.stroke()


def _vignette(ctx):
    g = cairo.RadialGradient(C, C, 900, C, C, 2250)
    g.add_color_stop_rgba(0, 0, 0, 0, 0); g.add_color_stop_rgba(1, 0, 0, 0, 0.6)
    ctx.set_source(g); ctx.paint()


def _text(cv: Canvas, title, subtitle, font):
    if not title and not subtitle:
        return
    ctx = cv.ctx
    ctx.select_font_face(font, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_source_rgba(*INK, 1)
    ctx.set_font_size(190)
    if title:
        ctx.move_to(190, 2650 if subtitle else 2810); ctx.show_text(title)
    if subtitle:
        ctx.select_font_face(font, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(62)
        ctx.set_source_rgba(*INK, 0.75)
        ctx.move_to(196, 2810); ctx.show_text(subtitle)


def ngons(cv: Canvas, layers=40, sides=(3, 4, 5, 6, 8), twist=0.075, spacing=30, red_layer=31):
    ctx = cv.ctx
    _grid_sq(ctx, 250, 0.045)
    for i in range(layers):
        n = sides[min(len(sides) - 1, i * len(sides) // layers)]
        is_red = i == red_layer
        ctx.set_line_width(3)
        ctx.set_source_rgba(*(RED if is_red else INK), 0.95 if is_red else 0.18 + 0.6 * i / layers)
        poly(ctx, n, (90 + i * spacing) / math.cos(math.pi / n) ** 0.5, i * twist, C, C)
        ctx.stroke()
    _ticks(ctx, 90 + layers * spacing + 130, 96, 40, 0.5, 4)
    _vignette(ctx)


def atom(cv: Canvas, shells=6, sides=6, red_shell=2):
    ctx = cv.ctx
    _grid_tri(ctx, 260, 0.05)
    for i in range(7):
        r = (85 + i * 40) * 2.78 * 1.1 / math.cos(math.pi / sides) ** 0.45
        ctx.set_line_width(4 if i < 6 else 6)
        ctx.set_source_rgba(*(RED if i == 6 else INK), 0.85 if i == 6 else 0.28 + 0.06 * i)
        poly(ctx, sides, r, 0.12 * i, C, C); ctx.stroke()
    A, Bq = 1180, 0.28
    for k in range(shells):
        tilt = 0.2 + k * math.pi / shells
        ctx.save(); ctx.translate(C, C); ctx.rotate(tilt); ctx.scale(1, Bq)
        ctx.arc(0, 0, A, 0, TAU); ctx.restore()
        ctx.set_line_width(3); ctx.set_source_rgba(*INK, 0.42); ctx.stroke()
        a0 = 0.9 + k * 1.7
        ct, st = math.cos(tilt), math.sin(tilt)
        for s in range(40):
            a1, a2 = a0 - 1.5 * s / 40, a0 - 1.5 * (s + 1) / 40
            pts = [(C + A * math.cos(a) * ct - A * Bq * math.sin(a) * st,
                    C + A * math.cos(a) * st + A * Bq * math.sin(a) * ct) for a in (a1, a2)]
            fa = (1 - s / 40) ** 2
            ctx.set_line_width(4 + 12 * fa)
            ctx.set_source_rgba(*(RED if k == red_shell else INK), fa)
            ctx.move_to(*pts[0]); ctx.line_to(*pts[1]); ctx.stroke()
    for j in range(19):
        rad = 34 * 1.25 * math.sqrt(j + 0.5)
        ang = j * 2.39996
        ctx.set_line_width(4)
        ctx.set_source_rgba(*(RED if j % 3 == 0 else INK), 0.9)
        ctx.arc(C + rad * math.cos(ang), C + rad * math.sin(ang), 21, 0, TAU); ctx.stroke()
    _vignette(ctx)


def lissajous(cv: Canvas, a=5, b=4, inner=(3, 2)):
    ctx = cv.ctx
    for r in range(1, 9):
        ctx.set_line_width(2); ctx.set_source_rgba(*INK, 0.05 + 0.01 * r)
        ctx.arc(C, C, r * 170, 0, TAU); ctx.stroke()
    for (aa, bb, d, col, al, w, R) in [(a, b, 0.0, INK, 0.75, 3, 1150), (a, b, 0.35, INK, 0.3, 2, 1150),
                                       (inner[0], inner[1], 0.6, RED, 0.9, 4, 700)]:
        ctx.set_line_width(w); ctx.set_source_rgba(*col, al)
        for j in range(4001):
            s = TAU * j / 4000
            x, y = C + R * math.sin(aa * s + d), C + R * math.sin(bb * s)
            ctx.line_to(x, y) if j else ctx.move_to(x, y)
        ctx.stroke()
    _ticks(ctx, 1300, 128, 50, 0.6, 4)
    ctx.set_line_width(2); ctx.set_source_rgba(*INK, 0.25)
    ctx.move_to(C, 60); ctx.line_to(C, 2940); ctx.move_to(60, C); ctx.line_to(2940, C); ctx.stroke()
    _vignette(ctx)


def ripple(cv: Canvas, rings=14, squares=6):
    ctx = cv.ctx
    _grid_tri(ctx, 200, 0.10)
    for i in range(rings):
        ctx.set_line_width(3 if i % 4 else 6)
        ctx.set_source_rgba(*INK, max(0.08, 0.8 - i * 0.055))
        ctx.arc(C, C, 120 * (1.22 ** i), 0, TAU); ctx.stroke()
    for i in range(squares):
        ctx.set_line_width(3); ctx.set_source_rgba(*INK, 0.6)
        poly(ctx, 4, 260 + i * 140, math.pi / 4 + i * math.radians(22.5), C, C); ctx.stroke()
    ctx.set_source_rgba(*RED, 1)
    poly(ctx, 4, 70, math.pi / 4, C, C); ctx.fill()
    m, L = 120, 160
    ctx.set_line_width(6); ctx.set_source_rgba(*INK, 0.7)
    for (x, y, sx, sy) in ((m, m, 1, 1), (3000 - m, m, -1, 1), (m, 3000 - m, 1, -1), (3000 - m, 3000 - m, -1, -1)):
        ctx.move_to(x, y + sy * L); ctx.line_to(x, y); ctx.line_to(x + sx * L, y)
    ctx.stroke()
    _vignette(ctx)


COVERS = {"ngons": ngons, "atom": atom, "lissajous": lissajous, "ripple": ripple}


def make_cover(kind: str, out: str, size=3000, title=None, subtitle=None, font="monospace", **params):
    cv = Canvas(size)
    COVERS[kind](cv, **params)
    _text(cv, title, subtitle, font)
    cv.save(out)
    print("wrote", out)
