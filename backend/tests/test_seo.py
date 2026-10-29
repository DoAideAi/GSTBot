"""Sitemap, robots.txt, and OG image — public, read-only, cached."""
from __future__ import annotations

import io
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestTheCrawlerFilesHaveOneSource:
    """P33 M13: the API kept its own sitemap and robots.txt, by hand, beside the
    site's.

    The site's are ``frontend/public/robots.txt`` and the sitemap the prerender
    build writes — the same list it prerenders, so the two cannot drift. The
    API's copy had: 91 of the 1,134 indexable pages were missing from it, every
    HSN page claimed to have changed today on every request, and its
    robots.txt pointed crawlers at that sitemap while disallowing /api/, the
    path it lives under, and hid /itc-calculator and /filing-checklist behind
    unanchored /itc and /filing rules. Both now send a crawler to the real one.
    """

    @pytest.mark.parametrize(
        ("path", "target"),
        [("/api/v1/seo/sitemap.xml", "/sitemap.xml"), ("/api/v1/seo/robots.txt", "/robots.txt")],
    )
    def test_each_is_a_permanent_redirect_to_the_sites_own(self, client, path, target):
        from app.core.config import settings

        response = client.get(path, follow_redirects=False)

        assert response.status_code == 301
        assert response.headers["location"] == f"{settings.public_site_url}{target}"

    @pytest.mark.parametrize("path", ["/api/v1/seo/sitemap.xml", "/api/v1/seo/robots.txt"])
    def test_needs_no_authentication(self, client, path):
        assert client.get(path, follow_redirects=False).status_code == 301

    def test_the_router_keeps_no_page_list_of_its_own(self):
        from app.routers import seo

        for name in ("STATIC_PAGES", "HSN_CODES", "PRODUCT_SLUGS", "ROBOTS_TXT"):
            assert not hasattr(seo, name), name

    def test_the_sites_robots_points_at_the_sites_sitemap(self):
        robots = (REPO_ROOT / "frontend" / "public" / "robots.txt").read_text()
        assert "Sitemap: https://gst.doaide.com/sitemap.xml" in robots


class TestOgImage:
    def test_returns_a_1200x630_png(self, client):
        response = client.get("/api/v1/seo/og-image", params={"title": "Test Title"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        img = Image.open(io.BytesIO(response.content))
        assert img.size == (1200, 630)

    def test_accepts_title_and_subtitle(self, client):
        response = client.get(
            "/api/v1/seo/og-image",
            params={"title": "GST Rate for Laptop", "subtitle": "18% under HSN 8471"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    def test_rejects_missing_title(self, client):
        response = client.get("/api/v1/seo/og-image")
        assert response.status_code == 422

    def test_rejects_empty_title(self, client):
        response = client.get("/api/v1/seo/og-image", params={"title": ""})
        assert response.status_code == 422

    def test_is_cached_for_a_day(self, client):
        response = client.get("/api/v1/seo/og-image", params={"title": "Cache test"})
        assert "max-age=86400" in response.headers.get("cache-control", "")

    def test_needs_no_authentication(self, client):
        assert client.get(
            "/api/v1/seo/og-image", params={"title": "Public"}
        ).status_code == 200

    def test_long_title_wraps_without_error(self, client):
        long_title = "GST Rate for Air Conditioner Split Inverter " * 3
        response = client.get("/api/v1/seo/og-image", params={"title": long_title[:200]})
        assert response.status_code == 200
        img = Image.open(io.BytesIO(response.content))
        assert img.size == (1200, 630)

    def test_font_fallback_logs_warning(self, caplog):
        from PIL import ImageFont as _IF

        from app.routers.seo import _render_og_image

        _real_truetype = _IF.truetype

        def _reject_dejavu(*args, **kwargs):
            path = args[0] if args else kwargs.get("font", "")
            if "dejavu" in str(path).lower():
                raise OSError("not found")
            return _real_truetype(*args, **kwargs)

        with (
            patch("app.routers.seo.ImageFont.truetype", side_effect=_reject_dejavu),
            caplog.at_level(logging.WARNING, logger="app.routers.seo"),
        ):
            png = _render_og_image("Fallback test")
        assert isinstance(png, bytes)
        assert "DejaVu fonts not found" in caplog.text


def test_an_og_image_is_rendered_once_per_title(client):
    # P18 M8: each render is ~300 ms of PIL on the API worker, and crawlers ask
    # for the site's same few titles over and over.
    from app.routers import seo

    seo._render_og_image.cache_clear()
    params = {"title": "GST Calculator", "subtitle": "Free"}
    first = client.get("/api/v1/seo/og-image", params=params)
    second = client.get("/api/v1/seo/og-image", params=params)
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    info = seo._render_og_image.cache_info()
    assert (info.hits, info.misses) == (1, 1)
    assert info.maxsize is not None  # bounded: titles come from the query string
