"""
Posts to a Facebook Page and an Instagram Business account via the Meta
Graph API.

IMPORTANT: Instagram's API requires the image to be reachable at a public
URL (Meta's servers fetch it) — it can't receive raw bytes from a GitHub
Actions runner directly. See README "Image Hosting" section for the two
supported options (GitHub raw content or a free static host).
"""

import json
import time
import urllib.request
import urllib.parse
import urllib.error

import config

GRAPH_BASE = f"https://graph.facebook.com/{config.GRAPH_API_VERSION}"


def _post(url: str, data: dict) -> dict:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        raise RuntimeError(f"Graph API error ({e.code}): {error_body}")


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


def post_to_instagram(image_public_url: str, caption: str) -> str:
    """Two-step IG posting: create media container, then publish it."""
    # Step 1: create container
    container_url = f"{GRAPH_BASE}/{config.IG_BUSINESS_ACCOUNT_ID}/media"
    container_data = {
        "image_url": image_public_url,
        "caption": caption,
        "access_token": config.FB_PAGE_ACCESS_TOKEN,  # IG posting uses the linked Page's token
    }
    container_result = _post(container_url, container_data)
    creation_id = container_result.get("id")
    if not creation_id:
        raise RuntimeError(f"IG container creation failed: {container_result}")

    # brief wait for Meta to fetch/process the image
    time.sleep(3)

    # Step 2: publish container
    publish_url = f"{GRAPH_BASE}/{config.IG_BUSINESS_ACCOUNT_ID}/media_publish"
    publish_data = {
        "creation_id": creation_id,
        "access_token": config.FB_PAGE_ACCESS_TOKEN,
    }
    publish_result = _post(publish_url, publish_data)
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
