"""A bounded free pilot must never become a payment or permanent access."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import require_paid_tier
from app.models.business import Business
from app.models.business_membership import BusinessMembership, MembershipRole
from app.models.pilot import PilotBusiness, PilotEnrollment
from app.models.subscription import Subscription, SubscriptionTier
from app.models.subscription_payment import SubscriptionPayment
from app.models.user import User, UserRole
from app.services import invoice_service, pilots, razorpay_client, usage
from tests.test_invoices import upload
from tests.test_reconciliation_report import _run

URL = "/api/v1/subscriptions/pilot"


def start(client, tier="pro"):
    response = client.post(URL, json={"tier": tier})
    assert response.status_code == 200, response.text
    return response.json()


def owner(db, business):
    return db.scalar(select(User).where(User.business_id == business.id))


def another(db, user=None, role=MembershipRole.ACCOUNTANT):
    biz = Business(legal_name="Another registration")
    db.add(biz)
    db.flush()
    if user:
        db.add(BusinessMembership(user_id=user.id, business_id=biz.id, role=role))
    db.commit()
    return biz


@pytest.mark.parametrize("tier,limit", [("pro", 1), ("enterprise", 5)])
def test_sixty_days_of_access_without_payment(
    auth_client, db_session, business, monkeypatch, tier, limit,
):
    def no_payment(**kwargs):
        pytest.fail("a free pilot must never call the payment gateway")
    monkeypatch.setattr(razorpay_client, "create_order", no_payment)
    state = start(auth_client, tier)
    pilot = db_session.scalar(select(PilotEnrollment))
    assert pilot.ends_at - pilot.starts_at == timedelta(days=60)
    assert state["enrollment"]["business_limit"] == limit
    assert state["enrollment"]["business_ids"] == [business.id]
    assert require_paid_tier(business, db_session).id == pilot.id
    assert usage.get_tier(db_session, business.id).value == tier
    assert invoice_service.plan_limit(business) == 500
    current = auth_client.get("/api/v1/subscriptions/current").json()
    assert current["source"] == "pilot" and current["status"] == "active"
    assert current["current_period_end"]
    assert db_session.scalar(select(func.count()).select_from(Subscription)) == 0
    assert db_session.scalar(select(func.count()).select_from(SubscriptionPayment)) == 0
    order = auth_client.post("/api/v1/subscriptions/create-order", json={"tier": tier})
    assert order.status_code == 409


def test_retrying_does_not_extend_or_switch_a_pilot(auth_client, db_session):
    first = start(auth_client)
    assert start(auth_client) == first
    assert auth_client.post(URL, json={"tier": "enterprise"}).status_code == 409
    assert db_session.scalar(select(func.count()).select_from(PilotEnrollment)) == 1


def test_expiry_blocks_new_work_but_preserves_data_and_report_exports(
    auth_client, db_session, business,
):
    start(auth_client)
    pilot = db_session.scalar(select(PilotEnrollment))
    run = _run(db_session, business)
    run.created_at = datetime.now(UTC) - timedelta(days=2)
    pilot.ends_at = datetime.now(UTC) - timedelta(days=1)
    db_session.commit()
    assert auth_client.get("/api/v1/subscriptions/current").json()["status"] == "expired"
    assert usage.get_tier(db_session, business.id) == SubscriptionTier.FREE
    assert invoice_service.plan_limit(business) == 50
    with pytest.raises(HTTPException) as denied:
        require_paid_tier(business, db_session)
    assert denied.value.status_code == 403
    assert auth_client.get("/api/v1/invoices").status_code == 200
    assert auth_client.get("/api/v1/businesses/mine/export").status_code == 200
    pdf = auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert auth_client.post(URL, json={"tier": "pro"}).status_code == 409
    run.created_at = datetime.now(UTC)
    db_session.commit()
    assert auth_client.get(f"/api/v1/reconciliation/{run.id}/report.pdf").status_code == 402


def test_pilot_report_purchase_does_not_open_checkout(auth_client, db_session, business):
    start(auth_client)
    run = _run(db_session, business)
    response = auth_client.post("/api/v1/reconciliation/report/purchase", json={"run_id": run.id})
    assert response.status_code == 200
    assert response.json()["already_purchased"] is True
    assert auth_client.get(f"/api/v1/reconciliation/{run.id}").json()["report_included"]


def test_deleted_uploads_do_not_reset_the_pilot_allowance(auth_client, business, monkeypatch):
    start(auth_client)
    monkeypatch.setattr(pilots, "INVOICE_LIMIT", 2)
    first = upload(auth_client, "Invoice No: TRIAL-1\nTotal Amount: 100.00", name="one.txt")
    assert first.status_code == 201
    invoice_id = first.json()["invoice"]["id"]
    assert auth_client.delete(f"/api/v1/invoices/{invoice_id}").status_code == 204
    second = upload(auth_client, "Invoice No: TRIAL-2\nTotal Amount: 200.00", name="two.txt")
    assert second.status_code == 201
    third = upload(auth_client, "Invoice No: TRIAL-3\nTotal Amount: 300.00", name="three.txt")
    assert third.status_code == 402
    assert "next calendar month" in third.json()["detail"]
    rows = auth_client.get("/api/v1/subscriptions/usage").json()["usage"]
    assert next(row for row in rows if row["endpoint"] == "invoice_uploads")["call_count"] == 2


def test_ca_covers_five_registrations_without_changing_roles(auth_client, db_session, business):
    user = owner(db_session, business)
    start(auth_client, "enterprise")
    others = [another(db_session, user) for _ in range(5)]
    for other in others[:4]:
        response = auth_client.post(URL + "/businesses", json={"business_id": other.id})
        assert response.status_code == 200, response.text
        assert pilots.active(db_session, other.id).tier == "enterprise"
        assert invoice_service.plan_limit(other) == 500
        assert auth_client.get("/api/v1/subscriptions/current", headers={
            "X-Business-Id": str(other.id),
        }).json()["source"] == "pilot"
    assert auth_client.post(URL + "/businesses",
        json={"business_id": others[-1].id}).status_code == 409
    assert auth_client.post(URL + "/businesses",
        json={"business_id": others[0].id}).status_code == 200
    member = db_session.scalar(select(BusinessMembership).where(
        BusinessMembership.business_id == others[0].id,
    ))
    assert member.role == MembershipRole.ACCOUNTANT
    member.deleted_at = datetime.now(UTC)
    db_session.commit()
    assert auth_client.get("/api/v1/invoices", headers={
        "X-Business-Id": str(others[0].id),
    }).status_code == 403
    assert auth_client.post(URL + "/businesses",
        json={"business_id": others[-1].id}).status_code == 409


def test_smb_cannot_add_an_extra_registration(auth_client, db_session, business):
    start(auth_client)
    other = another(db_session, owner(db_session, business))
    assert auth_client.post(URL + "/businesses", json={"business_id": other.id}).status_code == 409


@pytest.mark.parametrize("role", [None, MembershipRole.VIEWER])
def test_unrelated_and_read_only_registrations_cannot_be_covered(
    auth_client, db_session, business, role,
):
    start(auth_client, "enterprise")
    other = another(db_session, owner(db_session, business) if role else None, role=role)
    assert auth_client.post(URL + "/businesses", json={"business_id": other.id}).status_code == 404
    assert pilots.for_business(db_session, other.id) is None


@pytest.mark.parametrize("role", [UserRole.VIEWER, UserRole.ACCOUNTANT])
def test_only_an_owner_can_enrol(auth_client, db_session, business, role):
    owner(db_session, business).role = role
    db_session.commit()
    assert auth_client.post(URL, json={"tier": "pro"}).status_code == 403


def test_switching_business_cannot_claim_another_pilot(auth_client, db_session, business):
    other = another(db_session, owner(db_session, business), MembershipRole.OWNER)
    assert auth_client.post(URL, json={"tier": "enterprise"}, headers={
        "X-Business-Id": str(other.id),
    }).status_code == 403


def test_switching_business_cannot_manage_home_pilot(auth_client, db_session, business):
    start(auth_client, "enterprise")
    other = another(db_session, owner(db_session, business), MembershipRole.OWNER)
    assert auth_client.post(URL + "/businesses", json={"business_id": other.id}, headers={
        "X-Business-Id": str(other.id),
    }).status_code == 403
    assert pilots.for_business(db_session, other.id) is None


def test_existing_paid_plans_are_preserved(auth_client, db_session, paid_business):
    assert auth_client.post(URL, json={"tier": "pro"}).status_code == 409
    assert auth_client.get("/api/v1/subscriptions/current").json()["source"] == "paid"
    assert db_session.scalar(select(func.count()).select_from(PilotEnrollment)) == 0


@pytest.mark.parametrize("tier", ["pro", "enterprise"])
def test_cohort_capacity_is_lifetime_and_availability_is_truthful(auth_client, db_session, tier):
    for slot in range(1, pilots.CAPACITY[tier] + 1):
        biz = another(db_session)
        user = User(email=f"pilot{tier}{slot}@example.com", business_id=biz.id, role=UserRole.OWNER)
        db_session.add(user)
        db_session.flush()
        db_session.add(PilotEnrollment(business_id=biz.id, user_id=user.id, tier=tier,
            cohort_slot=slot, starts_at=datetime.now(UTC) - timedelta(days=65),
            ends_at=datetime.now(UTC) - timedelta(days=5)))
    db_session.commit()
    offered = auth_client.get("/api/v1/subscriptions/pricing").json()["pilot"]
    assert offered["remaining"][tier] == 0
    assert auth_client.post(URL, json={"tier": tier}).status_code == 409


def test_database_constraints_prevent_overbooking(db_session, business):
    db_session.add(PilotEnrollment(business_id=business.id, user_id=owner(db_session, business).id,
        tier="pro", cohort_slot=21, starts_at=datetime.now(UTC), ends_at=datetime.now(UTC)))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_a_covered_business_cannot_claim_a_second_pilot(auth_client, db_session, business):
    start(auth_client, "enterprise")
    user = owner(db_session, business)
    target = another(db_session, user, MembershipRole.OWNER)
    assert auth_client.post(URL + "/businesses", json={"business_id": target.id}).status_code == 200
    other = User(email="newowner@example.com", business_id=target.id, role=UserRole.OWNER)
    db_session.add(other)
    db_session.commit()
    with pytest.raises(HTTPException) as refused:
        pilots.start(db_session, other, target, "pro")
    assert refused.value.status_code == 409
    assert db_session.scalar(select(func.count()).select_from(PilotBusiness)) == 2
