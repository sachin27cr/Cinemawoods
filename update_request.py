"""
UPDATE post on request (a news card: headline, gold strip, poster, 4 pointers). Send ONE photo (the poster / picture)
with a caption like

    update: award | kannada
    BAATHA, produced by *Dheekshith Shetty*, wins *Best Debut Film* at IFFA
    ---
    AWARD WON | IFFA 2026
    ---
    pointer one
    pointer two
    pointer three
    pointer four
    ---
    Poster: Dheekshith Shetty | Which win surprised you most? Comment below
    ---
    your own post description (optional)

Parts are separated by a line with ---:
  1. headline (*words* turn gold). An optional FIRST line before it sets  tag | language  (update: award | kannada).
  2. the gold strip:  left label | right key fact
  3. pointers, one per line (1-5; four looks best)
  4. optional:  credit | footer question
  5. optional: the post description (otherwise I write one - 500 characters or less, same text for Instagram and Threads)

Or send  update  with a SCREENSHOT of the news: I write everything above from it, send it back to you, and wait for the
poster photo (no caption) to build the card. Your words are used exactly as written.
"""

import hashlib
import os
import re
import time

import config
import deps
import notify_telegram as tg

PREFIX_RE = re.compile(r"(?is)^\s*(?:/update(?:@\w+)?\b|update(?:\s*\+\s*(?:photo|poster|image|picture))?(?=\s*(?::|\n|$)))\s*[:\-]?\s*")
SPLIT_RE = re.compile(r"(?m)^\s*-{3,}\s*$")
BULLET_RE = re.compile(r"^\s*(?:[-*•▪●]|\d{1,2}[.)])\s+")
LANGS = ("TELUGU", "TAMIL", "KANNADA", "MALAYALAM", "HINDI", "BENGALI", "MARATHI", "PUNJABI")
OPEN_TTL = 6 * 3600

HELP = (
    "To make an UPDATE post (news card with 4 pointers):\n"
    "• Send ONE photo (the poster) with a caption like this (if the text is longer than Telegram's 1024-character caption limit,\n  send the text as a normal message first, then the photo with no caption):\n\n"
    "update: award | kannada\n"
    "BAATHA, produced by *Dheekshith Shetty*, wins *Best Debut Film* at IFFA\n"
    "---\n"
    "AWARD WON | IFFA 2026\n"
    "---\n"
    "pointer one\n"
    "pointer two\n"
    "pointer three\n"
    "pointer four\n"
    "---\n"
    "Poster: Dheekshith Shetty | Which win surprised you most? Comment below\n"
    "---\n"
    "your own post description (optional)\n\n"
    "*words* turn gold. The first line (tag | language) and the last two parts are optional.\n"
    "• Or send the word  update  with a SCREENSHOT of the news: I write all of this from it, then you send ONLY the "
    "poster photo (no caption) and get the finished card to approve."
)


def is_update_request(text: str) -> bool:
    return bool(PREFIX_RE.match(text or ""))


def _split_pair(s: str):
    a, _, b = (s or "").partition("|")
    return a.strip(), b.strip()


def parse(text: str) -> dict:
    """Fields from the message text. Missing parts come back as ''. 'pointers' is a list."""
    body = PREFIX_RE.sub("", text or "", count=1)
    parts = [p.strip() for p in SPLIT_RE.split(body.strip())]
    parts += [""] * max(0, 5 - len(parts))
    head_lines = [ln for ln in parts[0].splitlines() if ln.strip()]
    tag, lang = "", ""
    if len(head_lines) > 1:                 # first line = options, the rest = headline
        a, b = _split_pair(head_lines[0]) if "|" in head_lines[0] else (head_lines[0].strip(), "")
        if b == "" and a.upper() in LANGS:
            a, b = "", a
        tag, lang = a, b
        head_lines = head_lines[1:]
    headline = " ".join(" ".join(head_lines).split())
    sl, sr = _split_pair(parts[1])
    pointers = [BULLET_RE.sub("", ln).strip() for ln in parts[2].splitlines() if ln.strip()]
    credit, footer = _split_pair(parts[3]) if "|" in parts[3] else ("", parts[3].strip())
    if parts[3] and "|" not in parts[3] and re.match(r"(?i)^(poster|photo|image|source)\s*:", parts[3]):
        credit, footer = parts[3].strip(), ""
    return {"tag": tag, "lang": lang, "headline": headline, "strip_left": sl, "strip_right": sr,
            "pointers": pointers, "credit": credit, "footer": footer, "caption": parts[4].strip()}


def _plain(s: str) -> str:
    return re.sub(r"\*+", "", s or "").strip()


def _language(f: dict) -> str:
    if f.get("lang"):
        return f["lang"].upper()
    try:
        import classify
        return classify.detect_industry(_plain(f["headline"]) + " " + " ".join(f["pointers"])) or ""
    except Exception:
        return ""


DESC_PROMPT = """Write the post description for an Instagram/Threads news post on a South Indian cinema page.
The picture already shows this, so do NOT repeat its content line by line; add the angle, the context or the hook.

HEADLINE: {headline}
KEY FACT: {strip}
POINTERS ON THE PICTURE:
{pointers}

Rules:
- Use ONLY facts that appear above. Add no name, number, date, film or platform that is not there.
- Line 1: a heading in CAPS. Then 2 short sentences. Then one line asking fans to comment.
- A blank line, then at most 5 hashtags (never #CinemaWoods).
- Exact dates as written; never "today" or "tomorrow". No emojis.
- The WHOLE text must be 480 characters or fewer.

Reply with ONLY the description."""


def _write_description(f: dict) -> str:
    try:
        from caption_gen import _call_gemini
        reply = _call_gemini(DESC_PROMPT.format(
            headline=_plain(f["headline"]), strip=f"{f['strip_left']} {f['strip_right']}".strip(),
            pointers="\n".join("- " + p for p in f["pointers"])), search=False)
    except Exception as e:
        print(f"[WARN] Update description step failed ({type(e).__name__}); using the simple caption")
        return ""
    text = re.sub(r"^\x00", "", reply).replace("*", "").strip().strip('"')
    if len(text) < 60 or len(text) > 500 or len(re.findall(r"#\w+", text)) > 5:
        return ""
    return text


def _auto_caption(f: dict) -> str:
    return (_plain(f["headline"]).upper() + "\n\n" + " ".join(f["pointers"][:2]) +
            "\n\n#SouthIndianCinema #Tollywood #Kollywood #Sandalwood #Mollywood")[:500]


SHOT_PROMPT = """This image is a screenshot (or poster) of South Indian cinema news, usually from an Instagram post. \
Read the news in it and write an UPDATE post (news card) for the Cinema Woods page. Ignore Instagram's own interface.

Rules:
- Use ONLY facts that are in the image. Add no name, number, date, film or platform that is not there.
  If the poster title and the caption title differ, say so in the CREDIT line instead of guessing.
- Exact dates as written in the image; never "today" or "tomorrow".
- HEADLINE: news-article style, in plain words, max 3 lines (about 12-16 words), e.g. "X, produced by Y, wins Z at W".
  Put *single stars* around the 3-6 most important words (names, award, number, date).
- TAG: one short word for the story type (UPDATE, AWARD, BOX OFFICE, OTT, TRAILER, ANNOUNCED).
- LANG: Telugu, Tamil, Kannada or Malayalam (or Hindi); leave empty if unclear.
- STRIP_LEFT: 2-4 word label. STRIP_RIGHT: the key fact (date, number, award), 2-5 words.
- P1..P4: exactly four pointers, each 12-22 words, EXCITING and interesting for fans (a twist, a quote, a record, what
  makes it special). Never bare fact-reporting or a cast list. Only facts from the image.
- CREDIT: "Poster: <handle or name if visible>" or empty. FOOTER: an engagement question for fans.
- DESCRIPTION: 480 characters or fewer in total, plain text: line 1 a heading in CAPS, then 2 short sentences that do
  not repeat the pointers, then a line asking fans to comment, a blank line and at most 5 hashtags (never #CinemaWoods).
  No emojis.
- If the image holds no readable film news, reply with exactly: NOTEXT

Reply in exactly this form and nothing else:
HEADLINE: <text>
TAG: <text>
LANG: <text>
STRIP_LEFT: <text>
STRIP_RIGHT: <text>
P1: <text>
P2: <text>
P3: <text>
P4: <text>
CREDIT: <text>
FOOTER: <text>
DESCRIPTION:
<text>"""


def _parse_shot(reply: str):
    reply = re.sub(r"^\x00", "", reply).strip().strip("`")
    if reply.upper().startswith("NOTEXT"):
        return None

    def get(key):
        m = re.search(rf"(?im)^\s*{key}\s*:\s*(.*)$", reply)
        return " ".join(m.group(1).split()) if m else ""
    desc = ""
    m = re.search(r"(?is)\bDESCRIPTION\s*:\s*(.+)$", reply)
    if m:
        desc = m.group(1).replace("*", "").strip()
    f = {"headline": re.sub(r"\*{2,}", "*", get("HEADLINE")), "tag": get("TAG"), "lang": get("LANG"),
         "strip_left": get("STRIP_LEFT"), "strip_right": get("STRIP_RIGHT"),
         "pointers": [p for p in (get("P1"), get("P2"), get("P3"), get("P4")) if p],
         "credit": get("CREDIT"), "footer": get("FOOTER"), "caption": desc}
    if len(f["headline"]) < 15 or len(f["pointers"]) < 3 or not f["strip_right"]:
        return None
    if not (60 <= len(desc) <= 500):
        f["caption"] = ""
    return f


TEXT_PROMPT = SHOT_PROMPT.replace(
    "This image is a screenshot (or poster) of South Indian cinema news, usually from an Instagram post. Read the news in it and write",
    "Below is the text of a South Indian cinema news story. Write").replace(
    " Ignore Instagram's own interface.", "").replace("that are in the image", "that are in the story text").replace(
    "as written in the image", "as written in the story text").replace(
    "If the image holds no readable film news", "If the text holds no usable film news").replace(
    "from the image", "from the story text") + "\n\nSTORY TEXT:\n{story}"


def write_from_text(headline: str, caption: str):
    """Fields for an update card written from a news story's own text (a reply with  update  to a news draft).
    None when Gemini is unavailable or the answer is unusable."""
    story = (headline + "\n\n" + caption)[:3500]
    try:
        from caption_gen import _call_gemini
        return _parse_shot(_call_gemini(TEXT_PROMPT.replace("{story}", story), search=False))
    except Exception as e:
        print(f"[WARN] Update text from a story failed ({type(e).__name__}: {e})")
        return None


def as_message(f: dict) -> str:
    """The fields in the `update:` format (so you can edit it and send it back with the poster)."""
    first = " | ".join(x for x in (f.get("tag", ""), f.get("lang", "")) if x)
    out = "update: " + first + "\n" if first else "update:\n"
    out += f["headline"] + "\n---\n" + f["strip_left"] + " | " + f["strip_right"] + "\n---\n"
    out += "\n".join(f["pointers"]) + "\n---\n" + (f["credit"] + " | " if f.get("credit") else "") + f.get("footer", "")
    if f.get("caption"):
        out += "\n---\n" + f["caption"]
    return out


def handle_update_screenshot(message: dict, store: dict, file_id: str) -> bool:
    """`update` + a screenshot: write the card text, send it, then wait for the poster photo."""
    deps.ensure_pillow()
    data = tg.download_file(file_id)
    if not data:
        tg.send_text(f"I couldn't download that screenshot ({tg.LAST_ERROR or 'no reason given'}). Please send it again.")
        return False
    from caption_gen import _call_gemini, image_to_b64
    b64 = image_to_b64(data)
    f = None
    if b64:
        try:
            f = _parse_shot(_call_gemini(SHOT_PROMPT, search=False, image_b64=b64))
        except Exception as e:
            print(f"[WARN] Update screenshot step failed: {e}")
    if not f:
        tg.send_text("I couldn't read film news text in that screenshot. Please send a clearer one with the word  update  "
                     "in the caption, or write the post yourself in the  update:  format (send  update:  alone to see it).")
        return False
    store["open_req"] = {"kind": "update", "fields": f, "ts": time.time()}
    tg.send_text("📰 UPDATE TEXT\n\n" + as_message(f) +
                 "\n\nNow send the poster/photo (ONE photo, no caption). You'll get the finished card to approve.\n"
                 "To change any words, copy the text above, edit it and send it back as the CAPTION of the photo.")
    print(f"Update text written from a screenshot: {f['headline'][:60]}")
    return True


def open_update(store: dict):
    req = store.get("open_req") or {}
    if req.get("kind") == "update" and time.time() - req.get("ts", 0) < OPEN_TTL:
        return req
    return None


def build_from_open(message: dict, store: dict, file_ids: list) -> bool:
    req = open_update(store)
    msg = dict(message)
    msg["caption"] = msg["text"] = as_message(req["fields"])
    changed = handle_update_request(msg, store, file_ids)
    if changed:
        store.pop("open_req", None)
    return changed


def handle_update_request(message: dict, store: dict, file_ids: list) -> bool:
    """Returns True if pending.json changed."""
    text = (message.get("text") or message.get("caption") or "").strip()
    f = parse(text)
    if not f["headline"] or not f["pointers"] or not (f["strip_left"] or f["strip_right"]):
        tg.send_text(HELP)
        return False
    if not file_ids:
        # text first (too long for Telegram's 1024-character caption): keep it and wait for the poster photo
        store["open_req"] = {"kind": "update", "fields": f, "ts": time.time()}
        tg.send_text("📰 Update text saved. Now send the poster as ONE photo with no caption - you'll get the finished card "
                     "to approve.")
        return True
    if len(file_ids) > 1:
        tg.send_text("An UPDATE card shows one picture - I used the first one.")

    deps.ensure_pillow()
    import update_card
    from graphic_gen import OUT_DIR

    os.makedirs(OUT_DIR, exist_ok=True)
    item_id = hashlib.sha1(f"{text}|{message.get('message_id')}|{time.time()}".encode()).hexdigest()[:10]
    print(f"Update request: {f['headline'][:60]!r}")
    data = tg.download_file(file_ids[0])
    if not data:
        tg.send_text(f"I couldn't download that photo ({tg.LAST_ERROR or 'Telegram gave no reason'}). "
                     "Please send it again as a photo (JPG or PNG).")
        return False
    raw = os.path.join(OUT_DIR, f"{item_id}-u.tmp")
    with open(raw, "wb") as fh:
        fh.write(data)
    out_path = os.path.join(OUT_DIR, f"{item_id}.jpg")
    src_path = os.path.join(OUT_DIR, f"{item_id}-src.jpg")
    try:
        update_card.make_update_card(out_path, raw, f["headline"], f["strip_left"], f["strip_right"], f["pointers"],
                                     tag=f["tag"] or "UPDATE", lang=_language(f), credit=f["credit"],
                                     footer=f["footer"])
        from graphic_gen import save_source_copy
        save_source_copy(raw, src_path)
    except Exception as e:
        print(f"[ERROR] Update card failed: {e}")
        tg.send_text(f"⚠️ I couldn't build the update card: {str(e)[:250]}")
        return False
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass

    post_text = f["caption"] or _write_description(f) or _auto_caption(f)
    try:
        from caption_gen import threads_from_caption
        threads = threads_from_caption(_plain(f["headline"]), post_text, config.THREADS_MAX_CHARS)
    except Exception as e:
        print(f"[WARN] Update Threads text failed ({type(e).__name__}); cutting the caption")
        threads = post_text[:config.THREADS_MAX_CHARS].rsplit(" ", 1)[0]
    import post_meta
    message_id = tg.send_draft(out_path, item_id, post_text, "Update card", "",
                               threads if post_meta.threads_configured() else "")
    if not message_id:
        tg.send_text(f"The post was ready but Telegram would not take it ({tg.LAST_ERROR or 'no reason given'}). "
                     "Please send it again.")
        return False
    store["items"][item_id] = {
        "title": _plain(f["headline"]), "headline": _plain(f["headline"]), "link": "", "source": "Your update",
        "caption": post_text, "image": out_path.replace(os.sep, "/"), "src_image": src_path.replace(os.sep, "/"),
        "status": "pending", "message_id": message_id, "created_ts": time.time(), "posted": {},
        "threads_text": threads,
    }
    print(f"Update draft created: {f['headline'][:60]}")
    return True
