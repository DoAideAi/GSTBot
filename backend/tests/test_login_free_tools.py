"""The free tools stay login-free.

Product rule: a tool that answers a question from public information — is
this GSTIN valid, what is the tax on this amount, which HSN code is this —
needs no account. Login is for what is kept for a business (its invoices,
returns, history) and for the paid tier (bulk GSTIN, GSTR-2B reconciliation,
ITC optimisation, exports).

A paid-tier gate is added with one ``Depends``, and ``require_paid_tier``
resolves the current business, which needs a token. So the easy mistake is a
gate that lands one route over and quietly puts a free tool behind a login.
Removing a route from ``FREE_TOOLS`` is how a deliberate change says so.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import deps
from app.core.routes import collect_api_routes
from app.main import app
from tests.conftest import BUSINESS_GSTIN

FREE_TOOLS = {
    ("GET", "/api/v1/meta/gstin/{gstin}"),
    ("GET", "/api/v1/meta/states"),
    ("GET", "/api/v1/meta/recent-lookups"),
    ("POST", "/api/v1/meta/reminder-subscribe"),
    ("GET", "/api/v1/gpt/gstin/{gstin}"),
    ("GET", "/api/v1/gpt/hsn"),
    ("GET", "/api/v1/gpt/calculate"),
    ("GET", "/api/v1/gpt/filing-dates"),
    ("POST", "/api/v1/gpt/invoice"),
    ("POST", "/api/v1/advisor/ask"),
    ("GET", "/api/v1/subscriptions/pricing"),
    ("POST", "/api/v1/feedback"),
}

_AUTH = {deps.get_current_user, deps.oauth2_scheme}


def _needs_login(dependant) -> bool:
    return dependant.call in _AUTH or any(_needs_login(d) for d in dependant.dependencies)


def _routes() -> dict[tuple[str, str], Any]:
    found = {}
    for route in collect_api_routes(app):
        if not hasattr(route, "dependant"):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            found[(method, route.path)] = route
    return found


def test_every_free_tool_still_exists():
    # A renamed route would otherwise drop out of the check below unnoticed.
    assert not FREE_TOOLS - set(_routes()), FREE_TOOLS - set(_routes())


@pytest.mark.parametrize(("method", "path"), sorted(FREE_TOOLS), ids=lambda v: v)
def test_no_free_tool_depends_on_a_login(method, path):
    assert not _needs_login(_routes()[(method, path)].dependant), (
        f"{method} {path} now requires a login; free tools must stay login-free"
    )


@pytest.mark.parametrize(
    "url",
    [
        f"/api/v1/meta/gstin/{BUSINESS_GSTIN}",
        "/api/v1/meta/states",
        f"/api/v1/gpt/gstin/{BUSINESS_GSTIN}",
        "/api/v1/gpt/hsn?q=laptop",
        "/api/v1/gpt/calculate?amount=1000&rate=18",
        "/api/v1/gpt/filing-dates",
        "/api/v1/subscriptions/pricing",
    ],
)
def test_a_visitor_with_no_token_gets_an_answer(client, url):
    response = client.get(url)
    assert response.status_code == 200, (
        f"{url} answered {response.status_code}: {response.text[:200]}"
    )


def test_the_paid_features_are_the_ones_that_ask_for_a_login():
    # The other half of the rule, so the list above cannot grow to swallow them.
    paid = {
        ("POST", "/api/v1/meta/gstin/bulk"),
        ("POST", "/api/v1/reconciliation/gstr2b/import"),
        ("POST", "/api/v1/reconciliation/run"),
        ("GET", "/api/v1/itc"),
        ("GET", "/api/v1/itc/rule37"),
        ("GET", "/api/v1/itc/lapsing"),
    }
    routes = _routes()
    assert all(_needs_login(routes[key].dependant) for key in paid)
    assert not paid & FREE_TOOLS
