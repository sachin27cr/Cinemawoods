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


# ====================================================================== picture posts (you send the picture)

PHOTO_STYLES = ["fade", "framed", "overlay"]


def _text_block(d, title, summary, max_w, head_hi, head_lo, body_hi, body_lo, max_head_h, max_body_h):
    f, hl, lh = _fit_head(d, title, max_w, max_head_h, hi=head_hi, lo=head_lo)
    bl, bh, bf = [], 0, None
    if summary:
        bf, bl, bh = _fit_body(d, summary, max_w, max_body_h, hi=body_hi, lo=body_lo)
    return f, hl, lh, bf, bl, bh


def _draw_block(d, x, y, kicker, accent, f, hl, lh, bf, bl, bh, bar=True):
    _kicker(d, x, y, kicker, accent)
    y += 52
    for i, ln in enumerate(hl):
        d.text((x, y + i * lh), ln, font=f, fill=g.WHITE)
    y += len(hl) * lh + 22
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


def _footer(img, d, line=True):
    import branding
    if line:
        d.line([(60, H - 100), (W - 60, H - 100)], fill=g.LINE, width=2)
    d.text((60, H - 62), "SOUTH INDIAN CINEMA", font=g._font(g.REG_FONTS, 24), fill=g.MUTED)
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
    ind = g._detect_industry(title)
    accent = accent or (g.INDUSTRIES[ind]["color"] if ind else g._hex_to_rgb(g.config.ACCENT_COLOR))
    label = label or (g.INDUSTRIES[ind]["label"] if ind else "SOUTH CINEMA")
    category = category or g._detect_category(title)
    summary = (summary or "").strip()
    photo = ImageOps.exif_transpose(Image.open(photo_path)).convert("RGB")
    if style not in PHOTO_STYLES:  # portrait picture -> full-bleed overlay, landscape / square -> framed
        style = "overlay" if photo.height > photo.width else "framed"
    pad, max_w = 64, W - 128
    probe = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    bottom = H - 120

    if style == "overlay":
        img = ImageOps.fit(photo, (W, H), Image.LANCZOS, centering=(0.5, 0.28))
        f, hl, lh, bf, bl, bh = _text_block(probe, title, summary, max_w, 92, 54, 36, 30, 400, 250)
        T = 52 + len(hl) * lh + 22 + len(bl) * bh
        _fade_to(img, max(0, bottom - T - 420), H, (8, 8, 12), 0.98, 0.8)
        top_shade = Image.new("RGBA", (W, 240), (8, 8, 12, 255))
        ta = Image.new("L", (1, 240))
        for y in range(240):
            ta.putpixel((0, y), int(150 * (1 - y / 239) ** 1.4))
        top_shade.putalpha(ta.resize((W, 240)))
        img.paste(top_shade, (0, 0), top_shade)
        d = ImageDraw.Draw(img)
        _draw_block(d, pad, bottom - T, category, accent, f, hl, lh, bf, bl, bh)
    elif style == "framed":
        img = Image.new("RGB", (W, H), g.BG)
        d = ImageDraw.Draw(img)
        f, hl, lh, bf, bl, bh = _text_block(d, title, summary, max_w, 84, 52, 34, 30, 330, 210)
        T = 52 + len(hl) * lh + 22 + len(bl) * bh
        ph = max(560, bottom - T - 36 - 132)
        pw = W - 2 * 56
        pic = ImageOps.fit(photo, (pw, ph), Image.LANCZOS, centering=(0.5, 0.3))
        mask = Image.new("L", (pw, ph), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw - 1, ph - 1], radius=26, fill=255)
        img.paste(pic, (56, 132), mask)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([56, 132, 56 + pw - 1, 132 + ph - 1], radius=26, outline=accent + (255,), width=3)
        _header(img, accent, label)
        d = ImageDraw.Draw(img)
        _draw_block(d, pad, 132 + ph + 36, category, accent, f, hl, lh, bf, bl, bh)
        _footer(img, d)
        img.save(out_path, "JPEG", quality=93)
        return out_path
    else:  # fade
        img = Image.new("RGB", (W, H), g.BG)
        d = ImageDraw.Draw(img)
        f, hl, lh, bf, bl, bh = _text_block(d, title, summary, max_w, 88, 52, 34, 30, 330, 210)
        T = 52 + len(hl) * lh + 22 + len(bl) * bh
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
        _draw_block(d, pad, ph - 60, category, accent, f, hl, lh, bf, bl, bh)

    _header(img, accent, label)
    d = ImageDraw.Draw(img)
    _footer(img, d, line=(style != "overlay"))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path, "JPEG", quality=93)
    return out_path
