"""
OTT releases Reel (design v2): a "save this reel" title card over a scrolling wall of the posters, then one slide
per film - platform LOGO and streaming date on top, film title, a one-line description, the main language and the
languages it streams in, and the poster below - and a closing "save this reel" card.

Plain and professional: no sparkles, no beat-synced pulsing, no numbers or counters. The Reel is silent by default
so you can add your own music in Instagram (set OTT_REEL_AUDIO=1 to use the bot's music again).

Called by reel_templates.build_ott(); the old design stays available as build_ott_classic (OTT_TEMPLATE=v1).
"""

import math
import os
import re

from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "assets", "fonts")
LOGO_DIR = os.path.join(HERE, "assets", "platform_logos")
ANTON = os.path.join(FONT_DIR, "Anton-Regular.ttf")
BODY = os.path.join(FONT_DIR, "Montserrat-ExtraBold.ttf")
BODY_M = os.path.join(FONT_DIR, "Montserrat-SemiBold.ttf")

GOLD = (255, 200, 60)
WHITE = (255, 255, 255)

# (key, words that identify the platform, accent colour); the logo file is assets/platform_logos/<key>.png
PLATFORMS = [
    ("prime", (r"prime", r"amazon"), (0, 150, 255)),
    ("netflix", (r"netflix",), (229, 9, 20)),
    ("sony", (r"sony", r"\bliv\b"), (140, 95, 255)),
    ("aha", (r"\baha\b",), (255, 130, 0)),
    ("sun", (r"\bsun\b", r"sunnxt"), (232, 30, 120)),
]
LOGO_H = {"prime": 76, "netflix": 68, "sony": 108, "aha": 86, "sun": 108}
STRIP_H = {"prime": 52, "netflix": 46, "sony": 70, "aha": 56, "sun": 70}


def plat_key(name):
    low = (name or "").lower()
    for key, pats, _ in PLATFORMS:
        if any(re.search(p, low) for p in pats):
            return key
    return None


def plat_colour(name, fallback):
    key = plat_key(name)
    for k, _, col in PLATFORMS:
        if k == key:
            return col
    return fallback


def parse_langs(text):
    out = []
    for p in re.split(r"[,/&+]|\band\b", text or "", flags=re.I):
        p = p.strip().upper()
        if p and p not in out:
            out.append(p)
    return out


# ------------------------------------------------------------------ one-line descriptions (Gemini + search)

LINE_PROMPT = """These South Indian films are streaming on OTT this week. For EACH film write ONE plain, factual line \
(maximum 95 characters, no spoilers, no hype, no star ratings) that tells a viewer what the film is about. Use Google \
Search to check what each film is. If you cannot confirm what a film is about, write a dash for it instead of guessing.

Films:
{films}

Reply with exactly one line per film in this form and nothing else:
Title :: one line description"""


def add_lines(films):
    """Fills in films[i]['line'] (a one-line description) for films where the user did not give one."""
    todo = [f for f in films if not (f.get("line") or "").strip()]
    if not todo:
        return
    try:
        import caption_gen
        listing = "\n".join(f"- {f['title']} ({f.get('platform', '')}; {f.get('language', '')})" for f in todo)
        reply = caption_gen._call_gemini(LINE_PROMPT.format(films=listing), search=True)
    except Exception as e:  # no line is better than a wrong one
        print(f"[WARN] OTT one-liners not written: {e}")
        return
    got = {}
    for ln in (reply or "").lstrip("\x00").splitlines():
        if "::" in ln:
            t, d = ln.split("::", 1)
            got[re.sub(r"\W+", "", t.lower())] = d.strip(" -*\"'")
    for f in todo:
        d = got.get(re.sub(r"\W+", "", f["title"].lower()), "")
        if len(d) >= 15:
            f["line"] = d[:110].rstrip(" ,;:")


# ------------------------------------------------------------------ drawing helpers

def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def back(u):
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2


_TL = {}


def tl(text, size, fill, stroke=0, font=ANTON, pill=None, pad=(36, 14), icon=0, outline=None):
    key = (text, size, fill, stroke, font, pill, icon, outline)
    if key in _TL:
        return _TL[key]
    f = ImageFont.truetype(font, size)
    bb = f.getbbox(text, stroke_width=stroke)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    w, h = (tw + pad[0] * 2 + 40 + icon, th + pad[1] * 2 + 40) if pill else (tw + 60, th + 60)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    if pill:
        sd.rounded_rectangle((20, 26, w - 20, h - 14), radius=(h - 40) // 2, fill=(0, 0, 0, 190))
    else:
        sd.text((30 - bb[0], 36 - bb[1]), text, font=f, fill=(0, 0, 0, 230), stroke_width=stroke)
    im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(9)))
    d = ImageDraw.Draw(im)
    if pill:
        d.rounded_rectangle((20, 20, w - 20, h - 20), radius=(h - 40) // 2, fill=pill,
                            outline=outline, width=5 if outline else 0)
        d.text((20 + pad[0] + icon - bb[0], h // 2 - th // 2 - bb[1]), text, font=f, fill=fill)
        if icon:  # bookmark glyph
            ix, iy, ih = 20 + pad[0] - 6, h // 2 - 22, 44
            d.polygon([(ix, iy), (ix + 30, iy), (ix + 30, iy + ih), (ix + 15, iy + ih - 12), (ix, iy + ih)], fill=fill)
    else:
        d.text((30 - bb[0], 30 - bb[1]), text, font=f, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
    _TL[key] = im
    return im


def fit_title(text, maxw=960, start=190, stroke=6, fill=WHITE):
    for s in range(start, 70, -6):
        if ImageFont.truetype(ANTON, s).getlength(text) <= maxw:
            return tl(text, s, fill, stroke=stroke)
    return tl(text, 70, fill, stroke=stroke)


def wrap(text, size, maxw, font=BODY_M):
    f = ImageFont.truetype(font, size)
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if f.getlength(t) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def put(img, layer, cx, cy, s=1.0, a=1.0, dx=0):
    if s != 1.0:
        layer = layer.resize((max(1, int(layer.width * s)), max(1, int(layer.height * s))), Image.BICUBIC)
    if a < 1.0:
        al = layer.getchannel("A").point(lambda v: int(v * a))
        layer = layer.copy()
        layer.putalpha(al)
    img.paste(layer, (int(cx + dx - layer.width / 2), int(cy - layer.height / 2)), layer)


def slam(lt, delay=0.0, dur=0.22, big=1.6):
    if lt < delay:
        return None
    u = min(1.0, (lt - delay) / dur)
    return 1 + (big - 1) * (1 - u) ** 3, min(1.0, 0.25 + u * 2.5)


def slide_in(lt, delay, dur=0.3, dist=500):
    if lt < delay:
        return None
    u = min(1.0, (lt - delay) / dur)
    return -dist * (1 - u) ** 3, min(1.0, u * 3)


def logo(key, h):
    im = Image.open(os.path.join(LOGO_DIR, key + ".png")).convert("RGBA")
    return im.resize((max(1, int(im.width * h / im.height)), h), Image.LANCZOS)


def badge(name, colour):
    """Dark rounded badge with the platform's own logo (or its name, if there is no logo file) and a coloured edge."""
    key = plat_key(name)
    if key and os.path.exists(os.path.join(LOGO_DIR, key + ".png")):
        lg = logo(key, LOGO_H[key])
    else:
        lg = tl((name or "OTT").upper(), 62, WHITE)
        lg = lg.crop(lg.getbbox())
    pad, bh = 36, 134
    w = lg.width + pad * 2
    layer = Image.new("RGBA", (w + 40, bh + 40), (0, 0, 0, 0))
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((20, 28, w + 20, bh + 24), radius=34, fill=(0, 0, 0, 200))
    layer = Image.alpha_composite(layer, sh.filter(ImageFilter.GaussianBlur(10)))
    ImageDraw.Draw(layer).rounded_rectangle((20, 20, w + 20, bh + 20), radius=34, fill=(14, 14, 22, 245),
                                            outline=tuple(colour) + (255,), width=5)
    layer.paste(lg, (20 + pad, 20 + (bh - lg.height) // 2), lg)
    return layer


def logo_strip(keys):
    lgs = [logo(k, STRIP_H[k]) for k in keys]
    gap, pad, bh = 38, 44, 100
    w = sum(l.width for l in lgs) + gap * (len(lgs) - 1) + pad * 2
    layer = Image.new("RGBA", (w + 40, bh + 40), (0, 0, 0, 0))
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((20, 28, w + 20, bh + 24), radius=50, fill=(0, 0, 0, 200))
    layer = Image.alpha_composite(layer, sh.filter(ImageFilter.GaussianBlur(10)))
    ImageDraw.Draw(layer).rounded_rectangle((20, 20, w + 20, bh + 20), radius=50, fill=(14, 14, 22, 240),
                                            outline=(255, 255, 255, 70), width=3)
    x = 20 + pad
    for l in lgs:
        layer.paste(l, (x, 20 + (bh - l.height) // 2), l)
        x += l.width + gap
    return layer


def placeholder(title, name, lang, colour):
    """Poster stand-in for a film whose poster was not sent."""
    w, h = 640, 853
    ys = [i / (h - 1) for i in range(h)]
    top, bot = (60, 10, 70), tuple(int(c * 0.8) for c in colour)
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y, u in enumerate(ys):
        d.line((0, y, w, y), fill=tuple(int(top[i] * (1 - u) + bot[i] * u) for i in range(3)))
    for i in range(0, 900, 60):
        d.line((0, i, i, 0), fill=(255, 255, 255), width=1)

    def ctext(t, size, y, col, font=ANTON):
        ff = ImageFont.truetype(font, size)
        d.text(((w - ff.getlength(t)) / 2, y), t, font=ff, fill=col)

    if name:
        ctext("NEW ON " + name.upper(), 38, 90, WHITE, BODY)
    s = 170
    while s > 60 and ImageFont.truetype(ANTON, s).getlength(title) > w - 60:
        s -= 8
    ctext(title, s, 300, GOLD)
    if lang:
        ctext(lang, 40, 540, WHITE, BODY)
    ctext("STREAMING NOW", 48, 700, WHITE)
    return im


def poster_layer(src, colour, box_w, box_h):
    s = min(box_w / src.width, box_h / src.height)
    pw, ph = int(src.width * s), int(src.height * s)
    p = src.resize((pw, ph), Image.LANCZOS)
    if s > 1.05:
        p = p.filter(ImageFilter.UnsharpMask(radius=1.6, percent=80, threshold=2))
    pad = 80
    layer = Image.new("RGBA", (pw + pad * 2, ph + pad * 2), (0, 0, 0, 0))
    glow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle((pad - 6, pad - 6, pad + pw + 6, pad + ph + 6), radius=40,
                                           fill=tuple(colour) + (210,))
    layer = Image.alpha_composite(layer, glow.filter(ImageFilter.GaussianBlur(30)))
    m = Image.new("L", (pw, ph), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=30, fill=255)
    bm = Image.new("L", (pw + 8, ph + 8), 0)
    ImageDraw.Draw(bm).rounded_rectangle((0, 0, pw + 7, ph + 7), radius=34, fill=255)
    layer.paste(Image.new("RGBA", (pw + 8, ph + 8), tuple(colour) + (255,)), (pad - 4, pad - 4), bm)
    layer.paste(p, (pad, pad), m)
    return layer


# ------------------------------------------------------------------ the Reel

def build(spec, S):
    """S is the reel_templates module (Scene, RW, RH, on_beat, lockup_layer, pill_layer, parse_day, fmt_day ...)."""
    import config
    RW, RH = S.RW, S.RH
    films = spec["films"][:10]
    n = len(films)
    PER, HOOK, OUT = S.on_beat(2.5), S.on_beat(3.5), S.on_beat(3.5)
    BOTTOM = 1640            # the poster ends here; the follow block sits below it

    # ---- per-film data
    data = []
    for f in films:
        langs = parse_langs(f.get("language", ""))
        key = plat_key(f.get("platform", ""))
        col = plat_colour(f.get("platform", ""), S.platform_color(f.get("platform", ""), (230, 230, 235)))
        d = S.parse_day(f.get("date", ""))
        when = S.fmt_day(d) if d else (f.get("date") or "").upper()
        src = None
        if f.get("image") and os.path.exists(f["image"]):
            src = Image.open(f["image"]).convert("RGB")
        if src is None:
            src = placeholder(f["title"].upper(), f.get("platform", ""), (langs[0] if langs else ""), col)
        data.append(dict(title=f["title"].upper(), plat=f.get("platform", ""), key=key, col=col, when=when,
                         langs=langs, line=(f.get("line") or "").strip(), src=src, has_poster=bool(f.get("image"))))

    # ---- scrolling poster wall (hook + outro)
    COLW, GAP, TH = 350, 15, 467
    srcs = [d["src"] for d in data]
    cols = []
    for ci in range(3):
        seq = [srcs[(ci * 3 + k) % len(srcs)] for k in range(max(len(srcs), 6))]
        tiles = []
        for t in seq:
            s = max(COLW / t.width, TH / t.height)
            r = t.resize((int(t.width * s) + 1, int(t.height * s) + 1), Image.LANCZOS)
            r = r.crop(((r.width - COLW) // 2, (r.height - TH) // 2, (r.width - COLW) // 2 + COLW, (r.height - TH) // 2 + TH))
            tiles.append(r)
        hc = len(tiles) * (TH + GAP)
        strip = Image.new("RGB", (COLW, hc * 2), (10, 10, 10))
        for rep in range(2):
            for i, t in enumerate(tiles):
                strip.paste(t, (0, rep * hc + i * (TH + GAP)))
        cols.append((strip, hc))
    speeds = [150, -120, 190]
    yy = Image.linear_gradient("L").resize((RW, RH))   # 0 at top .. 255 at bottom

    def wall(t, dark):
        img = Image.new("RGB", (RW, RH), (8, 8, 8))
        for ci, (strip, hc) in enumerate(cols):
            off = int((speeds[ci] * t + ci * 400) % hc)
            img.paste(strip.crop((0, off, COLW, off + RH)), (ci * (COLW + GAP), 0))
        return Image.eval(img, lambda v: int(v * dark))

    def wall_dark(t, base):
        img = wall(t, base)
        band = Image.new("L", (RW, RH), 0)
        ImageDraw.Draw(band).rectangle((0, 380, RW, 1560), fill=120)
        band = band.filter(ImageFilter.GaussianBlur(120))
        black = Image.new("RGB", (RW, RH), (6, 6, 10))
        return Image.composite(black, img, band)

    # ---- hook
    used_keys = []
    for d in data:
        if d["key"] and d["key"] not in used_keys:
            used_keys.append(d["key"])
    STRIP = logo_strip(used_keys) if used_keys else None
    rng = (spec.get("range") or "").upper()

    def hook(t):
        img = wall_dark(t, 0.7)
        p = slam(t, 0.0, 0.22, 1.3) or (1, 1)
        put(img, tl("SAVE THIS REEL", 56, (0, 0, 0), pill=GOLD, pad=(34, 12), icon=58), RW / 2, 250, p[0], 1.0)
        put(img, tl("FOR YOUR WEEKEND WATCH", 34, WHITE, font=BODY), RW / 2, 345)
        p = slam(t, 0.05, 0.28, 1.5) or (1, 1)
        put(img, fit_title("NEW ON OTT", 990, 250, 8), RW / 2, 700, p[0], 1.0)
        p = slam(t, 0.30, 0.28, 1.5)
        if p:
            put(img, fit_title("THIS WEEK", 990, 250, 8, GOLD), RW / 2, 940, p[0], p[1])
        p = slam(t, 0.62, 0.22, 1.4)
        if p:
            put(img, tl("SOUTH INDIAN RELEASES", 66, WHITE, stroke=3), RW / 2, 1140, p[0], p[1])
        p = slam(t, 0.9, 0.22, 1.4)
        if p and rng:
            put(img, tl(rng, 64, (0, 0, 0), pill=GOLD, pad=(40, 10)), RW / 2, 1255, p[0], p[1])
        p = slam(t, 1.3, 0.25, 1.2)
        if p and STRIP is not None:
            put(img, STRIP, RW / 2, 1420, 1, p[1])
        return img

    scenes = [S.Scene(HOOK, hook, brand=True, brand_top=1668, sfx=[(0.02, "impact")])]

    # ---- one slide per film
    for i, d in enumerate(data):
        nl = 0
        lines = wrap(d["line"], 40, 920) if d["line"] else []
        lines = lines[:3]
        nl = len(lines)
        y_line0 = 462
        y_label = (y_line0 + (nl - 1) * 56 + 66) if nl else 448
        y_chip = y_label + 67
        y_avail = y_chip + 81
        p_top = y_avail + 40
        box_h = min(860, BOTTOM - p_top)
        layer = poster_layer(d["src"], d["col"], 640, box_h)
        p_mid = p_top + (BOTTOM - p_top) / 2 if layer.height - 160 < BOTTOM - p_top else p_top + (layer.height - 160) / 2
        y_target = p_mid
        s = max(d["src"].width, 1)
        sc = max(RW / d["src"].width, RH / d["src"].height)
        bgi = d["src"].resize((int(d["src"].width * sc) + 1, int(d["src"].height * sc) + 1), Image.LANCZOS)
        bgi = bgi.crop(((bgi.width - RW) // 2, (bgi.height - RH) // 2, (bgi.width - RW) // 2 + RW, (bgi.height - RH) // 2 + RH))
        bgi = ImageEnhance.Color(ImageEnhance.Brightness(bgi.filter(ImageFilter.GaussianBlur(55))).enhance(0.45)).enhance(1.5)
        tint = Image.new("RGB", (RW, RH), tuple(d["col"]))
        mask = Image.eval(Image.linear_gradient("L").transpose(Image.FLIP_TOP_BOTTOM).resize((RW, RH)), lambda v: int(v * 0.30))
        bgi = Image.composite(tint, bgi, mask)
        bdg = badge(d["plat"], d["col"])
        chip = tl(d["when"], 54, (0, 0, 0), pill=GOLD, pad=(30, 12)) if d["when"] else None
        title = fit_title(d["title"])
        main = d["langs"][0] if d["langs"] else ""
        if len(d["langs"]) > 1:
            ltxt = "ALSO ON OTT IN  " + "  ·  ".join(d["langs"])
        elif d["langs"]:
            ltxt = "ON OTT IN  " + d["langs"][0]
        else:
            ltxt = ""
        lsize = 32
        while ltxt and lsize > 24 and ImageFont.truetype(BODY_M, lsize).getlength(ltxt) > 960:
            lsize -= 2
        line_layers = [tl(ln, 40, WHITE, font=BODY_M) for ln in lines]
        lab = tl("MAIN LANGUAGE", 28, (255, 220, 120), font=BODY)
        main_chip = tl(main, 62, (0, 0, 0), pill=GOLD, pad=(40, 6)) if main else None
        lang_line = tl(ltxt, lsize, WHITE, font=BODY_M) if ltxt else None

        def draw(t, bgi=bgi, layer=layer, bdg=bdg, chip=chip, title=title, line_layers=line_layers, lab=lab,
                 main_chip=main_chip, lang_line=lang_line, y_target=y_target, y_label=y_label, y_chip=y_chip,
                 y_avail=y_avail, y_line0=y_line0):
            f = bgi.copy()
            u = clamp((t - 0.12) / 0.6)
            py = y_target + (700 * (1 - back(u)) if u < 1 else 0)
            bob = 5 * math.sin(t * 2.2)
            f.paste(layer, (int(RW / 2 - layer.width / 2), int(py - layer.height / 2 + bob)), layer)
            tot = bdg.width + (chip.width if chip else 0) + 14 - 80
            sl = slide_in(t, 0.0, 0.3, 700)
            if sl:
                put(f, bdg, RW / 2 - tot / 2 + bdg.width / 2 - 40, 158, 1, sl[1], dx=sl[0])
            sl = slide_in(t, 0.08, 0.3, 700)
            if sl and chip:
                put(f, chip, RW / 2 + tot / 2 - chip.width / 2 + 40, 158, 1, sl[1], dx=-sl[0])
            p = slam(t, 0.12, 0.24, 1.6)
            if p:
                put(f, title, RW / 2, 330, p[0], p[1])
            p = slam(t, 0.34, 0.25, 1.0)
            if p:
                for j, L in enumerate(line_layers):
                    put(f, L, RW / 2, y_line0 + j * 56 + (1 - p[1]) * 30, 1, p[1])
            p = slam(t, 0.5, 0.22, 1.4)
            if p:
                if main_chip is not None:
                    put(f, lab, RW / 2, y_label, p[0], p[1])
                    put(f, main_chip, RW / 2, y_chip, p[0], p[1])
                if lang_line is not None:
                    put(f, lang_line, RW / 2, y_avail, 1.0, p[1])
            return f

        scenes.append(S.Scene(PER, draw, enter="whip", brand=True, brand_top=1668, sfx=[(0.2, "pop")]))

    # ---- closing card: save this reel
    lk = S.lockup_layer(96)
    pl = S.pill_layer(1.9)

    def outro(t):
        img = wall_dark(t, 0.55)
        d = ImageDraw.Draw(img)
        p = slam(t, 0.0, 0.3, 1.8) or (1, 1)
        bx, by = RW / 2, 400
        sz = 230 * p[0]
        d.polygon([(bx - sz * 0.35, by - sz * 0.5), (bx + sz * 0.35, by - sz * 0.5), (bx + sz * 0.35, by + sz * 0.5),
                   (bx, by + sz * 0.3), (bx - sz * 0.35, by + sz * 0.5)], fill=GOLD)
        p = slam(t, 0.2, 0.28, 1.5)
        if p:
            put(img, fit_title("SAVE THIS REEL", 980, 190, 7, GOLD), RW / 2, 770, p[0], p[1])
        p = slam(t, 0.55, 0.25, 1.4)
        if p:
            put(img, tl("TO WATCH YOUR FAVOURITE", 78, WHITE, stroke=4), RW / 2, 940, p[0], p[1])
            put(img, tl("MOVIE THIS WEEKEND", 78, WHITE, stroke=4), RW / 2, 1030, p[0], p[1])
        p = slam(t, 1.0, 0.25, 1.3)
        if p:
            put(img, lk.img, RW / 2, 1240, p[0], p[1])
            put(img, pl.img, RW / 2, 1390, p[0], p[1])
            put(img, tl("NEW OTT RELEASES EVERY WEEK", 36, WHITE, font=BODY_M), RW / 2, 1500, 1, p[1])
        return img

    scenes.append(S.Scene(OUT, outro, enter="whip", brand=False, sfx=[(0.02, "impact")]))
    scenes[0].silent = not config.OTT_REEL_AUDIO
    return scenes, 0.0
