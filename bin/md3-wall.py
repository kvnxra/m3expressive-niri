#!/usr/bin/env python3
"""md3-wall — обои в палитре MD3: мягкий вертикальный градиент и три крупных цветных «пятна».
Рисуется в 480x270 и растягивается awww (быстро и без зависимостей: только стандартная библиотека).
Использование: md3-wall.py <куда сохранить.png>
"""
import json
import math
import os
import struct
import sys
import zlib

W, H = 480, 270
CONFIG = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def chunk(tag, data):
    body = tag + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def main(out):
    with open(os.path.join(CONFIG, "md3", "colors.json")) as f:
        c = json.load(f)
    top, bot = rgb(c["surface_container_low"]), rgb(c["surface"])
    blobs = [  # x, y, радиус (в долях высоты), цвет, сила
        (0.14, 0.22, 0.55, rgb(c["primary_container"]), 0.60),
        (0.90, 0.78, 0.60, rgb(c.get("tertiary_container", c["secondary_container"])), 0.50),
        (0.66, 0.08, 0.34, rgb(c["secondary_container"]), 0.45),
    ]
    aspect = W / H
    raw = bytearray()
    for y in range(H):
        t = y / (H - 1)
        base = [top[i] + (bot[i] - top[i]) * t for i in range(3)]
        raw.append(0)  # фильтр PNG: none
        for x in range(W):
            px = list(base)
            for bx, by, br, col, strength in blobs:
                d = math.hypot((x / W - bx) * aspect, y / H - by) / br
                if d < 1:
                    a = (1 - d) ** 2 * strength
                    for i in range(3):
                        px[i] += (col[i] - px[i]) * a
            raw += bytes(max(0, min(255, int(v))) for v in px)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(png)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
