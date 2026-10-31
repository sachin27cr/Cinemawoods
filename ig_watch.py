"""
Instagram watchlist: reads the latest posts of the Instagram pages you follow (actors, production companies, media
outlets) and turns them into story candidates, so the bot starts from the same official announcements you post by hand.

How: the Instagram Graph API "business discovery" feature lets your own Instagram business account read the public
posts of OTHER business / creator accounts (caption, date, link, picture). It needs no extra permission or secret:
the bot's existing FB_PAGE_ACCESS_TOKEN and IG_BUSINESS_ACCOUNT_ID are used. Personal (non-business) accounts cannot
be read this way; the bot tells you which handles failed.

Edit watchlist.txt (one handle per line, optional ",media" for news outlets) to change the pages watched.
Check which handles work:   python ig_watch.py
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import List

import config
from models import NewsItem

WATCHLIST_PATH = os.environ.get("WATCHLIST_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "watchlist.txt"))
POSTS_PER_PAGE = int(os.environ.get("IG_POSTS_PER_PAGE", "8"))
MAX_AGE_HOURS = float(os.environ.get("IG_MAX_AGE_HOURS", "30"))
MIN_CAPTION_CHARS = 25

ERRORS: list = []          # problems worth showing in the Telegram run summary
LAST_STATS: dict = {}      # {"ok": n, "failed": [handles], "posts": n}


def load_watchlist():
    """[(handle, kind)] where kind is 'official' (actor / producer / studio page) or 'media' (news outlet page)."""
    out, seen = [], set()
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                handle = parts[0].lstrip("@").lower()
                if not re.fullmatch(r"[a-z0-9._]{1,30}", handle) or handle in seen:
                    continue
                seen.add(handle)
                out.append((handle, "media" if len(parts) > 1 and parts[1].lower() == "media" else "official"))
    except FileNotFoundError:
        pass
    return out


def configured() -> bool:
    return bool(config.FB_PAGE_ACCESS_TOKEN and config.IG_BUSINESS_ACCOUNT_ID and load_watchlist())


def _discover(handle: str) -> dict:
    fields = (f"business_discovery.username({handle})"
              f"{{username,media.limit({POSTS_PER_PAGE})"
              f"{{caption,timestamp,permalink,media_type,media_url,thumbnail_url}}}}")
    url = (f"https://graph.facebook.com/{config.GRAPH_API_VERSION}/{config.IG_BUSINESS_ACCOUNT_ID}?"
           + urllib.parse.urlencode({"fields": fields, "access_token": config.FB_PAGE_ACCESS_TOKEN}))
    with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _error_text(e: Exception) -> str:
    if isinstance(e, urllib.error.HTTPError):
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", {})
            return f"{err.get('code')}: {err.get('message', '')[:160]}"
        except Exception:
            return f"HTTP {e.code}"
    return f"{type(e).__name__}"


def _ts(s: str) -> float:
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except Exception:
        return 0.0


def _clean_caption(c: str) -> str:
    """Caption as plain readable text: #Tags and @handles become plain words, links are dropped."""
    c = re.sub(r"https?://\S+", " ", c or "")
    c = re.sub(r"@([A-Za-z0-9._]+)", lambda m: m.group(1).replace(".", " ").replace("_", " "), c)
    c = re.sub(r"#([A-Za-z0-9_]+)", lambda m: re.sub(r"(?<=[a-z])(?=[A-Z])", " ", m.group(1)).replace("_", " "), c)
    c = re.sub(r"[ \t]+", " ", c)
    c = re.sub(r"\n\s*\n+", "\n", c)
    return c.strip()


def _title_from(caption: str) -> str:
    first = ""
    for line in caption.split("\n"):
        line = line.strip(" -•·|")
        if len(line) >= 12:
            first = line
            break
    first = first or caption.replace("\n", " ")
    return first[:150].rstrip()


def _posts_for(handle: str, kind: str, now: float) -> List[NewsItem]:
    data = _discover(handle)
    media = (data.get("business_discovery") or {}).get("media", {}).get("data", [])
    items = []
    for m in media:
        ts = _ts(m.get("timestamp", ""))
        if not ts or now - ts > MAX_AGE_HOURS * 3600:
            continue
        caption = _clean_caption(m.get("caption", ""))
        if len(caption) < MIN_CAPTION_CHARS:
            continue  # a poster with no text tells us nothing we can verify
        link = m.get("permalink", "")
        if not link:
            continue
        image = m.get("media_url") if m.get("media_type") != "VIDEO" else m.get("thumbnail_url", "")
        it = NewsItem(title=_title_from(caption), link=link, summary=caption[:900],
                      source=f"@{handle}", published_ts=ts)
        it.official = True
        it.official_kind = kind
        it.image_url = image or ""
        it.caption_text = caption
        items.append(it)
    return items


def fetch_posts() -> List[NewsItem]:
    """Latest posts from every watched page (best effort; failures are recorded in LAST_STATS / ERRORS)."""
    ERRORS.clear()
    LAST_STATS.clear()
    watch = load_watchlist()
    if not (config.FB_PAGE_ACCESS_TOKEN and config.IG_BUSINESS_ACCOUNT_ID and watch):
        return []
    now, items, failed, ok = time.time(), [], [], 0
    for handle, kind in watch:
        try:
            items.extend(_posts_for(handle, kind, now))
            ok += 1
        except Exception as e:
            msg = _error_text(e)
            failed.append(handle)
            print(f"  [IG] @{handle} skipped ({msg})")
            if msg.startswith("190") or msg.startswith("102"):
                ERRORS.append(f"Instagram token problem ({msg}) - the Instagram watchlist could not be read.")
                break
            if msg.startswith("4:") or msg.startswith("17:") or msg.startswith("32:"):
                ERRORS.append("Instagram rate limit reached; the rest of the watchlist was skipped this run.")
                break
        time.sleep(0.3)
    LAST_STATS.update({"ok": ok, "failed": failed, "posts": len(items), "total": len(watch)})
    print(f"  [IG] {ok}/{len(watch)} pages read, {len(items)} fresh captioned posts")
    return items


def self_test():
    watch = load_watchlist()
    if not watch:
        print("watchlist.txt has no handles yet.")
        return 1
    if not (config.FB_PAGE_ACCESS_TOKEN and config.IG_BUSINESS_ACCOUNT_ID):
        print("FB_PAGE_ACCESS_TOKEN / IG_BUSINESS_ACCOUNT_ID are not set.")
        return 1
    lines, now = [], time.time()
    for handle, kind in watch:
        try:
            data = _discover(handle)
            media = (data.get("business_discovery") or {}).get("media", {}).get("data", [])
            newest = max((_ts(m.get("timestamp", "")) for m in media), default=0)
            age = f"latest post {max(0, (now - newest) / 3600):.0f}h ago" if newest else "no posts returned"
            lines.append(f"✅ @{handle} ({kind}) - {age}")
        except Exception as e:
            lines.append(f"❌ @{handle} - {_error_text(e)}")
        time.sleep(0.3)
    good = sum(l.startswith("✅") for l in lines)
    report = f"Instagram watchlist check: {good}/{len(lines)} pages readable\n\n" + "\n".join(lines)
    if good < len(lines):
        report += ("\n\n❌ pages are usually personal (non-business) accounts, private pages, or a typo in the handle. "
                   "Business discovery can only read public Business/Creator accounts.")
    print(report)
    try:
        import notify_telegram
        if notify_telegram.is_configured():
            notify_telegram.send_text(report[:3900])
    except Exception as e:
        print("Telegram not sent:", e)
    return 0


if __name__ == "__main__":
    sys.exit(self_test())
