"""Group the same product across retailers by a normalized name."""

from __future__ import annotations

import re

_STRIP = re.compile(
    r"\b(pok[eé]mon|trading card game|trading card games|tcg|one piece|card game|bandai|scarlet & violet|"
    r"scarlet and violet|s&v|riftbound|league of legends|riot games|the|verify|bundle or box)\b",
    re.I,
)
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACES = re.compile(r"\s+")


def game_of(name: str) -> str:
    n = name.lower()
    if "one piece" in n or re.search(r"\b(op|st|eb|ib)-?\d{2}\b", n):
        return "One Piece"
    if "riftbound" in n or "league of legends" in n:
        return "Riftbound"
    return "Pokemon"


def normalize(name: str) -> str:
    n = _STRIP.sub(" ", name.lower())
    n = _PUNCT.sub(" ", n)
    return _SPACES.sub(" ", n).strip()


def group_key(name: str) -> str:
    return f"{game_of(name)}|{normalize(name)}"


def market_query(name: str) -> str:
    """What to type into TCGplayer for this product."""
    n = re.sub(r"\((bundle or box, )?verify\)", "", name, flags=re.I)
    n = re.sub(r"^\s*(pok[eé]mon|one piece|riftbound)\s+", "", n, flags=re.I)
    return _SPACES.sub(" ", n).strip()
