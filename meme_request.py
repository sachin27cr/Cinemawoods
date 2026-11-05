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
    "Optional: write a style after meme (meme: royal) - classic, brand, royal, studio, logo, forest, warm."
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


def _plain(s: str) -> str:
    return re.sub(r"\*+", "", s).strip()


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
        from caption_gen import _strip_hashtags, THREADS_TAG
        follow = (config.THREADS_FOLLOW_LINE or "").strip()
        follow = "" if follow == "-" else follow
        tail = "\n\n" + THREADS_TAG + (("\n\n" + follow) if follow else "")
        from caption_gen import _threads_fallback
        body = _strip_hashtags(_threads_fallback(headline, caption or headline, limit - len(tail)))
        return body + tail


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
    try:
        meme_card.make_meme_card(top, bottom, raws, out_path, style or meme_card.DEFAULT_STYLE)
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

    post_text = caption or _auto_caption(top, bottom)
    threads = _threads(top, bottom, config.THREADS_MAX_CHARS, post_text)
    import post_meta
    message_id = tg.send_draft(out_path, item_id, post_text, "Meme template", "",
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
    print(f"Meme draft created: {top[:60]}")
    return True
