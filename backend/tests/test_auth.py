"""Registration, login, and the tenant boundary they establish."""
from __future__ import annotations

from app.core.security import create_access_token
from app.models.business import Business, BusinessPlan
from app.models.business_membership import BusinessMembership
from app.models.user import User, UserRole
from tests.conftest import BUSINESS_GSTIN, TEST_EMAIL, TEST_PASSWORD
from tests.test_businesses import SECOND_GSTIN

REGISTRATION = {
    "email": "new@example.com",
    "password": "supersecret123",
    "gstin": BUSINESS_GSTIN,
    "legal_name": "Umang Traders Private Limited",
    "trade_name": "Umang Traders",
    "full_name": "Umang Shah",
    "phone": "+919820012345",
}


def test_register_creates_business_and_owner(client, db_session):
    response = client.post("/api/v1/auth/register", json=REGISTRATION)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["access_token"]
    assert body["user"]["email"] == "new@example.com"
    assert body["user"]["role"] == UserRole.OWNER.value
    assert body["business"]["gstin"] == BUSINESS_GSTIN
    assert body["business"]["plan"] == BusinessPlan.FREE.value

    business = db_session.query(Business).filter_by(gstin=BUSINESS_GSTIN).one()
    # Both are derived from the GSTIN rather than asked for, so a typo in one
    # cannot disagree with the other.
    assert business.state_code == "27"
    assert business.pan == "AAPFU0939F"

    user = db_session.query(User).filter_by(email="new@example.com").one()
    assert user.business_id == business.id
    # The password is never stored as given.
    assert user.hashed_password != REGISTRATION["password"]


def test_register_returns_decoded_state_name(client):
    response = client.post("/api/v1/auth/register", json=REGISTRATION)
    assert response.json()["business"]["state_name"] == "Maharashtra"


def test_register_normalizes_a_spaced_gstin(client, db_session):
    response = client.post(
        "/api/v1/auth/register", json={**REGISTRATION, "gstin": "27 aapfu0939f 1zv"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["business"]["gstin"] == BUSINESS_GSTIN


def test_register_rejects_an_invalid_gstin(client):
    response = client.post(
        "/api/v1/auth/register", json={**REGISTRATION, "gstin": "27AAPFU0939F1ZW"}
    )
    assert response.status_code == 422
    assert "gstin" in str(response.json()["detail"]).lower()


def test_register_rejects_a_short_password(client):
    response = client.post("/api/v1/auth/register", json={**REGISTRATION, "password": "short"})
    assert response.status_code == 422


def test_register_rejects_a_malformed_email(client):
    response = client.post("/api/v1/auth/register", json={**REGISTRATION, "email": "not-an-email"})
    assert response.status_code == 422


def test_duplicate_email_is_rejected(auth_client):
    response = auth_client.post(
        "/api/v1/auth/register",
        json={**REGISTRATION, "email": TEST_EMAIL, "gstin": "29AAGCB7383J1Z4"},
    )
    assert response.status_code == 409
    assert "email" in response.json()["detail"].lower()


def test_register_without_gstin_creates_a_business_with_no_registration(client, db_session):
    payload = {
        "email": "explorer@example.com",
        "password": "supersecret123",
        "full_name": "Explorer User",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["access_token"]
    assert body["business"]["gstin"] is None
    assert body["business"]["state_code"] is None
    assert body["business"]["state_name"] == ""
    assert body["business"]["legal_name"] == "Explorer User"
    assert body["business"]["plan"] == BusinessPlan.FREE.value

    business = db_session.get(Business, body["business"]["id"])
    assert business.gstin is None
    assert business.state_code is None
    assert business.pan is None


def test_register_without_gstin_falls_back_to_email_local_part(client):
    payload = {
        "email": "fallback@example.com",
        "password": "supersecret123",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["business"]["legal_name"] == "fallback"


def test_two_businesses_without_gstin_do_not_conflict(client):
    for email in ("first@example.com", "second-no-gstin@example.com"):
        response = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "supersecret123", "full_name": "No GSTIN"},
        )
        assert response.status_code == 201, response.text


def test_register_with_empty_string_gstin_treats_it_as_absent(client):
    payload = {
        "email": "empty-gstin@example.com",
        "password": "supersecret123",
        "gstin": "   ",
        "full_name": "Whitespace GSTIN",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["business"]["gstin"] is None


def test_duplicate_gstin_is_rejected(auth_client):
    """One GSTIN is one tenant.

    A second sign-up against a registration already on file must not create a
    parallel tenant — that would split one business's invoices across two
    ledgers that never reconcile.
    """
    response = auth_client.post(
        "/api/v1/auth/register", json={**REGISTRATION, "email": "second@example.com"}
    )
    assert response.status_code == 409
    assert "gstin" in response.json()["detail"].lower()


def test_login_returns_a_usable_token(client, auth_client):
    response = client.post(
        "/api/v1/auth/login", data={"username": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert response.json()["token_type"] == "bearer"

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == TEST_EMAIL


def test_login_with_a_wrong_password_fails(client, auth_client):
    response = client.post(
        "/api/v1/auth/login", data={"username": TEST_EMAIL, "password": "wrongpassword"}
    )
    assert response.status_code == 401


def test_login_does_not_reveal_whether_an_account_exists(client, auth_client):
    """Same status and same message either way.

    A different response for "no such user" would turn this endpoint into a
    way to test whether a given business banks with us.
    """
    unknown = client.post(
        "/api/v1/auth/login", data={"username": "nobody@example.com", "password": TEST_PASSWORD}
    )
    wrong_password = client.post(
        "/api/v1/auth/login", data={"username": TEST_EMAIL, "password": "wrongpassword"}
    )
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json()["detail"] == wrong_password.json()["detail"]


def test_inactive_user_cannot_log_in(client, auth_client, db_session):
    user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
    user.is_active = False
    db_session.commit()

    response = client.post(
        "/api/v1/auth/login", data={"username": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 403


def test_me_returns_the_user_and_their_business(auth_client):
    response = auth_client.get("/api/v1/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == TEST_EMAIL
    assert body["business"]["gstin"] == BUSINESS_GSTIN
    assert body["business"]["state_name"] == "Maharashtra"
    assert "hashed_password" not in body


class TestMeReportsTheRoleTheApiWillActuallyEnforce:
    """``active_role`` is the role on the business in the response.

    The frontend has no other way to decide which controls to show, and the
    top-level ``role`` is the wrong input for that decision: it is the role on
    the login's *own* business. An owner linked into a client as a viewer was
    told "owner" here while every write to that client answered 403 — so the
    app rendered a full set of buttons whose only outcome was a refusal, which
    is the same failure the business switcher had and for the same reason.
    """

    def _linked_as(self, auth_client, client, db_session, role):
        from tests.test_businesses import link, register_second_business

        register_second_business(client, email="other@example.com", password="othersecret1")
        other = db_session.query(User).filter_by(email="other@example.com").one()
        other.role = role
        db_session.commit()
        response = link(auth_client, email="other@example.com", password="othersecret1")
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def test_acting_as_your_own_tenant_it_is_the_role_on_the_login(self, auth_client):
        body = auth_client.get("/api/v1/auth/me").json()
        assert body["active_role"] == body["role"] == "owner"

    def test_acting_for_a_linked_business_it_is_the_membership_role(
        self, auth_client, client, db_session
    ):
        linked_id = self._linked_as(auth_client, client, db_session, UserRole.VIEWER)

        body = auth_client.get(
            "/api/v1/auth/me", headers={"X-Business-Id": str(linked_id)}
        ).json()
        assert body["business"]["id"] == linked_id
        assert body["active_role"] == "viewer"
        # The login's own role is unchanged and still reported — the two are
        # different facts, and collapsing them would lose the one the account
        # screen needs.
        assert body["role"] == "owner"

    def test_it_matches_what_a_write_to_that_business_actually_answers(
        self, auth_client, client, db_session
    ):
        """The claim is only worth making if it predicts the API's behaviour.

        Asserted against a real mutating route rather than against
        ``require_writer`` directly: what the frontend needs to know is whether
        a write will be refused, and this is that question asked end to end.
        """
        for role, writable in [(UserRole.VIEWER, False), (UserRole.ACCOUNTANT, True)]:
            db_session.query(BusinessMembership).delete()
            db_session.query(Business).filter(Business.gstin == SECOND_GSTIN).delete()
            db_session.query(User).filter(User.email == "other@example.com").delete()
            db_session.commit()

            linked_id = self._linked_as(auth_client, client, db_session, role)
            headers = {"X-Business-Id": str(linked_id)}

            body = auth_client.get("/api/v1/auth/me", headers=headers).json()
            write = auth_client.post(
                "/api/v1/invoices/upload",
                files={"file": ("b.txt", b"Invoice No: R-1\nTotal Amount: 100.00", "text/plain")},
                data={"invoice_type": "purchase"},
                headers=headers,
            )
            assert (body["active_role"] != "viewer") is writable
            assert (write.status_code != 403) is writable, (
                f"active_role={body['active_role']} but the write answered "
                f"{write.status_code}"
            )


def test_me_requires_authentication(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_rejects_a_garbage_token(client):
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert response.status_code == 401


def test_me_rejects_a_token_for_a_deleted_user(client, auth_client, db_session):
    """A valid signature is not enough.

    The token stays cryptographically valid after the user is gone, so the
    subject has to be resolved against the database on every request.
    """
    token = auth_client.headers["Authorization"]
    db_session.query(User).filter_by(email=TEST_EMAIL).delete()
    db_session.commit()

    assert client.get("/api/v1/auth/me", headers={"Authorization": token}).status_code == 401


def test_me_rejects_a_token_whose_subject_is_not_a_user_id(client):
    """A signature check is not an authorization check.

    ``create_access_token`` stringifies whatever it is handed, so anyone who
    ever obtains the signing key — or any future code path that mints a token
    from something other than a user id — produces a token that verifies
    perfectly and resolves to no user. The subject has to be rejected as
    unusable rather than reaching ``db.get`` and raising a 500 out of the
    driver, which would turn a bad token into an availability problem.
    """
    forged = create_access_token("admin")
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 401
    assert response.json()["detail"] == (
        "Your sign-in has expired or is not valid. Sign in again to continue."
    )


def test_login_still_finds_a_row_stored_with_mixed_case(client, db_session):
    """The fallback for rows written before addresses were folded.

    Registration lower-cases the address now, so the indexed lookup finds
    everything created since. A row from before that must still be able to log
    in — and only the exact address they typed can match it, because no index
    could serve a ``lower(email)`` comparison.
    """
    from app.core.security import hash_password
    from app.models.business import Business

    business = db_session.query(Business).filter_by(gstin=BUSINESS_GSTIN).one_or_none()
    if business is None:
        client.post("/api/v1/auth/register", json=REGISTRATION)
        business = db_session.query(Business).filter_by(gstin=BUSINESS_GSTIN).one()

    db_session.add(
        User(
            email="Legacy.Owner@Example.com",
            hashed_password=hash_password(TEST_PASSWORD),
            full_name="Legacy Owner",
            role=UserRole.OWNER,
            business_id=business.id,
        )
    )
    db_session.commit()

    response = client.post(
        "/api/v1/auth/login",
        data={"username": "Legacy.Owner@Example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


def test_register_rejects_a_password_from_the_top_of_every_breach_corpus(client):
    # Long enough to clear the length check, which is exactly why the length
    # check on its own is not enough.
    response = client.post(
        "/api/v1/auth/register", json={**REGISTRATION, "password": "Password123"}
    )
    assert response.status_code == 422
    assert "too common" in str(response.json()["detail"]).lower()


def test_register_rejects_a_password_that_is_only_whitespace(client):
    # Eight spaces satisfies min_length and is not in the corpus list.
    response = client.post("/api/v1/auth/register", json={**REGISTRATION, "password": "        "})
    assert response.status_code == 422
    assert "whitespace" in str(response.json()["detail"]).lower()


def test_inactive_business_blocks_access(auth_client, db_session):
    business = db_session.query(Business).filter_by(gstin=BUSINESS_GSTIN).one()
    business.is_active = False
    db_session.commit()

    assert auth_client.get("/api/v1/auth/me").status_code == 403


class TestLoginTellsNothingApart:
    """Two failed logins must be indistinguishable, and not only in the body.

    ``test_login_does_not_reveal_whether_an_account_exists`` above asserts the
    status and message match. That is the half an attacker reads; the half they
    *measure* is how long the answer took. bcrypt is deliberately slow, so a
    login against a real account costs a few hundred milliseconds and one
    against an address with no row would cost a database round trip — two
    orders of magnitude apart, and enough to enumerate which businesses bank
    with us from anywhere on the internet.
    """

    def _count_hashes(self, monkeypatch) -> list[bytes]:
        import app.core.security as security

        calls: list[bytes] = []
        real = security.bcrypt.checkpw

        def spy(password, hashed):
            calls.append(hashed)
            return real(password, hashed)

        # Built before the spy is installed, so the one-off lazy construction
        # is not mistaken for work the request did.
        security._absent_account_hash()
        monkeypatch.setattr(security.bcrypt, "checkpw", spy)
        return calls

    def test_an_unknown_address_costs_the_same_hashing_as_a_wrong_password(
        self, client, auth_client, monkeypatch
    ):
        calls = self._count_hashes(monkeypatch)

        unknown = client.post(
            "/api/v1/auth/login",
            data={"username": "nobody@example.com", "password": TEST_PASSWORD},
        )
        after_unknown = len(calls)
        wrong = client.post(
            "/api/v1/auth/login",
            data={"username": TEST_EMAIL, "password": "wrongpassword"},
        )

        assert unknown.status_code == wrong.status_code == 401
        # One bcrypt round each. Zero for the unknown address is the bug this
        # exists to catch, and it is invisible to every other assertion here.
        assert after_unknown == 1
        assert len(calls) - after_unknown == 1

    def test_the_stand_in_hash_is_what_the_unknown_address_is_checked_against(
        self, client, monkeypatch
    ):
        import app.core.security as security

        calls = self._count_hashes(monkeypatch)

        client.post(
            "/api/v1/auth/login",
            data={"username": "nobody@example.com", "password": TEST_PASSWORD},
        )

        assert calls == [security._absent_account_hash().encode("utf-8")]


class TestPerAccountLoginThrottle:
    """The limit an address-keyed one cannot replace.

    Credential stuffing is not one host guessing fast; it is thousands of hosts
    guessing once each. Against a 20/minute address limit that is a password
    every few milliseconds at any single account, from a limiter that never
    sees the same key twice. Keying a second budget on the account being
    attempted is what makes the target — the thing the attacker cannot spread
    the load over — the scarce resource.
    """

    def _login(self, client, username, password, *, ip="203.0.113.9"):
        return client.post(
            "/api/v1/auth/login",
            data={"username": username, "password": password},
            headers={"X-Forwarded-For": ip},
        )

    def _fail_from_many_addresses(self, client, username, times):
        """Each attempt from its own address, so the per-address limit — which
        this test is not about — never fires."""
        return [
            self._login(client, username, "wrong-password", ip=f"198.51.100.{i + 1}")
            for i in range(times)
        ]

    def test_one_account_is_capped_however_many_addresses_attack_it(
        self, client, auth_client, rate_limited, pinned_window, monkeypatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)

        statuses = [r.status_code for r in self._fail_from_many_addresses(client, TEST_EMAIL, 14)]

        # Ten guesses spent, then the budget is gone regardless of source.
        assert statuses[:10] == [401] * 10
        assert statuses[10:] == [429] * 4

    def test_the_refusal_says_when_to_come_back(
        self, client, auth_client, rate_limited, pinned_window, monkeypatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)

        blocked = self._fail_from_many_addresses(client, TEST_EMAIL, 11)[-1]

        assert blocked.status_code == 429
        assert 0 < int(blocked.headers["Retry-After"]) <= 15 * 60
        # The headers the caller is told to back off against must describe the
        # budget that actually refused them, not the address one they still
        # have room in.
        assert blocked.headers["X-RateLimit-Remaining"] == "0"
        assert blocked.headers["X-RateLimit-Limit"] == "10"
        assert blocked.json()["error"]["code"] == "rate_limited"

    def test_a_blocked_attempt_is_refused_before_any_hashing(
        self, client, auth_client, rate_limited, pinned_window, monkeypatch
    ):
        """The work per attempt is what a stuffing run is buying. Checking the
        budget after the bcrypt round would still refuse the attacker and still
        let them spend our CPU doing it."""
        import app.core.security as security
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        self._fail_from_many_addresses(client, TEST_EMAIL, 10)

        calls: list[bytes] = []
        real = security.bcrypt.checkpw
        monkeypatch.setattr(
            security.bcrypt,
            "checkpw",
            lambda p, h: (calls.append(h), real(p, h))[1],
        )

        assert self._login(client, TEST_EMAIL, "wrong-password").status_code == 429
        assert calls == []

    def test_the_right_password_hands_the_budget_back(
        self, client, auth_client, rate_limited, pinned_window, monkeypatch
    ):
        """Without this refund the counter is a lockout weapon: anyone who
        knows an email address could spend its owner's budget on their behalf
        and keep them out of their own filing. With it, the only caller a
        per-account budget can ever reach is one who cannot produce the
        password either."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        self._fail_from_many_addresses(client, TEST_EMAIL, 9)

        assert self._login(client, TEST_EMAIL, TEST_PASSWORD).status_code == 200

        # A fresh budget, not the one guess that was left.
        statuses = [r.status_code for r in self._fail_from_many_addresses(client, TEST_EMAIL, 10)]
        assert statuses == [401] * 10

    def test_a_deactivated_account_still_gets_its_budget_back(
        self, client, auth_client, db_session, rate_limited, pinned_window, monkeypatch
    ):
        """The 403 is about what the account may do, not about whether the
        caller is who they say. Withholding the refund here would leave exactly
        one class of user lockable by a stranger."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        user = db_session.query(User).filter_by(email=TEST_EMAIL).one()
        user.is_active = False
        db_session.commit()

        self._fail_from_many_addresses(client, TEST_EMAIL, 9)
        assert self._login(client, TEST_EMAIL, TEST_PASSWORD).status_code == 403

        statuses = [r.status_code for r in self._fail_from_many_addresses(client, TEST_EMAIL, 10)]
        assert statuses == [401] * 10

    def test_changing_the_case_of_the_address_does_not_mint_a_new_budget(
        self, client, auth_client, rate_limited, pinned_window, monkeypatch
    ):
        """The lookup folds the address to lower case, so the counter has to
        fold it the same way — otherwise the budget is bypassed by typing the
        address differently, and there are 2**n ways to do that."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        self._fail_from_many_addresses(client, TEST_EMAIL, 10)

        assert self._login(client, TEST_EMAIL.upper(), "wrong-password").status_code == 429
        assert self._login(client, f"  {TEST_EMAIL}  ", "wrong-password").status_code == 429

    def test_an_address_with_no_account_is_throttled_the_same_way(
        self, client, rate_limited, pinned_window, monkeypatch
    ):
        """Otherwise the throttle is itself the enumeration oracle the
        identical 401 body exists to close: guess eleven times, and whether the
        answer is 429 or 401 tells you whether the account is real."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)

        statuses = [
            r.status_code for r in self._fail_from_many_addresses(client, "nobody@example.com", 12)
        ]
        assert statuses == [401] * 10 + [429] * 2

    def test_two_accounts_have_two_budgets(
        self, client, auth_client, other_tenant, rate_limited, pinned_window, monkeypatch
    ):
        """One shared pool would mean any user could lock out every other."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        self._fail_from_many_addresses(client, TEST_EMAIL, 11)

        assert self._login(client, "rival@example.com", "wrong-password").status_code == 401

    def test_the_budget_is_tunable_without_a_deploy(
        self, client, auth_client, rate_limited, pinned_window, monkeypatch
    ):
        """An operator watching a stuffing run needs to be able to tighten this
        from the environment, under the name the limiter registers it as."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        monkeypatch.setattr(settings, "rate_limit_overrides", "login_account=2/15m")

        statuses = [r.status_code for r in self._fail_from_many_addresses(client, TEST_EMAIL, 4)]
        assert statuses == [401, 401, 429, 429]

    def test_the_budget_comes_back_when_the_window_rolls(
        self, client, auth_client, rate_limited, pinned_window, monkeypatch
    ):
        """A lockout that never lifted would be a denial-of-service anyone
        could aim at any address they knew.

        This is also the property that made every other test in this class
        flaky before the clock was pinned: the window is fifteen minutes cut
        against the wall clock, not fifteen minutes from the first attempt, so
        a burst that happens to straddle a boundary gets its budget refilled
        halfway through and the tail of it comes back 401 instead of 429.
        """
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        self._fail_from_many_addresses(client, TEST_EMAIL, 11)
        assert self._login(client, TEST_EMAIL, "wrong-password").status_code == 429

        pinned_window(15 * 60)

        # A whole fresh budget, and the correct password works again.
        statuses = [r.status_code for r in self._fail_from_many_addresses(client, TEST_EMAIL, 10)]
        assert statuses == [401] * 10

    def test_a_burst_across_a_boundary_gets_two_budgets(
        self, client, auth_client, rate_limited, pinned_window, monkeypatch
    ):
        """The known cost of a fixed window, recorded rather than discovered.

        An attacker who lines a run up with the boundary gets twenty guesses in
        quick succession, not ten — ten at the end of one window and ten at the
        start of the next. That is the tradeoff the module docstring takes
        deliberately (a sliding window costs a Lua script), so it belongs in a
        test: if someone later swaps the implementation, this is the assertion
        that tells them the burst behaviour changed.
        """
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)

        pinned_window(15 * 60 - 1)  # One second before the roll.
        spent = [r.status_code for r in self._fail_from_many_addresses(client, TEST_EMAIL, 10)]
        pinned_window(1)  # Over it.
        refilled = [r.status_code for r in self._fail_from_many_addresses(client, TEST_EMAIL, 10)]

        assert spent == [401] * 10
        assert refilled == [401] * 10
        # And the eleventh in the new window is still refused.
        assert self._login(client, TEST_EMAIL, "wrong-password").status_code == 429

    def test_turning_rate_limiting_off_turns_this_off_too(
        self, client, auth_client, monkeypatch
    ):
        """RATE_LIMIT_ENABLED is one switch. A budget that survived it would
        make the flag a lie and strand a developer at eleven typos."""
        from app.core import rate_limit
        from app.core.config import settings

        rate_limit.reset()
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        monkeypatch.setattr(settings, "trust_proxy_headers", True)

        statuses = [r.status_code for r in self._fail_from_many_addresses(client, TEST_EMAIL, 15)]
        assert statuses == [401] * 15
