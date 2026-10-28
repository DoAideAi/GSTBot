"""CA referral program — generate codes, track visits, show a leaderboard.

Public endpoints:
* ``POST /referrals/track`` — record that a visitor arrived via a referral link.
* ``GET /referrals/leaderboard`` — top referring CAs.

Authenticated endpoints:
* ``GET /referrals/my-code`` — the caller's referral code (generated on first call).
* ``GET /referrals/my-stats`` — how many visits and conversions the caller drove.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.rate_limit import RateLimit
from app.models.referral import Referral
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/referrals", tags=["referrals"])

_track_limit = RateLimit("referral_track", "60/minute", by="ip")
_leaderboard_limit = RateLimit("referral_leaderboard", "30/minute", by="ip")
_my_limit = RateLimit("referral_my", "60/minute", by="identity")


def _hash_ip(ip: str) -> str:
    return hashlib.sha256(ip.encode()).hexdigest()[:16]


def _generate_code() -> str:
    return f"CA-{secrets.token_urlsafe(8)}"


class TrackRequest(BaseModel):
    referral_code: str = Field(min_length=1, max_length=64)


@router.post(
    "/track",
    summary="Record a referral visit",
    description=(
        "Called by the frontend when a visitor arrives with ?ref=<code>. "
        "De-duplicates by hashed IP per code so refreshes don't inflate counts. "
        "Public — no auth required."
    ),
    dependencies=[Depends(_track_limit)],
)
def track_referral(
    body: TrackRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    ip = request.client.host if request.client else "unknown"
    ip_hash = _hash_ip(ip)

    referrer = db.query(User).filter(
        User.referral_code == body.referral_code,
        User.is_active.is_(True),
    ).first()
    if referrer is None:
        return {"tracked": False, "reason": "unknown_code"}

    existing = db.query(Referral).filter_by(
        referral_code=body.referral_code,
        visitor_ip_hash=ip_hash,
    ).first()
    if existing is not None:
        return {"tracked": False, "reason": "already_tracked"}

    referral = Referral(
        referral_code=body.referral_code,
        referrer_user_id=referrer.id,
        visitor_ip_hash=ip_hash,
    )
    db.add(referral)
    try:
        db.commit()
    except IntegrityError:
        # The same visitor's other request inserted between the check above and
        # this commit; uq_referrals_code_visitor kept the second row out.
        db.rollback()
        return {"tracked": False, "reason": "already_tracked"}
    logger.info("Referral tracked", extra={"code": body.referral_code})
    return {"tracked": True}


@router.get(
    "/leaderboard",
    summary="Top referring CAs",
    description=(
        "The top 20 referrers by total visit count. Public — shown on the "
        "referral page for social proof and gamification."
    ),
    dependencies=[Depends(_leaderboard_limit)],
)
def leaderboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = (
        db.query(
            Referral.referrer_user_id,
            sa_func.count(Referral.id).label("referral_count"),
        )
        .group_by(Referral.referrer_user_id)
        .order_by(sa_func.count(Referral.id).desc())
        .limit(20)
        .all()
    )

    user_ids = [r[0] for r in rows]
    users = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    leaders = []
    for uid, count in rows:
        user = users.get(uid)
        if user is None:
            continue
        name = user.full_name or user.email.split("@")[0]
        # Only show first name + last initial for privacy
        parts = name.split()
        display = parts[0] + (" " + parts[1][0] + "." if len(parts) > 1 else "")
        leaders.append({
            "name": display,
            "referral_count": count,
        })

    return {"leaders": leaders}


@router.get(
    "/my-code",
    summary="Get or generate the caller's referral code",
    description=(
        "Returns the caller's referral code, generating one on first call. "
        "The code is stable — calling again returns the same one."
    ),
    dependencies=[Depends(_my_limit)],
)
def my_code(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not current_user.referral_code:
        code = _generate_code()
        while db.query(User).filter_by(referral_code=code).first() is not None:
            code = _generate_code()
        current_user.referral_code = code
        db.commit()
    return {"referral_code": current_user.referral_code}


@router.get(
    "/my-stats",
    summary="The caller's referral statistics",
    description="How many visits and signups the caller's referral code has driven.",
    dependencies=[Depends(_my_limit)],
)
def my_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    code = current_user.referral_code
    if not code:
        return {"referral_code": None, "total_visits": 0, "conversions": 0}

    total = db.query(sa_func.count(Referral.id)).filter_by(
        referral_code=code
    ).scalar() or 0
    conversions = db.query(sa_func.count(Referral.id)).filter_by(
        referral_code=code,
        converted=True,
    ).scalar() or 0

    return {
        "referral_code": code,
        "total_visits": total,
        "conversions": conversions,
    }
