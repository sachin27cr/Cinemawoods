"""
UPDATE card: a news-style post. Headline on top (key words in gold), a gold strip with the key fact, the poster (or
photo) on the left and four short pointers on the right, engagement question in the footer.

    make_update_card(out_path, poster_path, headline, strip_left, strip_right, pointers,
                     tag="UPDATE", lang="", credit="", footer="")

Headline markup:  *words*  -> gold.  Everything is drawn in code; the poster is shown whole (never cropped).
Fonts: Anton (headline, assets/fonts/Anton-Regular.ttf) + Montserrat (body). Falls back to Bebas/Oswald if missing.
"""

import os

from PIL import Image, ImageDraw, ImageFont, ImageOps

import graphic_gen as g
import meme_card

W, H = g.W, g.H            # 1080 x 1350
PAD = 64
BG, GOLD, TXT, TXT2, EDGE = (13, 20, 16), (245, 184, 0), (244, 241, 234), (167, 179, 170), (76, 94, 82)

_FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")


def _f(names, size):
    for n in names:
        p = n if os.path.isabs(n) else os.path.join(_FD, n)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return g._font(g.TITLE_FONTS, size)


def anton(size):
    return _f(("Anton-Regular.ttf", "Oswald-Bold.ttf", "BebasNeue-Regular.ttf"), size)


def body(size, bold=False):
    return _f(("Montserrat-SemiBold.ttf" if bold else "Montserrat-Medium.ttf", "DMSans.ttf"), size)


def _wrap_tokens(d, toks, font, width):
    lines, cur = [], []
    for w, k in toks:
        trial = cur + [(w, k)]
        if cur and d.textlength(" ".join(t for t, _ in trial), font=font) > width:
            lines.append(cur)
            cur = [(w, k)]
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _wrap_text(d, text, font, width):
    out = [""]
    for w in text.split():
        if out[-1] and d.textlength(out[-1] + " " + w, font=font) > width:
            out.append(w)
        else:
            out[-1] = (out[-1] + " " + w).strip()
    return out


def make_update_card(out_path, poster_path, headline, strip_left, strip_right, pointers,
                     tag="UPDATE", lang="", credit="", footer=""):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # --- header: logo + name + tag chip, language on the right
    if os.path.exists(g.LOGO_PATH):
        lg = Image.open(g.LOGO_PATH).convert("RGBA")
        lg.thumbnail((70, 70))
        im.paste(lg, (PAD, 48), lg)
    nf = anton(34)
    d.text((PAD + 82, 60), "CINEMA WOODS", font=nf, fill=TXT)
    x0 = PAD + 82 + d.textlength("CINEMA WOODS", font=nf) + 22
    tag = (tag or "UPDATE").upper()[:16]
    tf = body(21, True)
    bw = int(d.textlength(tag, font=tf)) + 52
    d.rounded_rectangle((x0, 50, x0 + bw, 100), 6, outline=GOLD, width=3)
    d.text((x0 + bw / 2, 75), tag, font=tf, fill=GOLD, anchor="mm")
    if lang:
        d.text((W - PAD, 75), lang.upper(), font=body(22), fill=TXT2, anchor="rm")

    # --- headline: biggest Anton size that fits in 3 lines
    toks = meme_card._tokens(headline)
    for size in range(92, 55, -2):
        hf = anton(size)
        lines = _wrap_tokens(d, toks, hf, W - 2 * PAD)
        if len(lines) <= 3:
            break
    y = 150
    for ln in lines:
        x = PAD
        for w, k in ln:
            d.text((x, y), w, font=hf, fill=GOLD if k else TXT)
            x += d.textlength(w + " ", font=hf)
        y += int(size * 1.09)

    # --- gold strip
    sy, sh = y + 22, 90
    d.rounded_rectangle((PAD, sy, W - PAD, sy + sh), 16, fill=GOLD)
    lf = body(22, True)
    left = (strip_left or "").upper()
    d.text((PAD + 32, sy + sh // 2), left, font=lf, fill=BG, anchor="lm")
    avail = W - 2 * PAD - 64 - d.textlength(left, font=lf) - 24
    right = (strip_right or "").upper()
    for rs in range(54, 28, -2):
        rf = anton(rs)
        if d.textlength(right, font=rf) <= avail:
            break
    d.text((W - PAD - 32, sy + sh // 2), right, font=rf, fill=BG, anchor="rm")

    # --- poster (whole, no crop) on the left
    top = sy + sh + 34
    ph = H - top - 120
    pw = 540
    c = ImageOps.exif_transpose(Image.open(poster_path)).convert("RGB")
    s = min(pw / c.width, ph / c.height)          # fit inside the box; never crop
    c = c.resize((max(1, int(c.width * s)), max(1, int(c.height * s))), Image.LANCZOS)
    pw = c.width
    im.paste(c, (PAD, top))
    d.rectangle((PAD, top, PAD + c.width, top + c.height), outline=EDGE, width=2)

    # --- pointers on the right (size shrinks until they all fit)
    tx = PAD + pw + 48
    mw = W - PAD - tx
    pts = [p for p in pointers if p.strip()][:5]
    avail_h = ph - 60
    for fs in range(29, 19, -1):
        pf = body(fs)
        lh = int(fs * 1.28)
        wrapped = [_wrap_text(d, p, pf, mw) for p in pts]
        total = sum(len(w) * lh + 24 for w in wrapped)
        if total <= avail_h:
            break
    py = top + 8
    for w in wrapped:
        d.rounded_rectangle((tx - 30, py + 8, tx - 16, py + 22), 3, fill=GOLD)
        for ln in w:
            d.text((tx, py), ln, font=pf, fill=TXT)
            py += lh
        py += 24
    if credit:
        d.text((tx, top + c.height), credit, font=body(18), fill=TXT2, anchor="ls")

    # --- footer
    ff = body(20)
    if footer:
        foot = footer
        while d.textlength(foot, font=ff) > W - 2 * PAD - 260 and len(foot) > 10:
            foot = foot[:-2]
        d.text((PAD, H - 62), foot, font=ff, fill=TXT2)
    d.text((W - PAD, H - 62), "@cinema_woods_", font=body(24, True), fill=TXT, anchor="ra")
    im.save(out_path, "JPEG", quality=93)
    return out_path
