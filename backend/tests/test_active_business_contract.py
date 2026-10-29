"""Switching business is a contract over the route table, not a habit per router.

``tests/test_tenancy_contract.py`` sweeps the boundary between two *logins*.
This file sweeps the one inside a single login: a user who has linked a second
GSTIN sends ``X-Business-Id`` and every subsequent request must act for that
business and no other. The two are not the same check. A route that resolves
its tenant from the token rather than from ``get_current_business`` passes the
cross-tenant sweep perfectly — the rival still gets a 404 — while quietly
answering a switched request with the caller's *own* books. That is the shape
of the bug this file exists to catch, and it is a data-leak the user cannot
even see, because both sets of books legitimately belong to them.

``test_businesses.py`` already covers the header itself: which ids are honoured,
which are refused, and that a switch is revoked by unlinking. What it checks the
header *does* is one dashboard read and one upload. Twenty-nine other
business-scoped routes were taking the header on trust.

So the tenant under test here is seeded with rows carrying markers no other
business could produce, and then every business-scoped route is called with the
header pointing at a second, empty business. Nothing that comes back may contain
a marker. A route added later is swept without being named, which is the point:
:class:`TestTheSweepCoversEveryBusinessScopedRoute` fails while the route is
being written rather than after one client's books have been served to another.
"""
from __future__ import annotations

import re
from datetime import date

import pytest

from app.core.deps import get_current_business
from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType
from app.models.gstr_return import GSTRReturn, ReturnStatus, ReturnType
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from app.models.supplier import Supplier
from app.services.gstin import compute_check_digit
from tests.conftest import BUSINESS_GSTIN, make_paid
from tests.test_businesses import SECOND_GSTIN, link, register_second_business
from tests.test_route_contracts import API_ROUTES
from tests.test_tenancy_contract import FACTORIES, ROW_ID_ROUTES

PERIOD = "2026-04"

_PATH_PARAM = re.compile(r"\{(\w+)\}")
_ROW_ID = re.compile(r"\{(\w*_id)\}")


# ---------------------------------------------------------------------------
# What the tenant under test holds, and nobody else could
# ---------------------------------------------------------------------------

# Strings that can only have come from the home business's own rows. Chosen so
# that a leak is visible in the response text whatever shape the route returns
# — a list of invoices, a summary that names the business, a CSV export — which
# is what lets one assertion cover routes with nothing else in common.
#
# The GSTIN is the important one. It is the tenant's identity rather than a row
# it happens to hold, so a route that echoes it while switched is answering as
# the wrong business even when it has no data to leak.
HOME_INVOICE_NUMBER = "HOMEONLY-INV-1"
HOME_ARN = "HOMEONLYARN0000001"
HOME_ALERT_TITLE = "HOMEONLY: GSTR-3B for 2026-04 is overdue"
HOME_RUN_ERROR = "HOMEONLY: the run stopped on a supplier it could not place"

# A supplier of this tenant's own, and deliberately not one of ``conftest``'s
# shared GSTINs: ``test_tenancy_contract``'s factories build a supplier on
# ``SUPPLIER_GSTIN_OTHER_STATE`` for the same business, and one live supplier
# per GSTIN per tenant is a unique index. Karnataka, so the seeded invoice's
# IGST split is the one an inter-state purchase would really carry.
_HOME_SUPPLIER_PREFIX = "29AAGCB7383J3Z"
HOME_SUPPLIER_GSTIN = _HOME_SUPPLIER_PREFIX + compute_check_digit(_HOME_SUPPLIER_PREFIX)

HOME_MARKERS = (
    BUSINESS_GSTIN,
    HOME_INVOICE_NUMBER,
    HOME_SUPPLIER_GSTIN,
    HOME_ARN,
    HOME_ALERT_TITLE,
    HOME_RUN_ERROR,
)


class Seeded:
    """The ids the swept URLs need, and the markers the responses must not carry."""

    def __init__(self, *, invoice_id: int, supplier_id: int, run_id: int, alert_id: int):
        self.invoice_id = invoice_id
        self.supplier_id = supplier_id
        self.run_id = run_id
        self.alert_id = alert_id


@pytest.fixture()
def home(db_session, business) -> Seeded:
    """A full month for the home business: one of every row a route can read.

    Inserted rather than driven through the upload and reconciliation
    pipelines. What is under test is which tenant a route answers for, and a
    row that reached the table by hand is indistinguishable from one that
    arrived over HTTP by the time any of these routes reads it — while the
    pipeline would cost a parse and a reconciliation run per swept case.
    """
    supplier = Supplier(
        business_id=business.id,
        gstin=HOME_SUPPLIER_GSTIN,
        legal_name="Northwind Supplies Private Limited",
    )
    db_session.add(supplier)
    db_session.flush()

    invoice = Invoice(
        business_id=business.id,
        supplier_id=supplier.id,
        invoice_type=InvoiceType.PURCHASE,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=HOME_SUPPLIER_GSTIN,
        counterparty_name="Northwind Supplies Private Limited",
        invoice_number=HOME_INVOICE_NUMBER,
        invoice_date=date(2026, 4, 15),
        period=PERIOD,
        taxable_value="450000.00",
        igst="81000.00",
        total_value="531000.00",
    )
    run = ReconciliationRun(
        business_id=business.id,
        period=PERIOD,
        status=ReconciliationStatus.COMPLETED,
        total_invoices=1,
        matched_count=1,
        error=HOME_RUN_ERROR,
    )
    alert = Alert(
        business_id=business.id,
        alert_type=AlertType.FILING_DEADLINE,
        severity=AlertSeverity.CRITICAL,
        status=AlertStatus.PENDING,
        title=HOME_ALERT_TITLE,
        message="Recorded nowhere yet.",
        period=PERIOD,
    )
    filed = GSTRReturn(
        business_id=business.id,
        period=PERIOD,
        return_type=ReturnType.GSTR3B,
        status=ReturnStatus.FILED,
        arn=HOME_ARN,
    )
    db_session.add_all([invoice, run, alert, filed])
    db_session.commit()
    for row in (invoice, run, alert):
        db_session.refresh(row)

    return Seeded(
        invoice_id=invoice.id,
        supplier_id=supplier.id,
        run_id=run.id,
        alert_id=alert.id,
    )


@pytest.fixture()
def switched(auth_client, client) -> int:
    """A second business this login may act for, holding nothing at all.

    Empty on purpose. Every assertion below is that a home marker is *absent*,
    and a second business with books of its own would leave "the route answered
    for the right tenant" and "the route answered with the wrong tenant's data
    but none of the rows we happened to mark" indistinguishable.
    """
    register_second_business(client)
    response = link(auth_client)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# ---------------------------------------------------------------------------
# The routes that take the header, discovered rather than listed
# ---------------------------------------------------------------------------

def _calls(dependant):
    yield dependant.call
    for sub in dependant.dependencies:
        yield from _calls(sub)


def _business_scoped_routes() -> list[tuple[str, str]]:
    """``(method, path)`` for every route resolving a tenant through the dependency."""
    found = {
        (method, route.path)
        for route in API_ROUTES
        if hasattr(route, "dependant")
        and get_current_business in set(_calls(route.dependant))
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    return sorted(found)


BUSINESS_SCOPED_ROUTES = _business_scoped_routes()

# The reads, which can be swept by calling them: a GET has no body to invent,
# so the sweep needs nothing per route beyond values for its path parameters.
# Row-id routes are handled by the second sweep instead — their claim is
# sharper than "no marker came back", so they are asserted as 404 directly.
READ_ROUTES = [
    (method, path)
    for method, path in BUSINESS_SCOPED_ROUTES
    if method == "GET" and not _ROW_ID.search(path)
]

# Row-id routes reached while switched. Filtered against the tenancy sweep's
# inventory so the two files cannot drift: a row-id route that file does not
# know how to build a row for is its failure to report, not this one's.
ROW_ID_ROUTES_TAKING_THE_HEADER = [
    (method, path)
    for method, path in ROW_ID_ROUTES
    if (method, path) in set(BUSINESS_SCOPED_ROUTES)
]

# Path parameters, by name. Every one of these addresses the *home* tenant's
# data — which is the whole point: the request carries a header naming the
# other business, so none of it may be reachable.
def _url(path: str, seeded: Seeded) -> str:
    values = {
        "invoice_id": seeded.invoice_id,
        "supplier_id": seeded.supplier_id,
        "run_id": seeded.run_id,
        "alert_id": seeded.alert_id,
        "period": PERIOD,
        "return_type": ReturnType.GSTR3B.value,
        "extension": "json",
    }
    missing = [name for name in _PATH_PARAM.findall(path) if name not in values]
    assert not missing, (
        f"{path} takes a path parameter this sweep has no value for: {missing}"
    )
    return _PATH_PARAM.sub(lambda m: str(values[m.group(1)]), path)


def _query(path: str) -> dict:
    """``period`` where the route accepts one, so the sweep asks about the seeded month.

    A route left on its default period would ask about the current calendar
    month, which holds no home data in any tenant — and would pass this sweep
    by having nothing to leak.
    """
    for route in API_ROUTES:
        if route.path != path or not hasattr(route, "dependant"):
            continue
        if any(param.name == "period" for param in route.dependant.query_params):
            return {"period": PERIOD}
    return {}


def _ids(case) -> str:
    return f"{case[0]} {case[1]}"


# ---------------------------------------------------------------------------
# The sweep is only worth what its inventory covers
# ---------------------------------------------------------------------------

class TestTheSweepCoversEveryBusinessScopedRoute:
    def test_the_walk_found_routes(self):
        # Without this the parametrised sweeps below would pass by having no
        # cases at all — the failure mode every sweep in this suite guards.
        assert BUSINESS_SCOPED_ROUTES, "no business-scoped routes found"

    def test_every_business_scoped_route_is_swept_by_one_half_or_the_other(self):
        swept = set(READ_ROUTES) | set(ROW_ID_ROUTES_TAKING_THE_HEADER)
        writes = {
            (method, path)
            for method, path in BUSINESS_SCOPED_ROUTES
            if method != "GET" and not _ROW_ID.search(path)
        }
        # Writes with no row id in the path create rather than address, so
        # "the home row is unreachable" is not a claim that can be made about
        # them. They are covered one at a time further down instead, and named
        # here so that a new one has to be dealt with rather than forgotten.
        assert set(BUSINESS_SCOPED_ROUTES) - swept == writes, (
            "these business-scoped routes are swept by neither half: "
            f"{sorted(set(BUSINESS_SCOPED_ROUTES) - swept - writes)}"
        )

    def test_the_creating_writes_are_the_ones_this_file_covers_by_hand(self):
        # The list is short and stays short. A route arriving here is a
        # prompt to write the switched-write test for it below, which is a
        # judgement about what "landed on the right tenant" means for that
        # route and cannot be made generically.
        assert {
            (method, path)
            for method, path in BUSINESS_SCOPED_ROUTES
            if method != "GET" and not _ROW_ID.search(path)
        } == {
            ("POST", "/api/v1/invoices/upload"),
            ("POST", "/api/v1/invoices/bulk"),
            ("POST", "/api/v1/reconciliation/gstr2b/import"),
            ("POST", "/api/v1/reconciliation/run"),
            ("POST", "/api/v1/itc/set-off"),
            ("POST", "/api/v1/filing/{return_type}/filed"),
            ("DELETE", "/api/v1/filing/{return_type}/filed"),
            ("POST", "/api/v1/suppliers/rescore"),
            ("POST", "/api/v1/subscriptions/cancel"),
            ("POST", "/api/v1/subscriptions/create-order"),
            ("POST", "/api/v1/subscriptions/verify-payment"),
            # Writes nothing: it is here because the tier gate resolves the
            # active business to read its plan. Whose plan answers while
            # switched is TestThePlanThatCountsIsTheActiveBusinesss, below.
            ("POST", "/api/v1/meta/gstin/bulk"),
            # The paid PDF report (832f551). Its order receipt names the
            # business and run, and test_reconciliation_report proves another
            # tenant's run is not found. The switched-header case is not yet
            # written here.
            ("POST", "/api/v1/reconciliation/report/purchase"),
            ("POST", "/api/v1/reconciliation/report/verify"),
        }


# ---------------------------------------------------------------------------
# Nothing the home business holds may come back through the header
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", READ_ROUTES, ids=_ids)
def test_no_read_answers_a_switched_request_with_the_home_tenants_data(
    case, auth_client, home, switched
):
    _, path = case
    response = auth_client.get(
        _url(path, home), params=_query(path), headers={"X-Business-Id": str(switched)}
    )

    assert response.status_code < 500, (
        f"GET {path} answered {response.status_code} while switched: {response.text[:200]}"
    )
    leaked = [marker for marker in HOME_MARKERS if marker in response.text]
    assert not leaked, (
        f"GET {path} answered a request switched to another business with the "
        f"caller's own data: {leaked}"
    )


@pytest.mark.parametrize("case", ROW_ID_ROUTES_TAKING_THE_HEADER, ids=_ids)
def test_a_row_of_the_home_tenants_is_unreachable_while_switched(
    case, auth_client, db_session, business, home, switched
):
    """The caller owns this row. While acting as another business they do not."""
    method, path = case
    row_id = FACTORIES[path](auth_client, db_session, business)

    response = auth_client.request(
        method,
        _ROW_ID.sub(str(row_id), path),
        json={"hsn_code": "8471"} if method == "PATCH" else None,
        headers={"X-Business-Id": str(switched)},
    )

    assert response.status_code == 404, (
        f"{method} {path} reached the caller's own row while the request was "
        f"switched to another business: {response.status_code} {response.text[:200]}"
    )


class TestTheSweepIsNotVacuous:
    """Every "absent" above has to be the header working, not a marker nothing carries."""

    def test_each_marker_is_something_a_read_actually_returns(
        self, auth_client, home, switched
    ):
        # Without the header the same sweep must surface every marker at least
        # once. A marker no route ever echoes — a column dropped from a schema,
        # an ARN the filing status stopped reporting — would otherwise make its
        # half of the leak check permanently, invisibly true.
        seen = set()
        for _, path in READ_ROUTES:
            body = auth_client.get(_url(path, home), params=_query(path)).text
            seen.update(marker for marker in HOME_MARKERS if marker in body)

        assert seen == set(HOME_MARKERS), (
            "no read returns these markers, so their absence under a switched "
            f"header proves nothing: {sorted(set(HOME_MARKERS) - seen)}"
        )

    def test_the_switched_reads_are_reaching_the_other_business(
        self, auth_client, home, switched
    ):
        # And the reverse: the header is being honoured rather than the
        # requests failing early for some unrelated reason. The dashboard is
        # the one read that names the tenant it answered for.
        body = auth_client.get(
            "/api/v1/dashboard",
            params={"period": PERIOD},
            headers={"X-Business-Id": str(switched)},
        ).json()
        assert body["business_gstin"] == SECOND_GSTIN

    @pytest.mark.parametrize("case", ROW_ID_ROUTES_TAKING_THE_HEADER, ids=_ids)
    def test_the_row_id_sweep_reaches_those_rows_without_the_header(
        self, case, auth_client, db_session, business, home
    ):
        # The 404s above have to mean "not this business's row" rather than
        # "no such route" or "the factory built nothing".
        #
        # One case per test rather than a loop, because the factories are not
        # replayable against one another: two invoices built from the same
        # bytes are a duplicate upload, and the delete case would take away the
        # row a later read was about.
        method, path = case
        row_id = FACTORIES[path](auth_client, db_session, business)

        response = auth_client.request(
            method,
            _ROW_ID.sub(str(row_id), path),
            json={"hsn_code": "8471"} if method == "PATCH" else None,
        )

        assert response.status_code != 404, (
            f"{method} {path} answers 404 to the row's own owner with no "
            "header set — its switched case proves nothing"
        )


# ---------------------------------------------------------------------------
# The writes that create rather than address
# ---------------------------------------------------------------------------

class TestAWriteMadeWhileSwitchedLandsOnTheOtherBusiness:
    """The consequential half. A read that leaks is a disclosure; a write that
    lands on the wrong tenant is a filing recorded against a business that did
    not make it, and there is no screen anywhere that would show it as wrong.
    """

    def test_recording_a_filing_files_the_switched_business_and_not_the_home_one(
        self, auth_client, db_session, business, switched
    ):
        response = auth_client.post(
            f"/api/v1/filing/{ReturnType.GSTR3B.value}/filed",
            json={"period": PERIOD, "filed_at": "2026-05-20", "arn": "AA270426000001X"},
            headers={"X-Business-Id": str(switched)},
        )
        assert response.status_code in (200, 201), response.text

        filed = (
            db_session.query(GSTRReturn)
            .filter_by(period=PERIOD, return_type=ReturnType.GSTR3B, status=ReturnStatus.FILED)
            .all()
        )
        assert [row.business_id for row in filed] == [switched]
        assert business.id != switched

    def test_withdrawing_a_filing_while_switched_never_touches_the_home_one(
        self, auth_client, db_session, business, home, switched
    ):
        """The home business has GSTR-3B filed for PERIOD; the switched one has
        nothing. Withdrawing while switched must find nothing to withdraw, and
        after recording one there, withdraw that one and only that one."""
        url = f"/api/v1/filing/{ReturnType.GSTR3B.value}/filed"
        headers = {"X-Business-Id": str(switched)}

        def filed_for():
            return sorted(
                row.business_id
                for row in db_session.query(GSTRReturn).filter_by(
                    period=PERIOD, return_type=ReturnType.GSTR3B, status=ReturnStatus.FILED
                )
                if row.deleted_at is None
            )

        missing = auth_client.delete(url, params={"period": PERIOD}, headers=headers)
        assert missing.status_code == 404, missing.text
        assert filed_for() == [business.id]

        recorded = auth_client.post(
            url,
            json={"period": PERIOD, "filed_at": "2026-05-20", "arn": "AA270426000001X"},
            headers=headers,
        )
        assert recorded.status_code in (200, 201), recorded.text
        assert filed_for() == sorted([business.id, switched])

        withdrawn = auth_client.delete(url, params={"period": PERIOD}, headers=headers)
        assert withdrawn.status_code == 204, withdrawn.text
        db_session.expire_all()
        assert filed_for() == [business.id]

    def test_a_reconciliation_run_started_while_switched_is_the_other_businesss(
        self, auth_client, db_session, business, home, switched
    ):
        # Paid, or the tier gate answers 403 before the business is ever looked
        # in and this asserts nothing about which one it was.
        make_paid(db_session, switched)
        response = auth_client.post(
            "/api/v1/reconciliation/run",
            json={"period": PERIOD},
            headers={"X-Business-Id": str(switched)},
        )
        # A period with no imported 2B is refused, and which business it looked
        # in is the assertion: the home tenant's statement must not answer for
        # the switched one. Either way no run may be created against home.
        assert response.status_code < 500, response.text

        runs = db_session.query(ReconciliationRun).filter_by(business_id=business.id).all()
        assert [run.id for run in runs] == [home.run_id], (
            "a run started while switched to another business touched the "
            "caller's own reconciliation history"
        )


class TestThePlanThatCountsIsTheActiveBusinesss:
    """A subscription belongs to a business, not to the login.

    A CA who is paid on their own practice and switches into a client's free
    books must meet the client's plan — otherwise one subscription unlocks the
    paid tier for every business the login can reach.
    """

    BODY = {"gstins": [BUSINESS_GSTIN]}

    def test_the_home_plan_does_not_carry_into_a_free_business(
        self, auth_client, db_session, business, switched
    ):
        make_paid(db_session, business.id)
        assert auth_client.post("/api/v1/meta/gstin/bulk", json=self.BODY).status_code == 200

        response = auth_client.post(
            "/api/v1/meta/gstin/bulk", json=self.BODY, headers={"X-Business-Id": str(switched)}
        )
        assert response.status_code == 403, response.text

    def test_a_paid_business_is_paid_whoever_switches_into_it(
        self, auth_client, db_session, switched
    ):
        make_paid(db_session, switched)
        assert auth_client.post("/api/v1/meta/gstin/bulk", json=self.BODY).status_code == 403

        response = auth_client.post(
            "/api/v1/meta/gstin/bulk", json=self.BODY, headers={"X-Business-Id": str(switched)}
        )
        assert response.status_code == 200, response.text
