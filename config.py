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
    # more topics so a run is not all box-office headlines about one or two big films
    "Telugu movie OTT release date",
    "Tamil movie OTT release date",
    "Malayalam movie OTT release",
    "Kannada movie trailer teaser",
    "Telugu movie first look poster",
    "Tamil movie first look poster",
    "Tollywood new movie announcement",
    "Kollywood new film announcement",
    "Mollywood new film shooting update",
    "Sandalwood new film update",
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
    # generic listing / explainer pages that carry no actual news
    "daywise", "day wise", "hit or flop", "hit or a flop", "budget &", "budget and box office",
    "full list", "cast & crew", "cast and crew", "where to watch", "how to watch",
    "all you need to know", "everything you need to know", "explained",
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
# VARIETY + FRESHNESS
# ---------------------------------------------------------------------------
# Stories older than this are ignored, so every run is built from fresh news.
MAX_AGE_HOURS = float(os.environ.get("MAX_AGE_HOURS", "30"))

# Within one run: never two stories on the same film or star. After the first
# pick, every other pick is penalised by this many score points for each earlier
# pick from the same industry / of the same story type (box office, trailer...),
# which pushes the run to spread across languages and story types.
DIVERSITY_INDUSTRY_PENALTY = float(os.environ.get("DIVERSITY_INDUSTRY_PENALTY", "3"))
DIVERSITY_CATEGORY_PENALTY = float(os.environ.get("DIVERSITY_CATEGORY_PENALTY", "3"))

# Across runs: a film/star covered recently is skipped for a while.
#  - same topic AND same story type (e.g. another Jailer 2 box office update)
TOPIC_COOLDOWN_HOURS = float(os.environ.get("TOPIC_COOLDOWN_HOURS", "48"))
#  - same topic but a different story type (e.g. Jailer 2 trailer after box office)
TOPIC_ANY_TYPE_COOLDOWN_HOURS = float(os.environ.get("TOPIC_ANY_TYPE_COOLDOWN_HOURS", "12"))

# Extra story count from one outlet-heavy story is capped so a single mega-story
# cannot dominate the ranking.
COVERAGE_BONUS_PER_OUTLET = 1.5
COVERAGE_BONUS_MAX_OUTLETS = 3

# ---------------------------------------------------------------------------
# DEDUP
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "posted_log.db")
DEDUP_TITLE_SIMILARITY_THRESHOLD = 0.80

# ---------------------------------------------------------------------------
# POSTING LIMITS
# ---------------------------------------------------------------------------
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "3"))
# Pause between stories so Gemini's free per-minute limit is not hit.
GEMINI_PAUSE_SECONDS = float(os.environ.get("GEMINI_PAUSE_SECONDS", "6"))

# ---------------------------------------------------------------------------
# ARTICLE IMAGES
# 1 = show the publisher's lead image (poster/still) inside the card when one can
# be found. These images are the publishers' property: copyright risk is yours.
# 0 = always use the text-only designed card.
# ---------------------------------------------------------------------------
USE_ARTICLE_IMAGES = os.environ.get("USE_ARTICLE_IMAGES", "1") == "1"

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
