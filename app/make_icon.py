"""Draws the Albion Ava Mapper icon: flat black square, big tight white "AV" in Space Grotesk Bold
(the app's heading font, bundled in static/fonts). Writes icon.ico (exe) and static/icon.png.
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(HERE, "static", "fonts", "space-grotesk.woff2")
S = 1024                       # master size, scaled down for each icon size
BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
TEXT = "AV"
TRACKING = -0.06               # tight letter spacing, as a share of the font size


def make():
    img = Image.new("RGBA", (S, S), BLACK)
    d = ImageDraw.Draw(img)

    def font(size):
        f = ImageFont.truetype(FONT, size)
        f.set_variation_by_name("Bold")
        return f

    def width(f):
        gap = f.size * TRACKING
        return sum(d.textlength(ch, font=f) for ch in TEXT) + gap * (len(TEXT) - 1)

    # biggest size that fills ~70% of the width
    size = 700
    while width(font(size)) > S * 0.70:
        size -= 10
    f = font(size)
    gap = size * TRACKING
    left, top, right, bottom = d.textbbox((0, 0), TEXT, font=f)
    ink_h = bottom - top
    x = (S - width(f)) / 2
    y = (S - ink_h) / 2 - top
    for ch in TEXT:
        d.text((x, y), ch, font=f, fill=WHITE)
        x += d.textlength(ch, font=f) + gap

    img.save(os.path.join(HERE, "icon.ico"), sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "static", "icon.png"))


if __name__ == "__main__":
    make()
    print("icon.ico + static/icon.png written")
