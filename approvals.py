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


def _image_url(item: dict) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{item['image']}"


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


def _apply_poster(item_id: str, item: dict, file_id: str) -> bool:
    """Rebuilds a draft around a poster you replied with."""
    if item["status"] in ("posted", "rejected"):
        tg.send_text(f"That draft is already {item['status']}, so the poster was not used.")
        return False

    data = tg.download_file(file_id)
    if not data:
        tg.send_text("Could not download that image from Telegram. Please send it again.")
        return False

    deps.ensure_pillow()
    from graphic_gen import OUT_DIR, make_poster_card

    os.makedirs("graphics", exist_ok=True)
    raw_path = os.path.join("graphics", f"{item_id}-src.bin")
    with open(raw_path, "wb") as f:
        f.write(data)
    out_path = os.path.join(OUT_DIR, f"{item_id}-p{int(time.time()) % 100000}.jpg")
    try:
        make_poster_card(item["title"], raw_path, out_path)
        from graphic_gen import save_source_copy
        item["src_image"] = save_source_copy(raw_path, os.path.join(OUT_DIR, f"{item_id}-src.jpg")).replace(os.sep, "/")
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
        return _apply_poster(item_id, item, file_id)
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
