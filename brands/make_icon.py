"""Generate an original brand icon for the WetterOnline custom integration.

Deliberately original artwork (sun behind a cloud on a blue rounded square) — it
does NOT use or imitate WetterOnline's official logo, to avoid any trademark /
copyright issue. Run: python brands/make_icon.py
"""

from pathlib import Path
from PIL import Image, ImageDraw

S = 1024  # supersampled working size
R = 180   # corner radius at working size

OUT = Path(__file__).parent


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    return m


def vertical_gradient(size, top, bottom):
    strip = Image.new("RGB", (1, size))
    px = strip.load()
    for y in range(size):
        t = y / (size - 1)
        px[0, y] = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return strip.resize((size, size))


def main():
    # Background: blue vertical gradient, clipped to a rounded square.
    bg = vertical_gradient(S, (0x4F, 0xAC, 0xFE), (0x12, 0x5E, 0xC8)).convert("RGBA")
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), rounded_mask(S, R))

    d = ImageDraw.Draw(icon)

    # Sun — warm amber disc, upper-left, with simple rays.
    cx, cy, rad = int(S * 0.40), int(S * 0.38), int(S * 0.16)
    for i in range(8):
        import math
        a = math.radians(i * 45)
        x0 = cx + math.cos(a) * rad * 1.35
        y0 = cy + math.sin(a) * rad * 1.35
        x1 = cx + math.cos(a) * rad * 1.85
        y1 = cy + math.sin(a) * rad * 1.85
        d.line([(x0, y0), (x1, y1)], fill=(0xFF, 0xD5, 0x4A, 255), width=int(S * 0.022))
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=(0xFF, 0xCA, 0x28, 255))

    # Cloud — white, overlapping the sun, lower-right.
    white = (0xFC, 0xFD, 0xFF, 255)
    base_y = int(S * 0.66)
    d.rounded_rectangle(
        [int(S * 0.30), base_y, int(S * 0.80), int(S * 0.78)],
        radius=int(S * 0.06), fill=white,
    )
    for ex, ey, er in [
        (0.40, 0.60, 0.11),
        (0.55, 0.55, 0.15),
        (0.70, 0.61, 0.12),
    ]:
        d.ellipse(
            [int((ex - er) * S), int((ey - er) * S),
             int((ex + er) * S), int((ey + er) * S)],
            fill=white,
        )

    # Downscale with antialiasing and write the brand assets.
    for name, size in [("icon.png", 256), ("icon@2x.png", 512)]:
        img = icon.resize((size, size), Image.LANCZOS)
        img.save(OUT / name)
    # logo.png: HA brands accepts a square logo; reuse the 512 icon.
    icon.resize((512, 512), Image.LANCZOS).save(OUT / "logo.png")
    icon.resize((512, 512), Image.LANCZOS).save(OUT / "logo@2x.png")
    print("wrote:", *[p.name for p in OUT.glob("*.png")])


if __name__ == "__main__":
    main()
