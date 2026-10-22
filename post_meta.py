"""
Posts to a Facebook Page and an Instagram Business account via the Meta
Graph API.

Instagram's API needs the image at a public URL (Meta's servers fetch it) and
only accepts JPEG. The bot serves cards from this public repo through
raw.githubusercontent.com.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

import config

GRAPH_BASE = f"https://graph.facebook.com/{config.GRAPH_API_VERSION}"


def _post(url: str, data: dict) -> dict:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", "ignore")[:400]
        raise RuntimeError(f"Graph API error ({e.code}): {error_body}")


def _get(url: str, params: dict) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(full, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_to_facebook(image_public_url: str, caption: str) -> str:
    """Posts a photo to the FB Page. Returns the post id."""
    url = f"{GRAPH_BASE}/{config.FB_PAGE_ID}/photos"
    data = {
        "url": image_public_url,
        "caption": caption,
        "access_token": config.FB_PAGE_ACCESS_TOKEN,
    }
    result = _post(url, data)
    return result.get("post_id") or result.get("id")


def _wait_until_ready(creation_id: str) -> None:
    """Polls the Instagram media container until Meta has fetched the image."""
    for _ in range(12):
        try:
            status = _get(f"{GRAPH_BASE}/{creation_id}", {
                "fields": "status_code",
                "access_token": config.FB_PAGE_ACCESS_TOKEN,
            }).get("status_code")
        except Exception:
            status = None
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError("Instagram could not process the image (container status ERROR)")
        time.sleep(5)


def post_to_instagram(image_public_url: str, caption: str) -> str:
    """Two-step IG posting: create media container, then publish it."""
    container_url = f"{GRAPH_BASE}/{config.IG_BUSINESS_ACCOUNT_ID}/media"
    container_result = _post(container_url, {
        "image_url": image_public_url,
        "caption": caption,
        "access_token": config.FB_PAGE_ACCESS_TOKEN,
    })
    creation_id = container_result.get("id")
    if not creation_id:
        raise RuntimeError(f"IG container creation failed: {container_result}")

    _wait_until_ready(creation_id)

    publish_url = f"{GRAPH_BASE}/{config.IG_BUSINESS_ACCOUNT_ID}/media_publish"
    publish_result = _post(publish_url, {
        "creation_id": creation_id,
        "access_token": config.FB_PAGE_ACCESS_TOKEN,
    })
    return publish_result.get("id")


def post_everywhere(image_public_url: str, caption: str) -> dict:
    """Posts to both platforms; returns whatever succeeded, logs what failed
    rather than raising, so one platform's failure doesn't block the other."""
    results = {}

    try:
        results["facebook_post_id"] = post_to_facebook(image_public_url, caption)
        print(f"[OK] Posted to Facebook: {results['facebook_post_id']}")
    except Exception as e:
        print(f"[ERROR] Facebook post failed: {e}")
        results["facebook_error"] = str(e)

    try:
        results["instagram_post_id"] = post_to_instagram(image_public_url, caption)
        print(f"[OK] Posted to Instagram: {results['instagram_post_id']}")
    except Exception as e:
        print(f"[ERROR] Instagram post failed: {e}")
        results["instagram_error"] = str(e)

    return results


# ----------------------------------------------------------------- Reels

def _wait_reel_ready(creation_id: str, tries: int = 40) -> None:
    """Instagram needs a while to fetch and process a video."""
    last = None
    for _ in range(tries):
        try:
            res = _get(f"{GRAPH_BASE}/{creation_id}", {
                "fields": "status_code,status",
                "access_token": config.FB_PAGE_ACCESS_TOKEN,
            })
            last = res.get("status_code")
        except Exception:
            last = None
        if last == "FINISHED":
            return
        if last in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process the Reel video (status {last}: {res.get('status', '')})")
        time.sleep(6)
    raise RuntimeError(f"Instagram is still processing the Reel (last status: {last}); tap Post Reel again in a minute")


def post_reel_to_instagram(video_public_url: str, caption: str) -> str:
    """REELS container from a public video URL, wait until FINISHED, then publish."""
    result = _post(f"{GRAPH_BASE}/{config.IG_BUSINESS_ACCOUNT_ID}/media", {
        "media_type": "REELS",
        "video_url": video_public_url,
        "caption": caption[:2200],
        "share_to_feed": "true",
        "access_token": config.FB_PAGE_ACCESS_TOKEN,
    })
    creation_id = result.get("id")
    if not creation_id:
        raise RuntimeError(f"IG Reel container creation failed: {result}")
    _wait_reel_ready(creation_id)
    published = _post(f"{GRAPH_BASE}/{config.IG_BUSINESS_ACCOUNT_ID}/media_publish", {
        "creation_id": creation_id,
        "access_token": config.FB_PAGE_ACCESS_TOKEN,
    })
    return published.get("id")


def post_reel_to_facebook(video_public_url: str, description: str) -> str:
    """Facebook Page Reel: start -> upload (Facebook pulls the file from our URL) -> finish."""
    start = _post(f"{GRAPH_BASE}/{config.FB_PAGE_ID}/video_reels", {
        "upload_phase": "start",
        "access_token": config.FB_PAGE_ACCESS_TOKEN,
    })
    video_id, upload_url = start.get("video_id"), start.get("upload_url")
    if not video_id or not upload_url:
        raise RuntimeError(f"Facebook Reel start failed: {start}")

    req = urllib.request.Request(upload_url, data=b"", method="POST", headers={
        "Authorization": f"OAuth {config.FB_PAGE_ACCESS_TOKEN}",
        "file_url": video_public_url,
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            up = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Facebook Reel upload error ({e.code}): {e.read().decode('utf-8', 'ignore')[:300]}")
    if up.get("success") is False:
        raise RuntimeError(f"Facebook Reel upload failed: {up}")

    done = _post(f"{GRAPH_BASE}/{config.FB_PAGE_ID}/video_reels", {
        "upload_phase": "finish",
        "video_id": video_id,
        "video_state": "PUBLISHED",
        "description": description[:2200],
        "access_token": config.FB_PAGE_ACCESS_TOKEN,
    })
    if done.get("success") is False:
        raise RuntimeError(f"Facebook Reel publish failed: {done}")
    return video_id
