"""
Fact-check gate for generated posts. Free and deterministic (no extra Gemini call):

Every name, number and year in the post must also appear in the source (the headline and the article text).
Details the model added from its own memory or from a different story - the wrong director, an old date -
are exactly what this catches.

check() -> (ok, problems, checked)
  checked=False means no article text was available, so only the "old date" rule could be applied.
"""

import datetime
import re

# capitalised words that are not claims
COMMON = {w.lower() for w in """
January February March April May June July August September October November December
Monday Tuesday Wednesday Thursday Friday Saturday Sunday
Telugu Tamil Kannada Malayalam Hindi English India Indian South Tollywood Kollywood Sandalwood Mollywood Bollywood
Cinema Woods Instagram Facebook Telegram OTT YouTube Dasara Diwali Sankranti Pongal Ugadi Onam Eid Christmas
Rs INR USD Crore Lakh Million Billion
""".split()}

NAME_RE = re.compile(r"\b[A-Z][A-Za-z'’\-]{2,}\b")
NUM_RE = re.compile(r"(?<![\w#@])(\d[\d,]*(?:\.\d+)?)(?:st|nd|rd|th)?(?![\w])")
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _strip(text: str) -> str:
    text = re.sub(r"#\w+", " ", text)                 # hashtags
    text = re.sub(r"@\w+", " ", text)                 # handles
    text = re.sub(r"https?://\S+", " ", text)
    text = text.replace("*", " ").replace("_", " ")
    return text


def _name_candidates(caption: str):
    """Capitalised words that are claims: skip single sentence-opening words ('Fans', 'Directed')."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", _strip(caption)):
        words = sentence.split()
        for i, raw in enumerate(words):
            m = NAME_RE.fullmatch(re.sub(r"^[^A-Za-z]+|[^A-Za-z'’]+$", "", raw)) if raw else None
            if not m:
                continue
            word = m.group(0)
            prev_cap = i > 0 and re.match(r"[A-Z]", re.sub(r"^[^A-Za-z]+", "", words[i - 1]) or "x")
            next_cap = i + 1 < len(words) and re.match(r"[A-Z]", re.sub(r"^[^A-Za-z]+", "", words[i + 1]) or "x")
            if i == 0 and not next_cap:
                continue  # a lone sentence-opening word is not a name
            if i == 0 and next_cap is None:
                continue
            word = re.sub(r"(['’]s)$", "", word)
            if len(word) >= 3 and word.lower() not in COMMON:
                out.append(word)
    return out


def check(caption: str, headline: str, source_text: str = "", summary: str = "", today=None):
    now = today or datetime.date.today()
    hay = f"{headline} {summary} {source_text}".lower().replace(",", "")
    have_source = len((source_text or "").strip()) >= 200
    body = _strip(caption)
    problems = []

    # years: an unsupported year is the classic stale-news tell ("launched March 6, 2025")
    for y in sorted(set(YEAR_RE.findall(body))):
        if y not in hay:
            if have_source or int(y) != now.year:
                problems.append(f"year {y}")

    if have_source:
        for n in NUM_RE.findall(body):
            plain = n.replace(",", "")
            if YEAR_RE.fullmatch(plain):
                continue
            try:
                if float(plain) <= 10:
                    continue  # small counts are usually written out in the article ("five languages")
            except ValueError:
                continue
            if plain not in hay:
                problems.append(f"number {n}")
        seen = set()
        for word in _name_candidates(caption):
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            if key not in hay:
                problems.append(f"name {word}")

    # keep the report short and unique
    uniq = []
    for p in problems:
        if p not in uniq:
            uniq.append(p)
    return (not uniq, uniq[:8], have_source)
