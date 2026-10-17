"""
Checks Telegram for Approve / Reject taps and publishes approved drafts to
Facebook + Instagram. Runs on its own schedule (.github/workflows/approvals.yml).
Standard library only, so the workflow needs no pip install.
"""

import os

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


def main():
    if not tg.is_configured():
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - nothing to do.")
        return

    taps = tg.get_button_taps()
    if not taps:
        print("No button taps waiting.")
        return

    store = pending.load()
    changed = False
    try:
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
