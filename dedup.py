"""
Tracks already-posted stories in SQLite so the same news isn't posted twice,
even when multiple sources cover the same story with slightly different
headlines (fuzzy title match via difflib).
"""

import sqlite3
import time
from difflib import SequenceMatcher
from typing import List

import classify
import config
from fetch_news import NewsItem

SCHEMA = """
CREATE TABLE IF NOT EXISTS posted (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    link TEXT NOT NULL UNIQUE,
    source TEXT,
    posted_ts REAL
);
"""


SKIPPED_SCHEMA = "CREATE TABLE IF NOT EXISTS skipped (link TEXT PRIMARY KEY, ts REAL)"
SKIP_RECHECK_HOURS = 12  # a headline judged "no real news" is not re-asked for this long


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(SCHEMA)
    conn.execute(SKIPPED_SCHEMA)
    return conn


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def filter_unposted(items: List[NewsItem]) -> List[NewsItem]:
    """Return items whose link is new AND whose title isn't a near-duplicate
    of something already posted in the last 14 days."""
    conn = _connect()
    now = time.time()
    cutoff = now - (14 * 86400)
    recent_rows = conn.execute(
        "SELECT title, posted_ts FROM posted WHERE posted_ts > ?", (cutoff,)
    ).fetchall()
    recent_titles = [r[0] for r in recent_rows]
    existing_links = {
        row[0] for row in conn.execute("SELECT link FROM posted").fetchall()
    }
    recently_skipped = {
        row[0] for row in conn.execute(
            "SELECT link FROM skipped WHERE ts > ?", (now - SKIP_RECHECK_HOURS * 3600,)
        ).fetchall()
    }
    conn.close()

    unposted = []
    seen_in_this_batch = []  # also dedup within the same run across sources
    for item in items:
        if item.link in existing_links or item.link in recently_skipped:
            continue
        if any(_similar(item.title, t) >= config.DEDUP_TITLE_SIMILARITY_THRESHOLD
               for t in recent_titles + seen_in_this_batch):
            continue
        if _in_topic_cooldown(item, recent_rows, now):
            continue
        unposted.append(item)
        seen_in_this_batch.append(item.title)

    return unposted


def _in_topic_cooldown(item: NewsItem, recent_rows, now: float) -> bool:
    """True if we recently covered the same film/star (see config cooldowns)."""
    category = classify.detect_category(item.title)
    for title, ts in recent_rows:
        age_h = (now - ts) / 3600.0
        if age_h > config.TOPIC_COOLDOWN_HOURS:
            continue
        if not classify.same_topic(item.title, title):
            continue
        if classify.detect_category(title) == category:
            return True
        if age_h <= config.TOPIC_ANY_TYPE_COOLDOWN_HOURS:
            return True
    return False


def mark_posted(item: NewsItem):
    conn = _connect()
    conn.execute(
        "INSERT OR IGNORE INTO posted (title, link, source, posted_ts) VALUES (?, ?, ?, ?)",
        (item.title, item.link, item.source, time.time()),
    )
    conn.commit()
    conn.close()


def mark_skipped(item: NewsItem):
    """Remembers a headline that was judged to hold no real news (re-checked later)."""
    conn = _connect()
    conn.execute("INSERT OR REPLACE INTO skipped (link, ts) VALUES (?, ?)", (item.link, time.time()))
    conn.commit()
    conn.close()
