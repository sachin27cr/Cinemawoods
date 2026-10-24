"""
Checks Telegram for Approve / Reject taps and publishes approved drafts to
Facebook + Instagram. Runs on its own schedule (.github/workflows/approvals.yml).
Standard library only, so the workflow needs no pip install.
"""

import json
import os
import time
import urllib.request

import config
import deps
import notify_telegram as tg
import pending
import post_meta
import reel_request
import tips


def _raw_image_url(item: dict) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{item['image']}"


def _image_urls(item: dict) -> list:
    """Public addresses Instagram/Facebook can fetch the card from: the Cloudflare Worker first (proper image
    headers and no rate limits), then raw GitHub as a backup."""
    urls = []
    base = os.environ.get("WORKER_URL", "").rstrip("/")
    name = os.path.basename(item["image"])
    if base:
        urls.append(f"{base}/i/{name}")
    urls.append(_raw_image_url(item))
    return urls


def _wait_public_image(url: str, tries: int = 10) -> bool:
    """True once the address really serves a JPEG (the card was just committed, so it can take a few seconds)."""
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=20) as resp:
                ctype = resp.headers.get("Content-Type", "")
                if resp.status == 200 and ctype.startswith("image/") and len(resp.read(2048)) > 500:
                    return True
        except Exception:
            pass
        time.sleep(4)
    return False


def _reel_url(path: str) -> str:
    """Public address Meta can fetch the video from (the Cloudflare Worker when set up, else raw GitHub)."""
    name = os.path.basename(path)
    base = os.environ.get("WORKER_URL", "").rstrip("/")
    if base:
        return f"{base}/v/{name}"
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{path.replace(os.sep, '/')}"


def _wait_public(url: str, tries: int = 12) -> bool:
    """The video is committed to the repo; wait until the public address actually serves it."""
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, headers={"Range": "bytes=0-1"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status in (200, 206):
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def _drop_reel_file(reel: dict) -> None:
    path = reel.get("path", "")
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
    reel["path"] = ""


def handle_reel_tap(action: str, item_id: str, item: dict, tap_id: str, chat_id, message_id) -> bool:
    """v = make a Reel from the draft, pr = post the Reel, dr = discard it."""
    reel = item.setdefault("reel", {})

    if action == "v":
        if reel.get("status") == "posted":
            tg.answer_tap(tap_id, "This Reel is already posted.")
            return False
        tg.answer_tap(tap_id, "Making the Reel - about a minute...")
        deps.ensure_pillow()
        import reel_maker
        try:
            path = reel_maker.make_reel(item_id, item["title"], item["caption"], item["image"],
                                        item.get("src_image", ""))
        except Exception as e:
            print(f"[ERROR] Reel render failed: {e}")
            tg.send_text(f"⚠️ I couldn't make the Reel: {str(e)[:250]}")
            return False
        reel_request.send_preview(item_id, item, path, old_message_id=reel.get("message_id"))
        return True

    if action == "dr":
        _drop_reel_file(reel)
        reel["status"] = "discarded"
        tg.answer_tap(tap_id, "Reel discarded.")
        tg.set_status(chat_id, message_id, "🗑 Reel discarded")
        return True

    # action == "pr"
    if reel.get("status") == "posted":
        tg.answer_tap(tap_id, "Already posted.")
        return False
    path = reel.get("path", "")
    if not path or not os.path.exists(path):
        tg.answer_tap(tap_id, "This Reel file is gone - tap Make Reel again.")
        return False

    tg.answer_tap(tap_id, "Posting the Reel...")
    url = _reel_url(path)
    print(f"Posting Reel: {item['title']} -> {url}")
    done = reel.setdefault("posted", {})
    errors = []
    if not _wait_public(url):
        errors.append("The video is not reachable at its public address yet "
                      f"({url.split('/')[2]}). If you use the Cloudflare Worker, redeploy the newest worker.js.")
    else:
        if "instagram" not in done:
            try:
                done["instagram"] = post_meta.post_reel_to_instagram(url, item["caption"])
                print("  [OK] Instagram Reel")
            except Exception as e:
                errors.append(f"Instagram Reel: {str(e)[:300]}")
        if "facebook" not in done:
            try:
                done["facebook"] = post_meta.post_reel_to_facebook(url, item["caption"])
                print("  [OK] Facebook Reel")
            except Exception as e:
                errors.append(f"Facebook Reel: {str(e)[:300]}")

    if errors:
        reel["status"] = "failed"
        for err in errors:
            print(f"  [ERROR] {err}")
        tg.send_text(f"⚠️ Reel posting problem for: {item['title']}\n\n" + "\n".join(errors)
                     + "\n\nTap Post Reel again to retry the part that failed.")
        return True

    reel["status"] = "posted"
    _drop_reel_file(reel)
    tg.set_status(chat_id, message_id, "✅ Reel posted to Instagram + Facebook")
    return True


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

    if action in ("v", "pr", "dr"):
        return handle_reel_tap(action, item_id, item, tap_id, chat_id, message_id)

    if action in ("ai", "tc"):
        tg.answer_tap(tap_id, "Building the post...")
        return _apply_quick(item_id, item, action)

    if item["status"] == "posted":
        tg.answer_tap(tap_id, "Already posted.")
        tg.set_status(chat_id, message_id, "✅ Posted", reel_for=item_id)
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

    if not item.get("image") or not os.path.exists(item["image"]):
        tg.answer_tap(tap_id, "This draft has no picture yet.")
        tg.send_text("This story has no picture yet. Reply to the story message with the picture you want.")
        return False

    tg.answer_tap(tap_id, "Posting...")
    print(f"Approved: {item['title']}")
    tg.set_buttons(chat_id, message_id, [[{"text": "⏳ Posting...", "callback_data": "noop"}]])

    done = item.setdefault("posted", {})
    errors = []
    urls = [u for u in _image_urls(item) if _wait_public_image(u)]
    print(f"  Reachable picture addresses: {[u.split('/')[2] for u in urls] or 'none'}")
    if not urls:
        urls = _image_urls(item)  # try anyway; the error text will say what Instagram saw

    if "facebook" not in done:
        try:
            done["facebook"] = post_meta.post_to_facebook(urls, item["caption"], local_path=item["image"])
            print("  [OK] Facebook")
        except Exception as e:
            errors.append(f"Facebook: {str(e)[:350]}")
    if "instagram" not in done:
        try:
            done["instagram"] = post_meta.post_to_instagram(urls, item["caption"])
            print("  [OK] Instagram")
        except Exception as e:
            errors.append(f"Instagram: {str(e)[:450]}")

    if errors:
        item["status"] = "failed"
        for err in errors:
            print(f"  [ERROR] {err}")
        ok_parts = [n.title() for n in done]
        tg.send_text(
            f"⚠️ Posting problem for: {item.get('headline') or item['title']}\n\n"
            + ("Already posted to: " + ", ".join(ok_parts) + "\n\n" if ok_parts else "")
            + "\n".join(errors)
            + "\n\nTap Retry posting under the draft (only the part that failed is retried)."
        )
        tg.set_retry(chat_id, message_id, item_id)
        return True

    item["status"] = "posted"
    tg.set_status(chat_id, message_id, "✅ Posted to Facebook + Instagram", reel_for=item_id)
    return True


def _photo_file_id(message: dict):
    """File id of an image you sent: a normal photo (largest size) or an image sent as a file."""
    if message.get("photo"):
        return message["photo"][-1]["file_id"]
    doc = message.get("document") or {}
    if str(doc.get("mime_type", "")).startswith("image/"):
        return doc.get("file_id")
    return None


def _finish_draft(item_id: str, item: dict, out_path: str, src_path: str = "", note: str = "Your picture") -> bool:
    """Sends the finished card + caption for approval and retires the earlier message of this story."""
    old_message_id = item.get("message_id")
    item["image"] = out_path.replace(os.sep, "/")
    if src_path:
        item["src_image"] = src_path.replace(os.sep, "/")
    new_message_id = tg.send_draft(out_path, item_id, item["caption"], note, item["link"])
    if not new_message_id:
        tg.send_text("The post was ready but Telegram would not take it. Please send the picture again.")
        return False
    item["message_id"] = new_message_id
    if old_message_id:
        tg.set_status(config.TELEGRAM_CHAT_ID, old_message_id, "🖼 Picture added - post is below ⬇")
    item["status"] = "pending"
    print(f"Post card built for: {item.get('headline') or item['title']}")
    return True


def _apply_image(item_id: str, item: dict, file_id: str, reply_text: str = "") -> bool:
    """Builds the post card around the picture you replied with.
    Start your reply's caption with  poster:  to keep the picture completely untouched."""
    if item["status"] in ("posted", "rejected"):
        tg.send_text(f"That story is already {item['status']}, so the picture was not used.")
        return False

    data = tg.download_file(file_id)
    if not data:
        tg.send_text("Could not download that image from Telegram. Please send it again.")
        return False

    deps.ensure_pillow()
    from graphic_gen import OUT_DIR, make_original_card, make_photo_card, save_source_copy

    os.makedirs(OUT_DIR, exist_ok=True)
    raw_path = os.path.join(OUT_DIR, f"{item_id}-src.bin")
    with open(raw_path, "wb") as f:
        f.write(data)
    out_path = os.path.join(OUT_DIR, f"{item_id}-p{int(time.time()) % 100000}.jpg")
    untouched = bool(tips.POSTER_PREFIX_RE.match(reply_text or ""))
    headline = item.get("headline") or item["title"]
    try:
        if untouched:
            make_original_card(raw_path, out_path)
        else:
            make_photo_card(headline, raw_path, out_path)
        src = save_source_copy(raw_path, os.path.join(OUT_DIR, f"{item_id}-src.jpg"))
    except Exception as e:
        tg.send_text(f"Could not use that image ({type(e).__name__}). Please send a JPG or PNG.")
        return False
    finally:
        try:
            os.remove(raw_path)
        except OSError:
            pass
    return _finish_draft(item_id, item, out_path, src, "Picture untouched" if untouched else "Your picture")


def _apply_quick(item_id: str, item: dict, kind: str) -> bool:
    """Quick buttons on a news message: ai = the article's own picture, tc = a text card."""
    if item["status"] in ("posted", "rejected"):
        return False
    deps.ensure_pillow()
    import image_fetch
    from graphic_gen import OUT_DIR, make_headline_card, make_photo_card, save_source_copy

    os.makedirs(OUT_DIR, exist_ok=True)
    headline = item.get("headline") or item["title"]
    out_path = os.path.join(OUT_DIR, f"{item_id}-p{int(time.time()) % 100000}.jpg")
    src = ""
    if kind == "ai":
        lead = os.path.join(OUT_DIR, f"{item_id}-lead.tmp.jpg")
        if item.get("article_image") and image_fetch.save_image_url(item["article_image"], lead):
            try:
                make_photo_card(headline, lead, out_path)
                src = save_source_copy(lead, os.path.join(OUT_DIR, f"{item_id}-src.jpg"))
            finally:
                if os.path.exists(lead):
                    os.remove(lead)
            return _finish_draft(item_id, item, out_path, src, "Article picture")
        tg.send_text("I couldn't download the article's picture. Reply with your own picture, or tap Text card.")
        return False
    make_headline_card(headline, item.get("source", ""), out_path=out_path)
    return _finish_draft(item_id, item, out_path, "", "Text card")


def handle_message(message: dict, store: dict) -> bool:
    """Your messages: a reply with an image to a draft's picture swaps in that poster;
    anything else is a new story tip (see tips.py). Returns True if pending.json changed."""
    if str((message.get("chat") or {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
        return False
    file_id = _photo_file_id(message)
    file_ids = message.get("_file_ids") or ([file_id] if file_id else [])
    text = (message.get("text") or message.get("caption") or "")

    if reel_request.is_reel_request(text) and not message.get("reply_to_message"):
        return reel_request.handle_reel_request(message, store, file_ids)
    if len(file_ids) > 1:
        tg.send_text("For several photos, start the caption with  reel:  and I'll make a Reel from them. "
                     "(A single photo with a description becomes a normal post.)")
        return False

    replied = (message.get("reply_to_message") or {}).get("message_id")
    item_id, item = next(
        ((k, v) for k, v in store["items"].items() if replied and v.get("message_id") == replied),
        (None, None),
    )
    if item and file_id:
        return _apply_image(item_id, item, file_id, text)
    if item:
        return False  # a text reply to a draft is not a tip
    return tips.handle_tip(message, store, file_id)


def _merge_albums(messages: list) -> list:
    """Photos sent together arrive as separate messages sharing a media_group_id; make them one message."""
    out, groups = [], {}
    for m in messages:
        gid = m.get("media_group_id")
        if not gid:
            out.append(m)
            continue
        merged = groups.get(gid)
        if merged is None:
            merged = dict(m)
            merged["_file_ids"] = []
            groups[gid] = merged
            out.append(merged)
        fid = _photo_file_id(m)
        if fid:
            merged["_file_ids"].append(fid)
        if (m.get("caption") or "").strip() and not (merged.get("caption") or "").strip():
            merged["caption"] = m["caption"]
    return out


def _drain_worker_queue() -> list:
    """Updates the Cloudflare worker kept for us (see cloudflare/worker.js)."""
    base = os.environ.get("WORKER_URL", "").rstrip("/")
    secret = os.environ.get("WORKER_SECRET", "")
    if not base:
        return []
    try:
        req = urllib.request.Request(base + "/queue", data=b"", method="POST",
                                     headers={"X-Queue-Secret": secret})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8")).get("updates", [])
    except Exception as e:
        print(f"[WARN] Could not read the worker queue: {type(e).__name__}")
        return []


def collect_updates(store: dict) -> dict:
    """Instant mode: the tap that started this run + anything queued by the worker.
    Classic mode (no worker set up): read Telegram directly."""
    raw = os.environ.get("TELEGRAM_UPDATE", "").strip()
    instant = bool(raw) or bool(os.environ.get("WORKER_URL"))
    if not instant:
        return tg.get_updates()

    updates = []
    if raw:
        try:
            updates.append(json.loads(raw))
        except ValueError:
            print("[WARN] Could not read the update that started this run.")
    updates += _drain_worker_queue()
    if any((u.get("message") or {}).get("media_group_id") for u in updates):
        time.sleep(6)  # the other photos of the album are still arriving
        updates += _drain_worker_queue()

    done = set(store.get("done_updates", []))
    fresh, seen = [], set()
    for u in sorted(updates, key=lambda x: x.get("update_id", 0)):
        uid = u.get("update_id")
        if uid in done or uid in seen:
            continue
        seen.add(uid)
        fresh.append(u)
    store["done_updates"] = (list(done) + [u.get("update_id") for u in fresh])[-300:]
    return {
        "taps": [u["callback_query"] for u in fresh if "callback_query" in u],
        "messages": [u["message"] for u in fresh if "message" in u],
    }


def main():
    if not tg.is_configured():
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set - nothing to do.")
        return

    store = pending.load()
    updates = collect_updates(store)
    taps, messages = updates["taps"], _merge_albums(updates["messages"])
    if not taps and not messages:
        print("No button taps or messages waiting.")
        pending.save(store)  # keeps the processed-update list current
        return

    changed = True  # the processed-update list changed
    try:
        for message in messages:
            try:
                changed = handle_message(message, store) or changed
            except Exception as e:
                print(f"[ERROR] Could not handle a message: {type(e).__name__}: {str(e)[:200]}")
                try:
                    tg.send_text(f"⚠️ I hit an error handling that message ({type(e).__name__}: {str(e)[:150]}). "
                                 "Please send it again; if it repeats, check the Actions log for 'approvals'.")
                except Exception:
                    pass
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
