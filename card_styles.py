"""Text-only post cards, magazine style: a mixed-case serif headline (DM Serif Display), a short description in DM Sans
and the Cinema Woods header / footer. The whole block is centred vertically, so the card is filled, not top-heavy.

Styles:  editorial (left aligned, accent rule)  |  split (colour panel on top, text below)  |  classic (centred title card)
"""

import os
import re
import random

from PIL import Image, ImageDraw, ImageFilter

import graphic_gen as g

W, H = g.W, g.H
HERE = os.path.dirname(os.path.abspath(__file__))
SERIF = os.path.join(HERE, "assets", "fonts", "DMSerifDisplay-Regular.ttf")
SANS = os.path.join(HERE, "assets", "fonts", "DMSans.ttf")
LABEL = os.path.join(HERE, "assets", "fonts", "Montserrat-ExtraBold.ttf")
STYLES = ["editorial", "split", "classic"]

_SMALL = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or", "but", "with", "by", "after", "from",
          "as", "is", "are", "be", "over", "into", "amid", "not", "vs"}
_ACRO = {"ntr", "ott", "kgf", "bo", "tn", "ap", "ssmb", "ssmb29", "ram", "ssr", "ai", "tv", "uk", "us", "usa", "ipl", "bgm", "ps"}


def nice_title(t):
    """ALL CAPS headline -> normal title case (acronyms kept); anything else is left as written."""
    t = (t or "").strip()
    letters = [c for c in t if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.7:
        return t
    out = []
    for i, w in enumerate(t.split()):
        lw = w.lower().strip(".,:;!?'\"")
        if lw in _ACRO:
            out.append(w.upper() if lw not in ("ram", "ps") else w.capitalize())
        elif i and lw in _SMALL:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def _font(path, size, weight=None):
    from PIL import ImageFont
    f = ImageFont.truetype(path, size)
    if weight:
        try:
            f.set_variation_by_axes([14, weight])  # DM Sans: optical size, weight
        except Exception:
            pass
    return f


def _tw(d, s, f):
    return d.textlength(s, font=f)


def _wrap(d, text, f, max_w):
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if _tw(d, trial, f) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _balance(d, text, f, max_w):
    """Wrap, then even out the line lengths so the last line is not a single orphan word."""
    lines = _wrap(d, text, f, max_w)
    n = len(lines)
    if n < 2:
        return lines
    lo, hi = max(_tw(d, w, f) for w in text.split()), max_w
    for _ in range(14):
        mid = (lo + hi) / 2
        if len(_wrap(d, text, f, mid)) <= n:
            hi = mid
        else:
            lo = mid
    return _wrap(d, text, f, hi + 2)


def _fit_head(d, text, max_w, max_h, hi=128, lo=58):
    for size in range(hi, lo - 1, -2):
        f = _font(SERIF, size)
        lines = _balance(d, text, f, max_w)
        if len(lines) * size * 1.08 <= max_h:
            return f, lines, int(size * 1.08)
    f = _font(SERIF, lo)
    lines = _balance(d, text, f, max_w)
    return f, lines, int(lo * 1.08)


def _fit_body(d, text, max_w, max_h, hi=48, lo=32):
    for size in range(hi, lo - 1, -1):
        f = _font(SANS, size, 400)
        lines = _wrap(d, text, f, max_w)
        if len(lines) * size * 1.42 <= max_h:
            return f, lines, int(size * 1.42)
    f = _font(SANS, lo, 400)
    lines = _wrap(d, text, f, max_w)
    keep = max(1, int(max_h // (lo * 1.42)))
    if len(lines) > keep:
        lines = lines[:keep]
        lines[-1] = lines[-1].rstrip(" ,;:.") + "…"
    return f, lines, int(lo * 1.42)


def summary_from(caption, title, words=46):
    """A short description for the card: the first sentence(s) of the post that add something to the headline."""
    cap = re.sub(r"#\w+", "", caption or "")
    sents = []
    for ln in cap.splitlines():          # a line that is only the headline in caps must not glue onto the next one
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            sents += re.split(r"(?<=[.!?])\s+", ln)
    tw = set(re.findall(r"[a-z0-9]+", title.lower()))
    out, n = [], 0
    for s in sents:
        sw = re.findall(r"[a-z0-9]+", s.lower())
        if not sw:
            continue
        if len(set(sw) & tw) / len(set(sw)) > 0.8:   # just repeats the headline
            continue
        if re.search(r"follow|which one|what do you think|tag a|comment", s, re.I):
            continue
        out.append(s)
        n += len(sw)
        if n >= words * 0.7:
            break
    text = " ".join(out)
    w = text.split()
    if len(w) > words:
        text = " ".join(w[:words]).rstrip(",;:") + "…"
    return text


def _bg(accent, kind, seed):
    rnd = random.Random(seed)
    base = Image.new("RGB", (W, H), g.BG)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    if kind == "editorial":
        gd.ellipse([W - 620, -300, W + 280, 600], fill=accent + (70,))
        gd.ellipse([-380, H - 560, 420, H + 240], fill=accent + (38,))
    elif kind == "classic":
        gd.ellipse([W // 2 - 620, H // 2 - 560, W // 2 + 620, H // 2 + 560], fill=accent + (46,))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    base = Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")
    return base


def _kicker_w(d, text):
    f = _font(LABEL, 24)
    return sum(_tw(d, ch, f) + 4 for ch in text) - 4


def _kicker(d, x, y, text, accent, align="left"):
    f = _font(LABEL, 24)
    tracked = "  ".join(text) if False else text
    tw = _tw(d, tracked, f) + (len(tracked) - 1) * 4
    if align == "center":
        x = x - tw / 2
    cx = x
    for ch in tracked:
        d.text((cx, y), ch, font=f, fill=accent)
        cx += _tw(d, ch, f) + 4
    return tw


def make_story_card(title, summary, out_path, style=None, industry_label=None, accent=None, category=None):
    title = nice_title(title).replace("₹", "Rs ")   # the serif has no rupee sign
    seed = g._hash(title)
    style = style if style in STYLES else STYLES[seed % len(STYLES)]
    if accent is None or industry_label is None or category is None:
        ind = g._detect_industry(title)
        accent = accent or (g.INDUSTRIES[ind]["color"] if ind else g._hex_to_rgb(g.config.ACCENT_COLOR))
        industry_label = industry_label or (g.INDUSTRIES[ind]["label"] if ind else "SOUTH CINEMA")
        category = category or g._detect_category(title)
    summary = (summary or "").strip()

    img = _bg(accent, style, seed)
    d = ImageDraw.Draw(img)
    top, bottom = 190, H - 150                  # area between the header and the footer
    pad = 72
    max_w = W - 2 * pad

    if style == "split":
        split_y = 700
        panel = Image.new("RGB", (W, split_y), accent)
        gr = Image.new("L", (1, split_y))
        for y in range(split_y):
            gr.putpixel((0, y), int(255 * (0.12 + 0.55 * y / split_y)))
        dark = Image.new("RGB", (W, split_y), (14, 10, 12))
        panel = Image.composite(dark, panel, gr.resize((W, split_y)))
        img.paste(panel, (0, 0))
        d = ImageDraw.Draw(img)
        f, hl, lh = _fit_head(d, title, max_w, split_y - 270, hi=112, lo=56)
        hh = len(hl) * lh
        y0 = 150 + max(0, (split_y - 150 - 70 - hh - 50) / 2) + 50
        _kicker(d, pad, y0 - 54, category, (255, 255, 255))
        for i, ln in enumerate(hl):
            d.text((pad, y0 + i * lh), ln, font=f, fill=(255, 255, 255))
        d.rectangle([pad, split_y + 46, pad + 110, split_y + 53], fill=accent)
        if summary:
            bf, bl, bh = _fit_body(d, summary, max_w, bottom - (split_y + 100), hi=48, lo=32)
            blk = len(bl) * bh
            yy = split_y + 90 + max(0, (bottom - split_y - 90 - blk) / 2 - 20)
            for ln in bl:
                d.text((pad, yy), ln, font=bf, fill=(224, 224, 232))
                yy += bh
    elif style == "classic":
        f, hl, lh = _fit_head(d, title, max_w - 20, 640, hi=124, lo=60)
        hh = len(hl) * lh
        bl, bh, bf = [], 0, None
        if summary:
            bf, bl, bh = _fit_body(d, summary, max_w - 60, 400, hi=46, lo=32)
        blk = 40 + 36 + hh + 56 + (len(bl) * bh + 40 if bl else 0)
        y = top + max(0, (bottom - top - blk) / 2) - 10
        _kicker(d, W / 2, y, category, accent, "center")
        y += 70
        for i, ln in enumerate(hl):
            tw = _tw(d, ln, f)
            d.text(((W - tw) / 2, y + i * lh), ln, font=f, fill=g.WHITE)
        y += hh + 46
        d.line([(W / 2 - 150, y + 10), (W / 2 - 22, y + 10)], fill=accent, width=3)
        d.line([(W / 2 + 22, y + 10), (W / 2 + 150, y + 10)], fill=accent, width=3)
        d.ellipse([W / 2 - 6, y + 4, W / 2 + 6, y + 16], fill=accent)
        y += 62
        for ln in bl:
            tw = _tw(d, ln, bf)
            d.text(((W - tw) / 2, y), ln, font=bf, fill=(205, 205, 214))
            y += bh
    else:  # editorial
        f, hl, lh = _fit_head(d, title, max_w, 700, hi=128, lo=60)
        hh = len(hl) * lh
        bl, bh, bf = [], 0, None
        body_room = bottom - top - 40 - hh - 90
        if summary:
            bf, bl, bh = _fit_body(d, summary, max_w - 36, max(120, min(body_room, 440)), hi=48, lo=32)
        blk = 56 + hh + 44 + (len(bl) * bh + 12 if bl else 0)
        y = top + max(0, (bottom - top - blk) / 2) - 10
        _kicker(d, pad, y, category, accent)
        y += 56
        for i, ln in enumerate(hl):
            d.text((pad, y + i * lh), ln, font=f, fill=g.WHITE)
        y += hh + 50
        if bl:
            d.rectangle([pad, y + 4, pad + 6, y + 4 + len(bl) * bh - 14], fill=accent)
            for ln in bl:
                d.text((pad + 36, y), ln, font=bf, fill=(205, 205, 214))
                y += bh
        else:
            d.rectangle([pad, y, pad + 120, y + 7], fill=accent)

    g._frame(img, d, (255, 255, 255) if style == "split" else accent, industry_label, "")
    img = g._add_grain(img)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "JPEG", quality=93)
    return out_path


POINTS_PROMPT = """From this Instagram post about South Indian cinema, write {n} KEY POINTS for the image card.
Rules: each point is a short plain fact of at most 12 words; do NOT repeat the headline ("{h}"); no hashtags, no @handles
(write the name instead), no emojis, no question to the audience, no calls to follow. Use exact figures and dates.
Focus on the NEWS itself: what happened, numbers, dates, deals, reactions, what is still pending. Do NOT list the cast,
crew, director or music director (readers know them) - only use cast / crew details if the post has too little news
to fill the points.
Return ONLY a JSON array of {n} strings.

POST:
{c}"""


_HANDLES = {"ssrajamouli": "SS Rajamouli", "urstrulymahesh": "Mahesh Babu", "therealprithvi": "Prithviraj",
            "mythriofficial": "Mythri Movie Makers", "priyankachopra": "Priyanka Chopra", "alluarjun": "Allu Arjun",
            "tarak9999": "Jr NTR", "actorvijay": "Vijay", "kichchasudeepa": "Sudeep", "rishabshettyofficial": "Rishab Shetty"}


def _handle_name(m):
    h = m.group(1).lower()
    if h in _HANDLES:
        return _HANDLES[h]
    h = re.sub(r"(official|the|real|actor|actress|urstruly|_)", " ", h).strip()
    return h.title() if h else ""


def _clip(sent, words=17):
    sent = re.sub(r"@(\w+)", _handle_name, sent)
    sent = re.sub(r",?\s+(writing|saying|adding|stating|said|wrote)\b.*$", "", sent) if len(sent.split()) > words else sent
    sent = re.sub(r"\s+", " ", sent).strip(" -–—,;")
    m = re.search(r",\s+(which|making|with|but|while|as|after|writing|saying)\b", sent)
    if m and len(sent[:m.start()].split()) >= 6:      # drop the trailing clause, keep the main fact
        sent = sent[:m.start()]
    w = sent.split()
    if len(w) <= words:
        return sent.rstrip(".")
    cut = " ".join(w[:words])
    for sep in (", ", "; ", " - ", " which ", " for around "):
        i = cut.rfind(sep)
        if i > len(cut) * 0.5:
            return cut[:i].rstrip(",;. ")
    return cut.rstrip(",;:. ")


class Points(list):
    """Key points that also remember the full post text (used to detect the industry)."""
    context = ""


def key_points(caption, headline, n=3):
    pts = _key_points(caption, headline, n)
    out = Points(pts)
    out.context = caption or ""
    return out


def _key_points(caption, headline, n=3):
    """Short key points for the card: written by Gemini when it is available, else cut from the post's own sentences."""
    cap = re.sub(r"#\w+", "", caption or "").strip()
    try:
        import json
        import caption_gen
        raw = caption_gen._call_gemini(POINTS_PROMPT.format(n=n, h=headline, c=cap[:1800]), search=False)
        m = re.search(r"\[.*\]", raw, re.S)
        pts = [re.sub(r"\s+", " ", str(p)).strip().rstrip(".") for p in json.loads(m.group(0))] if m else []
        pts = [p for p in pts if 3 <= len(p.split()) <= 18][:n]
        if len(pts) >= 2:
            return pts
    except Exception:
        pass
    tw = set(re.findall(r"[a-z0-9]+", (headline or "").lower()))
    cands = []
    for ln in cap.splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if not ln or ln.upper() == ln:          # the all-caps first line is the headline again
            continue
        for sn in re.split(r"(?<=[.!?])\s+", ln):
            sw = re.findall(r"[a-z0-9]+", sn.lower())
            if len(sw) < 4 or len(set(sw) & tw) / len(set(sw)) > 0.75:
                continue
            if re.search(r"follow|which one|what do you think|tell us|tag a|comment|\?\s*$", sn, re.I):
                continue
            cands.append(sn)
    if not cands:  # a very short post: use its sentences even if they echo the headline
        for ln in cap.splitlines():
            for sn in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", ln).strip()):
                if len(sn.split()) >= 4 and not re.search(r"follow|which one|tell us|drop your|comment", sn, re.I):
                    cands.append(sn)
    crew = re.compile(r"^\s*(starring|directed by|music by|produced by|written by|cast|featuring)\b|\b(stars|starring|directed by|music composer|produced by)\b", re.I)
    news = [c for c in cands if not crew.search(c)]
    crew_only = [c for c in cands if crew.search(c)]
    cands = news + (crew_only if len(news) < 2 else [])   # cast / crew only when there is little real news
    cands.sort(key=lambda x: (-bool(re.search(r"\d", x)), len(x.split()) < 9 and not re.search(r"\d", x)))  # figures first, short fluff last   # figures and dates first, then the original order
    chosen = sorted(cands[:n], key=cands.index) if False else cands[:n]
    return [_clip(c) for c in chosen]


# ====================================================================== picture posts (you send the picture)

PHOTO_STYLES = ["fade", "framed", "overlay"]


def _text_block(d, title, summary, max_w, head_hi, head_lo, body_hi, body_lo, max_head_h, max_body_h):
    f, hl, lh = _fit_head(d, title, max_w, max_head_h, hi=head_hi, lo=head_lo)
    bl, bh, bf = [], 0, None
    if isinstance(summary, (list, tuple)):
        pts = [p for p in summary if p][:3]
        for size in range(body_hi, body_lo - 1, -1):
            bf = _font(SANS, size, 450)
            bl = []
            for p in pts:
                for k, ln in enumerate(_wrap(d, p, bf, max_w - 44)):
                    bl.append((k == 0, ln))
            bh = int(size * 1.36)
            if _pts_h(bl, bh) <= max_body_h:
                break
    elif summary:
        bf, bl, bh = _fit_body(d, summary, max_w - 40, max_body_h, hi=body_hi, lo=body_lo)  # room for the accent bar
    return f, hl, lh, bf, bl, bh


def _pts_h(bl, bh):
    """Height of a bullet list (tuples) or of plain lines (strings)."""
    if bl and isinstance(bl[0], tuple):
        return len(bl) * bh + 14 * max(0, sum(1 for m, _ in bl if m) - 1)
    return len(bl) * bh


def _draw_block(d, x, y, kicker, accent, f, hl, lh, bf, bl, bh, bar=True, chip=False):
    if kicker:
        if chip:  # readable on any picture
            kw = _kicker_w(d, kicker)
            d.rounded_rectangle([x - 16, y - 12, x + kw + 16, y + 40], radius=26, fill=(10, 10, 14))
        _kicker(d, x, y, kicker, accent)
        y += 52
    for i, ln in enumerate(hl):
        d.text((x, y + i * lh), ln, font=f, fill=g.WHITE)
    y += len(hl) * lh + 26
    if bl and isinstance(bl[0], tuple):
        first = True
        for marker, ln in bl:
            if marker:
                if not first:
                    y += 14
                first = False
                cy = y + int(bh * 0.52)
                d.polygon([(x, cy - 8), (x + 8, cy), (x, cy + 8), (x - 8, cy)], fill=accent)
            d.text((x + 28, y), ln, font=bf, fill=(226, 226, 232))
            y += bh
        return y
    if bl:
        if bar:
            d.rectangle([x, y + 6, x + 5, y + len(bl) * bh - 12], fill=accent)
        for ln in bl:
            d.text((x + (30 if bar else 0), y), ln, font=bf, fill=(208, 208, 216))
            y += bh
    return y


def _header(img, accent, label, shaded=True):
    import branding
    d = ImageDraw.Draw(img)
    branding.lockup(img, 50, 40, 60)
    tf = g._font(g.BOLD_FONTS, 24)
    tw = g._text_w(d, label, tf)
    d.rounded_rectangle([W - 60 - tw - 40, 54, W - 60, 102], radius=24, fill=(10, 10, 14), outline=accent, width=3)
    d.text((W - 60 - tw - 20, 62), label, font=tf, fill=accent)


def _footer(img, d, line=True, chip=None, accent=(255, 255, 255)):
    """Footer: the category chip (CINEMA NEWS, BOX OFFICE ...) on the left, the follow pill on the right."""
    import branding
    if line:
        d.line([(60, H - 100), (W - 60, H - 100)], fill=g.LINE, width=2)
    if chip:
        kw = _kicker_w(d, chip)
        x, y = 60, H - 84
        d.rounded_rectangle([x, y, x + kw + 36, y + 46], radius=23, fill=(10, 10, 14), outline=accent, width=2)
        _kicker(d, x + 18, y + 11, chip, accent)
    branding.follow_pill(img, H - 78, right=W - 60)


def _fade_to(img, y0, y1, col=None, a_max=1.0, power=1.35):
    col = col or g.BG
    lay = Image.new("RGBA", (W, y1 - y0), col + (255,))
    a = Image.new("L", (1, y1 - y0))
    for y in range(y1 - y0):
        a.putpixel((0, y), int(255 * a_max * (y / max(1, y1 - y0 - 1)) ** power))
    lay.putalpha(a.resize((W, y1 - y0)))
    img.paste(lay, (0, y0), lay)


def make_photo_story_card(title, photo_path, out_path, summary="", style=None, accent=None, label=None, category=None):
    from PIL import ImageOps
    title = nice_title(title).replace("₹", "Rs ")
    seed = g._hash(title)
    extra = (" ".join(summary) + " " + getattr(summary, "context", "")) if isinstance(summary, (list, tuple)) else (summary or "")
    ind = g._detect_industry(title) or g._detect_industry(title + " " + extra)
    accent = accent or (g.INDUSTRIES[ind]["color"] if ind else g._hex_to_rgb(g.config.ACCENT_COLOR))
    label = label or (g.INDUSTRIES[ind]["label"] if ind else "SOUTH CINEMA")
    category = category or g._detect_category(title)
    summary = summary if isinstance(summary, (list, tuple)) else (summary or "").strip()
    photo = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
    if style not in PHOTO_STYLES:  # portrait picture -> full-bleed overlay, landscape / square -> framed
        style = "overlay" if photo.height > photo.width else "framed"
    pad, max_w = 64, W - 128
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    bottom = H - 135

    if style == "overlay":
        img = ImageOps.fit(photo, (W, H), Image.LANCZOS, centering=(0.5, 0.28))
        f, hl, lh, bf, bl, bh = _text_block(probe, title, summary, max_w, 78, 46, 38, 30, 400, 330)
        T = len(hl) * lh + 26 + _pts_h(bl, bh)
        lum = sum(img.crop((0, H // 2, W, H)).convert("L").resize((1, 1)).getdata()) / 255.0
        reach = 420 + int(300 * max(0.0, lum - 0.35) / 0.65)   # a bright picture needs a taller, stronger fade
        _fade_to(img, max(0, bottom - T - reach), H, (8, 8, 12), 0.98, 0.7 if lum > 0.5 else 0.8)
        top_shade = Image.new("RGBA", (W, 240), (8, 8, 12, 255))
        ta = Image.new("L", (1, 240))
        for y in range(240):
            ta.putpixel((0, y), int(150 * (1 - y / 239) ** 1.4))
        top_shade.putalpha(ta.resize((W, 240)))
        img.paste(top_shade, (0, 0), top_shade)
        d = ImageDraw.Draw(img)
        _draw_block(d, pad + 16, bottom - T, None, accent, f, hl, lh, bf, bl, bh)
    elif style == "framed":
        img = Image.new("RGB", (W, H), g.BG)
        d = ImageDraw.Draw(img)
        f, hl, lh, bf, bl, bh = _text_block(d, title, summary, max_w, 72, 46, 36, 30, 330, 300)
        T = len(hl) * lh + 26 + _pts_h(bl, bh)
        ph = max(560, bottom - T - 36 - 132)
        pw = W - 2 * 56
        pic = ImageOps.fit(photo, (pw, ph), Image.LANCZOS, centering=(0.5, 0.3))
        mask = Image.new("L", (pw, ph), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw - 1, ph - 1], radius=26, fill=255)
        img.paste(pic, (56, 132), mask)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([56, 132, 56 + pw - 1, 132 + ph - 1], radius=26, outline=accent + (255,), width=3)
        _header(img, accent, category)
        d = ImageDraw.Draw(img)
        _draw_block(d, pad + 16, 132 + ph + 40, None, accent, f, hl, lh, bf, bl, bh)
        _footer(img, d, chip=label, accent=accent)
        img.save(out_path, "JPEG", quality=93)
        return out_path
    else:  # fade
        img = Image.new("RGB", (W, H), g.BG)
        d = ImageDraw.Draw(img)
        f, hl, lh, bf, bl, bh = _text_block(d, title, summary, max_w, 72, 46, 36, 30, 330, 300)
        T = len(hl) * lh + 26 + _pts_h(bl, bh)
        ph = max(600, bottom - T - 20)
        pic = ImageOps.fit(photo, (W, ph), Image.LANCZOS, centering=(0.5, 0.3))
        img.paste(pic, (0, 0))
        _fade_to(img, ph - 330, ph + 1, g.BG, 1.0)
        top_shade = Image.new("RGBA", (W, 220), (8, 8, 12, 255))
        ta = Image.new("L", (1, 220))
        for y in range(220):
            ta.putpixel((0, y), int(150 * (1 - y / 219) ** 1.4))
        top_shade.putalpha(ta.resize((W, 220)))
        img.paste(top_shade, (0, 0), top_shade)
        d = ImageDraw.Draw(img)
        _draw_block(d, pad + 16, ph - 40, None, accent, f, hl, lh, bf, bl, bh)

    _header(img, accent, category)
    d = ImageDraw.Draw(img)
    _footer(img, d, line=(style != "overlay"), chip=label, accent=accent)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "JPEG", quality=93)
    return out_path
