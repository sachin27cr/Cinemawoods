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
    text = caption
    if len(text) + len(suffix) > CAPTION_LIMIT:
        text = text[: CAPTION_LIMIT - len(suffix) - 3].rstrip() + "..."
    text += suffix

    keyboard = [[
        {"text": "✅ Approve", "callback_data": f"a:{item_id}"},
        {"text": "❌ Reject", "callback_data": f"r:{item_id}"},
    ]]
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
        return res["result"]["message_id"]
    return None


def get_button_taps() -> list:
    """Returns waiting button taps and confirms them with Telegram, so each tap
    is handled at most once. If a tap is lost, just tap the button again."""
    res = _call("getUpdates", {
        "timeout": 0, "limit": 50, "allowed_updates": ["callback_query"],
    })
    updates = res.get("result", []) if res.get("ok") else []
    if updates:
        last_id = max(u["update_id"] for u in updates)
        _call("getUpdates", {
            "offset": last_id + 1, "timeout": 0, "limit": 1,
            "allowed_updates": ["callback_query"],
        })
    return [u["callback_query"] for u in updates if "callback_query" in u]


def answer_tap(callback_id: str, text: str = "") -> None:
    _call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})


def set_status(chat_id, message_id, label: str) -> None:
    """Replaces the buttons on a draft with a single status label."""
    _call("editMessageReplyMarkup", {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]},
    })


def send_text(text: str) -> None:
    if is_configured():
        _call("sendMessage", {"chat_id": config.TELEGRAM_CHAT_ID, "text": text[:3500]})
