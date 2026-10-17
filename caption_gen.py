"""
Rewrites a raw news headline into a short social caption using Gemini.
If Gemini fails the story is skipped for this run (never posted as a bare
headline); the reason is printed in the run log.
"""

import json
import re
import urllib.error
import urllib.request

import config
from fetch_news import NewsItem

PROMPT_TEMPLATE = """You write the text that appears BELOW the picture on an Instagram/Facebook post for \
"Cinema Woods", a South Indian cinema news page (Telugu, Tamil, Kannada, Malayalam). The picture only \
shows the headline, so this text must carry the full information so a reader understands the news without \
clicking anything.

Rules:
- English. Write 5 to 8 complete sentences (about 90-140 words) as 1-2 short paragraphs: what happened, who \
is involved, the key facts (film, star, director, numbers, dates, platform) and brief useful context for a \
fan. Every sentence must be complete and must make sense on its own; never stop mid-sentence.
- Use Google Search to check this exact news and add verified details. Only state facts you are confident \
about; never invent numbers, dates, cast, plot or quotes. If you cannot verify more than the headline says, \
write fewer sentences (3 minimum) rather than guessing.
- If the headline has no concrete news (e.g. a generic "budget & box office collection daywise" listing page, \
a review index, a "hit or flop" explainer, or anything with no actual event or figure), reply with exactly: SKIP
- Do not mention the news outlet's name or say "source".
- Finish with a blank line, then 5-8 hashtags (film/star specific plus industry tags such as #Tollywood \
#Kollywood #Sandalwood #Mollywood as applicable).
- At most 2 emojis.

Headline: {title}
Summary: {summary}

Respond with ONLY the post text (or SKIP), nothing else."""

FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"]


def _models_to_try():
    models = []
    for m in [config.GEMINI_MODEL] + FALLBACK_MODELS:
        if m and m not in models:
            models.append(m)
    return models


def _call_model(model: str, prompt: str, grounded: bool = True) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={config.GEMINI_API_KEY}"
    )
    generation = {"temperature": 0.4, "maxOutputTokens": 4096}
    if model.startswith("gemini-2.5"):
        generation["thinkingConfig"] = {"thinkingBudget": 0}  # thinking tokens used to eat the budget and cut the text
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation,
    }
    if grounded:
        payload["tools"] = [{"google_search": {}}]
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError(f"no candidates returned: {str(data.get('promptFeedback'))[:200]}")
    if candidates[0].get("finishReason") == "MAX_TOKENS":
        raise ValueError("response was cut off (MAX_TOKENS)")
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
            try:
                return _call_model(model, prompt, grounded=True)
            except urllib.error.HTTPError as e:
                if e.code in (400, 403, 429, 404):
                    print(f"[WARN] Gemini {model} with search failed (HTTP {e.code}); retrying without search")
                    return _call_model(model, prompt, grounded=False)
                raise
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


SKIP = "SKIP"


def generate_caption(item: NewsItem):
    """Returns the post text, SKIP when the headline carries no real news, or
    None when Gemini could not be reached (the story is then retried next run
    instead of posting a bare headline)."""
    prompt = PROMPT_TEMPLATE.format(title=item.title, summary=item.summary or "(none)")
    try:
        caption = _call_gemini(prompt)
        caption = re.sub(r"^[\"']|[\"']$", "", caption.strip())
        if caption.upper().startswith("SKIP"):
            return SKIP
        if len(caption.split()) < 25:
            raise ValueError("caption too short to be useful")
        body = caption.split("\n\n#")[0].split("\n#")[0].strip()
        if body and body[-1].isalnum():
            raise ValueError("caption ends mid-sentence")
        return caption
    except Exception as e:
        print(f"[WARN] Caption generation failed for '{item.title}': {e}")
        return None
