"""
Main run (scheduled 3x/day):
  RSS fetch -> relevance filter + trending rank -> dedup -> caption -> JPEG card

  TELEGRAM_REVIEW=1 (default): each story is sent to Telegram with Approve /
      Reject buttons and saved in pending.json. Nothing is posted here; the
      separate approvals workflow (approvals.py) publishes approved stories.
  TELEGRAM_REVIEW=0: stories are posted straight to Facebook + Instagram.

  python main.py --dry-run  -> builds captions/cards, sends and posts nothing
"""

import argparse
import os
import subprocess
import time

import classify
import config
import image_fetch
import notify_telegram
import pending
import caption_gen
from caption_gen import SKIP, generate_caption
from classify import pick_diverse
from dedup import filter_unposted, mark_posted, mark_skipped
from fetch_news import fetch_all
from graphic_gen import OUT_DIR, make_headline_card, make_poster_card
from post_meta import post_everywhere


def prune_old_images(store: dict) -> None:
    """Deletes cards that are no longer waiting for approval."""
    if not os.path.isdir(OUT_DIR):
        return
    keep = set(store["items"].keys())
    keep |= {os.path.splitext(os.path.basename(v.get("image", "")))[0] for v in store["items"].values()}
    for name in os.listdir(OUT_DIR):
        stem, ext = os.path.splitext(name)
        if ext.lower() in (".jpg", ".png") and stem not in keep:
            try:
                os.remove(os.path.join(OUT_DIR, name))
            except OSError:
                pass


def push_image_and_get_public_url(local_path: str) -> str:
    """Auto mode only: commits the card and returns its raw.githubusercontent URL."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    if not repo:
        raise RuntimeError("GITHUB_REPOSITORY not set - auto-posting only works inside GitHub Actions.")

    subprocess.run(["git", "config", "user.name", "southcinema-bot"], check=True)
    subprocess.run(["git", "config", "user.email", "bot@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", local_path], check=True)
    subprocess.run(["git", "commit", "-m", f"Add graphic: {os.path.basename(local_path)}"], check=True)
    subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", branch], check=True)
    subprocess.run(["git", "push"], check=True)
    time.sleep(10)  # give raw.githubusercontent.com a moment to serve the new file
    return f"https://raw.githubusercontent.com/{repo}/{branch}/{local_path.replace(os.sep, '/')}"


def queue_for_approval(store, item, item_id, caption, image_path) -> bool:
    footer = f"Trend score {item.score:.1f} · {item.coverage} outlet(s) · {item.source}"
    message_id = notify_telegram.send_draft(image_path, item_id, caption, footer, item.link)
    if not message_id:
        print("  Could not send the draft to Telegram; it will be retried next run.")
        return False

    store["items"][item_id] = {
        "title": item.title,
        "link": item.link,
        "source": item.source,
        "caption": caption,
        "image": image_path.replace(os.sep, "/"),
        "status": "pending",
        "message_id": message_id,
        "created_ts": time.time(),
        "posted": {},
    }
    pending.save(store)
    mark_posted(item)  # so the same story is never queued twice
    print("  Sent to Telegram for approval.")
    return True


def run(dry_run: bool = False):
    store = pending.load()
    prune_old_images(store)

    print("Fetching news...")
    items = fetch_all()
    print(f"  {len(items)} stories at or above the trending threshold")

    unposted = filter_unposted(items)
    print(f"  {len(unposted)} are new (not already queued/posted, not near-duplicates)")

    # Pick a few extra so a skipped story (no real news / Gemini down) can be replaced.
    candidates = pick_diverse(unposted, config.MAX_POSTS_PER_RUN + 8)
    if not candidates:
        print("Nothing new to post this run.")
        if not dry_run and notify_telegram.is_configured():
            notify_telegram.send_text(
                f"ℹ️ Cinema Woods run finished with no new drafts: {len(items)} trending stories were found, "
                "but none were new and different enough from what was already covered.")
        return

    done = 0
    stats = {"no_caption": 0, "no_news": 0}
    for item in candidates:
        if done >= config.MAX_POSTS_PER_RUN:
            break
        item_id = pending.make_id(item.link)
        print(f"\n--- Processing: {item.title} ({item.source}) ---")
        print(f"    {classify.detect_industry(item.title) or 'SOUTH'} / {classify.detect_category(item.title)}")

        if done or stats["no_caption"] or stats["no_news"]:
            time.sleep(config.GEMINI_PAUSE_SECONDS)
        caption = generate_caption(item)
        if caption == SKIP:
            stats["no_news"] += 1
            print("  Skipped: headline has no concrete news.")
            if not dry_run:
                mark_skipped(item)  # not asked again for a few hours
            continue
        if caption is None:
            stats["no_caption"] += 1
            print("  Skipped: no caption (will be retried next run).")
            if stats["no_caption"] >= 2 and done == 0:
                print("  Gemini keeps failing - stopping early so quota is not wasted.")
                break
            continue

        card_title = getattr(item, "card_title", "") or item.title
        print(f"  Picture headline: {card_title}")
        image_path = os.path.join(OUT_DIR, f"{item_id}.jpg")
        os.makedirs(OUT_DIR, exist_ok=True)
        lead_path = os.path.join(OUT_DIR, f"{item_id}-lead.tmp.jpg")
        if image_fetch.get_article_image(item.link, lead_path):
            make_poster_card(card_title, lead_path, image_path)
            print("  Card built around the article image.")
        else:
            make_headline_card(card_title, item.source, out_path=image_path)
        if os.path.exists(lead_path):
            os.remove(lead_path)
        done += 1

        if dry_run:
            print("[DRY RUN] Caption:\n", caption)
            print("[DRY RUN] Card saved at:", image_path)
            continue

        if config.TELEGRAM_REVIEW:
            queue_for_approval(store, item, item_id, caption, image_path)
            continue

        try:
            public_url = push_image_and_get_public_url(image_path)
            results = post_everywhere(public_url, caption)
            print("  Result:", results)
            mark_posted(item)
        except Exception as e:
            print(f"[ERROR] Failed to post '{item.title}': {e}")

    if done < config.MAX_POSTS_PER_RUN and not dry_run and notify_telegram.is_configured():
        reason = [f"Only {done} of {config.MAX_POSTS_PER_RUN} drafts this run.",
                  f"Trending stories found: {len(items)}; new and different enough after the "
                  f"duplicate/variety filters: {len(unposted)}."]
        if stats["no_caption"]:
            reason.append(f"{stats['no_caption']} stories could not get a description from Gemini.")
            if caption_gen.ERRORS:
                reason.append("Gemini said:\n" + "\n".join(f"• {e}" for e in caption_gen.ERRORS[:4]))
        if stats["no_news"]:
            reason.append(f"{stats['no_news']} stories were skipped by Gemini as having no real news:")
            reason.extend(f"• {t} — {r or 'no reason given'}" for t, r in caption_gen.SKIP_REASONS[:6])
        if len(candidates) < config.MAX_POSTS_PER_RUN:
            reason.append("Too few fresh stories: most of today's headlines repeat films already covered "
                          "(see TOPIC_COOLDOWN_HOURS in config.py).")
        notify_telegram.send_text("ℹ️ Cinema Woods run summary\n\n" + "\n".join(reason))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Build captions and cards but send/post nothing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
