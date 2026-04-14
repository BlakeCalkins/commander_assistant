"""Shared constants for the Commander deck-building skeleton."""

from __future__ import annotations

CATEGORY_ORDER = [
    "synergy",
    "ramp",
    "draw",
    "removal",
    "wipe",
    "protection",
    "recursion",
]

ALL_DECK_CATEGORIES = ["commander", *CATEGORY_ORDER, "lands", "other"]

BUDGET_TIER_LABELS = {
    "low": "Low (~$100 total)",
    "medium": "Medium (~$100-$500 total)",
    "high": "High ($500+)",
    "none": "No limit",
}

BUDGET_PRICE_FILTERS = {
    "low": "usd<=1.00",
    "medium": "usd<=10.00",
    "high": "usd<=100.00",
    "none": None,
}

COLOR_ORDER = ["W", "U", "B", "R", "G"]
