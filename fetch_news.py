"""
Fetches and filters news items from configured RSS feeds.
"""

import time
from dataclasses import dataclass, field
from typing import List

import feedparser

import config


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source: str
    published_ts: float = field(default=0.0)


def _is_relevant(source_name: str, title: str, summary: str) -> bool:
    if any(source_name.startswith(p) for p in config.ALWAYS_PASS_PREFIXES):
        return True
    text = f"{title} {summary}".lower()
    return any(kw in text for kw in config.KEYWORD_FILTER)


def fetch_all() -> List[NewsItem]:
    """Fetch every configured feed, apply relevance filter, return flat list."""
    items: List[NewsItem] = []

    for source_name, url in config.RSS_FEEDS.items():
        parsed = feedparser.parse(url)

        if parsed.bozo and not parsed.entries:
            print(f"[WARN] Feed failed or empty: {source_name} ({url}) — {parsed.get('bozo_exception')}")
            continue

        for entry in parsed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "") or entry.get("description", "")
            link = entry.get("link", "")

            if not title or not link:
                continue

            if not _is_relevant(source_name, title, summary):
                continue

            published_ts = time.time()
            if entry.get("published_parsed"):
                published_ts = time.mktime(entry["published_parsed"])

            items.append(NewsItem(
                title=title,
                link=link,
                summary=summary[:500],
                source=source_name,
                published_ts=published_ts,
            ))

    # newest first
    items.sort(key=lambda i: i.published_ts, reverse=True)
    return items


def self_test():
    """Prints feed health — run this first after setup to confirm sources work."""
    print("Testing feed connectivity...\n")
    for source_name, url in config.RSS_FEEDS.items():
        parsed = feedparser.parse(url)
        status = "OK" if parsed.entries else "EMPTY/FAILED"
        print(f"[{status}] {source_name}: {len(parsed.entries)} entries")
    print("\nIf a feed shows EMPTY/FAILED repeatedly, remove or replace it in config.py")


if __name__ == "__main__":
    self_test()
