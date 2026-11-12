"""
Cinema Woods Reel templates: animated 1080x1920 Reels drawn frame by frame with Pillow and encoded with ffmpeg.

  ott     OTT releases this week - duotone poster-wall hook with the exact date range, then one slide per film
          (poster card, platform, streaming date, language) with whip transitions on the beat
  news    Exciting news / update - headline revealed line by line on the photo, then 2-4 key points
          on frosted panels
  poster  New poster reveal - blurred teaser + riser, flash reveal on the beat drop, film name and notes
  bo      Box office - counter that runs up to the collection figure, then the breakdown table

Look: every Reel takes its colours from the poster you send (a vivid accent, a tinted dark and a light tone),
uses a magazine type system (Oswald headlines, Playfair Display italic accents, Montserrat text and tracked
labels), soft film grain and a vignette. Text in a headline wrapped in *asterisks* is highlighted in the accent;
numbers and dates are highlighted automatically.

Every Reel carries the small logo lockup + FOLLOW pill at the bottom-right of Instagram's safe area
(clear of the like/comment column and the caption) and ends on a short follow card.
Sound: reel_audio.py (a beat made in code) or a track from assets/music/, with effects on every edit point.
"""

import colorsys
import datetime
import glob
import math
import os
import random
import re
import subprocess
import tempfile
from collections import namedtuple

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import branding
import config
import graphic_gen as g

RW, RH, FPS = 1080, 1920, 30
BPM = 120
MUSIC_DIR = os.path.join("assets", "music")
FONT_DIR = os.path.join("assets", "fonts")


def _fp(name, fallback):
    return (os.path.join(FONT_DIR, name),) + tuple(fallback)


HEAD = _fp("Oswald-Bold.ttf", g.HEAD_FONTS)          # headlines, titles, numbers
HEAD_M = _fp("Oswald-Medium.ttf", g.HEAD_FONTS)      # date lines, secondary numbers
SERIF = _fp("PlayfairDisplay-BoldItalic.ttf", g.BOLD_FONTS)  # accent words ("New on", "First look")
SANS = _fp("Montserrat-SemiBold.ttf", g.BOLD_FONTS)  # body text
SANS_X = _fp("Montserrat-ExtraBold.ttf", g.BOLD_FONTS)  # tracked labels, tags
SANS_M = _fp("Montserrat-Medium.ttf", g.REG_FONTS)

WHITE = (250, 248, 244)
MUTED = (200, 198, 204)

# Instagram safe area: the top bar, the action column on the right and the caption at the bottom cover the rest
SAFE_L, SAFE_R = 64, 944
SAFE_W = SAFE_R - SAFE_L
TEXT_BOTTOM = 1440
BRAND_RIGHT, BRAND_TOP = 940, 1474

PLATFORMS = [  # (keywords, colour) - shown as a small colour square beside the name, never a logo
    (("netflix",), (229, 9, 20)),
    (("prime", "amazon"), (0, 168, 225)),
    (("hotstar", "jio", "disney"), (34, 110, 240)),
    (("zee5", "zee 5"), (150, 60, 200)),
    (("sony", "liv"), (230, 230, 235)),
    (("aha",), (255, 98, 0)),
    (("sun nxt", "sunnxt", "sun"), (255, 150, 0)),
    (("etv", "win"), (0, 170, 150)),
    (("manorama",), (230, 20, 60)),
]

LANG_INDUSTRY = {"telugu": "TELUGU", "tamil": "TAMIL", "kannada": "KANNADA", "malayalam": "MALAYALAM"}
_MONTHS_RE = r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


# ====================================================================== small helpers

def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def prog(t, start, dur):
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


def ease_out(x):
    return 1 - (1 - x) ** 3


def ease_out5(x):
    return 1 - (1 - x) ** 5


def ease_in_out(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_back(x, s=1.5):
    x -= 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


def on_beat(seconds, minimum=0.0):
    """Rounds a duration up to whole beats so cuts land on the music."""
    beat = 60.0 / BPM
    return max(minimum, math.ceil(seconds / beat - 1e-6) * beat)


def font(paths, size):
    return g._font(tuple(paths), int(size))


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def platform_color(name, fallback):
    low = (name or "").lower()
    for keys, col in PLATFORMS:
        if any(k in low for k in keys):
            return col
    return fallback


# ====================================================================== colour palette from the poster

class Palette:
    """accent: vivid colour from the poster (highlights, rules, numbers)
    dark:   the poster's dominant hue at very low brightness (gradients, backgrounds)
    light:  a soft tint of the accent (serif accent words, secondary text)"""

    def __init__(self, accent, dark=None, light=None):
        self.accent = tuple(accent)
        h, s, v = colorsys.rgb_to_hsv(*[c / 255 for c in self.accent])
        self.dark = tuple(dark) if dark else _hsv(h, min(0.55, s), 0.09)
        self.light = tuple(light) if light else mix(self.accent, (255, 250, 240), 0.62)
        self.deep = mix(self.dark, (0, 0, 0), 0.35)


def _hsv(h, s, v):
    return tuple(int(c * 255) for c in colorsys.hsv_to_rgb(h, clamp(s), clamp(v)))


def palette_from(images, fallback_text=""):
    """Reads the colours of the first picture: the most vivid sizeable colour becomes the accent,
    the most common colour (darkened) becomes the background tint."""
    ind = g._detect_industry(fallback_text or "")
    fallback = g.INDUSTRIES[ind]["color"] if ind else branding.GOLD
    if not images:
        return Palette(fallback)
    im = images[0].copy()
    im.thumbnail((140, 140))
    q = im.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    counts = q.getcolors() or []
    total = float(sum(c for c, _ in counts)) or 1.0
    cands = []
    for c, i in counts:
        rgb = tuple(pal[i * 3:i * 3 + 3])
        h, s, v = colorsys.rgb_to_hsv(*[x / 255 for x in rgb])
        cands.append((c / total, rgb, h, s, v))
    vivid = [x for x in cands if x[3] > 0.32 and x[4] > 0.35 and x[0] > 0.012]
    if vivid:
        share, rgb, h, s, v = max(vivid, key=lambda x: (x[3] * x[4]) ** 1.4 * x[0] ** 0.35)
        accent = _hsv(h, clamp(s * 1.05, 0.5, 0.88), max(v, 0.9))
    else:
        h = colorsys.rgb_to_hsv(*[c / 255 for c in fallback])[0]
        accent = fallback
    dom = max(cands, key=lambda x: x[0]) if cands else None
    if dom and dom[3] > 0.15:
        dark = _hsv(dom[2], clamp(dom[3], 0.35, 0.6), 0.10)
    else:
        dark = _hsv(h, 0.45, 0.09)
    return Palette(accent, dark)


# ====================================================================== layers (pre-rendered text / shapes)

Layer = namedtuple("Layer", "img ox oy w h")  # img RGBA; (ox, oy) = where the content starts inside img


def _measure(text, fnt, tracking=0):
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    if tracking:
        widths = [d.textlength(c, font=fnt) for c in text]
        return sum(widths) + tracking * max(0, len(text) - 1), widths
    return d.textlength(text, font=fnt), None


def _ink_box(fnt, text="HÁgy"):
    """Vertical extent of the font's ink (so text boxes hug the letters, not the font's empty leading)."""
    b = fnt.getbbox(text)
    return b[1], b[3]


def rich_layer(segments, fnt, shadow=True, tracking=0, glow=None):
    """segments: [(text, colour)] drawn one after another on a single line."""
    full = "".join(t for t, _ in segments)
    w, _ = _measure(full, fnt, tracking)
    top, bottom = _ink_box(fnt, full + "Hg")
    pad = 34 if (shadow or glow) else 6
    img = Image.new("RGBA", (int(w) + pad * 2 + 4, bottom - top + pad * 2), (0, 0, 0, 0))

    def draw_on(layer, recolor=None, dy=0):
        d = ImageDraw.Draw(layer)
        x = pad
        for text, col in segments:
            c = recolor or (tuple(col[:3]) + (255,))
            if tracking:
                for ch in text:
                    d.text((x, pad - top + dy), ch, font=fnt, fill=c)
                    x += d.textlength(ch, font=fnt) + tracking
            else:
                d.text((x, pad - top + dy), text, font=fnt, fill=c)
                x += d.textlength(text, font=fnt)

    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw_on(sh, (0, 0, 0, 170), 5)
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)))
    if glow:
        gl = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw_on(gl, tuple(glow[:3]) + (120,))
        img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(18)))
    draw_on(img)
    return Layer(img, pad, pad, int(w), bottom - top)


def text_layer(text, fnt, fill=WHITE, shadow=True, tracking=0, glow=None):
    return rich_layer([(text, fill)], fnt, shadow, tracking, glow)


def gradient_text(text, fnt, top_col, bottom_col, shadow=True):
    """Text filled with a vertical gradient (used for the big box-office figure)."""
    base = text_layer(text, fnt, WHITE, shadow=False)
    mask = base.img.getchannel("A")
    grad = Image.new("RGB", (1, base.img.height))
    for y in range(base.img.height):
        t = clamp((y - base.oy) / max(1, base.h))
        grad.putpixel((0, y), mix(top_col, bottom_col, t ** 1.2))
    fill = grad.resize(base.img.size).convert("RGBA")
    fill.putalpha(mask)
    if not shadow:
        return Layer(fill, base.ox, base.oy, base.w, base.h)
    out = Image.new("RGBA", base.img.size, (0, 0, 0, 0))
    sh = Image.new("RGBA", base.img.size, (0, 0, 0, 0))
    sh.putalpha(mask.point(lambda v: int(v * 0.7)))
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)), (0, 6))
    out.alpha_composite(fill)
    return Layer(out, base.ox, base.oy, base.w, base.h)


def label_layer(text, color, size=27, tracking=None):
    """Small tracked caps label (the magazine 'kicker')."""
    return text_layer(text.upper(), font(SANS_X, size), color, shadow=True,
                      tracking=tracking if tracking is not None else size * 0.32)


def tag_layer(text, color, size=28, fill=None):
    """Thin outlined tag with tracked caps (replaces the fat pills)."""
    fnt = font(SANS_X, size)
    tr = size * 0.22
    w, _ = _measure(text, fnt, tr)
    top, bottom = _ink_box(fnt, text)
    px, py = 22, 14
    tw, th = int(w) + px * 2, bottom - top + py * 2
    img = Image.new("RGBA", (tw + 4, th + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, tw + 1, th + 1], radius=8, fill=tuple(fill) + (255,) if fill else (0, 0, 0, 120),
                        outline=tuple(color) + (255,), width=2)
    x = 2 + px
    ink = (14, 12, 16) if fill and sum(fill) > 380 else (255, 255, 255)
    for ch in text:
        d.text((x, 2 + py - top), ch, font=fnt, fill=ink if fill else tuple(color))
        x += d.textlength(ch, font=fnt) + tr
    return Layer(img, 2, 2, tw, th)


def platform_layer(name, fallback):
    """Colour square + platform name in tracked caps."""
    col = platform_color(name, fallback)
    fnt = font(SANS_X, 32)
    text = name.upper()
    tr = 6
    w, _ = _measure(text, fnt, tr)
    top, bottom = _ink_box(fnt, text)
    h = bottom - top
    sq = h
    pad = 30
    img = Image.new("RGBA", (int(w) + sq + 18 + pad * 2, h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([pad, pad, pad + sq, pad + sq], radius=5, fill=col)
    x = pad + sq + 18
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    xx = x
    for ch in text:
        sd.text((xx, pad - top + 4), ch, font=fnt, fill=(0, 0, 0, 170))
        xx += d.textlength(ch, font=fnt) + tr
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6)))
    for ch in text:
        d.text((x, pad - top), ch, font=fnt, fill=WHITE)
        x += d.textlength(ch, font=fnt) + tr
    return Layer(img, pad, pad, int(w) + sq + 18, h)


def row_of(layers, gap=18, align="center"):
    """Places layers side by side in one layer."""
    w = sum(L.w for L in layers) + gap * (len(layers) - 1)
    h = max(L.h for L in layers)
    pad = 40
    img = Image.new("RGBA", (int(w) + pad * 2, h + pad * 2), (0, 0, 0, 0))
    x = pad
    for L in layers:
        y = pad + (h - L.h if align == "bottom" else (h - L.h) // 2)
        img.paste(L.img, (int(x - L.ox), int(y - L.oy)), L.img)
        x += L.w + gap
    return Layer(img, pad, pad, int(w), h)


def _widow(lines):
    return len(lines) > 1 and (len(lines[-1].split()) == 1 and len(lines[-1]) <= 6)


def fit_lines(text, paths, box_w, box_h, max_size, min_size, spacing=1.08, max_lines=None):
    """Largest size that fits, avoiding a lone short word on the last line ('DEVARA PART / 2')."""
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    plain = text.replace("*", "")
    fnt, lines, line_h = g._fit(d, plain, paths, box_w, box_h, max_size=max_size, min_size=min_size, spacing=spacing)
    if _widow(lines):
        for size in range(fnt.size - 4, max(min_size, int(fnt.size * 0.78)) - 1, -4):
            f2 = font(paths, size)
            l2 = g._wrap(d, plain, f2, box_w)
            if len(l2) < len(lines) and all(d.textlength(x, font=f2) <= box_w for x in l2):
                fnt, lines, line_h = f2, l2, int(size * spacing)
                break
        else:  # same size, move a word down so the last line isn't alone
            words = lines[-2].split()
            if len(words) > 1:
                lines = lines[:-2] + [" ".join(words[:-1]), words[-1] + " " + lines[-1]]
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:-") + "…"
    return fnt, lines, line_h


def highlight_lines(text, lines, accent, base=WHITE):
    """Colours *marked* words and numbers/dates in the accent, keeping the wrapped lines."""
    marked = set()
    for m in re.finditer(r"\*([^*]+)\*", text):
        marked.update(w.lower() for w in m.group(1).split())
    out = []
    for ln in lines:
        segs = []
        for k, w in enumerate(ln.split()):
            key = w.lower().strip(".,:;!?'\"")
            hot = key in marked or bool(re.search(r"\d|₹|\$", w)) or bool(re.fullmatch(rf"({_MONTHS_RE})[a-z]*", key))
            segs.append((w + (" " if k < len(ln.split()) - 1 else ""), accent if hot else base))
        out.append(segs)
    return out


def fade(img, a):
    if a >= 0.997:
        return img
    r, gg, b, al = img.split()
    return Image.merge("RGBA", (r, gg, b, al.point(lambda v: int(v * a))))


def put(canvas, L, x, y, alpha=1.0, scale=1.0):
    """Draws layer L so its content's top-left lands at (x, y); scale is around the content centre."""
    if alpha <= 0.004:
        return
    img = L.img
    cx = x - L.ox + img.width / 2
    cy = y - L.oy + img.height / 2
    if abs(scale - 1) > 0.003:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
    img = fade(img, alpha)
    canvas.paste(img, (int(round(cx - img.width / 2)), int(round(cy - img.height / 2))), img)


def put_reveal(canvas, L, x, y, u, alpha=1.0):
    """Mask reveal: the text rises into its own line box from below (u 0 -> 1)."""
    if u <= 0.001:
        return
    e = ease_out5(u)
    dy = int((1 - e) * (L.h + 12))
    top = y - 14
    bottom = y + L.h + 16
    src_top = (top - (y + dy)) + L.oy
    src_bottom = (bottom - (y + dy)) + L.oy
    box = (0, int(max(0, src_top)), L.img.width, int(min(L.img.height, src_bottom)))
    if box[3] <= box[1]:
        return
    crop = fade(L.img.crop(box), alpha)
    canvas.paste(crop, (int(x - L.ox), int(y + dy - L.oy + box[1])), crop)


def centred_x(L):
    return (RW - L.w) / 2


# ====================================================================== pictures & backgrounds

def load(path):
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def blurred(src, w, h, radius=40, dark=0.55, tint=None, tint_amt=0.35):
    small = ImageOps.fit(src, (max(8, w // 6), max(8, h // 6)), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(max(1, radius // 6)))
    big = small.resize((w, h), Image.BILINEAR)
    if tint:
        big = Image.blend(big, Image.new("RGB", (w, h), tint), tint_amt)
    return Image.blend(big, Image.new("RGB", (w, h), (0, 0, 0)), dark)


def duotone(src, pal, w, h, centering=(0.5, 0.4)):
    """Picture recoloured into the palette (deep shadows -> accent highlights): the 'designed' look."""
    im = ImageOps.fit(src, (w, h), Image.LANCZOS, centering=centering).convert("L")
    im = ImageOps.autocontrast(im, cutoff=2)
    return ImageOps.colorize(im, black=pal.deep, mid=mix(pal.dark, pal.accent, 0.55), white=pal.light)


def composed(src, w, h, pal=None, centering=(0.5, 0.36)):
    """Full-bleed for tall pictures; wide pictures sit whole on a blurred, tinted copy of themselves."""
    if src.width / src.height <= 0.72:
        return ImageOps.fit(src, (w, h), Image.LANCZOS, centering=centering)
    bg = blurred(src, w, h, dark=0.35, tint=pal.dark if pal else None, tint_amt=0.5)
    pw = w
    ph = int(src.height * pw / src.width)
    if ph > h * 0.62:
        ph = int(h * 0.62)
        pw = int(src.width * ph / src.height)
    pic = src.resize((pw, ph), Image.LANCZOS)
    bg.paste(pic, ((w - pw) // 2, int(h * 0.38 - ph / 2)))
    return bg


def designed_bg(pal, w=RW, h=RH):
    """Background for stories without a picture: palette gradient, accent glow, fine diagonal texture."""
    img = Image.new("RGB", (w, h), pal.deep)
    grad = Image.new("L", (1, h))
    for y in range(h):
        grad.putpixel((0, y), int(255 * (1 - y / h) ** 1.4))
    top = Image.new("RGB", (w, h), pal.dark)
    img.paste(top, (0, 0), grad.resize((w, h)))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([-w * 0.3, h * 0.12, w * 1.0, h * 0.62], fill=tuple(pal.accent) + (70,))
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    img.paste(glow, (0, 0), glow)
    tex = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(tex)
    for x in range(-h, w, 34):
        d.line([x, h, x + h, 0], fill=(255, 255, 255, 7), width=2)
    img.paste(tex, (0, 0), tex)
    return img


class KenBurns:
    """Slow zoom/pan over a picture prepared 1.25x larger than the frame."""
    S = 1.25

    def __init__(self, picture, z0=1.0, z1=1.12, dur=4.0, drift=(0.0, -0.25)):
        size = (int(RW * self.S), int(RH * self.S))
        self.base = picture if picture.size == size else picture.resize(size, Image.LANCZOS)
        self.z0, self.z1, self.dur, self.drift = z0, z1, dur, drift

    def frame(self, t, z=None):
        u = clamp(t / self.dur) if self.dur else 1
        z = z if z is not None else self.z0 + (self.z1 - self.z0) * u
        bw, bh = self.base.size
        cw, ch = bw / z, bh / z
        slack_x, slack_y = (bw - cw) / 2, (bh - ch) / 2
        cx = bw / 2 + self.drift[0] * slack_x * u
        cy = bh / 2 + self.drift[1] * slack_y * u
        return self.base.resize((RW, RH), Image.BILINEAR, box=(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2))


def shade_layer(col, bottom_from=0.30, bottom_max=0.97, top_max=0.65, top_to=380):
    """Full-frame darkening in the palette's dark colour: strong at the bottom (text), light at the top."""
    a = Image.new("L", (1, RH))
    for y in range(RH):
        yy = y / RH
        v = min(1.0, ((yy - bottom_from) / (0.82 - bottom_from))) ** 1.15 * bottom_max if yy > bottom_from else 0.0
        if y < top_to:
            v = max(v, (1 - y / top_to) ** 1.5 * top_max)
        a.putpixel((0, y), int(v * 255))
    lay = Image.new("RGBA", (RW, RH), tuple(col) + (255,))
    lay.putalpha(a.resize((RW, RH)))
    return lay


def vignette_layer(col=(0, 0, 0), strength=0.55):
    small = Image.new("L", (108, 192))
    px = small.load()
    for y in range(192):
        for x in range(108):
            dx, dy = (x - 54) / 54, (y - 96) / 96
            px[x, y] = int(255 * clamp((math.sqrt(dx * dx * 0.9 + dy * dy * 0.6) - 0.55) / 0.6) ** 1.6 * strength)
    lay = Image.new("RGBA", (RW, RH), tuple(col) + (255,))
    lay.putalpha(small.resize((RW, RH), Image.BICUBIC))
    return lay


def radial_glow(col, cy, rx=520, ry=380, alpha=110, cx=RW / 2):
    lay = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    ImageDraw.Draw(lay).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=tuple(col) + (alpha,))
    return lay.filter(ImageFilter.GaussianBlur(150))


def poster_card(src, max_w, max_h, glow_col=None, fade_col=None, fade_frac=0.42):
    """Poster as a card: rounded corners, hairline border, soft shadow and a faint coloured glow.
    fade_col darkens the bottom part of the poster so text can sit on it."""
    r = min(max_w / src.width, max_h / src.height)
    w, h = max(2, int(src.width * r)), max(2, int(src.height * r))
    pic = src.resize((w, h), Image.LANCZOS).convert("RGBA")
    if fade_col:
        fh = int(h * fade_frac)
        a = Image.new("L", (1, fh))
        for y in range(fh):
            u = y / fh  # quick ramp to a near-solid fade, so the poster's own title art doesn't fight our text
            a.putpixel((0, y), int(255 * min(0.97, 0.97 * (u / 0.55) ** 1.1 if u < 0.55 else 0.97)))
        shade = Image.new("RGBA", (w, fh), tuple(fade_col) + (255,))
        shade.putalpha(a.resize((w, fh)))
        pic.alpha_composite(shade, (0, h - fh))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=18, fill=255)
    pic.putalpha(mask)
    pad = 90
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    if glow_col:
        gl = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(gl).rounded_rectangle([pad - 10, pad - 10, pad + w + 10, pad + h + 10], radius=30,
                                             fill=tuple(glow_col) + (90,))
        img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(40)))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad + 10, pad + 30, pad + w - 10, pad + h + 30], radius=24,
                                         fill=(0, 0, 0, 210))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(28)))
    img.alpha_composite(pic, (pad, pad))
    ImageDraw.Draw(img).rounded_rectangle([pad, pad, pad + w - 1, pad + h - 1], radius=18,
                                          outline=(255, 255, 255, 55), width=2)
    return Layer(img, pad, pad, w, h)


def frosted(frame, box, pal, alpha=0.62):
    """Frosted-glass panel: blurs what's behind the box and tints it with the palette's dark."""
    x0, y0, x1, y1 = [int(v) for v in box]
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    region = frame.crop((x0, y0, x1, y1))
    small = region.resize((max(2, (x1 - x0) // 10), max(2, (y1 - y0) // 10)), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(2))
    region = small.resize(region.size, Image.BILINEAR)
    region = Image.blend(region, Image.new("RGB", region.size, pal.deep), alpha)
    mask = Image.new("L", region.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, region.width - 1, region.height - 1], radius=26, fill=255)
    frame.paste(region, (x0, y0), mask)
    d = ImageDraw.Draw(frame, "RGBA")
    d.rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=26, outline=(255, 255, 255, 40), width=2)


# ====================================================================== frame effects

_WHITE = Image.new("RGB", (RW, RH), (255, 255, 255))


def shake(frame, amount, t):
    if amount < 0.6:
        return frame
    m = 14
    dx = amount * math.sin(t * 97.0)
    dy = amount * math.cos(t * 71.0)
    return frame.resize((RW, RH), Image.BILINEAR, box=(m + dx, m + dy, RW - m + dx, RH - m + dy))


def flash(frame, a, col=(255, 255, 255)):
    if a <= 0.01:
        return frame
    over = _WHITE if col == (255, 255, 255) else Image.new("RGB", (RW, RH), col)
    return Image.blend(frame, over, clamp(a))


def decay(t, start, dur, peak=1.0):
    """peak -> 0 over dur, starting at start (0 before start)."""
    if t < start:
        return 0.0
    return peak * (1 - prog(t, start, dur)) ** 2


def transition(kind, a, b, u):
    if kind == "whip":
        e = ease_in_out(u)
        off = int(e * RW)
        out = Image.new("RGB", (RW, RH))
        out.paste(a, (-off, 0))
        out.paste(b, (RW - off, 0))
        k = 1 + int(math.sin(math.pi * u) * 30)
        if k > 1:
            out = out.resize((max(16, RW // k), RH // 2), Image.BILINEAR).resize((RW, RH), Image.BILINEAR)
        return out
    if kind == "flash":
        return Image.blend(a, _WHITE, min(1, u * 2) * 0.9) if u < 0.5 else Image.blend(b, _WHITE, (1 - u) * 2 * 0.9)
    if kind == "zoom":  # push into the outgoing frame while the next one fades in
        e = ease_in_out(u)
        z = 1 + 0.18 * e
        cw, ch = RW / z, RH / z
        a2 = a.resize((RW, RH), Image.BILINEAR, box=((RW - cw) / 2, (RH - ch) / 2, (RW + cw) / 2, (RH + ch) / 2))
        return Image.blend(a2, b, e)
    return Image.blend(a, b, ease_in_out(u))  # fade


# ====================================================================== brand pieces

def lockup_layer(h):
    tmp = Image.new("RGBA", (int(h * 9), int(h * 1.5)), (0, 0, 0, 0))
    right = branding.lockup(tmp, 4, 4, h)
    box = tmp.getbbox() or (0, 0, int(right), h)
    img = tmp.crop(box)
    return Layer(img, 0, 0, img.width, img.height)


def pill_layer(scale):
    tmp = Image.new("RGBA", (int(700 * scale), int(80 * scale)), (0, 0, 0, 0))
    x0, x1, y1 = branding.follow_pill(tmp, 4, left=4, scale=scale)
    img = tmp.crop((x0 - 2, 2, int(x1) + 2, int(y1) + 2))
    return Layer(img, 0, 0, img.width, img.height)


def brand_block():
    """Small logo lockup + FOLLOW pill, right-aligned, stacked. Returns (RGBA, x, y)."""
    lk, pl = lockup_layer(42), pill_layer(0.95)
    w = max(lk.w, pl.w) + 24
    h = lk.h + 10 + pl.h + 24
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    back = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(back).rounded_rectangle([6, 6, w - 6, h - 6], radius=22, fill=(0, 0, 0, 70))
    img.alpha_composite(back.filter(ImageFilter.GaussianBlur(12)))
    img.alpha_composite(lk.img, (w - 12 - lk.w, 12))
    img.alpha_composite(pl.img, (w - 12 - pl.w, 12 + lk.h + 10))
    return img, BRAND_RIGHT - w + 12, BRAND_TOP


def grain_frames(n=4, strength=10):
    """A few full-frame film-grain overlays, cycled every other frame."""
    try:
        import numpy as np
    except ImportError:
        return []
    out = []
    rng = np.random.default_rng(7)
    for _ in range(n):
        noise = rng.normal(128, 46, (RH // 2, RW // 2)).clip(0, 255).astype("uint8")
        lum = Image.fromarray(noise, "L").resize((RW, RH), Image.BILINEAR)
        lay = Image.merge("RGBA", (lum, lum, lum, Image.new("L", (RW, RH), strength)))
        out.append(lay)
    return out


# ====================================================================== timeline + encoder

class Scene:
    def __init__(self, dur, draw, enter="cut", trans=0.3, brand=True, sfx=None, brand_top=None):
        self.dur, self.draw, self.enter, self.trans, self.brand = dur, draw, enter, trans, brand
        self.brand_top = brand_top
        self.sfx = list(sfx or [])
        self.voice = None  # optional narration audio file, starts shortly after the scene does


def outro_scene(pal):
    bg = designed_bg(pal)
    lk = lockup_layer(112)
    tag = text_layer("More South cinema, every day", font(SERIF, 58), pal.light)
    pl = pill_layer(2.0)
    y0 = 720

    def draw(t):
        f = bg.copy()
        put(f, lk, centred_x(lk), y0, alpha=prog(t, 0, 0.2), scale=0.85 + 0.15 * ease_out(prog(t, 0, 0.5)))
        put_reveal(f, tag, centred_x(tag), y0 + lk.h + 56, prog(t, 0.18, 0.5))
        w = int(160 * ease_out(prog(t, 0.3, 0.4)))
        if w > 1:
            ImageDraw.Draw(f).rectangle([RW / 2 - w, y0 + lk.h + 56 + tag.h + 34,
                                         RW / 2 + w, y0 + lk.h + 56 + tag.h + 36], fill=pal.accent)
        sp = ease_back(prog(t, 0.45, 0.35)) if t < 0.8 else 1.0
        put(f, pl, centred_x(pl), y0 + lk.h + tag.h + 140, alpha=prog(t, 0.45, 0.1), scale=0.6 + 0.4 * sp)
        return f

    return Scene(on_beat(1.8), draw, enter="whip", brand=False, sfx=[(0.02, "pop"), (0.47, "pop")])


def _music_tracks():
    return [p for ext in ("mp3", "m4a", "wav", "aac", "ogg") for p in glob.glob(os.path.join(MUSIC_DIR, f"*.{ext}"))]


def render_scenes(scenes, out_path, drums_from=0.0):
    import reel_audio as ra  # needs numpy

    starts, total = [], 0.0
    for s in scenes:
        starts.append(total)
        total += s.dur
    total = round(total, 3)
    events = []
    for i, (s, st) in enumerate(zip(scenes, starts)):
        if i > 0 and s.enter in ("whip", "flash", "zoom"):
            events.append((st + s.trans / 2, "whoosh"))
        for ev in s.sfx:
            events.append((st + ev[0],) + tuple(ev[1:]))

    brand_img, bx, by = brand_block()
    grains = grain_frames()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tracks = _music_tracks()
        if tracks:
            track = random.choice(tracks)
            print(f"  [reel] music: {os.path.basename(track)} + effects")
            sfx_wav = ra.write_wav(os.path.join(tmp, "sfx.wav"), ra.sfx(total, events), fade_out=0.3)
            audio_args = ["-stream_loop", "-1", "-i", track, "-i", sfx_wav]
            afilter = (f"[1:a]atrim=0:{total},asetpts=N/SR/TB,volume=0.8,afade=t=in:d=0.3,"
                       f"afade=t=out:st={max(0, total - 1.0):.2f}:d=1.0[m];[2:a]volume=0.75[s];"
                       "[m][s]amix=inputs=2:normalize=0:duration=first[aout]")
        else:
            print("  [reel] music: generated beat + effects (add your own tracks to assets/music/)")
            mix_ = ra.beat(total, drums_from) * 0.7 + ra.sfx(total, events)
            wav = ra.write_wav(os.path.join(tmp, "audio.wav"), mix_)
            audio_args = ["-i", wav]
            afilter = "[1:a]anull[aout]"
        voices = [(st, s.voice) for s, st in zip(scenes, starts) if getattr(s, "voice", None)]
        if voices:  # narration on top, music ducked underneath
            base_inputs = sum(1 for a_ in audio_args if a_ == "-i")
            afilter = afilter.replace("[aout]", "[abase]")
            parts = [f"[abase]volume=0.42[bg]"]
            labels = ["[bg]"]
            for k, (st, vp) in enumerate(voices):
                audio_args += ["-i", vp]
                ms = int((st + 0.35) * 1000)
                parts.append(f"[{1 + base_inputs + k}:a]aresample=44100,adelay={ms}|{ms},volume=1.9[v{k}]")
                labels.append(f"[v{k}]")
            parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first[aout]")
            afilter = afilter + ";" + ";".join(parts)
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-",
               *audio_args, "-filter_complex", afilter, "-map", "0:v", "-map", "[aout]",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-profile:v", "high",
               "-maxrate", "9M", "-bufsize", "18M", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
               "-t", f"{total:.3f}", "-movflags", "+faststart", out_path]
        errlog = open(os.path.join(tmp, "ffmpeg.log"), "w+")
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errlog)
        n = int(round(total * FPS))
        idx = 0
        try:
            for fi in range(n):
                t = fi / FPS
                while idx + 1 < len(scenes) and t >= starts[idx + 1]:
                    idx += 1
                sc = scenes[idx]
                tl = t - starts[idx]
                frame = sc.draw(tl)
                if idx > 0 and sc.enter != "cut" and tl < sc.trans:
                    prev = scenes[idx - 1]
                    frame = transition(sc.enter, prev.draw(prev.dur + tl), frame, tl / sc.trans)
                    show_brand = sc.brand and prev.brand
                else:
                    show_brand = sc.brand
                if grains:
                    gr = grains[(fi // 2) % len(grains)]
                    frame.paste(gr, (0, 0), gr)
                if show_brand:
                    frame.paste(brand_img, (bx, sc.brand_top or by), brand_img)
                proc.stdin.write(frame.convert("RGB").tobytes())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        code = proc.wait()
        errlog.seek(0)
        err = errlog.read()
        errlog.close()
        if code != 0 or not os.path.exists(out_path):
            raise RuntimeError(f"ffmpeg failed: {err[-400:]}")
    print(f"  [reel] rendered {out_path} ({os.path.getsize(out_path) // 1024} KB, {total:.1f}s, {len(scenes)} scenes)")
    return total


# ====================================================================== dates

_MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def parse_day(text, today=None):
    """'Nov 1', '1 Nov', 'November 1, 2026', '01/11' (day/month) -> date, else None."""
    if not text:
        return None
    today = today or datetime.date.today()
    s = text.lower()
    day = mon = None
    m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\b", s)
    if m and m.group(2)[:3] in _MON:
        day, mon = int(m.group(1)), _MON.index(m.group(2)[:3]) + 1
    if day is None:
        m = re.search(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", s)
        if m and m.group(1)[:3] in _MON:
            day, mon = int(m.group(2)), _MON.index(m.group(1)[:3]) + 1
    if day is None:
        m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-]\d{2,4})?\b", s)
        if m:
            day, mon = int(m.group(1)), int(m.group(2))
    if day is None:
        return None
    ym = re.search(r"\b(20\d\d)\b", s)
    year = int(ym.group(1)) if ym else today.year
    try:
        d = datetime.date(year, mon, day)
    except ValueError:
        return None
    if not ym and (today - d).days > 180:
        d = d.replace(year=year + 1)
    return d


def fmt_day(d):
    return f"{_MON[d.month - 1].upper()} {d.day}"


def fmt_range(dates):
    dates = sorted(set(dates))
    if not dates:
        return ""
    a, b = dates[0], dates[-1]
    if a == b:
        return fmt_day(a)
    if a.month == b.month:
        return f"{fmt_day(a)} – {b.day}"
    return f"{fmt_day(a)} – {fmt_day(b)}"


# ====================================================================== box-office figures

FIG_RE = re.compile(r"(?i)(₹|rs\.?|inr|\$|usd)?\s*(\d[\d,]*(?:\.\d+)?)\s*"
                    r"(crores?|cr|lakhs?|million|mn|billion|bn|k|m|b|l)?\b\s*(\+)?")


class Figure:
    def __init__(self, text):
        m = FIG_RE.search(text or "")
        if not m:
            raise ValueError("no figure")
        sym, num, unit, plus = m.group(1) or "", m.group(2), (m.group(3) or "").lower(), m.group(4) or ""
        self.value = float(num.replace(",", ""))
        self.decimals = len(num.split(".")[1]) if "." in num else 0
        self.commas = "," in num
        unit_map = {"crore": "CR", "crores": "CR", "cr": "CR", "lakh": "LAKH", "lakhs": "LAKH", "l": "LAKH",
                    "million": "M", "mn": "M", "m": "M", "billion": "B", "bn": "B", "b": "B", "k": "K"}
        self.unit = unit_map.get(unit, "")
        s = sym.lower()
        if s in ("$", "usd"):
            self.symbol = "$"
        elif s or self.unit in ("CR", "LAKH"):
            self.symbol = "₹"
        else:
            self.symbol = ""
        self.plus = plus
        self.rest = (text[:m.start()] + " " + text[m.end():]).strip(" |-:,")

    def fmt(self, v=None, plus=True):
        v = self.value if v is None else v
        num = f"{v:,.{self.decimals}f}" if self.commas else f"{v:.{self.decimals}f}"
        tail = f" {self.unit}" if self.unit and self.unit not in ("M", "B", "K") else self.unit
        return f"{self.symbol}{num}{tail}{self.plus if plus else ''}"


# ====================================================================== template: OTT releases

def build_ott(spec):
    films = spec["films"][:10]
    n = len(films)
    per = on_beat(2.5)  # every film stays readable for at least ~2 s after its text has come in
    srcs = [load(f["image"]) if f.get("image") else None for f in films]
    posters = [s for s in srcs if s is not None]
    pal = palette_from(posters, " ".join(f["title"] + " " + f.get("language", "") for f in films))
    vign = vignette_layer(pal.deep, 0.7)

    # --- hook: a duotone wall of the posters drifting upwards
    hook_dur = on_beat(2.5)
    tile_w, tile_h = 360, 540
    rows = int(math.ceil((RH + 500) / tile_h)) + 1
    wall = Image.new("RGB", (RW, rows * tile_h), pal.deep)
    if posters:
        k = 0
        for r in range(rows):
            for c in range(3):
                p = posters[k % len(posters)]
                k += 1
                tile = duotone(p, pal, tile_w - 8, tile_h - 8)
                wall.paste(tile, (c * tile_w + 4, r * tile_h + 4 - (tile_h // 2 if c == 1 else 0)))
        wall = wall.filter(ImageFilter.GaussianBlur(3))
        wall = Image.blend(wall, Image.new("RGB", wall.size, pal.deep), 0.62)
    else:
        wall = designed_bg(pal, RW, rows * tile_h)
    wall.paste(vign.resize(wall.size), (0, 0), vign.resize(wall.size))
    centre = radial_glow(pal.deep, RH / 2, rx=620, ry=640, alpha=200)

    rng = spec.get("range") or ""
    L_kick = label_layer("Cinema Woods  •  OTT Guide", pal.accent, 30)
    L_serif = text_layer("New on", font(SERIF, 132), pal.light)
    L_ott = text_layer("OTT", font(HEAD, 400), WHITE, glow=pal.accent)
    L_rng = text_layer(rng, font(HEAD_M, 76), WHITE, tracking=6) if rng else None
    platforms = sorted({f.get("platform", "").strip().upper() for f in films if f.get("platform")})
    L_meta = label_layer("New this week", MUTED, 27)  # no film counts: the list is often split in two reels
    y_kick = 520
    y_serif = y_kick + L_kick.h + 60
    y_ott = y_serif + L_serif.h - 6
    y_rng = y_ott + L_ott.h + 56
    y_meta = y_rng + (L_rng.h + 52 if L_rng else 0)

    def hook(t):
        u = t / hook_dur
        top = int(380 * (1 - u) + 40)
        f = wall.crop((0, top, RW, top + RH))
        f.paste(centre, (0, 0), centre)
        put(f, L_kick, centred_x(L_kick), y_kick, alpha=prog(t, 0.0, 0.3))
        put_reveal(f, L_serif, centred_x(L_serif), y_serif, prog(t, 0.12, 0.5))
        s = 1.12 - 0.12 * ease_out5(prog(t, 0.3, 0.45))
        put(f, L_ott, centred_x(L_ott), y_ott, alpha=prog(t, 0.3, 0.15), scale=s)
        if L_rng:
            w = (L_rng.w / 2 + 90) * ease_out(prog(t, 0.75, 0.45))
            if w > 2:
                d = ImageDraw.Draw(f)
                yy = y_rng + L_rng.h / 2
                if w > L_rng.w / 2 + 34:
                    d.rectangle([RW / 2 - w - 70, yy - 1.5, RW / 2 - L_rng.w / 2 - 34, yy + 1.5], fill=pal.accent)
                    d.rectangle([RW / 2 + L_rng.w / 2 + 34, yy - 1.5, RW / 2 + w + 70, yy + 1.5], fill=pal.accent)
            put_reveal(f, L_rng, centred_x(L_rng), y_rng, prog(t, 0.8, 0.45))
        put(f, L_meta, centred_x(L_meta), y_meta, alpha=prog(t, 1.1, 0.35))
        return flash(f, decay(t, 0.42, 0.2, 0.18), pal.light)

    scenes = [Scene(hook_dur, hook, sfx=[(0.42, "impact"), (0.8, "pop")])]

    # --- one slide per film, coloured by its own poster
    for i, (film, src) in enumerate(zip(films, srcs)):
        lang = (film.get("language") or "").strip()
        ind = LANG_INDUSTRY.get(lang.lower()) or g._detect_industry(film["title"])
        fp = palette_from([src], film["title"] + " " + lang) if src is not None else pal
        title = film["title"].upper()
        fnt, lines, lh = fit_lines(title, HEAD, SAFE_W, 200, 100, 58, spacing=1.04, max_lines=2)
        L_title = [text_layer(ln, fnt, WHITE) for ln in lines]
        title_h = sum(L.h for L in L_title) + (len(L_title) - 1) * 12
        d = parse_day(film.get("date", ""))
        when = fmt_day(d) if d else (film.get("date") or "").upper()
        L_date = row_of([text_layer("Streaming from", font(SERIF, 46), fp.light),
                         text_layer(when, font(HEAD_M, 56), WHITE, tracking=3)], 16, align="bottom") if when else None
        L_plat = platform_layer(film["platform"], fp.accent) if film.get("platform") else None
        parts = [x for x in (L_plat, L_date) if x]
        L_row = row_of(parts, 34) if parts else None  # platform + streaming date on one line
        if L_row and L_row.w > SAFE_W:  # too wide for one line: stack them
            L_row = None
        lang_txt = lang.upper() if lang else (g.INDUSTRIES[ind]["label"] if ind else "")
        L_lang = label_layer(lang_txt, fp.accent, 26) if lang_txt else None
        L_idx = row_of([text_layer(f"{i + 1:02d}", font(HEAD, 64), fp.accent),
                        text_layer(f"/ {n:02d}", font(HEAD_M, 36), MUTED)], 10, align="bottom")
        gap = 22
        rows = [("title", None)]
        if L_row:
            rows.append(("row", L_row))
        else:
            rows += [(k, L) for k, L in (("plat", L_plat), ("date", L_date)) if L]
        if L_lang:
            rows.append(("lang", L_lang))
        info_h = title_h + sum(L.h for _, L in rows[1:]) + gap * (len(rows) - 1)

        # poster as large as the space allows, kept clean; the details sit in the space below it
        area_top, info_bottom = 292, 1640
        if src is not None:
            max_h = min(1150, info_bottom - area_top - 44 - info_h)
            card = poster_card(src, 940, max_h, glow_col=fp.accent)
            total = card.h + 44 + info_h
            top = area_top + max(0, (info_bottom - area_top - total) / 2)
            bgimg = blurred(src, int(RW * 1.25), int(RH * 1.25), radius=60, dark=0.5, tint=fp.dark, tint_amt=0.55)
            glow = radial_glow(fp.accent, top + card.h / 2, rx=520, ry=640, alpha=70)
            bgimg.paste(glow.resize(bgimg.size), (0, 0), glow.resize(bgimg.size))
            bg = KenBurns(bgimg, 1.0, 1.06, per)
            y = top + card.h + 44
        else:
            top = area_top
            card, bg = None, KenBurns(designed_bg(fp, int(RW * 1.25), int(RH * 1.25)), 1.0, 1.04, per)
            y = 900 - info_h / 2
        ys = {}
        for k, L in rows:
            ys[k] = y
            y += (title_h if k == "title" else L.h) + gap
        L_info = dict(rows[1:])

        def slide(t, card=card, bg=bg, L_title=L_title, L_info=L_info, L_idx=L_idx, ys=ys, fp=fp, i=i, top=top):
            f = bg.frame(t)
            if card:
                s = 0.96 + 0.04 * ease_out5(prog(t, 0, 0.45)) + 0.02 * prog(t, 0.45, per)
                put(f, card, centred_x(card), top, alpha=prog(t, 0, 0.15), scale=s)
            yy = ys["title"]
            for k, L in enumerate(L_title):
                put_reveal(f, L, centred_x(L), yy, prog(t, 0.15 + 0.07 * k, 0.4))
                yy += L.h + 12
            for k, (key, L) in enumerate(L_info.items()):
                if key == "lang":
                    put(f, L, centred_x(L), ys[key], alpha=prog(t, 0.5, 0.3))
                else:
                    put_reveal(f, L, centred_x(L), ys[key], prog(t, 0.3 + 0.08 * k, 0.4))
            dr = ImageDraw.Draw(f, "RGBA")
            u = (i + clamp(t / per)) / n
            dr.rectangle([SAFE_L, 210, SAFE_R, 213], fill=(255, 255, 255, 70))
            dr.rectangle([SAFE_L, 210, SAFE_L + int(SAFE_W * u), 213], fill=fp.accent)
            return f

        scenes.append(Scene(per, slide, enter="whip", sfx=[(0.2, "pop")], brand_top=1668))

    scenes.append(outro_scene(pal))
    return scenes, 0.0


# ====================================================================== template: exciting news / update

def _word_layers(text, fnt, max_w, line_h, color=WHITE):
    """Word layers with positions (for the word-by-word reveal)."""
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = g._wrap(d, text, fnt, max_w)
    out = []
    space = d.textlength(" ", font=fnt)
    for li, ln in enumerate(lines):
        x = 0
        for w in ln.split():
            L = text_layer(w, fnt, color, shadow=False)
            out.append((L, x, li * line_h))
            x += d.textlength(w, font=fnt) + space
    return out, len(lines)


import voiceover  # noqa: E402  (optional voice-over)

CARD_TOP, BLOCK_BOTTOM, BLOCK_GAP = 165, 1580, 26


def _progress(f, pal, u):
    dr = ImageDraw.Draw(f, "RGBA")
    dr.rectangle([SAFE_L, 128, SAFE_R, 131], fill=(255, 255, 255, 70))
    dr.rectangle([SAFE_L, 128, SAFE_L + int(SAFE_W * clamp(u)), 131], fill=pal.accent)


def _crop_for_card(src, max_aspect=0.9):
    """Wide photos are cropped to a taller frame so the picture fills the screen; posters stay whole."""
    if src is None or src.width / src.height <= max_aspect:
        return src
    return ImageOps.fit(src, (int(src.height * max_aspect), src.height), Image.LANCZOS, centering=(0.5, 0.3))


def _fit_body(text, width, max_h, start=44, floor=32, font_paths=None):
    size = start
    while True:
        pf = font(font_paths or SANS, size)
        words, nl = _word_layers(text, pf, width, int(size * 1.36))
        if nl * size * 1.36 <= max_h or size <= floor:
            return words, int(nl * size * 1.36)
        size -= 2


def _vo(spec, text, tmp_dir):
    """Voice-over for one slide when the Reel asks for it: (path, seconds) or None."""
    if not spec.get("voice") or not text:
        return None
    return voiceover.speak(text, tmp_dir)


def _story_scene(strip, pal, src, per, u0, u1, tag, heads, body_words, body_h, enter="whip", trans=0.3,
                 sfx=None, voice=None):
    """One slide: a clean picture card (no text on it) with a text panel directly below. The card takes whatever
    height the text leaves, so the screen is always filled."""
    gap_in = 12
    items_h = (tag.h + gap_in if tag else 0) + sum(L.h for L in heads) + 6 * max(0, len(heads) - 1) \
        + ((14 + body_h) if body_words else 0)
    panel_h = items_h + 76
    avail = BLOCK_BOTTOM - CARD_TOP
    card = bgimg = None
    if src is not None:
        pic = _crop_for_card(src)
        card = poster_card(pic, 952, max(380, avail - BLOCK_GAP - panel_h), glow_col=pal.accent)
        bgimg = blurred(src, int(RW * 1.25), int(RH * 1.25), radius=60, dark=0.55, tint=pal.dark, tint_amt=0.55)
    else:
        bgimg = designed_bg(pal, int(RW * 1.25), int(RH * 1.25))
    bg = KenBurns(bgimg, 1.0, 1.05, per)
    total = (card.h + BLOCK_GAP if card else 0) + panel_h
    top = CARD_TOP + max(0, (avail - total) / 2) if card else 560
    panel_y0 = top + (card.h + BLOCK_GAP if card else 0)
    step = min(0.06, 0.7 / max(1, len(body_words)))

    def draw(t):
        f = bg.frame(t)
        if card:
            sc = 0.95 + 0.05 * ease_out5(prog(t, 0, 0.5)) + 0.012 * prog(t, 0.5, per)
            put(f, card, centred_x(card), top, alpha=prog(t, 0, 0.2), scale=sc)
        e = ease_out5(prog(t, 0, 0.4))
        py = panel_y0 + (1 - e) * 50
        if e > 0.02:
            frosted(f, (SAFE_L, py, SAFE_R, py + panel_h), pal, alpha=0.5 + 0.12 * e)
            ImageDraw.Draw(f).rectangle([SAFE_L + 2, py + 28, SAFE_L + 7, py + panel_h - 28], fill=pal.accent)
        yy = py + 38
        if tag:
            put(f, tag, SAFE_L + 40 - 4, yy - 4, alpha=prog(t, 0.15, 0.3))
            yy += tag.h + gap_in
        for k, L in enumerate(heads):
            put_reveal(f, L, SAFE_L + 40, yy, prog(t, 0.25 + 0.08 * k, 0.45))
            yy += L.h + 6
        if body_words:
            yy += 8
        for w_i, (L, x, y) in enumerate(body_words):
            we = ease_out(prog(t, 0.5 + w_i * step, 0.25))
            put(f, L, SAFE_L + 40 + x, yy + y + (1 - we) * 10, alpha=we)
        f.paste(strip, (0, RH - 150), strip)
        return f

    sc_ = Scene(per, draw, enter=enter, trans=trans, brand=False, sfx=sfx or [(0.1, "pop")])
    if voice:
        sc_.voice = voice[0]
    return sc_


def _fit_per(base, voice):
    """Slide length: the reading time, or the narration plus a short pause if that is longer."""
    if voice:
        base = max(base, voice[1] + 0.9)
    return on_beat(base)


def build_news(spec):
    raw_headline = spec["headline"]
    headline = raw_headline.upper()
    points = [p for p in spec.get("points", []) if p.strip()]
    srcs = [load(p) for p in spec.get("images", []) if p]
    pal = palette_from(srcs, raw_headline + " " + " ".join(points))
    cat = (spec.get("category") or "").upper() or "SOUTH CINEMA"
    strip = _bottom_strip()
    n = len(points) + 1
    tmp = tempfile.mkdtemp(prefix="vo-")
    pic = (lambda k: srcs[k % len(srcs)] if srcs else None)

    fnt, lines, lh = fit_lines(headline, HEAD, SAFE_W - 80, 330, 104, 58, spacing=1.06, max_lines=4)
    L_lines = [rich_layer(segs, fnt) for segs in highlight_lines(headline, lines, pal.accent)]
    vo = _vo(spec, raw_headline + ".", tmp)
    hook_dur = _fit_per(max(2.8, 0.9 + 0.12 * len(L_lines) + 1.8), vo)
    scenes = [_story_scene(strip, pal, pic(0), hook_dur, 0, 1.0 / n, label_layer(cat, pal.accent, 28), L_lines, [], 0,
                           enter="cut", sfx=[(0.3, "whoosh"), (0.3 + 0.1 * (len(L_lines) - 1) + 0.25, "impact")],
                           voice=vo)]

    for j, point in enumerate(points):
        vo = _vo(spec, point, tmp)
        per = _fit_per(min(6.0, max(2.4, 1.2 + len(point.split()) * 0.28)), vo)
        words, body_h = _fit_body(point, SAFE_W - 90, 420, 52, 34)
        changes = len(srcs) > 1
        scenes.append(_story_scene(strip, pal, pic(j + 1), per, (j + 1) / n, (j + 2) / n, None, [], words, body_h,
                                   enter="whip" if changes else "zoom", trans=0.3 if changes else 0.35, voice=vo))

    scenes.append(_outro_with_voice(spec, pal, tmp))
    return scenes, 0.0


def _outro_with_voice(spec, pal, tmp):
    sc = outro_scene(pal)
    vo = _vo(spec, "Follow Cinema Woods for more South cinema updates, every day.", tmp)
    if vo:
        sc.voice = vo[0]
        sc.dur = on_beat(max(sc.dur, vo[1] + 0.8))
    return sc


# ====================================================================== template: weekly roundup

def build_roundup(spec):
    """Title slide, then one slide per story (clean picture, industry tag, headline + one-liner), then the outro."""
    items = [it for it in spec["items"] if it.get("headline")]
    n = len(items)
    srcs = [load(it["image"]) if it.get("image") else None for it in items]
    pics = [s for s in srcs if s is not None]
    pal = palette_from(pics, " ".join(it["headline"] for it in items))
    strip = _bottom_strip()
    rng = (spec.get("range") or "").upper()
    tmp = tempfile.mkdtemp(prefix="vo-")

    # --- title slide: three clean pictures, the title below them
    intro = "This week in South cinema" + (f", {spec['range']}" if spec.get("range") else "") \
        + f". Here are the top stories."
    vo = _vo(spec, intro, tmp)
    hook_dur = _fit_per(3.2, vo)
    bgk = KenBurns(designed_bg(pal, int(RW * 1.25), int(RH * 1.25)), 1.0, 1.05, hook_dur)
    cards = [poster_card(p, 330, 520, glow_col=pal.accent) for p in pics[:3]]
    L_kick = label_layer("Cinema Woods", pal.accent, 30)
    hf, hl, _ = fit_lines("WEEKLY ROUNDUP", BEBAS, SAFE_W + 40, 300, 330, 120, max_lines=1)
    L_big = text_layer(hl[0], hf, WHITE, glow=pal.accent)
    L_serif = text_layer("South cinema, this week", font(SERIF, 62), pal.light)
    L_rng = text_layer(rng, font(HEAD_M, 76), WHITE, tracking=6) if rng else None
    L_meta = label_layer("Top stories", WHITE, 28)
    txt_h = L_kick.h + 26 + L_big.h + 14 + L_serif.h + 36 + ((L_rng.h + 30) if L_rng else 0) + L_meta.h
    ch = max([c.h for c in cards] or [0])
    block = (ch + 90 if cards else 0) + txt_h
    y_top = 165 + max(0, (BLOCK_BOTTOM - 165 - block) / 2)
    ytxt = y_top + (ch + 90 if cards else 0)

    def hook(t):
        f = bgk.frame(t)
        if cards:
            gap = 22
            tot = sum(c.w for c in cards) + gap * (len(cards) - 1)
            x = (RW - tot) / 2
            for k, c in enumerate(cards):
                put(f, c, x, y_top + (ch - c.h) / 2 + (1 - ease_out5(prog(t, 0.05 * k, 0.5))) * 80,
                    alpha=prog(t, 0.05 * k, 0.25))
                x += c.w + gap
        y = ytxt
        put(f, L_kick, centred_x(L_kick), y, alpha=prog(t, 0.2, 0.3))
        y += L_kick.h + 26
        sc = 1.1 - 0.1 * ease_out5(prog(t, 0.3, 0.45))
        put(f, L_big, centred_x(L_big), y, alpha=prog(t, 0.3, 0.15), scale=sc)
        y += L_big.h + 14
        put_reveal(f, L_serif, centred_x(L_serif), y, prog(t, 0.6, 0.5))
        y += L_serif.h + 36
        if L_rng:
            put_reveal(f, L_rng, centred_x(L_rng), y, prog(t, 0.8, 0.45))
            y += L_rng.h + 30
        put(f, L_meta, centred_x(L_meta), y, alpha=prog(t, 1.1, 0.35))
        f.paste(strip, (0, RH - 150), strip)
        return flash(f, decay(t, 0.3, 0.2, 0.15), pal.light)

    h0 = Scene(hook_dur, hook, brand=False, sfx=[(0.3, "impact"), (0.7, "pop")])
    if vo:
        h0.voice = vo[0]
    scenes = [h0]

    for i, it in enumerate(items):
        src = srcs[i]
        fp = palette_from([src], it["headline"]) if src is not None else pal
        detail = (it.get("detail") or "").strip()
        ind = it.get("industry") or "SOUTH CINEMA"
        ind_col = next((v["color"] for v in g.INDUSTRIES.values() if v["label"] == ind), fp.accent)
        spoken = f"{ind.title()}. {it['headline'].rstrip('.')}." + (f" {detail}" if detail else "")
        vo = _vo(spec, spoken, tmp)
        per = _fit_per(clamp(1.8 + (len(it["headline"].split()) + len(detail.split())) / 3.6, 4.4, 9.0), vo)
        hf2, hl2, _ = fit_lines(it["headline"].upper(), HEAD, SAFE_W - 90, 200, 70, 44, spacing=1.04, max_lines=2)
        heads = [rich_layer(s, hf2) for s in highlight_lines(it["headline"].upper(), hl2, fp.accent)]
        head_h = sum(L.h for L in heads) + 6 * max(0, len(heads) - 1)
        bwords, bh = _fit_body(detail, SAFE_W - 90, max(120, 460 - head_h), 40, 30, SANS_M) if detail else ([], 0)
        scenes.append(_story_scene(strip, fp, src, per, (i + 1) / (n + 1), (i + 2) / (n + 1),
                                   tag_layer(ind, ind_col, 26), heads, bwords, bh, enter="whip", voice=vo))

    scenes.append(_outro_with_voice(spec, pal, tmp))
    return scenes, 0.0


# ====================================================================== template: poster reveal

def build_poster(spec):
    srcs = [load(p) for p in spec.get("images", []) if p]
    if not srcs:
        raise ValueError("a poster reveal needs the poster picture")
    film = spec["film"].upper()
    label = (spec.get("label") or "NEW POSTER").upper()
    notes = [n for n in spec.get("notes", []) if n.strip()][:2]
    pal = palette_from(srcs, spec["film"] + " " + " ".join(notes))

    teaser = on_beat(1.5)
    reveal = on_beat(5.0)
    extra = on_beat(2.0)
    size = (int(RW * KenBurns.S), int(RH * KenBurns.S))
    kb0 = KenBurns(composed(srcs[0], *size, pal=pal), dur=teaser + reveal)
    blur_base = blurred(srcs[0], *size, radius=70, dark=0.35, tint=pal.dark, tint_amt=0.45)
    blur0 = KenBurns(blur_base, dur=teaser)
    shade = shade_layer(pal.deep, bottom_from=0.36)

    fnt, lines, lh = fit_lines(film, HEAD, SAFE_W, 360, 150, 70, spacing=1.04, max_lines=3)
    L_lines = [text_layer(ln, fnt, WHITE) for ln in lines]
    gap_l = int(fnt.size * 0.1)
    film_h = sum(L.h for L in L_lines) + gap_l * (len(L_lines) - 1)
    L_tag = tag_layer(label, pal.accent, 30, fill=pal.accent)
    note_layers = []
    for nt in notes:
        nf, nlines, nlh = fit_lines(nt, SANS, SAFE_W, 130, 44, 32, spacing=1.3, max_lines=2)
        note_layers.append([text_layer(x, nf, (236, 234, 238)) for x in nlines])
    notes_h = sum(sum(L.h + 12 for L in ls) + 10 for ls in note_layers)
    y_film = TEXT_BOTTOM - notes_h - film_h - (30 if note_layers else 0)
    y_tag = y_film - L_tag.h - 34

    serif_word = {"FIRST LOOK": "First look", "RELEASE DATE": "Release date", "OTT POSTER": "Streaming soon"}.get(
        label, "New poster")
    L_tease = text_layer(serif_word, font(SERIF, 150), WHITE, glow=pal.accent)
    L_sub = label_layer("Cinema Woods", pal.accent, 26, tracking=14)

    def overlay_text(f, t, animate=True):
        a = prog(t, 0.75, 0.3) if animate else 1
        put(f, L_tag, SAFE_L, y_tag, alpha=a)
        yy = y_film
        for k, L in enumerate(L_lines):
            if animate:
                put_reveal(f, L, SAFE_L, yy, prog(t, 0.4 + 0.1 * k, 0.5))
            else:
                put(f, L, SAFE_L, yy)
            yy += L.h + gap_l
        yy += 30
        for n_i, ls in enumerate(note_layers):
            for L in ls:
                e = ease_out(prog(t, 1.0 + 0.25 * n_i, 0.4)) if animate else 1
                put(f, L, SAFE_L, yy + (1 - e) * 20, alpha=e)
                yy += L.h + 12
            yy += 10

    def tease(t):
        f = blur0.frame(t, 1.14 - 0.05 * t / teaser)
        s = 0.94 + 0.06 * ease_out(prog(t, 0.05, teaser))
        put(f, L_tease, centred_x(L_tease), 820, alpha=prog(t, 0.05, 0.45), scale=s)
        w = int(200 * ease_out(prog(t, 0.35, 0.6)))
        if w > 1:
            ImageDraw.Draw(f).rectangle([RW / 2 - w, 820 + L_tease.h + 40, RW / 2 + w, 820 + L_tease.h + 42],
                                        fill=pal.accent)
        put(f, L_sub, centred_x(L_sub), 820 + L_tease.h + 74, alpha=prog(t, 0.5, 0.4))
        return f

    def show(t):
        tt = teaser + t
        z = 1.12 - 0.12 * ease_out5(prog(t, 0, 0.7)) if t < 0.7 else 1.0 + 0.045 * prog(t, 0.7, reveal)
        f = kb0.frame(tt, z)
        f.paste(shade, (0, 0), shade)
        overlay_text(f, t)
        f = flash(f, decay(t, 0, 0.35, 0.85))
        return shake(f, decay(t, 0, 0.3, 7), t)

    scenes = [Scene(teaser, tease, brand=False, sfx=[(teaser, "riser", 1.4)]),
              Scene(reveal, show, enter="cut", sfx=[(0.0, "impact"), (0.75, "pop")])]
    for p in srcs[1:3]:
        kb = KenBurns(composed(p, *size, pal=pal), z0=1.08, z1=1.0, dur=extra)

        def more(t, kb=kb):
            f = kb.frame(t)
            f.paste(shade, (0, 0), shade)
            overlay_text(f, t, animate=False)
            return f

        scenes.append(Scene(extra, more, enter="flash", trans=0.3, sfx=[(0.15, "impact")]))
    scenes.append(outro_scene(pal))
    return scenes, teaser


# ====================================================================== template: box office

def build_bo(spec):
    fig = Figure(spec["figure"])
    film = (spec.get("film") or "").upper()
    label = (spec.get("label") or fig.rest or "").upper()
    rows = spec.get("rows", [])[:6]
    srcs = [load(p) for p in spec.get("images", []) if p]
    pal = palette_from(srcs, film + " " + label)
    hook_dur = on_beat(4.0)
    rows_dur = on_beat(1.0 + 0.5 * len(rows) + 1.2) if rows else 0
    size = (int(RW * KenBurns.S), int(RH * KenBurns.S))
    if srcs:
        base = duotone(srcs[0], pal, *size).filter(ImageFilter.GaussianBlur(5))
        base = Image.blend(base, Image.new("RGB", size, pal.deep), 0.55)
    else:
        base = designed_bg(pal, *size)
    vign = vignette_layer(pal.deep, 0.8).resize(size)
    base.paste(vign, (0, 0), vign)
    kb = KenBurns(base, dur=hook_dur + rows_dur, z1=1.1)
    glow = radial_glow(pal.accent, 930, alpha=95)

    L_kick = label_layer("Box Office", pal.accent, 36, tracking=14)
    if film:
        ff, flines, _ = fit_lines(film, HEAD, SAFE_W, 220, 104, 60, spacing=1.04, max_lines=2)
        L_film = [text_layer(x, ff, WHITE) for x in flines]
    else:
        L_film = []
    final = fig.fmt()
    size_n = 300
    while size_n > 120 and _measure(final, font(HEAD, size_n))[0] > 820:
        size_n -= 10
    nfont = font(HEAD, size_n)
    if label:
        lf, llines, _ = fit_lines(label, SANS_X, SAFE_W - 60, 150, 46, 30, spacing=1.2, max_lines=2)
        L_label = [text_layer(x, lf, (232, 230, 236), tracking=3) for x in llines]
    else:
        L_label = []
    L_final = gradient_text(final, nfont, pal.light, pal.accent)

    y_kick = 380
    y_film = y_kick + L_kick.h + 44
    film_h = sum(L.h + 12 for L in L_film)
    y_num = y_film + film_h + 54
    y_label = y_num + L_final.h + 50
    c0, c1 = 0.7, 2.3
    land = c1

    ticks, last_shown, last_t = [], None, -1
    for fi in range(int(hook_dur * FPS)):
        t = fi / FPS
        if c0 <= t < c1:
            shown = fig.fmt(fig.value * ease_out(prog(t, c0, c1 - c0)), plus=False)
            if shown != last_shown and t - last_t >= 0.055:
                ticks.append((t, "tick"))
                last_t = t
            last_shown = shown
    num_cache = {}

    def num_layer(text):
        if text not in num_cache:
            if len(num_cache) > 200:
                num_cache.clear()
            num_cache[text] = text_layer(text, nfont, WHITE, shadow=False)
        return num_cache[text]

    def hook(t):
        f = kb.frame(t)
        f.paste(glow, (0, 0), glow)
        put(f, L_kick, centred_x(L_kick), y_kick, alpha=prog(t, 0.05, 0.3))
        w = (L_kick.w / 2 + 110) * ease_out(prog(t, 0.05, 0.5))
        if w > L_kick.w / 2 + 30:
            d = ImageDraw.Draw(f)
            yy = y_kick + L_kick.h / 2
            d.rectangle([RW / 2 - w, yy - 1, RW / 2 - L_kick.w / 2 - 28, yy + 1], fill=pal.accent)
            d.rectangle([RW / 2 + L_kick.w / 2 + 28, yy - 1, RW / 2 + w, yy + 1], fill=pal.accent)
        yy = y_film
        for k, L in enumerate(L_film):
            put_reveal(f, L, centred_x(L), yy, prog(t, 0.2 + 0.08 * k, 0.5))
            yy += L.h + 12
        if t >= c0:
            if t < land:
                L = num_layer(fig.fmt(fig.value * ease_out(prog(t, c0, c1 - c0)), plus=False))
                put(f, L, centred_x(L), y_num, alpha=prog(t, c0, 0.12))
            else:
                s = 1.0 + 0.08 * (1 - ease_out(prog(t, land, 0.35)))
                put(f, L_final, centred_x(L_final), y_num, scale=s)
        yy = y_label
        for k, L in enumerate(L_label):
            put_reveal(f, L, centred_x(L), yy, prog(t, land + 0.15 + 0.08 * k, 0.45))
            yy += L.h + 14
        f = flash(f, decay(t, land, 0.22, 0.3), pal.light)
        return shake(f, decay(t, land, 0.3, 8), t)

    scenes = [Scene(hook_dur, hook, sfx=[*ticks, (land, "impact")])]

    if rows:
        L_top = gradient_text(final, font(HEAD, 150), pal.light, pal.accent)
        L_sub = label_layer((film or label)[:40], WHITE, 26, tracking=6)
        row_imgs = []
        for name, val in rows:
            rimg = Image.new("RGBA", (SAFE_W, 120), (0, 0, 0, 0))
            rd = ImageDraw.Draw(rimg)
            nf, nl, _ = fit_lines(name, SANS, 520, 60, 42, 30, max_lines=1)
            rd.text((24, 60), nl[0], font=nf, fill=WHITE, anchor="lm")
            rd.text((SAFE_W - 24, 60), val.upper(), font=font(HEAD, 70), fill=pal.light, anchor="rm")
            rd.rectangle([0, 117, SAFE_W, 118], fill=(255, 255, 255, 40))
            row_imgs.append(Layer(rimg, 0, 0, SAFE_W, 120))
        y0 = 300 + L_top.h + L_sub.h + 110

        def rows_scene(t):
            f = kb.frame(hook_dur + t)
            put(f, L_top, centred_x(L_top), 300, alpha=prog(t, 0, 0.25))
            put(f, L_sub, centred_x(L_sub), 300 + L_top.h + 26, alpha=prog(t, 0.1, 0.25))
            e0 = ease_out5(prog(t, 0.15, 0.4))
            if e0 > 0.02:
                frosted(f, (SAFE_L - 30, y0 - 26, SAFE_R + 30, y0 + len(row_imgs) * 132 + 14), pal,
                        alpha=0.45 + 0.25 * e0)
            for k, L in enumerate(row_imgs):
                e = ease_out5(prog(t, 0.35 + 0.5 * k, 0.45))
                put(f, L, SAFE_L + (1 - e) * 140, y0 + k * 132, alpha=e)
            return f

        scenes.append(Scene(rows_dur, rows_scene, enter="zoom", trans=0.35,
                            sfx=[(0.35 + 0.5 * k, "pop") for k in range(len(rows))]))
    scenes.append(outro_scene(pal))
    return scenes, 0.0


# ====================================================================== entry point


# ====================================================================== template: theatre releases this week

BEBAS = _fp("BebasNeue-Regular.ttf", g.HEAD_FONTS)   # big condensed titles
GLASS = (10, 10, 14)


def _stack_row(label, value, label_w, total_w, accent, size=34):
    """One credit line: tracked accent label in a fixed column, the name next to it (columns line up)."""
    lab = label_layer(label, accent, 22)
    vf, vl, _ = fit_lines(value, SANS, total_w - label_w - 24, 60, size, 24, max_lines=1)
    val = text_layer(vl[0], vf, WHITE, shadow=False)
    h = max(lab.h, val.h)
    pad = 40
    img = Image.new("RGBA", (total_w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    img.paste(lab.img, (pad - lab.ox, pad + (h - lab.h) // 2 - lab.oy), lab.img)
    img.paste(val.img, (pad + label_w + 24 - val.ox, pad + (h - val.h) // 2 - val.oy), val.img)
    return Layer(img, pad, pad, total_w, h)


def _bottom_strip():
    """Logo on the left, FOLLOW pill on the right, at the very bottom edge of the frame."""
    lk, pl = lockup_layer(50), pill_layer(1.05)
    strip = Image.new("RGBA", (RW, 150), (0, 0, 0, 0))
    shade = Image.new("L", (1, 150))
    for y in range(150):
        shade.putpixel((0, y), int(150 * (y / 149) ** 1.3))
    dark = Image.new("RGBA", (RW, 150), (0, 0, 0, 255))
    dark.putalpha(shade.resize((RW, 150)))
    strip.alpha_composite(dark)
    cy = 92
    strip.alpha_composite(lk.img, (SAFE_L - 6, cy - lk.img.height // 2))
    strip.alpha_composite(pl.img, (SAFE_R + 6 - pl.img.width, cy - pl.img.height // 2))
    return strip


def _title_panel(title, fp, w, h):
    """The slide's own big title card when a film has no poster."""
    pad = 60
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        grad.putpixel((0, y), mix(fp.dark, fp.deep, (y / h) ** 0.9))
    panel = grad.resize((w, h)).convert("RGBA")
    d = ImageDraw.Draw(panel)
    for x in range(-h, w, 40):
        d.line([x, h, x + h, 0], fill=(255, 255, 255, 5), width=2)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=22, fill=255)
    panel.putalpha(mask)
    gl = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(gl).rounded_rectangle([pad - 8, pad - 8, pad + w + 8, pad + h + 8], radius=30,
                                         fill=tuple(fp.accent) + (90,))
    img.alpha_composite(gl.filter(ImageFilter.GaussianBlur(36)))
    img.alpha_composite(panel, (pad, pad))
    ImageDraw.Draw(img).rounded_rectangle([pad, pad, pad + w - 1, pad + h - 1], radius=22,
                                          outline=tuple(fp.accent) + (200,), width=3)
    k = label_layer("Now in theatres", fp.accent, 26)
    img.alpha_composite(k.img, (pad + (w - k.w) // 2 - k.ox, pad + 70 - k.oy))
    tf, tl, tlh = fit_lines(title.upper(), BEBAS, w - 110, h - 260, 250, 90, spacing=0.98, max_lines=4)
    layers = [text_layer(t, tf, WHITE) for t in tl]
    total = sum(L.h for L in layers) + 12 * (len(layers) - 1)
    y = pad + 130 + (h - 200 - total) // 2
    for L in layers:
        img.alpha_composite(L.img, (pad + (w - L.w) // 2 - L.ox, int(y - L.oy)))
        y += L.h + 12
    return Layer(img, pad, pad, w, h)


def build_theatre(spec):
    """Title slide, then one slide per film in the order given: big poster, big title, genre + date, director, cast,
    music director and a short description - each held long enough to read - then the outro."""
    films = spec["films"][:12]
    n = len(films)
    srcs = [load(f["image"]) if f.get("image") else None for f in films]
    posters = [x for x in srcs if x is not None]
    pal = palette_from(posters, " ".join(f["title"] + " " + f.get("industry", "") for f in films))
    strip = _bottom_strip()
    inds = []
    for f in films:
        if f.get("industry") and f["industry"] not in inds:
            inds.append(f["industry"])

    # --- title slide: a bright wall of the real posters, a dark band behind the text only
    hook_dur = on_beat(3.0)
    tile_w, tile_h = 360, 540
    rows = int(math.ceil((RH + 500) / tile_h)) + 1
    wall = Image.new("RGB", (RW, rows * tile_h), pal.deep)
    if posters:
        k = 0
        for r in range(rows):
            for c in range(3):
                pp = posters[k % len(posters)]
                k += 1
                tile = ImageOps.fit(pp, (tile_w - 8, tile_h - 8), Image.LANCZOS, centering=(0.5, 0.3))
                tile = Image.blend(tile, Image.new("RGB", tile.size, pal.deep), 0.12)
                wall.paste(tile, (c * tile_w + 4, r * tile_h + 4 - (tile_h // 2 if c == 1 else 0)))
    else:
        wall = designed_bg(pal, RW, rows * tile_h)
    vg = vignette_layer(pal.deep, 0.5)
    wall.paste(vg.resize(wall.size), (0, 0), vg.resize(wall.size))
    band = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    ba = Image.new("L", (1, RH))
    for y in range(RH):
        u = abs(y - 900) / 620
        ba.putpixel((0, y), int(236 * max(0.0, 1 - u ** 2.4)))
    bl = Image.new("RGBA", (RW, RH), tuple(pal.deep) + (255,))
    bl.putalpha(ba.resize((RW, RH)))
    band.alpha_composite(bl)

    rng = (spec.get("range") or "").upper()
    L_kick = label_layer("Cinema Woods  •  Release Guide", pal.accent, 30)
    L_serif = text_layer("In theatres", font(SERIF, 140), pal.light)
    hf, hl, _ = fit_lines("THIS WEEK", BEBAS, SAFE_W + 40, 330, 400, 150, max_lines=1)
    L_big = text_layer(hl[0], hf, WHITE, glow=pal.accent)
    L_rng = text_layer(rng, font(HEAD_M, 82), WHITE, tracking=6) if rng else None
    L_meta = label_layer("New releases", WHITE, 28)  # no film counts: the list is often split in two reels
    y_kick = 560
    y_serif = y_kick + L_kick.h + 54
    y_big = y_serif + L_serif.h - 14
    y_rng = y_big + L_big.h + 44
    y_meta = y_rng + (L_rng.h + 46 if L_rng else 0)

    def hook(t):
        u = t / hook_dur
        top = int(380 * (1 - u) + 40)
        f = wall.crop((0, top, RW, top + RH))
        f.paste(band, (0, 0), band)
        put(f, L_kick, centred_x(L_kick), y_kick, alpha=prog(t, 0.0, 0.3))
        put_reveal(f, L_serif, centred_x(L_serif), y_serif, prog(t, 0.12, 0.5))
        sc = 1.12 - 0.12 * ease_out5(prog(t, 0.3, 0.45))
        put(f, L_big, centred_x(L_big), y_big, alpha=prog(t, 0.3, 0.15), scale=sc)
        if L_rng:
            w = (L_rng.w / 2 + 90) * ease_out(prog(t, 0.75, 0.45))
            if w > 2:
                dd = ImageDraw.Draw(f)
                yy = y_rng + L_rng.h / 2
                if w > L_rng.w / 2 + 34:
                    dd.rectangle([RW / 2 - w - 70, yy - 1.5, RW / 2 - L_rng.w / 2 - 34, yy + 1.5], fill=pal.accent)
                    dd.rectangle([RW / 2 + L_rng.w / 2 + 34, yy - 1.5, RW / 2 + w + 70, yy + 1.5], fill=pal.accent)
            put_reveal(f, L_rng, centred_x(L_rng), y_rng, prog(t, 0.8, 0.45))
        put(f, L_meta, centred_x(L_meta), y_meta, alpha=prog(t, 1.1, 0.35))
        f.paste(strip, (0, RH - 150), strip)
        return flash(f, decay(t, 0.42, 0.2, 0.18), pal.light)

    scenes = [Scene(hook_dur, hook, brand=False, sfx=[(0.42, "impact"), (0.8, "pop")])]

    # --- one slide per film, in the order given
    for i, (film, src) in enumerate(zip(films, srcs)):
        ind = film.get("industry") or g._detect_industry(film["title"])
        ind_col = g.INDUSTRIES[ind]["color"] if ind in g.INDUSTRIES else pal.accent
        fp = palette_from([src], film["title"] + " " + (ind or "")) if src is not None else pal
        d = parse_day(film.get("date", ""))
        when = fmt_day(d) if d else (film.get("date") or "").upper()
        genre = (film.get("genre") or "").strip()
        about = _shorten((film.get("about") or film.get("desc") or "").strip(), 18)
        creds = [(lab, (film.get(key) or "").strip())
                 for lab, key in (("DIRECTOR", "director"), ("CAST", "cast"), ("MUSIC", "music")) if (film.get(key) or "").strip()]

        # how long the slide must stay: animation + reading time for everything written on it
        words = (len(film["title"].split()) + len(genre.split()) + 2 + sum(len(v.split()) + 1 for _, v in creds)
                 + len(about.split()))
        per = on_beat(clamp(1.8 + words / 4.0, 4.6, 8.5))

        L_title = []
        title_h = 0
        if src is not None:
            tf, tl, _ = fit_lines(film["title"].upper(), BEBAS, SAFE_W, 200, 132, 70, spacing=1.0, max_lines=2)
            L_title = [text_layer(t, tf, WHITE) for t in tl]
            title_h = sum(L.h for L in L_title) + (len(L_title) - 1) * 6
        parts = []
        if when:
            parts.append(tag_layer(when, fp.accent, 34, fill=fp.accent))
        if genre:
            parts.append(text_layer(genre, font(SERIF, 50), fp.light))
        L_meta_row = row_of(parts, 26) if parts else None
        if L_meta_row and L_meta_row.w > SAFE_W:
            L_meta_row = row_of(parts[:1], 26)
        label_w = int(max([label_layer(lab, WHITE, 22).w for lab, _ in creds] or [0]))
        L_creds = [_stack_row(lab, v, label_w, SAFE_W - 40, fp.accent) for lab, v in creds]
        L_desc = []
        if about:
            df, dl, _ = fit_lines(about, SANS_M, SAFE_W - 40, 130, 38, 29, spacing=1.2, max_lines=2)
            L_desc = [text_layer(t, df, MUTED, shadow=False) for t in dl]
        gap = 22
        cred_h = sum(L.h for L in L_creds) + max(0, len(L_creds) - 1) * 12
        desc_h = sum(L.h for L in L_desc) + max(0, len(L_desc) - 1) * 8
        info_h = ((title_h + gap) if L_title else 0) + (L_meta_row.h if L_meta_row else 0) \
            + ((gap + cred_h) if L_creds else 0) + ((gap + desc_h) if L_desc else 0)

        L_idx = row_of([text_layer(f"{i + 1:02d}", font(BEBAS, 84), fp.accent),
                        text_layer(f"/ {n:02d}", font(HEAD_M, 38), MUTED)], 12, align="bottom")
        L_ind = tag_layer(ind, ind_col, 24) if ind else None

        area_top, info_bottom = 250, 1768
        if src is not None:
            max_h = info_bottom - area_top - 34 - info_h
            card = poster_card(src, 980, max_h, glow_col=fp.accent)
            bgimg = blurred(src, int(RW * 1.25), int(RH * 1.25), radius=60, dark=0.5, tint=fp.dark, tint_amt=0.55)
        else:
            card = _title_panel(film["title"], fp, 820, info_bottom - area_top - 34 - info_h)
            bgimg = designed_bg(fp, int(RW * 1.25), int(RH * 1.25))
        # details go ABOVE the poster so Instagram's channel name / caption never covers them
        avail = info_bottom - area_top - 34 - info_h
        top = area_top + info_h + 34 + max(0, (avail - card.h) / 2)
        glow = radial_glow(fp.accent, top + card.h / 2, rx=560, ry=700, alpha=80)
        bgimg.paste(glow.resize(bgimg.size), (0, 0), glow.resize(bgimg.size))
        bg = KenBurns(bgimg, 1.0, 1.05, per)
        y0 = area_top

        def slide(t, card=card, bg=bg, L_title=L_title, L_meta_row=L_meta_row, L_creds=L_creds, L_desc=L_desc,
                  L_idx=L_idx, L_ind=L_ind, fp=fp, i=i, top=top, y0=y0, gap=gap, per=per):
            f = bg.frame(t)
            sc = 0.94 + 0.06 * ease_out5(prog(t, 0, 0.5)) + 0.015 * prog(t, 0.5, per)
            put(f, card, centred_x(card), top, alpha=prog(t, 0, 0.18), scale=sc)
            yy = y0
            for k, L in enumerate(L_title):
                put_reveal(f, L, centred_x(L), yy, prog(t, 0.2 + 0.07 * k, 0.4))
                yy += L.h + 6
            if L_title:
                yy += gap - 6
            if L_meta_row:
                put_reveal(f, L_meta_row, centred_x(L_meta_row), yy, prog(t, 0.4, 0.4))
                yy += L_meta_row.h
            if L_creds:
                yy += gap
            for k, L in enumerate(L_creds):
                put_reveal(f, L, centred_x(L), yy, prog(t, 0.6 + 0.12 * k, 0.4))
                yy += L.h + 12
            if L_creds:
                yy += gap - 12
            elif L_desc:
                yy += gap
            for k, L in enumerate(L_desc):
                put_reveal(f, L, centred_x(L), yy, prog(t, 1.0 + 0.1 * k, 0.4))
                yy += L.h + 8
            if L_ind:
                put(f, L_ind, SAFE_R - L_ind.w, 176, alpha=prog(t, 0.1, 0.3))
            dr = ImageDraw.Draw(f, "RGBA")
            u = (i + clamp(t / per)) / n
            dr.rectangle([SAFE_L, 128, SAFE_R, 131], fill=(255, 255, 255, 70))
            dr.rectangle([SAFE_L, 128, SAFE_L + int(SAFE_W * u), 131], fill=fp.accent)
            f.paste(strip, (0, RH - 150), strip)
            return f

        scenes.append(Scene(per, slide, enter="whip", brand=False, sfx=[(0.2, "pop")]))

    scenes.append(outro_scene(pal))
    return scenes, 0.0


BUILDERS = {"roundup": build_roundup, "ott": build_ott, "theatre": build_theatre, "news": build_news, "poster": build_poster, "bo": build_bo}
NAMES = {"roundup": "Weekly roundup", "ott": "OTT releases", "theatre": "Theatre releases", "news": "News update", "poster": "Poster reveal", "bo": "Box office"}


def render(kind, spec, out_path):
    """Renders a Reel. Returns its length in seconds. Raises ValueError for bad input, RuntimeError for ffmpeg."""
    scenes, drums_from = BUILDERS[kind](spec)
    return render_scenes(scenes, out_path, drums_from=drums_from)


# ====================================================================== drafts -> template

def _sentences(caption):
    lines = [ln.strip() for ln in (caption or "").splitlines()]
    body = " ".join(ln for ln in lines if ln and not ln.startswith("#") and not ln.startswith("📸"))
    body = re.sub(r"#\w+|https?://\S+", "", body)
    body = re.sub(r"\s+", " ", body).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip()) > 3]


def _shorten(s, words=26):
    w = s.split()
    if len(w) <= words:
        return s
    cut = " ".join(w[:words])
    for sep in (", ", "; ", " - "):
        if sep in cut[len(cut) // 2:]:
            return cut[:cut.rindex(sep)] + "."
    return cut.rstrip(",;:") + "…"


def _overlap(a, b):
    wa, wb = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def from_draft(title, caption, images):
    """Picks a template for a bot draft (Make Reel button). Returns (kind, spec)."""
    cat = g._detect_category(title)
    imgs = [p for p in images if p and os.path.exists(p)]
    money = g._find_money(title)
    if cat == "BOX OFFICE" and money:
        label = re.sub(r"\s+", " ", g.MONEY_RE.sub("", title)).strip(" ,:-|")
        return "bo", {"figure": money, "film": "", "label": label, "rows": [], "images": imgs[:1]}
    sents = [s for s in _sentences(caption) if _overlap(s, title) < 0.7]
    if cat == "FIRST LOOK" and imgs:
        return "poster", {"film": title, "label": "FIRST LOOK" if "first look" in title.lower() else "NEW POSTER",
                          "notes": [_shorten(s, 18) for s in sents[:1]], "images": imgs[:3]}
    ind = g._detect_industry(title)
    category = cat if cat != "CINEMA NEWS" else (g.INDUSTRIES[ind]["label"] if ind else "SOUTH CINEMA")
    return "news", {"headline": title, "category": category,
                    "points": [_shorten(s) for s in sents[:3]], "images": imgs[:4]}
