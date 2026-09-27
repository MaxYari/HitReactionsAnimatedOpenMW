#!/usr/bin/env python3
"""Pack the mod banner into the DDS the settings page draws.

Reads img/nexus banner.png, fits it to a power-of-two canvas and writes

  textures/MaxYari/HitReactionsAnimated/banner.dds

then prints the content rectangle inside that canvas. menu.lua uses the
rectangle to crop the transparent padding back off, so re-run this after
changing the art and paste the numbers it prints into menu.lua.

Needs ImageMagick (`magick`).

  python3 tools/make_banner.py
"""
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, 'img', 'nexus banner.png')
TEXTURE = os.path.join(ROOT, 'textures', 'MaxYari', 'HitReactionsAnimated', 'banner.dds')

# Power-of-two canvas. The banner is laid into the top-left corner and the rest
# is left transparent; OpenMW wants the sides to be powers of two, the UI does
# not have to show all of it.
TEX_W, TEX_H = 1024, 512


def write_dds(path, pixels, w, h):
    """Uncompressed A8R8G8B8 with a full mip chain, averaging colour by alpha.

    Weighting by alpha keeps the transparent padding from bleeding its colour
    into the edge of the banner as the mips get smaller.
    """
    levels = [(w, h, pixels)]
    while w > 1 or h > 1:
        nw, nh = max(1, w // 2), max(1, h // 2)
        src = levels[-1][2]
        out = []
        for y in range(nh):
            for x in range(nw):
                quad = [src[min(y * 2 + dy, h - 1) * w + min(x * 2 + dx, w - 1)]
                        for dy in (0, 1) for dx in (0, 1)]
                a = sum(p[3] for p in quad)
                if a > 0:
                    rgb = [sum(p[c] * p[3] for p in quad) / a for c in range(3)]
                else:
                    rgb = [sum(p[c] for p in quad) / 4 for c in range(3)]
                out.append((rgb[0], rgb[1], rgb[2], a / 4))
        levels.append((nw, nh, out))
        w, h = nw, nh

    W, H = levels[0][0], levels[0][1]
    header = struct.pack('<4sIIIIIII44x', b'DDS ', 124,
                         0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000,
                         H, W, W * 4, 0, len(levels))
    header += struct.pack('<IIIIIIII', 32, 0x41, 0, 32,
                          0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    header += struct.pack('<IIII4x', 0x1000 | 0x400000 | 0x8, 0, 0, 0)

    body = bytearray()
    for _, _, level in levels:
        for r, g, b, a in level:
            body += bytes((int(b + 0.5), int(g + 0.5), int(r + 0.5), int(a + 0.5)))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(header + bytes(body))


def main():
    if not os.path.exists(SOURCE):
        sys.exit(f'make_banner: {SOURCE} is missing')

    out = subprocess.run(['magick', 'identify', '-format', '%w %h', SOURCE],
                         capture_output=True, text=True, check=True).stdout
    src_w, src_h = (int(n) for n in out.split())

    # Widest fit that still leaves the whole banner inside the canvas.
    content_w = TEX_W
    content_h = round(src_h * content_w / src_w)
    if content_h > TEX_H:
        sys.exit(f'make_banner: {src_w}x{src_h} does not fit {TEX_W}x{TEX_H}')

    raw = subprocess.run(
        ['magick', SOURCE,
         '-resize', f'{content_w}x{content_h}!',
         '-background', 'none', '-gravity', 'NorthWest',
         '-extent', f'{TEX_W}x{TEX_H}',
         '-depth', '8', 'RGBA:-'],
        capture_output=True, check=True).stdout

    expected = TEX_W * TEX_H * 4
    if len(raw) != expected:
        sys.exit(f'make_banner: got {len(raw)} bytes from ImageMagick, wanted {expected}')

    pixels = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
    write_dds(TEXTURE, pixels, TEX_W, TEX_H)

    print(f'wrote {os.path.relpath(TEXTURE, ROOT)}  ({os.path.getsize(TEXTURE)} bytes)')
    print(f'source {src_w}x{src_h} -> canvas {TEX_W}x{TEX_H}')
    print('menu.lua content rectangle:')
    print(f'    offset = util.vector2(0, 0),')
    print(f'    size = util.vector2({content_w}, {content_h}),')
    print(f'  and the aspect for the drawn size: {content_h} / {content_w}')


if __name__ == '__main__':
    main()
