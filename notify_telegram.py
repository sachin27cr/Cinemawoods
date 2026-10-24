"""
Telegram helpers: send drafts with Approve/Reject buttons, read button taps,
and update the buttons afterwards. Standard library only.

Use a bot token that no other script polls with getUpdates, otherwise the two
scripts will steal each other's button taps.
"""

import json
import urllib.error
import urllib.request
import uuid

import config

API_URL = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024


def is_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def _request(method: str, data: bytes, content_type: str, timeout: int = 30) -> dict:
    url = API_URL.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": content_type}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")[:200]
        print(f"[WARN] Telegram {method} failed: HTTP {e.code} {body}")
    except Exception as e:  # exception name only, so the bot token never reaches the log
        print(f"[WARN] Telegram {method} failed: {type(e).__name__}")
    return {"ok": False}


def _call(method: str, params: dict) -> dict:
    return _request(method, json.dumps(params).encode("utf-8"), "application/json")


def send_draft(image_path: str, item_id: str, caption: str, footer: str, source_link: str = ""):
    """Sends image + caption with Approve / Reject buttons.
    Returns the Telegram message id, or None if sending failed."""
    if not is_configured():
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - cannot send draft.")
        return None

    suffix = f"\n\n— {footer}"
    # Telegram limits photo captions to 1024 characters. A longer post text is
    # sent in full as a reply under the photo instead of being cut off.
    send_full_text_separately = len(caption) + len(suffix) > CAPTION_LIMIT
    if send_full_text_separately:
        text = "Draft post (full text below)" + suffix
    else:
        text = caption + suffix

    keyboard = [[
        {"text": "✅ Approve", "callback_data": f"a:{item_id}"},
        {"text": "❌ Reject", "callback_data": f"r:{item_id}"},
    ]]
    keyboard.append([{"text": "🎬 Make Reel", "callback_data": f"v:{item_id}"}])
    if source_link and len(source_link) < 1500:
        keyboard.append([{"text": "🔗 Open source", "url": source_link}])

    boundary = "----cinemawoods" + uuid.uuid4().hex
    parts = []

    def add_field(name: str, value: str):
        parts.append(
            (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n').encode()
            + value.encode("utf-8") + b"\r\n"
        )

    add_field("chat_id", str(config.TELEGRAM_CHAT_ID))
    add_field("caption", text)
    add_field("reply_markup", json.dumps({"inline_keyboard": keyboard}))
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    parts.append(
        (f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; '
         f'filename="draft.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode()
        + image_bytes + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())

    res = _request("sendPhoto", b"".join(parts), f"multipart/form-data; boundary={boundary}")
    if res.get("ok"):
        message_id = res["result"]["message_id"]
        if send_full_text_separately:
            try:
                _call("sendMessage", {
                    "chat_id": str(config.TELEGRAM_CHAT_ID),
                    "text": caption[:4000],
                    "reply_to_message_id": message_id,
                })
            except Exception as e:
                print(f"[WARN] Could not send the full post text: {type(e).__name__}")
        return message_id
    return None


def send_news(item_id: str, label: str, headline: str, caption: str, footer: str, source_link: str = "",
              article_image: bool = False):
    """News-first draft: text only, no picture. You reply to this message with the picture to use.
    Returns the Telegram message id, or None."""
    if not is_configured():
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - cannot send the news.")
        return None
    text = (f"📰 {label}\n\n{headline}\n\n{caption}\n\n— {footer}\n\n"
            "🖼 Reply to THIS message with the picture you want, and I'll build the post for your approval.")
    rows = []
    quick = []
    if article_image:
        quick.append({"text": "🖼 Use article picture", "callback_data": f"ai:{item_id}"})
    quick.append({"text": "📝 Text card", "callback_data": f"tc:{item_id}"})
    rows.append(quick)
    rows.append([{"text": "❌ Reject", "callback_data": f"r:{item_id}"}])
    if source_link and len(source_link) < 1500:
        rows.append([{"text": "🔗 Open source", "url": source_link}])
    res = _call("sendMessage", {"chat_id": str(config.TELEGRAM_CHAT_ID), "text": text[:4000],
                                "reply_markup": {"inline_keyboard": rows}, "disable_web_page_preview": True})
    return res["result"]["message_id"] if res.get("ok") else None


def set_buttons(chat_id, message_id, rows: list) -> None:
    _call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": message_id,
                                     "reply_markup": {"inline_keyboard": rows}})


def set_retry(chat_id, message_id, item_id: str, label: str = "🔁 Retry posting") -> None:
    set_buttons(chat_id, message_id, [[{"text": label, "callback_data": f"a:{item_id}"},
                                       {"text": "❌ Reject", "callback_data": f"r:{item_id}"}]])


def get_updates() -> dict:
    """Returns {"taps": [...], "messages": [...]} and confirms them with Telegram,
    so each is handled at most once. If a tap is lost, just tap the button again."""
    allowed = ["callback_query", "message"]
    res = _call("getUpdates", {"timeout": 0, "limit": 50, "allowed_updates": allowed})
    updates = res.get("result", []) if res.get("ok") else []
    if updates:
        last_id = max(u["update_id"] for u in updates)
        _call("getUpdates", {"offset": last_id + 1, "timeout": 0, "limit": 1, "allowed_updates": allowed})
    return {
        "taps": [u["callback_query"] for u in updates if "callback_query" in u],
        "messages": [u["message"] for u in updates if "message" in u],
    }


def get_button_taps() -> list:
    return get_updates()["taps"]


def download_file(file_id: str):
    """Downloads a file you sent to the bot. Returns bytes, or None on failure."""
    res = _call("getFile", {"file_id": file_id})
    path = (res.get("result") or {}).get("file_path") if res.get("ok") else None
    if not path:
        return None
    try:
        url = f"https://api.telegram.org/file/bot{config.TELEGRAM_BOT_TOKEN}/{path}"
        with urllib.request.urlopen(url, timeout=60) as resp:
            return resp.read()
    except Exception as e:  # name only, so the bot token never reaches the log
        print(f"[WARN] Telegram file download failed: {type(e).__name__}")
        return None


def answer_tap(callback_id: str, text: str = "") -> None:
    _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def set_status(chat_id, message_id, label: str, reel_for: str = "") -> None:
    """Replaces the buttons on a draft with a status label (plus a Make Reel button if reel_for is an item id)."""
    rows = [[{"text": label, "callback_data": "noop"}]]
    if reel_for:
        rows.append([{"text": "🎬 Make Reel", "callback_data": f"v:{reel_for}"}])
    _call("editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": {"inline_keyboard": rows},
    })


def send_video(video_path: str, caption: str, keyboard: list):
    """Sends a video with buttons. Returns the message id, or None."""
    if not is_configured():
        return None
    boundary = "----cinemawoods" + uuid.uuid4().hex
    parts = []

    def add_field(name: str, value: str):
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n').encode()
                     + value.encode("utf-8") + b"\r\n")

    add_field("chat_id", str(config.TELEGRAM_CHAT_ID))
    add_field("caption", caption[:1000])
    add_field("supports_streaming", "true")
    add_field("reply_markup", json.dumps({"inline_keyboard": keyboard}))
    with open(video_path, "rb") as f:
        data = f.read()
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="video"; '
                  f'filename="reel.mp4"\r\nContent-Type: video/mp4\r\n\r\n').encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    res = _request("sendVideo", b"".join(parts), f"multipart/form-data; boundary={boundary}", timeout=120)
    return res["result"]["message_id"] if res.get("ok") else None


def send_text(text: str) -> None:
    if is_configured():
        _call("sendMessage", {"chat_id": config.TELEGRAM_CHAT_ID, "text": text[:3500]})
