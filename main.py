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

import claude_writer
import classify
import config
import factcheck
import image_fetch
import notify_telegram
import pending
import caption_gen
from caption_gen import SKIP, generate_caption
from classify import pick_diverse
from dedup import filter_unposted, mark_posted, mark_skipped
from fetch_news import fetch_all
from graphic_gen import OUT_DIR, make_headline_card, make_poster_card, save_source_copy
from post_meta import post_everywhere


def prune_reels(store: dict) -> None:
    """Deletes Reel videos that are posted, discarded or no longer tied to a draft."""
    if not os.path.isdir("reels"):
        return
    live = {os.path.basename(v.get("reel", {}).get("path", "")) for v in store["items"].values()
            if v.get("reel", {}).get("status") in ("rendered", "failed")}
    for name in os.listdir("reels"):
        if name.endswith(".mp4") and name not in live:
            try:
                os.remove(os.path.join("reels", name))
            except OSError:
                pass


def prune_old_images(store: dict) -> None:
    """Deletes cards that are no longer waiting for approval."""
    prune_reels(store)
    if not os.path.isdir(OUT_DIR):
        return
    keep = set(store["items"].keys())
    keep |= {os.path.splitext(os.path.basename(v.get("image", "")))[0] for v in store["items"].values()}
    keep |= {os.path.splitext(os.path.basename(v.get("src_image", "")))[0] for v in store["items"].values() if v.get("src_image")}
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


def queue_for_approval(store, item, item_id, caption, image_path, src_image: str = "") -> bool:
    note = getattr(item, "check_note", "")
    footer = f"{note + chr(10) if note else ''}Trend score {item.score:.1f} · {item.coverage} outlet(s) · {item.source}"
    message_id = notify_telegram.send_draft(image_path, item_id, caption, footer, item.link)
    if not message_id:
        print("  Could not send the draft to Telegram; it will be retried next run.")
        return False

    store["items"][item_id] = {
        "title": item.title,
        "headline": getattr(item, "card_title", ""),
        "link": item.link,
        "source": item.source,
        "caption": caption,
        "image": image_path.replace(os.sep, "/"),
        "src_image": src_image.replace(os.sep, "/"),
        "status": "pending",
        "message_id": message_id,
        "created_ts": time.time(),
        "posted": {},
    }
    store["last_batch_ts"] = time.time()
    pending.save(store)
    mark_posted(item)  # so the same story is never queued twice
    print("  Sent to Telegram for approval.")
    return True


def _choose_image(item, page, article_text):
    """(image url or '', note for the draft). Claude looks at the candidate pictures and picks the real
    poster/still; without Claude (or if it fails) the article's lead image is used as before."""
    if not config.USE_ARTICLE_IMAGES:
        return "", ""
    if claude_writer.enabled():
        try:
            cands = image_fetch.get_image_candidates(item.link)
            lead = page.get("image_url")
            if lead and lead not in cands:
                cands.insert(0, lead)
            res = claude_writer.choose_poster(item.title, article_text, cands)
        except Exception as e:
            print(f"  [image] Claude picture check failed ({type(e).__name__})")
            res = None
        if res is not None:
            url, why = res
            print(f"  [image] Claude: {'picked a picture' if url else 'no suitable picture'} ({why})")
            return (url, "🖼 picture checked") if url else ("", "🖼 no suitable poster found - text card used")
    return page.get("image_url") or "", ""


def queue_news(store, item, item_id, caption, headline, article_image: str = "") -> bool:
    """Sends the story as text only and waits for your picture (reply) or a quick-pick button."""
    note = getattr(item, "check_note", "")
    footer = f"{note + chr(10) if note else ''}Trend score {item.score:.1f} · {item.coverage} outlet(s) · {item.source}"
    industry = classify.detect_industry(item.title) or "SOUTH"
    label = f"{industry} · {classify.detect_category(item.title)}".upper()
    message_id = notify_telegram.send_news(item_id, label, headline, caption, footer, item.link, bool(article_image))
    if not message_id:
        print("  Could not send the story to Telegram; it will be retried next run.")
        return False
    store["items"][item_id] = {
        "title": item.title,
        "headline": headline,
        "link": item.link,
        "source": item.source,
        "caption": caption,
        "image": "",
        "src_image": "",
        "article_image": article_image,
        "status": "awaiting_image",
        "message_id": message_id,
        "created_ts": time.time(),
        "posted": {},
    }
    store["last_batch_ts"] = time.time()
    pending.save(store)
    mark_posted(item)
    print("  Sent to Telegram (waiting for your picture).")
    return True


def run(dry_run: bool = False):
    store = pending.load()
    scheduled = os.environ.get("SCHEDULED_RUN") == "1" or os.environ.get("RUN_EVENT") == "schedule"
    if scheduled and not dry_run and time.time() - store.get("last_batch_ts", 0) < 50 * 60:
        print("Drafts were already made for this time slot (within the last 50 minutes); nothing to do.")
        return
    prune_old_images(store)

    print("Fetching news...")
    items = fetch_all()
    print(f"  {len(items)} stories at or above the trending threshold")

    unposted = filter_unposted(items)
    print(f"  {len(unposted)} are new (not already queued/posted, not near-duplicates)")

    # Pick a few extra so a skipped story (no real news / Gemini down) can be replaced.
    candidates = pick_diverse(unposted, config.MAX_POSTS_PER_RUN + 8)
    if candidates and claude_writer.enabled():
        cutoff = time.time() - 48 * 3600
        recent = [v.get("title", "") for v in store["items"].values() if v.get("created_ts", 0) >= cutoff]
        ranked = claude_writer.rank(candidates, recent, config.MAX_POSTS_PER_RUN + 6)
        if ranked:
            print(f"  Claude picked {len(ranked)} of {len(candidates)} candidates, in this order:")
            for r in ranked:
                print(f"    - {r.title[:90]}")
            candidates = ranked
    if not candidates:
        print("Nothing new to post this run.")
        if not dry_run and notify_telegram.is_configured():
            notify_telegram.send_text(
                f"ℹ️ Cinema Woods run finished with no new drafts: {len(items)} trending stories were found, "
                "but none were new and different enough from what was already covered.")
        return

    done = 0
    stats = {"no_caption": 0, "no_news": 0, "stale": 0}
    held = []  # (title, problems) drafts stopped by the fact-check
    for item in candidates:
        if done >= config.MAX_POSTS_PER_RUN:
            break
        item_id = pending.make_id(item.link)
        print(f"\n--- Processing: {item.title} ({item.source}) ---")
        print(f"    {classify.detect_industry(item.title) or 'SOUTH'} / {classify.detect_category(item.title)}")

        # read the real article first: its text, its own publish date and its picture
        page = image_fetch.get_page_info(item.link)
        pub = page.get("published_ts")
        if pub and time.time() - pub > config.ARTICLE_MAX_AGE_HOURS * 3600:
            age_days = (time.time() - pub) / 86400
            print(f"  Skipped: the article itself is {age_days:.0f} days old (feed re-dated it).")
            stats["stale"] += 1
            if not dry_run:
                mark_skipped(item)
            continue
        article_text = " ".join(x for x in (page.get("description", ""), page.get("text", "")) if x)
        print(f"  Article text: {len(article_text)} characters" if article_text else "  Article text: unavailable")

        if (done or stats["no_caption"] or stats["no_news"]) and not claude_writer.enabled():
            time.sleep(config.GEMINI_PAUSE_SECONDS)
        caption = generate_caption(item, article_text)
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

        # fact-check: every name, number and year must be in the headline/article; one rewrite, else hold
        ok, problems, checked = factcheck.check(caption, item.title, article_text, item.summary)
        if not ok:
            print(f"  Fact-check failed ({', '.join(problems)}); asking for a rewrite.")
            if not claude_writer.enabled():
                time.sleep(config.GEMINI_PAUSE_SECONDS)
            retry = generate_caption(item, article_text, fix_hint=problems)
            if retry and retry != SKIP:
                ok, problems2, checked = factcheck.check(retry, item.title, article_text, item.summary)
                if ok:
                    caption, problems = retry, []
                else:
                    problems = problems2
        if not ok:
            print(f"  Held: could not verify ({', '.join(problems)}).")
            held.append((item.title[:70], problems))
            if not dry_run:
                mark_skipped(item)
            continue
        item.check_note = ("✅ Fact-checked against the article" if checked
                           else "⚠️ Article could not be opened - check names and dates yourself")

        card_title = getattr(item, "card_title", "") or item.title
        print(f"  Picture headline: {card_title}")
        if config.NEWS_FIRST:
            # text first: you reply with the picture you want (optional buttons offer the article picture or a text card)
            article_image, _note = _choose_image(item, page, article_text)
            done += 1
            if dry_run:
                print("[DRY RUN] News-first draft:\n", card_title, "\n", caption)
                continue
            queue_news(store, item, item_id, caption, card_title, article_image)
            continue
        image_path = os.path.join(OUT_DIR, f"{item_id}.jpg")
        os.makedirs(OUT_DIR, exist_ok=True)
        lead_path = os.path.join(OUT_DIR, f"{item_id}-lead.tmp.jpg")
        src_image = ""
        image_url, image_note = _choose_image(item, page, article_text)
        if image_url and image_fetch.save_image_url(image_url, lead_path):
            make_poster_card(card_title, lead_path, image_path)
            src_image = save_source_copy(lead_path, os.path.join(OUT_DIR, f"{item_id}-src.jpg"))
            print("  Card built around the article image.")
        else:
            make_headline_card(card_title, item.source, out_path=image_path)
        if image_note:
            item.check_note = f"{item.check_note} · {image_note}"
        if os.path.exists(lead_path):
            os.remove(lead_path)
        done += 1

        if dry_run:
            print("[DRY RUN] Caption:\n", caption)
            print("[DRY RUN] Card saved at:", image_path)
            continue

        if config.TELEGRAM_REVIEW:
            queue_for_approval(store, item, item_id, caption, image_path, src_image)
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
        if stats["stale"]:
            reason.append(f"{stats['stale']} stories were skipped because the article itself is old.")
        if held:
            reason.append(f"{len(held)} drafts were HELD by the fact-check (details not found in the article):")
            reason.extend(f"• {t} — {', '.join(p)}" for t, p in held[:5])
        if stats["no_news"]:
            reason.append(f"{stats['no_news']} stories were skipped by Gemini as having no real news:")
            reason.extend(f"• {t} — {r or 'no reason given'}" for t, r in caption_gen.SKIP_REASONS[:6])
        if len(candidates) < config.MAX_POSTS_PER_RUN:
            reason.append("Too few fresh stories: most of today's headlines repeat films already covered "
                          "(see TOPIC_COOLDOWN_HOURS in config.py).")
        if claude_writer.ERRORS:
            reason.append("Claude said:\n" + "\n".join(f"• {e}" for e in claude_writer.ERRORS[:3]))
        if config.USE_CLAUDE and config.ANTHROPIC_API_KEY:
            reason.append(claude_writer.usage_line())
        notify_telegram.send_text("ℹ️ Cinema Woods run summary\n\n" + "\n".join(reason))


    if config.USE_CLAUDE and config.ANTHROPIC_API_KEY:
        print(claude_writer.usage_line())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Build captions and cards but send/post nothing")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
