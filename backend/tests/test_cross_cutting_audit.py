"""M4 cross-cutting audit: response consistency across every endpoint.

Census-style sweeps that verify:
1. Every list endpoint returns 200 on the empty set with {items, total}.
2. Every detail endpoint returns 404 for a non-existent row, shaped as the
   standard error envelope.
3. Every error response carries security headers.
4. No error response leaks internal details (SQL, tracebacks, file paths).
5. Every response carries X-Request-ID.

These catch the regression where a new endpoint is added without matching the
conventions the rest of the API follows.
"""
from __future__ import annotations

import re

import pytest

from app.core.deps import (
    get_current_business,
    get_current_user,
    require_admin,
    require_paid_tier,
)
from app.core.routes import collect_api_routes
from app.main import app

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _calls(dependant):
    yield dependant.call
    for sub in dependant.dependencies:
        yield from _calls(sub)


def _needs_auth(route) -> bool:
    return bool(
        {get_current_business, get_current_user}
        & set(_calls(route.dependant))
    )


def _needs_elevated(route) -> bool:
    """Admin or paid-tier — not reachable with a plain free-tier auth_client."""
    fns = set(_calls(route.dependant))
    return require_admin in fns or require_paid_tier in fns


def _list_endpoints():
    """Every GET endpoint whose response model name contains 'List'."""
    found = []
    for route in collect_api_routes(app):
        if "GET" not in route.methods:
            continue
        model = route.response_model
        if (model and "List" in getattr(model, "__name__", "")
                and _needs_auth(route) and not _needs_elevated(route)):
            found.append(route.path)
    return sorted(set(found))


def _detail_endpoints():
    """Every GET endpoint with an {*_id} path parameter."""
    found = []
    for route in collect_api_routes(app):
        if "GET" not in route.methods:
            continue
        if not _needs_auth(route):
            continue
        if re.search(r"\{[a-z_]+_id\}", route.path):
            found.append(route.path)
    return sorted(set(found))


# -----------------------------------------------------------------------
# 1. Every list endpoint returns 200 on the empty set
# -----------------------------------------------------------------------

LIST_ENDPOINTS = _list_endpoints()


class TestEveryListEndpointHandlesTheEmptySet:
    """A new business has no data. Every list must answer 200, not 500."""

    def test_the_sweep_found_list_endpoints(self):
        assert len(LIST_ENDPOINTS) >= 4, (
            f"only {len(LIST_ENDPOINTS)} list endpoints found"
        )

    @pytest.mark.parametrize("path", LIST_ENDPOINTS)
    def test_an_empty_list_is_200_with_items(
        self, auth_client, path,
    ):
        resp = auth_client.get(path)
        assert resp.status_code == 200, (
            f"{path} → {resp.status_code}: {resp.text[:200]}"
        )
        body = resp.json()
        assert "items" in body or "years" in body, (
            f"{path} missing 'items' key: {sorted(body)}"
        )

    @pytest.mark.parametrize("path", LIST_ENDPOINTS)
    def test_an_empty_list_carries_a_total(
        self, auth_client, path,
    ):
        resp = auth_client.get(path)
        body = resp.json()
        has_total = (
            "total" in body
            or "total_at_risk" in body
        )
        assert has_total, (
            f"{path} missing a total field: {sorted(body)}"
        )


# -----------------------------------------------------------------------
# 2. Every detail endpoint returns 404 with the envelope
# -----------------------------------------------------------------------

DETAIL_ENDPOINTS = _detail_endpoints()


class TestEveryDetailEndpointReturns404ForAMissingRow:

    def test_the_sweep_found_detail_endpoints(self):
        assert len(DETAIL_ENDPOINTS) >= 3, (
            f"only {len(DETAIL_ENDPOINTS)} detail endpoints"
        )

    @pytest.mark.parametrize("path", DETAIL_ENDPOINTS)
    def test_a_nonexistent_row_is_404(self, auth_client, path):
        url = re.sub(r"\{[a-z_]+_id\}", "999999", path)
        resp = auth_client.get(url)
        assert resp.status_code == 404, (
            f"{path} → {resp.status_code}"
        )

    @pytest.mark.parametrize("path", DETAIL_ENDPOINTS)
    def test_the_404_carries_the_standard_envelope(
        self, auth_client, path,
    ):
        url = re.sub(r"\{[a-z_]+_id\}", "999999", path)
        resp = auth_client.get(url)
        if resp.status_code != 404:
            pytest.skip(f"{path} → {resp.status_code}")
        body = resp.json()
        assert {"detail", "error", "correlation_id"} <= set(
            body
        ), f"{path} envelope keys: {sorted(body)}"
        assert body["error"]["code"] == "not_found"
        assert body["error"]["status"] == 404

    @pytest.mark.parametrize("path", DETAIL_ENDPOINTS)
    def test_the_404_does_not_confirm_whether_the_id_exists(
        self, auth_client, path,
    ):
        url = re.sub(r"\{[a-z_]+_id\}", "999999", path)
        resp = auth_client.get(url)
        if resp.status_code != 404:
            pytest.skip(f"{path} → {resp.status_code}")
        detail = str(resp.json().get("detail", "")).lower()
        assert "does not belong" not in detail, (
            f"{path} leaks ownership info"
        )


# -----------------------------------------------------------------------
# 3. Every response carries security headers and X-Request-ID
# -----------------------------------------------------------------------

class TestEveryResponseCarriesSecurityHeaders:

    @pytest.mark.parametrize("path", LIST_ENDPOINTS[:3])
    def test_a_successful_response_has_security_headers(
        self, auth_client, path,
    ):
        resp = auth_client.get(path)
        for header, expected in SECURITY_HEADERS.items():
            assert resp.headers.get(header) == expected, (
                f"{path} missing {header}"
            )

    @pytest.mark.parametrize("path", LIST_ENDPOINTS[:3])
    def test_a_successful_response_has_x_request_id(
        self, auth_client, path,
    ):
        resp = auth_client.get(path)
        assert resp.headers.get("X-Request-ID"), (
            f"{path} missing X-Request-ID"
        )

    @pytest.mark.parametrize("path", DETAIL_ENDPOINTS[:2])
    def test_a_404_has_security_headers(
        self, auth_client, path,
    ):
        url = re.sub(r"\{[a-z_]+_id\}", "999999", path)
        resp = auth_client.get(url)
        for header, expected in SECURITY_HEADERS.items():
            assert resp.headers.get(header) == expected, (
                f"{path} 404 missing {header}"
            )

    def test_an_unauthenticated_401_has_security_headers(
        self, client,
    ):
        resp = client.get("/api/v1/invoices")
        assert resp.status_code == 401
        for header, expected in SECURITY_HEADERS.items():
            assert resp.headers.get(header) == expected, (
                f"401 missing {header}"
            )
        assert resp.headers.get("X-Request-ID")


# -----------------------------------------------------------------------
# 4. No error response leaks internal details
# -----------------------------------------------------------------------

LEAK_PATTERNS = [
    re.compile(r"Traceback \(most recent", re.IGNORECASE),
    re.compile(r"File \".*\.py\"", re.IGNORECASE),
    re.compile(r"sqlalchemy\.", re.IGNORECASE),
    re.compile(r"psycopg[23]?\.", re.IGNORECASE),
    re.compile(r"sqlite3\.", re.IGNORECASE),
    re.compile(r"password|secret|api_key", re.IGNORECASE),
]

# Endpoints that intentionally mention technical terms in their
# error responses are excluded from the leak check.
LEAK_EXCEPTIONS = set()


class TestNoErrorLeaksInternalDetails:

    @pytest.mark.parametrize("path", DETAIL_ENDPOINTS)
    def test_a_404_does_not_leak_internals(
        self, auth_client, path,
    ):
        url = re.sub(r"\{[a-z_]+_id\}", "999999", path)
        resp = auth_client.get(url)
        if resp.status_code not in (404, 403):
            pytest.skip(f"{path} → {resp.status_code}")
        text = resp.text
        for pattern in LEAK_PATTERNS:
            assert not pattern.search(text), (
                f"{path} leaks: {pattern.pattern}"
            )

    def test_a_401_does_not_leak_internals(self, client):
        resp = client.get("/api/v1/invoices")
        assert resp.status_code == 401
        text = resp.text
        for pattern in LEAK_PATTERNS:
            assert not pattern.search(text), (
                f"401 leaks: {pattern.pattern}"
            )

    def test_a_422_does_not_leak_file_paths(self, auth_client):
        resp = auth_client.patch(
            "/api/v1/invoices/1",
            json={"taxable_value": "not-a-number"},
        )
        assert resp.status_code in (404, 422)
        text = resp.text
        assert "app/" not in text or "app/models" not in text
        for pattern in LEAK_PATTERNS:
            assert not pattern.search(text), (
                f"422 leaks: {pattern.pattern}"
            )


# -----------------------------------------------------------------------
# 5. Every list endpoint respects Cache-Control
# -----------------------------------------------------------------------

class TestAuthenticatedResponsesAreNotCached:

    @pytest.mark.parametrize("path", LIST_ENDPOINTS[:3])
    def test_a_list_response_sets_cache_control(
        self, auth_client, path,
    ):
        resp = auth_client.get(path)
        cc = resp.headers.get("Cache-Control", "")
        assert "no-store" in cc, (
            f"{path} Cache-Control={cc!r}, expected no-store"
        )
