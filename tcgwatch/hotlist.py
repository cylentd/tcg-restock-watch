"""Hot-item rule: which products are worth tracking. Stated in README "Hot items".

config.yaml records no product type, only a name, so the type is read from the name the same way
lifecycle.product_kind does. Pure: no I/O.
"""

from __future__ import annotations

import re

# Product types worth tracking (David, 2026-10-09: loose packs are not worth it).
HOT_PATTERN = re.compile(
    r"booster bundle"
    r"|elite trainer|\betb\b"
    r"|booster box|booster display"
    r"|premium collection"          # also matches super-premium and ultra-premium
    r"|special collection"
    r"|illustration box"
    r"|premium card collection",    # One Piece
    re.I,
)

# Types that are never hot, even when a hot phrase also appears (e.g. "Premium Collection Tin").
NOT_HOT_PATTERN = re.compile(
    r"double pack|blister|\btins?\b|\bdecks?\b|booster pack|sleeved booster",
    re.I,
)


def is_hot(name: str, override: bool | None = None) -> bool:
    """True when the product is hot; see README "Hot items".

    `override` is the product's `hot:` value from config.yaml: True or False wins over the name, and
    None (no `hot:` set) leaves the decision to the name rule.
    """
    if override is not None:
        return override
    if NOT_HOT_PATTERN.search(name):
        return False
    return HOT_PATTERN.search(name) is not None
