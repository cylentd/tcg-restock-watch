"""Image cache: a picture is downloaded once; a failed download is not retried within a day.

Oracle (David, 2026-10-09): fill missing pictures from TCGplayer; each URL is fetched at most once while
its file exists, and a failed one (non-2xx) leaves the placeholder and waits a day before the next try.
requests.get is faked, so no host is touched.
"""

import io

import pytest
import requests
from PIL import Image

from tcgwatch import images

URL = "https://product-images.tcgplayer.com/fit-in/874x874/12345.jpg"
DAY = 24 * 60 * 60


class FakeResponse:
    def __init__(self, status):
        self.status_code = status
        buf = io.BytesIO()
        Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "PNG")
        self.content = buf.getvalue()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture
def fetches(monkeypatch):
    """Records each URL asked for; the status to answer with is set via fetches.status."""
    class Fetches(list):
        status = 200

    asked = Fetches()

    def fake_get(url, **kwargs):
        asked.append(url)
        return FakeResponse(asked.status)

    monkeypatch.setattr(images.requests, "get", fake_get)
    monkeypatch.setattr(images, "_last_fetch", 0.0)
    monkeypatch.setattr(images.time, "sleep", lambda s: None, raising=False)
    return asked


def test_a_good_download_is_saved_and_returned_by_name(tmp_path, fetches):
    name = images.ensure_webp(URL, tmp_path)

    assert name.endswith(".webp")
    assert (tmp_path / name).exists()
    assert fetches == [URL]


def test_a_file_already_cached_is_not_downloaded_again(tmp_path, fetches):
    first = images.ensure_webp(URL, tmp_path)

    second = images.ensure_webp(URL, tmp_path)

    assert second == first
    assert fetches == [URL]


def test_a_failed_download_returns_none_and_saves_no_picture(tmp_path, fetches):
    fetches.status = 404

    assert images.ensure_webp(URL, tmp_path) is None
    assert list(tmp_path.glob("*.webp")) == []


def test_a_failed_download_is_not_retried_within_a_day(tmp_path, fetches, clock):
    fetches.status = 404
    images.ensure_webp(URL, tmp_path)

    clock.advance(DAY - 1)
    assert images.ensure_webp(URL, tmp_path) is None

    assert fetches == [URL]


def test_a_failed_download_is_retried_after_a_day(tmp_path, fetches, clock):
    fetches.status = 404
    images.ensure_webp(URL, tmp_path)

    clock.advance(DAY)
    fetches.status = 200
    name = images.ensure_webp(URL, tmp_path)

    assert fetches == [URL, URL]
    assert (tmp_path / name).exists()


def test_the_tcgplayer_url_for_a_float_product_id_uses_the_integer(tmp_path):
    # market search answers productId as a float (504257.0)
    assert images.tcgplayer_image(504257.0) == "https://product-images.tcgplayer.com/fit-in/874x874/504257.jpg"
