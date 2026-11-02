"""
Meme-style card: a bold caption on top, a photo collage in the middle, a bold caption below, on a solid dark
background. You provide the words and the photos; the bot only lays them out.

Caption highlight markup:  *word or phrase*  -> highlight colour 1 (gold),   **word or phrase**  -> colour 2.
Photos: 1 = one big picture, 2 = side by side, 3 = one big + two stacked, 4 = three stacked + one big.
"""

import re

from PIL import Image, ImageDraw, ImageOps

import branding
import graphic_gen as g

W, H = g.W, g.H
TOP_H, BOTTOM_H, FOOTER_H = 250, 230, 78
GAP = 6

# name: (background, text, highlight 1, highlight 2, thin rule colour)
STYLES = {
    "classic": ("Classic Gold", (0, 0, 0), (255, 255, 255), (255, 198, 43), (43, 212, 245), (255, 198, 43)),
    "brand":   ("Brand Red", (11, 11, 15), (255, 255, 255), (255, 77, 90), (255, 198, 43), (255, 77, 90)),
    "royal":   ("Royal Navy", (10, 16, 32), (245, 241, 230), (212, 175, 55), (110, 200, 200), (212, 175, 55)),
    "studio":  ("Studio Blue", (20, 22, 26), (255, 255, 255), (77, 163, 255), (255, 198, 43), (77, 163, 255)),
}
# styles built from the Cinema Woods logo: reel gold, leaf green, cream clapper
GOLD, CREAM = (244, 180, 26), (245, 241, 227)
STYLES.update({
    "logo":     ("Logo · Black", (12, 12, 16), CREAM, GOLD, (138, 196, 60), GOLD),
    "forest":   ("Logo · Forest", (9, 20, 12), CREAM, GOLD, (138, 196, 60), (106, 154, 42)),
    "warm":     ("Logo · Warm Black", (17, 13, 8), CREAM, GOLD, (138, 196, 60), GOLD),
    "logoexact": ("Logo · Exact leaf green", (12, 12, 16), CREAM, GOLD, (106, 154, 42), GOLD),
})
DEFAULT_STYLE = "forest"


def _tokens(text: str):
    """'Three *chart-topping albums* across' -> [(word, 0|1|2), ...] (0 = normal, 1/2 = highlights)."""
    out = []
    for part in re.split(r"(\*\*.+?\*\*|\*.+?\*)", text.strip()):
        if not part:
            continue
        kind = 2 if part.startswith("**") else 1 if part.startswith("*") else 0
        body = part.strip("*") if kind else part
        for w in body.split():
            out.append((w.upper(), kind))
    return out


def _wrap(draw, toks, font, width):
    lines, cur, cur_w = [], [], 0
    space = draw.textlength(" ", font=font)
    for w, k in toks:
        ww = draw.textlength(w, font=font)
        add = ww if not cur else ww + space
        if cur and cur_w + add > width:
            lines.append(cur)
            cur, cur_w = [(w, k)], ww
        else:
            cur.append((w, k))
            cur_w += add
    if cur:
        lines.append(cur)
    return lines


def _draw_caption(img, text, box, colours, max_lines=3, max_size=170):
    """Centred, auto-sized, multi-colour caption inside box=(x, y, w, h)."""
    draw = ImageDraw.Draw(img)
    x, y, w, h = box
    toks = _tokens(text)
    if not toks:
        return
    for size in range(max_size, 40, -4):
        font = g._font(g.TITLE_FONTS, size)
        lines = _wrap(draw, toks, font, w)
        line_h = int(size * 1.0)
        if len(lines) <= max_lines and line_h * len(lines) <= h and \
                all(sum(draw.textlength(t, font=font) for t, _ in ln) + draw.textlength(" ", font=font) * (len(ln) - 1) <= w
                    for ln in lines):
            break
    # balance the line breaks: narrowest width that still gives the same number of lines (no one-word last line)
    n, lo, hi = len(lines), int(w * 0.45), w
    while hi - lo > 6:
        mid = (lo + hi) // 2
        if len(_wrap(draw, toks, font, mid)) <= n:
            hi = mid
        else:
            lo = mid
    lines = _wrap(draw, toks, font, hi)
    top = y + (h - line_h * len(lines)) / 2
    space = draw.textlength(" ", font=font)
    for i, ln in enumerate(lines):
        lw = sum(draw.textlength(t, font=font) for t, _ in ln) + space * (len(ln) - 1)
        cx = x + (w - lw) / 2
        for t, k in ln:
            draw.text((cx, top + i * line_h), t, font=font, fill=colours[k])
            cx += draw.textlength(t, font=font) + space


def _tile(img, photo, rect):
    x, y, w, h = [int(v) for v in rect]
    tile = ImageOps.fit(photo, (w, h), Image.LANCZOS, centering=(0.5, 0.3))
    img.paste(tile, (x, y))


def _layout(n, x, y, w, h):
    """Rectangles (x, y, w, h) for n photos inside the collage area."""
    if n == 1:
        return [(x, y, w, h)]
    if n == 2:
        half = (w - GAP) // 2
        return [(x, y, half, h), (x + half + GAP, y, w - half - GAP, h)]
    if n == 3:
        big = int(w * 0.6)
        small_h = (h - GAP) // 2
        return [(x, y, big, h), (x + big + GAP, y, w - big - GAP, small_h),
                (x + big + GAP, y + small_h + GAP, w - big - GAP, h - small_h - GAP)]
    left = int(w * 0.38)
    third = (h - 2 * GAP) // 3
    rects = [(x, y + i * (third + GAP), left, third) for i in range(3)]
    rects[2] = (x, y + 2 * (third + GAP), left, h - 2 * (third + GAP))
    rects.append((x + left + GAP, y, w - left - GAP, h))
    return rects


def _seam(n, x, y, w, h):
    """Where the photos meet: (centre x, centre y) for the logo badge."""
    cy = y + int(h * 0.70)
    if n == 1:
        return x + w // 2, y + h - 70
    if n == 2:
        return x + (w - GAP) // 2 + GAP // 2, cy
    if n == 3:
        return x + int(w * 0.6) + GAP // 2, cy
    return x + int(w * 0.38) + GAP // 2, cy


def _logo_badge(img, cx, cy, bg, rule):
    """Small plate with the full logo lockup, centred on (cx, cy)."""
    scratch = Image.new("RGB", (700, 140), bg)
    lw = branding.lockup(scratch, 0, 0, 62)
    pad_x, pad_y = 22, 14
    bw, bh = int(lw + 2 * pad_x), 62 + 2 * pad_y
    x0, y0 = int(cx - bw / 2), int(cy - bh / 2)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=bh // 2 - 6, fill=bg, outline=rule, width=3)
    branding.lockup(img, x0 + pad_x, y0 + pad_y, 62)


def make_meme_card(top: str, bottom: str, photo_paths: list, out_path: str, style: str = DEFAULT_STYLE) -> str:
    name, bg, text, hi1, hi2, rule = STYLES.get(style, STYLES[DEFAULT_STYLE])
    img = Image.new("RGB", (W, H), bg)
    photos = []
    for p in photo_paths[:4]:
        photos.append(ImageOps.exif_transpose(Image.open(p)).convert("RGB"))
    if not photos:
        raise ValueError("a meme card needs at least one photo")

    colours = (text, hi1, hi2)
    pad = 40
    _draw_caption(img, top, (pad, 18, W - 2 * pad, TOP_H - 30), colours, max_lines=3)
    cy, ch = TOP_H, H - TOP_H - BOTTOM_H - FOOTER_H
    for photo, rect in zip(photos, _layout(len(photos), 0, cy, W, ch)):
        _tile(img, photo, rect)
    bx, by = _seam(len(photos), 0, cy, W, ch)
    _logo_badge(img, bx, by, bg, rule)
    _draw_caption(img, bottom, (pad, H - BOTTOM_H - FOOTER_H + 12, W - 2 * pad, BOTTOM_H - 24), colours, max_lines=3)

    # footer: thin rule, logo left, follow pill right
    fy = H - FOOTER_H
    ImageDraw.Draw(img).rectangle([pad, fy, W - pad, fy + 2], fill=rule)
    branding.follow_pill(img, fy + 20, cx=W // 2, scale=1.1)
    img.save(out_path, "JPEG", quality=93)
    return out_path
