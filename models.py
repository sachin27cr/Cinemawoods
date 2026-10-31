"""Shared data type for a news story (kept dependency-free so every workflow can import it)."""

from dataclasses import dataclass


@dataclass
class NewsItem:
    title: str
    link: str
    summary: str
    source: str
    published_ts: float = 0.0
    score: float = 0.0
    coverage: int = 1  # number of different outlets covering the same story
    official: bool = False  # came from an Instagram page on the watchlist
    official_kind: str = ""  # "official" (actor/producer page) or "media" (news outlet page)
    image_url: str = ""  # the post's own picture (watchlist posts)
    caption_text: str = ""  # the post's full caption (watchlist posts)
    card_title: str = ""  # clean headline for the picture (written by Gemini; set later)
