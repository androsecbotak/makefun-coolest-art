#!/usr/bin/env python3
"""Make the coolest art — make.fun bounty entry.

A deterministic, standard-library-only Python program that draws one
cool picture (a neon cyber-samurai under a blood-red sun) and writes
it to /output/entry.png.

No network, no randomness, no third-party libraries: the PNG encoder
is written by hand on top of zlib (stdlib). Two runs produce
byte-identical output.
"""

import math
import os
import struct
import zlib

# ---------------------------------------------------------------------------
# Canvas (rendered at 2x, then box-downsampled for smooth edges)
# ---------------------------------------------------------------------------
SS = 2                      # supersampling factor
W, H = 1024, 1024           # final size
RW, RH = W * SS, H * SS     # render size


class Canvas:
    def __init__(self):
        self.buf = bytearray(RW * RH * 3)

    def _set(self, x, y, r, g, b):
        if 0 <= x < RW and 0 <= y < RH:
            i = (y * RW + x) * 3
            self.buf[i] = r
            self.buf[i + 1] = g
            self.buf[i + 2] = b

    def _blend(self, x, y, r, g, b, a):
        """Alpha-blend a colour over the pixel at (x, y). a in [0, 1]."""
        if a <= 0 or not (0 <= x < RW and 0 <= y < RH):
            return
        i = (y * RW + x) * 3
        if a >= 1:
            self.buf[i] = r
            self.buf[i + 1] = g
            self.buf[i + 2] = b
            return
        self.buf[i] = int(self.buf[i] * (1 - a) + r * a)
        self.buf[i + 1] = int(self.buf[i + 1] * (1 - a) + g * a)
        self.buf[i + 2] = int(self.buf[i + 2] * (1 - a) + b * a)

    def row_fill(self, y, x0, x1, col):
        """Fill pixels x0..x1 (float bounds) on row y, solid colour."""
        if y < 0 or y >= RH:
            return
        a = max(0, int(math.floor(x0)))
        b = min(RW - 1, int(math.ceil(x1)) - 1)
        if b < a:
            return
        r, g, bl = col
        base = (y * RW + a) * 3
        n = b - a + 1
        self.buf[base:base + n * 3] = bytes((r, g, bl)) * n

    def circle(self, cx, cy, rad, col, alpha=1.0):
        cx *= SS
        cy *= SS
        rad *= SS
        y0 = max(0, int(math.floor(cy - rad)))
        y1 = min(RH - 1, int(math.ceil(cy + rad)))
        for y in range(y0, y1 + 1):
            dy = (y + 0.5) - cy
            if abs(dy) >= rad:
                continue
            dx = math.sqrt(rad * rad - dy * dy)
            if alpha >= 1.0:
                self.row_fill(y, cx - dx, cx + dx, col)
            else:
                for x in range(max(0, int(cx - dx)), min(RW - 1, int(cx + dx)) + 1):
                    self._blend(x, y, col[0], col[1], col[2], alpha)

    def ellipse(self, cx, cy, rx, ry, col, alpha=1.0):
        cx *= SS
        cy *= SS
        rx *= SS
        ry *= SS
        y0 = max(0, int(math.floor(cy - ry)))
        y1 = min(RH - 1, int(math.ceil(cy + ry)))
        for y in range(y0, y1 + 1):
            dy = (y + 0.5) - cy
            if abs(dy) >= ry:
                continue
            t = 1.0 - (dy * dy) / (ry * ry)
            dx = rx * math.sqrt(max(0.0, t))
            if alpha >= 1.0:
                self.row_fill(y, cx - dx, cx + dx, col)
            else:
                for x in range(max(0, int(cx - dx)), min(RW - 1, int(cx + dx)) + 1):
                    self._blend(x, y, col[0], col[1], col[2], alpha)

    def poly(self, pts, col):
        """Scanline-fill a polygon given as [(x, y), ...] in final coords."""
        pts = [(x * SS, y * SS) for x, y in pts]
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(RH - 1, int(math.ceil(max(ys))))
        n = len(pts)
        for y in range(y0, y1 + 1):
            yc = y + 0.5
            xs = []
            for i in range(n):
                x1, y1p = pts[i]
                x2, y2p = pts[(i + 1) % n]
                if (y1p <= yc < y2p) or (y2p <= yc < y1p):
                    t = (yc - y1p) / (y2p - y1p)
                    xs.append(x1 + t * (x2 - x1))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                self.row_fill(y, xs[k], xs[k + 1], col)

    def thick_line(self, x1, y1, x2, y2, w, col):
        """Draw a thick line segment (final coords, width in final px).

        NOTE: poly() does the SS scaling itself, so pass final coords here.
        """
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length == 0:
            return
        nx, ny = -dy / length, dx / length
        hw = w / 2.0
        self.poly([
            (x1 + nx * hw, y1 + ny * hw),
            (x2 + nx * hw, y2 + ny * hw),
            (x2 - nx * hw, y2 - ny * hw),
            (x1 - nx * hw, y1 - ny * hw),
        ], col)

    def tube(self, pts, w, col):
        """Draw a smooth tube along a polyline (overlapping circles, so
        there are no seams at the joints). Final coords."""
        r = w / 2.0
        for (x, y) in pts:
            self.circle(x, y, r, col)

    def arc(self, cx, cy, rad, a0, a1, w, col, steps=48):
        """Draw a thick arc (angles in radians, final coords)."""
        pts = []
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * i / steps
            pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
        for i in range(len(pts) - 1):
            self.thick_line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], w, col)

    def vgrad(self, top, bottom):
        """Vertical gradient background (final coords)."""
        for y in range(RH):
            t = y / max(1, RH - 1)
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            base = y * RW * 3
            self.buf[base:base + RW * 3] = bytes((r, g, b)) * RW

    def downsample(self):
        """Box-average the 2x buffer down to W x H, returns bytes."""
        out = bytearray(W * H * 3)
        src = self.buf
        for y in range(H):
            sy = y * SS
            for x in range(W):
                sx = x * SS
                r = g = b = 0
                for dy in range(SS):
                    base = ((sy + dy) * RW + sx) * 3
                    for dx in range(SS):
                        i = base + dx * 3
                        r += src[i]
                        g += src[i + 1]
                        b += src[i + 2]
                o = (y * W + x) * 3
                n = SS * SS
                out[o] = r // n
                out[o + 1] = g // n
                out[o + 2] = b // n
        return bytes(out)


# ---------------------------------------------------------------------------
# Minimal PNG encoder (RGB, 8-bit, filter 0, zlib)
# ---------------------------------------------------------------------------
def write_png(path, rgb, w, h):
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(ctype, data):
        c = struct.pack(">I", len(data)) + ctype + data
        c += struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)
        return c

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


# ---------------------------------------------------------------------------
# The picture: a neon cyber-samurai under a blood-red sun, rain and petals
# ---------------------------------------------------------------------------
INK   = (10, 10, 24)      # near-black indigo
INDIGO = (22, 22, 48)     # dark background bottom
STEEL = (38, 40, 58)      # armor plates
STEEL_D = (24, 26, 40)    # armor shadow
STEEL_L = (74, 78, 108)   # armor highlight edge
GOLD  = (212, 175, 55)    # kabuto horns / crest
GOLD_D = (160, 124, 32)
SUN   = (232, 48, 48)     # blood-red sun
SUN_L = (255, 110, 70)    # sun core
CYAN  = (0, 240, 255)     # neon cyan
CYAN_D = (0, 140, 180)
MAGENTA = (255, 45, 120)  # neon magenta
PETAL = (255, 150, 180)   # cherry blossom
RAIN  = (110, 130, 180)   # rain streaks
WHITE = (255, 255, 255)
FACE  = (8, 8, 18)        # shadowed face


def lcg(seed, n):
    """Deterministic pseudo-random numbers in [0, 1)."""
    out = []
    x = seed
    for _ in range(n):
        x = (1103515245 * x + 12345) % (1 << 31)
        out.append(x / (1 << 31))
    return out


def rot(px, py, cx, cy, ang):
    c, s = math.cos(ang), math.sin(ang)
    dx, dy = px - cx, py - cy
    return (cx + dx * c - dy * s, cy + dx * s + dy * c)


def draw():
    c = Canvas()
    # Night sky: deep indigo up top fading to near-black.
    c.vgrad((16, 14, 40), (8, 8, 20))

    # Blood-red sun with a soft halo, high behind the samurai.
    c.circle(512, 360, 260, SUN, alpha=0.22)
    c.circle(512, 360, 232, SUN, alpha=0.45)
    c.circle(512, 360, 208, SUN)
    c.circle(512, 360, 168, SUN_L)
    # Sun slats: two thin dark bands, kept inside the sun disc.
    c.poly([(336, 302), (688, 302), (688, 312), (336, 312)], INK)
    c.poly([(330, 372), (694, 372), (694, 380), (330, 380)], INK)

    # Distant mountains, dark silhouettes.
    c.poly([(0, 760), (180, 640), (330, 740), (520, 620), (700, 745),
            (860, 650), (1024, 760), (1024, 1024), (0, 1024)], (14, 14, 30))
    # Far city glow on the horizon.
    c.ellipse(512, 760, 420, 26, (60, 30, 70), alpha=0.5)

    # Rain: thin diagonal streaks, deterministic positions.
    r = lcg(20261113, 90)
    for i in range(45):
        x = 20 + r[i * 2] * 984
        y = 20 + r[i * 2 + 1] * 700
        ln = 34 + r[(i + 45) % 90] * 30
        c.thick_line(x, y, x - 12, y + ln, 2, RAIN)

    # ---- Samurai ----
    # Shoulders / torso: broad armor mass, darkest at the edges.
    c.poly([(512, 560), (300, 640), (240, 1024), (784, 1024), (724, 640)],
           STEEL_D)
    c.poly([(512, 580), (330, 650), (300, 1024), (724, 1024), (694, 650)],
           STEEL)
    # Chest plate centre ridge + neon seam.
    c.poly([(512, 600), (452, 700), (452, 1024), (572, 1024), (572, 700)],
           STEEL)
    c.thick_line(452, 700, 452, 1024, 3, CYAN_D)
    c.thick_line(572, 700, 572, 1024, 3, CYAN_D)
    # Belt band with a gold buckle.
    c.poly([(300, 880), (724, 880), (724, 916), (300, 916)], STEEL_D)
    c.poly([(486, 880), (538, 880), (538, 916), (486, 916)], GOLD_D)
    c.poly([(494, 888), (530, 888), (530, 908), (494, 908)], GOLD)
    # Layered shoulder guards (sode), left and right.
    for sgn in (-1, 1):
        # Angled pauldron plates: outer plate, inner plate, neon top edge.
        ox = 512 + 205 * sgn
        c.poly([(ox - 118 * sgn, 606), (ox + 52 * sgn, 586),
                (ox + 108 * sgn, 668), (ox + 78 * sgn, 762),
                (ox - 78 * sgn, 748)], STEEL_L)
        c.poly([(ox - 96 * sgn, 622), (ox + 42 * sgn, 606),
                (ox + 88 * sgn, 668), (ox + 62 * sgn, 742),
                (ox - 62 * sgn, 730)], STEEL)
        c.poly([(ox - 72 * sgn, 640), (ox + 30 * sgn, 626),
                (ox + 66 * sgn, 672), (ox + 46 * sgn, 720),
                (ox - 46 * sgn, 710)], STEEL_D)
        c.thick_line(ox - 118 * sgn, 606, ox + 52 * sgn, 586, 4, CYAN)

    # Neck guard.
    c.poly([(472, 560), (552, 560), (566, 640), (458, 640)], STEEL_D)

    # Head: face first, then the kabuto dome overlapping its top so the
    # two read as one head; a thin brim sits on the boundary.
    c.ellipse(512, 505, 92, 62, FACE)         # face shadow
    c.ellipse(512, 395, 158, 112, STEEL_L)    # helmet rim light
    c.ellipse(512, 393, 148, 104, STEEL)      # dome
    c.ellipse(512, 478, 150, 16, STEEL_D)     # thin dark brim over the brow
    # Helmet ridge lines.
    c.arc(512, 398, 122, math.radians(195), math.radians(345), 5, STEEL_L)
    c.arc(512, 398, 96, math.radians(200), math.radians(340), 4, STEEL_D)
    # Kuwagata horns: gold, tapering, sweeping up from the helmet sides.
    for sgn in (-1, 1):
        pts = []
        for i in range(25):
            t = i / 24
            pts.append((512 + sgn * (118 + 108 * t),
                        408 - 30 * math.sin(t * 1.9) - 130 * t))
        c.tube(pts[:16], 18, GOLD_D)
        c.tube(pts[:16], 12, GOLD)
        c.tube(pts[15:], 12, GOLD_D)
        c.tube(pts[15:], 7, GOLD)
    # Forehead crest: small gold crescent.
    c.arc(512, 366, 26, math.radians(180), math.radians(360), 8, GOLD)

    # Glowing eyes: cyan slits in the shadow.
    for ex in (474, 550):
        c.ellipse(ex, 522, 21, 9, CYAN, alpha=0.35)
        c.ellipse(ex, 522, 15, 6, CYAN)
        c.circle(ex, 522, 4, WHITE)
    # Menpo mask grill lines under the eyes.
    for i in range(3):
        c.thick_line(480, 548 + i * 10, 544, 548 + i * 10, 3, STEEL_D)

    # ---- Katana, drawn diagonally across the body ----
    # Glow underlay, then the bright blade, then the dark edge line.
    c.thick_line(318, 912, 724, 470, 26, CYAN, )
    c.thick_line(318, 912, 724, 470, 14, (120, 240, 255))
    c.thick_line(318, 912, 724, 470, 7, WHITE)
    # Handle (tsuka), wrapped, at the lower end.
    hx, hy = 318, 912
    c.thick_line(hx, hy, hx - 52, hy + 62, 22, (20, 18, 26))
    c.thick_line(hx - 8, hy + 8, hx - 44, hy + 54, 3, GOLD_D)
    c.thick_line(hx - 20, hy + 22, hx - 52, hy + 62, 3, GOLD_D)
    # Tsuba (guard): small dark disc where blade meets handle.
    c.ellipse(318, 912, 26, 26, STEEL_L)
    c.ellipse(318, 912, 18, 18, STEEL_D)

    # Magenta energy slash arcing across the chest and the blade.
    # It ends on the blade instead of floating in the sky.
    c.arc(700, 860, 330, math.radians(200), math.radians(272), 10, MAGENTA)
    c.arc(700, 860, 330, math.radians(200), math.radians(272), 4, (255, 150, 200))

    # Cherry blossom petals drifting in, deterministic spots.
    p = lcg(777, 72)
    for i in range(18):
        x = 40 + p[i * 2] * 944
        y = 60 + p[i * 2 + 1] * 860
        s = 7 + p[(i + 15) % 60] * 8
        c.ellipse(x, y, s, s * 0.6, PETAL, alpha=0.85)

    # Ground glow: cyan reflection strip at the very bottom.
    c.ellipse(512, 1030, 480, 40, CYAN_D, alpha=0.35)
    return c.downsample()


def main():
    out = "/output/entry.png" if os.path.isdir("/output") else "output/entry.png"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    rgb = draw()
    write_png(out, rgb, W, H)
    print("wrote", out, len(rgb), "bytes of RGB,", os.path.getsize(out), "bytes PNG")


if __name__ == "__main__":
    main()
