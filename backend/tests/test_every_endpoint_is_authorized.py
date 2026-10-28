"""Authorization as a contract over the whole route table, driven at runtime.

The other sweeps each hold one line and most of them read declarations:

* ``test_request_guards.py`` — no route outside a named public list lacks the
  token dependency (static).
* ``test_tenancy_contract.py`` / ``test_active_business_contract.py`` — another
  tenant's row, or the home tenant's while switched, is unreachable (runtime).
* ``test_rbac.py`` — every write refuses a viewer (runtime).
* ``test_openapi_contract.py`` — the spec says which of these can happen.

What none of them asks the running app is the rest of the authorization
surface, and every one of these is a request rather than a reading:

1. A guarded route refuses every kind of bad credential — absent, malformed,
   wrong key, expired, the wrong token type, an unknown or deactivated user —
   with a 401. A dependency can be attached and still let one of those through.
2. A route behind the paid tier refuses a free business *and* one whose paid
   period has run out, and lets a paying one past the gate. The set of such
   routes is pinned, so dropping a gate is a red test, not a silent upgrade.
3. The routes that spend the business's money (subscription and payment
   writes) refuse an accountant, not only a viewer.
4. Every webhook refuses an unsigned or wrongly signed delivery.
5. A paid report downloads only for the business that bought it.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.deps import RequireRole
from app.core.openapi import is_guarded, is_paid_gated
from app.core.routes import collect_api_routes, dependency_calls
from app.core.security import create_access_token
from app.main import app
from app.models.report_purchase import ReportPurchase
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier
from app.models.user import User, UserRole
from tests.test_rbac import set_home_role

ROUTES = [r for r in collect_api_routes(app) if not r.path.startswith("/_")]
VERBS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# What each path parameter is filled with. No value has to name a row that
# exists: every refusal swept here is decided by a dependency, before the
# route looks anything up.
PATH_VALUES = {
    "return_type": "gstr1",
    "extension": "json",
    "period": "2026-04",
    "gstin": "27AAPFU0939F1ZV",
    "provider": "google",
}
_PARAM = re.compile(r"\{(\w+)\}")


def _fill(path: str) -> str:
    return _PARAM.sub(lambda m: PATH_VALUES.get(m.group(1), "999999"), path)


def _calls(predicate) -> list[tuple[str, str]]:
    return sorted(
        (method, route.path)
        for route in ROUTES
        if predicate(route)
        for method in (route.methods or set()) & VERBS
    )


def _ids(calls):
    return [f"{method} {path}" for method, path in calls]


# ---------------------------------------------------------------------------
# 1. Every guarded route refuses every bad credential
# ---------------------------------------------------------------------------

GUARDED = _calls(is_guarded)


def _signed(payload: dict, key: str | None = None) -> str:
    return jwt.encode(payload, key or settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _later() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


BAD_CREDENTIALS = {
    "absent": None,
    "not a bearer token": "Basic dXNlcjpwYXNz",
    "not a JWT": "Bearer not-a-token",
    "signed with another key": lambda: "Bearer "
    + _signed(
        {"sub": "1", "type": "access", "exp": _later()},
        "some-other-secret-at-least-32-bytes",
    ),
    "expired": lambda: "Bearer "
    + _signed({"sub": "1", "type": "access", "exp": datetime.now(UTC) - timedelta(minutes=1)}),
    "not an access token": lambda: "Bearer "
    + _signed({"sub": "1", "type": "refresh", "exp": _later()}),
    "no subject": lambda: "Bearer " + _signed({"type": "access", "exp": _later()}),
    "a subject that is not a user id": lambda: "Bearer "
    + _signed({"sub": "admin", "type": "access", "exp": _later()}),
    "a user that does not exist": lambda: "Bearer " + create_access_token(987654),
    "unsigned (alg none)": lambda: "Bearer "
    + jwt.encode({"sub": "1", "type": "access", "exp": _later()}, None, algorithm="none"),
}


class TestEveryGuardedRouteRefusesABadCredential:
    def test_the_sweep_found_the_guarded_surface(self):
        assert len(GUARDED) >= 40, f"only {len(GUARDED)} guarded calls found"

    @pytest.mark.parametrize("credential", list(BAD_CREDENTIALS), ids=list(BAD_CREDENTIALS))
    @pytest.mark.parametrize(("method", "path"), GUARDED, ids=_ids(GUARDED))
    def test_it_is_a_401(self, client, method, path, credential):
        header = BAD_CREDENTIALS[credential]
        if callable(header):
            header = header()
        headers = {"Authorization": header} if header else {}
        response = client.request(method, _fill(path), headers=headers)
        assert response.status_code == 401, (
            f"{method} {path} with {credential}: {response.status_code} {response.text[:160]}"
        )

    @pytest.mark.parametrize(("method", "path"), GUARDED, ids=_ids(GUARDED))
    def test_a_deactivated_user_is_refused(self, auth_client, db_session, method, path):
        user = db_session.query(User).one()
        user.is_active = False
        db_session.commit()
        assert auth_client.request(method, _fill(path)).status_code == 401


# ---------------------------------------------------------------------------
# 2. The paid tier
# ---------------------------------------------------------------------------

# The features sold as Premium. Pinned, so a gate dropped from one of them is a
# failure here rather than the feature quietly becoming free; a new one is
# added here on purpose.
PREMIUM = {
    ("GET", "/api/v1/itc"),
    ("GET", "/api/v1/itc/rule37"),
    ("GET", "/api/v1/itc/lapsing"),
    ("POST", "/api/v1/meta/gstin/bulk"),
    ("POST", "/api/v1/reconciliation/gstr2b/import"),
    ("POST", "/api/v1/reconciliation/run"),
}
PAID = _calls(is_paid_gated)


def _refused_for_the_plan(response) -> bool:
    return response.status_code == 403 and "paid subscription" in response.text


class TestThePaidTier:
    def test_the_gated_routes_are_the_premium_features(self):
        assert set(PAID) == PREMIUM

    @pytest.mark.parametrize(("method", "path"), PAID, ids=_ids(PAID))
    def test_a_free_business_is_refused(self, auth_client, business, method, path):
        response = auth_client.request(method, _fill(path))
        assert _refused_for_the_plan(response), f"{response.status_code} {response.text[:160]}"

    @pytest.mark.parametrize(("method", "path"), PAID, ids=_ids(PAID))
    def test_a_lapsed_paid_period_is_refused(
        self, auth_client, db_session, business, method, path
    ):
        db_session.add(
            Subscription(
                business_id=business.id,
                tier=SubscriptionTier.PRO,
                status=SubscriptionStatus.ACTIVE,
                current_period_end=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        db_session.commit()
        response = auth_client.request(method, _fill(path))
        assert _refused_for_the_plan(response), f"{response.status_code} {response.text[:160]}"

    @pytest.mark.parametrize(("method", "path"), PAID, ids=_ids(PAID))
    def test_a_paying_business_gets_past_the_gate(self, auth_client, paid_business, method, path):
        """No body is sent, so the answer is usually a 422 — anything but the
        plan refusal shows the gate is what the free business met."""
        assert not _refused_for_the_plan(auth_client.request(method, _fill(path)))


# ---------------------------------------------------------------------------
# 3. Spending the business's money is the owner's call
# ---------------------------------------------------------------------------


def _owner_only(route) -> bool:
    return any(
        isinstance(call, RequireRole) and call.minimum is UserRole.OWNER
        for call in dependency_calls(route.dependant)
    )


OWNER_ONLY = _calls(_owner_only)


class TestOwnerOnlyRoutesRefuseAnAccountant:
    """``test_rbac.py`` drives every write as a viewer. An accountant may write
    the books, so these are the routes where the accountant is the one to
    refuse — the subscription and its payments."""

    def test_the_subscription_writes_are_owner_only(self):
        assert {
            ("POST", "/api/v1/subscriptions/create-order"),
            ("POST", "/api/v1/subscriptions/verify-payment"),
            ("POST", "/api/v1/subscriptions/cancel"),
        } <= set(OWNER_ONLY)

    @pytest.mark.parametrize(("method", "path"), OWNER_ONLY, ids=_ids(OWNER_ONLY))
    def test_an_accountant_is_refused(self, auth_client, db_session, method, path):
        set_home_role(db_session, UserRole.ACCOUNTANT)
        response = auth_client.request(method, _fill(path))
        assert response.status_code == 403, f"{response.status_code} {response.text[:160]}"
        assert "paid subscription" not in response.text  # the role, not the plan

    @pytest.mark.parametrize(("method", "path"), OWNER_ONLY, ids=_ids(OWNER_ONLY))
    def test_the_owner_is_not(self, auth_client, method, path):
        assert auth_client.request(method, _fill(path)).status_code != 403


# ---------------------------------------------------------------------------
# 4. Webhooks
# ---------------------------------------------------------------------------

WEBHOOKS = _calls(lambda route: "webhook" in route.path)


def _razorpay_unsigned(client):
    return client.post("/api/v1/subscriptions/webhook", content=b'{"event": "x"}')


def _razorpay_wrongly_signed(client):
    return client.post(
        "/api/v1/subscriptions/webhook",
        content=b'{"event": "x"}',
        headers={"X-Razorpay-Signature": "0" * 64},
    )


def _twilio_unsigned(client):
    return client.post("/api/v1/whatsapp/webhook", data={"From": "whatsapp:+1", "Body": "hi"})


def _twilio_wrongly_signed(client):
    return client.post(
        "/api/v1/whatsapp/webhook",
        data={"From": "whatsapp:+1", "Body": "hi"},
        headers={"X-Twilio-Signature": "bm90LWl0"},
    )


def _handshake_wrong_token(client):
    return client.get(
        "/api/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "1"},
    )


WEBHOOK_REFUSALS = {
    ("POST", "/api/v1/subscriptions/webhook"): [_razorpay_unsigned, _razorpay_wrongly_signed],
    ("POST", "/api/v1/whatsapp/webhook"): [_twilio_unsigned, _twilio_wrongly_signed],
    ("GET", "/api/v1/whatsapp/webhook"): [_handshake_wrong_token],
}


@pytest.fixture()
def webhook_secrets(monkeypatch):
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "razorpay-webhook-secret")
    monkeypatch.setattr(settings, "whatsapp_twilio_auth_token", "twilio-auth-token")
    monkeypatch.setattr(settings, "whatsapp_verify_token", "the-verify-token")


class TestEveryWebhookRefusesAnUnsignedDelivery:
    def test_every_webhook_has_its_refusals_listed(self):
        assert set(WEBHOOKS) == set(WEBHOOK_REFUSALS)

    @pytest.mark.parametrize(
        "send",
        [send for sends in WEBHOOK_REFUSALS.values() for send in sends],
        ids=lambda send: send.__name__.lstrip("_"),
    )
    def test_it_is_refused(self, client, webhook_secrets, send):
        response = send(client)
        assert 400 <= response.status_code < 500 and response.status_code != 404, (
            f"{send.__name__}: {response.status_code} {response.text[:160]}"
        )

    def test_an_unconfigured_razorpay_secret_refuses_rather_than_trusts(self, client, monkeypatch):
        monkeypatch.setattr(settings, "razorpay_webhook_secret", "")
        assert 400 <= _razorpay_wrongly_signed(client).status_code < 500


# ---------------------------------------------------------------------------
# 5. A paid report is the buyer's
# ---------------------------------------------------------------------------


class TestAReportDownloadsOnlyForItsBuyer:
    def _run(self, db_session, business):
        from tests.test_reconciliation_report import _run

        return _run(db_session, business)

    def test_without_a_purchase_it_is_402(self, auth_client, db_session, business):
        run = self._run(db_session, business)
        assert auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf").status_code == 402

    def test_another_businesss_purchase_of_it_does_not_count(
        self, auth_client, client, db_session, business, other_tenant
    ):
        """The entitlement is looked up by (business, run). A purchase row
        naming this run under any other business — however it got there — must
        not unlock it."""
        from app.models.business import Business

        run = self._run(db_session, business)
        rival = db_session.query(Business).filter(Business.id != business.id).one()
        db_session.add(
            ReportPurchase(
                business_id=rival.id,
                run_id=run.id,
                razorpay_order_id="order_rival",
                razorpay_payment_id="pay_rival",
                amount_paise=9900,
            )
        )
        db_session.commit()
        assert auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf").status_code == 402

        # And the rival, who "bought" it, cannot reach a run that is not theirs.
        client.headers["Authorization"] = f"Bearer {other_tenant}"
        assert client.get(f"/api/v1/reconciliation/{run.id}/report.pdf").status_code == 404

    def test_the_buyer_gets_the_pdf(self, auth_client, db_session, business):
        run = self._run(db_session, business)
        db_session.add(
            ReportPurchase(
                business_id=business.id,
                run_id=run.id,
                razorpay_order_id="order_own",
                razorpay_payment_id="pay_own",
                amount_paise=9900,
            )
        )
        db_session.commit()
        response = auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf")
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF")


# ---------------------------------------------------------------------------
# 6. Every route that decodes a GSTIN is rate limited, at a pinned budget
# ---------------------------------------------------------------------------

# Three routes take a GSTIN, and they are deliberately not on one budget. The
# public lookup is 30/minute per address (M13: scraping). Bulk validation is
# per business, behind the paid tier. The GPT tool shares the GPT bucket at
# 600/minute per address because every ChatGPT user arrives from a handful of
# OpenAI egress addresses — at 30 they would all be throttled together. A new
# GSTIN route, or a budget changed on one of these, fails here and is decided
# rather than inherited.
GSTIN_BUDGETS = {
    ("GET", "/api/v1/meta/gstin/{gstin}"): ("30/minute", "ip"),
    ("POST", "/api/v1/meta/gstin/bulk"): ("30/minute", "identity"),
    ("GET", "/api/v1/gpt/gstin/{gstin}"): ("600/minute", "ip"),
}


def test_every_gstin_route_has_its_own_pinned_budget():
    from app.core.rate_limit import RateLimit

    found = {}
    for route in ROUTES:
        if "gstin" not in route.path.lower():
            continue
        limits = [c for c in dependency_calls(route.dependant) if isinstance(c, RateLimit)]
        assert limits, f"{route.path} decodes a GSTIN with no rate limit of its own"
        for method in (route.methods or set()) & VERBS:
            found[(method, route.path)] = (limits[0].spec, limits[0].by)
    assert found == GSTIN_BUDGETS
