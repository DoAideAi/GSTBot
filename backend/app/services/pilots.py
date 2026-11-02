"""Admission, coverage and expiry for the founding-customer pilot."""
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ratespec import parse_rate
from app.models.business import Business
from app.models.business_membership import BusinessMembership, MembershipRole
from app.models.mixins import utcnow
from app.models.pilot import PilotBusiness, PilotEnrollment
from app.models.subscription import Subscription
from app.models.user import User, UserRole

DAYS = 60
CAPACITY = {"pro": 20, "enterprise": 10}
BUSINESS_LIMIT = {"pro": 1, "enterprise": 5}
INVOICE_LIMIT = 500


def for_business(db: Session, business_id: int) -> PilotEnrollment | None:
    return db.scalar(select(PilotEnrollment).join(PilotBusiness).where(
        PilotBusiness.business_id == business_id,
    ))


def active(db: Session, business_id: int) -> PilotEnrollment | None:
    pilot = for_business(db, business_id)
    return pilot if pilot is not None and pilot.active(utcnow()) else None


def report_included(db: Session, business_id: int, created_at: datetime) -> bool:
    pilot = for_business(db, business_id)
    if pilot is None:
        return False
    # Exports of existing work survive expiry; this does not allow a new run.
    created = created_at.replace(tzinfo=UTC) if created_at.tzinfo is None else created_at
    end = pilot.ends_at.replace(tzinfo=UTC) if pilot.ends_at.tzinfo is None else pilot.ends_at
    return created < end


def offer(db: Session) -> dict:
    counts = dict(db.execute(select(PilotEnrollment.tier, func.count()).group_by(
        PilotEnrollment.tier,
    )).all())
    return {
        "days": DAYS, "capacity": CAPACITY,
        "remaining": {tier: max(0, cap - counts.get(tier, 0)) for tier, cap in CAPACITY.items()},
        "business_limits": BUSINESS_LIMIT, "monthly_invoice_limit": INVOICE_LIMIT,
        "payment_required": False,
        "advisor_allowance": parse_rate(settings.rate_limits.get("advisor_daily", "100/day")).label,
        "reparse_allowance": parse_rate(
            settings.rate_limits.get("invoice_reparse_daily", "100/day"),
        ).label,
    }


def _serialise(db: Session) -> None:
    # All admissions and client additions share this transaction lock. Unique
    # slots also enforce the cohort ceilings in the database, including SQLite.
    if db.get_bind().dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(-6072026, 60)))


def _own(db: Session, user: User) -> PilotEnrollment | None:
    return db.scalar(select(PilotEnrollment).where(or_(
        PilotEnrollment.user_id == user.id, PilotEnrollment.business_id == user.business_id,
    )))


def _paid(db: Session, business_id: int) -> bool:
    sub = db.scalar(select(Subscription).where(Subscription.business_id == business_id))
    return sub is not None and sub.is_paid()


def _home_owner(user: User, business: Business) -> bool:
    return user.role == UserRole.OWNER and user.business_id == business.id


def eligible_businesses(db: Session, user: User) -> list[Business]:
    linked = exists().where(
        BusinessMembership.user_id == user.id,
        BusinessMembership.business_id == Business.id,
        BusinessMembership.deleted_at.is_(None),
        BusinessMembership.role.in_([MembershipRole.OWNER, MembershipRole.ACCOUNTANT]),
    )
    return list(db.scalars(select(Business).where(
        Business.reachable(), or_(Business.id == user.business_id, linked),
    ).order_by(Business.id)))


def status(db: Session, user: User, business: Business) -> dict:
    pilot = _own(db, user)
    owner = _home_owner(user, business)
    info = None
    if pilot is not None:
        info = {
            "tier": pilot.tier, "starts_at": pilot.starts_at, "ends_at": pilot.ends_at,
            "active": pilot.active(utcnow()), "business_limit": BUSINESS_LIMIT[pilot.tier],
            "business_ids": list(db.scalars(select(PilotBusiness.business_id).where(
                PilotBusiness.pilot_id == pilot.id,
            ).order_by(PilotBusiness.slot))),
        }
    return {
        "enrollment": info,
        "can_start": owner and pilot is None and for_business(db, business.id) is None
        and not _paid(db, business.id),
        "can_manage": owner and pilot is not None and pilot.user_id == user.id,
        "is_home": user.business_id == business.id,
        "businesses": [{"id": b.id, "name": b.legal_name, "gstin": b.gstin}
                       for b in eligible_businesses(db, user)] if owner else [],
    }


def start(db: Session, user: User, business: Business, tier: str) -> PilotEnrollment:
    if not _home_owner(user, business):
        raise HTTPException(403, "Switch to your own business as its owner to start a pilot.")
    if tier not in CAPACITY:
        raise HTTPException(400, "Choose SMB or CA for the introductory pilot.")
    _serialise(db)
    existing = _own(db, user)
    if existing is not None:
        if existing.user_id == user.id and existing.tier == tier and existing.active(utcnow()):
            return existing  # Retry never changes its dates or consumes another place.
        raise HTTPException(409, "This account has already used its one introductory pilot.")
    if for_business(db, business.id) is not None:
        raise HTTPException(409, "This business has already received introductory access.")
    if _paid(db, business.id):
        raise HTTPException(409, "Your paid plan is active. Its access and billing stay unchanged.")
    slot = int(db.scalar(select(func.count()).select_from(PilotEnrollment).where(
        PilotEnrollment.tier == tier,
    )) or 0) + 1
    if slot > CAPACITY[tier]:
        raise HTTPException(409, "This pilot cohort is full. Contact us about the next intake.")
    now = utcnow()
    pilot = PilotEnrollment(business_id=business.id, user_id=user.id, tier=tier,
                            cohort_slot=slot, starts_at=now, ends_at=now + timedelta(days=DAYS))
    try:
        db.add(pilot)
        db.flush()
        db.add(PilotBusiness(pilot_id=pilot.id, business_id=business.id, slot=1))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "A pilot place was just claimed. Refresh pricing and try again.",
        ) from None
    return pilot


def cover(db: Session, user: User, business: Business, target_id: int) -> None:
    if not _home_owner(user, business):
        raise HTTPException(403, "Switch to your own business as its owner to manage the pilot.")
    _serialise(db)
    pilot = _own(db, user)
    if pilot is None or pilot.user_id != user.id or not pilot.active(utcnow()):
        raise HTTPException(409, "There is no active pilot to add a registration to.")
    if target_id not in {b.id for b in eligible_businesses(db, user)}:
        raise HTTPException(404, "No accessible registration found. Link its account first.")
    previous = db.scalar(select(PilotBusiness).where(PilotBusiness.business_id == target_id))
    if previous is not None:
        if previous.pilot_id == pilot.id:
            return
        raise HTTPException(409, "This registration has already received introductory access.")
    if _paid(db, target_id):
        raise HTTPException(409, "This registration already has an active paid plan.")
    count = int(db.scalar(select(func.count()).select_from(PilotBusiness).where(
        PilotBusiness.pilot_id == pilot.id,
    )) or 0)
    if count >= BUSINESS_LIMIT[pilot.tier]:
        raise HTTPException(409, "All registration places in your pilot have been used.")
    try:
        db.add(PilotBusiness(pilot_id=pilot.id, business_id=target_id, slot=count + 1))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, "Coverage changed. Refresh the page before trying again.",
        ) from None
