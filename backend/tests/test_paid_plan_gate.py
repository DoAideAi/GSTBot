"""Every paid feature refuses a free business the same way.

The refusal shares its status, 403, with a viewer being refused a write — and
the two call for different actions: upgrade the plan, or ask an owner. The
error-code catalog in ``app.core.errors`` tells clients to branch on
``error.code``, so this one has its own, and the funnel counts paywall hits by
it. Swept over the route table so a newly gated route cannot answer with the
role refusal's code instead.
"""
from __future__ import annotations

import re

import pytest

from app.core.deps import require_paid_tier
from app.core.openapi import dependency_calls
from app.core.routes import collect_api_routes
from app.main import app

GATED = sorted(
    (method, route.path)
    for route in collect_api_routes(app)
    if require_paid_tier in dependency_calls(route.dependant)
    for method in route.methods
)


def test_the_sweep_finds_the_paid_features():
    paths = {path for _, path in GATED}
    assert "/api/v1/itc" in paths
    assert "/api/v1/reconciliation/run" in paths
    assert "/api/v1/meta/gstin/bulk" in paths


@pytest.mark.parametrize(("method", "path"), GATED, ids=lambda v: v)
def test_a_free_business_is_told_to_upgrade_not_to_ask_an_owner(auth_client, method, path):
    # The gate is a dependency, and FastAPI resolves dependencies before it
    # validates the route's own parameters — so a placeholder path is enough
    # to reach it, and no body is needed.
    response = auth_client.request(method, re.sub(r"\{[^}]+\}", "1", path))

    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "paid_plan_required"
    assert "/pricing" in error["message"]


def test_a_role_refusal_keeps_the_generic_code(auth_client, db_session):
    """The distinction runs both ways: a viewer refused a write is still
    ``forbidden``, so a client does not send them to the pricing page."""
    from app.models.user import UserRole
    from tests.test_rbac import set_home_role

    set_home_role(db_session, UserRole.VIEWER)
    response = auth_client.post("/api/v1/suppliers/rescore")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
