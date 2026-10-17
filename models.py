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
    card_title: str = ""  # clean headline for the picture (written by Gemini; set later)
