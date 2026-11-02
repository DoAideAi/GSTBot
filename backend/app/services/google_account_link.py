"""Require both Google proof and the existing password before linking accounts."""
from __future__ import annotations

import hmac
import secrets
import time
from typing import NoReturn

from fastapi import HTTPException, Request
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import charge, register_limit_name
from app.core.ratespec import parse_rate
from app.core.security import _password_fingerprint, verify_password
from app.models.user import User

SESSION_KEY = "google_account_link"
LINK_SECONDS = 5 * 60
_ACCOUNT_LIMIT = register_limit_name("google_link_account")
_EXPIRED = "This Google sign-in link expired or has already been used. Start again with Google."


def eligible(user: User) -> bool:
    return bool(
        user.is_active and user.hashed_password
        and user.oauth_provider is None and user.oauth_id is None
    )


def begin(request: Request, user: User, google_id: str) -> None:
    # Only the verified Google callback may create this proof. The signed,
    # HttpOnly session binds it to this browser; it is never an access token.
    request.session[SESSION_KEY] = {
        "user_id": user.id,
        "email": user.email,
        "google_id": google_id,
        "client_id": settings.google_client_id,
        "password_version": _password_fingerprint(user.hashed_password),
        "expires_at": int(time.time()) + LINK_SECONDS,
        "csrf_token": secrets.token_urlsafe(32),
    }


def _refuse(request: Request) -> NoReturn:
    request.session.pop(SESSION_KEY, None)
    raise HTTPException(400, _EXPIRED, headers={"Cache-Control": "no-store"})


def pending(request: Request, db: Session) -> tuple[User, dict]:
    proof = request.session.get(SESSION_KEY)
    if (
        not isinstance(proof, dict)
        or not isinstance(proof.get("expires_at"), int)
        or proof["expires_at"] <= time.time()
        or not isinstance(proof.get("user_id"), int)
        or not isinstance(proof.get("google_id"), str)
        or not proof["google_id"]
        or not isinstance(proof.get("csrf_token"), str)
        or not proof["csrf_token"]
        or proof.get("client_id") != settings.google_client_id
    ):
        _refuse(request)
    user = db.get(User, proof["user_id"])
    if (
        user is None or not eligible(user) or user.email != proof.get("email")
        or not hmac.compare_digest(
            str(proof.get("password_version", "")),
            _password_fingerprint(user.hashed_password),
        )
    ):
        _refuse(request)
    return user, proof


def complete(request: Request, db: Session, password: str, csrf_token: str) -> User:
    user, proof = pending(request, db)
    if not hmac.compare_digest(proof["csrf_token"].encode(), csrf_token.encode()):
        raise HTTPException(
            403, "The linking request could not be verified. Start again with Google.",
            headers={"Cache-Control": "no-store"},
        )
    # A copied pending cookie or a new OAuth attempt cannot reset the password
    # budget, and changing network addresses must not bypass it either.
    if settings.rate_limit_enabled:
        budget = charge(
            f"{_ACCOUNT_LIMIT}:{user.id}",
            parse_rate(settings.rate_limits.get(_ACCOUNT_LIMIT, "10/15m")),
        )
        if not budget.allowed:
            request.state.rate_limit = budget
            raise HTTPException(
                429, "Too many password attempts. Please wait before trying again.",
                headers={"Retry-After": str(budget.retry_after), "Cache-Control": "no-store"},
            )
    password_hash = user.hashed_password
    if not verify_password(password, password_hash):
        raise HTTPException(
            400, "Incorrect DoAide GST password. Try again.",
            headers={"Cache-Control": "no-store"},
        )
    # Compare-and-set makes the proof single-use even across concurrent tabs.
    # A password reset, deactivation or competing link must win over this one.
    try:
        result = db.execute(
            update(User).where(
                User.id == user.id,
                User.email == proof["email"],
                User.is_active.is_(True),
                User.hashed_password == password_hash,
                User.oauth_provider.is_(None),
                User.oauth_id.is_(None),
            ).values(oauth_provider="google", oauth_id=proof["google_id"]),
            execution_options={"synchronize_session": False},
        )
        if result.rowcount != 1:
            db.rollback()
            _refuse(request)
        db.commit()
    except IntegrityError:
        db.rollback()
        _refuse(request)
    request.session.pop(SESSION_KEY, None)
    db.refresh(user)
    return user
