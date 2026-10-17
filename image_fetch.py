"""
Looks up the lead image (og:image) of a news article so a story can be shown
with the picture the publisher used (often a poster or still).

NOTE: these images are the publishers' property. Using them on your page carries
copyright risk. Switch this off with USE_ARTICLE_IMAGES=0 (see config.py).

Best effort only: if anything fails, the caller falls back to the text card.
"""

import base64
import io
import re
import urllib.request
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
    # otherwise see if Google redirects us straight to the publisher
    try:
        final_url, _ = _get(link, 2000)
        if "google." not in urlparse(final_url).netloc:
            return final_url
    except Exception:
        pass
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


def get_article_image(link: str, out_path: str) -> bool:
    """Saves the article's lead image to out_path. Returns True on success."""
    if not config.USE_ARTICLE_IMAGES:
        return False
    try:
        article_url = resolve_article_url(link)
        if not article_url:
            print("  [image] could not open the article page (Google News link)")
            return False
        page_url, html = _get(article_url, 400_000)
        image_url = _find_image_url(page_url, html)
        if not image_url:
            print("  [image] no lead image found on the article page")
            return False
        _, data = _get(image_url, MAX_BYTES)
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        if im.width < MIN_WIDTH or im.height < MIN_HEIGHT:
            print(f"  [image] too small ({im.width}x{im.height}), not used")
            return False
        im.convert("RGB").save(out_path, "JPEG", quality=92)
        return True
    except Exception as e:
        print(f"  [image] not used ({type(e).__name__})")
        return False
