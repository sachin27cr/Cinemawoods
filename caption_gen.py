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
from models import NewsItem

PROMPT_TEMPLATE = """You write the text that appears BELOW the picture on an Instagram/Facebook post for \
"Cinema Woods", a South Indian cinema news page (Telugu, Tamil, Kannada, Malayalam). The picture only \
shows the headline, so this text must carry the full information so a reader understands the news without \
clicking anything.

Reply in exactly this layout:
HEADLINE: <a complete, clean headline for the picture, 8-14 words, max 95 characters, no outlet name>
<blank line>
<the post text>

The headline you are given may be cut off mid-word or mid-sentence (many outlets truncate titles); use your \
search to work out what it says and write a complete headline that stands on its own.

Rules for the post text:
- English. Write 5 to 8 complete sentences (about 90-140 words) as 1-2 short paragraphs: what happened, who \
is involved, the key facts (film, star, director, numbers, dates, platform) and brief useful context for a \
fan. Every sentence must be complete and must make sense on its own; never stop mid-sentence.
- Use Google Search to check this exact news and add verified details. Only state facts you are confident \
about; never invent numbers, dates, cast, plot or quotes. If you cannot verify more than the headline says, \
write fewer sentences (3 minimum) rather than guessing.
- Almost every headline about a film, star, trailer, teaser, release, box office figure, OTT deal, casting or \
shoot is real news: write the post for it. Reply "SKIP: <reason in five words>" ONLY if the headline is purely \
a generic listing page with no event at all (for example a "daywise collection table" or "full cast list" \
page, or a pure "where to watch" guide). A review, birthday feature or opinion piece is not a SKIP: summarise \
what the headline says.
- Do not mention the news outlet's name or say "source".
- Finish with a blank line, then 5-8 hashtags (film/star specific plus industry tags such as #Tollywood \
#Kollywood #Sandalwood #Mollywood as applicable).
- At most 2 emojis.
- Voice for this post: {style}

Headline: {title}
Summary: {summary}

Respond with ONLY the HEADLINE line and the post text (or SKIP), nothing else."""

# Posts used to read the same every time. Each post now gets one of these voices at random.
STYLES = [
    "Open with a short punchy hook line (a few words), then the facts. End with a one-line question that gets fans commenting.",
    "Write it like a quick breaking-news update: lead with the single most important fact in the first sentence. End with what to watch for next.",
    "Open with the fan angle (why this matters to fans of the star or film), then the facts. End by asking fans to share their reaction.",
    "Write it in a warm, conversational voice, as if telling a friend the news. End with a short line inviting fans to tag a friend.",
    "Lead with the number, date or milestone if there is one, then give the context. End with a one-line takeaway.",
    "Open with a one-sentence scene-setter about the film or star, then the news and facts. End with an open question about expectations.",
]


def _style() -> str:
    import random
    return random.choice(STYLES)


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
    for attempt in range(3):
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
                    if attempt < 2 and delay is not None and delay <= 60:
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
SKIP_REASONS = []  # (headline, reason) skipped this run, shown in the Telegram report
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


def _clean_headline(h: str, original: str) -> str:
    h = re.sub(r"\s+", " ", h).strip(" *\"'")
    if 15 <= len(h) <= 110:
        return h
    return _tidy_original(original)


def _tidy_original(title: str) -> str:
    """Fallback when Gemini gives no usable headline: a title that was cut off by
    the outlet loses its last (partial) word; over-long titles end at a whole word."""
    t = title.strip()
    if len(t) >= 100 and t[-1].isalnum():
        t = t.rsplit(" ", 1)[0]
        t = t.rstrip(" ,;:-") + "..."
    if len(t) > 110:
        t = t[:107].rsplit(" ", 1)[0].rstrip(" ,;:-") + "..."
    return t


def generate_caption(item: NewsItem):
    """Returns the post text, SKIP when the headline carries no real news, or
    None when Gemini could not be reached (the story is then retried next run
    instead of posting a bare headline)."""
    prompt = PROMPT_TEMPLATE.format(style=_style(), title=item.title, summary=item.summary or "(none)")
    try:
        caption = _call_gemini(prompt)
        caption = re.sub(r"^(\x00?)[\"']|[\"']$", r"\1", caption.strip())
        head = caption.lstrip("\x00")
        if re.match(r"(?i)skip\b", head):
            reason = head[4:].lstrip(": -").splitlines()[0][:80] if len(head) > 4 else ""
            print(f"  Gemini says SKIP: {reason or 'no reason given'}")
            SKIP_REASONS.append((item.title[:70], reason))
            return SKIP
        trunc = caption.startswith("\x00")
        raw = caption.lstrip("\x00")
        m = re.match(r"\s*\**HEADLINE\**\s*:\s*(.+?)\s*(?:\n|$)", raw, re.I)
        if m:
            item.card_title = _clean_headline(m.group(1), item.title)
            raw = raw[m.end():].strip()
        else:
            item.card_title = _tidy_original(item.title)
        return _finalise(("\x00" if trunc else "") + raw)
    except Exception as e:
        print(f"[WARN] Caption generation failed for '{item.title}': {e}")
        return None


TIP_PROMPT = """You are the editor of "Cinema Woods", a South Indian cinema news page (Telugu, Tamil, Kannada, \
Malayalam). The page owner sent you this tip. It may be a link, a headline, or rough notes:

Today's date is {today}. Your own knowledge is out of date: films and events after your training exist, so \
NEVER reject a tip because you do not recognise a film, a release or a number. Judge only from what Google Search \
shows and from what the owner wrote. Treat the owner's tip as probably true.

TIP: {tip}
{page}
Use Google Search to verify the story and collect the key facts, then write the post.

Reply in exactly this layout:
HEADLINE: <a complete, clean headline for the picture, 8-14 words, max 95 characters>
<blank line>
<the post text>

Rules for the post text:
- English. {length}: what happened, who is involved, \
key facts (film, star, director, numbers, dates, platform) and brief useful context for a fan.
- Only state facts you can verify or that the owner gave you. Never invent numbers, dates, cast, plot or quotes.
- Do not mention the news outlet's name or say "source".
- Finish with a blank line, then 5-8 hashtags (film/star specific plus industry tags such as #Tollywood \
#Kollywood #Sandalwood #Mollywood as applicable). At most 2 emojis.
- Voice for this post: {style}
{mode}
Respond with ONLY the layout above."""

MODE_VERIFY = """- Reply OFFTOPIC: <reason in five words> ONLY if the tip is clearly unrelated to films, actors or the entertainment \
industry (for example cricket, politics, a non-film product). A film or star from any Indian industry that you \
simply do not recognise is NOT off topic.
- Reply UNVERIFIED: <what you could not confirm> ONLY if searching finds nothing at all about it and the tip itself \
has no concrete detail. If searches find the story, or the link page describes it, write the post."""
MODE_FORCE = """- The owner has asked you to write this even if it cannot be fully verified: use the owner's details and anything \
you can confirm, and keep the wording factual and cautious where unsure."""


LENGTH_LONG = "5 to 8 complete sentences (about 90-140 words), as 1-2 short paragraphs"
LENGTH_SHORT = ("2 to 4 complete sentences (about 45-70 words), as ONE short paragraph - the picture carries the "
                "post, so keep the text light and easy to scan")


def generate_from_tip(tip: str, page: dict = None, force: bool = False, short: bool = False):
    """Researches a tip. Returns (status, headline, caption, reason) where status is
    "ok", "unverified", "offtopic" or "failed"."""
    page_text = ""
    if page and (page.get("title") or page.get("description")):
        page_text = "LINK PAGE TITLE: {t}\nLINK PAGE DESCRIPTION: {d}\n".format(
            t=page.get("title", ""), d=(page.get("description", "") or "")[:600])
    prompt = TIP_PROMPT.format(length=LENGTH_SHORT if short else LENGTH_LONG, style=_style(), today=time.strftime('%d %B %Y'), tip=tip[:1500], page=page_text, mode=MODE_FORCE if force else MODE_VERIFY)
    try:
        reply = _call_gemini(prompt)
    except Exception as e:
        print(f"[WARN] Tip research failed: {e}")
        return "failed", "", "", "; ".join(ERRORS[:2]) or str(e)[:200]
    trunc = reply.startswith("\x00")
    raw = reply.lstrip("\x00").strip()
    m = re.match(r"(?i)(unverified|offtopic)\b[:\s-]*(.*)", raw)
    if m:
        return m.group(1).lower(), "", "", (m.group(2).splitlines() or [""])[0][:200]
    try:
        hm = re.match(r"\s*\**HEADLINE\**\s*:\s*(.+?)\s*(?:\n|$)", raw, re.I)
        headline = _clean_headline(hm.group(1), tip) if hm else _tidy_original(tip.splitlines()[0])
        body = raw[hm.end():].strip() if hm else raw
        return "ok", headline, _finalise(("\x00" if trunc else "") + body), ""
    except Exception as e:
        return "failed", "", "", f"Gemini's reply was not usable ({e})"
