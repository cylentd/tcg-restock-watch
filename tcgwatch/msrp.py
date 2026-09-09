"""Reference MSRPs (USD) so a listing can be judged before you tap Buy.

Verified 2026-09-06 against manufacturer and big-box listings. Pokemon raised
packs from $3.99 to $4.49 in Dec 2022; Japan moved to ¥200/pack in May 2026 and
an English increase is expected but unconfirmed. Use per-product `msrp` in
config.yaml for special sets, which often carry their own price.
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

MSRP = {
    "pokemon": {
        "booster_pack": 4.49,
        "booster_bundle": 26.94,       # 6 packs; special sets list higher (Prismatic Evolutions bundle: 31.99)
        "elite_trainer_box": 49.99,
        "booster_box": 161.64,         # 36 packs at 4.49
        "ultra_premium_collection": 119.99,
        "battle_deck": 16.99,
    },
    "onepiece": {
        "booster_pack": 4.99,
        "booster_box": 119.76,         # 24 packs at 4.99
        "starter_deck": 11.99,
        "double_pack_set": 24.99,      # unverified as official MSRP
    },
}


@functools.lru_cache(maxsize=1)
def _shipping_cfg() -> dict:
    """Load the `shipping:` block from config.yaml (see that file for sourcing/confidence notes).

    Cached for the life of the process; config.yaml isn't hot-reloaded here (the rest of the
    watcher reads it once at startup too), so this matches existing behavior.
    """
    path = Path(__file__).resolve().parent.parent / "config.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError:
        return {}
    return raw.get("shipping") or {}


def landed_price(price: float, retailer: str, shipping_cfg: dict) -> float:
    """Item price plus the flat shipping fee, unless price already clears the free-shipping
    threshold for that retailer. `shipping_cfg` is the `shipping:` block from config.yaml,
    keyed by retailer (see config.yaml for which numbers are verified vs. estimated)."""
    entry = (shipping_cfg or {}).get(retailer.lower(), {}) or {}
    free_over = float(entry.get("free_over") or 0)
    flat_fee = float(entry.get("flat_fee") or 0)
    if free_over and price >= free_over:
        return price
    return price + flat_fee


def verdict(price: float | None, msrp: float | None, max_ratio: float, retailer: str | None = None) -> tuple[bool, str]:
    """Return (acceptable, label). When `retailer` is given, the accept/reject decision is made
    on landed price (item + likely shipping, via `landed_price()`/config.yaml's `shipping:`
    block) while the label still shows the raw item price, calling out shipping separately when
    it's what pushed the item over MSRP. Omit `retailer` to fall back to the old raw-price-only
    behavior."""
    if price is None:
        return True, "price unknown"
    if msrp is None:
        return True, f"${price:.2f} (no MSRP set)"
    landed = landed_price(price, retailer, _shipping_cfg()) if retailer else price
    ship_fee = landed - price
    ratio = landed / msrp
    if ratio <= max_ratio:
        if ship_fee > 0.005:
            return True, f"${price:.2f} + ${ship_fee:.2f} shipping = ${landed:.2f} ({ratio:.0%} of MSRP)"
        return True, f"${price:.2f} = MSRP ${msrp:.2f}" if abs(ratio - 1) < 0.02 else f"${price:.2f} ({ratio:.0%} of MSRP)"
    if ship_fee > 0.005:
        return False, f"${price:.2f} + ${ship_fee:.2f} shipping = INFLATED ${landed:.2f} vs MSRP ${msrp:.2f} ({ratio:.0%})"
    return False, f"INFLATED ${price:.2f} vs MSRP ${msrp:.2f} ({ratio:.0%})"
