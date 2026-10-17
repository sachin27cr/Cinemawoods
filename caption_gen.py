"""
Rewrites a raw news headline into a short social caption using Gemini.
If every Gemini attempt fails, the reason is printed in the run log and a
plain headline caption is used instead, so the pipeline never blocks.
"""

import json
import re
import urllib.error
import urllib.request

import config
from fetch_news import NewsItem

PROMPT_TEMPLATE = """You are writing a short Instagram/Facebook caption for "Cinema Woods", a \
South Indian cinema news page (Telugu, Tamil, Kannada, Malayalam film industries).

Rules:
- Write in English. 2-3 sentences max, punchy and factual.
- Use ONLY facts present in the headline/summary below. Never invent details, numbers, dates, cast or quotes.
- If the headline is thin, write one clean sentence rather than guessing.
- Do not mention the news outlet's name.
- End with 5-8 relevant hashtags (movie/actor-specific plus industry tags like #Tollywood #Kollywood #Sandalwood #Mollywood as applicable).
- At most 1-2 emojis.

Headline: {title}
Summary: {summary}

Respond with ONLY the caption text, nothing else."""

FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]


def _models_to_try():
    models = []
    for m in [config.GEMINI_MODEL] + FALLBACK_MODELS:
        if m and m not in models:
            models.append(m)
    return models


def _call_model(model: str, prompt: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={config.GEMINI_API_KEY}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 400},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError(f"no candidates returned: {str(data.get('promptFeedback'))[:200]}")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise ValueError("empty text returned")
    return text


def _call_gemini(prompt: str) -> str:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is empty - check the repo secret name and value")

    last_error = "unknown error"
    for model in _models_to_try():
        try:
            return _call_model(model, prompt)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")[:300]
            last_error = f"{model}: HTTP {e.code} {body}"
            print(f"[WARN] Gemini {last_error}")
            if e.code in (400, 401, 403):
                break  # bad key or permission: other models will fail the same way
        except Exception as e:
            last_error = f"{model}: {e}"
            print(f"[WARN] Gemini {last_error}")
    raise RuntimeError(last_error)


def _fallback_caption(item: NewsItem) -> str:
    tags = "#SouthIndianCinema #Tollywood #Kollywood #Sandalwood #Mollywood"
    return f"{item.title}\n\n{tags}"


def generate_caption(item: NewsItem) -> str:
    prompt = PROMPT_TEMPLATE.format(title=item.title, summary=item.summary or "(none)")
    try:
        caption = _call_gemini(prompt)
        caption = re.sub(r"^[\"']|[\"']$", "", caption.strip())
        if not caption:
            raise ValueError("empty caption after cleanup")
        return caption
    except Exception as e:
        print(f"[WARN] Caption generation failed for '{item.title}': {e}. Using fallback.")
        return _fallback_caption(item)
