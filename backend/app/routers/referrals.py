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
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func as sa_func
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.rate_limit import RateLimit, client_ip
from app.core.sanitize import visible_text
from app.models.referral import Referral
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/referrals", tags=["referrals"])

_track_limit = RateLimit("referral_track", "60/minute", by="ip")
_leaderboard_limit = RateLimit("referral_leaderboard", "30/minute", by="ip")
_my_limit = RateLimit("referral_my", "60/minute", by="identity")


def _hash_ip(ip: str) -> str:
    """A stable, unreversible key for one visitor's address.

    Keyed with a server secret. A bare SHA-256 of an IPv4 address is reversed by
    hashing all four billion of them — an afternoon on a laptop — so every
    stored "hash" was the visitor's address in all but name, kept indefinitely
    for a statistic. The prefix separates this use of the secret from signing
    tokens with it.
    """
    key = settings.jwt_secret.encode()
    return hmac.new(key, b"referral-visitor:" + ip.encode(), hashlib.sha256).hexdigest()[:32]


# How long after a visit a sign-up from the same visitor still counts as the
# referral converting.
CONVERSION_WINDOW = timedelta(days=30)


def visitor_ip(request: Request) -> str:
    """The address a referral visit is keyed on — the same one ``/track`` uses.

    Through :func:`client_ip`, like the rate limiter: reading ``request.client``
    here meant the two disagreed about who the caller was whenever
    ``TRUST_PROXY_HEADERS`` is the thing supplying the real address.
    """
    return client_ip(request)


def record_conversion(db: Session, ip: str) -> bool:
    """Mark this visitor's latest open referral as converted; ``True`` if one was.

    ``converted`` existed, ``/my-stats`` counted it and the referral page shows
    it as "Signups" — and nothing ever set it, so every CA's count read 0 no
    matter who signed up through their link. A sign-up is matched to a visit
    the way ``/track`` recognised the visit: by the visitor's hashed address.
    The most recent visit wins when one visitor followed two links, and only
    within :data:`CONVERSION_WINDOW`.

    Best effort, in its own commit after the account exists: attribution is a
    statistic, and a sign-up must never fail for its sake.
    """
    try:
        latest = db.scalar(
            select(Referral.id)
            .where(
                Referral.visitor_ip_hash == _hash_ip(ip),
                Referral.converted.is_(False),
                Referral.created_at >= datetime.now(UTC) - CONVERSION_WINDOW,
            )
            .order_by(Referral.created_at.desc(), Referral.id.desc())
            .limit(1)
        )
        if latest is None:
            return False
        # Conditional on still being open: two sign-ups from one address in
        # the same moment both find this visit, and only one may convert it.
        # The loser reports False rather than claiming a conversion it lost.
        converted = db.execute(
            update(Referral)
            .where(Referral.id == latest, Referral.converted.is_(False))
            .values(converted=True)
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()
        if converted:
            logger.info("Referral converted", extra={"referral_id": latest})
        return bool(converted)
    except Exception:  # noqa: BLE001 - a statistic must not fail a sign-up
        db.rollback()
        logger.exception("Referral conversion not recorded")
        return False


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
    ip_hash = _hash_ip(visitor_ip(request))

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
    # A deactivated account is not someone to put on a public page.
    users = {
        u.id: u
        for u in db.query(User).filter(User.id.in_(user_ids), User.is_active.is_(True)).all()
    } if user_ids else {}

    leaders = []
    for uid, count in rows:
        user = users.get(uid)
        if user is None:
            continue
        leaders.append({
            "name": _public_name(user.full_name),
            "referral_count": count,
        })

    return {"leaders": leaders}


def _public_name(full_name: str | None) -> str:
    """First name and last initial, for a page anyone can read.

    Never the email. A user with no name was shown as their address's local
    part — "suman.sharma1990" on a public leaderboard is most of an email
    address — and a name that is only whitespace split to nothing and took
    the whole endpoint down with an IndexError, for every visitor, for as
    long as that user ranked.
    """
    parts = visible_text(full_name or "", keep_newlines=False).split()
    if not parts:
        return "A DoAide GST user"
    return parts[0] + (f" {parts[-1][0]}." if len(parts) > 1 else "")


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
        # Claimed only if still unclaimed, and then read back. Assigning it
        # outright let two first calls — two tabs, or two components asking at
        # once — each generate a code and each commit it, the later one
        # overwriting the earlier. The first caller had already been handed its
        # code and may have shared it; once overwritten it answered
        # ``unknown_code`` at /track, and every visit through that link was
        # dropped with nothing to say why. Whichever request claims first, both
        # now return the code that stuck.
        db.execute(
            update(User)
            .where(User.id == current_user.id, User.referral_code.is_(None))
            .values(referral_code=code)
        )
        db.commit()
        db.refresh(current_user)
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
