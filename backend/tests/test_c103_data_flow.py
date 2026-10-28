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
