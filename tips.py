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
import post_meta
import factcheck
import classify
from caption_gen import generate_from_tip, headline_for, read_screenshot

URL_RE = re.compile(r"https?://[^\s<>\"']+")

HELP = (
    "/news - fetch fresh news and send drafts now (/news 5 = up to 5 drafts)\n\n"
    "How to send me a story:\n"
    "• Send a link, a headline, or rough notes - I research it and send the post text; then reply with the picture.\n"
    "• Two-step with a screenshot: send it with the caption  post  or  meme  - I write the post (or the meme's top, bottom "
    "and description) from it. Then send ONLY the picture(s) (no caption; a meme takes 1-4 photos as one album) and you "
    "get the finished card to approve.\n"
    "• Send a SCREENSHOT of an Instagram post (no caption needed) - I read the text in it, write the post, and ask for the picture.\n"
    "• Send a photo WITH a description as the caption - I put the main headline on the picture and post your "
    "description exactly as you wrote it (no rewriting).\n"
    "• Start that caption with  poster:  to keep the picture completely untouched (no headline on it).\n"
    "• Reel from your own content: send 1-6 photos (an album) with a caption starting  reel:  and your text "
    "(or just  reel: your text ). I add the headline and send a preview to post.\n"
    "• Meme-style post: send 1-4 photos with a caption starting  meme:  (send  meme:  alone to see the format).\n"
    "• Forwarding a post from a channel works too.\n"
    "• Share an Instagram post link (Share → Telegram). I try to read its caption and picture; if Instagram blocks me, "
    "send the link together with the caption text.\n"
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


def _read_instagram_post(link: str) -> dict:
    """Best effort: caption + picture of a public Instagram post from its page's meta tags.
    {} when Instagram does not give them (it blocks many server addresses)."""
    if not link or not IG_RE.search(link):
        return {}
    try:
        page = image_fetch.get_page_info(link) or {}
    except Exception:
        return {}
    desc = (page.get("description") or "").strip()
    # typical form:  '1,234 likes, 56 comments - handle on October 30, 2026: "the caption".'
    m = re.search(r':\s*["\u201c](.+?)["\u201d]\.?\s*$', desc, re.S)
    caption = (m.group(1) if m else desc).strip()
    if len(caption) < 25 or "log in" in caption.lower()[:40]:
        return {}
    return {"caption": caption, "description": caption, "text": caption, "image_url": page.get("image_url", ""), "published_ts": None}


def _queue_tip_news(store: dict, item_id: str, headline: str, caption: str, check_note: str, link, page: dict) -> bool:
    """Text first: sends the written post and waits for the picture you reply with (same as the scheduled news)."""
    article_image = (page or {}).get("image_url", "") or ""
    label = f"{classify.detect_industry(headline + ' ' + caption) or 'SOUTH'} · {classify.detect_category(headline)}".upper()
    message_id = tg.send_news(item_id, label, headline, caption, check_note, link or "", bool(article_image))
    if not message_id:
        tg.send_text(f"The draft was ready but Telegram would not take it ({tg.LAST_ERROR or 'no reason given'}). Please send the tip again.")
        return False
    store["items"][item_id] = {
        "title": headline,
        "headline": headline,
        "link": link or "",
        "source": "Your tip",
        "caption": caption,
        "image": "",
        "src_image": "",
        "article_image": article_image,
        "status": "awaiting_image",
        "message_id": message_id,
        "created_ts": time.time(),
        "posted": {},
    }
    print(f"News-first draft created from your tip: {headline}")
    return True


def handle_tip(message: dict, store: dict, file_id=None) -> bool:
    """Handles one tip message. Returns True if pending.json changed."""
    text = (message.get("text") or message.get("caption") or "").strip()

    if text.startswith("/"):
        if text.split()[0].lower().split("@")[0] in ("/start", "/help"):
            tg.send_text(HELP)
        return False
    shot_text = ""
    if file_id and not text:
        # a photo with no caption: read the text inside the picture (an Instagram screenshot or a poster), write the
        # post from it, and ask for the picture afterwards
        data = tg.download_file(file_id)
        deps.ensure_pillow()
        shot_text = read_screenshot(data) if data else ""
        if not shot_text:
            tg.send_text("I could not read any film news text in that picture. Add a caption saying what the news is "
                         "(a photo WITH a caption becomes a post using that picture), or send the news as text.")
            return False
        text = shot_text
        file_id = None  # the screenshot is the source of the information, not the poster
    if not text:
        tg.send_text("I got the photo but no caption. Add a caption saying what the news is, "
                     "or send it again as a reply to a draft's picture to use it as that draft's poster.")
        return False

    official = bool(file_id and POSTER_PREFIX_RE.match(text))
    if official:
        text = POSTER_PREFIX_RE.sub("", text, count=1).strip()
    ig_page = {}
    if not file_id and IG_RE.search(text) and len(URL_RE.sub("", text).strip()) < 15:
        # a bare Instagram link (shared from the Instagram app): try to read the public post's caption and picture
        ig_page = _read_instagram_post(_first_link(message, text) or "")
        if not ig_page:
            tg.send_text("I could not read that Instagram post (Instagram often blocks bots). Please do ONE of these:\n"
                         "1. Send the link TOGETHER with the caption text, in one message (copy the caption from the post) - "
                         "I'll write the draft from it.\n"
                         "2. Send the poster as a PHOTO with the caption (your words are posted exactly as written). "
                         "Start the caption with  poster:  to keep the poster untouched.")
            return False
        text = f"{ig_page['caption']}\n{_first_link(message, text)}"

    force = text.startswith("!") or bool(shot_text)  # a screenshot of an official post is trusted
    if text.startswith("!"):
        text = text[1:].strip()
    if file_id:
        # photo + description: your words are posted exactly as written; only the picture headline is created
        link, page = None, {}
        print(f"Photo tip received: {text[:80]!r} (official poster mode: {official})")
        caption = text
        headline = headline_for(text)
    else:
        link = _first_link(message, text)
        if shot_text:
            page = {"title": "Text read from your screenshot", "description": shot_text[:600], "text": shot_text}
        else:
            page = ig_page or (image_fetch.get_page_info(link) if link else {})
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
    if not file_id and config.NEWS_FIRST:
        if shot_text:
            check_note = ("Read from your screenshot · "
                          + check_note.replace("Your tip · ", "").replace("matches the article", "matches the text in your screenshot")
                          .replace("not in the article", "not in the screenshot text"))
        return _queue_tip_news(store, item_id, headline, caption, check_note, link, page)
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

    threads = ""
    if post_meta.threads_configured():
        try:
            from caption_gen import threads_text
            threads = threads_text(headline, caption)
        except Exception as e:
            print(f"[WARN] Could not prepare the Threads text ({type(e).__name__})")
    message_id = tg.send_draft(out_path, item_id, caption, check_note, link or "", threads)
    if not message_id:
        tg.send_text(f"The draft was ready but Telegram would not take it ({tg.LAST_ERROR or 'no reason given'}). Please send the tip again.")
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
        "threads_text": threads,
    }
    print(f"Draft created from your tip: {headline}")
    return True
