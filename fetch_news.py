"""
Fetches news from the configured RSS feeds, keeps only South Indian film
stories, and ranks them by how likely they are to be trending.
"""

import calendar
import html
import re
import time
from difflib import SequenceMatcher
from typing import List

import feedparser

import config
import ig_watch
from models import NewsItem  # noqa: F401  (re-exported)


def _compile(terms):
    pattern = r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")s?\b"
    return re.compile(pattern, re.IGNORECASE)


INDUSTRY_RE = _compile(config.INDUSTRY_TERMS)
STAR_RE = _compile(config.STAR_NAMES)
FILM_RE = _compile(config.FILM_WORDS)
BLOCK_RE = _compile(config.BLOCK_TERMS)
HOT_RE = _compile(config.HOT_TERMS)
BOLLY_RE = _compile(config.BOLLYWOOD_TERMS)
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
    if BOLLY_RE.search(title) and not INDUSTRY_RE.search(title):
        return False  # Hindi-film news that merely features a South star
    has_south = bool(INDUSTRY_RE.search(text) or STAR_RE.search(text))
    has_film = bool(FILM_RE.search(text))
    return has_south and has_film


def _score(item: NewsItem, now: float) -> float:
    t = item.title
    s = 0.0
    s += min(len(HOT_RE.findall(t)), 3) * 2.0
    s += min(len(STAR_RE.findall(t)), 2) * 1.5
    if item.official:
        s += config.IG_OFFICIAL_BONUS if item.official_kind == "official" else config.IG_MEDIA_BONUS
    s += min(item.coverage - 1, config.COVERAGE_BONUS_MAX_OUTLETS) * config.COVERAGE_BONUS_PER_OUTLET
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

    # Instagram pages you follow: the preferred source (official announcements, posters, release dates)
    for post in ig_watch.fetch_posts():
        if BLOCK_RE.search(post.title) or BLOCK_RE.search(post.summary[:300]):
            continue
        if not FILM_RE.search(f"{post.title} {post.summary}"):
            continue  # not film news (birthday wishes without a film, ads, etc.)
        raw.append(post)

    feeds = {} if (config.IG_WATCH_ONLY and raw) else config.RSS_FEEDS
    for feed_name, url in feeds.items():
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

            if not entry.get("published_parsed"):
                continue  # no date = cannot tell if it is old, so it is not used
            published_ts = calendar.timegm(entry["published_parsed"])

            raw.append(NewsItem(
                title=title, link=link, summary=summary,
                source=source, published_ts=published_ts,
            ))

    # Same article appearing in several topic feeds counts once; stale news is dropped.
    max_age = config.MAX_AGE_HOURS * 3600
    unique: List[NewsItem] = []
    seen = set()
    for item in raw:
        key = _norm(item.title)
        if key in seen:
            continue
        if time.time() - item.published_ts > max_age:
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
