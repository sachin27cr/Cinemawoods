"""
Generates a branded text-card image (JPEG) for each headline instead of
reposting copyrighted press photos/stills. Instagram's publishing API only
accepts JPEG, so cards are always saved as .jpg.
"""

import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

import config

WIDTH, HEIGHT = 1080, 1080  # IG square
OUT_DIR = "graphics"

FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
]
FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "DejaVuSans.ttf",
]


def _load_font(candidates, size):
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)  # Pillow 10.1+ supports a size
    except TypeError:
        return ImageFont.load_default()


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def make_headline_card(title: str, source: str, out_path: str = None) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    if out_path is None:
        safe_name = "".join(c if c.isalnum() else "_" for c in title[:40])
        out_path = os.path.join(OUT_DIR, f"{safe_name}.jpg")
    else:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if len(title) > 130:
        title = title[:127].rsplit(" ", 1)[0] + "..."

    accent = _hex_to_rgb(config.ACCENT_COLOR)
    bg = (17, 17, 17)
    fg = (245, 245, 245)

    img = Image.new("RGB", (WIDTH, HEIGHT), bg)
    draw = ImageDraw.Draw(img)

    # accent bar at top
    draw.rectangle([0, 0, WIDTH, 18], fill=accent)

    # brand label
    brand_font = _load_font(FONT_CANDIDATES_BOLD, 34)
    draw.text((60, 70), config.PAGE_NAME.upper(), font=brand_font, fill=accent)

    # headline text, wrapped and vertically centered-ish
    headline_font = _load_font(FONT_CANDIDATES_BOLD, 62)
    lines = textwrap.fill(title, width=24).split("\n")
    line_height = 78
    start_y = (HEIGHT - line_height * len(lines)) // 2

    for i, line in enumerate(lines):
        draw.text((60, start_y + i * line_height), line, font=headline_font, fill=fg)

    # source attribution footer
    footer_font = _load_font(FONT_CANDIDATES_REGULAR, 28)
    draw.text((60, HEIGHT - 90), f"Source: {source}", font=footer_font, fill=(160, 160, 160))

    img.save(out_path, "JPEG", quality=92)
    return out_path
