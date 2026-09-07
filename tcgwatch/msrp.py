"""Reference MSRPs (USD) so a listing can be judged before you tap Buy.

Verified 2026-09-06 against manufacturer and big-box listings. Pokemon raised
packs from $3.99 to $4.49 in Dec 2022; Japan moved to ¥200/pack in May 2026 and
an English increase is expected but unconfirmed. Use per-product `msrp` in
config.yaml for special sets, which often carry their own price.
"""

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


def verdict(price: float | None, msrp: float | None, max_ratio: float) -> tuple[bool, str]:
    """Return (acceptable, label)."""
    if price is None:
        return True, "price unknown"
    if msrp is None:
        return True, f"${price:.2f} (no MSRP set)"
    ratio = price / msrp
    if ratio <= max_ratio:
        return True, f"${price:.2f} = MSRP ${msrp:.2f}" if abs(ratio - 1) < 0.02 else f"${price:.2f} ({ratio:.0%} of MSRP)"
    return False, f"INFLATED ${price:.2f} vs MSRP ${msrp:.2f} ({ratio:.0%})"
