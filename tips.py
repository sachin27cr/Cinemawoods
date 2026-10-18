"""
Tips: send the bot a link, a headline, or a photo with a caption in Telegram.
The bot researches it (Gemini + Google Search), writes the headline and the
5-8 sentence post text, picks a picture and sends you a draft with
Approve / Reject buttons - exactly like the automatic news drafts.

Start your message with ! to post something Gemini could not fully verify.
"""

import hashlib
import os
import re
import time

import config
import deps
import image_fetch
import notify_telegram as tg
from caption_gen import generate_from_tip

URL_RE = re.compile(r"https?://[^\s<>\"']+")

HELP = (
    "/news - fetch fresh news and send drafts now (/news 5 = up to 5 drafts)\n\n"
    "How to send me a story:\n"
    "• Send a link, a headline, or rough notes - I research it and send back a draft.\n"
    "• Send a photo WITH a caption - I use your photo and research the caption.\n"
    "• Forwarding a post from a channel works too.\n"
    "• Start with ! (for example: !Spirit teaser out today) to post something I could not fully verify.\n"
    "• To change a draft's picture: long-press the draft PICTURE, tap Reply, send the poster."
)


def _first_link(message: dict, text: str):
    for key in ("entities", "caption_entities"):
        for ent in message.get(key) or []:
            if ent.get("type") == "text_link" and ent.get("url"):
                return ent["url"]
    m = URL_RE.search(text)
    return m.group(0).rstrip(").,;]") if m else None


IG_RE = re.compile(r"https?://(?:www\.)?instagram\.com/([^\s/?#]+)(?:/([^\s/?#]+))?", re.I)
HANDLE_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9._]{2,30})")
NOT_HANDLES = {"p", "reel", "reels", "tv", "stories", "explore", "share"}


def _poster_credit(text: str):
    """(is_official_poster, @handle or '') from the caption you sent with a photo."""
    handle = ""
    m = HANDLE_RE.search(text)
    if m:
        handle = m.group(1)
    for ig in IG_RE.finditer(text):
        if not handle and ig.group(1).lower() not in NOT_HANDLES:
            handle = ig.group(1)
    official = bool(handle or IG_RE.search(text) or re.match(r"(?i)\s*(official\s+)?poster\s*[:\-]", text))
    return official, handle.rstrip(".")


def _add_credit(caption: str, handle: str) -> str:
    if not handle:
        return caption
    line = f"📸 Poster: @{handle}"
    head, sep, tags = caption.rpartition("\n\n")
    if sep and tags.lstrip().startswith("#"):
        return f"{head}\n\n{line}\n\n{tags}"
    return f"{caption}\n\n{line}"


def handle_tip(message: dict, store: dict, file_id=None) -> bool:
    """Handles one tip message. Returns True if pending.json changed."""
    text = (message.get("text") or message.get("caption") or "").strip()

    if text.startswith("/"):
        if text.split()[0].lower().split("@")[0] in ("/start", "/help"):
            tg.send_text(HELP)
        return False
    if not text:
        tg.send_text("I got the photo but no caption. Add a caption saying what the news is, "
                     "or send it again as a reply to a draft's picture to use it as that draft's poster.")
        return False

    official, handle = _poster_credit(text) if file_id else (False, "")
    if not file_id and IG_RE.search(text) and len(URL_RE.sub("", text).strip()) < 15:
        tg.send_text("I can't download pictures from Instagram links (Instagram blocks it). To repost an official poster:\n"
                     "1. Save the poster from the actor's post.\n"
                     "2. Send it here as a PHOTO, with the caption: the news in a few words + the page's @handle "
                     "(for example: Salaar 2 release date out @hombalefilms).\n"
                     "I'll keep the poster exactly as it is, write the update, and credit the page.")
        return False

    force = text.startswith("!")
    if force:
        text = text[1:].strip()
    link = _first_link(message, text)
    page = image_fetch.get_page_info(link) if link else {}

    print(f"Tip received: {text[:80]!r} (link: {bool(link)}, photo: {bool(file_id)}, force: {force})")
    gen_text = text
    if official:
        gen_text = ("(An official poster from " + (f"@{handle}" if handle else "the film's or star's page") +
                    " is attached. Write this as a news update announcing what the poster shows.) " + text)
    status, headline, caption, reason = generate_from_tip(gen_text, page, force)
    if status == "unverified":
        tg.send_text(f"⚠️ I couldn't verify this: {reason or 'no reliable sources found'}.\n\n"
                     "If you're sure about it, send it again starting with ! and I'll write it from your details.")
        return False
    if status == "offtopic":
        tg.send_text(f"This doesn't look like South Indian cinema news ({reason or 'off topic'}). "
                     "Send it again starting with ! to post it anyway.")
        return False
    if status != "ok":
        tg.send_text(f"I couldn't research that just now: {reason or 'unknown error'}. Please try again in a minute.")
        return False

    item_id = hashlib.sha1(f"{text}|{message.get('message_id')}|{time.time()}".encode()).hexdigest()[:10]
    deps.ensure_pillow()
    from graphic_gen import OUT_DIR, make_headline_card, make_original_card, make_poster_card

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{item_id}.jpg")
    lead = os.path.join(OUT_DIR, f"{item_id}-lead.tmp")
    used_photo = False
    try:
        if file_id:
            data = tg.download_file(file_id)
            if data:
                with open(lead, "wb") as f:
                    f.write(data)
                if official:
                    make_original_card(lead, out_path)
                    caption = _add_credit(caption, handle)
                else:
                    make_poster_card(headline, lead, out_path)
                used_photo = True
        if not used_photo and page.get("image_url") and config.USE_ARTICLE_IMAGES:
            if image_fetch.save_image_url(page["image_url"], lead):
                make_poster_card(headline, lead, out_path)
                used_photo = True
        if not used_photo:
            make_headline_card(headline, "", out_path=out_path)
    finally:
        if os.path.exists(lead):
            os.remove(lead)

    message_id = tg.send_draft(out_path, item_id, caption, "Your tip", link or "")
    if not message_id:
        tg.send_text("The draft was ready but Telegram would not take it. Please send the tip again.")
        return False

    store["items"][item_id] = {
        "title": headline,
        "link": link or "",
        "source": "Your tip",
        "caption": caption,
        "image": out_path.replace(os.sep, "/"),
        "status": "pending",
        "message_id": message_id,
        "created_ts": time.time(),
        "posted": {},
    }
    print(f"Draft created from your tip: {headline}")
    return True
