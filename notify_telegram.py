"""
Sends a draft (image + caption) to a private Telegram chat for a manual
thumbs-up before it goes live. Matches the review-gate pattern used in your
other bots. If TELEGRAM_REVIEW is off in config, this module isn't called.
"""

import json
import urllib.request

import config


def send_draft_for_review(image_path: str, caption: str, source_link: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[WARN] Telegram review requested but TELEGRAM_BOT_TOKEN/CHAT_ID not set. Skipping review, printing draft instead:")
        print(caption)
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendPhoto"
    review_text = f"{caption}\n\n🔗 Source: {source_link}\n\n(Review only — this bot does not auto-post without your Meta approval step; see README for the posting run.)"

    with open(image_path, "rb") as img_f:
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body = []
        body.append(f"--{boundary}".encode())
        body.append(b'Content-Disposition: form-data; name="chat_id"')
        body.append(b"")
        body.append(str(config.TELEGRAM_CHAT_ID).encode())
        body.append(f"--{boundary}".encode())
        body.append(b'Content-Disposition: form-data; name="caption"')
        body.append(b"")
        body.append(review_text.encode("utf-8"))
        body.append(f"--{boundary}".encode())
        body.append(f'Content-Disposition: form-data; name="photo"; filename="draft.png"'.encode())
        body.append(b"Content-Type: image/png")
        body.append(b"")
        body.append(img_f.read())
        body.append(f"--{boundary}--".encode())
        body.append(b"")
        payload = b"\r\n".join(body)

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        print(f"[OK] Sent draft to Telegram for review: {source_link}")
    except Exception as e:
        print(f"[WARN] Telegram send failed: {e}")
