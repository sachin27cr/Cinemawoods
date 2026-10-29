"""
Claude as the editor of Cinema Woods (optional; needs the ANTHROPIC_API_KEY secret).

  rank(...)          picks and orders the day's stories (variety, real news, not stale)
  write_post(...)    writes the headline + post text from the article, or says SKIP / UNVERIFIED
  write_tip(...)     same for a tip you send in Telegram (uses web search)
  headline(...)      short picture headline for text you wrote yourself
  choose_poster(...) looks at the candidate pictures and picks the real poster/still, or none

Every function returns None when Claude is unavailable (no key, over budget, error), and the caller then falls
back to the old Gemini path, so a Claude outage never stops the bot.

Spend is tracked in claude_usage.json and the bot stops calling Claude once CLAUDE_MONTHLY_CAP_USD is reached.
"""

import base64
import json
import re
import time
import urllib.error
import urllib.request

import config

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
SEARCH_USD = 0.01  # per web search

# USD per million tokens (input, output); matched by a word in the model name
PRICES = {"haiku": (0.10, 0.50), "sonnet": (2.0, 10.0), "opus": (4.0, 20.0)}

ERRORS = []        # distinct Claude problems this run (shown in the Telegram summary)
CAP_HIT = False


def _note(text: str) -> None:
    text = text.replace(config.ANTHROPIC_API_KEY or "\x00", "***")[:300]
    if text not in ERRORS:
        ERRORS.append(text)


# ------------------------------------------------------------------ spend tracking

def _month() -> str:
    return time.strftime("%Y-%m")


def _load_usage() -> dict:
    try:
        with open(config.CLAUDE_USAGE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if data.get("month") != _month():
        data = {"month": _month(), "usd": 0.0, "calls": 0}
    return data


def _add_usage(model: str, usage: dict) -> None:
    pin, pout = next((p for k, p in PRICES.items() if k in model), PRICES["sonnet"])
    cost = (usage.get("input_tokens", 0) * pin + usage.get("output_tokens", 0) * pout) / 1_000_000
    cost += (usage.get("cache_creation_input_tokens", 0) * pin * 1.25 + usage.get("cache_read_input_tokens", 0) * pin * 0.1) / 1_000_000
    cost += (usage.get("server_tool_use") or {}).get("web_search_requests", 0) * SEARCH_USD
    data = _load_usage()
    data["usd"] = round(data["usd"] + cost, 5)
    data["calls"] += 1
    try:
        with open(config.CLAUDE_USAGE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError:
        pass


def spent_usd() -> float:
    return _load_usage()["usd"]


def usage_line() -> str:
    if not config.USE_CLAUDE:
        return ""
    d = _load_usage()
    return f"Claude spend this month: ${d['usd']:.2f} of ${config.CLAUDE_MONTHLY_CAP_USD:.0f} cap ({d['calls']} calls)"


def enabled() -> bool:
    global CAP_HIT
    if not (config.USE_CLAUDE and config.ANTHROPIC_API_KEY):
        return False
    if spent_usd() >= config.CLAUDE_MONTHLY_CAP_USD:
        if not CAP_HIT:
            CAP_HIT = True
            _note(f"monthly Claude cap of ${config.CLAUDE_MONTHLY_CAP_USD:.0f} reached - using Gemini until next month")
            print(f"[WARN] {ERRORS[-1]}")
        return False
    return True


# ------------------------------------------------------------------ API call

def _post(payload: dict) -> dict:
    last = None
    for attempt in range(3):
        req = urllib.request.Request(
            API_URL, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": API_VERSION,
                     "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            last = f"HTTP {e.code} {body[:200]}"
            if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            raise RuntimeError(last)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < 2:
                time.sleep(3)
                continue
            raise RuntimeError(last)
    raise RuntimeError(last or "failed")


def complete(model: str, system: str, user, max_tokens: int = 1200, search: bool = False):
    """Text reply from Claude, or None if unavailable. `user` is a string or a list of content blocks."""
    if not enabled():
        return None
    payload = {"model": model, "max_tokens": max_tokens, "system": system,
               "messages": [{"role": "user", "content": user}]}
    if search and config.CLAUDE_SEARCH:
        payload["tools"] = [{"type": config.CLAUDE_SEARCH_TOOL, "name": "web_search", "max_uses": 3}]
    try:
        try:
            data = _post(payload)
        except RuntimeError as e:
            if "tools" in payload and "HTTP 400" in str(e):
                _note(f"web search not available ({str(e)[:120]}); continuing without it")
                payload.pop("tools")
                data = _post(payload)
            else:
                raise
    except Exception as e:
        print(f"[WARN] Claude {model}: {e}")
        _note(f"{model}: {e}")
        return None
    _add_usage(model, data.get("usage") or {})
    blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    text = "".join(blocks).strip()
    if data.get("stop_reason") == "max_tokens" and text:
        text = "\x00" + text  # marker: reply was cut off (caller trims to the last full sentence)
    return text or None


# ------------------------------------------------------------------ writing

HOOK = (
    "- The headline must make a fan curious enough to read on, yet stay 100% true and answerable from the story: build "
    "it from the most interesting REAL detail (a surprising number, a first or record, a contrast, an unexpected name, "
    "or a question the post answers). Never mislead, never exaggerate, no 'shocking' or 'you won't believe', no ALL CAPS, "
    "never a vague label like 'box office update'. The post text opens with a one-sentence hook from a real fact.\n"
)

HOUSE_RULES = (
    "- Always give exact dates (for example 24 October 2026), never 'today', 'tomorrow' or 'yesterday'.\n"
    "- For a box office story the HEADLINE must start with the collection figure (for example "
    "'₹300 Cr worldwide: Jailer 2 ...').\n"
) + HOOK

POST_SYSTEM = """You are the editor of "Cinema Woods", a South Indian cinema news page on Instagram and Facebook \
(Telugu, Tamil, Kannada, Malayalam). You write the text that sits BELOW the picture; the picture only shows a \
headline, so your text must carry the full news.

Today's date is {today}. Your own knowledge is out of date: films, stars and events after your training exist, so \
NEVER reject a story because you do not recognise it. Judge only from the article text given to you.

Reply in exactly this layout:
HEADLINE: <complete, clean headline for the picture, 8-14 words, max 95 characters, no outlet name>
<blank line>
<the post text>

Post text rules:
- English, 5 to 8 complete sentences (about 90-140 words) in 1-2 short paragraphs: what happened, who is involved, \
the key facts (film, star, director, numbers, dates, platform) and a little useful context for a fan. Every \
sentence complete; never stop mid-sentence. If the source supports fewer than 5 sentences, write fewer (3 minimum).
- {sourcing}
- Never invent or "remember" names, numbers, dates, cast, plot or quotes. Several films and people share names: \
state only what THIS story says.
{house}- Do not mention the news outlet or say "source".
- Finish with a blank line, then 5-8 hashtags (film/star specific plus #Tollywood #Kollywood #Sandalwood \
#Mollywood as applicable). At most 2 emojis.
- Voice for this post: {style}

Other replies (use instead of the layout):
- "SKIP: <reason in five words>" only if the story is not news (a pure listing page, cast list or where-to-watch \
guide) or is not about South Indian cinema (for example a Hindi-only film).
- "UNVERIFIED: <what is unclear>" only if you cannot tell which film or person this is about."""

SOURCING_ARTICLE = ("Base EVERY fact on the ARTICLE TEXT in the user message. If the headline and the article "
                    "disagree, trust the article. Leave a detail out rather than guess it.")
SOURCING_SEARCH = ("The article could not be opened. Use web search, and state only facts that at least two "
                   "independent reports confirm for THIS exact story. Do not name directors, producers or "
                   "composers, and do not mention dates or years, unless the headline or those reports do.")


def write_post(item, article_text: str, style: str, fix_hint=None):
    """Raw reply in the HEADLINE:/text layout (or SKIP:/UNVERIFIED:), or None if Claude is unavailable."""
    have = bool(article_text.strip())
    system = POST_SYSTEM.format(today=time.strftime("%d %B %Y"), style=style, house=HOUSE_RULES,
                                sourcing=SOURCING_ARTICLE if have else SOURCING_SEARCH)
    user = f"HEADLINE FROM THE FEED: {item.title}\nFEED SUMMARY: {item.summary or '(none)'}\n"
    if have:
        user += f"\nARTICLE TEXT (the only trusted source):\n\"\"\"\n{article_text[:3500]}\n\"\"\"\n"
    if fix_hint:
        user += ("\nYour previous draft was REJECTED by the fact-checker because it contained details that are "
                 f"not in the article: {', '.join(fix_hint)}. Rewrite the post and leave those details out.\n")
    return complete(config.CLAUDE_MODEL, system, user, max_tokens=900, search=not have)


TIP_SYSTEM = """You are the editor of "Cinema Woods", a South Indian cinema news page (Telugu, Tamil, Kannada, \
Malayalam). The page owner sends you a tip: a link, a headline or rough notes. Today's date is {today}. Your own \
knowledge is out of date: NEVER reject a tip because you do not recognise a film, release or number. Treat the \
owner's tip as probably true and judge from the link page text and web search.

Reply in exactly this layout:
HEADLINE: <complete, clean headline for the picture, 8-14 words, max 95 characters>
<blank line>
<the post text>

Post text rules:
- English. {length}: what happened, who is involved, key facts (film, star, director, numbers, dates, platform) and \
brief useful context.
- Only state facts you can verify or that the owner gave you. Never invent numbers, dates, cast, plot or quotes.
{house}- Do not mention the news outlet or say "source".
- Finish with a blank line, then 5-8 hashtags (film/star specific plus #Tollywood #Kollywood #Sandalwood \
#Mollywood as applicable). At most 2 emojis.
- Voice for this post: {style}
{mode}"""


def write_tip(tip: str, page_text: str, length: str, style: str, mode: str):
    system = TIP_SYSTEM.format(today=time.strftime("%d %B %Y"), length=length, style=style, mode=mode, house=HOUSE_RULES)
    user = f"TIP: {tip[:1500]}\n{page_text}"
    return complete(config.CLAUDE_MODEL, system, user, max_tokens=900, search=True)


HEADLINE_SYSTEM = ("You write ONE headline to print on the picture of an Instagram news post for a South Indian "
                   "cinema page. Capture the main highlight of the post text. Complete and clear, 6-14 words, at most "
                   "95 characters, no outlet name, no hashtags, no emojis, no quotes, no facts that are not in the "
                   "text. For a box office post start with the collection figure. Reply with ONLY the headline.")


def headline(text: str):
    return complete(config.CLAUDE_FAST_MODEL, HEADLINE_SYSTEM, text[:1500], max_tokens=80)


# ------------------------------------------------------------------ choosing stories

RANK_SYSTEM = """You are the news editor of "Cinema Woods", a South Indian cinema page (Telugu, Tamil, Kannada, \
Malayalam). From the numbered candidate stories, choose and order the ones to post this run.

Today's date is {today}. Rules:
- Prefer concrete, fresh, fan-friendly news: box office figures, trailers/teasers, first looks, release dates, OTT \
dates, casting, shoots, awards.
- Spread the picks across the four industries and across story types. Never two stories about the same film or star.
- Do not pick a topic already covered in the RECENT POSTS list.
- Drop: Hindi-film stories with no South angle, listicles/explainers/"where to watch" pages, gossip about age, \
net worth or family, politics, and anything that looks old or recycled.
Return ONLY JSON: {{"order": [candidate numbers, best first, up to {limit}], "drop": {{"number": "reason in a few words"}}}}"""


def rank(candidates: list, recent_titles: list, limit: int):
    """Reordered/filtered candidates, or None if Claude is unavailable."""
    if not candidates:
        return candidates
    import classify
    lines = []
    for i, it in enumerate(candidates, 1):
        age = (time.time() - it.published_ts) / 3600 if it.published_ts else -1
        lines.append(f"{i}. {it.title} | {it.source} | {it.coverage} outlets | "
                     f"{classify.detect_industry(it.title) or 'SOUTH'}/{classify.detect_category(it.title)} | "
                     f"{'%.0fh old' % age if age >= 0 else 'age unknown'} | trend {it.score:.1f}")
    recent = "\n".join(f"- {t[:110]}" for t in recent_titles[:15]) or "(none)"
    user = "CANDIDATES:\n" + "\n".join(lines) + f"\n\nRECENT POSTS (do not repeat these topics):\n{recent}"
    reply = complete(config.CLAUDE_PICK_MODEL, RANK_SYSTEM.format(today=time.strftime("%d %B %Y"), limit=limit),
                     user, max_tokens=700)
    if not reply:
        return None
    m = re.search(r"\{.*\}", reply.lstrip("\x00"), re.S)
    try:
        data = json.loads(m.group(0))
        order = [int(x) for x in data.get("order", [])]
    except Exception:
        _note("ranking reply was not usable JSON")
        return None
    seen, picked = set(), []
    for n in order:
        if 1 <= n <= len(candidates) and n not in seen:
            seen.add(n)
            picked.append(candidates[n - 1])
    if not picked:
        return None
    for n, why in (data.get("drop") or {}).items():
        try:
            print(f"  [claude] dropped: {candidates[int(n) - 1].title[:70]} - {why}")
        except (ValueError, IndexError):
            pass
    return picked


# ------------------------------------------------------------------ choosing the poster

POSTER_SYSTEM = """You choose the picture for a South Indian cinema news post. You get the story and numbered \
candidate images from the article page. Pick the ONE image that is the official poster, first-look, teaser/trailer \
still or a clear photo of the film/star the story is about.

Reject: logos, outlet banners, ads, stock or unrelated photos, other films or other people, screenshots with big \
text overlays or watermarks, collages, tiny crops. If none is good, say none.
Return ONLY JSON: {"best": <number or null>, "reason": "<few words>"}"""


def choose_poster(title: str, article_text: str, image_urls: list):
    """(url or '', reason) after Claude looks at the images; None if Claude is unavailable or failed."""
    if not image_urls or not enabled():
        return None
    import image_fetch
    blocks, kept = [], []
    for url in image_urls[:6]:
        thumb = image_fetch.fetch_thumbnail(url)
        if not thumb:
            continue
        kept.append(url)
        blocks.append({"type": "text", "text": f"Image {len(kept)}:"})
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                   "data": base64.b64encode(thumb).decode()}})
    if not kept:
        return ("", "no usable images on the page")
    blocks.append({"type": "text", "text": f"STORY: {title}\n{article_text[:600]}"})
    reply = complete(config.CLAUDE_PICK_MODEL, POSTER_SYSTEM, blocks, max_tokens=150)
    if not reply:
        return None
    m = re.search(r"\{.*\}", reply, re.S)
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    best = data.get("best")
    reason = str(data.get("reason", ""))[:80]
    if isinstance(best, int) and 1 <= best <= len(kept):
        return (kept[best - 1], reason)
    return ("", reason or "no suitable picture")
