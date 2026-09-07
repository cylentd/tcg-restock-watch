"""Push alerts to a phone: Discord webhook (primary) and/or ntfy.sh."""

from __future__ import annotations

import logging

import requests

log = logging.getLogger("tcgwatch.notify")

COLORS = {"urgent": 0x2ECC71, "high": 0xF1C40F, "default": 0x95A5A6}


def discord(webhook: str, title: str, body: str, url: str | None = None, priority: str = "high",
            mention_everyone: bool = True) -> bool:
    """Post an embed to a Discord channel webhook. @everyone on urgent so the phone buzzes."""
    content = "@everyone" if (priority == "urgent" and mention_everyone) else ""
    embed = {"title": title[:256], "description": body[:4000], "color": COLORS.get(priority, COLORS["default"])}
    if url:
        embed["url"] = url
        embed["description"] += f"\n\n[Open]({url})"
    try:
        r = requests.post(webhook, json={"content": content, "embeds": [embed]}, timeout=15)
        if r.status_code == 429:
            log.warning("discord webhook rate limited; retry after %s", r.headers.get("Retry-After"))
        elif not r.ok:
            log.warning("discord webhook returned %s: %s", r.status_code, r.text[:200])
        return r.ok
    except requests.RequestException as e:
        log.warning("discord push failed: %s", e)
        return False


def ntfy(
    server: str,
    topic: str,
    title: str,
    body: str,
    url: str | None = None,
    priority: str = "high",
    tags: str = "shopping_cart",
) -> bool:
    headers = {
        "Title": title.encode("ascii", "ignore").decode(),
        "Priority": priority,
        "Tags": tags,
    }
    if url:
        headers["Click"] = url
        headers["Actions"] = f"view, Open, {url}, clear=true"
    try:
        r = requests.post(f"{server}/{topic}", data=body.encode("utf-8"), headers=headers, timeout=15)
        if not r.ok:
            log.warning("ntfy returned %s: %s", r.status_code, r.text[:200])
        return r.ok
    except requests.RequestException as e:
        log.warning("ntfy push failed: %s", e)
        return False


def push(cfg, title: str, body: str, url: str | None = None, priority: str = "high",
         tags: str = "shopping_cart") -> bool:
    """Send to every configured channel. True if at least one accepted it."""
    ok = False
    if cfg.discord_webhook:
        ok = discord(cfg.discord_webhook, title, body, url, priority, cfg.discord_mention_everyone) or ok
    if cfg.ntfy_topic:
        ok = ntfy(cfg.ntfy_server, cfg.ntfy_topic, title, body, url, priority, tags) or ok
    if not cfg.discord_webhook and not cfg.ntfy_topic:
        log.warning("no notification channel configured (discord_webhook or ntfy_topic)")
    return ok
