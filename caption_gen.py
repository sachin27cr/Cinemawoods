"""
Rewrites a raw news headline into a short social caption using Gemini.
If Gemini fails the story is skipped for this run (never posted as a bare
headline); the reason is printed in the run log.
"""

import json
import os
import re
import time
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

# Google retires Gemini models regularly, so the bot asks Google which models your
# key can use today instead of relying on a fixed list. These names are only a
# last resort if that lookup itself fails.
LAST_RESORT_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]
SKIP_MODEL_WORDS = ("image", "tts", "live", "audio", "embedding", "robotics", "computer", "learnlm",
                    "gemma", "vision", "thinking-exp", "aqa", "imagen", "veo", "native-dialog")

_discovered = None      # cached model list for this run
_dead = set()           # models that returned 404 / quota-exhausted this run


ERRORS = []  # distinct recent Gemini errors this run (key removed), shown in the Telegram report


def _note_error(text: str) -> None:
    text = text.replace(config.GEMINI_API_KEY or "\x00", "***")[:300]
    if text not in ERRORS:
        ERRORS.append(text)


def _version_of(name: str) -> float:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def _discover_models() -> list:
    """Flash-class models your key can call right now, newest first."""
    global _discovered
    if _discovered is not None:
        return _discovered
    found = []
    try:
        url = ("https://generativelanguage.googleapis.com/v1beta/models"
               f"?pageSize=200&key={config.GEMINI_API_KEY}")
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for m in data.get("models", []):
            name = m.get("name", "").replace("models/", "")
            if (name.startswith("gemini") and "flash" in name
                    and "generateContent" in m.get("supportedGenerationMethods", [])
                    and not any(w in name for w in SKIP_MODEL_WORDS)):
                found.append(name)
        found.sort(key=lambda n: (-_version_of(n), "lite" in n, "preview" in n or "exp" in n, n))
        print(f"[INFO] Gemini models available to your key: {', '.join(found[:8]) or 'none found'}")
    except Exception as e:
        print(f"[WARN] Could not list Gemini models ({type(e).__name__}); using built-in names")
        _note_error(f"model list lookup failed: {type(e).__name__}")
    _discovered = found
    return found


def _models_to_try():
    models = []
    explicit = os.environ.get("GEMINI_MODEL", "").strip()  # only if you set the variable yourself
    for m in ([explicit] if explicit else []) + _discover_models()[:4] + LAST_RESORT_MODELS:
        if m and m not in models and m not in _dead:
            models.append(m)
    return models


def _call_model(model: str, prompt: str, grounded: bool = True) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={config.GEMINI_API_KEY}"
    )
    generation = {"temperature": 0.4, "maxOutputTokens": 8192}
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
    cut_off = candidates[0].get("finishReason") == "MAX_TOKENS"
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise ValueError("empty text returned")
    if cut_off:
        print(f"[WARN] Gemini {model}: reply hit the length limit; trimming to the last full sentence")
        text = "\x00" + text  # marker: finalised (trimmed) by generate_caption
    return text


def _retry_delay(body: str):
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body) or re.search(r"retry in (\d+(?:\.\d+)?)s", body)
    return float(m.group(1)) if m else None


def _try_model(model: str, prompt: str) -> str:
    """One model: with search first, then without; waits once for a short rate-limit."""
    for attempt in range(2):
        for grounded in (True, False):
            try:
                return _call_model(model, prompt, grounded=grounded)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")
                label = f"{model}{' with search' if grounded else ''}: HTTP {e.code} {body[:200]}"
                print(f"[WARN] Gemini {label}")
                _note_error(label)
                if e.code in (401, 403) and "search" not in body.lower():
                    raise
                if e.code == 404:
                    _dead.add(model)
                    raise
                if e.code == 429:
                    delay = _retry_delay(body)
                    if grounded:
                        continue  # try again without search (separate, larger quota)
                    if attempt == 0 and delay is not None and delay <= 45:
                        print(f"  waiting {delay:.0f}s for the rate limit, then retrying {model}")
                        time.sleep(delay + 1)
                        break  # outer loop retries once
                    _dead.add(model)  # quota used up: don't hammer it for every story
                    raise
                if grounded:
                    continue
                raise
            except Exception as e:
                label = f"{model}: {e}"
                print(f"[WARN] Gemini {label}")
                _note_error(label)
                if grounded:
                    continue
                raise
        else:
            raise RuntimeError(f"{model}: failed")
    raise RuntimeError(f"{model}: rate limited")


def _call_gemini(prompt: str) -> str:
    if not config.GEMINI_API_KEY:
        _note_error("GEMINI_API_KEY is empty - the repo secret is missing, misspelled, or not passed to the workflow")
        raise RuntimeError("GEMINI_API_KEY is empty - check the repo secret name and value")

    last_error = "unknown error"
    for model in _models_to_try():
        try:
            return _try_model(model, prompt)
        except urllib.error.HTTPError as e:
            last_error = f"{model}: HTTP {e.code}"
            if e.code in (401, 403):
                break  # bad key or permission: other models will fail the same way
        except Exception as e:
            last_error = f"{model}: {e}"
    raise RuntimeError(last_error)


SKIP = "SKIP"
DEFAULT_TAGS = "#SouthIndianCinema #Tollywood #Kollywood #Sandalwood #Mollywood"
TAGS_RE = re.compile(r"((?:\s*#\w+)+)\s*$")


def _finalise(text: str) -> str:
    """Splits the hashtags from the text, makes sure the text ends on a complete
    sentence (trimming a cut-off reply back to its last full sentence), and
    puts the hashtags on their own line."""
    truncated = text.startswith("\x00")
    text = text.lstrip("\x00").strip()
    m = TAGS_RE.search(text)
    tags = m.group(1).strip() if m else ""
    body = (text[:m.start()] if m else text).strip()

    if truncated or (body and body[-1].isalnum()):
        cut = max(body.rfind("."), body.rfind("!"), body.rfind("?"))
        if cut == -1:
            raise ValueError("caption has no complete sentence")
        body = body[:cut + 1].strip()
    if len(body.split()) < 20 or len(re.findall(r"[.!?](?:\s|$)", body)) < 2:
        raise ValueError("caption too short to be useful")
    return f"{body}\n\n{tags or DEFAULT_TAGS}"


def generate_caption(item: NewsItem):
    """Returns the post text, SKIP when the headline carries no real news, or
    None when Gemini could not be reached (the story is then retried next run
    instead of posting a bare headline)."""
    prompt = PROMPT_TEMPLATE.format(title=item.title, summary=item.summary or "(none)")
    try:
        caption = _call_gemini(prompt)
        caption = re.sub(r"^(\x00?)[\"']|[\"']$", r"\1", caption.strip())
        if caption.lstrip("\x00").upper().startswith("SKIP"):
            return SKIP
        return _finalise(caption)
    except Exception as e:
        print(f"[WARN] Caption generation failed for '{item.title}': {e}")
        return None
