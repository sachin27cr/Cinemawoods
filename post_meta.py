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


def _describe_error(code: int, body: str) -> str:
    """Readable Graph API error: message plus the code/subcode that tell you what to fix."""
    try:
        err = json.loads(body).get("error", {})
        parts = [err.get("error_user_msg") or err.get("message") or body[:200]]
        extra = ", ".join(f"{k} {err[k]}" for k in ("code", "error_subcode") if err.get(k))
        if extra:
            parts.append(f"({extra})")
        if err.get("code") in (190, 102) or err.get("type") == "OAuthException" and err.get("code") == 190:
            parts.append("- the Facebook/Instagram access token has expired or was revoked; create a new long-lived page token")
        return " ".join(parts)[:400]
    except Exception:
        return body[:300]


def _post(url: str, data: dict) -> dict:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Graph API error ({e.code}): {_describe_error(e.code, e.read().decode('utf-8', 'ignore'))}")


def _get(url: str, params: dict) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(full, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _urls(value) -> list:
    return [value] if isinstance(value, str) else [u for u in value if u]


def _clean_caption(caption: str, limit: int = 2200) -> str:
    """Instagram allows 2,200 characters and 30 hashtags."""
    tags = [t for t in caption.split() if t.startswith("#")]
    if len(tags) > 30:
        for t in tags[30:]:
            caption = caption.replace(t, "")
    return caption.strip()[:limit]


def post_to_facebook(image_public_url, caption: str, local_path: str = "") -> str:
    """Posts a photo to the FB Page. Tries each public URL, then uploads the file itself. Returns the post id."""
    errors = []
    for url_ in _urls(image_public_url):
        try:
            result = _post(f"{GRAPH_BASE}/{config.FB_PAGE_ID}/photos", {
                "url": url_, "caption": caption, "access_token": config.FB_PAGE_ACCESS_TOKEN})
            return result.get("post_id") or result.get("id")
        except Exception as e:
            errors.append(str(e))
    if local_path:
        try:
            return _facebook_upload(local_path, caption)
        except Exception as e:
            errors.append(f"file upload: {e}")
    raise RuntimeError(" | ".join(errors)[:500])


def _facebook_upload(local_path: str, caption: str) -> str:
    """Sends the picture bytes straight to Facebook (does not depend on any public URL)."""
    import uuid
    boundary = "----cw" + uuid.uuid4().hex
    parts = []
    for name, value in (("caption", caption), ("access_token", config.FB_PAGE_ACCESS_TOKEN), ("published", "true")):
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n').encode()
                     + value.encode("utf-8") + b"\r\n")
    with open(local_path, "rb") as f:
        data = f.read()
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="source"; filename="post.jpg"\r\n'
                  'Content-Type: image/jpeg\r\n\r\n').encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"{GRAPH_BASE}/{config.FB_PAGE_ID}/photos", data=b"".join(parts), method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Graph API error ({e.code}): {_describe_error(e.code, e.read().decode('utf-8', 'ignore'))}")
    return result.get("post_id") or result.get("id")


def _wait_until_ready(creation_id: str, tries: int = 14) -> None:
    """Polls the Instagram media container until Meta has fetched the image. Raises with Instagram's own
    reason if it failed or is still not ready."""
    last, detail = None, ""
    for _ in range(tries):
        try:
            res = _get(f"{GRAPH_BASE}/{creation_id}", {
                "fields": "status_code,status",
                "access_token": config.FB_PAGE_ACCESS_TOKEN,
            })
            last, detail = res.get("status_code"), res.get("status", "")
        except Exception:
            last = None
        if last == "FINISHED":
            return
        if last in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not fetch/process the image ({last}: {detail})")
        time.sleep(4)
    raise RuntimeError(f"Instagram did not finish processing the image in time (status {last})")


def _publish_container(creation_id: str) -> str:
    """media_publish, retried while Instagram says the media is not ready yet."""
    last = None
    for attempt in range(6):
        try:
            result = _post(f"{GRAPH_BASE}/{config.IG_BUSINESS_ACCOUNT_ID}/media_publish", {
                "creation_id": creation_id, "access_token": config.FB_PAGE_ACCESS_TOKEN})
            return result.get("id")
        except RuntimeError as e:
            last = e
            msg = str(e).lower()
            if any(w in msg for w in ("not ready", "not available", "2207027", "9007", "processing")):
                time.sleep(5 * (attempt + 1))
                continue
            raise
    raise last


def post_to_instagram(image_public_url, caption: str) -> str:
    """Two-step IG posting (container, then publish). `image_public_url` may be a list of addresses for the same
    picture; each is tried (twice) until Instagram manages to fetch one."""
    caption = _clean_caption(caption)
    errors = []
    for url_ in _urls(image_public_url):
        for attempt in range(2):
            try:
                container = _post(f"{GRAPH_BASE}/{config.IG_BUSINESS_ACCOUNT_ID}/media", {
                    "image_url": url_, "caption": caption, "access_token": config.FB_PAGE_ACCESS_TOKEN})
                creation_id = container.get("id")
                if not creation_id:
                    raise RuntimeError(f"IG container creation failed: {container}")
                _wait_until_ready(creation_id)
                return _publish_container(creation_id)
            except Exception as e:
                msg = str(e)
                if msg not in errors:
                    errors.append(msg)
                print(f"  [IG] attempt failed via {url_.split('/')[2]}: {msg[:200]}")
                if any(w in msg for w in ("(code 190", "(code 10,", "(code 200", "access token", "permission")):
                    raise RuntimeError(msg)  # a token/permission problem: retrying other addresses cannot help
                time.sleep(4)
    raise RuntimeError(" | ".join(errors)[:600])


def post_everywhere(image_public_url, caption: str, local_path: str = "") -> dict:
    """Posts to both platforms; returns whatever succeeded, logs what failed
    rather than raising, so one platform's failure doesn't block the other."""
    results = {}

    try:
        results["facebook_post_id"] = post_to_facebook(image_public_url, caption, local_path)
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
