"""The role on a login decided nothing until this file existed.

``UserRole`` has been stored since the first migration, returned by
``/auth/me``, carried over onto a linked business by ``POST
/businesses/mine/link``, and displayed in the business switcher. Nothing read
it. A ``viewer`` — the role a business gives the person it wants to *show* the
books to — could upload invoices, patch the figures on one, delete it, import
a GSTR-2B over the statement a reconciliation had already run against, and
record a return as filed, which silences the deadline alert for a filing that
never happened.

Two properties are asserted here, and the second is the one a per-router habit
would get wrong:

* A read-only role is refused every write. :class:`TestEveryMutatingRouteIsGated`
  sweeps that off the assembled route table rather than trusting the list of
  routes that happen to be gated today.
* The role that decides is the role *on the business being acted for*, not the
  role on the login. An owner of their own books who has been linked into a
  client's as a viewer is a viewer there, and the reverse — a viewer at home
  who owns a linked business — must not be locked out of books they own.
"""
from __future__ import annotations

import re
from datetime import date
from io import BytesIO

import pytest
from sqlalchemy import event, select

from app.core.deps import RequireRole
from app.models.business_membership import BusinessMembership, MembershipRole
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.user import User, UserRole
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE, TEST_EMAIL
from tests.test_businesses import link, register_second_business
from tests.test_route_contracts import API_ROUTES

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


# ---------------------------------------------------------------------------
# Fixtures: a login whose role is something other than owner
# ---------------------------------------------------------------------------

def set_home_role(db_session, role: UserRole) -> None:
    """Give the ``auth_client`` login *role* on its own business.

    Registration always mints an owner — one sign-up is one registration and
    the person doing it is the person who holds it — so there is no API that
    produces a viewer on their *own* tenant today. The column is what the
    product means by the role, and it is read on every request, so setting it
    directly is testing the mechanism rather than working around it.
    """
    user = db_session.scalar(select(User).where(User.email == TEST_EMAIL))
    user.role = role
    db_session.commit()


@pytest.fixture()
def viewer(auth_client, db_session):
    """``auth_client``, demoted to a read-only role on its own business."""
    set_home_role(db_session, UserRole.VIEWER)
    return auth_client


@pytest.fixture()
def seeded_invoice(db_session, business) -> int:
    """One parsed purchase invoice, written directly.

    Not uploaded through the API: the upload route is one of the things under
    test here, and a fixture that has to be an owner to build the row a viewer
    is then refused would tie every assertion below to the order the role is
    changed in.
    """
    invoice = Invoice(
        business_id=business.id,
        invoice_type=InvoiceType.PURCHASE,
        status=InvoiceStatus.PARSED,
        invoice_number="RBAC-1",
        invoice_date=date(2026, 4, 15),
        period="2026-04",
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Northwind Supplies",
    )
    db_session.add(invoice)
    db_session.commit()
    return invoice.id


def _file(name: str = "bill.txt"):
    return {"file": (name, BytesIO(b"TAX INVOICE\nTotal: 100.00\n"), "text/plain")}


# ---------------------------------------------------------------------------
# What a read-only role may not do
# ---------------------------------------------------------------------------

class TestAViewerIsRefusedEveryWrite:
    """The five routes R25 named, plus the rest of the write surface."""

    def test_a_viewer_cannot_patch_an_invoice(self, viewer, seeded_invoice):
        response = viewer.patch(
            f"/api/v1/invoices/{seeded_invoice}", json={"invoice_number": "TAMPERED"}
        )
        assert response.status_code == 403, response.text

    def test_the_figures_are_genuinely_unchanged(
        self, viewer, seeded_invoice, db_session
    ):
        """A 403 that still wrote the row would pass the assertion above."""
        viewer.patch(
            f"/api/v1/invoices/{seeded_invoice}", json={"invoice_number": "TAMPERED"}
        )
        db_session.expire_all()
        assert db_session.get(Invoice, seeded_invoice).invoice_number == "RBAC-1"

    def test_a_viewer_cannot_record_a_return_as_filed(self, viewer):
        # The write with the worst failure mode in the product: recording a
        # filing that did not happen stops the deadline alert for a return
        # that is genuinely late, and late GSTR-3B carries interest per day.
        response = viewer.post(
            "/api/v1/filing/gstr3b/filed",
            json={"period": "2026-04", "arn": "AA270426000000X"},
        )
        assert response.status_code == 403, response.text

    def test_a_viewer_cannot_upload_an_invoice(self, viewer):
        response = viewer.post(
            "/api/v1/invoices/upload", files=_file(), data={"invoice_type": "purchase"}
        )
        assert response.status_code == 403, response.text

    def test_a_viewer_cannot_upload_a_batch(self, viewer):
        response = viewer.post(
            "/api/v1/invoices/bulk",
            files=[("files", ("a.txt", BytesIO(b"TAX INVOICE"), "text/plain"))],
        )
        assert response.status_code == 403, response.text

    def test_a_viewer_cannot_delete_an_invoice(self, viewer, seeded_invoice):
        assert viewer.delete(f"/api/v1/invoices/{seeded_invoice}").status_code == 403

    def test_a_viewer_cannot_reparse_an_invoice(self, viewer, seeded_invoice):
        response = viewer.post(f"/api/v1/invoices/{seeded_invoice}/reparse")
        assert response.status_code == 403, response.text

    def test_a_viewer_cannot_import_a_gstr2b(self, viewer):
        # Re-importing soft-deletes the statement a reconciliation already ran
        # against, so this is destructive as well as a write.
        response = viewer.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={"file": ("2b.json", BytesIO(b"{}"), "application/json")},
            data={"period": "2026-04"},
        )
        assert response.status_code == 403, response.text

    def test_a_viewer_cannot_run_a_reconciliation(self, viewer):
        response = viewer.post(
            "/api/v1/reconciliation/run", json={"period": "2026-04"}
        )
        assert response.status_code == 403, response.text

    def test_a_viewer_cannot_rescore_suppliers(self, viewer):
        assert viewer.post("/api/v1/suppliers/rescore").status_code == 403

    def test_a_viewer_cannot_dismiss_an_alert(self, viewer, db_session, business):
        """Dismissal is a decision on behalf of the whole business.

        An alert's status is a column on the tenant's row, not a per-user
        read receipt: dismissing one stops the daily sweep raising it for
        *everybody*. So the person shown the books cannot be the one who
        decides the business already knows about a deadline.
        """
        from app.models.alert import Alert, AlertSeverity, AlertStatus, AlertType

        alert = Alert(
            business_id=business.id,
            alert_type=AlertType.FILING_DEADLINE,
            severity=AlertSeverity.WARNING,
            status=AlertStatus.PENDING,
            title="GSTR-3B for 2026-04 is due",
            message="File it by 20 May 2026.",
        )
        db_session.add(alert)
        db_session.commit()

        assert viewer.post(f"/api/v1/alerts/{alert.id}/dismiss").status_code == 403
        assert viewer.post(f"/api/v1/alerts/{alert.id}/read").status_code == 403


class TestTheRefusalIsUsable:
    """A 403 nobody can act on sends the user to support instead of to an owner."""

    def test_it_names_the_role_the_caller_actually_holds(self, viewer, seeded_invoice):
        detail = viewer.patch(
            f"/api/v1/invoices/{seeded_invoice}", json={"paid_at": "2026-05-01"}
        ).json()["detail"]
        assert "viewer" in detail
        # The reader cannot change what the route demands; they can ask
        # somebody who holds more. So the sentence has to name that somebody.
        assert "owner" in detail and "accountant" in detail

    def test_it_carries_the_shared_error_envelope(self, viewer, seeded_invoice):
        body = viewer.delete(f"/api/v1/invoices/{seeded_invoice}").json()
        assert body["error"]["code"] == "forbidden"
        assert body["error"]["status"] == 403
        assert body["correlation_id"]

    def test_the_token_is_not_treated_as_dead(self, viewer, seeded_invoice):
        """A role refusal must not read as an expired session.

        The frontend drops the bearer token on a 401 and deliberately does not
        on a 403 (see ``request`` in ``lib/api.js``). Answering 401 here would
        sign a viewer out every time they clicked a button they cannot use.
        """
        assert viewer.delete(f"/api/v1/invoices/{seeded_invoice}").status_code != 401
        # And the session still works afterwards.
        assert viewer.get("/api/v1/invoices").status_code == 200

    def test_the_refusal_does_not_depend_on_the_row_existing(self, viewer):
        """403 here leaks nothing, which is why it is not the tenancy 404.

        Cross-tenant reads answer 404 so that a refusal cannot confirm another
        business's id exists. This refusal is decided before any id is looked
        up and is identical for a real row, another tenant's row and a row
        nobody has ever created — so it distinguishes none of them.
        """
        assert viewer.patch("/api/v1/invoices/999999", json={}).status_code == 403
        assert viewer.delete("/api/v1/invoices/999999").status_code == 403

    def test_an_owner_still_gets_the_404_for_the_same_id(self, auth_client):
        # Guards the test above from passing for the wrong reason: if every
        # caller got a 403 for a missing id, it would prove nothing about roles.
        assert auth_client.delete("/api/v1/invoices/999999").status_code == 404


class TestAViewerCanStillRead:
    """Read-only is the role's purpose, not a synonym for locked out."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/invoices",
            "/api/v1/dashboard",
            "/api/v1/suppliers",
            "/api/v1/alerts",
            "/api/v1/itc",
            "/api/v1/filing/validate?period=2026-04",
            "/api/v1/reconciliation",
            "/api/v1/businesses/mine",
            "/api/v1/auth/me",
        ],
    )
    def test_the_read_surface_is_untouched(self, viewer, paid_business, path):
        # Paid, so a tier-gated read (``/itc``) answers for the role alone.
        assert viewer.get(path).status_code == 200, path

    def test_a_viewer_may_read_one_invoice(self, viewer, seeded_invoice):
        assert viewer.get(f"/api/v1/invoices/{seeded_invoice}").status_code == 200

    def test_the_set_off_calculator_is_still_open_to_them(self, viewer):
        """A POST that reads no row and writes none is not a write.

        ``/itc/set-off`` is arithmetic over numbers in the request body — the
        what-if a CA runs against figures that are not in the books yet. Gating
        it on the write role would refuse a viewer the one thing a viewer is
        for, on the strength of the HTTP verb alone.
        """
        response = viewer.post(
            "/api/v1/itc/set-off",
            json={
                "credit_igst": "100.00", "credit_cgst": "0.00",
                "credit_sgst": "0.00", "credit_cess": "0.00",
                "liability_igst": "50.00", "liability_cgst": "0.00",
                "liability_sgst": "0.00", "liability_cess": "0.00",
            },
        )
        assert response.status_code == 200, response.text


class TestAnAccountantHasTheWholeWriteSurface:
    """The role an outside CA holds, and the reason owner is not the gate.

    Separating owner from accountant on filing would be routed around by
    sharing the owner's password, which is strictly worse for the business
    than granting the role. The line this product draws is at touching the
    books at all.
    """

    @pytest.fixture()
    def accountant(self, auth_client, db_session):
        set_home_role(db_session, UserRole.ACCOUNTANT)
        return auth_client

    def test_an_accountant_may_patch_an_invoice(self, accountant, seeded_invoice):
        response = accountant.patch(
            f"/api/v1/invoices/{seeded_invoice}", json={"invoice_number": "RBAC-2"}
        )
        assert response.status_code == 200, response.text

    def test_an_accountant_may_record_a_filing(self, accountant):
        response = accountant.post(
            "/api/v1/filing/gstr3b/filed", json={"period": "2026-04"}
        )
        assert response.status_code == 201, response.text

    def test_an_accountant_may_upload(self, accountant):
        response = accountant.post(
            "/api/v1/invoices/upload", files=_file(), data={"invoice_type": "purchase"}
        )
        assert response.status_code == 201, response.text

    def test_an_owner_is_unaffected(self, auth_client, seeded_invoice):
        """The default role, and the one every existing session holds."""
        response = auth_client.patch(
            f"/api/v1/invoices/{seeded_invoice}", json={"invoice_number": "RBAC-3"}
        )
        assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# Which business the role is read from
# ---------------------------------------------------------------------------

def _membership(db_session, business_id: int) -> BusinessMembership:
    return db_session.scalar(
        select(BusinessMembership).where(
            BusinessMembership.business_id == business_id,
            BusinessMembership.deleted_at.is_(None),
        )
    )


class TestTheRoleIsTheOneOnTheBusinessBeingActedFor:
    """The failure a login-level role check would have shipped with.

    ``X-Business-Id`` lets one login act for a business it does not own, and
    the membership carries its own role for exactly this reason. A check that
    read ``current_user.role`` would apply an accountant's authority over their
    own books to every client they have been linked into — and would lock the
    owner of a linked registration out of books that are theirs.
    """

    @pytest.fixture()
    def linked(self, auth_client, client):
        """A second business this login can act for, and its id."""
        second = register_second_business(client)
        assert link(auth_client).status_code == 201
        return second["business"]["id"]

    def _switched(self, business_id: int) -> dict[str, str]:
        return {"X-Business-Id": str(business_id)}

    def test_an_owner_at_home_who_is_a_viewer_on_a_client_cannot_write_there(
        self, auth_client, db_session, linked
    ):
        _membership(db_session, linked).role = MembershipRole.VIEWER
        db_session.commit()

        response = auth_client.post(
            "/api/v1/invoices/upload",
            files=_file(),
            data={"invoice_type": "purchase"},
            headers=self._switched(linked),
        )
        assert response.status_code == 403, response.text
        assert "viewer" in response.json()["detail"]

    def test_and_is_still_an_owner_on_their_own_books(
        self, auth_client, db_session, linked
    ):
        """The same request without the header must be unaffected."""
        _membership(db_session, linked).role = MembershipRole.VIEWER
        db_session.commit()

        response = auth_client.post(
            "/api/v1/invoices/upload", files=_file(), data={"invoice_type": "purchase"}
        )
        assert response.status_code == 201, response.text

    def test_a_viewer_at_home_who_owns_a_linked_business_may_write_there(
        self, auth_client, db_session, linked
    ):
        """The other direction, which a login-level check would get wrong.

        The membership was created as ``owner`` — ``link_business`` carries the
        *other* account's role over, and that account registered its own
        GSTIN — so this login owns the linked books while holding a read-only
        role on its own.
        """
        assert _membership(db_session, linked).role is MembershipRole.OWNER
        set_home_role(db_session, UserRole.VIEWER)

        response = auth_client.post(
            "/api/v1/invoices/upload",
            files=_file(),
            data={"invoice_type": "purchase"},
            headers=self._switched(linked),
        )
        assert response.status_code == 201, response.text

        # And is still refused at home, so the switch is what changed it.
        refused = auth_client.post(
            "/api/v1/invoices/upload", files=_file("other.txt"),
            data={"invoice_type": "purchase"},
        )
        assert refused.status_code == 403, refused.text

    def test_unlinking_removes_the_authority_with_the_access(
        self, auth_client, linked
    ):
        # Not a role refusal: without a live membership the header names a
        # business this login cannot reach at all.
        assert auth_client.delete(f"/api/v1/businesses/mine/{linked}").status_code == 204
        response = auth_client.post(
            "/api/v1/invoices/upload",
            files=_file(),
            data={"invoice_type": "purchase"},
            headers=self._switched(linked),
        )
        assert response.status_code == 403
        assert "access to that business" in response.json()["detail"]


class TestTheRoleCostsNoExtraQuery:
    """Resolving authority must not double the membership lookup.

    The role travels on the same object as the business precisely so it is one
    query. FastAPI caches a dependency per request by the callable that
    declares it, so a route depending on both ``get_current_business`` and
    ``require_writer`` resolves ``get_active_tenant`` once — but only while
    both really go through it. A second resolver added later would be
    invisible except here.
    """

    @staticmethod
    def _membership_reads(db_session, call) -> int:
        reads: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            squashed = " ".join(statement.split()).lower()
            if squashed.startswith("select") and "from business_memberships" in squashed:
                reads.append(squashed)

        engine = db_session.get_bind()
        event.listen(engine, "before_cursor_execute", _record)
        try:
            call()
        finally:
            event.remove(engine, "before_cursor_execute", _record)
        return len(reads)

    def test_a_switched_write_reads_the_membership_once(
        self, auth_client, client, db_session
    ):
        register_second_business(client)
        assert link(auth_client).status_code == 201
        linked = db_session.scalar(
            select(BusinessMembership.business_id).where(
                BusinessMembership.deleted_at.is_(None)
            )
        )

        def _upload():
            response = auth_client.post(
                "/api/v1/invoices/upload",
                files=_file(),
                data={"invoice_type": "purchase"},
                headers={"X-Business-Id": str(linked)},
            )
            assert response.status_code == 201, response.text

        assert self._membership_reads(db_session, _upload) == 1


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------

# Mutating routes that deliberately carry no role gate. Adding to this list is
# a security decision — it says a read-only session may perform this write —
# and each entry says why it is not one.
UNGATED_MUTATIONS = {
    # There is no session yet, so there is no role to read.
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    # These two manage *this login's* access, not any business's books. They
    # resolve through ``get_current_user`` and never through a tenant, and
    # linking is proven by the other account's own password — a role on some
    # third business has no bearing on either. Refusing a viewer the ability to
    # unlink would also trap them in a business they want to leave.
    "/api/v1/businesses/mine/link",
    "/api/v1/businesses/mine/{business_id}",
    # Arithmetic over the request body. No row is read and none is written, so
    # the verb is the only thing about it that resembles a write; see
    # ``TestAViewerCanStillRead.test_the_set_off_calculator_is_still_open_to_them``.
    "/api/v1/itc/set-off",
    # Called by Razorpay's servers, not by users — authenticated by webhook
    # signature, not by a bearer token.
    "/api/v1/subscriptions/webhook",
    # Email capture from the landing page — no session exists yet.
    "/api/v1/meta/reminder-subscribe",
    # Public email capture for filing-deadline reminders.
    "/api/v1/subscribers",
    # WhatsApp webhook — called by Twilio / WhatsApp servers, authenticated
    # by webhook signature rather than a bearer token.
    "/api/v1/whatsapp/webhook",
    # Anonymous product feedback — no session exists.
    "/api/v1/feedback",
    # Uncaught browser errors, reported by the page on its own.
    "/api/v1/feedback/error",
    # AI advisor chatbot — public, no session exists.
    "/api/v1/advisor/ask",
    "/api/v1/advisor/ask/stream",
    # CA referral tracking — public, records a visit by hashed IP.
    "/api/v1/referrals/track",
    # GPT Actions invoice — arithmetic over the body, like ``/itc/set-off``;
    # nothing is read or stored, and there is no session to hold a role.
    "/api/v1/gpt/invoice",
    # Bulk GSTIN validation — gated by subscription tier, not by role. Any
    # paid user can validate GSTINs regardless of whether they are a viewer
    # or an owner; the gate is the subscription, not the authority.
    "/api/v1/meta/gstin/bulk",
    # Site-admin housekeeping (ADMIN_EMAILS), not a business's data: no
    # business role reaches these, the owner's included.
    "/api/v1/feedback/{feedback_id}",
    "/api/v1/feedback/errors/{error_id}",
}


class TestEveryMutatingRouteIsGated:
    """A new write endpoint cannot ship ungated without this going red.

    The same shape as the three sweeps in ``test_tenancy_contract.py`` and
    ``test_request_guards.py``, and for the same reason: authorisation was
    about to become a fourth per-router habit, and the routes it is easiest to
    forget on are the ones added last.
    """

    @staticmethod
    def _calls(dependant):
        yield dependant.call
        for sub in dependant.dependencies:
            yield from TestEveryMutatingRouteIsGated._calls(sub)

    @classmethod
    def _mutating(cls):
        return [
            route
            for route in API_ROUTES
            # tests/test_errors.py mounts a router on the shared app and
            # whether it is here depends on import order — the other sweeps
            # drop the same prefix.
            if not route.path.startswith("/_") and (route.methods or set()) & MUTATING
        ]

    def test_no_mutating_route_outside_the_list_is_ungated(self):
        ungated = {
            route.path
            for route in self._mutating()
            if not any(isinstance(call, RequireRole) for call in self._calls(route.dependant))
        }
        assert ungated <= UNGATED_MUTATIONS, (
            "writes a read-only session could perform: "
            + ", ".join(sorted(ungated - UNGATED_MUTATIONS))
        )

    def test_the_sweep_is_reading_real_routes(self):
        """A walk that found nothing would pass the assertion above."""
        gated = [
            route
            for route in self._mutating()
            if any(isinstance(call, RequireRole) for call in self._calls(route.dependant))
        ]
        # Eleven today: five on invoices, two each on alerts and
        # reconciliation, one each on filing and suppliers. A floor rather
        # than an equality — the number only ever goes up, and a sweep that
        # had to be edited to add a route is one people edit without reading.
        assert len(gated) >= 11, f"only {len(gated)} routes look gated"

    def test_the_ungated_list_has_not_gone_stale(self):
        """Every exemption must still name a route that exists."""
        paths = {route.path for route in self._mutating()}
        assert paths >= UNGATED_MUTATIONS, (
            "exemptions for routes that no longer exist: "
            + ", ".join(sorted(UNGATED_MUTATIONS - paths))
        )

    def test_every_gated_route_also_resolves_a_tenant(self):
        """A role is meaningless without the business it is held on.

        ``require_writer`` reads the role off ``get_active_tenant``, so a
        gated route that never resolved a tenant would be a contradiction —
        and the two are the same dependency, so this pins that they stay so.
        """
        from app.core.deps import get_current_business, get_current_user

        for route in self._mutating():
            calls = set(self._calls(route.dependant))
            if any(isinstance(call, RequireRole) for call in calls):
                assert {get_current_business, get_current_user} & calls, route.path

    def test_a_gate_that_admits_a_viewer_does_not_count_as_gated(self):
        """The presence of the dependency is not the property that matters.

        Every assertion above asks whether a ``RequireRole`` is on the route,
        and ``RequireRole(UserRole.VIEWER)`` is one: it constructs, it reads
        the tenant, and its comparison is ``_RANK[viewer] < _RANK[viewer]``,
        which is false for everyone. A route carrying it would satisfy the
        whole sweep while admitting exactly the role the sweep exists to
        refuse. So the minimum is checked, not just the type.
        """
        for route in self._mutating():
            for call in self._calls(route.dependant):
                if isinstance(call, RequireRole):
                    assert call.minimum is not UserRole.VIEWER, (
                        f"{route.path} carries a gate that refuses nobody"
                    )


# The value substituted for each path parameter on the sweep below. None of
# them has to name a row that exists: the refusal is decided before any id is
# looked up, which is the point ``TestTheRefusalIsUsable`` makes at length. A
# real ``return_type`` is used anyway so that the owner half of the sweep
# fails on something other than the enum.
SWEEP_PATH_VALUES = {
    "return_type": "gstr1",
    "extension": "json",
}
SWEEP_DEFAULT_ID = "999999"

_PATH_PARAM = re.compile(r"\{(\w+)\}")


def _fill(path: str) -> str:
    return _PATH_PARAM.sub(
        lambda m: SWEEP_PATH_VALUES.get(m.group(1), SWEEP_DEFAULT_ID), path
    )


def _gated_calls() -> list[tuple[str, str]]:
    """Every ``(method, path)`` the role gate is supposed to refuse a viewer.

    Module level rather than a classmethod because ``parametrize`` is evaluated
    while the class body is still executing, so the class does not yet have a
    name to call it through.
    """
    return [
        (method, route.path)
        for route in TestEveryMutatingRouteIsGated._mutating()
        if route.path not in UNGATED_MUTATIONS
        for method in sorted((route.methods or set()) & MUTATING)
    ]


GATED_CALLS = _gated_calls()
GATED_IDS = [f"{method} {path}" for method, path in GATED_CALLS]


class TestEveryGatedRouteRefusesARealViewer:
    """The sweep above reads the route table; this one drives it.

    They fail for different reasons and that is why both exist. The static
    sweep catches the route that shipped without a gate — it can see a route
    nobody thought to test. It cannot see whether the gate *works*: it reads
    declarations, and a dependency can be declared and still let the request
    through, by ordering, by an override left installed, or by the wrong
    minimum. This one asks the assembled application the question the product
    actually promises an answer to — a viewer's session, a real request, a
    403 — for every gated route rather than the eleven somebody listed.
    """

    def test_the_sweep_found_the_write_surface(self):
        """A parametrize over an empty list passes every case it has."""
        assert len(GATED_CALLS) >= 11, f"only {len(GATED_CALLS)} gated calls found"

    @pytest.mark.parametrize(("method", "path"), GATED_CALLS, ids=GATED_IDS)
    def test_the_viewer_is_refused(self, viewer, method, path):
        """No body is sent on purpose.

        The gate is a sub-dependency, so it is solved before the route's own
        body and path parameters are read. A viewer who could reach the 422
        would be a viewer whose request had already been let past the role,
        and sending nothing is the shortest way to say that a well-formed
        payload is not what stands between them and the write.
        """
        response = viewer.request(method, _fill(path))
        assert response.status_code == 403, (
            f"{method} {path} answered {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.parametrize(("method", "path"), GATED_CALLS, ids=GATED_IDS)
    def test_the_same_request_as_an_owner_is_not_a_403(
        self, auth_client, paid_business, method, path
    ):
        """What stops this file proving nothing.

        Every assertion above is "the viewer got a 403", and a route that 403s
        for *everybody* — a broken tenant lookup, a fixture that built no
        membership — would satisfy all of them while testing no role at all.
        The owner sends the same empty request, so the answer is a 404 or a
        422 rather than a 200; what matters is only that it is not the refusal
        the viewer got. The business is paid, so a route the subscription
        gates (``reconciliation/run``) cannot 403 the owner for the tier.
        """
        response = auth_client.request(method, _fill(path))
        assert response.status_code != 403, (
            f"{method} {path} refuses an owner too, so the viewer's 403 means nothing"
        )


class TestTheSpecSaysSoToo:
    """A client generated from the spec should know which calls a viewer loses."""

    @pytest.fixture(scope="class")
    def spec(self):
        from app.main import app

        return app.openapi()

    def test_every_gated_operation_documents_a_403(self, spec):
        from app.core.openapi import is_role_gated

        missing = [
            f"{method} {route.path}"
            for route in API_ROUTES
            if route.include_in_schema and is_role_gated(route)
            for method in sorted((route.methods or set()) & MUTATING)
            if "403"
            not in spec["paths"].get(route.path, {}).get(method.lower(), {}).get(
                "responses", {}
            )
        ]
        assert missing == [], "role-gated but no documented 403: " + ", ".join(missing)

    def test_a_read_route_does_not_advertise_the_role_403(self, spec):
        """The code is derived, so it must not appear where it cannot happen."""
        from app.core.openapi import FORBIDDEN

        listed = spec["paths"]["/api/v1/invoices"]["get"]["responses"]
        assert listed.get("403", {}).get("description") != FORBIDDEN["description"]

    def test_the_patch_route_carries_the_derived_wording(self, spec):
        from app.core.openapi import FORBIDDEN

        described = spec["paths"]["/api/v1/invoices/{invoice_id}"]["patch"]["responses"]
        assert described["403"]["description"] == FORBIDDEN["description"]


def test_the_business_switcher_still_reports_the_role_it_now_enforces(viewer):
    """``GET /businesses/mine`` was displaying a role that meant nothing.

    It is the same value the gate now reads, so the switcher's badge stops
    being decoration — which is the whole of what R25 flagged.
    """
    items = viewer.get("/api/v1/businesses/mine").json()["items"]
    home = next(item for item in items if item["is_home"])
    assert home["role"] == "viewer"
    assert home["gstin"] == BUSINESS_GSTIN


def test_the_gate_governs_existing_logins_rather_than_creating_them():
    """Guards a misreading: this is not an invitation flow.

    There is no endpoint that adds a second user to an existing business —
    sign-up is one GSTIN and one owner. A viewer today is a login whose row
    says so, or a membership carried over by ``POST /businesses/mine/link``.
    If an invite route is added later it will need a role on the payload, and
    this assertion is where that gets noticed.
    """
    paths = {route.path for route in API_ROUTES}
    assert not [path for path in paths if "invite" in path or "member" in path]
