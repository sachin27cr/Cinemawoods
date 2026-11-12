"""
Meme template on request: send 1-4 photos (one album) with a caption like

    meme:
    Three *chart-topping albums* across different genres in just a *100-day span*
    ---
    That's the magic of **Devi Sri Prasad**

The first part is the top text, the second part (after a line with ---) the bottom text. *words* are highlighted
gold, **words** green. An optional third part (after another ---) is the post caption; without it the caption is
your two texts plus hashtags. Put  style: classic / brand / royal / studio / logo / forest / warm  on the first
line (for example  meme: royal ) to change the colours. Your words are used exactly as written.
"""

import hashlib
import os
import re
import time

import config
import deps
import notify_telegram as tg

MEME_PREFIX_RE = re.compile(r"(?is)^\s*(?:/meme(?:@\w+)?\b|meme\b)\s*[:\-]?\s*")
STYLE_RE = re.compile(r"(?i)^\s*(?:style\s*[:=]\s*)?(classic|brand|royal|studio|logo|forest|warm|logoexact)\b[ \t]*[:\-]?[ \t]*(?:\n|$)")
SPLIT_RE = re.compile(r"(?m)^\s*-{3,}\s*$")
TAGS = "#SouthIndianCinema #Tollywood #Kollywood #Sandalwood #Mollywood"

HELP = (
    "To make a meme-style post:\n"
    "• Send 1-4 photos (as one album) with a caption like this:\n\n"
    "meme:\n"
    "Three *chart-topping albums* across different genres in just a *100-day span*\n"
    "---\n"
    "That's the magic of **Devi Sri Prasad**\n\n"
    "The first part is the top text, the part after --- is the bottom text. *words* turn gold, **words** turn green.\n"
    "Optional: another --- line, then your own post caption (otherwise I use your two texts plus hashtags).\n"
    "Optional: write a style after meme (meme: royal) - classic, brand, royal, studio, logo, forest, warm.\n"
    "Optional: write  +photo  in the first line (meme+photo:) to post a carousel - the meme card first, then your "
    "original photo(s). Without it, only the meme card is posted."
)


def is_meme_request(text: str) -> bool:
    return bool(MEME_PREFIX_RE.match(text or ""))


def parse(text: str):
    """(style or '', top, bottom, caption or '') from the message text; top/bottom may be '' when missing."""
    body = MEME_PREFIX_RE.sub("", text or "", count=1)
    style = ""
    m = STYLE_RE.match(body)
    if m:
        style = m.group(1).lower()
        body = body[m.end():]
    parts = [p.strip() for p in SPLIT_RE.split(body.strip())]
    if len(parts) == 1:  # no --- line: first line = top, the rest = bottom
        lines = [ln for ln in parts[0].splitlines() if ln.strip()]
        parts = [lines[0], " ".join(lines[1:])] if len(lines) > 1 else [parts[0], ""]
    top = " ".join(parts[0].split())
    bottom = " ".join(parts[1].split()) if len(parts) > 1 else ""
    caption = parts[2].strip() if len(parts) > 2 else ""
    return style, top, bottom, caption


FLAG_RE = re.compile(r"(?i)\+\s*(?:photos?|originals?|orig|images?|pics?)\b")


def split_flag(text: str):
    """Looks for  +photo  in the FIRST line of a message (`meme+photo:`, `meme: +photo`, `meme royal +photo`, or a
    reply that is only `+photo`). Returns (text without the flag, True/False)."""
    text = text or ""
    first, sep, rest = text.partition("\n")
    if not FLAG_RE.search(first):
        return text, False
    is_meme = bool(MEME_PREFIX_RE.match(first)) or bool(re.match(r"(?i)^\s*(?:/post(?:@\w+)?|post)\s*(?:\+|[:\-]|$)", first))
    if not (is_meme or FLAG_RE.sub("", first).strip(" :-\t") == ""):
        return text, False  # a +photo somewhere in a normal sentence: leave it alone
    first = re.sub(r"\s{2,}", " ", FLAG_RE.sub("", first)).rstrip()
    first = re.sub(r"(?i)^(\s*(?:/meme(?:@\w+)?|meme|/post(?:@\w+)?|post))\s*(?=[:\-]|$)", r"\1", first)
    return (first + sep + rest).strip(), True


def make_extras(item_id: str, file_ids: list, limit: int = 9) -> list:
    """Downloads the pictures you sent and makes a swipe slide of each (the whole photo, nothing cropped)."""
    from graphic_gen import OUT_DIR
    os.makedirs(OUT_DIR, exist_ok=True)
    extras = []
    for i, fid in enumerate(file_ids[:limit]):
        data = tg.download_file(fid)
        if not data:
            continue
        raw = os.path.join(OUT_DIR, f"{item_id}-x{i}.tmp")
        with open(raw, "wb") as f:
            f.write(data)
        ep = os.path.join(OUT_DIR, f"{item_id}-o{i}.jpg")
        try:
            _fit_slide(raw, ep)
            extras.append(ep.replace(os.sep, "/"))
        except Exception as e:
            print(f"  [WARN] swipe photo {i + 1} unusable: {type(e).__name__}")
        finally:
            try:
                os.remove(raw)
            except OSError:
                pass
    return extras


def _fit_slide(src: str, out: str) -> None:
    """The original photo on a 1080x1350 slide: the whole picture, nothing cropped, on a soft blurred background
    (so Instagram does not cut the faces when it crops the carousel to the first slide's shape)."""
    from PIL import Image, ImageFilter
    W, H = 1080, 1350
    im = Image.open(src).convert("RGB")
    bg = im.copy()
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1))
    left, top = (bg.width - W) // 2, (bg.height - H) // 2
    bg = bg.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(28))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (9, 20, 12)), 0.45)
    fg_scale = min(W / im.width, H / im.height)
    fg = im.resize((max(1, int(im.width * fg_scale)), max(1, int(im.height * fg_scale))), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    bg.save(out, "JPEG", quality=92)


def _plain(s: str) -> str:
    return re.sub(r"\*+", "", s).strip()


DESC_PROMPT = """Write the Instagram description for a meme-style cinema post (South Indian cinema news page).
The picture already carries these two lines, which you must build on and never contradict.

TOP CAPTION: {top}
BOTTOM CAPTION: {bottom}

Rules:
- Use ONLY facts that appear in the two lines above. Add no name, number, date, film or platform that is not there.
- Exactly this shape, plain text, no markdown, no asterisks:
  Paragraph 1: 1-2 sentences saying what the news is, with the key facts (film, star, date, number).
  Paragraph 2: 1-2 sentences with the remaining details.
  One closing line asking fans to comment or tag a friend.
  A blank line, then exactly 5 hashtags that are relevant to this news and widely used (film name, star name, \
language industry tags). Never #CinemaWoods.
- Use exact dates as written; never "today" or "tomorrow".
- Keep the whole thing under 900 characters. No emojis.

Reply with ONLY the description."""


def _write_description(top: str, bottom: str) -> str:
    """Gemini writes the post description from the card's own two lines. '' when Gemini is unavailable."""
    import re as _re
    try:
        from caption_gen import _call_gemini
        reply = _call_gemini(DESC_PROMPT.format(top=_plain(top), bottom=_plain(bottom)), search=False)
    except Exception as e:
        print(f"[WARN] Meme description step failed ({type(e).__name__}); using the simple caption")
        return ""
    text = _re.sub(r"^\x00", "", reply).replace("*", "").strip().strip('"')
    tags = _re.findall(r"#\w+", text)
    if len(text) < 60 or len(tags) < 2 or len(text) > 1500:
        return ""
    return text


def _auto_caption(top: str, bottom: str) -> str:
    lines = [t if t[-1:] in ".!?" else t + "." for t in (_plain(top), _plain(bottom)) if t]
    return " ".join(lines) + "\n\n" + TAGS


def _threads(top: str, bottom: str, limit: int, caption: str = "") -> str:
    """Threads text: the Instagram caption shortened (same wording), up to the Threads limit."""
    headline = " ".join(t for t in (_plain(top), _plain(bottom)) if t)
    try:
        from caption_gen import threads_text
        return threads_text(headline, caption or headline, limit)
    except Exception as e:
        print(f"[WARN] Meme Threads text failed ({type(e).__name__}); using a simple one")
        from caption_gen import _strip_hashtags, _threads_tags, _threads_fallback
        follow = (config.THREADS_FOLLOW_LINE or "").strip()
        follow = "" if follow == "-" else follow
        tags = _threads_tags(caption or "#SouthIndianCinema")
        tail = (("\n\n" + tags) if tags else "") + (("\n\n" + follow) if follow else "")
        body = _strip_hashtags(_threads_fallback(headline, caption or headline, limit - len(tail)))
        return body + tail


SHOT_MEME_PROMPT = """This image is a screenshot (or poster) of South Indian cinema news, usually from an Instagram post. \
Read the news in it and write a MEME-STYLE post for the Cinema Woods page. Ignore Instagram's own interface.

Rules:
- Use ONLY facts that are in the image. Add no name, number, date, film or platform that is not there.
- Use exact dates as written in the image; never "today" or "tomorrow".
- TOP: one bold caption, the news itself with its key facts. Put *single stars* around the 2-4 most important words
  or phrases (film, star, number, date). Keep any comma or full stop right after a highlight INSIDE the stars.
- BOTTOM: a short punchy line (a reaction or a hook) that does NOT repeat names already used in TOP. Also use *single
  stars* on 1-2 key words. Never use double stars.
- DESCRIPTION: plain text, no asterisks: 2 short paragraphs with the details, then one line asking fans to comment or
  tag a friend, then a blank line and exactly 5 relevant, widely used hashtags (never #CinemaWoods). If the news is a
  box office figure, lead TOP with the collection figure.
- If the image holds no readable film news, reply with exactly: NOTEXT

Reply in exactly this form and nothing else:
TOP: <text>
BOTTOM: <text>
DESCRIPTION:
<text>"""

OPEN_TTL = 6 * 3600   # seconds an unanswered "now send the photos" request stays open


def _parse_shot_meme(reply: str):
    """(top, bottom, description) from Gemini's reply, or None when it is unusable."""
    reply = re.sub(r"^\x00", "", reply).strip().strip("`")
    if reply.upper().startswith("NOTEXT"):
        return None
    m = re.search(r"(?is)TOP\s*:\s*(.+?)\s*\n\s*BOTTOM\s*:\s*(.+?)\s*\n\s*DESCRIPTION\s*:\s*(.+)$", reply)
    if not m:
        return None
    top, bottom = " ".join(m.group(1).split()), " ".join(m.group(2).split())
    desc = m.group(3).replace("*", "").strip()
    desc = re.sub(r"\n-{3,}\s*", "\n", desc)
    top, bottom = re.sub(r"\*{2,}", "*", top), re.sub(r"\*{2,}", "*", bottom)
    if len(top) < 10 or len(bottom) < 4 or len(desc) < 60:
        return None
    return top, bottom, desc


def handle_meme_screenshot(message: dict, store: dict, file_id: str) -> bool:
    """`meme` + a screenshot: write the meme text (top, bottom, description), send it, then wait for the photos."""
    deps.ensure_pillow()
    data = tg.download_file(file_id)
    if not data:
        tg.send_text(f"I couldn't download that screenshot ({tg.LAST_ERROR or 'no reason given'}). Please send it again.")
        return False
    from caption_gen import _call_gemini, image_to_b64
    b64 = image_to_b64(data)
    parsed = None
    if b64:
        try:
            parsed = _parse_shot_meme(_call_gemini(SHOT_MEME_PROMPT, search=False, image_b64=b64))
        except Exception as e:
            print(f"[WARN] Meme screenshot step failed: {e}")
    if not parsed:
        tg.send_text("I couldn't read film news text in that screenshot. Please send a clearer one with the word  meme  "
                     "in the caption, or write the meme yourself in the  meme:  format.")
        return False
    top, bottom, desc = parsed
    store["open_req"] = {"kind": "meme", "top": top, "bottom": bottom, "caption": desc, "ts": time.time(),
                         "carousel": bool(message.get("_carousel"))}
    tg.send_text("🖼 MEME TEXT\n\nTOP: " + _plain(top) + "\nBOTTOM: " + _plain(bottom) +
                 "\n\nPOST DESCRIPTION:\n" + desc +
                 "\n\nNow send the photo(s) for the card - 1 to 4, as one album, with no caption. "
                 "You'll get the finished meme to approve." +
                 ("\n\nIt will post as a carousel: the meme card first, then your original photo(s)."
                  if message.get("_carousel") else
                  "\n\nTip: add  +photo  as the caption of the photos to also post the original photo(s) after the card."))
    print(f"Meme text written from a screenshot: {top[:60]}")
    return True


def open_meme(store: dict):
    req = store.get("open_req") or {}
    if req.get("kind") == "meme" and time.time() - req.get("ts", 0) < OPEN_TTL:
        return req
    return None


def build_from_open(message: dict, store: dict, file_ids: list) -> bool:
    """The photos you sent after a `meme` screenshot: build the card with the text that was written."""
    req = open_meme(store)
    text = "meme:\n" + req["top"] + "\n---\n" + req["bottom"] + "\n---\n" + req["caption"]
    msg = dict(message)
    msg["caption"], msg["text"] = text, text
    msg["_carousel"] = bool(message.get("_carousel") or req.get("carousel"))
    changed = handle_meme_request(msg, store, file_ids)
    if changed:
        store.pop("open_req", None)
    return changed


def handle_meme_request(message: dict, store: dict, file_ids: list) -> bool:
    """Returns True if pending.json changed."""
    text = (message.get("text") or message.get("caption") or "").strip()
    style, top, bottom, caption = parse(text)
    if not file_ids or not top:
        tg.send_text(HELP)
        return False

    deps.ensure_pillow()
    import meme_card
    from graphic_gen import OUT_DIR

    os.makedirs(OUT_DIR, exist_ok=True)
    item_id = hashlib.sha1(f"{text}|{message.get('message_id')}|{time.time()}".encode()).hexdigest()[:10]
    print(f"Meme request: {top[:60]!r} with {len(file_ids)} picture(s), style {style or 'default'}")

    raws = []
    for i, fid in enumerate(file_ids[:4]):
        data = tg.download_file(fid)
        if not data:
            continue
        raw = os.path.join(OUT_DIR, f"{item_id}-m{i}.tmp")
        with open(raw, "wb") as f:
            f.write(data)
        raws.append(raw)
    if not raws:
        tg.send_text("I couldn't download those photos "
                     f"({tg.LAST_ERROR or 'Telegram gave no reason'}). Please send them again as photos (JPG or PNG).")
        return False
    if len(file_ids) > 4:
        tg.send_text("A meme card holds up to 4 photos - I used the first 4.")

    out_path = os.path.join(OUT_DIR, f"{item_id}.jpg")
    extras = []
    try:
        meme_card.make_meme_card(top, bottom, raws, out_path, style or meme_card.DEFAULT_STYLE)
        if message.get("_carousel"):
            for i, r in enumerate(raws[:9]):
                ep = os.path.join(OUT_DIR, f"{item_id}-o{i}.jpg")
                _fit_slide(r, ep)
                extras.append(ep.replace(os.sep, "/"))
            if extras:
                from graphic_gen import add_swipe_hint
                add_swipe_hint(out_path)
    except Exception as e:
        print(f"[ERROR] Meme card failed: {e}")
        tg.send_text(f"⚠️ I couldn't build the meme card: {str(e)[:250]}")
        return False
    finally:
        for r in raws:
            try:
                os.remove(r)
            except OSError:
                pass

    post_text = caption or _write_description(top, bottom) or _auto_caption(top, bottom)
    threads = _threads(top, bottom, config.THREADS_MAX_CHARS, post_text)
    import post_meta
    footer = "Meme template" + (f" · carousel: card + {len(extras)} original photo(s)" if extras else "")
    message_id = tg.send_draft(out_path, item_id, post_text, footer, "",
                               threads if post_meta.threads_configured() else "")
    if not message_id:
        tg.send_text(f"The meme was ready but Telegram would not take it ({tg.LAST_ERROR or 'no reason given'}). "
                     "Please send it again.")
        return False
    store["items"][item_id] = {
        "title": _plain(top), "headline": _plain(top), "link": "", "source": "Your meme",
        "caption": post_text, "image": out_path.replace(os.sep, "/"), "src_image": "",
        "status": "pending", "message_id": message_id, "created_ts": time.time(), "posted": {},
        "threads_text": threads,
    }
    if extras:
        store["items"][item_id]["extra_images"] = extras
    print(f"Meme draft created: {top[:60]}")
    return True
