"""Sitemap, robots.txt, and OG image — public, read-only, cached."""
from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
from unittest.mock import patch

from PIL import Image


class TestSitemap:
    def test_returns_valid_xml(self, client):
        response = client.get("/api/v1/seo/sitemap.xml")
        assert response.status_code == 200
        assert "application/xml" in response.headers["content-type"]
        root = ET.fromstring(response.text)
        assert root.tag.endswith("urlset")

    def test_contains_static_pages(self, client):
        body = client.get("/api/v1/seo/sitemap.xml").text
        assert "https://gst.doaide.com/calculator" in body
        assert "https://gst.doaide.com/hsn" in body
        assert "https://gst.doaide.com/lookup" in body

    def test_contains_free_tool_pages(self, client):
        body = client.get("/api/v1/seo/sitemap.xml").text
        assert "https://gst.doaide.com/penalty-calculator" in body
        assert "https://gst.doaide.com/eway-bill" in body
        assert "https://gst.doaide.com/input-tax-credit" in body
        assert "https://gst.doaide.com/composition-scheme" in body
        assert "https://gst.doaide.com/invoice-generator" in body
        assert "https://gst.doaide.com/reverse-charge" in body
        assert "https://gst.doaide.com/itc-mismatch" in body

    def test_contains_product_rate_pages(self, client):
        body = client.get("/api/v1/seo/sitemap.xml").text
        assert "https://gst.doaide.com/gst-rate/laptop" in body
        assert "https://gst.doaide.com/gst-rate/mobile-phone" in body
        assert "https://gst.doaide.com/gst-rate/cement" in body

    def test_each_product_url_has_monthly_changefreq(self, client):
        root = ET.fromstring(client.get("/api/v1/seo/sitemap.xml").text)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        product_urls = [
            url for url in root.findall("s:url", ns)
            if "gst-rate" in url.find("s:loc", ns).text
        ]
        assert len(product_urls) > 100
        for url in product_urls[:5]:
            assert url.find("s:changefreq", ns).text == "monthly"

    def test_is_cached(self, client):
        response = client.get("/api/v1/seo/sitemap.xml")
        assert "max-age=3600" in response.headers.get("cache-control", "")

    def test_needs_no_authentication(self, client):
        assert client.get("/api/v1/seo/sitemap.xml").status_code == 200


class TestRobotsTxt:
    def test_returns_plain_text(self, client):
        response = client.get("/api/v1/seo/robots.txt")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]

    def test_allows_public_pages(self, client):
        body = client.get("/api/v1/seo/robots.txt").text
        assert "Allow: /gst-rate/" in body
        assert "Allow: /gstin/" in body
        assert "Allow: /calculator" in body

    def test_allows_free_tool_pages(self, client):
        body = client.get("/api/v1/seo/robots.txt").text
        assert "Allow: /penalty-calculator" in body
        assert "Allow: /eway-bill" in body
        assert "Allow: /input-tax-credit" in body
        assert "Allow: /composition-scheme" in body
        assert "Allow: /invoice-generator" in body
        assert "Allow: /reverse-charge" in body
        assert "Allow: /itc-mismatch" in body

    def test_disallows_private_pages(self, client):
        body = client.get("/api/v1/seo/robots.txt").text
        assert "Disallow: /api/" in body
        assert "Disallow: /invoices" in body

    def test_includes_sitemap_url(self, client):
        body = client.get("/api/v1/seo/robots.txt").text
        assert "Sitemap: https://gst.doaide.com/api/v1/seo/sitemap.xml" in body

    def test_is_cached(self, client):
        response = client.get("/api/v1/seo/robots.txt")
        assert "max-age=86400" in response.headers.get("cache-control", "")

    def test_needs_no_authentication(self, client):
        assert client.get("/api/v1/seo/robots.txt").status_code == 200


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
