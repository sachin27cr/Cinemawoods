"""
Cinema Woods Reel templates: animated 1080x1920 Reels drawn frame by frame with Pillow and encoded with ffmpeg.

  ott     OTT releases this week - hook with the exact date range, then one slide per film (poster card,
          platform badge, streaming date, language) with whip transitions on the beat
  news    Exciting news / update - headline slam on the photo, then 2-4 key points, one at a time
  poster  New poster reveal - blurred teaser + riser, flash reveal on the beat drop, film name and note
  bo      Box office - counter that runs up to the collection figure, then the breakdown rows

Every Reel carries the small logo lockup + FOLLOW pill at the bottom-right of Instagram's safe area
(clear of the like/comment column and the caption) and ends on a short follow card.
Sound: reel_audio.py (a beat made in code) or a track from assets/music/, with effects on every edit point.
"""

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
MUSIC_DIR = os.path.join("assets", "music")
FONT_DIR = os.path.join("assets", "fonts")

ANTON = (os.path.join(FONT_DIR, "Anton-Regular.ttf"),) + g.HEAD_FONTS
BEBAS = (os.path.join(FONT_DIR, "BebasNeue-Regular.ttf"),) + g.HEAD_FONTS
BODY = g.BOLD_FONTS

WHITE = (250, 250, 250)
MUTED = (196, 196, 206)
INK = (12, 12, 16)

# Instagram safe area: the top bar, the action column on the right and the caption at the bottom cover the rest
SAFE_L, SAFE_R = 64, 944
SAFE_W = SAFE_R - SAFE_L
TEXT_BOTTOM = 1440
BRAND_RIGHT, BRAND_TOP = 940, 1474

PLATFORMS = [  # (keywords, label colour)
    (("netflix",), (229, 9, 20)),
    (("prime", "amazon"), (0, 160, 220)),
    (("hotstar", "jio", "disney"), (18, 98, 226)),
    (("zee5", "zee 5"), (130, 47, 183)),
    (("sony", "liv"), (60, 60, 72)),
    (("aha",), (255, 98, 0)),
    (("sun nxt", "sunnxt", "sun"), (255, 136, 0)),
    (("etv", "win"), (0, 150, 136)),
    (("manorama",), (214, 0, 50)),
]

LANG_INDUSTRY = {"telugu": "TELUGU", "tamil": "TAMIL", "kannada": "KANNADA", "malayalam": "MALAYALAM"}


# ====================================================================== small helpers

def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def prog(t, start, dur):
    return clamp((t - start) / dur) if dur > 0 else float(t >= start)


def ease_out(x):
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_back(x, s=1.9):
    x -= 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


BPM = 120


def on_beat(seconds, minimum=0.0):
    """Rounds a duration up to whole beats so cuts land on the music."""
    beat = 60.0 / BPM
    return max(minimum, math.ceil(seconds / beat - 1e-6) * beat)


def font(paths, size):
    return g._font(paths, int(size))


def accent_for(text, default=None):
    ind = g._detect_industry(text or "")
    if ind:
        return g.INDUSTRIES[ind]["color"]
    return default or g._hex_to_rgb(config.ACCENT_COLOR)


def platform_color(name, fallback):
    low = (name or "").lower()
    for keys, col in PLATFORMS:
        if any(k in low for k in keys):
            return col
    return fallback


# ====================================================================== layers (pre-rendered text / shapes)

Layer = namedtuple("Layer", "img ox oy w h")  # img RGBA; (ox, oy) = where the content starts inside img


def _measure(text, fnt, tracking=0):
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    if tracking:
        widths = [d.textlength(c, font=fnt) for c in text]
        return sum(widths) + tracking * max(0, len(text) - 1), widths
    return d.textlength(text, font=fnt), None


def text_layer(text, fnt, fill=WHITE, shadow=True, tracking=0, stroke=0):
    w, widths = _measure(text, fnt, tracking)
    asc, desc = fnt.getmetrics()
    pad = 26 if shadow else 6 + stroke
    img = Image.new("RGBA", (int(w) + pad * 2 + 2, asc + desc + pad * 2), (0, 0, 0, 0))

    def draw_on(layer, col, dx, dy):
        d = ImageDraw.Draw(layer)
        x, y = pad + dx, pad + dy
        if tracking:
            for c, cw in zip(text, widths):
                d.text((x, y), c, font=fnt, fill=col, stroke_width=stroke, stroke_fill=(0, 0, 0, 230))
                x += cw + tracking
        else:
            d.text((x, y), text, font=fnt, fill=col, stroke_width=stroke, stroke_fill=(0, 0, 0, 230))

    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw_on(sh, (0, 0, 0, 200), 0, 6)
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(9)))
    draw_on(img, tuple(fill[:3]) + (255,), 0, 0)
    return Layer(img, pad, pad, int(w), asc + desc)


def chip_layer(text, bg, fg=INK, size=46, pad_x=26, pad_y=12, outline=None, fnt_paths=BEBAS):
    fnt = font(fnt_paths, size)
    w, _ = _measure(text, fnt)
    asc, desc = fnt.getmetrics()
    h = asc + desc + pad_y * 2 - 8
    cw = int(w) + pad_x * 2
    img = Image.new("RGBA", (cw + 4, h + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = tuple(bg[:3]) + ((bg[3],) if len(bg) > 3 else (255,))
    d.rounded_rectangle([2, 2, cw + 1, h + 1], radius=h // 2, fill=fill,
                        outline=outline, width=3 if outline else 0)
    d.text((2 + pad_x, 2 + pad_y - 2), text, font=fnt, fill=fg)
    return Layer(img, 2, 2, cw, h)


def row_of(layers, gap=18):
    """Places layers side by side in one layer (vertically centred)."""
    w = sum(L.w for L in layers) + gap * (len(layers) - 1)
    h = max(L.h for L in layers)
    pad = 30
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    x = pad
    for L in layers:
        y = pad + (h - L.h) // 2
        img.paste(L.img, (int(x - L.ox), int(y - L.oy)), L.img)
        x += L.w + gap
    return Layer(img, pad, pad, w, h)


def lines_fit(text, paths, box_w, box_h, max_size, min_size, spacing=1.08, max_lines=None):
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    fnt, lines, line_h = g._fit(d, text, paths, box_w, box_h, max_size=max_size, min_size=min_size, spacing=spacing)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .,;:-") + "…"
    return fnt, lines, line_h


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


def centred_x(L):
    return (RW - L.w) / 2


# ====================================================================== pictures & backgrounds

def load(path):
    return ImageOps.exif_transpose(Image.open(path)).convert("RGB")


def blurred(src, w, h, radius=40, dark=0.55, tint=None):
    small = ImageOps.fit(src, (max(8, w // 6), max(8, h // 6)), Image.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(max(1, radius // 6)))
    big = small.resize((w, h), Image.BILINEAR)
    big = Image.blend(big, Image.new("RGB", (w, h), INK), dark)
    if tint:
        big = Image.blend(big, Image.new("RGB", (w, h), tint), 0.10)
    return big


def composed(src, w, h, centering=(0.5, 0.36)):
    """Full-bleed for tall pictures; wide pictures sit whole on a blurred copy of themselves."""
    if src.width / src.height <= 0.72:
        return ImageOps.fit(src, (w, h), Image.LANCZOS, centering=centering)
    bg = blurred(src, w, h, dark=0.45)
    pw = w
    ph = int(src.height * pw / src.width)
    if ph > h * 0.62:
        ph = int(h * 0.62)
        pw = int(src.width * ph / src.height)
    pic = src.resize((pw, ph), Image.LANCZOS)
    bg.paste(pic, ((w - pw) // 2, int(h * 0.40 - ph / 2)))
    return bg


def designed_bg(accent, w=RW, h=RH):
    """Background for stories without a picture: dark gradient, accent glow, faint diagonal stripes."""
    img = Image.new("RGB", (w, h), (14, 14, 19))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(glow)
    d.ellipse([-w * 0.4, h * 0.05, w * 1.1, h * 0.75], fill=tuple(accent) + (95,))
    img.paste(glow.filter(ImageFilter.GaussianBlur(160)), (0, 0), glow.filter(ImageFilter.GaussianBlur(160)))
    stripes = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(stripes)
    for x in range(-h, w, 90):
        d.line([x, h, x + h, 0], fill=(255, 255, 255, 10), width=26)
    img.paste(stripes, (0, 0), stripes)
    return img


class KenBurns:
    """Slow zoom/pan over a picture prepared 1.25x larger than the frame."""
    S = 1.25

    def __init__(self, picture, z0=1.0, z1=1.12, dur=4.0, drift=(0.0, -0.25)):
        self.base = picture.resize((int(RW * self.S), int(RH * self.S)), Image.LANCZOS) \
            if picture.size != (int(RW * self.S), int(RH * self.S)) else picture
        self.z0, self.z1, self.dur, self.drift = z0, z1, dur, drift

    @classmethod
    def from_source(cls, src, **kw):
        return cls(composed(src, int(RW * cls.S), int(RH * cls.S)), **kw)

    def frame(self, t, z=None):
        u = clamp(t / self.dur) if self.dur else 1
        z = z if z is not None else self.z0 + (self.z1 - self.z0) * u
        bw, bh = self.base.size
        cw, ch = bw / z, bh / z
        slack_x, slack_y = (bw - cw) / 2, (bh - ch) / 2
        cx = bw / 2 + self.drift[0] * slack_x * u
        cy = bh / 2 + self.drift[1] * slack_y * u
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        return self.base.resize((RW, RH), Image.BILINEAR, box=box)


def shade_layer(top_from=None, bottom_from=0.45, bottom_max=0.94, top_max=0.55, top_to=330):
    """Full-frame RGBA darkening: strong at the bottom (text), light at the top (Instagram bar)."""
    col = Image.new("L", (1, RH))
    for y in range(RH):
        a = 0.0
        yy = y / RH
        if yy > bottom_from:
            a = ((yy - bottom_from) / (1 - bottom_from)) ** 1.1 * bottom_max
        if top_from is not False and y < top_to:
            a = max(a, (1 - y / top_to) * top_max)
        col.putpixel((0, y), int(a * 255))
    lay = Image.new("RGBA", (RW, RH), (6, 6, 10, 255))
    lay.putalpha(col.resize((RW, RH)))
    return lay


def radial_glow(accent, cy, rx=520, ry=360, alpha=120):
    lay = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    ImageDraw.Draw(lay).ellipse([RW / 2 - rx, cy - ry, RW / 2 + rx, cy + ry], fill=tuple(accent) + (alpha,))
    return lay.filter(ImageFilter.GaussianBlur(140))


def poster_card(src, max_w, max_h):
    """Poster as a framed card: rounded corners, thin light border, soft shadow."""
    r = min(max_w / src.width, max_h / src.height)
    w, h = max(2, int(src.width * r)), max(2, int(src.height * r))
    pic = src.resize((w, h), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=26, fill=255)
    pic.putalpha(mask)
    pad = 60
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([pad, pad + 18, pad + w, pad + h + 18], radius=30, fill=(0, 0, 0, 200))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(24)))
    img.alpha_composite(pic, (pad, pad))
    ImageDraw.Draw(img).rounded_rectangle([pad, pad, pad + w - 1, pad + h - 1], radius=26,
                                          outline=(255, 255, 255, 70), width=3)
    return Layer(img, pad, pad, w, h)


# ====================================================================== frame effects

_WHITE = Image.new("RGB", (RW, RH), (255, 255, 255))


def shake(frame, amount, t):
    if amount < 0.6:
        return frame
    m = 18
    dx = amount * math.sin(t * 97.0)
    dy = amount * math.cos(t * 71.0)
    return frame.resize((RW, RH), Image.BILINEAR, box=(m + dx, m + dy, RW - m + dx, RH - m + dy))


def flash(frame, a):
    return Image.blend(frame, _WHITE, clamp(a)) if a > 0.01 else frame


def decay(t, start, dur, peak=1.0):
    """1 -> 0 over dur, starting at start (0 before start)."""
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
        return Image.blend(a, _WHITE, min(1, u * 2) * 0.95) if u < 0.5 else Image.blend(b, _WHITE, (1 - u) * 2 * 0.95)
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
    lk, pl = lockup_layer(44), pill_layer(1.0)
    w = max(lk.w, pl.w) + 24
    h = lk.h + 10 + pl.h + 24
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    back = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(back).rounded_rectangle([6, 6, w - 6, h - 6], radius=22, fill=(0, 0, 0, 80))
    img.alpha_composite(back.filter(ImageFilter.GaussianBlur(10)))
    img.alpha_composite(lk.img, (w - 12 - lk.w, 12))
    img.alpha_composite(pl.img, (w - 12 - pl.w, 12 + lk.h + 10))
    return img, BRAND_RIGHT - w + 12, BRAND_TOP


# ====================================================================== timeline + encoder

class Scene:
    def __init__(self, dur, draw, enter="cut", trans=0.3, brand=True, sfx=None):
        self.dur, self.draw, self.enter, self.trans, self.brand = dur, draw, enter, trans, brand
        self.sfx = list(sfx or [])


def outro_scene(accent):
    bg = designed_bg(accent)
    lk = lockup_layer(118)
    tag = text_layer("DAILY SOUTH CINEMA UPDATES", font(BEBAS, 58), MUTED, shadow=False, tracking=3)
    pl = pill_layer(2.1)

    def draw(t):
        f = bg.copy()
        s = ease_back(prog(t, 0.0, 0.4)) if t < 0.4 else 1.0
        put(f, lk, centred_x(lk), 760, alpha=prog(t, 0, 0.12), scale=0.6 + 0.4 * s)
        put(f, tag, centred_x(tag), 760 + lk.h + 48, alpha=prog(t, 0.2, 0.25))
        sp = ease_back(prog(t, 0.4, 0.35)) if t < 0.75 else 1.0
        put(f, pl, centred_x(pl), 760 + lk.h + 140, alpha=prog(t, 0.4, 0.1), scale=0.5 + 0.5 * sp)
        return f

    return Scene(on_beat(1.6), draw, enter="whip", brand=False, sfx=[(0.02, "pop"), (0.42, "pop")])


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
        if i > 0 and s.enter in ("whip", "flash"):
            events.append((st + s.trans / 2, "whoosh"))
        for ev in s.sfx:
            events.append((st + ev[0],) + tuple(ev[1:]))

    brand_img, bx, by = brand_block()
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
            mix = ra.beat(total, drums_from) * 0.7 + ra.sfx(total, events)
            wav = ra.write_wav(os.path.join(tmp, "audio.wav"), mix)
            audio_args = ["-i", wav]
            afilter = "[1:a]anull[aout]"
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-",
               *audio_args, "-filter_complex", afilter, "-map", "0:v", "-map", "[aout]",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high",
               "-maxrate", "8M", "-bufsize", "16M", "-pix_fmt", "yuv420p", "-r", str(FPS),
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
                if show_brand:
                    frame.paste(brand_img, (bx, by), brand_img)
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
    base_accent = accent_for(" ".join(f["title"] + " " + f.get("language", "") for f in films))
    per = on_beat(2.0 if n <= 5 else 1.5)
    srcs = [load(f["image"]) if f.get("image") else None for f in films]
    posters = [s for s in srcs if s is not None]

    # --- hook: scrolling poster wall, OTT stamp, date range
    if posters:
        tile_w, tile_h = 360, 540
        rows = int(math.ceil((RH + 500) / tile_h)) + 1
        wall = Image.new("RGB", (RW, rows * tile_h), INK)
        k = 0
        for r in range(rows):
            for c in range(3):
                p = posters[k % len(posters)]
                k += 1
                wall.paste(ImageOps.fit(p, (tile_w, tile_h), Image.BILINEAR), (c * tile_w, r * tile_h))
        wall = wall.filter(ImageFilter.GaussianBlur(4))
        wall = Image.blend(wall, Image.new("RGB", wall.size, INK), 0.62)
        wall = Image.blend(wall, Image.new("RGB", wall.size, base_accent), 0.08)
    else:
        wall = designed_bg(base_accent, RW, RH + 500)
    hook_dur = on_beat(2.0)
    rng = spec.get("range") or ""
    L_ott = text_layer("OTT", font(ANTON, 300), base_accent)
    L_rel = text_layer("RELEASES", font(ANTON, 150), WHITE)
    L_week = text_layer("THIS WEEK", font(ANTON, 150), WHITE)
    L_rng = chip_layer(rng, base_accent, INK, size=70, pad_x=34) if rng else None
    platforms = sorted({f.get("platform", "").strip().upper() for f in films if f.get("platform")})
    meta = f"{n} FILM{'S' if n != 1 else ''}" + (f"  •  {len(platforms)} PLATFORM{'S' if len(platforms) != 1 else ''}"
                                                  if platforms else "")
    L_meta = text_layer(meta, font(BEBAS, 52), MUTED, shadow=True, tracking=2)
    stack = [L_ott, L_rel, L_week] + ([L_rng] if L_rng else []) + [L_meta]
    gaps = [-36, -18, 34, 26]
    total_h = sum(L.h for L in stack) + sum(gaps[:len(stack) - 1])
    ys, y = [], 880 - total_h / 2
    for i, L in enumerate(stack):
        ys.append(y)
        y += L.h + (gaps[i] if i < len(gaps) else 0)
    scroll = 420

    def hook(t):
        u = t / hook_dur
        top = int(scroll * (1 - u) * 0.6 + 40)
        f = wall.crop((0, top, RW, top + RH))
        land = 0.32
        s_ott = 1.8 - 0.8 * ease_out(prog(t, 0.04, land - 0.04))
        put(f, L_ott, centred_x(L_ott), ys[0], alpha=prog(t, 0.04, 0.08), scale=s_ott)
        e = ease_out(prog(t, 0.36, 0.28))
        put(f, L_rel, centred_x(L_rel) - (1 - e) * 900, ys[1], alpha=prog(t, 0.36, 0.1))
        e = ease_out(prog(t, 0.52, 0.28))
        put(f, L_week, centred_x(L_week) + (1 - e) * 900, ys[2], alpha=prog(t, 0.52, 0.1))
        j = 3
        if L_rng:
            sp = ease_back(prog(t, 0.8, 0.3)) if t < 1.1 else 1
            put(f, L_rng, centred_x(L_rng), ys[3], alpha=prog(t, 0.8, 0.08), scale=0.3 + 0.7 * sp)
            j = 4
        put(f, L_meta, centred_x(L_meta), ys[j], alpha=prog(t, 1.05, 0.25))
        f = flash(f, decay(t, land, 0.18, 0.55))
        return shake(f, decay(t, land, 0.35, 16), t)

    scenes = [Scene(hook_dur, hook, sfx=[(0.32, "impact"), (0.36, "pop"), (0.52, "pop"), (0.8, "pop")])]

    # --- one slide per film
    for i, (film, src) in enumerate(zip(films, srcs)):
        lang = (film.get("language") or "").strip()
        ind = LANG_INDUSTRY.get(lang.lower()) or g._detect_industry(film["title"])
        accent = g.INDUSTRIES[ind]["color"] if ind else base_accent
        title = film["title"].upper()
        fnt, lines, lh = lines_fit(title, ANTON, SAFE_W, 230, 104, 56, spacing=1.06, max_lines=2)
        L_title = [text_layer(ln, fnt, WHITE) for ln in lines]
        title_h = lh * len(lines)
        badges = []
        if film.get("platform"):
            badges.append(chip_layer(film["platform"].upper(), platform_color(film["platform"], accent), WHITE, size=50))
        d = parse_day(film.get("date", ""))
        date_txt = f"FROM {fmt_day(d)}" if d else (film.get("date") or "").upper()
        if date_txt:
            badges.append(chip_layer(date_txt, (14, 14, 20, 235), WHITE, size=50, outline=accent))
        L_badges = row_of(badges, 16) if badges else None
        L_lang = text_layer(lang.upper() if lang else (g.INDUSTRIES[ind]["label"] if ind else ""),
                            font(BEBAS, 46), accent, shadow=True, tracking=4)
        L_idx = row_of([text_layer(f"{i + 1:02d}", font(ANTON, 64), accent),
                        text_layer(f"/ {n:02d}", font(BEBAS, 50), MUTED)], 10)
        info_h = title_h + 26 + (L_badges.h if L_badges else 0) + 22 + L_lang.h
        top = 330
        if src is not None:
            avail_h = TEXT_BOTTOM - top - 44 - info_h
            card = poster_card(src, 860, max(420, min(800, avail_h)))
            bg = KenBurns(blurred(src, int(RW * 1.25), int(RH * 1.25), dark=0.6, tint=accent), 1.0, 1.06, per)
            y_info = top + card.h + 44
        else:
            card, bg = None, None
            plain = designed_bg(accent)
            y_info = 860 - info_h / 2
        y_badges = y_info + title_h + 26
        y_lang = y_badges + (L_badges.h if L_badges else 0) + 22

        def slide(t, card=card, bg=bg, plain=None if src is not None else plain, L_title=L_title, lh=lh,
                  L_badges=L_badges, L_lang=L_lang, L_idx=L_idx, y_info=y_info, y_badges=y_badges,
                  y_lang=y_lang, accent=accent, i=i):
            f = bg.frame(t) if bg else plain.copy()
            if card:
                s = 0.9 + 0.1 * ease_out(prog(t, 0, 0.35)) + 0.03 * prog(t, 0.35, per)
                put(f, card, centred_x(card), top, alpha=prog(t, 0, 0.12), scale=s)
            for k, L in enumerate(L_title):
                e = ease_out(prog(t, 0.12 + 0.06 * k, 0.28))
                put(f, L, centred_x(L), y_info + k * lh + (1 - e) * 46, alpha=e)
            if L_badges:
                sp = ease_back(prog(t, 0.3, 0.28)) if t < 0.58 else 1
                put(f, L_badges, centred_x(L_badges), y_badges, alpha=prog(t, 0.3, 0.08), scale=0.4 + 0.6 * sp)
            put(f, L_lang, centred_x(L_lang), y_lang, alpha=prog(t, 0.45, 0.25))
            put(f, L_idx, SAFE_L, 238, alpha=prog(t, 0.05, 0.2))
            dr = ImageDraw.Draw(f)
            u = (i + clamp(t / per)) / n
            dr.rectangle([SAFE_L, 222, SAFE_R, 228], fill=(255, 255, 255))
            dr.rectangle([SAFE_L, 222, SAFE_L + int(SAFE_W * u), 228], fill=accent)
            return f

        scenes.append(Scene(per, slide, enter="whip", sfx=[(0.3, "pop")]))

    scenes.append(outro_scene(base_accent))
    return scenes, 0.0


# ====================================================================== template: exciting news / update

def _words_layers(text, fnt, max_w, line_h):
    """Word layers with their positions (for the word-by-word reveal)."""
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines = g._wrap(d, text, fnt, max_w)
    out = []
    space = d.textlength(" ", font=fnt)
    for li, ln in enumerate(lines):
        x = 0
        for w in ln.split():
            L = text_layer(w, fnt, WHITE, shadow=False)
            out.append((L, x, li * line_h))
            x += L.w + space
    return out, len(lines)


def build_news(spec):
    headline = spec["headline"].upper()
    points = [p for p in spec.get("points", []) if p.strip()][:4]
    accent = accent_for(spec["headline"] + " " + " ".join(points))
    srcs = [load(p) for p in spec.get("images", []) if p]
    cat = (spec.get("category") or "").upper() or "SOUTH CINEMA"

    # timing first, so every Ken Burns knows how long its picture stays on screen
    fnt, lines, lh = lines_fit(headline, ANTON, SAFE_W, 560, 128, 64, spacing=1.04, max_lines=5)
    land = 0.25 + 0.12 * (len(lines) - 1) + 0.2
    hook_dur = on_beat(land + 1.6, 2.5)
    pdurs = [on_beat(min(4.0, max(2.0, 1.0 + len(p.split()) * 0.21))) for p in points]
    pic_of = [0] + [((j + 1) % len(srcs)) if srcs else 0 for j in range(len(points))]
    durs = [hook_dur] + pdurs
    span = {}
    for k, pi in enumerate(pic_of):
        span[pi] = span.get(pi, 0) + durs[k]
    kbs = {pi: KenBurns.from_source(srcs[pi], z0=1.0, z1=1.14, dur=span[pi], drift=(0.0, -0.3)) for pi in span} \
        if srcs else {}
    plain = designed_bg(accent)
    shade = shade_layer(bottom_from=0.38)
    elapsed = {pi: 0.0 for pi in span}
    offsets = []
    for k, pi in enumerate(pic_of):
        offsets.append(elapsed[pi])
        elapsed[pi] += durs[k]

    def bg_at(k, t):
        if not srcs:
            return plain.copy()
        kb = kbs[pic_of[k]]
        tt = offsets[k] + t
        if k == 0:
            z = 1.14 - 0.12 * ease_out(prog(t, 0, 0.45)) if t < 0.45 else 1.02 + 0.10 * prog(tt, 0.45, kb.dur)
            return kb.frame(tt, z)
        return kb.frame(tt, 1.02 + 0.10 * prog(tt, 0.45, kb.dur))

    # --- hook: headline slam
    L_lines = [text_layer(ln, fnt, WHITE) for ln in lines]
    y_text = TEXT_BOTTOM - lh * len(lines)
    L_cat = chip_layer(cat, accent, INK, size=50)

    def hook(t):
        f = bg_at(0, t)
        f.paste(shade, (0, 0), shade)
        sp = ease_back(prog(t, 0.08, 0.28)) if t < 0.36 else 1
        put(f, L_cat, SAFE_L, y_text - L_cat.h - 34, alpha=prog(t, 0.08, 0.08), scale=0.4 + 0.6 * sp)
        for k, L in enumerate(L_lines):
            st = 0.25 + 0.12 * k
            s = 1.4 - 0.4 * ease_out(prog(t, st, 0.2))
            put(f, L, SAFE_L, y_text + k * lh, alpha=prog(t, st, 0.09), scale=s)
        bar = int(240 * ease_out(prog(t, land, 0.35)))
        if bar > 2:
            ImageDraw.Draw(f).rectangle([SAFE_L, TEXT_BOTTOM + 14, SAFE_L + bar, TEXT_BOTTOM + 22], fill=accent)
        f = flash(f, decay(t, land, 0.16, 0.45))
        return shake(f, decay(t, land, 0.32, 13), t)

    scenes = [Scene(hook_dur, hook, sfx=[(0.08, "pop"), (land, "impact")])]

    # --- points
    ctx_text = headline if len(headline) <= 44 else headline[:43].rsplit(" ", 1)[0] + "…"
    L_ctx = chip_layer(ctx_text, (12, 12, 16, 200), WHITE, size=44, outline=accent)
    for j, point in enumerate(points):
        k = j + 1
        size = 54
        while size > 36:
            pf = font(BODY, size)
            words, nl = _words_layers(point, pf, SAFE_W - 90, int(size * 1.3))
            if nl * size * 1.3 <= 420:
                break
            size -= 4
        plh = int(size * 1.3)
        panel_h = nl * plh + 70
        panel_y = TEXT_BOTTOM - panel_h
        L_num = text_layer(f"{k:02d}", font(ANTON, 110), accent)
        panel = Image.new("RGBA", (SAFE_W, panel_h), (0, 0, 0, 0))
        pd = ImageDraw.Draw(panel)
        pd.rounded_rectangle([0, 0, SAFE_W - 1, panel_h - 1], radius=28, fill=(12, 12, 18, 228))
        pd.rectangle([0, 26, 9, panel_h - 26], fill=accent)
        L_panel = Layer(panel, 0, 0, SAFE_W, panel_h)
        step = min(0.07, 0.75 / max(1, len(words)))
        changes = pic_of[k] != pic_of[k - 1]

        def pscene(t, k=k, words=words, panel_y=panel_y, L_num=L_num, L_panel=L_panel, step=step):
            f = bg_at(k, t)
            f.paste(shade, (0, 0), shade)
            put(f, L_ctx, SAFE_L, 262, alpha=prog(t, 0, 0.2))
            e = ease_out(prog(t, 0, 0.28))
            put(f, L_panel, SAFE_L, panel_y + (1 - e) * 90, alpha=e)
            sp = ease_back(prog(t, 0.1, 0.3)) if t < 0.4 else 1
            put(f, L_num, SAFE_L, panel_y - L_num.h - 6, alpha=prog(t, 0.1, 0.08), scale=0.4 + 0.6 * sp)
            for w_i, (L, x, y) in enumerate(words):
                st = 0.22 + w_i * step
                we = ease_out(prog(t, st, 0.16))
                put(f, L, SAFE_L + 48 + x, panel_y + 35 + y + (1 - we) * 14 + (1 - e) * 90, alpha=we)
            return f

        scenes.append(Scene(pdurs[j], pscene, enter="whip" if changes else "fade",
                            trans=0.3 if changes else 0.2, sfx=[(0.1, "pop")]))

    scenes.append(outro_scene(accent))
    return scenes, 0.0


# ====================================================================== template: poster reveal

def build_poster(spec):
    srcs = [load(p) for p in spec.get("images", []) if p]
    if not srcs:
        raise ValueError("a poster reveal needs the poster picture")
    film = spec["film"].upper()
    label = (spec.get("label") or "NEW POSTER").upper()
    notes = [n for n in spec.get("notes", []) if n.strip()][:2]
    accent = accent_for(spec["film"] + " " + " ".join(notes))

    teaser = on_beat(1.5)
    reveal = on_beat(5.0)
    extra = on_beat(2.0)
    kb0 = KenBurns.from_source(srcs[0], dur=teaser + reveal)
    blur0 = KenBurns(kb0.base.filter(ImageFilter.GaussianBlur(34)), dur=teaser)
    dark = Image.new("RGB", (RW, RH), INK)
    shade = shade_layer(bottom_from=0.5)

    fnt, lines, lh = lines_fit(film, ANTON, SAFE_W, 330, 132, 64, spacing=1.04, max_lines=3)
    L_lines = [text_layer(ln, fnt, WHITE) for ln in lines]
    L_label = chip_layer(label, accent, INK, size=52)
    note_layers = []
    for nt in notes:
        nf, nlines, nlh = lines_fit(nt, BODY, SAFE_W, 130, 46, 34, spacing=1.25, max_lines=2)
        note_layers.append(([text_layer(x, nf, WHITE) for x in nlines], nlh))
    notes_h = sum(len(ls) * nlh + 14 for ls, nlh in note_layers)
    film_h = lh * (len(lines) - 1) + sum(fnt.getmetrics())  # Anton is taller than its point size
    y_film = TEXT_BOTTOM - notes_h - film_h - (34 if note_layers else 0)
    L_tease = None

    def overlay_text(f, t, animate=True):
        sp = ease_back(prog(t, 0.85, 0.3)) if animate and t < 1.15 else 1
        put(f, L_label, SAFE_L, y_film - L_label.h - 30,
            alpha=prog(t, 0.85, 0.08) if animate else 1, scale=0.4 + 0.6 * sp)
        for k, L in enumerate(L_lines):
            st = 0.45 + 0.1 * k
            s = 1.3 - 0.3 * ease_out(prog(t, st, 0.2)) if animate else 1
            put(f, L, SAFE_L, y_film + k * lh, alpha=prog(t, st, 0.09) if animate else 1, scale=s)
        y = y_film + film_h + 34
        for n_i, (ls, nlh) in enumerate(note_layers):
            st = 1.2 + 0.3 * n_i
            for L in ls:
                e = ease_out(prog(t, st, 0.3)) if animate else 1
                put(f, L, SAFE_L, y + (1 - e) * 30, alpha=e)
                y += nlh
            y += 14

    def tease(t):
        f = Image.blend(blur0.frame(t, 1.18 - 0.06 * t / teaser), dark, 0.55)
        tracking = 6 + 20 * t / teaser
        L = text_layer(label, font(BEBAS, 128), WHITE, shadow=True, tracking=tracking)
        a = prog(t, 0.08, 0.35)
        if t < 0.55:
            a *= 0.55 + 0.45 * (math.sin(t * 70) > -0.2)
        put(f, L, centred_x(L), 820, alpha=a)
        sub = text_layer("CINEMA WOODS", font(BEBAS, 48), accent, shadow=False, tracking=10)
        put(f, sub, centred_x(sub), 820 + L.h + 18, alpha=prog(t, 0.5, 0.4) * 0.9)
        return f

    def show(t):
        tt = teaser + t
        z = 1.14 - 0.14 * ease_out(prog(t, 0, 0.6)) if t < 0.6 else 1.0 + 0.05 * prog(t, 0.6, reveal)
        f = kb0.frame(tt, z)
        f.paste(shade, (0, 0), shade)
        overlay_text(f, t)
        f = flash(f, decay(t, 0, 0.32, 1.0))
        return shake(f, decay(t, 0, 0.38, 15), t)

    scenes = [Scene(teaser, tease, brand=False, sfx=[(teaser, "riser", 1.4)]),
              Scene(reveal, show, enter="cut", sfx=[(0.0, "impact"), (0.45, "pop"), (0.85, "pop")])]
    for p in srcs[1:3]:
        kb = KenBurns.from_source(p, z0=1.08, z1=1.0, dur=extra)

        def more(t, kb=kb):
            f = kb.frame(t)
            f.paste(shade, (0, 0), shade)
            overlay_text(f, t, animate=False)
            return shake(f, decay(t, 0.15, 0.3, 9), t)

        scenes.append(Scene(extra, more, enter="flash", trans=0.3, sfx=[(0.15, "impact")]))
    scenes.append(outro_scene(accent))
    return scenes, teaser


# ====================================================================== template: box office

def build_bo(spec):
    fig = Figure(spec["figure"])
    film = (spec.get("film") or "").upper()
    label = (spec.get("label") or fig.rest or "").upper()
    rows = spec.get("rows", [])[:6]
    accent = accent_for(film + " " + label)
    srcs = [load(p) for p in spec.get("images", []) if p]
    hook_dur = on_beat(4.0)
    rows_dur = on_beat(1.0 + 0.5 * len(rows) + 1.2) if rows else 0
    if srcs:
        kb = KenBurns(Image.blend(composed(srcs[0], int(RW * 1.25), int(RH * 1.25)),
                                  Image.new("RGB", (int(RW * 1.25), int(RH * 1.25)), INK), 0.55),
                      dur=hook_dur + rows_dur)
        bgf = kb.frame
    else:
        plain = designed_bg(accent)
        bgf = lambda t: plain.copy()  # noqa: E731
    glow = radial_glow(accent, 900, alpha=110)

    L_chip = chip_layer("BOX OFFICE", accent, INK, size=54)
    if film:
        ff, flines, flh = lines_fit(film, ANTON, SAFE_W, 200, 92, 56, spacing=1.05, max_lines=2)
        L_film = [text_layer(x, ff, WHITE) for x in flines]
    else:
        L_film, flh = [], 0
    final = fig.fmt()
    size = 270
    while size > 110 and _measure(final, font(ANTON, size))[0] > 820:
        size -= 10
    nfont = font(ANTON, size)
    lf, llines, llh = lines_fit(label, BEBAS, SAFE_W, 170, 76, 46, spacing=1.08, max_lines=2) if label else (None, [], 0)
    L_label = [text_layer(x, lf, WHITE, tracking=2) for x in llines]

    y_chip = 360
    y_film = y_chip + L_chip.h + 36
    y_num = y_film + flh * len(L_film) + 40
    num_h = sum(nfont.getmetrics())
    y_label = y_num + num_h + 26
    c0, c1, land = 0.6, 2.2, 2.2

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
            num_cache[text] = text_layer(text, nfont, accent if text == final else WHITE, shadow=False, stroke=4)
        return num_cache[text]

    def hook(t):
        f = bgf(t)
        f.paste(glow, (0, 0), glow)
        sp = ease_back(prog(t, 0.1, 0.3)) if t < 0.4 else 1
        put(f, L_chip, centred_x(L_chip), y_chip, alpha=prog(t, 0.1, 0.08), scale=0.4 + 0.6 * sp)
        for k, L in enumerate(L_film):
            e = ease_out(prog(t, 0.25 + 0.08 * k, 0.3))
            put(f, L, centred_x(L), y_film + k * flh + (1 - e) * 40, alpha=e)
        if t >= c0:
            if t < land:
                txt = fig.fmt(fig.value * ease_out(prog(t, c0, c1 - c0)), plus=False)
                s = 1.0
            else:
                txt = final
                s = 1.0 + 0.16 * (1 - ease_out(prog(t, land, 0.3)))
            L = num_layer(txt)
            put(f, L, centred_x(L), y_num, alpha=prog(t, c0, 0.1), scale=s)
        for k, L in enumerate(L_label):
            e = ease_out(prog(t, land + 0.15 + 0.1 * k, 0.3))
            put(f, L, centred_x(L), y_label + k * llh + (1 - e) * 30, alpha=e)
        f = flash(f, decay(t, land, 0.2, 0.5))
        return shake(f, decay(t, land, 0.35, 16), t)

    scenes = [Scene(hook_dur, hook, sfx=[(0.1, "pop"), *ticks, (land, "impact")])]

    if rows:
        L_top = text_layer(final, font(ANTON, 150), accent)
        L_sub = text_layer((film or label)[:40], font(BEBAS, 54), WHITE, tracking=2)
        row_layers = []
        for name, val in rows:
            rimg = Image.new("RGBA", (SAFE_W, 118), (0, 0, 0, 0))
            rd = ImageDraw.Draw(rimg)
            rd.rounded_rectangle([0, 0, SAFE_W - 1, 117], radius=24, fill=(12, 12, 18, 225))
            rd.rectangle([0, 22, 8, 95], fill=accent)
            nf, nl, _ = lines_fit(name.upper(), BEBAS, 480, 70, 56, 36, max_lines=1)
            rd.text((36, 59), nl[0], font=nf, fill=WHITE, anchor="lm")
            vf = font(ANTON, 64)
            rd.text((SAFE_W - 34, 59), val.upper(), font=vf, fill=accent, anchor="rm")
            row_layers.append(Layer(rimg, 0, 0, SAFE_W, 118))
        y0 = 300 + L_top.h + L_sub.h + 90

        def rows_scene(t):
            f = bgf(hook_dur + t)
            put(f, L_top, centred_x(L_top), 300, alpha=prog(t, 0, 0.2))
            put(f, L_sub, centred_x(L_sub), 300 + L_top.h + 10, alpha=prog(t, 0.1, 0.2))
            for k, L in enumerate(row_layers):
                st = 0.35 + 0.5 * k
                e = ease_out(prog(t, st, 0.3))
                put(f, L, SAFE_L + (1 - e) * 360, y0 + k * 138, alpha=e)
            return f

        scenes.append(Scene(rows_dur, rows_scene, enter="fade", trans=0.25,
                            sfx=[(0.35 + 0.5 * k, "pop") for k in range(len(rows))]))
    scenes.append(outro_scene(accent))
    return scenes, 0.0


# ====================================================================== entry point

BUILDERS = {"ott": build_ott, "news": build_news, "poster": build_poster, "bo": build_bo}
NAMES = {"ott": "OTT releases", "news": "News update", "poster": "Poster reveal", "bo": "Box office"}


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
