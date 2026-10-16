"""Generate logo project Recy -> app/static/img/logo.png (murni stdlib).

Desain: tile rounded-square gelap (tema obsidian) + grafik garis naik neon
hijau (#00E599) dengan glow halus + bingkai neon — selaras gaya neon
terminal. Digambar via SDF (signed distance field) sehingga tepi anti-alias
tanpa library raster eksternal (Pillow tidak tersedia di .env).

Pemakaian:
    .venv/Scripts/python make_logo.py
"""

import math
import os
import struct
import zlib

SIZE = 256          # ukuran final (px)
RADIUS = 56         # radius sudut tile
BORDER = 4          # ketebalan bingkai neon

# Warna tema (RGB)
BG_TOP = (11, 14, 20)       # #0B0E14 obsidian
BG_BOTTOM = (16, 27, 46)    # gradasi ke navy
NEON = (0, 229, 153)        # #00E599 bull
CYAN = (0, 216, 255)        # #00D8FF cyber


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def rounded_rect_sdf(x, y, w, h, r):
    """SDF rounded-rect: < 0 di dalam, >= 0 di luar (jarak px)."""
    cx = max(r - x, x - (w - r), 0.0)
    cy = max(r - y, y - (h - r), 0.0)
    outside = math.hypot(cx, cy)
    inside = min(max(r - x, x - w + r), max(r - y, y - h + r))
    return outside if outside > 0 else -inside


def seg_dist(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    len2 = vx * vx + vy * vy
    t = 0.0 if len2 == 0 else clamp((wx * vx + wy * vy) / len2)
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def write_png(path, width, height, rgba):
    """Tulis PNG RGBA tanpa dependensi eksternal (filter type 0)."""

    def chunk(tag, data):
        payload = tag + data
        return (
            struct.pack(">I", len(data))
            + payload
            + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)
        )

    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter: None
        raw.extend(rgba[y * stride:(y + 1) * stride])

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


def main():
    w = h = SIZE
    buf = bytearray(w * h * 4)

    # Titik poligon grafik (koordinat ternormalisasi di dalam tile).
    pts = [
        (0.16, 0.74), (0.30, 0.60), (0.42, 0.68),
        (0.56, 0.44), (0.68, 0.52), (0.84, 0.26),
    ]
    # Skala ke pixel dengan margin aman dari bingkai.
    pad = 34.0
    scale_x = w - 2 * pad
    scale_y = h - 2 * pad
    segs = []
    px = [(pad + x * scale_x, pad + y * scale_y) for x, y in pts]
    for i in range(len(px) - 1):
        segs.append((px[i], px[i + 1]))
    end = px[-1]
    start = px[0]

    def blend(i, r, g, b, a):
        """Alpha-over ke buffer RGBA."""
        a = clamp(a)
        if a <= 0:
            return
        ba = buf[i + 3] / 255.0
        na = a + ba * (1.0 - a)
        if na <= 0:
            return
        for k, src in enumerate((r, g, b)):
            dst = buf[i + k]
            buf[i + k] = int(clamp((src * a + dst * ba * (1.0 - a)) / na) * 255 + 0.5)
        buf[i + 3] = int(na * 255 + 0.5)

    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            sdf = rounded_rect_sdf(x + 0.5, y + 0.5, w, h, RADIUS)

            # Glow luar tile (halo neon tipis).
            if 0 < sdf < 14:
                g = (1.0 - sdf / 14.0) ** 2
                blend(i, *NEON, g * 0.30)
                continue
            if sdf > 0:
                continue

            cover = clamp(0.5 - sdf)  # anti-alias tepi tile
            # Latar gradien vertikal obsidian -> navy.
            t = y / (h - 1)
            r = BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t
            g = BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t
            b = BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t

            # Grid samar (2 garis horizontal) di belakang chart.
            for gy in (0.42, 0.66):
                dline = abs((y + 0.5) - gy * h)
                if dline < 1.0:
                    r, g, b = (
                        r + (200 - r) * 0.06,
                        g + (210 - g) * 0.06,
                        b + (220 - b) * 0.06,
                    )

            # Bingkai neon (sudut dalam - BORDER .. tepi).
            edge = sdf + BORDER  # ~0 di batas dalam bingkai
            if -BORDER <= sdf <= 0:
                k = clamp(1.0 - abs(edge) / BORDER)  # puncak di tengah bingkai
                ring = (1.0 - (abs(sdf) / BORDER)) * 0.9
                mix = clamp(ring)
                r = r + (NEON[0] - r) * mix
                g = g + (NEON[1] - g) * mix
                b = b + (NEON[2] - b) * mix
                _ = k  # dipertahankan utk kejelasan intensitas

            blend(i, int(r), int(g), int(b), cover)

    # --- Garis chart: glow + core (di atas latar, hanya di dalam tile) ---
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            if buf[i + 3] < 8:
                continue
            d = min(seg_dist(x + 0.5, y + 0.5, *a, *b) for a, b in segs)
            if d < 26:
                blend(i, *NEON, ((1.0 - d / 26.0) ** 2) * 0.35)   # glow
            if d < 5.0:
                blend(i, *NEON, clamp(5.0 - d, 0, 1) * 0.98)      # core AA

    # Titik awal (outline cyan) & titik ujung (penanda harga).
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            if buf[i + 3] < 8:
                continue
            pxf, pyf = x + 0.5, y + 0.5
            de = math.hypot(pxf - end[0], pyf - end[1])
            if de < 16:
                blend(i, *NEON, ((1.0 - de / 16.0) ** 2) * 0.5)   # glow ujung
            if de < 7.5:
                blend(i, 240, 255, 252, clamp(7.5 - de, 0, 1))    # inti putih-hijau
                if de < 3.2:
                    blend(i, *NEON, clamp(3.2 - de, 0, 1))
            ds = math.hypot(pxf - start[0], pyf - start[1])
            if ds < 5.0:
                blend(i, *CYAN, clamp(5.0 - ds, 0, 1) * 0.9)

    out_dir = os.path.join("app", "static", "img")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "logo.png")
    write_png(out_path, w, h, buf)
    print(f"OK {out_path} ({os.path.getsize(out_path)} bytes, {w}x{h})")


if __name__ == "__main__":
    main()
