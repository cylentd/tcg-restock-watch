"""tcg-restock-watch entry point.

  python watch.py                    run forever
  python watch.py --once             check everything once and print
  python watch.py --test             send a test push to your phone
  python watch.py --login            open the watcher's Chrome so you can sign in to each store
  python watch.py --lookup target 93954446   print name/price/status for an ID
"""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from tcgwatch import config as config_mod
from tcgwatch import notify
from tcgwatch.browser import Browser
from tcgwatch.retailers import PRODUCT_URLS, bestbuy, gamestop, target, walmart
from tcgwatch.watcher import Watcher

ROOT = Path(__file__).resolve().parent

LOGIN_URLS = [
    "https://www.target.com/account",
    "https://www.bestbuy.com/identity/signin",
    "https://www.walmart.com/account/login",
]


def setup_logging(data_dir: Path, verbose: bool) -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    fh = RotatingFileHandler(data_dir / "watch.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--once", action="store_true", help="single pass, print and save results, no alerts")
    ap.add_argument("--only", metavar="RETAILER", help="with --once: poll just this retailer (target, bestbuy, walmart, gamestop)")
    ap.add_argument("--test", action="store_true", help="send a test notification")
    ap.add_argument("--login", action="store_true", help="open the watcher browser on each store's sign-in page")
    ap.add_argument("--lookup", nargs=2, metavar=("RETAILER", "ID"), help="print name/price/status for a product ID")
    ap.add_argument("--discover", metavar="KEYWORD", help="search Target for products it sells itself; prints config entries")
    ap.add_argument("--site", action="store_true", help="build the static status page into site/")
    ap.add_argument("--deploy", action="store_true", help="with --site: deploy site/ to Vercel (npx vercel --prod)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    cfg = config_mod.load(args.config)
    setup_logging(cfg.data_dir, args.verbose)
    log = logging.getLogger("tcgwatch")

    if args.test:
        if not cfg.discord_webhook and not cfg.ntfy_topic:
            print("Set discord_webhook (or ntfy_topic) in config.yaml first.")
            return 2
        ok = notify.push(cfg, "tcg-restock-watch", "Test alert. Tap Open to confirm the link works.",
                         "https://www.target.com/c/pokemon-trading-cards", "urgent", "white_check_mark")
        print("sent" if ok else "FAILED (see log)")
        return 0 if ok else 1

    if args.login:
        b = Browser(cfg.chrome_path, cfg.profile_dir, timeout=120)
        b.open(LOGIN_URLS[0])
        for url in LOGIN_URLS[1:]:
            # `tab new` with no URL blocks; giving it the URL opens and navigates in one step.
            b.run("tab", "new", url, check=False)
        print("Sign in to each store in the Chrome window that opened, then close it. Logins persist in", cfg.profile_dir)
        return 0

    if args.discover:
        hits = target.discover(cfg, args.discover)
        print(f"# {len(hits)} products sold by Target for '{args.discover}' (marketplace excluded)")
        for h in sorted(hits, key=lambda x: x["name"]):
            print(f"  - retailer: target\n    id: \"{h['id']}\"\n    name: \"{h['name']}\"\n    msrp: {h['price'] or 0}   # {h['status']}")
        return 0

    if args.site:
        from tcgwatch import site as site_mod

        out = site_mod.build(cfg, ROOT / "site")
        print("built", out)
        if args.deploy:
            import subprocess

            subprocess.run(f'npx -y vercel --prod --yes --cwd "{ROOT / "site"}"', shell=True, check=False)
        return 0

    if args.lookup:
        retailer, pid = args.lookup[0].lower(), args.lookup[1]
        if retailer == "target":
            info = target.lookup(cfg, pid)
        elif retailer == "bestbuy":
            info = bestbuy.lookup(cfg, pid)
        elif retailer == "walmart":
            info = walmart.lookup(cfg, pid, Browser(cfg.chrome_path, cfg.profile_dir))
        elif retailer == "gamestop":
            info = gamestop.lookup(cfg, pid)
        else:
            print("lookup supports target, bestbuy, walmart, gamestop; for pokemoncenter paste the product URL into config.yaml")
            return 2
        for k, v in info.items():
            print(f"{k:7} {v}")
        marketplace = "marketplace" in str(info.get("seller", "")).lower() or "marketplace" in str(info.get("status", "")).lower()
        msrp_line = "0  # marketplace price shown above is NOT MSRP; set the real one" if marketplace else str(info.get("price") or 0)
        print(f"\nconfig.yaml entry:\n  - retailer: {retailer}\n    id: \"{pid}\"\n    name: \"{info.get('name')}\"\n    msrp: {msrp_line}")
        return 0

    if not cfg.products and not cfg.feeds:
        print("config.yaml has no products or feeds. Add some (see README) or run --lookup to find IDs.")
        return 2

    w = Watcher(cfg)
    if args.once:
        results = w.run_retailer(args.only.lower()) if args.only else w.run_once()
        for res in results:
            w.record(res)
            price = f"${res.price:.2f}" if res.price else "-"
            print(f"{res.product.retailer:14} {res.product.name[:44]:44} in_stock={res.in_stock!s:5} {price:9} {res.note}")
        if not args.only:
            for h in w.run_feeds(alert=False):
                print(f"{'r/' + h['subreddit']:14} {h['title'][:80]}")
        return 0

    try:
        w.run_forever()
    except KeyboardInterrupt:
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
