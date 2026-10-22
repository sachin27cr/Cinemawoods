"""
Reel on request: send one or more photos with a caption starting with  reel:  (or just text starting with reel:)
and the bot makes a Reel from them. Your words are used word for word; only the headline on the video is created.
"""

import hashlib
import os
import re
import time

import config
import deps
import notify_telegram as tg
from caption_gen import headline_for

REEL_PREFIX_RE = re.compile(r"(?is)^\s*(?:/reel(?:@\w+)?\b|reel\s*[:\-])\s*")

HELP = (
    "To make a Reel from your own content:\n"
    "• Send 1-6 photos (as one album) with a caption that starts with  reel:  - for example\n"
    "  reel: Salaar 2 shoot begins today. Prabhas joins the sets in Hyderabad.\n"
    "• Or send just text starting with  reel:  to get a text Reel.\n"
    "I post your text word for word, put a headline on the video, and send a preview with Post Reel / Discard."
)


def is_reel_request(text: str) -> bool:
    return bool(REEL_PREFIX_RE.match(text or ""))


def send_preview(item_id: str, item: dict, path: str, old_message_id=None):
    """Sends the Reel preview with Post / Discard buttons and records it on the item."""
    mid = tg.send_video(path, f"🎬 Reel preview ({config.REEL_SECONDS}s+)\n\n{item['title']}\n\n"
                              "Post Reel publishes it on Instagram and Facebook.",
                        [[{"text": "✅ Post Reel", "callback_data": f"pr:{item_id}"},
                          {"text": "🗑 Discard", "callback_data": f"dr:{item_id}"}]])
    if old_message_id and mid:
        tg.set_status(config.TELEGRAM_CHAT_ID, old_message_id, "🎬 Replaced by a newer preview")
    item["reel"] = {"status": "rendered", "path": path, "message_id": mid, "posted": {}}
    if not mid:
        tg.send_text("The Reel was made but Telegram would not take the preview. Please send it again.")
    return mid


def handle_reel_request(message: dict, store: dict, file_ids: list) -> bool:
    """Returns True if pending.json changed."""
    text = (message.get("text") or message.get("caption") or "").strip()
    body = REEL_PREFIX_RE.sub("", text, count=1).strip()
    if not body:
        tg.send_text(HELP)
        return False

    deps.ensure_pillow()
    import reel_maker
    from graphic_gen import OUT_DIR, make_headline_card, make_photo_card, save_source_copy

    item_id = hashlib.sha1(f"{body}|{message.get('message_id')}|{time.time()}".encode()).hexdigest()[:10]
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Reel request: {body[:80]!r} with {len(file_ids)} picture(s)")
    headline = headline_for(body)

    # your pictures -> lighter working copies
    sources = []
    for i, fid in enumerate(file_ids[:config.REEL_MAX_IMAGES]):
        data = tg.download_file(fid)
        if not data:
            continue
        raw = os.path.join(OUT_DIR, f"{item_id}-dl{i}.tmp")
        with open(raw, "wb") as f:
            f.write(data)
        try:
            sources.append(save_source_copy(raw, os.path.join(OUT_DIR, f"{item_id}-s{i}.jpg")))
        except Exception as e:
            print(f"  [WARN] picture {i + 1} unusable: {type(e).__name__}")
        finally:
            os.remove(raw)
    if file_ids and not sources:
        tg.send_text("I couldn't read those pictures. Please send them again as photos (JPG or PNG).")
        return False
    if len(file_ids) > config.REEL_MAX_IMAGES:
        tg.send_text(f"Using the first {config.REEL_MAX_IMAGES} pictures (the limit per Reel).")

    # the card also serves as the fallback picture and the thumbnail
    card_path = os.path.join(OUT_DIR, f"{item_id}.jpg")
    if sources:
        make_photo_card(headline, sources[0], card_path)
    else:
        make_headline_card(headline, "", out_path=card_path)

    try:
        path = reel_maker.make_reel(item_id, headline, body, card_path, images=sources)
    except Exception as e:
        print(f"[ERROR] Reel render failed: {e}")
        tg.send_text(f"⚠️ I couldn't make the Reel: {str(e)[:250]}")
        return False
    finally:
        for extra in sources[1:]:  # keep only the first picture (used if you tap Make Reel again)
            try:
                os.remove(extra)
            except OSError:
                pass

    item = {
        "title": headline, "caption": body, "link": "", "source": "Your reel",
        "image": card_path.replace(os.sep, "/"),
        "src_image": sources[0].replace(os.sep, "/") if sources else "",
        "status": "reel", "message_id": None, "created_ts": time.time(), "posted": {},
    }
    send_preview(item_id, item, path)
    store["items"][item_id] = item
    return True
