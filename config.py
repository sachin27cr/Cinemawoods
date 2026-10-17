"""
Central configuration for the South Indian Cinema News Bot.
Edit RSS_FEEDS and KEYWORD_FILTER to tune coverage.
"""

import os

# ---------------------------------------------------------------------------
# RSS SOURCES
# Mix of (a) broad national outlets with entertainment sections and
# (b) Google News topic-search feeds, which are the most reliable way to
# cover fragmented regional trade press (most single-site regional trade
# blogs do not maintain stable RSS feeds).
# ---------------------------------------------------------------------------

GOOGLE_NEWS_TOPICS = [
    "Telugu cinema",
    "Tollywood movie",
    "Tamil cinema",
    "Kollywood movie",
    "Kannada cinema",
    "Sandalwood movie",
    "Malayalam cinema",
    "Mollywood movie",
]

def _google_news_url(topic: str) -> str:
    q = topic.replace(" ", "+")
    return f"https://news.google.com/rss/search?q={q}+when:1d&hl=en-IN&gl=IN&ceid=IN:en"

RSS_FEEDS = {
    "TOI Entertainment": "https://timesofindia.indiatimes.com/rss_entertainment.cms",
    "The Hindu Entertainment": "https://www.thehindu.com/entertainment/movies/feeder/default.rss",
}

# Auto-add all Google News topic feeds
for _topic in GOOGLE_NEWS_TOPICS:
    RSS_FEEDS[f"Google News - {_topic}"] = _google_news_url(_topic)

# ---------------------------------------------------------------------------
# RELEVANCE FILTER
# Google News topic feeds are already scoped by query, but TOI/Hindu are
# generic entertainment feeds, so we filter those by keyword match on the
# title/summary before they enter the pipeline.
# ---------------------------------------------------------------------------

KEYWORD_FILTER = [
    "telugu", "tollywood", "tamil", "kollywood", "kannada", "sandalwood",
    "malayalam", "mollywood", "south indian film", "south indian cinema",
    "andhra", "telangana", "hyderabad film", "chennai film", "kochi film",
    "bengaluru film",
]

# Feeds that should always pass through regardless of keyword match
# (topic-scoped Google News feeds are already relevant by construction)
ALWAYS_PASS_PREFIXES = ["Google News -"]

# ---------------------------------------------------------------------------
# DEDUP
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "posted_log.db")
DEDUP_TITLE_SIMILARITY_THRESHOLD = 0.80  # 0-1, higher = stricter match required to count as duplicate

# ---------------------------------------------------------------------------
# POSTING LIMITS
# ---------------------------------------------------------------------------
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "3"))

# ---------------------------------------------------------------------------
# REVIEW GATE
# If TELEGRAM_REVIEW is "1", drafts are sent to a private Telegram chat for
# a manual thumbs-up before posting live, instead of posting automatically.
# ---------------------------------------------------------------------------
TELEGRAM_REVIEW = os.environ.get("TELEGRAM_REVIEW", "1") == "1"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# LLM (Gemini free tier, matching your existing analysis bot)
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# ---------------------------------------------------------------------------
# META GRAPH API
# ---------------------------------------------------------------------------
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")
IG_BUSINESS_ACCOUNT_ID = os.environ.get("IG_BUSINESS_ACCOUNT_ID", "")
GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v21.0")

# Public base URL where generated graphics are hosted so Meta's API can
# fetch them (IG/FB require a public image URL, not a raw file upload from
# a GitHub Actions runner). See README for the two supported options.
PUBLIC_IMAGE_BASE_URL = os.environ.get("PUBLIC_IMAGE_BASE_URL", "")

# ---------------------------------------------------------------------------
# BRANDING
# ---------------------------------------------------------------------------
PAGE_NAME = os.environ.get("PAGE_NAME", "South Cinema Buzz")
ACCENT_COLOR = os.environ.get("ACCENT_COLOR", "#E63946")
