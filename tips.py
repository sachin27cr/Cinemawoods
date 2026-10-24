"""
Tips: send the bot a link or a headline, or a photo with a description, in Telegram.
- Link / text: the bot researches it (Gemini + Google Search), writes the headline and the
  5-8 sentence post text and picks a picture.
- Photo + description: your description is posted word for word; only the picture headline is created.
Either way you get a draft with Approve / Reject buttons.

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
import factcheck
from caption_gen import generate_from_tip, headline_for

URL_RE = re.compile(r"https?://[^\s<>\"']+")

HELP = (
    "/news - fetch fresh news and send drafts now (/news 5 = up to 5 drafts)\n\n"
    "How to send me a story:\n"
    "• Send a link, a headline, or rough notes - I research it and send back a draft.\n"
    "• Send a photo WITH a description as the caption - I put the main headline on the picture and post your "
    "description exactly as you wrote it (no rewriting).\n"
    "• Start that caption with  poster:  to keep the picture completely untouched (no headline on it).\n"
    "• Reel from your own content: send 1-6 photos (an album) with a caption starting  reel:  and your text "
    "(or just  reel: your text ). I add the headline and send a preview to post.\n"
    "• Forwarding a post from a channel works too.\n"
    "• Start with ! (for example: !Spirit teaser out today) to post something I could not fully verify.\n"
    "• News arrives as TEXT. Reply to the story message with the picture you want and I'll build the post (headline on "
    "the picture, description below) for your Approve. Caption your reply  poster:  to keep the picture untouched. "
    "The buttons under a story offer the article's own picture or a plain text card instead."
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


POSTER_PREFIX_RE = re.compile(r"(?i)^\s*(?:official\s+)?poster\s*[:\-]\s*")


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

    official = bool(file_id and POSTER_PREFIX_RE.match(text))
    if official:
        text = POSTER_PREFIX_RE.sub("", text, count=1).strip()
    if not file_id and IG_RE.search(text) and len(URL_RE.sub("", text).strip()) < 15:
        tg.send_text("I can't download pictures from Instagram links (Instagram blocks it). To repost an official poster:\n"
                     "1. Save the poster from the actor's post.\n"
                     "2. Send it here as a PHOTO with your description as the caption. I'll put the main headline on "
                     "the picture and post your description word for word. To keep the poster completely untouched "
                     "(no headline on it), start the caption with  poster:  .")
        return False

    force = text.startswith("!")
    if force:
        text = text[1:].strip()
    if file_id:
        # photo + description: your words are posted exactly as written; only the picture headline is created
        link, page = None, {}
        print(f"Photo tip received: {text[:80]!r} (official poster mode: {official})")
        caption = text
        headline = headline_for(text)
    else:
        link = _first_link(message, text)
        page = image_fetch.get_page_info(link) if link else {}
        print(f"Tip received: {text[:80]!r} (link: {bool(link)}, force: {force})")
        status, headline, caption, reason = generate_from_tip(text, page, force)
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

    check_note = "Your tip"
    if not file_id:
        ok, problems, checked = factcheck.check(caption, headline + " " + text, (page.get("text", "") + " " + page.get("description", "")))
        if checked and not ok:
            check_note = "Your tip · ⚠️ not in the article: " + ", ".join(problems[:5])
        elif checked:
            check_note = "Your tip · ✅ matches the article"
        elif link:
            check_note = "Your tip · ⚠️ article could not be opened - verify details"
    item_id = hashlib.sha1(f"{text}|{message.get('message_id')}|{time.time()}".encode()).hexdigest()[:10]
    deps.ensure_pillow()
    from graphic_gen import (OUT_DIR, make_headline_card, make_original_card, make_photo_card,
                             make_poster_card, save_source_copy)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{item_id}.jpg")
    lead = os.path.join(OUT_DIR, f"{item_id}-lead.tmp")
    used_photo = False
    src_image = ""
    try:
        if file_id:
            data = tg.download_file(file_id)
            if data:
                with open(lead, "wb") as f:
                    f.write(data)
                if official:
                    make_original_card(lead, out_path)
                else:
                    make_photo_card(headline, lead, out_path)
                src_image = save_source_copy(lead, os.path.join(OUT_DIR, f"{item_id}-src.jpg"))
                used_photo = True
        if not used_photo and page.get("image_url") and config.USE_ARTICLE_IMAGES:
            if image_fetch.save_image_url(page["image_url"], lead):
                make_poster_card(headline, lead, out_path)
                src_image = save_source_copy(lead, os.path.join(OUT_DIR, f"{item_id}-src.jpg"))
                used_photo = True
        if not used_photo:
            make_headline_card(headline, "", out_path=out_path)
    finally:
        if os.path.exists(lead):
            os.remove(lead)

    message_id = tg.send_draft(out_path, item_id, caption, check_note, link or "")
    if not message_id:
        tg.send_text("The draft was ready but Telegram would not take it. Please send the tip again.")
        return False

    store["items"][item_id] = {
        "title": headline,
        "link": link or "",
        "source": "Your tip",
        "caption": caption,
        "image": out_path.replace(os.sep, "/"),
        "src_image": src_image.replace(os.sep, "/"),
        "status": "pending",
        "message_id": message_id,
        "created_ts": time.time(),
        "posted": {},
    }
    print(f"Draft created from your tip: {headline}")
    return True
