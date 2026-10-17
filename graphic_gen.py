"""
Generates a branded text-card image for each headline instead of reposting
copyrighted press photos/stills. This is the single biggest legal-risk
reducer in the whole pipeline — it means the bot never touches an image it
doesn't have rights to.
"""

import os
import textwrap
from PIL import Image, ImageDraw, ImageFont

import config

WIDTH, HEIGHT = 1080, 1080  # IG square
OUT_DIR = "generated_graphics"

FONT_CANDIDATES_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
FONT_CANDIDATES_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(candidates, size):
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def make_headline_card(title: str, source: str, out_path: str = None) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    if out_path is None:
        safe_name = "".join(c if c.isalnum() else "_" for c in title[:40])
        out_path = os.path.join(OUT_DIR, f"{safe_name}.png")

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
    wrapped = textwrap.fill(title, width=24)
    lines = wrapped.split("\n")
    line_height = 78
    total_h = line_height * len(lines)
    start_y = (HEIGHT - total_h) // 2

    for i, line in enumerate(lines):
        draw.text((60, start_y + i * line_height), line, font=headline_font, fill=fg)

    # source attribution footer
    footer_font = _load_font(FONT_CANDIDATES_REGULAR, 28)
    draw.text((60, HEIGHT - 90), f"Source: {source}", font=footer_font, fill=(160, 160, 160))

    img.save(out_path)
    return out_path
