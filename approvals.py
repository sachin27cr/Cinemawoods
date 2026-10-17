"""
Checks Telegram for Approve / Reject taps and publishes approved drafts to
Facebook + Instagram. Runs on its own schedule (.github/workflows/approvals.yml).
Standard library only, so the workflow needs no pip install.
"""

import os
import time

import config
import notify_telegram as tg
import pending
import post_meta


def _image_url(item: dict) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{item['image']}"


def handle_tap(tap: dict, store: dict) -> bool:
    """Handles one button tap. Returns True if pending.json changed."""
    message = tap.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    tap_id = tap.get("id", "")

    # Only taps from your own chat count.
    if str(chat_id) != str(config.TELEGRAM_CHAT_ID):
        print("[WARN] Ignoring a button tap from a different chat.")
        return False

    data = tap.get("data", "")
    if ":" not in data:  # status labels use callback_data "noop"
        tg.answer_tap(tap_id)
        return False

    action, item_id = data.split(":", 1)
    item = store["items"].get(item_id)
    if not item:
        tg.answer_tap(tap_id, "This draft has expired.")
        return False

    if item["status"] == "posted":
        tg.answer_tap(tap_id, "Already posted.")
        tg.set_status(chat_id, message_id, "✅ Posted")
        return False

    if action == "r":
        item["status"] = "rejected"
        tg.answer_tap(tap_id, "Rejected.")
        tg.set_status(chat_id, message_id, "❌ Rejected")
        print(f"Rejected: {item['title']}")
        return True

    if action != "a":
        tg.answer_tap(tap_id)
        return False

    tg.answer_tap(tap_id, "Posting...")
    print(f"Approved: {item['title']}")

    image_url = _image_url(item)
    done = item.setdefault("posted", {})
    errors = []

    if "facebook" not in done:
        try:
            done["facebook"] = post_meta.post_to_facebook(image_url, item["caption"])
            print("  [OK] Facebook")
        except Exception as e:
            errors.append(f"Facebook: {str(e)[:250]}")
    if "instagram" not in done:
        try:
            done["instagram"] = post_meta.post_to_instagram(image_url, item["caption"])
            print("  [OK] Instagram")
        except Exception as e:
            errors.append(f"Instagram: {str(e)[:250]}")

    if errors:
        item["status"] = "failed"
        for err in errors:
            print(f"  [ERROR] {err}")
        tg.send_text(
            f"⚠️ Posting problem for: {item['title']}\n\n"
            + "\n".join(errors)
            + "\n\nTap Approve again to retry the part that failed."
        )
        return True

    item["status"] = "posted"
    tg.set_status(chat_id, message_id, "✅ Posted to Facebook + Instagram")
    return True


def _photo_file_id(message: dict):
    """File id of an image you sent: a normal photo (largest size) or an image sent as a file."""
    if message.get("photo"):
        return message["photo"][-1]["file_id"]
    doc = message.get("document") or {}
    if str(doc.get("mime_type", "")).startswith("image/"):
        return doc.get("file_id")
    return None


def handle_message(message: dict, store: dict) -> bool:
    """Reply to a draft's picture with a poster image to rebuild that draft around it.
    Returns True if pending.json changed."""
    if str((message.get("chat") or {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
        return False
    file_id = _photo_file_id(message)
    if not file_id:
        return False

    replied = (message.get("reply_to_message") or {}).get("message_id")
    item_id, item = next(
        ((k, v) for k, v in store["items"].items() if replied and v.get("message_id") == replied),
        (None, None),
    )
    if not item:
        tg.send_text("To add a poster, long-press the draft PICTURE in this chat, tap Reply, "
                     "and send the poster image as the reply.")
        return False
    if item["status"] in ("posted", "rejected"):
        tg.send_text(f"That draft is already {item['status']}, so the poster was not used.")
        return False

    data = tg.download_file(file_id)
    if not data:
        tg.send_text("Could not download that image from Telegram. Please send it again.")
        return False

    from graphic_gen import OUT_DIR, make_poster_card  # needs Pillow; loaded only when a poster arrives

    os.makedirs("graphics", exist_ok=True)
    raw_path = os.path.join("graphics", f"{item_id}-src.bin")
    with open(raw_path, "wb") as f:
        f.write(data)
    out_path = os.path.join(OUT_DIR, f"{item_id}-p{int(time.time()) % 100000}.jpg")
    try:
        make_poster_card(item["title"], raw_path, out_path)
    except Exception as e:
        tg.send_text(f"Could not use that image ({type(e).__name__}). Please send a JPG or PNG poster.")
        return False
    finally:
        try:
            os.remove(raw_path)
        except OSError:
            pass

    old_message_id = item.get("message_id")
    item["image"] = out_path.replace(os.sep, "/")
    new_message_id = tg.send_draft(out_path, item_id, item["caption"],
                                   "Poster version", item["link"])
    if new_message_id:
        item["message_id"] = new_message_id
        if old_message_id:
            tg.set_status(config.TELEGRAM_CHAT_ID, old_message_id, "🖼 Replaced with poster version")
    item["status"] = "pending"
    print(f"Poster card built for: {item['title']}")
    return True


def main():
    if not tg.is_configured():
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - nothing to do.")
        return

    updates = tg.get_updates()
    taps, messages = updates["taps"], updates["messages"]
    if not taps and not messages:
        print("No button taps or messages waiting.")
        return

    store = pending.load()
    changed = False
    try:
        for message in messages:
            try:
                changed = handle_message(message, store) or changed
            except Exception as e:
                print(f"[ERROR] Could not handle a message: {type(e).__name__}: {str(e)[:200]}")
        for tap in taps:
            try:
                changed = handle_tap(tap, store) or changed
            except Exception as e:
                print(f"[ERROR] Could not handle a tap: {type(e).__name__}: {str(e)[:200]}")
    finally:
        if changed:
            pending.save(store)


if __name__ == "__main__":
    main()
