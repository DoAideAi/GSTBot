"""Multi-GSTIN access: listing, linking, unlinking, and X-Business-Id.

A GSTIndia sign-up is one GSTIN, so a company or a practice with several
registrations ends up with several separate logins. This is the router that
lets one of those logins reach the others — see app/routers/businesses.py —
and the tests below cover the three moving parts: proving you hold the other
account's password before a link is created, listing what one login can now
act for, and the header that actually switches which business a request acts
as.
"""
from __future__ import annotations

import pytest
from sqlalchemy import event

from app.models.business import Business
from app.models.business_membership import BusinessMembership, MembershipRole
from app.models.user import User, UserRole
from app.services.gstin import compute_check_digit
from tests.conftest import BUSINESS_GSTIN, TEST_EMAIL, TEST_PASSWORD

SECOND_EMAIL = "owner-2@example.com"
SECOND_PASSWORD = "anothersecret123"
SECOND_GSTIN = "27AAGCB7383J2Z7"


def _valid_gstin(index: int) -> str:
    """A distinct checksum-valid GSTIN, for tests that need more than a couple.

    Registration is not the subject of these tests but the check digit is
    still enforced underneath them, so a made-up 15th character would fail on
    the GSTIN rather than on what is being asserted. Built rather than listed
    because a table of constants is one more thing to extend every time a test
    wants one more business.
    """
    # 2 state + 10 PAN (5 letters, 4 digits, 1 letter) + 1 entity + "Z" = 14.
    first14 = f"27AAGCB{7000 + index:04d}J1Z"
    return first14 + compute_check_digit(first14)


def register_second_business(client, *, email=SECOND_EMAIL, password=SECOND_PASSWORD,
                              gstin=SECOND_GSTIN):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "gstin": gstin,
            "legal_name": "Second Business Pvt Ltd",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def link(auth_client, *, email=SECOND_EMAIL, password=SECOND_PASSWORD):
    return auth_client.post(
        "/api/v1/businesses/mine/link", json={"email": email, "password": password}
    )


# ---------------------------------------------------------------------------
# GET /businesses/mine
# ---------------------------------------------------------------------------

class TestListingMyBusinesses:
    def test_a_fresh_login_sees_only_its_own_business(self, auth_client, business):
        body = auth_client.get("/api/v1/businesses/mine").json()
        assert [item["id"] for item in body["items"]] == [business.id]
        assert body["items"][0]["is_home"] is True
        assert body["items"][0]["gstin"] == BUSINESS_GSTIN

    def test_it_requires_authentication(self, client):
        assert client.get("/api/v1/businesses/mine").status_code == 401

    def test_a_linked_business_appears_alongside_the_home_one(
        self, auth_client, client, business
    ):
        register_second_business(client)
        link(auth_client)

        body = auth_client.get("/api/v1/businesses/mine").json()
        assert len(body["items"]) == 2
        assert {item["gstin"] for item in body["items"]} == {BUSINESS_GSTIN, SECOND_GSTIN}
        home = next(item for item in body["items"] if item["gstin"] == BUSINESS_GSTIN)
        linked = next(item for item in body["items"] if item["gstin"] == SECOND_GSTIN)
        assert home["is_home"] is True
        assert linked["is_home"] is False
        assert linked["role"] == "owner"

    def test_a_linked_business_that_was_deleted_drops_out_of_the_list(
        self, auth_client, client, business, db_session
    ):
        """The membership outlives the business it points at.

        Unlinking soft-deletes the membership; deleting the *business* does
        not, because the two are separate rows and nothing cascades a soft
        delete. So a live membership can point at a tombstone, and listing has
        to filter on the far side of the join rather than trusting that a
        membership implies a business worth showing.

        Left unfiltered this is not a cosmetic bug: the row is rendered by
        ``_out``, so a deleted registration keeps appearing in the tenant
        switcher, and picking it acts as a business that is supposed to be
        gone.
        """
        second = register_second_business(client)
        link(auth_client)
        assert len(auth_client.get("/api/v1/businesses/mine").json()["items"]) == 2

        deleted = db_session.get(Business, second["business"]["id"])
        deleted.soft_delete()
        db_session.commit()

        body = auth_client.get("/api/v1/businesses/mine").json()
        assert [item["id"] for item in body["items"]] == [business.id]
        # The membership is untouched — it is the listing that filters, not the
        # delete that cleaned up after itself.
        assert db_session.query(BusinessMembership).count() == 1

    def test_a_linked_business_that_was_suspended_drops_out_of_the_list(
        self, auth_client, client, business, db_session
    ):
        """Suspension hides it from the switcher exactly as deletion does.

        This is the half that used to be missed. Listing filtered
        ``deleted_at`` and stopped there, so a *suspended* registration stayed
        in the switcher while ``get_active_tenant`` — which checks both — 403'd
        every request made after picking it. The user clicked their own company
        and was told they had no access to it, with nothing on screen to
        explain why, and no way to tell it from a bug.
        """
        second = register_second_business(client)
        link(auth_client)
        assert len(auth_client.get("/api/v1/businesses/mine").json()["items"]) == 2

        suspended = db_session.get(Business, second["business"]["id"])
        suspended.is_active = False
        db_session.commit()

        body = auth_client.get("/api/v1/businesses/mine").json()
        assert [item["id"] for item in body["items"]] == [business.id]

    def test_a_suspended_home_business_drops_out_of_the_list_too(
        self, auth_client, business, db_session
    ):
        """The home half is filtered on the same predicate as the linked half.

        Not a symmetry for its own sake: ``get_active_tenant`` resolves the
        caller's own tenant through the same check, so a suspended home
        business is one every request 403s on. Listing it would offer the one
        entry in the switcher guaranteed to fail.
        """
        business.is_active = False
        db_session.commit()

        body = auth_client.get("/api/v1/businesses/mine").json()
        assert body["items"] == []

    def test_listing_costs_the_same_number_of_queries_at_one_link_and_at_many(
        self, auth_client, db_session, business
    ):
        """The listing must not read the businesses table once per membership.

        ``membership.business`` is a plain lazy relationship, so walking the
        memberships in a loop emits one SELECT per row. Nobody sees it at the
        two or three registrations a practice starts with, and the endpoint is
        on the critical path of every page load — the business switcher calls
        it — so the cost lands on a consultant with thirty client GSTINs and
        on nobody who would report it.

        Counting the reads at two sizes is what makes this a claim about the
        shape of the query rather than about a number that a schema change
        could shift for an unrelated reason. Same count at 1 as at 12, or the
        loop is back.
        """

        def _reads_of_businesses_for(link_count: int, first_gstin: int) -> int:
            user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
            # Only the memberships go: the businesses stay behind, so each
            # sizing needs GSTINs of its own or the second insert collides
            # with the first's rows on the unique index.
            db_session.query(BusinessMembership).delete()
            db_session.commit()
            for index in range(first_gstin, first_gstin + link_count):
                gstin = _valid_gstin(index)
                linked = Business(
                    gstin=gstin,
                    legal_name=f"Linked {index} Pvt Ltd",
                    state_code=gstin[:2],
                )
                db_session.add(linked)
                db_session.flush()
                db_session.add(
                    BusinessMembership(
                        user_id=user.id, business_id=linked.id, role=UserRole.OWNER
                    )
                )
            db_session.commit()

            # A real request opens its own session and shares nothing with the
            # rows just written. Without this the lazy loads are answered out
            # of the identity map, no SQL is emitted, and the N+1 the test
            # exists to catch is invisible to it.
            db_session.expunge_all()

            reads: list[str] = []

            def _record(conn, cursor, statement, parameters, context, executemany):
                squashed = " ".join(statement.split()).lower()
                if squashed.startswith("select") and "from businesses" in squashed:
                    reads.append(squashed)

            engine = db_session.get_bind()
            event.listen(engine, "before_cursor_execute", _record)
            try:
                response = auth_client.get("/api/v1/businesses/mine")
            finally:
                event.remove(engine, "before_cursor_execute", _record)

            assert response.status_code == 200, response.text
            assert len(response.json()["items"]) == link_count + 1
            return len(reads)

        at_one = _reads_of_businesses_for(1, first_gstin=0)
        at_twelve = _reads_of_businesses_for(12, first_gstin=100)
        assert at_one == at_twelve, (
            f"{at_one} reads of businesses for one link, {at_twelve} for twelve: "
            "the listing is loading each membership's business on its own."
        )


# ---------------------------------------------------------------------------
# POST /businesses/mine/link
# ---------------------------------------------------------------------------

class TestLinkingABusiness:
    def test_the_right_password_links_it(self, auth_client, client, db_session):
        register_second_business(client)
        response = link(auth_client)
        assert response.status_code == 201, response.text
        assert response.json()["gstin"] == SECOND_GSTIN
        assert response.json()["is_home"] is False

        row = db_session.query(BusinessMembership).one()
        assert row.business.gstin == SECOND_GSTIN

    def test_the_wrong_password_is_refused(self, auth_client, client):
        register_second_business(client)
        response = link(auth_client, password="not-the-right-password")
        assert response.status_code == 401

    def test_an_unknown_email_is_refused_the_same_way_as_a_wrong_password(
        self, auth_client, client
    ):
        register_second_business(client)
        wrong_password = link(auth_client, password="not-the-right-password")
        unknown_email = link(auth_client, email="nobody@example.com")
        assert wrong_password.status_code == unknown_email.status_code == 401
        assert wrong_password.json()["detail"] == unknown_email.json()["detail"]

    def test_linking_your_own_business_again_is_refused(self, auth_client):
        response = link(auth_client, email=TEST_EMAIL, password=TEST_PASSWORD)
        assert response.status_code == 409
        assert "already your business" in response.json()["detail"].lower()

    def test_linking_the_same_business_twice_is_refused(self, auth_client, client):
        register_second_business(client)
        assert link(auth_client).status_code == 201
        second = link(auth_client)
        assert second.status_code == 409
        assert "already linked" in second.json()["detail"].lower()

    def test_an_inactive_accounts_password_is_refused(
        self, auth_client, client, db_session
    ):
        register_second_business(client)
        other = db_session.query(User).filter_by(email=SECOND_EMAIL).one()
        other.is_active = False
        db_session.commit()

        assert link(auth_client).status_code == 401

    def test_linking_requires_authentication(self, client):
        register_second_business(client)
        response = client.post(
            "/api/v1/businesses/mine/link",
            json={"email": SECOND_EMAIL, "password": SECOND_PASSWORD},
        )
        assert response.status_code == 401

    def test_linking_a_deleted_business_is_refused(self, auth_client, client, db_session):
        """A membership to a closed registration is access to nothing.

        This used to answer 201. The caller was told the link succeeded, the
        business then never appeared in ``GET /businesses/mine`` because that
        filters soft deletes, and every request carrying its id came back
        "This business has been deactivated" — three surfaces disagreeing about one row.
        """
        second = register_second_business(client)
        closed = db_session.get(Business, second["business"]["id"])
        closed.soft_delete()
        db_session.commit()

        response = link(auth_client)
        assert response.status_code == 409, response.text
        assert "closed or suspended" in response.json()["detail"].lower()
        # Refused means refused: no row left behind to be honoured later if the
        # business is ever reactivated.
        assert db_session.query(BusinessMembership).count() == 0

    def test_linking_a_suspended_business_is_refused(self, auth_client, client, db_session):
        """Suspension refuses the link for the same reason deletion does.

        The account's password is still correct — this is not an authentication
        answer and deliberately does not pretend to be one. What is missing is
        anything to link *to*.
        """
        second = register_second_business(client)
        suspended = db_session.get(Business, second["business"]["id"])
        suspended.is_active = False
        db_session.commit()

        response = link(auth_client)
        assert response.status_code == 409, response.text
        assert "closed or suspended" in response.json()["detail"].lower()
        assert db_session.query(BusinessMembership).count() == 0

    def test_a_refused_link_does_not_reveal_whether_the_password_was_right(
        self, auth_client, client, db_session
    ):
        """The 409 is only ever reached with a correct password.

        Worth pinning because the refusal above is more specific than the login
        answer beside it, and a reader could reasonably wonder whether it turns
        this endpoint into an oracle. It does not: a wrong password on a
        suspended business answers the same 401 as a wrong password on a live
        one, so the 409 tells an attacker nothing they had not already proven
        they knew.
        """
        second = register_second_business(client)
        suspended = db_session.get(Business, second["business"]["id"])
        suspended.is_active = False
        db_session.commit()

        wrong = link(auth_client, password="not-the-right-password")
        assert wrong.status_code == 401
        assert "closed or suspended" not in wrong.json()["detail"].lower()

    def test_the_linked_accounts_role_is_carried_over(self, auth_client, client, db_session):
        register_second_business(client, email="viewer@example.com", password="viewersecret1")
        viewer = db_session.query(User).filter_by(email="viewer@example.com").one()
        viewer.role = UserRole.VIEWER
        db_session.commit()

        response = link(auth_client, email="viewer@example.com", password="viewersecret1")
        assert response.json()["role"] == "viewer"


# ---------------------------------------------------------------------------
# DELETE /businesses/mine/{business_id}
# ---------------------------------------------------------------------------

# --------------------------------------------------------------------------
# GB036: Fence audit — per-account brute-force protection on link
# --------------------------------------------------------------------------

class TestLinkPerAccountRateLimit:
    """The link endpoint verifies passwords and must have a per-account counter.

    Without it, a distributed attacker can guess passwords at this endpoint
    without the per-account budget that login enforces — the IP limit alone
    is only as strong as the number of source addresses the attacker has.
    """

    def test_failures_are_counted_per_account(
        self, auth_client, client, rate_limited, pinned_window
    ):
        register_second_business(client)
        for _ in range(10):
            response = link(auth_client, password="wrong-password-guess")
            assert response.status_code == 401

        # The 11th attempt should be rate-limited
        response = link(auth_client, password="wrong-password-guess")
        assert response.status_code == 429
        assert "too many failed attempts" in response.json()["detail"].lower()

    def test_correct_password_resets_the_counter(
        self, auth_client, client, rate_limited, pinned_window
    ):
        register_second_business(client)
        for _ in range(5):
            link(auth_client, password="wrong-password-guess")

        # Correct password should succeed and reset the counter
        response = link(auth_client)
        assert response.status_code == 201

    def test_different_accounts_have_separate_budgets(
        self, auth_client, client, rate_limited, pinned_window
    ):
        register_second_business(client)
        # Exhaust the budget for SECOND_EMAIL
        for _ in range(10):
            link(auth_client, password="wrong")

        # A different email should still have its own budget
        response = link(auth_client, email="nonexistent@example.com", password="wrong")
        assert response.status_code == 401  # Not 429


class TestUnlinkingABusiness:
    def test_it_removes_the_membership(self, auth_client, client, db_session):
        register_second_business(client)
        linked_id = link(auth_client).json()["id"]

        response = auth_client.delete(f"/api/v1/businesses/mine/{linked_id}")
        assert response.status_code == 204

        body = auth_client.get("/api/v1/businesses/mine").json()
        assert [item["id"] for item in body["items"]] == [
            item["id"] for item in body["items"] if item["is_home"]
        ]

    def test_unlinking_something_never_linked_is_404(self, auth_client, business):
        response = auth_client.delete(f"/api/v1/businesses/mine/{business.id + 999}")
        assert response.status_code == 404

    def test_the_home_business_cannot_be_unlinked(self, auth_client, business):
        # It has no membership row to remove — it is not reached through one.
        response = auth_client.delete(f"/api/v1/businesses/mine/{business.id}")
        assert response.status_code == 404

    def test_unlinking_requires_authentication(self, client):
        # No `business` fixture here on purpose: it pulls in `auth_client`,
        # which mutates this same TestClient's headers as a side effect —
        # exactly the authentication this test exists to require the absence
        # of. Any id does; the auth check runs before the row is looked up.
        assert client.delete("/api/v1/businesses/mine/1").status_code == 401


class TestTheLinkedBusinessesOwnerCanSeeAndRevokeLinks:
    """A link was the linker's alone to end.

    It is proven by a password, there is no way to change a password, and the
    business linked into could not list or remove it — so whoever once knew
    the password kept the books for good. ``auth_client`` links the second
    business here; that business's own owner is the one acting below.
    """

    @staticmethod
    def _as_second_owner(second):
        return {"Authorization": f"Bearer {second['access_token']}"}

    def test_the_owner_sees_who_has_linked_in(self, auth_client, client):
        second = register_second_business(client)
        link(auth_client)

        response = auth_client.get(
            "/api/v1/businesses/mine/members", headers=self._as_second_owner(second)
        )
        assert response.status_code == 200
        [member] = response.json()["items"]
        assert member["email"] == TEST_EMAIL
        assert member["role"] == "owner"

    def test_revoking_ends_the_linkers_switch(self, auth_client, client):
        second = register_second_business(client)
        linked_id = link(auth_client).json()["id"]
        as_owner = self._as_second_owner(second)
        member_id = auth_client.get(
            "/api/v1/businesses/mine/members", headers=as_owner
        ).json()["items"][0]["id"]

        revoked = auth_client.delete(
            f"/api/v1/businesses/mine/members/{member_id}", headers=as_owner
        )
        assert revoked.status_code == 204

        switched = auth_client.get(
            "/api/v1/dashboard", headers={"X-Business-Id": str(linked_id)}
        )
        assert switched.status_code == 403
        assert auth_client.get(
            "/api/v1/businesses/mine/members", headers=as_owner
        ).json()["items"] == []

    def test_a_linked_viewer_cannot_list_or_revoke(self, auth_client, client, db_session):
        register_second_business(client)
        linked_id = link(auth_client).json()["id"]
        membership = db_session.query(BusinessMembership).one()
        membership.role = MembershipRole.VIEWER
        db_session.commit()
        switched = {"X-Business-Id": str(linked_id)}

        assert auth_client.get(
            "/api/v1/businesses/mine/members", headers=switched
        ).status_code == 403
        assert auth_client.delete(
            f"/api/v1/businesses/mine/members/{membership.id}", headers=switched
        ).status_code == 403


# ---------------------------------------------------------------------------
# X-Business-Id
# ---------------------------------------------------------------------------

class TestSwitchingBusinessWithTheHeader:
    def test_no_header_acts_for_the_home_business_as_always(self, auth_client, business):
        response = auth_client.get("/api/v1/dashboard")
        assert response.status_code == 200
        assert response.json()["business_gstin"] == business.gstin

    def test_a_linked_businesss_id_switches_the_active_tenant(
        self, auth_client, client, business
    ):
        register_second_business(client)
        linked_id = link(auth_client).json()["id"]

        response = auth_client.get(
            "/api/v1/dashboard", headers={"X-Business-Id": str(linked_id)}
        )
        assert response.status_code == 200
        assert response.json()["business_gstin"] == SECOND_GSTIN

    def test_an_unlinked_business_id_is_refused(self, auth_client, client, business):
        second = register_second_business(client)
        other_business_id = second["business"]["id"]

        # Never linked — auth_client's user has no membership to it.
        response = auth_client.get(
            "/api/v1/dashboard", headers={"X-Business-Id": str(other_business_id)}
        )
        assert response.status_code == 403

    def test_a_business_id_that_does_not_exist_is_refused(self, auth_client):
        response = auth_client.get(
            "/api/v1/dashboard", headers={"X-Business-Id": "999999"}
        )
        assert response.status_code == 403

    def test_switching_to_your_own_id_explicitly_still_works(self, auth_client, business):
        response = auth_client.get(
            "/api/v1/dashboard", headers={"X-Business-Id": str(business.id)}
        )
        assert response.status_code == 200
        assert response.json()["business_gstin"] == business.gstin

    def test_unlinking_revokes_the_switch(self, auth_client, client, business):
        register_second_business(client)
        linked_id = link(auth_client).json()["id"]
        auth_client.delete(f"/api/v1/businesses/mine/{linked_id}")

        response = auth_client.get(
            "/api/v1/dashboard", headers={"X-Business-Id": str(linked_id)}
        )
        assert response.status_code == 403

    def test_data_written_while_switched_lands_under_the_linked_business(
        self, auth_client, client, db_session
    ):
        from app.models.invoice import Invoice

        register_second_business(client)
        linked_id = link(auth_client).json()["id"]

        response = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("bill.txt", b"Invoice No: SW-1\nTotal Amount: 100.00", "text/plain")},
            data={"invoice_type": "purchase"},
            headers={"X-Business-Id": str(linked_id)},
        )
        assert response.status_code == 201, response.text

        invoice = db_session.query(Invoice).filter_by(invoice_number="SW-1").one()
        assert invoice.business_id == linked_id

    @pytest.mark.parametrize("bad_id", ["0", "-1", "2147483648", "99999999999"])
    def test_an_x_business_id_outside_the_row_range_is_refused(self, auth_client, bad_id):
        response = auth_client.get(
            "/api/v1/dashboard", headers={"X-Business-Id": bad_id}
        )
        assert response.status_code == 422

    def test_a_deactivated_business_is_refused_even_with_a_valid_membership(
        self, auth_client, client, db_session
    ):
        register_second_business(client)
        linked_id = link(auth_client).json()["id"]

        from app.models.business import Business

        target = db_session.get(Business, linked_id)
        target.is_active = False
        db_session.commit()

        response = auth_client.get(
            "/api/v1/dashboard", headers={"X-Business-Id": str(linked_id)}
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# One predicate, three surfaces
# ---------------------------------------------------------------------------

class TestTheThreeSurfacesAgreeOnReachability:
    """Listing, linking and acting must answer one question the same way.

    Two columns end a business and they end it for different reasons:
    ``deleted_at`` is the tenant closing the account, ``is_active`` is us
    suspending it. Three places asked separately and gave three answers —
    ``get_active_tenant`` checked both, ``/businesses/mine`` checked only
    ``deleted_at``, and ``link_business`` checked neither. Every pairwise
    disagreement was reachable, and each one showed up as the product
    contradicting itself rather than as an error anyone could act on.

    The per-surface tests above pin each answer. These pin that the answers
    are the *same* answer, which is the property that actually broke — and
    they are written against the state matrix rather than against the three
    call sites, so a fourth caller asking the question a fourth way is what
    this is waiting for.
    """

    # (deleted, suspended) -> reachable. Both columns, and both at once: a
    # business can be closed by its owner and suspended by us, and the pair
    # must not cancel out into a live row.
    STATES = [
        (False, False, True),
        (True, False, False),
        (False, True, False),
        (True, True, False),
    ]

    def _put_second_business_in(self, client, db_session, deleted, suspended):
        second = register_second_business(client)
        target = db_session.get(Business, second["business"]["id"])
        if deleted:
            target.soft_delete()
        if suspended:
            target.is_active = False
        db_session.commit()
        return target.id

    def test_the_python_predicate_and_the_sql_clause_agree(self, db_session):
        """``is_reachable`` and ``reachable()`` are one rule in two shapes.

        They have to be: the listing filters in SQL and the link check tests
        the loaded object, so a drift between them would put the two surfaces
        back into disagreement while every individual test still passed. Read
        both out of the same four rows and compare.
        """
        for index, (deleted, suspended, _expected) in enumerate(self.STATES):
            gstin = _valid_gstin(500 + index)
            row = Business(gstin=gstin, legal_name=f"State {index}", state_code=gstin[:2])
            if deleted:
                row.soft_delete()
            if suspended:
                row.is_active = False
            db_session.add(row)
        db_session.commit()

        in_python = {
            row.id for row in db_session.query(Business) if row.is_reachable
        }
        in_sql = {
            row.id
            for row in db_session.query(Business).filter(Business.reachable()).all()
        }
        assert in_python == in_sql, (
            "the property and the WHERE clause disagree about which businesses "
            "are reachable, so listing and linking will drift apart"
        )

    def test_listing_and_acting_agree_across_every_state(
        self, auth_client, client, db_session
    ):
        """Anything the switcher offers must be something a request can act for.

        The direction that bit: a business in the list that 403s on use is a
        menu entry whose only outcome is a refusal. Asserted both ways, because
        the opposite drift — a usable business hidden from the switcher — is a
        business the user simply cannot reach.
        """
        for deleted, suspended, expected in self.STATES:
            db_session.query(BusinessMembership).delete()
            db_session.query(Business).filter(
                Business.gstin == SECOND_GSTIN
            ).delete()
            db_session.query(User).filter(User.email == SECOND_EMAIL).delete()
            db_session.commit()

            linked_id = self._put_second_business_in(
                client, db_session, deleted, suspended
            )
            # The link is made directly: `link_business` now refuses these
            # states, and this test is about the other two surfaces given a
            # membership that already exists — which is what the link endpoint
            # leaves behind for a business suspended *after* it was linked.
            user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
            db_session.add(
                BusinessMembership(
                    user_id=user.id, business_id=linked_id, role=UserRole.OWNER
                )
            )
            db_session.commit()

            listed = [
                item["id"]
                for item in auth_client.get("/api/v1/businesses/mine").json()["items"]
            ]
            acting = auth_client.get(
                "/api/v1/dashboard", headers={"X-Business-Id": str(linked_id)}
            )

            assert (linked_id in listed) is expected, (
                f"deleted={deleted} suspended={suspended}: listing says "
                f"{'reachable' if linked_id in listed else 'unreachable'}"
            )
            assert (acting.status_code == 200) is expected, (
                f"deleted={deleted} suspended={suspended}: acting answered "
                f"{acting.status_code}"
            )

    def test_linking_agrees_with_listing_across_every_state(
        self, auth_client, client, db_session
    ):
        """A link that succeeds must produce a business the switcher then shows.

        The 201-then-invisible case is what this forbids: linking answered
        success for a business ``/businesses/mine`` would never list and no
        request could act for, leaving the caller with a confirmation and
        nothing behind it.
        """
        for deleted, suspended, expected in self.STATES:
            db_session.query(BusinessMembership).delete()
            db_session.query(Business).filter(
                Business.gstin == SECOND_GSTIN
            ).delete()
            db_session.query(User).filter(User.email == SECOND_EMAIL).delete()
            db_session.commit()

            linked_id = self._put_second_business_in(
                client, db_session, deleted, suspended
            )
            linked = link(auth_client)
            assert (linked.status_code == 201) is expected, (
                f"deleted={deleted} suspended={suspended}: link answered "
                f"{linked.status_code}"
            )

            listed = [
                item["id"]
                for item in auth_client.get("/api/v1/businesses/mine").json()["items"]
            ]
            assert (linked_id in listed) is expected, (
                f"deleted={deleted} suspended={suspended}: link answered "
                f"{linked.status_code} but listing "
                f"{'shows' if linked_id in listed else 'hides'} it"
            )


class TestAccessChangesLeaveATrace:
    """P19 M11: linking another business is an access grant, and its access
    line (``POST /businesses/mine/link``) cannot say whose — the business is in
    the body. Nothing else recorded it, nor the unlink."""

    def test_a_link_and_an_unlink_are_logged_with_the_business(self, auth_client, caplog):
        second = register_second_business(auth_client)
        response = link(auth_client)
        assert response.status_code in (200, 201), response.text
        linked_id = second["business"]["id"]

        (line,) = [r for r in caplog.records if r.getMessage() == "Business linked"]
        assert line.linked_business_id == linked_id
        assert line.role == "owner"

        assert auth_client.delete(f"/api/v1/businesses/mine/{linked_id}").status_code == 204
        (gone,) = [r for r in caplog.records if r.getMessage() == "Business unlinked"]
        assert gone.linked_business_id == linked_id


def test_a_link_that_loses_the_race_says_already_linked(auth_client, db_session, monkeypatch):
    # P19 M9: both clicks pass the "already linked?" read before either commits;
    # the unique index refuses the second, which answered the generic conflict.
    from app.models.business_membership import BusinessMembership

    register_second_business(auth_client)
    original_scalar = db_session.scalar

    def miss_the_membership(statement, *args, **kwargs):
        # The loser's read: the winner's row is not visible to it yet.
        if "business_memberships" in str(statement):
            return None
        return original_scalar(statement, *args, **kwargs)

    assert link(auth_client).status_code in (200, 201)
    monkeypatch.setattr(db_session, "scalar", miss_the_membership)
    response = link(auth_client)
    assert response.status_code == 409
    assert response.json()["detail"] == "That business is already linked."
    monkeypatch.undo()
    assert db_session.query(BusinessMembership).count() == 1
