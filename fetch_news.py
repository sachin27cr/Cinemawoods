"""
Fetches news from the configured RSS feeds, keeps only South Indian film
stories, and ranks them by how likely they are to be trending.
"""

import calendar
import html
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List

import feedparser

import config


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source: str
    published_ts: float = 0.0
    score: float = 0.0
    coverage: int = 1  # number of different outlets covering the same story


def _compile(terms):
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")s?\b"
    return re.compile(pattern, re.IGNORECASE)


INDUSTRY_RE = _compile(config.INDUSTRY_TERMS)
STAR_RE = _compile(config.STAR_NAMES)
FILM_RE = _compile(config.FILM_WORDS)
BLOCK_RE = _compile(config.BLOCK_TERMS)
HOT_RE = _compile(config.HOT_TERMS)
LOW_RE = _compile(config.LOW_VALUE_TERMS)

TAG_RE = re.compile(r"<[^>]+>")


def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", s or ""))).strip()


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _is_relevant(title: str, summary: str) -> bool:
    text = f"{title} {summary}"
    if BLOCK_RE.search(title):
        return False
    has_south = bool(INDUSTRY_RE.search(text) or STAR_RE.search(text))
    has_film = bool(FILM_RE.search(text))
    return has_south and has_film


def _score(item: NewsItem, now: float) -> float:
    t = item.title
    s = 0.0
    s += min(len(HOT_RE.findall(t)), 3) * 2.0
    s += min(len(STAR_RE.findall(t)), 2) * 1.5
    s += min(item.coverage - 1, 6) * 2.0
    age_h = max(0.0, (now - item.published_ts) / 3600.0)
    if age_h < 6:
        s += 3
    elif age_h < 12:
        s += 2
    elif age_h < 24:
        s += 1
    if LOW_RE.search(t):
        s -= 4
    return s


def _add_coverage(items: List[NewsItem]) -> None:
    """For each item, count the distinct outlets carrying a similar headline.
    The same story showing up at many outlets is our trending signal."""
    norms = [_norm(i.title) for i in items]
    for idx, item in enumerate(items):
        outlets = {item.source}
        for jdx, other in enumerate(items):
            if idx == jdx or other.source in outlets:
                continue
            sm = SequenceMatcher(None, norms[idx], norms[jdx])
            if sm.real_quick_ratio() < 0.55 or sm.quick_ratio() < 0.55:
                continue
            if sm.ratio() >= 0.55:
                outlets.add(other.source)
        item.coverage = len(outlets)


def fetch_all() -> List[NewsItem]:
    """Fetch every feed, filter for relevance, rank by trending score."""
    raw: List[NewsItem] = []

    for feed_name, url in config.RSS_FEEDS.items():
        parsed = feedparser.parse(url)

        if parsed.bozo and not parsed.entries:
            print(f"[WARN] Feed failed or empty: {feed_name} — {parsed.get('bozo_exception')}")
            continue

        is_google = feed_name.startswith("Google News -")

        for entry in parsed.entries:
            title = _clean_text(entry.get("title", ""))
            link = entry.get("link", "")
            if not title or not link:
                continue

            source = feed_name
            if is_google:
                # Google titles end with " - Publisher"; Google's summary is
                # just a list of related headlines, so it is not used.
                if " - " in title:
                    title, publisher = title.rsplit(" - ", 1)
                    source = publisher.strip() or feed_name
                summary = ""
            else:
                summary = _clean_text(entry.get("summary", "") or entry.get("description", ""))[:500]

            if not _is_relevant(title, summary):
                continue

            published_ts = time.time()
            if entry.get("published_parsed"):
                published_ts = calendar.timegm(entry["published_parsed"])

            raw.append(NewsItem(
                title=title, link=link, summary=summary,
                source=source, published_ts=published_ts,
            ))

    # Same article appearing in several topic feeds counts once.
    unique: List[NewsItem] = []
    seen = set()
    for item in raw:
        key = _norm(item.title)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    _add_coverage(unique)

    now = time.time()
    for item in unique:
        item.score = _score(item, now)

    ranked = sorted(unique, key=lambda i: (i.score, i.published_ts), reverse=True)

    print(f"  {len(unique)} relevant stories; top candidates by trending score:")
    for item in ranked[:10]:
        print(f"    [{item.score:.1f}] {item.title} ({item.source}, outlets: {item.coverage})")

    return [i for i in ranked if i.score >= config.MIN_SCORE]


def self_test():
    """Prints feed health — run this first after setup to confirm sources work."""
    print("Testing feed connectivity...\n")
    for feed_name, url in config.RSS_FEEDS.items():
        parsed = feedparser.parse(url)
        status = "OK" if parsed.entries else "EMPTY/FAILED"
        print(f"[{status}] {feed_name}: {len(parsed.entries)} entries")
    print("\nIf a feed shows EMPTY/FAILED repeatedly, remove or replace it in config.py")


if __name__ == "__main__":
    self_test()
