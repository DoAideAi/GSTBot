"""Authentication: register (with GSTIN onboarding), login, me.

The rate limits here are the strictest in the product and are keyed by
*address* rather than by identity, because the attack these endpoints face
comes from someone who has no identity yet: credential stuffing against login,
bulk sign-ups against register. Everywhere else, limiting by IP would punish an
office behind one NAT; here it is the only key that means anything.

Login carries a second limit on top, keyed by the account being attempted.
An address limit alone is only as strong as the number of addresses the
attacker has, and a stuffing run's whole shape is one guess per host across
thousands of hosts — twenty a minute each, against one account, is a password
every three seconds from a limiter that never sees the same key twice. The
per-account counter is the one that costs the attacker something, because the
target is the thing they cannot spread the load across.
"""
from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import ActiveTenant, get_active_tenant, get_current_user
from app.core.rate_limit import (
    RateLimit,
    apply_headers,
    charge,
    client_ip,
    forget,
    peek,
    wait_phrase,
)
from app.core.ratespec import Rate, parse_rate
from app.core.security import create_access_token, hash_password, verify_password
from app.models.business import Business, BusinessPlan
from app.models.user import User, UserRole
from app.schemas.auth import (
    BusinessOut,
    MeOut,
    RegisterRequest,
    RegisterResponse,
    Token,
    UserOut,
)
from app.services import gstin as gstin_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Ten sign-ups an hour from one address. A CA onboarding a handful of clients
# stays well under it; a script farming free-tier accounts does not.
_register_limit = RateLimit("register", "10/hour", by="ip")
# Twenty attempts a minute is far more than someone who has forgotten their
# password needs, and far less than a stuffing run wants.
_login_limit = RateLimit("login", "20/minute", by="ip")
_me_limit = RateLimit("me", "120/minute")

# The per-account failure budget, spent by wrong passwords and refunded the
# moment a right one arrives. Ten in a quarter of an hour: a person who has
# forgotten which of their passwords it is runs out of guesses long before
# this, and an attacker who has spread themselves over a thousand hosts still
# only gets forty guesses an hour at any one account.
_LOGIN_ACCOUNT_LIMIT = "login_account"
_LOGIN_ACCOUNT_SPEC = "10/15m"


def _account_rate() -> Rate:
    # Read per call rather than memoised, so RATE_LIMIT_OVERRIDES and a test's
    # monkeypatch both take effect without a restart.
    return parse_rate(settings.rate_limits.get(_LOGIN_ACCOUNT_LIMIT, _LOGIN_ACCOUNT_SPEC))


def _account_key(username: str) -> str:
    """The counter key for the account *username* names.

    Folded the same way the lookup folds it, so varying the case cannot mint a
    fresh budget. Hashed rather than stored plain because these keys outlive
    the request in Redis, and Redis is not where this product's email addresses
    should be legible — the same reason the failed-login log line carries the
    address of the caller and not the account they guessed at.
    """
    digest = hashlib.sha256(username.strip().lower().encode("utf-8")).hexdigest()
    return f"{_LOGIN_ACCOUNT_LIMIT}:{digest[:32]}"


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a business and its owner login",
    description=(
        "One call creates the tenant (a GST registration) and the owner account "
        "that files under it, and returns a usable token — there is no second "
        "login round trip.\n\n"
        "The GSTIN's check digit is verified before anything is written, and the "
        "state code and PAN it encodes are decoded and stored, because they "
        "decide the IGST-vs-CGST/SGST split on every invoice that follows."
    ),
    responses={
        201: {"description": "Business and owner created; the token is live."},
        409: {
            "description": (
                "The email is taken, or this GSTIN is already registered — which "
                "is an invitation problem, not a registration one."
            )
        },
        422: {"description": "The GSTIN failed its check digit, or a field is invalid."},
    },
    dependencies=[Depends(_register_limit)],
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> RegisterResponse:
    """Create a business and its owner login in one step.

    GSTIN is optional — a user can sign up to explore the product and add their
    registration later. When provided, the GSTIN has already been validated and
    normalised by the schema, so what remains here is uniqueness.
    """
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists. Sign in with it instead.",
        )

    legal_name = (payload.legal_name or payload.full_name or email.split("@")[0]).strip()

    if payload.gstin:
        if db.scalar(select(Business).where(Business.gstin == payload.gstin)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This GSTIN is already registered. Ask its owner to invite you.",
            )
        parts = gstin_service.parse(payload.gstin)
        business = Business(
            gstin=parts.gstin,
            legal_name=legal_name,
            trade_name=payload.trade_name,
            state_code=parts.state_code,
            pan=parts.pan,
            plan=BusinessPlan.FREE,
        )
    else:
        business = Business(
            gstin=None,
            legal_name=legal_name,
            trade_name=payload.trade_name,
            state_code=None,
            pan=None,
            plan=BusinessPlan.FREE,
        )

    db.add(business)
    db.flush()

    user = User(
        business_id=business.id,
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
        role=UserRole.OWNER,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(business)

    logger.info(
        "Business registered",
        extra={"business_id": business.id, "user_id": user.id},
    )

    return RegisterResponse(
        user=UserOut.model_validate(user),
        business=BusinessOut.from_business(business),
        access_token=create_access_token(user.id),
    )


@router.post(
    "/login",
    response_model=Token,
    summary="Exchange email and password for a bearer token",
    description=(
        "OAuth2 password flow, so the body is form-encoded and the email goes in "
        "the field named `username`.\n\n"
        "The token is a JWT whose `sub` claim is the user id; send it as "
        "`Authorization: Bearer <token>`. It expires after "
        "`ACCESS_TOKEN_EXPIRE_MINUTES` (24 hours by default) and there is no "
        "refresh flow — a filing session is not a long-lived one."
    ),
    responses={
        401: {
            "description": (
                "Wrong email or password. One message for both, so the endpoint "
                "cannot be used to enumerate which GSTINs have accounts."
            )
        },
        403: {"description": "The account exists but has been deactivated."},
        429: {
            "description": (
                "Too many attempts from this address, or too many failed "
                "attempts against this account from anywhere."
            )
        },
    },
    dependencies=[Depends(_login_limit)],
)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    # ``None`` switches the per-account counter off wholesale, which is how
    # RATE_LIMIT_ENABLED=false stays a single decision rather than three.
    account_rate = _account_rate() if settings.rate_limit_enabled else None
    account_key = _account_key(form.username)

    # Checked before the password is, so a spent budget costs the attacker a
    # rejection rather than a bcrypt round — which is the point: the work this
    # endpoint does per attempt is what a stuffing run is buying.
    if account_rate is not None:
        budget = peek(account_key, account_rate)
        if not budget.allowed:
            logger.warning(
                "Login blocked: account attempt budget exhausted",
                extra={"client_ip": client_ip(request), "status_code": 429},
            )
            # Overwrites the address limiter's decision, which the dependency
            # left here on the way in. The access-log middleware copies
            # whatever is on the request onto the response, so without this the
            # caller is told they have budget left by the very response
            # refusing them for having none.
            request.state.rate_limit = budget
            headers = {"Retry-After": str(budget.retry_after)}
            apply_headers(headers, budget)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    "Too many failed sign-in attempts for this account. "
                    f"Try again in {wait_phrase(budget.retry_after)}, and check the email "
                    "and password carefully before you do."
                ),
                headers=headers,
            )

    # OAuth2PasswordRequestForm calls it ``username``; we treat it as the email.
    # Registration stores the address folded to lower case, so that is the
    # indexed lookup. The second attempt covers rows written before the folding
    # existed — an exact match on what the user typed — rather than a
    # ``lower(email)`` comparison, which no index could serve.
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if user is None and form.username != form.username.lower():
        user = db.scalar(select(User).where(User.email == form.username))
    # ``None`` when no row matched, and ``verify_password`` hashes against a
    # throwaway digest in that case rather than returning early. Both branches
    # therefore cost one bcrypt round, which is what stops the response time
    # answering the question the identical 401 body refuses to. Verified before
    # the branch, not inside it, so no short circuit can skip that round.
    matched = verify_password(form.password, user.hashed_password if user else None)
    if user is None or not matched:
        if account_rate is not None:
            charge(account_key, account_rate)
        # Logged without the attempted email: a failed-login log is exactly
        # where a mistyped password ends up sitting next to the address that
        # typed it.
        logger.warning("Failed login attempt", extra={"client_ip": client_ip(request)})
        # One message for both cases, so the endpoint cannot be used to
        # enumerate which GSTINs have accounts.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Refunded on proof of identity, and before the active check: a deactivated
    # account whose owner still types the right password is not a guess, and
    # leaving its counter spent would let anyone lock that account's budget
    # empty on its owner's behalf. That refund is what keeps a per-account
    # counter from being a way to deny someone their own login.
    if account_rate is not None:
        forget(account_key, account_rate)

    if not user.is_active:
        # The right password for an account somebody switched off: an
        # off-boarded login still in use, which is worth an alert. The other
        # two outcomes of this route leave a line; this one left none, and the
        # access line cannot name the user, because no token was resolved.
        logger.warning(
            "Login refused: account deactivated",
            extra={
                "user_id": user.id,
                "business_id": user.business_id,
                "client_ip": client_ip(request),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Contact support to reactivate it.",
        )

    logger.info("Login", extra={"user_id": user.id, "business_id": user.business_id})
    return Token(access_token=create_access_token(user.id))


@router.get(
    "/me",
    response_model=MeOut,
    summary="The signed-in user and the business they act for",
    description=(
        "Returns both in one response because the frontend needs both on every "
        "page load, and a second round trip for the business would be one the "
        "app always makes.\n\n"
        "Also the session check: a 401 here means the stored token is expired or "
        "belongs to a deleted user.\n\n"
        "`active_role` is the role held **on the business in this response**, "
        "which is what the API enforces. It differs from the top-level `role` "
        "whenever `X-Business-Id` points at a linked business."
    ),
    dependencies=[Depends(_me_limit)],
)
def me(
    current_user: User = Depends(get_current_user),
    tenant: ActiveTenant = Depends(get_active_tenant),
) -> MeOut:
    # ``get_active_tenant`` rather than ``get_current_business``, for the role
    # that comes with it. ``UserOut.role`` is the role on the login's own
    # business, and answering with only that is the mistake the whole tenancy
    # design exists to prevent one layer down: an owner of their own books who
    # has been linked into a client as a *viewer* was told "owner" here while
    # every write to that client answered 403. The frontend has no other way to
    # know which controls to show, so it showed them all and let the user find
    # out by being refused.
    #
    # ``get_current_business`` depends on this same callable, and FastAPI caches
    # a dependency per request by the callable that declares it, so reading the
    # tenant here still runs the membership lookup exactly once.
    return MeOut(
        **UserOut.model_validate(current_user).model_dump(),
        business=BusinessOut.from_business(tenant.business),
        active_role=tenant.role,
    )
