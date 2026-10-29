"""Contracts every route keeps, checked across the whole API at once.

Per-route tests check what one endpoint answers. These check the promises
that hold *between* endpoints — the ones a client helper is written against
once and then trusts everywhere.
"""
from __future__ import annotations

import pytest

from app.main import app


@pytest.fixture()
def admin(admin_client):
    return admin_client


def _paginated_operations():
    spec = app.openapi()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            names = {p["name"] for p in op.get("parameters", []) if p["in"] == "query"}
            if {"limit", "offset"} <= names:
                yield method.upper(), path, op


# ── Pagination ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("method", "path", "op"), list(_paginated_operations()), ids=lambda v: str(v)[:40]
)
def test_every_paginated_list_echoes_its_window(method, path, op):
    """``{items, total, limit, offset}`` on every list that takes a window.

    The two feedback lists returned ``{items, total}`` alone, so the one
    client helper that pages every other list could not page them.
    """
    spec = app.openapi()
    ref = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    schema = spec["components"]["schemas"][ref.split("/")[-1]]
    assert {"items", "total", "limit", "offset"} <= set(schema["required"]), path


def test_there_are_paginated_lists_to_check():
    # Guards the parametrisation above against silently matching nothing.
    assert len(list(_paginated_operations())) >= 6


@pytest.mark.parametrize("url", ["/api/v1/feedback", "/api/v1/feedback/errors"])
def test_the_feedback_lists_echo_the_window_they_were_asked_for(admin, url):
    body = admin.get(url, params={"limit": 7, "offset": 3}).json()
    assert (body["limit"], body["offset"], body["items"]) == (7, 3, [])


# ── Trailing slashes ───────────────────────────────────────


def test_a_trailing_slash_is_served_not_redirected(auth_client):
    """The redirect was built from the request's scheme.

    Behind a proxy uvicorn does not trust, that scheme is ``http`` — so the
    307 sent an HTTPS caller to ``http://``, and a client that follows it drops
    its ``Authorization`` header on the downgrade.
    """
    canonical = auth_client.get("/api/v1/invoices")
    slashed = auth_client.get(
        "/api/v1/invoices/", headers={"X-Forwarded-Proto": "https"}, follow_redirects=False
    )

    assert slashed.status_code == 200
    assert "location" not in slashed.headers
    assert slashed.json() == canonical.json()


def test_a_trailing_slash_on_a_write_reaches_the_route(client):
    response = client.post(
        "/api/v1/feedback/", json={"message": "slash"}, follow_redirects=False
    )
    assert response.status_code == 201


def test_more_than_one_trailing_slash_is_trimmed_too(client):
    response = client.get("/api/v1/health//", follow_redirects=False)
    assert response.status_code == 200


def test_an_unknown_path_is_still_a_404_with_the_error_body(client):
    response = client.get("/api/v1/nope/", follow_redirects=False)
    assert response.status_code == 404
    assert response.json()["error"]["status"] == 404


def test_the_root_is_left_alone(client):
    assert client.get("/", follow_redirects=False).status_code == 200
