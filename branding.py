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


def follow_pill(img, y, cx=None, left=None, scale=1.0):
    """'FOLLOW FOR MORE UPDATES / @handle' pill with a person-plus icon. Returns (x0, x1, y1)."""
    d = ImageDraw.Draw(img)
    f = g._font(g.BOLD_FONTS, int(26 * scale))
    f2 = g._font(g.BOLD_FONTS, int(20 * scale))
    t1, t2 = "FOLLOW FOR MORE UPDATES", "@" + config.REEL_HANDLE
    w1, w2 = g._text_w(d, t1, f), g._text_w(d, t2, f2)
    ph = int(76 * scale)
    ic = ph - 16
    pw = ic + int(24 * scale) + max(w1, w2) + int(34 * scale)
    x0 = left if left is not None else (cx if cx is not None else img.width // 2) - pw // 2
    fill = DARK + ((240,) if img.mode == "RGBA" else ())
    d.rounded_rectangle([x0, y, x0 + pw, y + ph], radius=ph // 2, fill=fill, outline=GOLD, width=3)
    ix, iy = x0 + 8, y + 8
    d.ellipse([ix, iy, ix + ic, iy + ic], fill=GOLD)
    cxp, cyp, r = ix + ic * 0.42, iy + ic * 0.38, ic * 0.15
    d.ellipse([cxp - r, cyp - r, cxp + r, cyp + r], fill=DARK)
    d.pieslice([cxp - r * 2, iy + ic * 0.52, cxp + r * 2, iy + ic * 1.25], 180, 360, fill=DARK)
    px, py, k = ix + ic * 0.78, iy + ic * 0.72, ic * 0.17
    d.ellipse([px - k * 1.25, py - k * 1.25, px + k * 1.25, py + k * 1.25], fill=(255, 255, 255), outline=GOLD, width=2)
    lw = max(3, int(ic * 0.07))
    d.line([px - k * .7, py, px + k * .7, py], fill=DARK, width=lw)
    d.line([px, py - k * .7, px, py + k * .7], fill=DARK, width=lw)
    tx = x0 + ic + int(22 * scale)
    d.text((tx, y + int(10 * scale)), t1, font=f, fill=(255, 255, 255))
    d.text((tx, y + int(42 * scale)), t2, font=f2, fill=GOLD)
    return x0, x0 + pw, y + ph
