"""
Orchestrates the full pipeline:
RSS fetch -> relevance filter -> dedup -> caption gen -> graphic gen ->
(review gate OR direct post) -> Meta posting -> mark as posted.

Run modes:
  python main.py            -> normal run (respects TELEGRAM_REVIEW)
  python main.py --dry-run  -> does everything except posting/reviewing;
                                just prints what WOULD happen
"""

import argparse
import os
import subprocess
import sys

import config
from fetch_news import fetch_all
from dedup import filter_unposted, mark_posted
from caption_gen import generate_caption
from graphic_gen import make_headline_card
from notify_telegram import send_draft_for_review
from post_meta import post_everywhere


def push_image_and_get_public_url(local_path: str) -> str:
    """
    Commits the generated graphic into the repo (under graphics/) and pushes,
    then returns its raw.githubusercontent.com URL — a zero-cost way to give
    Meta's Graph API a public image URL without standing up separate hosting.
    Requires the workflow to run with a checkout that has push permission
    (see .github/workflows/post.yml — uses GITHUB_TOKEN).
    """
    repo = os.environ.get("GITHUB_REPOSITORY")  # e.g. "yourname/southcinema-bot"
    branch = os.environ.get("GITHUB_REF_NAME", "main")

    if not repo:
        raise RuntimeError(
            "GITHUB_REPOSITORY env var not set — push_image_and_get_public_url "
            "only works inside GitHub Actions. For local testing, set "
            "PUBLIC_IMAGE_BASE_URL and host the file yourself, or use --dry-run."
        )

    dest_rel_path = f"graphics/{os.path.basename(local_path)}"
    os.makedirs("graphics", exist_ok=True)
    subprocess.run(["cp", local_path, dest_rel_path], check=True)

    subprocess.run(["git", "config", "user.name", "southcinema-bot"], check=True)
    subprocess.run(["git", "config", "user.email", "bot@users.noreply.github.com"], check=True)
    subprocess.run(["git", "add", dest_rel_path], check=True)
    subprocess.run(["git", "commit", "-m", f"Add graphic: {os.path.basename(local_path)}"], check=True)
    subprocess.run(["git", "push"], check=True)

    return f"https://raw.githubusercontent.com/{repo}/{branch}/{dest_rel_path}"


def run(dry_run: bool = False):
    print("Fetching news...")
    items = fetch_all()
    print(f"  {len(items)} relevant items found across all feeds")

    unposted = filter_unposted(items)
    print(f"  {len(unposted)} are new (not already posted, not near-duplicates)")

    to_process = unposted[:config.MAX_POSTS_PER_RUN]
    if not to_process:
        print("Nothing new to post this run.")
        return

    for item in to_process:
        print(f"\n--- Processing: {item.title} ({item.source}) ---")

        caption = generate_caption(item)
        image_path = make_headline_card(item.title, item.source)

        if dry_run:
            print("[DRY RUN] Caption:\n", caption)
            print("[DRY RUN] Graphic saved at:", image_path)
            continue

        if config.TELEGRAM_REVIEW:
            send_draft_for_review(image_path, caption, item.link)
            # Review-gate mode: draft is sent for a human thumbs-up.
            # This run does NOT auto-post or mark as posted, so the
            # story remains eligible next run until you flip
            # TELEGRAM_REVIEW off or add an approval-triggered post step.
            continue

        try:
            public_url = push_image_and_get_public_url(image_path)
            results = post_everywhere(public_url, caption)
            print("  Result:", results)
            mark_posted(item)
        except Exception as e:
            print(f"[ERROR] Failed to post '{item.title}': {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Generate everything but don't post or send for review")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
