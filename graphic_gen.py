"""
Generates branded JPEG news cards (Instagram only accepts JPEG).

Every card shares one brand frame (logo/name, industry tag, footer,
film grain) so the feed looks consistent, but the layout rotates through six
designs and the accent color follows the industry (Telugu, Tamil, Kannada,
Malayalam). Box-office stories with a money figure get a big-number layout.

All artwork is drawn in code: no photos, posters or actor images are used.
Optional: put your logo at assets/logo.png (PNG with transparent background).
"""

import hashlib
import os
import re
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

import config

W, H = 1080, 1350  # 4:5 portrait, a strong Instagram feed size
OUT_DIR = "graphics"
LOGO_PATH = os.path.join("assets", "logo.png")

BG = (13, 13, 17)
PANEL = (27, 27, 34)
WHITE = (245, 245, 245)
MUTED = (150, 150, 162)
LINE = (52, 52, 62)

HEAD_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSansCondensed-Bold.ttf",
)
BOLD_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
)
REG_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "DejaVuSans.ttf",
)

TEMPLATES = ["spotlight", "filmstrip", "diagonal", "viewfinder", "ticket"]

INDUSTRIES = {
    "TELUGU": {
        "label": "TELUGU CINEMA", "color": (255, 122, 26),
        "explicit": ["telugu", "tollywood"],
        "words": ["telugu", "tollywood", "prabhas", "allu arjun", "mahesh babu", "jr ntr", "ntr",
                  "ram charan", "pawan kalyan", "chiranjeevi", "nagarjuna", "rajamouli", "pushpa",
                  "baahubali", "salaar", "devara", "nani", "vijay deverakonda", "game changer",
                  "sukumar", "trivikram", "balakrishna"],
    },
    "TAMIL": {
        "label": "TAMIL CINEMA", "color": (230, 57, 70),
        "explicit": ["tamil", "kollywood"],
        "words": ["tamil", "kollywood", "rajinikanth", "kamal haasan", "vijay", "ajith", "suriya",
                  "dhanush", "karthi", "sivakarthikeyan", "jailer", "coolie", "thug life",
                  "lokesh kanagaraj", "atlee", "nayanthara", "trisha", "mani ratnam"],
    },
    "KANNADA": {
        "label": "KANNADA CINEMA", "color": (244, 180, 0),
        "explicit": ["kannada", "sandalwood"],
        "words": ["kannada", "sandalwood", "yash", "darshan", "sudeep", "rishab shetty", "kantara",
                  "kgf", "shiva rajkumar", "puneeth rajkumar", "prashanth neel"],
    },
    "MALAYALAM": {
        "label": "MALAYALAM CINEMA", "color": (0, 184, 148),
        "explicit": ["malayalam", "mollywood"],
        "words": ["malayalam", "mollywood", "mohanlal", "mammootty", "dulquer salmaan",
                  "fahadh faasil", "prithviraj", "tovino thomas", "nivin pauly"],
    },
}

CATEGORIES = [
    ("BOX OFFICE", ["box office", "collection", "crore", "crores", "day 1", "opening", "blockbuster", "worldwide", "gross"]),
    ("TRAILER", ["trailer"]),
    ("TEASER", ["teaser", "glimpse"]),
    ("FIRST LOOK", ["first look", "poster", "motion poster"]),
    ("RELEASE DATE", ["release date", "to release", "releasing", "release on"]),
    ("OTT", ["ott", "netflix", "prime video", "hotstar", "zee5", "sonyliv", "streaming"]),
    ("SONG", ["song", "lyrical", "first single"]),
    ("BIGG BOSS", ["bigg boss"]),
    ("CASTING", ["joins", "roped in", "to star", "cast as"]),
]

MONEY_RE = re.compile(r"(?:₹\s?|Rs\.?\s?)?(\d[\d,]*(?:\.\d+)?)\s?(Cr|Crore|Crores)\b(\+)?", re.IGNORECASE)


# ---------------------------------------------------------------- helpers

@lru_cache(maxsize=64)
def _font(paths, size):
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _has_glyph(font, ch):
    try:
        return font.getmask(ch).tobytes() != font.getmask("￿").tobytes()
    except Exception:
        return True


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hash(text):
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)


def _text_w(draw, text, font):
    return draw.textlength(text, font=font)


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if not cur or _text_w(draw, trial, font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text, paths, box_w, box_h, max_size=100, min_size=44, spacing=1.14):
    """Largest font size at which the wrapped text fits the box."""
    for size in range(max_size, min_size - 1, -4):
        font = _font(paths, size)
        lines = _wrap(draw, text, font, box_w)
        line_h = int(size * spacing)
        if len(lines) * line_h <= box_h and all(_text_w(draw, ln, font) <= box_w for ln in lines):
            return font, lines, line_h
    font = _font(paths, min_size)
    line_h = int(min_size * spacing)
    lines = _wrap(draw, text, font, box_w)
    max_lines = max(1, box_h // line_h)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:-") + "..."
    return font, lines, line_h


def _draw_lines(draw, lines, font, line_h, box, align, fill=WHITE):
    """Draws lines vertically centered in box=(x, y, w, h). Returns text bottom y."""
    x, y, w, h = box
    top = y + (h - line_h * len(lines)) // 2
    for i, line in enumerate(lines):
        lw = _text_w(draw, line, font)
        lx = x + (w - lw) / 2 if align == "center" else x
        draw.text((lx, top + i * line_h), line, font=font, fill=fill)
    return top + line_h * len(lines)


def _glow(img, cx, cy, rx, ry, color, alpha, blur):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=color + (alpha,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _overlay_polygon(img, points, color, alpha):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(layer).polygon(points, fill=color + (alpha,))
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _chip(draw, x, y, text, accent, align="left"):
    font = _font(BOLD_FONTS, 30)
    tw = _text_w(draw, text, font)
    pad_x, pad_y = 24, 12
    w, h = int(tw + pad_x * 2), 30 + pad_y * 2
    if align == "center":
        x = x - w // 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=accent)
    draw.text((x + pad_x, y + pad_y - 2), text, font=font, fill=(15, 15, 18))
    return w, h


def _detect_industry(title):
    t = title.lower()
    best, best_score = None, 0
    for name, info in INDUSTRIES.items():
        score = 0
        for word in info["words"]:
            if re.search(r"\b" + re.escape(word) + r"\b", t):
                score += 3 if word in info["explicit"] else 1
        if score > best_score:
            best, best_score = name, score
    return best


def _detect_category(title):
    t = title.lower()
    for label, words in CATEGORIES:
        for word in words:
            if re.search(r"\b" + re.escape(word) + r"\b", t):
                return label
    return "CINEMA NEWS"


def _find_money(title):
    m = MONEY_RE.search(title)
    if not m:
        return None
    number = m.group(1)
    plus = "+" if m.group(3) else ""
    symbol = "₹" if _has_glyph(_font(HEAD_FONTS, 100), "₹") else "Rs "
    return f"{symbol}{number} Cr{plus}"


# ------------------------------------------------------------ backgrounds

def _bg_spotlight(accent):
    img = Image.new("RGB", (W, H), BG)
    img = _glow(img, int(W * 0.88), 260, 560, 460, accent, 120, 170)
    return _glow(img, 120, H - 160, 420, 300, accent, 45, 150)


def _bg_filmstrip(accent):
    img = Image.new("RGB", (W, H), BG)
    return _glow(img, W // 2, H // 2, 460, 520, accent, 55, 190)


DIAG_LEFT_Y, DIAG_RIGHT_Y = int(H * 0.80), int(H * 0.70)


def _bg_diagonal(accent):
    img = Image.new("RGB", (W, H), BG)
    img = _glow(img, W - 100, 200, 420, 360, accent, 60, 160)
    return _overlay_polygon(img, [(0, DIAG_LEFT_Y), (W, DIAG_RIGHT_Y), (W, H), (0, H)], accent, 40)


def _bg_viewfinder(accent):
    img = Image.new("RGB", (W, H), BG)
    return _glow(img, W // 2, H // 2, 520, 560, (255, 255, 255), 20, 200)


def _bg_ticket(accent):
    img = Image.new("RGB", (W, H), BG)
    return _glow(img, W // 2, 140, 620, 260, accent, 70, 170)


def _bg_stat(accent):
    img = Image.new("RGB", (W, H), BG)
    img = _glow(img, W // 2, 520, 620, 420, accent, 110, 190)
    return _glow(img, W // 2, H - 100, 700, 200, accent, 35, 140)


BACKGROUNDS = {
    "spotlight": _bg_spotlight, "filmstrip": _bg_filmstrip, "diagonal": _bg_diagonal,
    "viewfinder": _bg_viewfinder, "ticket": _bg_ticket, "stat": _bg_stat,
}


# --------------------------------------------------------------- layouts
# Each layout draws its decoration and returns:
#   (headline box (x, y, w, h), text alignment, chip position (x, y, align))

def _layout_spotlight(draw, accent, seed):
    return (60, 400, W - 120, 620), "left", (60, 330, "left")


def _layout_filmstrip(draw, accent, seed):
    strip_top, strip_bottom = 150, H - 135
    for side_x in (0, W - 84):
        draw.rectangle([side_x, strip_top, side_x + 84, strip_bottom], fill=(20, 20, 24))
        hole_x = side_x + 24
        for y in range(strip_top + 22, strip_bottom - 30, 72):
            draw.rounded_rectangle([hole_x, y, hole_x + 36, y + 28], radius=6, fill=(66, 66, 76))
    draw.line([(84, strip_top), (84, strip_bottom)], fill=accent, width=3)
    draw.line([(W - 84, strip_top), (W - 84, strip_bottom)], fill=accent, width=3)
    return (150, 440, W - 300, 600), "center", (W // 2, 360, "center")


def _layout_diagonal(draw, accent, seed):
    draw.line([(0, DIAG_LEFT_Y), (W, DIAG_RIGHT_Y)], fill=accent, width=10)
    return (60, 380, W - 120, 470), "left", (60, 310, "left")


def _layout_viewfinder(draw, accent, seed):
    m, length, width = 90, 100, 8
    top, bottom = 190, H - 190
    for (cx, cy, dx, dy) in ((m, top, 1, 1), (W - m, top, -1, 1), (m, bottom, 1, -1), (W - m, bottom, -1, -1)):
        draw.line([(cx, cy), (cx + dx * length, cy)], fill=accent, width=width)
        draw.line([(cx, cy), (cx, cy + dy * length)], fill=accent, width=width)
    small = _font(BOLD_FONTS, 26)
    draw.ellipse([130, 228, 154, 252], fill=(230, 40, 40))
    draw.text((166, 224), "REC", font=small, fill=WHITE)
    label = "4K  ·  24 FPS"
    draw.text((W - 130 - _text_w(draw, label, small), 224), label, font=small, fill=MUTED)
    return (150, 450, W - 300, 560), "center", (W // 2, 370, "center")


def _layout_ticket(draw, accent, seed):
    left, top, right, bottom = 60, 190, W - 60, H - 180
    draw.rounded_rectangle([left, top, right, bottom], radius=36, fill=PANEL, outline=accent, width=3)
    notch_y = 940
    for nx in (left, right):
        draw.ellipse([nx - 34, notch_y - 34, nx + 34, notch_y + 34], fill=BG, outline=accent, width=3)
    x = left + 40
    while x < right - 40:
        draw.line([(x, notch_y), (x + 18, notch_y)], fill=LINE, width=3)
        x += 32
    # ticket stub: ADMIT ONE and a decorative barcode derived from the headline
    draw.text((left + 50, notch_y + 50), "ADMIT ONE", font=_font(HEAD_FONTS, 54), fill=accent)
    draw.text((left + 50, notch_y + 120), config.PAGE_NAME.upper(), font=_font(BOLD_FONTS, 24), fill=MUTED)
    bx = right - 60
    digits = f"{seed:040d}"
    for i, d in enumerate(reversed(digits[:34])):
        bar_w = 3 + int(d) % 4
        draw.rectangle([bx - bar_w, notch_y + 48, bx, notch_y + 140], fill=WHITE)
        bx -= bar_w + 5 + (i % 3)
        if bx < right - 330:
            break
    return (left + 50, 330, right - left - 100, 580), "left", (left + 50, 262, "left")


def _layout_stat(draw, accent, seed):
    return (80, 720, W - 160, 420), "center", (W // 2, 250, "center")


LAYOUTS = {
    "spotlight": _layout_spotlight, "filmstrip": _layout_filmstrip, "diagonal": _layout_diagonal,
    "viewfinder": _layout_viewfinder, "ticket": _layout_ticket, "stat": _layout_stat,
}


# ----------------------------------------------------------- shared frame

def _frame(img, draw, accent, industry_label, source, chrome_on_top=True):
    # header: full logo lockup (mark + name), industry tag on the right
    import branding
    branding.lockup(img, 56, 34, 92)

    tag_font = _font(BOLD_FONTS, 24)
    tw = _text_w(draw, industry_label, tag_font)
    draw.rounded_rectangle([W - 60 - tw - 40, 62, W - 60, 110], radius=24, outline=accent, width=3)
    draw.text((W - 60 - tw - 20, 70), industry_label, font=tag_font, fill=accent)

    # footer: follow pill on the left, tagline on the right
    draw.line([(60, H - 112), (W - 60, H - 112)], fill=LINE, width=2)
    foot = _font(REG_FONTS, 26)
    branding.follow_pill(img, H - 100, left=60, scale=0.95)
    tagline = "SOUTH INDIAN CINEMA"
    draw.text((W - 60 - _text_w(draw, tagline, foot), H - 76), tagline, font=foot, fill=MUTED)


def _add_grain(img):
    noise = Image.effect_noise((W, H), 26).convert("RGB")
    return Image.blend(img, noise, 0.035)


# ------------------------------------------------------------------ main

def make_headline_card(title: str, source: str, out_path: str = None, style: str = None) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    if out_path is None:
        safe_name = "".join(c if c.isalnum() else "_" for c in title[:40])
        out_path = os.path.join(OUT_DIR, f"{safe_name}.jpg")
    else:
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if len(title) > 150:
        title = title[:147].rsplit(" ", 1)[0] + "..."

    industry = _detect_industry(title)
    accent = INDUSTRIES[industry]["color"] if industry else _hex_to_rgb(config.ACCENT_COLOR)
    industry_label = INDUSTRIES[industry]["label"] if industry else "SOUTH CINEMA"
    category = _detect_category(title)
    money = _find_money(title)
    seed = _hash(title)

    template = style or ("stat" if money else TEMPLATES[seed % len(TEMPLATES)])

    img = BACKGROUNDS[template](accent)
    draw = ImageDraw.Draw(img)
    box, align, (chip_x, chip_y, chip_align) = LAYOUTS[template](draw, accent, seed)

    _chip(draw, chip_x, chip_y, category, accent, chip_align)

    if template == "stat":
        number_font, number_lines, _ = _fit(draw, money, HEAD_FONTS, W - 160, 300, max_size=300, min_size=120)
        bottom = _draw_lines(draw, number_lines, number_font, int(number_font.size * 1.1),
                             (80, 330, W - 160, 340), "center", fill=accent)
        draw.rounded_rectangle([W // 2 - 70, 690, W // 2 + 70, 698], radius=4, fill=accent)
        font, lines, line_h = _fit(draw, title, HEAD_FONTS, box[2], box[3], max_size=64, min_size=40)
    else:
        font, lines, line_h = _fit(draw, title, HEAD_FONTS, box[2], box[3])
    bottom = _draw_lines(draw, lines, font, line_h, box, align)

    if template in ("spotlight", "diagonal"):
        draw.rounded_rectangle([60, bottom + 26, 60 + 150, bottom + 36], radius=5, fill=accent)

    _frame(img, draw, accent, industry_label, source)
    img = _add_grain(img)
    img.save(out_path, "JPEG", quality=92)
    return out_path


def make_poster_card(title: str, poster_path: str, out_path: str) -> str:
    """Card built around a poster you supply: blurred poster as backdrop, the
    poster itself framed in the centre, headline underneath."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if len(title) > 150:
        title = title[:147].rsplit(" ", 1)[0] + "..."

    industry = _detect_industry(title)
    accent = INDUSTRIES[industry]["color"] if industry else _hex_to_rgb(config.ACCENT_COLOR)
    industry_label = INDUSTRIES[industry]["label"] if industry else "SOUTH CINEMA"
    category = _detect_category(title)

    poster = ImageOps.exif_transpose(Image.open(poster_path)).convert("RGB")

    # backdrop: poster stretched to fill, heavily blurred and darkened
    bg = ImageOps.fit(poster, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), BG), 0.68)
    bg = Image.blend(bg, Image.new("RGB", (W, H), accent), 0.07)

    # poster, fitted into the middle area
    box_w, box_h = 900, 830
    ratio = min(box_w / poster.width, box_h / poster.height)
    pw, ph = max(1, int(poster.width * ratio)), max(1, int(poster.height * ratio))
    poster = poster.resize((pw, ph), Image.LANCZOS)
    px, py = (W - pw) // 2, 140 + (box_h - ph) // 2

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([px, py + 14, px + pw, py + ph + 14], radius=26, fill=(0, 0, 0, 200))
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    img = Image.alpha_composite(bg.convert("RGBA"), shadow).convert("RGB")

    mask = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw - 1, ph - 1], radius=22, fill=255)
    img.paste(poster, (px, py), mask)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([px - 3, py - 3, px + pw + 3, py + ph + 3], radius=25, outline=accent, width=4)

    # headline strip under the poster
    chip_y = 1000
    _chip(draw, 60, chip_y, category, accent, "left")
    font, lines, line_h = _fit(draw, title, HEAD_FONTS, W - 120, 150, max_size=48, min_size=32)
    _draw_lines(draw, lines, font, line_h, (60, chip_y + 66, W - 120, 150), "left")

    _frame(img, draw, accent, industry_label, "")
    img = _add_grain(img)
    img.save(out_path, "JPEG", quality=92)
    return out_path


def make_original_card(poster_path: str, out_path: str) -> str:
    """Official poster kept exactly as it is: scaled to fit the 4:5 frame, on a soft blurred
    backdrop made from the same poster. No headline, no overlay - the poster is the post."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    poster = ImageOps.exif_transpose(Image.open(poster_path)).convert("RGB")
    bg = ImageOps.fit(poster, (W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(45))
    bg = Image.blend(bg, Image.new("RGB", (W, H), BG), 0.55)
    ratio = min(W / poster.width, H / poster.height)
    pw, ph = max(1, int(poster.width * ratio)), max(1, int(poster.height * ratio))
    fitted = poster.resize((pw, ph), Image.LANCZOS)
    bg.paste(fitted, ((W - pw) // 2, (H - ph) // 2))
    bg.save(out_path, "JPEG", quality=94)
    return out_path


def make_photo_card(title: str, photo_path: str, out_path: str) -> str:
    """Photo-led card: your picture fills the whole frame, with a small logo on top and a short
    headline on a soft dark gradient at the bottom. Much lighter than the text cards."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if len(title) > 110:
        title = title[:107].rsplit(" ", 1)[0] + "..."
    industry = _detect_industry(title)
    accent = INDUSTRIES[industry]["color"] if industry else _hex_to_rgb(config.ACCENT_COLOR)
    label = INDUSTRIES[industry]["label"] if industry else "SOUTH CINEMA"
    category = _detect_category(title)

    photo = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
    img = ImageOps.fit(photo, (W, H), Image.LANCZOS, centering=(0.5, 0.28))  # keep faces/heads in frame

    # gradients: dark at the bottom (headline) and a light one at the top (logo)
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = shade.load()
    for y in range(H):
        a_bottom = max(0.0, (y - H * 0.50) / (H * 0.50)) ** 1.25
        a_top = max(0.0, 1 - y / 230.0) * 0.55
        a = int(min(1.0, a_bottom * 0.92 + a_top) * 255)
        for x in range(W):
            px[x, y] = (8, 8, 12, a)
    img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")
    draw = ImageDraw.Draw(img)

    # header: full logo lockup + industry tag
    import branding
    branding.lockup(img, 50, 30, 92)
    tag_font = _font(BOLD_FONTS, 24)
    tw = _text_w(draw, label, tag_font)
    draw.rounded_rectangle([W - 60 - tw - 40, 54, W - 60, 102], radius=24, fill=(10, 10, 14), outline=accent, width=3)
    draw.text((W - 60 - tw - 20, 62), label, font=tag_font, fill=accent)

    # headline block at the bottom (max 3 lines)
    font, lines, line_h = _fit(draw, title, HEAD_FONTS, W - 120, 250, max_size=70, min_size=44)
    block_h = line_h * len(lines)
    y_text = H - 150 - block_h
    _chip(draw, 60, y_text - 78, category, accent, "left")
    y = y_text
    for ln in lines:
        draw.text((60, y), ln, font=font, fill=WHITE)
        y += line_h
    branding.follow_pill(img, H - 118, cx=W // 2)

    img.save(out_path, "JPEG", quality=93)
    return out_path


def save_source_copy(src_path: str, dest_path: str) -> str:
    """Keeps a lighter copy of the original picture (used later to make a Reel from it)."""
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    im = ImageOps.exif_transpose(Image.open(src_path)).convert("RGB")
    im.thumbnail((1620, 2880), Image.LANCZOS)
    im.save(dest_path, "JPEG", quality=88)
    return dest_path
