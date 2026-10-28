"""The per-route performance budgets in ``app.core.budgets``."""
from __future__ import annotations

from app.core import budgets
from app.core.routes import collect_api_routes
from app.main import app

ROUTES = {
    (method, route.path.removeprefix("/api/v1"))
    for route in collect_api_routes(app)
    for method in route.methods
}


def test_every_listed_budget_names_a_route_that_exists():
    """A renamed route would leave its entry behind, silently, and fall back
    on the default — the slow route then reads as over budget, or the entry
    excuses nothing at all."""
    stale = sorted(key for key in budgets.ROUTE_BUDGETS_MS if key not in ROUTES)
    assert stale == []


def test_a_listed_route_gets_its_own_budget():
    assert budgets.budget_for("POST", "/reconciliation/run") == 5000


def test_an_unlisted_read_and_write_fall_back_on_their_method():
    assert budgets.budget_for("GET", "/dashboard") == budgets.READ_MS
    assert budgets.budget_for("PATCH", "/invoices/{invoice_id}") == budgets.WRITE_MS


def test_an_unrouted_path_is_held_to_the_default():
    assert budgets.budget_for("GET", None) == budgets.READ_MS
    assert budgets.budget_for("POST", None) == budgets.WRITE_MS


def test_no_budget_is_looser_than_the_slowest_thing_it_waits_on():
    """Generous is not the same as unbounded: the largest allowance is the
    advisor's, which is held to its own 20 s upstream timeout."""
    assert max(budgets.ROUTE_BUDGETS_MS.values()) <= 20000
