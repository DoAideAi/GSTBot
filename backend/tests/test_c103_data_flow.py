"""C103 Pass 14, M2: what a verified payment computes, and that it computes it once."""
from __future__ import annotations

from datetime import timedelta

from app.models.subscription_payment import SubscriptionPayment
from app.routers import subscriptions as subscriptions_router
from tests.test_c103_boundaries import _end, _pay


class TestAPaymentIsAppliedOnce:
    def test_replaying_an_older_payment_buys_nothing(self, auth_client, business):
        """The row held only the latest payment, so re-verifying an earlier
        one — genuine, paid, correctly signed — added another 30 days each time."""
        _pay(auth_client, business.id, payment="pay_1")
        current = _end(_pay(auth_client, business.id, payment="pay_2"))

        replayed = _pay(auth_client, business.id, payment="pay_1")
        assert replayed.status_code == 200
        assert _end(replayed) == current

    def test_each_applied_payment_is_recorded_with_the_period_it_bought(
        self, auth_client, db_session, business
    ):
        first = _end(_pay(auth_client, business.id, payment="pay_1"))
        second = _end(_pay(auth_client, business.id, payment="pay_2"))
        _pay(auth_client, business.id, payment="pay_1")  # a replay adds no row

        rows = (
            db_session.query(SubscriptionPayment)
            .filter_by(business_id=business.id)
            .order_by(SubscriptionPayment.id)
            .all()
        )
        assert [r.razorpay_payment_id for r in rows] == ["pay_1", "pay_2"]
        assert [_aware(r.period_end) for r in rows] == [first, second]
        assert second - first == timedelta(days=30)

    def test_a_payment_one_business_used_is_refused_for_another(
        self, client, auth_client, business, other_tenant, db_session
    ):
        _pay(auth_client, business.id, payment="pay_shared")
        rival = db_session.query(SubscriptionPayment).one().business_id
        assert rival == business.id

        client.headers["Authorization"] = f"Bearer {other_tenant}"
        from app.models.business import Business

        other_id = db_session.query(Business).filter(Business.id != business.id).one().id
        refused = _pay(client, other_id, payment="pay_shared")
        assert refused.status_code == 409

    def test_two_verifies_racing_apply_the_payment_once(
        self, auth_client, db_session, business, monkeypatch
    ):
        """Both pass the ledger check before either commits; the unique key
        lets one through and the other answers as a replay."""
        _pay(auth_client, business.id, payment="pay_1")
        end = _end(_pay(auth_client, business.id, payment="pay_race"))

        real = subscriptions_router._applied_payment
        calls = {"n": 0}

        def blind_first_time(db, payment_id):
            calls["n"] += 1
            return None if calls["n"] == 1 else real(db, payment_id)

        monkeypatch.setattr(subscriptions_router, "_applied_payment", blind_first_time)
        # The row's current payment is pay_race, so replay it as pay_1's twin:
        # pay_1 is in the ledger but not on the row, which is the case only the
        # ledger can catch — and the first lookup is blinded.
        again = _pay(auth_client, business.id, payment="pay_1")
        assert again.status_code == 200
        assert _end(again) == end
        assert db_session.query(SubscriptionPayment).filter_by(
            razorpay_payment_id="pay_1"
        ).count() == 1


def _aware(moment):
    from datetime import UTC

    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


class TestASignatureWithANonAsciiCharacterIsRefusedNotA500:
    """``hmac.compare_digest`` on two ``str`` raises ``TypeError`` when either
    holds a non-ASCII character, and every one of these compared a value the
    client sent. The default TestClient re-raises an unhandled exception, so a
    crash here fails the test rather than reading as a status."""

    SIG = "é" * 64

    def test_razorpay_signatures_are_simply_unequal(self, monkeypatch):
        from app.core.config import settings
        from app.services import razorpay_client

        monkeypatch.setattr(settings, "razorpay_key_secret", "secret")
        monkeypatch.setattr(settings, "razorpay_webhook_secret", "hook-secret")
        assert razorpay_client.verify_payment_signature("order_1", "pay_1", self.SIG) is False
        assert razorpay_client.verify_webhook_signature(b"{}", self.SIG) is False

    def test_verify_payment_answers_400(self, auth_client, business, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "razorpay_key_secret", "secret")
        response = auth_client.post(
            "/api/v1/subscriptions/verify-payment",
            json={
                "razorpay_order_id": "order_1",
                "razorpay_payment_id": "pay_1",
                "razorpay_signature": self.SIG,
                "tier": "pro",
            },
        )
        assert response.status_code == 400

    def test_the_razorpay_webhook_refuses_it(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "razorpay_webhook_secret", "hook-secret")
        response = client.post(
            "/api/v1/subscriptions/webhook",
            content=b"{}",
            # Raw latin-1 bytes: the test client will not encode a non-ASCII
            # str header, and the server decodes headers as latin-1 anyway.
            headers={
                "X-Razorpay-Signature": ("é" * 10).encode("latin-1"),
                "content-type": "application/json",
            },
        )
        assert 400 <= response.status_code < 500

    def test_the_whatsapp_handshake_answers_403(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "whatsapp_verify_token", "the-token")
        response = client.get(
            "/api/v1/whatsapp/webhook",
            params={"hub.mode": "subscribe", "hub.verify_token": "é", "hub.challenge": "1"},
        )
        assert response.status_code == 403

    def test_an_unsubscribe_link_with_a_mangled_token_is_refused(self, client):
        response = client.get(
            "/api/v1/subscribers/unsubscribe",
            params={"email": "a@example.com", "token": "é" * 64},
        )
        assert response.status_code == 200
        assert response.json()["unsubscribed"] is False


class TestRetryAfterIsLongEnough:
    """It was the seconds left in the window *truncated*: with 49.5s to go it
    said 49, and a client that waited exactly that long retried half a second
    early, inside the same window, and was refused again."""

    GSTIN = "/api/v1/meta/gstin/27AAPFU0939F1ZV"

    def test_waiting_exactly_retry_after_seconds_is_enough(
        self, client, rate_limited, pinned_window
    ):
        pinned_window(10.5)
        for _ in range(30):
            client.get(self.GSTIN)
        refused = client.get(self.GSTIN)
        assert refused.status_code == 429
        wait = int(refused.headers["Retry-After"])
        assert wait == 50  # 49.5 seconds left, rounded up

        pinned_window(wait)
        assert client.get(self.GSTIN).status_code == 200

    def test_at_the_very_start_of_a_window_it_is_the_whole_window(
        self, client, rate_limited, pinned_window
    ):
        for _ in range(30):
            client.get(self.GSTIN)
        assert client.get(self.GSTIN).headers["Retry-After"] == "60"
