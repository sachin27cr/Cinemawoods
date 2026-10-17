"""
Tiny JSON store for drafts that are waiting for your Approve/Reject tap.
The file (pending.json) lives in the repo so both workflows can share it.
"""

import hashlib
import json
import os
import time

PENDING_PATH = os.environ.get("PENDING_PATH", "pending.json")
KEEP_DAYS = 14


def make_id(link: str) -> str:
    """Short, stable id for a story (used in file names and button data)."""
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:10]


def load() -> dict:
    try:
        with open(PENDING_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", {})
    return data


def save(data: dict) -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    data["items"] = {
        k: v for k, v in data["items"].items() if v.get("created_ts", 0) >= cutoff
    }
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
