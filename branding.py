"""Shared brand elements: the full logo lockup (mark + CINEMA WOODS) and the follow pill.
Used by every card (graphic_gen.py) and every Reel (reel_maker.py)."""
import os
from PIL import Image, ImageDraw

import config
import graphic_gen as g

GOLD = (244, 180, 26)
DARK = (12, 12, 16)


def _put(img, layer, xy):
    """Draw `layer` (RGBA) onto img, whether img is RGB or RGBA."""
    if img.mode == "RGBA":
        img.alpha_composite(layer, xy)
    else:
        img.paste(layer, xy, layer)


def lockup(img, x, y, h=92):
    """Clapper mark + 'CINEMA' (white) over 'WOODS' (gold). Returns the right edge x."""
    d = ImageDraw.Draw(img)
    right = x
    if os.path.exists(g.LOGO_PATH):
        try:
            logo = Image.open(g.LOGO_PATH).convert("RGBA")
            r = h / logo.height
            logo = logo.resize((max(1, int(logo.width * r)), h), Image.LANCZOS)
            _put(img, logo, (x, y))
            right = x + logo.width
        except Exception:
            pass
    tx = right + 16
    f = g._font(g.HEAD_FONTS, int(h * 0.52))
    for t, yy, c in (("CINEMA", y + 2, (255, 255, 255)), ("WOODS", y + h * 0.48, GOLD)):
        d.text((tx + 2, yy + 2), t, font=f, fill=(0, 0, 0, 255) if img.mode == "RGBA" else (0, 0, 0))
        d.text((tx, yy), t, font=f, fill=c)
    return tx + g._text_w(d, "CINEMA", f)


def follow_pill(img, y, cx=None, left=None, right=None, scale=1.0):
    """Minimal one-line pill: '+ FOLLOW @handle'. Returns (x0, x1, y1)."""
    d = ImageDraw.Draw(img)
    f = g._font(g.BOLD_FONTS, int(17 * scale))
    text = "FOLLOW @" + getattr(config, "REEL_HANDLE", "cinema_woods_")
    ph = int(38 * scale)
    pad = int(16 * scale)
    plus = int(24 * scale)
    pw = pad + plus + g._text_w(d, text, f) + pad
    x0 = (right - pw) if right is not None else left if left is not None else (cx if cx is not None else img.width // 2) - pw // 2
    fill = DARK + ((215,) if img.mode == "RGBA" else ())
    d.rounded_rectangle([x0, y, x0 + pw, y + ph], radius=ph // 2, fill=fill, outline=GOLD, width=2)
    px, py, k = x0 + pad + plus * 0.3, y + ph / 2, plus * 0.3
    lw = max(2, int(3 * scale))
    d.line([px - k, py, px + k, py], fill=GOLD, width=lw)
    d.line([px, py - k, px, py + k], fill=GOLD, width=lw)
    d.text((x0 + pad + plus, y + (ph - f.size) / 2 - 2 * scale), text, font=f, fill=(255, 255, 255))
    return x0, x0 + pw, y + ph
