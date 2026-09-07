"""Product thumbnails for the status page: download once, convert to WebP, cache by URL hash."""

from __future__ import annotations

import hashlib
import io
import logging
import time
from pathlib import Path

import requests
from PIL import Image

log = logging.getLogger("tcgwatch.images")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
MAX_EDGE = 400
QUALITY = 82
_last_fetch = 0.0


def knock_out_background(img: Image.Image, mode: str = "dark", thresh: int | None = None) -> Image.Image:
    """Make the edge-connected background transparent.

    mode="dark": near-black background (mascot art). mode="light": near-white background
    (retailer packshots). Only regions touching the image border are removed, so a white
    box or a black outline inside the product survives. The cut edge is feathered.
    """
    import numpy as np
    from scipy import ndimage

    arr = np.array(img.convert("RGBA"))
    rgb = arr[..., :3].astype(np.int16)
    if mode == "dark":
        t = 48 if thresh is None else thresh
        mask = rgb.max(axis=2) < t
        dist = (rgb.max(axis=2) - t).astype(np.float32)  # how far past the cut a pixel is
    else:
        t = 232 if thresh is None else thresh
        mask = (rgb.min(axis=2) > t) & ((rgb.max(axis=2) - rgb.min(axis=2)) < 18)
        dist = (t - rgb.min(axis=2)).astype(np.float32)
    labels, n = ndimage.label(mask)
    if n == 0:
        return img
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border.discard(0)
    bg = np.isin(labels, list(border))
    if bg.mean() < 0.02:
        return img  # background is not actually flat; leave it alone
    alpha = arr[..., 3].astype(np.float32)
    alpha[bg] = 0
    edge = ndimage.binary_dilation(bg, iterations=2) & ~bg
    alpha[edge] = np.minimum(alpha[edge], np.clip(dist[edge] / 50.0, 0.2, 1.0) * 255)
    arr[..., 3] = alpha.astype(np.uint8)
    out = Image.fromarray(arr, "RGBA")
    bbox = out.getbbox()
    return out.crop(bbox) if bbox else out


def _is_flat(img: Image.Image, mode: str) -> bool:
    w, h = img.size
    pts = [(1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)]
    px = [img.convert("RGB").getpixel(p) for p in pts]
    if mode == "dark":
        return sum(max(p) < 48 for p in px) >= 3
    return sum(min(p) > 232 for p in px) >= 3


def export_mascot(src: Path, out_dir: Path) -> bool:
    """assets/mascot.png -> site/mascot.webp (background removed) + icon.png favicon / touch icon."""
    if not src.exists():
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(src).convert("RGBA")
    if img.getpixel((0, 0))[3] == 255 and _is_flat(img, "dark"):
        img = knock_out_background(img, "dark")
    big = img.copy()
    big.thumbnail((512, 512), Image.LANCZOS)
    big.save(out_dir / "mascot.webp", "WEBP", quality=90, method=6)
    icon = img.copy()
    icon.thumbnail((180, 180), Image.LANCZOS)
    icon.save(out_dir / "icon.png", "PNG", optimize=True)
    return True


def tcgplayer_image(product_id) -> str | None:
    try:
        return f"https://product-images.tcgplayer.com/fit-in/874x874/{int(float(product_id))}.jpg"
    except (TypeError, ValueError):
        return None


def upscale_url(url: str) -> str:
    """Ask retailer CDNs for a larger rendition where the URL pattern allows it."""
    if "target.scene7.com" in url:
        base = url.split("?")[0]
        return base + "?wid=800&hei=800&fmt=png-alpha&qlt=90"
    if "i5.walmartimages.com" in url:
        return url.split("?")[0] + "?odnHeight=800&odnWidth=800&odnBg=FFFFFF"
    if "pisces.bbystatic.com" in url:
        return url.split(";")[0]
    return url


def ensure_webp(url: str | None, out_dir: Path) -> str | None:
    """Return the relative path of a cached WebP for this URL, downloading and converting if needed."""
    global _last_fetch
    if not url:
        return None
    url = upscale_url(url)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(("v2:" + url).encode()).hexdigest()[:16] + ".webp"
    path = out_dir / name
    if path.exists():
        return name
    # One fetch at a time, gently spaced; image CDNs are tolerant but not infinitely so.
    wait = 0.4 - (time.time() - _last_fetch)
    if wait > 0:
        time.sleep(wait)
    _last_fetch = time.time()
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept": "image/*,*/*;q=0.8"}, timeout=20)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content))
        img.load()
        img = img.convert("RGBA")
        if _is_flat(img, "light"):
            img = knock_out_background(img, "light")
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        img.save(path, "WEBP", quality=QUALITY, method=6)
        return name
    except Exception as e:  # noqa: BLE001
        log.warning("image failed %s: %s", url[:80], e)
        return None
