"""
Rewrites a raw news item into a short social caption using Gemini
(matches the free-tier vision/text provider used in your other bots).
"""

import json
import re
import urllib.request
import urllib.error

import config
from fetch_news import NewsItem

PROMPT_TEMPLATE = """You are writing a short Instagram/Facebook caption for a South Indian \
cinema news page (Telugu, Tamil, Kannada, Malayalam film industries).

Rules:
- 2-3 sentences max, punchy and factual — no invented details, no invented quotes.
- If the headline/summary doesn't give enough detail for a claim, leave it out rather than guessing.
- End with 5-8 relevant hashtags (mix of actor/movie-specific and industry tags like #Tollywood #Kollywood #Sandalwood #Mollywood as applicable).
- No emojis in excess — at most 1-2.
- Do not fabricate box office numbers, release dates, or cast details not present in the source text.

Source headline: {title}
Source summary: {summary}

Respond with ONLY the caption text, nothing else."""


def _call_gemini(prompt: str) -> str:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 300},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def _fallback_caption(item: NewsItem) -> str:
    """Used if the LLM call fails — a safe, non-hallucinated caption made
    directly from the headline, so the pipeline degrades gracefully rather
    than blocking."""
    tags = "#SouthIndianCinema #Tollywood #Kollywood #Sandalwood #Mollywood"
    return f"{item.title}\n\n{tags}"


def generate_caption(item: NewsItem) -> str:
    prompt = PROMPT_TEMPLATE.format(title=item.title, summary=item.summary or item.title)
    try:
        caption = _call_gemini(prompt)
        caption = re.sub(r"^[\"']|[\"']$", "", caption.strip())
        if not caption:
            raise ValueError("empty caption returned")
        return caption
    except Exception as e:
        print(f"[WARN] Caption generation failed for '{item.title}': {e}. Using fallback.")
        return _fallback_caption(item)
