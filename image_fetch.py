"""
Looks up the lead image (og:image) of a news article so a story can be shown
with the picture the publisher used (often a poster or still).

NOTE: these images are the publishers' property. Using them on your page carries
copyright risk. Switch this off with USE_ARTICLE_IMAGES=0 (see config.py).

Best effort only: if anything fails, the caller falls back to the text card.
"""

import base64
import calendar
import html as _html
import io
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleGrab/1.0 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BAD_URL_WORDS = ("logo", "favicon", "placeholder", "default", "avatar", "sprite", "blank")
MIN_WIDTH, MIN_HEIGHT = 500, 400
MAX_BYTES = 8_000_000

_META_RES = [
    re.compile(r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]*content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', re.I),
    re.compile(r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]*content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*name=["\']twitter:image["\']', re.I),
]


def _get(url: str, limit: int, timeout: int = 12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.geturl(), resp.read(limit)


def resolve_article_url(link: str):
    """Google News links are wrappers. Returns the publisher URL, or None."""
    host = urlparse(link).netloc
    if "news.google.com" not in host:
        return link
    # older wrapper links carry the publisher URL inside the base64 id
    m = re.search(r"/articles/([A-Za-z0-9_-]+)", link)
    if m:
        try:
            raw = base64.urlsafe_b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4))
            found = re.search(rb"https?://[\x21-\x7e]+", raw)
            if found:
                return found.group(0).decode("ascii", "ignore")
        except Exception:
            pass
    # current wrapper links (CBMi...) are decoded through Google's own page + batchexecute endpoint
    decoded = _decode_google_news(link)
    if decoded:
        return decoded
    # otherwise see if Google redirects us straight to the publisher
    try:
        final_url, _ = _get(link, 2000)
        if "google." not in urlparse(final_url).netloc:
            return final_url
    except Exception:
        pass
    return None


def _decode_google_news(link: str):
    """Publisher URL behind a news.google.com/rss/articles/<id> link, or None (best effort)."""
    try:
        art_id = urlparse(link).path.rstrip("/").rsplit("/", 1)[-1]
        if not art_id:
            return None
        _, raw = _get(f"https://news.google.com/rss/articles/{art_id}", 300_000)
        page = raw.decode("utf-8", "ignore")
        sg = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sg and ts):
            return None
        inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
                 f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{art_id}",{ts.group(1)},"{sg.group(1)}"]')
        body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner, None, "generic"]]]))
        req = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body.encode("utf-8"), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8", "ignore")
        payload = json.loads(text.split("\n\n", 1)[1])
        url = json.loads(payload[0][2])[1]
        return url if str(url).startswith("http") else None
    except Exception as e:
        print(f"  [page] could not decode the Google News link ({type(e).__name__})")
        return None


def _find_image_url(page_url: str, html_bytes: bytes):
    html = html_bytes.decode("utf-8", "ignore")
    for rx in _META_RES:
        m = rx.search(html)
        if m:
            url = urljoin(page_url, m.group(1).replace("&amp;", "&").strip())
            if url.startswith("http") and not any(w in url.lower() for w in BAD_URL_WORDS):
                return url
    return None


_PAGE_CACHE = {}


def _fetch_article(link: str):
    """(page_url, html_bytes) of the article behind a link, or None. Cached per link for this run."""
    if link in _PAGE_CACHE:
        return _PAGE_CACHE[link]
    result = None
    try:
        article_url = resolve_article_url(link)
        if article_url:
            result = _get(article_url, 600_000)
        else:
            print("  [page] could not open the article page (Google News link)")
    except Exception as e:
        print(f"  [page] could not read the article ({type(e).__name__})")
    _PAGE_CACHE[link] = result
    return result


def get_article_image(link: str, out_path: str) -> bool:
    """Saves the article's lead image to out_path. Returns True on success."""
    if not config.USE_ARTICLE_IMAGES:
        return False
    try:
        fetched = _fetch_article(link)
        if not fetched:
            return False
        image_url = _find_image_url(*fetched)
        if not image_url:
            print("  [image] no lead image found on the article page")
            return False
        return save_image_url(image_url, out_path)
    except Exception as e:
        print(f"  [image] not used ({type(e).__name__})")
        return False


def _meta_content(html_text: str, *names: str) -> str:
    import html as _h
    for name in names:
        for rx in (
            re.compile(r'<meta[^>]+(?:property|name)=["\']' + re.escape(name) + r'["\'][^>]*content=["\']([^"\']*)["\']', re.I),
            re.compile(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']' + re.escape(name) + r'["\']', re.I),
        ):
            m = rx.search(html_text)
            if m and m.group(1).strip():
                return _h.unescape(m.group(1)).strip()
    return ""


_DATE_META = ("article:published_time", "og:article:published_time", "article:published", "pubdate",
              "publishdate", "parsely-pub-date", "dc.date.issued", "date", "sailthru.date")


def _parse_time(value: str):
    """Epoch seconds from an ISO-ish date string, or None."""
    v = (value or "").strip()
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
        if not m:
            return None
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))  # no zone given: an Indian outlet
    return dt.timestamp()


def _published_ts(html_text: str):
    for name in _DATE_META:
        ts = _parse_time(_meta_content(html_text, name))
        if ts:
            return ts
    m = re.search(r'"datePublished"\s*:\s*"([^"]+)"', html_text) or \
        re.search(r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)["\']', html_text, re.I)
    return _parse_time(m.group(1)) if m else None


def _article_text(html_text: str, limit: int = 3500) -> str:
    """Readable body text: the paragraphs of the page (scripts, menus and footers removed)."""
    cleaned = re.sub(r"(?is)<(script|style|nav|footer|aside|noscript|form|header)[^>]*>.*?</\1>", " ", html_text)
    paras = []
    for m in re.finditer(r"(?is)<p[^>]*>(.*?)</p>", cleaned):
        t = re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
        if len(t) >= 45 and not re.search(r"(?i)^(also read|read more|follow us|subscribe|click here|advertisement)", t):
            paras.append(t)
    return " ".join(paras)[:limit]


def get_page_info(link: str) -> dict:
    """Title, description, lead-image URL, body text and publish time of a page
    (best effort; {} on failure)."""
    try:
        fetched = _fetch_article(link)
        if not fetched:
            return {}
        page_url, raw = fetched
        html_text = raw.decode("utf-8", "ignore")
        title = _meta_content(html_text, "og:title", "twitter:title")
        if not title:
            m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
            title = re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        return {
            "url": page_url,
            "title": title,
            "description": _meta_content(html_text, "og:description", "description", "twitter:description"),
            "image_url": _find_image_url(page_url, raw),
            "text": _article_text(html_text),
            "published_ts": _published_ts(html_text),
        }
    except Exception as e:
        print(f"  [page] could not read the link ({type(e).__name__})")
        return {}


def save_image_url(image_url: str, out_path: str) -> bool:
    """Downloads an image URL to out_path as JPEG (rejects tiny images)."""
    try:
        _, data = _get(image_url, MAX_BYTES)
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if im.width < MIN_WIDTH or im.height < MIN_HEIGHT:
            return False
        im.convert("RGB").save(out_path, "JPEG", quality=92)
        return True
    except Exception as e:
        print(f"  [image] not used ({type(e).__name__})")
        return False


_IMG_TAG_RE = re.compile(r"(?is)<img\b[^>]*>")
_SRC_RE = re.compile(r"""(?:data-src|data-lazy-src|src)=["']([^"']+)["']""", re.I)


def get_image_candidates(link: str, limit: int = 6) -> list:
    """Possible pictures on an article page: the share images (og/twitter) first, then large in-body images."""
    fetched = _fetch_article(link)
    if not fetched:
        return []
    page_url, raw = fetched
    html_text = raw.decode("utf-8", "ignore")
    urls = []

    def add(u):
        u = urljoin(page_url, _html.unescape(u).strip())
        low = u.lower()
        if (u.startswith("http") and not any(w in low for w in BAD_URL_WORDS)
                and not re.search(r"\.(svg|gif)(\?|$)", low) and u not in urls):
            urls.append(u)

    for rx in _META_RES:
        for m in rx.finditer(html_text):
            add(m.group(1))
    for tag in _IMG_TAG_RE.findall(html_text):
        w = re.search(r"""width=["']?(\d+)""", tag, re.I)
        if w and int(w.group(1)) < 300:
            continue
        m = _SRC_RE.search(tag)
        if m:
            add(m.group(1))
    return urls[:limit]


def fetch_thumbnail(url: str, width: int = 640):
    """JPEG bytes of the image at url scaled to `width` (None if it is missing or too small to use)."""
    try:
        _, data = _get(url, MAX_BYTES)
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if im.width < MIN_WIDTH or im.height < MIN_HEIGHT:
            return None
        im = im.convert("RGB")
        im.thumbnail((width, width * 2))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
        return buf.getvalue()
    except Exception:
        return None
