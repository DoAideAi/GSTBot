"""Tenancy as a contract over the route table, not a habit per router.

Every router already scopes its lookups to the calling business, and most of
them have a test that says so — ``test_invoices.py`` checks the invoice detail
route, ``test_alerts.py`` the two alert routes, ``test_supplier_score.py`` the
supplier one. Those tests are good and they stay. What none of them can do is
notice a route that *nobody wrote a test for*: ``POST
/invoices/{invoice_id}/reparse`` shipped correctly scoped and completely
unchecked, and the only reason that was safe is that whoever wrote it happened
to reach for ``_owned_invoice``. The next one might reach for ``db.get``.

So this file sweeps the assembled route table instead of naming routes. Any
route with an ``*_id`` path parameter has to appear in :data:`FACTORIES` with a
way to build a row for one tenant, and is then called by the *other* tenant and
required to answer 404. Add a route with a row id in its path and
:class:`TestEveryRowIdRouteIsCovered` fails until it is listed here — which is
the whole point, because the failure arrives while the route is being written
rather than after a business has read another business's books.

404 rather than 403 throughout, for the reason the individual tests already
give: a 403 confirms the id exists, and ids are sequential, so a competitor's
invoice count is a loop away.

The paired owner check in :class:`TestTheSweepIsNotVacuous` is what stops this
file quietly proving nothing. Every assertion here is "the rival got a 404",
and a factory that silently built no row — wrong tenant, missing column, a
route that 404s for everyone — would satisfy that while testing nothing at all.
Asserting the owner does *not* get a 404 from the same URL is what makes the
rival's 404 mean tenancy rather than absence.
"""
from __future__ import annotations

import re
from io import BytesIO

import pytest

from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.invoice import InvoiceType
from app.models.reconciliation_run import ReconciliationRun
from app.models.supplier import Supplier
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE
from tests.test_route_contracts import API_ROUTES

PERIOD = "2026-04"

# A path parameter naming a row, as opposed to one naming a period, a return
# type or a GSTIN. Those address a tenant's data too, but not by an id a
# stranger can guess by counting, and the ones that matter already have their
# own tests (``test_reconciliation.py`` for the 2B period, and the filing
# export routes take an enum that cannot address another tenant at all).
_ROW_ID = re.compile(r"\{(\w*_id)\}")


def _row_id_params(path: str) -> list[str]:
    return _ROW_ID.findall(path)


def _routes_with_a_row_id() -> list[tuple[str, str]]:
    """``(method, path)`` for every route addressing a row by id."""
    found = {
        (method, route.path)
        for route in API_ROUTES
        if _row_id_params(route.path)
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    return sorted(found)


ROW_ID_ROUTES = _routes_with_a_row_id()


# --------------------------------------------------------------------------
# Building a row that belongs to the tenant under test
# --------------------------------------------------------------------------

def _an_invoice(auth_client, db_session, business) -> int:
    """Uploaded rather than inserted, so the file reparse re-reads exists.

    A bare ``Invoice`` row would be enough for the tenancy check itself — the
    ownership lookup answers before anything opens the file — but then the
    owner half of the sweep could not tell "reparse works and this row is
    mine" from "reparse 500s for everyone".
    """
    body = BytesIO(b"Invoice No: OWN-1\nTotal Amount: 500.00")
    response = auth_client.post(
        "/api/v1/invoices/upload",
        files={"file": ("bill.txt", body, "text/plain")},
        data={"invoice_type": InvoiceType.PURCHASE.value},
    )
    assert response.status_code == 201, response.text
    return response.json()["invoice"]["id"]


def _an_alert(auth_client, db_session, business) -> int:
    alert = Alert(
        business_id=business.id,
        alert_type=AlertType.FILING_DEADLINE,
        severity=AlertSeverity.WARNING,
        status=AlertStatus.PENDING,
        title="GSTR-3B is due",
        message="Recorded nowhere yet.",
        period=PERIOD,
    )
    db_session.add(alert)
    db_session.commit()
    db_session.refresh(alert)
    return alert.id


def _a_supplier(auth_client, db_session, business) -> int:
    supplier = Supplier(business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE)
    db_session.add(supplier)
    db_session.commit()
    db_session.refresh(supplier)
    return supplier.id


def _a_run(auth_client, db_session, business) -> int:
    run = ReconciliationRun(business_id=business.id, period=PERIOD)
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run.id


def _a_linked_business(auth_client, db_session, business) -> int:
    """A third business, linked to *this* tenant's owner via membership.

    Unlike the other factories, the row this route addresses is not owned by
    ``business`` at all — a membership is deliberately not a row scoped to any
    tenant's own data, it is what widens *access* to one. What must still be
    true is the same shape: the rival tenant's owner has no membership row
    naming this business, so the route 404s for them exactly as the others do.
    Returns the linked business's id, the unlink route's path parameter.
    """
    from app.models.business import Business
    from app.models.business_membership import BusinessMembership, MembershipRole
    from app.models.user import User

    linked = Business(gstin="27AAGCB7383J2Z7", legal_name="Linked Co", state_code="27")
    db_session.add(linked)
    db_session.flush()

    owner = db_session.query(User).filter_by(business_id=business.id).one()
    db_session.add(
        BusinessMembership(user_id=owner.id, business_id=linked.id, role=MembershipRole.OWNER)
    )
    db_session.commit()
    return linked.id


# Keyed by path, because the two alert routes and the four invoice routes each
# address the same kind of row and differ only in what they do to it.
FACTORIES = {
    "/api/v1/invoices/{invoice_id}": _an_invoice,
    "/api/v1/invoices/{invoice_id}/reparse": _an_invoice,
    "/api/v1/alerts/{alert_id}/read": _an_alert,
    "/api/v1/alerts/{alert_id}/dismiss": _an_alert,
    "/api/v1/suppliers/{supplier_id}": _a_supplier,
    "/api/v1/reconciliation/{run_id}": _a_run,
    "/api/v1/reconciliation/{run_id}/report.pdf": _a_run,
    "/api/v1/businesses/mine/{business_id}": _a_linked_business,
}

# A body that passes validation, so a 404 is the ownership check answering and
# not a malformed field being refused before the row is ever looked up. Only
# PATCH needs one; the rest carry no body.
BODIES = {
    ("PATCH", "/api/v1/invoices/{invoice_id}"): {"hsn_code": "8471"},
}


def _call(client, method: str, path: str, row_id: int, *, token: str | None = None):
    url = _ROW_ID.sub(str(row_id), path)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.request(
        method, url, json=BODIES.get((method, path)), headers=headers
    )


def _ids(case) -> str:
    return f"{case[0]} {case[1]}"


class TestEveryRowIdRouteIsCovered:
    """The guard that makes the rest of the file self-extending."""

    def test_the_sweep_found_routes(self):
        # Without this the parametrised tests below would pass by having no
        # cases at all, which is exactly how the sweeps in
        # ``test_route_contracts.py`` once stopped sweeping.
        assert ROW_ID_ROUTES, "no row-id routes found — the sweep proves nothing"

    def test_every_row_id_route_has_a_factory(self):
        missing = sorted({path for _, path in ROW_ID_ROUTES if path not in FACTORIES})
        assert not missing, (
            "these routes address a row by id and are not checked for tenancy; "
            f"add a factory in FACTORIES: {missing}"
        )

    def test_no_factory_names_a_route_that_is_gone(self):
        # The other direction: a renamed route would otherwise leave a factory
        # here that runs against nothing and reports coverage that is not real.
        live = {path for _, path in ROW_ID_ROUTES}
        stale = sorted(set(FACTORIES) - live)
        assert not stale, f"FACTORIES names routes the app no longer serves: {stale}"


@pytest.mark.parametrize("case", ROW_ID_ROUTES, ids=_ids)
def test_another_tenants_row_is_not_reachable(
    case, auth_client, db_session, business, other_tenant
):
    """The rival is told the row does not exist, whatever the route does to it."""
    method, path = case
    row_id = FACTORIES[path](auth_client, db_session, business)

    response = _call(auth_client, method, path, row_id, token=other_tenant)

    assert response.status_code == 404, (
        f"{method} {path} answered {response.status_code} to another tenant: "
        f"{response.text[:200]}"
    )


class TestTheSweepIsNotVacuous:
    """Every 404 above has to be tenancy, not a row that was never built."""

    @pytest.mark.parametrize("case", ROW_ID_ROUTES, ids=_ids)
    def test_the_owner_is_not_told_the_row_is_missing(
        self, case, auth_client, db_session, business
    ):
        method, path = case
        row_id = FACTORIES[path](auth_client, db_session, business)

        response = _call(auth_client, method, path, row_id)

        assert response.status_code != 404, (
            f"{method} {path} answered 404 to the row's own owner — the "
            "tenancy case for this route is proving nothing"
        )
        # Not a 5xx either: a route that errors for everyone would also never
        # reach the ownership check it is supposed to be demonstrating.
        assert response.status_code < 500, (
            f"{method} {path} answered {response.status_code} to its owner: "
            f"{response.text[:200]}"
        )

    def test_a_row_that_never_existed_is_also_404(self, auth_client, db_session, business):
        # The third reading of a 404: absence. Kept alongside the other two so
        # the file states all three meanings the status carries here.
        assert auth_client.get("/api/v1/invoices/999999").status_code == 404
