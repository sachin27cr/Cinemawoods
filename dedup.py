"""
Tracks already-posted stories in SQLite so the same news isn't posted twice,
even when multiple sources cover the same story with slightly different
headlines (fuzzy title match via difflib).
"""

import sqlite3
import time
from difflib import SequenceMatcher
from typing import List

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


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute(SCHEMA)
    return conn


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def filter_unposted(items: List[NewsItem]) -> List[NewsItem]:
    """Return items whose link is new AND whose title isn't a near-duplicate
    of something already posted in the last 14 days."""
    conn = _connect()
    cutoff = time.time() - (14 * 86400)
    recent_titles = [
        row[0] for row in
        conn.execute("SELECT title FROM posted WHERE posted_ts > ?", (cutoff,)).fetchall()
    ]
    existing_links = {
        row[0] for row in conn.execute("SELECT link FROM posted").fetchall()
    }
    conn.close()

    unposted = []
    seen_in_this_batch = []  # also dedup within the same run across sources
    for item in items:
        if item.link in existing_links:
            continue
        if any(_similar(item.title, t) >= config.DEDUP_TITLE_SIMILARITY_THRESHOLD
               for t in recent_titles + seen_in_this_batch):
            continue
        unposted.append(item)
        seen_in_this_batch.append(item.title)

    return unposted


def mark_posted(item: NewsItem):
    conn = _connect()
    conn.execute(
        "INSERT OR IGNORE INTO posted (title, link, source, posted_ts) VALUES (?, ?, ?, ?)",
        (item.title, item.link, item.source, time.time()),
    )
    conn.commit()
    conn.close()
