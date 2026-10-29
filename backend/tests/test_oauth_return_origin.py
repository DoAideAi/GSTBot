"""Where a sign-in sends the browser back to, with its token in the fragment.

The OAuth routes redirected to ``BACKEND_CORS_ORIGINS[0]`` — the first origin
allowed to call the API, which is not the same thing as the site. On
2026-10-29 production's list held only the product's previous domain, so every
Google, GitHub or Microsoft sign-in that day handed its bearer token to that
domain. A stale origin listed first is still only a startup warning. In
production the return address is ``PUBLIC_SITE_URL``, the one validated origin
of the site; elsewhere it stays the first CORS origin, which is the dev server.
"""
from __future__ import annotations

import pytest

from app.core.config import Settings, settings
from app.routers import oauth


def _settings(**overrides) -> Settings:
    base = {
        "environment": "development",
        "backend_cors_origins": "http://localhost:5173,http://localhost:3000",
        "public_site_url": "https://gst.doaide.com",
    }
    return Settings.model_construct(**{**base, **overrides})


class TestFrontendOrigin:
    def test_production_returns_to_the_site_not_the_first_cors_origin(self):
        current = _settings(
            environment="production",
            backend_cors_origins="https://old-domain.example,https://gst.doaide.com",
        )
        assert current.frontend_origin == "https://gst.doaide.com"

    def test_production_returns_to_the_site_even_with_no_cors_origin(self):
        current = _settings(environment="production", backend_cors_origins="")
        assert current.frontend_origin == "https://gst.doaide.com"

    def test_development_keeps_the_dev_server(self):
        # PUBLIC_SITE_URL defaults to production; a local sign-in must not
        # hand a dev token to the live site.
        assert _settings().frontend_origin == "http://localhost:5173"

    def test_development_with_no_cors_origin_falls_back_to_vite(self):
        assert _settings(backend_cors_origins="").frontend_origin == "http://localhost:5173"


class TestTheRedirect:
    @pytest.fixture()
    def production(self, monkeypatch):
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(
            settings, "backend_cors_origins", "https://old-domain.example,https://gst.doaide.com"
        )
        monkeypatch.setattr(settings, "public_site_url", "https://gst.doaide.com")

    def test_an_error_goes_back_to_the_site(self, production):
        response = oauth._login_error("github_auth_failed")
        assert response.headers["location"] == (
            "https://gst.doaide.com/login?error=github_auth_failed"
        )

    def test_the_address_is_read_per_request_not_frozen_at_import(self, production, monkeypatch):
        monkeypatch.setattr(settings, "public_site_url", "https://staging.gst.example")
        location = oauth._login_error("x").headers["location"]
        assert location.startswith("https://staging.gst.example/")
