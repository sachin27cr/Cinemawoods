"""
Central configuration for the Cinema Woods South Indian cinema news bot.
Tune the lists below to change what gets picked and how it is ranked.
"""

import os

# ---------------------------------------------------------------------------
# RSS SOURCES
# Google News topic-search feeds are the main source. The queries lean toward
# trending-type stories (box office, trailers, teasers) in each industry.
# ---------------------------------------------------------------------------

GOOGLE_NEWS_TOPICS = [
    "Telugu cinema",
    "Tollywood box office",
    "Telugu movie trailer teaser",
    "Tamil cinema",
    "Kollywood box office",
    "Tamil movie trailer teaser",
    "Kannada cinema",
    "Kannada movie box office",
    "Malayalam cinema",
    "Mollywood box office",
    "Malayalam movie trailer teaser",
    "South Indian cinema",
    "pan-India South film box office",
]


def _google_news_url(topic: str) -> str:
    q = topic.replace(" ", "+")
    return f"https://news.google.com/rss/search?q={q}+when:1d&hl=en-IN&gl=IN&ceid=IN:en"


RSS_FEEDS = {
    "TOI Entertainment": "https://timesofindia.indiatimes.com/rss_entertainment.cms",
    "The Hindu Entertainment": "https://www.thehindu.com/entertainment/movies/feeder/default.rss",
}
for _topic in GOOGLE_NEWS_TOPICS:
    RSS_FEEDS[f"Google News - {_topic}"] = _google_news_url(_topic)

# ---------------------------------------------------------------------------
# RELEVANCE RULES (checked against the headline)
# A story must mention a South industry term OR a South star/film, AND must
# look like film news (FILM_WORDS). This blocks Hindi-film stories and things
# like Tamil Nadu politics.
# ---------------------------------------------------------------------------

INDUSTRY_TERMS = [
    "telugu", "tollywood", "tamil", "kollywood", "kannada", "sandalwood",
    "malayalam", "mollywood", "south indian", "south cinema", "south film",
    "south movie", "pan-india", "pan india",
]

STAR_NAMES = [
    "prabhas", "allu arjun", "mahesh babu", "jr ntr", "ntr", "ram charan",
    "pawan kalyan", "chiranjeevi", "nagarjuna", "venkatesh", "balakrishna",
    "nani", "vijay deverakonda", "naga chaitanya", "rajamouli", "sukumar",
    "prashanth neel", "trivikram", "rajinikanth", "kamal haasan", "vijay",
    "ajith", "suriya", "dhanush", "karthi", "sivakarthikeyan", "vikram",
    "lokesh kanagaraj", "atlee", "shankar", "mani ratnam", "nayanthara",
    "trisha", "samantha", "rashmika", "sai pallavi", "keerthy suresh",
    "yash", "darshan", "sudeep", "rishab shetty", "shiva rajkumar",
    "puneeth rajkumar", "mohanlal", "mammootty", "dulquer salmaan",
    "fahadh faasil", "prithviraj", "tovino thomas", "nivin pauly",
    "pushpa", "kantara", "kgf", "baahubali", "salaar", "jailer", "devara",
    "game changer", "coolie", "thug life",
]

FILM_WORDS = [
    "film", "movie", "cinema", "trailer", "teaser", "box office", "collection",
    "actor", "actress", "director", "starrer", "release", "ott", "song",
    "shoot", "shooting", "first look", "poster", "glimpse", "cast", "role",
    "review", "biopic", "sequel", "prequel", "screening", "theatre", "theater",
    "bigg boss", "audio launch", "pre-release", "premiere", "awards",
]

# Headlines containing any of these are dropped outright.
BLOCK_TERMS = [
    "election", "chief minister", "assembly", "bypoll", "lok sabha", "sensex",
    "stock market", "weather", "rain alert", "horoscope", "recipe",
]

# ---------------------------------------------------------------------------
# VIRALITY SCORING
# score = hot words + star power + how many different outlets cover the same
# story + freshness - low-value penalty. Only stories at or above MIN_SCORE
# are posted, best first. Lower MIN_SCORE if too few stories pass.
# ---------------------------------------------------------------------------

HOT_TERMS = [
    "box office", "collection", "crore", "record", "blockbuster", "trailer",
    "teaser", "first look", "glimpse", "release date", "ott release",
    "viral", "announced", "announces", "update", "breaks", "opening",
    "day 1", "first day", "pan-india", "pan india", "bigg boss", "reunite",
    "first single", "lyrical", "motion poster",
]

LOW_VALUE_TERMS = [
    "net worth", "age", "biography", "wiki", "boyfriend", "girlfriend",
    "husband", "wife", "salary", "how to watch",
]

MIN_SCORE = float(os.environ.get("MIN_SCORE", "5"))

# ---------------------------------------------------------------------------
# DEDUP
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "posted_log.db")
DEDUP_TITLE_SIMILARITY_THRESHOLD = 0.80

# ---------------------------------------------------------------------------
# POSTING LIMITS
# ---------------------------------------------------------------------------
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "3"))

# ---------------------------------------------------------------------------
# REVIEW GATE
# ---------------------------------------------------------------------------
TELEGRAM_REVIEW = os.environ.get("TELEGRAM_REVIEW", "1") == "1"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# LLM (Gemini free tier). If this model is unavailable the bot also tries the
# fallback models listed in caption_gen.py.
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# ---------------------------------------------------------------------------
# META GRAPH API
# ---------------------------------------------------------------------------
FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "")
IG_BUSINESS_ACCOUNT_ID = os.environ.get("IG_BUSINESS_ACCOUNT_ID", "")
GRAPH_API_VERSION = os.environ.get("GRAPH_API_VERSION", "v21.0")
PUBLIC_IMAGE_BASE_URL = os.environ.get("PUBLIC_IMAGE_BASE_URL", "")

# ---------------------------------------------------------------------------
# BRANDING
# ---------------------------------------------------------------------------
PAGE_NAME = os.environ.get("PAGE_NAME", "Cinema Woods")
ACCENT_COLOR = os.environ.get("ACCENT_COLOR", "#E63946")
