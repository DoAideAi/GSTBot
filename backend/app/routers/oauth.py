"""OAuth SSO endpoints: Google, GitHub, Microsoft."""
from __future__ import annotations

import logging
from typing import Any

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import RateLimit
from app.core.security import create_access_token
from app.models.business import Business, BusinessPlan
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

oauth = OAuth()

if settings.google_client_id:
    oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

if settings.github_client_id:
    oauth.register(
        name="github",
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        authorize_url="https://github.com/login/oauth/authorize",
        access_token_url="https://github.com/login/oauth/access_token",
        api_base_url="https://api.github.com/",
        client_kwargs={"scope": "user:email"},
    )

if settings.microsoft_client_id:
    oauth.register(
        name="microsoft",
        client_id=settings.microsoft_client_id,
        client_secret=settings.microsoft_client_secret,
        server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

FRONTEND_URL = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"

_oauth_initiate_limit = RateLimit("oauth_initiate", "30/minute", by="ip")
_oauth_callback_limit = RateLimit("oauth_callback", "30/minute", by="ip")

# What these six routes answer, for the spec. Each one *redirects* — to the
# provider, or back into the app with a token or an error code — and the spec
# said 200, which no client following it would ever see. And each one raises
# 501 from `_configured_client` when the provider has no client id, which the
# spec did not mention. Declaring the status code here documents the redirect
# without changing it: every handler returns its RedirectResponse directly, and
# a returned Response keeps its own status.
_NOT_CONFIGURED = {
    501: {"description": "This sign-in provider is not configured on this deployment."}
}
_LOGIN_REDIRECT: dict[str, Any] = {
    "status_code": status.HTTP_302_FOUND,  # authlib's authorize_redirect
    "response_class": RedirectResponse,
    "responses": {
        302: {"description": "Redirect to the provider's consent screen."},
        **_NOT_CONFIGURED,
    },
}
_CALLBACK_REDIRECT: dict[str, Any] = {
    "status_code": status.HTTP_307_TEMPORARY_REDIRECT,  # RedirectResponse's default
    "response_class": RedirectResponse,
    "responses": {
        307: {
            "description": (
                "Redirect into the app: `/auth/callback#token=…` on success, "
                "`/login?error=<code>` on failure."
            )
        },
        **_NOT_CONFIGURED,
    },
}


#: How each provider is named in an error the user or a log reader sees.
_PROVIDER_LABELS = {"google": "Google", "github": "GitHub", "microsoft": "Microsoft"}


def _callback_url(provider: str) -> str:
    return f"{settings.oauth_redirect_base}{settings.api_v1_prefix}/auth/{provider}/callback"


def _configured_client(provider: str) -> Any:
    """The registered authlib client for *provider*, or a 501 if it has no client id.

    Read from settings on every call rather than once at import, so a
    deployment (or a test) that sets the id later is honoured the same way the
    three hand-written copies of this check honoured it.
    """
    if not getattr(settings, f"{provider}_client_id"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                f"Sign-in with {_PROVIDER_LABELS[provider]} is not available on "
                "this site. Sign in with your email and password instead."
            ),
        )
    return oauth.create_client(provider)


async def _start_login(request: Request, provider: str) -> Any:
    """Redirect to *provider*'s consent screen."""
    client = _configured_client(provider)
    return await client.authorize_redirect(request, _callback_url(provider))


def _login_error(code: str) -> RedirectResponse:
    """Send the browser back to the login page with *code* for it to explain."""
    return RedirectResponse(f"{FRONTEND_URL}/login?error={code}")


def _provider_id(value: object) -> str:
    """The provider's account id as text, or "" when it sent none.

    ``str(profile.get("id", ""))`` turned a null id into the string "None", and
    ``.get("sub", "")`` kept an absent one as "": either is then looked up as an
    identity, and matches whichever account was once stored with the same
    placeholder. The callers refuse an empty one.
    """
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _find_or_create_oauth_user(
    db: Session,
    *,
    provider: str,
    oauth_id: str,
    email: str,
    name: str | None,
    email_verified: bool = False,
) -> User | None:
    user = db.scalar(
        select(User).where(User.oauth_provider == provider, User.oauth_id == oauth_id)
    )
    if user:
        if not user.is_active:
            return None
        return user

    user = db.scalar(select(User).where(User.email == email))
    if user:
        if not user.is_active:
            return None
        if not email_verified:
            logger.warning(
                "OAuth link refused: provider did not verify email",
                extra={"provider": provider, "user_id": user.id},
            )
            return None
        if not user.oauth_provider:
            user.oauth_provider = provider
            user.oauth_id = oauth_id
            db.commit()
            db.refresh(user)
            logger.info(
                "OAuth provider linked to existing account",
                extra={"provider": provider, "user_id": user.id},
            )
        return user

    business = Business(
        legal_name=name or email.split("@")[0],
        plan=BusinessPlan.FREE,
        is_active=True,
    )
    db.add(business)
    db.flush()

    user = User(
        email=email,
        full_name=name,
        business_id=business.id,
        role=UserRole.OWNER,
        oauth_provider=provider,
        oauth_id=oauth_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(
        "OAuth account created",
        extra={
            "provider": provider,
            "user_id": user.id,
            "business_id": business.id,
        },
    )
    # Not a column: read once, by the redirect below, to tell the frontend that
    # this sign-in was a sign-up. The funnel has to count those, and from the
    # callback page a new account and a returning one look the same.
    user.oauth_created = True
    return user


def _complete_oauth_login(user: User | None, provider: str) -> RedirectResponse:
    if user is None:
        return _login_error("account_deactivated")
    logger.info(
        "OAuth login",
        extra={"user_id": user.id, "business_id": user.business_id, "provider": provider},
    )
    access_token = create_access_token(user.id)
    # Fragment (not query param) so the token never reaches server logs or
    # Referer headers. ``new`` and ``provider`` ride along for the same reason
    # and are what the callback page reports to analytics.
    fragment = f"token={access_token}&provider={provider}"
    # Popped, not read: the session's identity map hands this same object back
    # to the next lookup of this user, which would otherwise report a
    # returning sign-in as a second sign-up.
    if vars(user).pop("oauth_created", False):
        fragment += "&new=1"
    return RedirectResponse(f"{FRONTEND_URL}/auth/callback#{fragment}")


# ── Google ────────────────────────────────────────────────

@router.get(
    "/google",
    summary="Initiate Google OAuth login",
    description="Redirects to Google's consent screen. The browser returns to `/google/callback`.",
    dependencies=[Depends(_oauth_initiate_limit)],
    **_LOGIN_REDIRECT,
)
async def google_login(request: Request):
    return await _start_login(request, "google")


@router.get(
    "/google/callback",
    summary="Handle Google OAuth callback",
    description=(
        "Exchanges Google's authorization code for a token, resolves the user "
        "(creating an account if needed), and redirects into the app with a "
        "bearer token in the URL fragment. On failure, redirects to `/login?error=…`."
    ),
    dependencies=[Depends(_oauth_callback_limit)],
    **_CALLBACK_REDIRECT,
)
async def google_callback(request: Request, db: Session = Depends(get_db)):
    client = _configured_client("google")
    try:
        token = await client.authorize_access_token(request)
    except Exception:
        logger.exception("Google OAuth callback failed")
        return _login_error("google_auth_failed")

    userinfo = token.get("userinfo", {})
    email = userinfo.get("email")
    if not email:
        return _login_error("no_email")

    oauth_id = _provider_id(userinfo.get("sub", ""))
    if not oauth_id:
        logger.warning("OAuth sign-in refused: no account id", extra={"provider": "google"})
        return _login_error("google_auth_failed")

    user = _find_or_create_oauth_user(
        db,
        provider="google",
        oauth_id=oauth_id,
        email=email.lower(),
        name=userinfo.get("name"),
        email_verified=bool(userinfo.get("email_verified")),
    )
    return _complete_oauth_login(user, "google")


# ── GitHub ────────────────────────────────────────────────

@router.get(
    "/github",
    summary="Initiate GitHub OAuth login",
    description="Redirects to GitHub's consent screen. The browser returns to `/github/callback`.",
    dependencies=[Depends(_oauth_initiate_limit)],
    **_LOGIN_REDIRECT,
)
async def github_login(request: Request):
    return await _start_login(request, "github")


@router.get(
    "/github/callback",
    summary="Handle GitHub OAuth callback",
    description=(
        "Exchanges GitHub's authorization code for a token, fetches the "
        "user's primary verified email (from `/user/emails` when the profile "
        "omits it), and redirects into the app with a bearer token or an error."
    ),
    dependencies=[Depends(_oauth_callback_limit)],
    **_CALLBACK_REDIRECT,
)
async def github_callback(request: Request, db: Session = Depends(get_db)):
    client = _configured_client("github")
    try:
        token = await client.authorize_access_token(request)
    except Exception:
        logger.exception("GitHub OAuth callback failed")
        return _login_error("github_auth_failed")

    try:
        resp = await client.get("user", token=token)
        profile = resp.json()
    except Exception:
        logger.exception("GitHub user profile fetch failed")
        return _login_error("github_auth_failed")

    email = profile.get("email")
    if not email:
        try:
            emails_resp = await client.get("user/emails", token=token)
            for e in emails_resp.json():
                if e.get("primary") and e.get("verified"):
                    email = e["email"]
                    break
        except Exception:
            logger.exception("GitHub user emails fetch failed")
            return _login_error("github_auth_failed")

    if not email:
        return _login_error("no_email")

    oauth_id = _provider_id(profile.get("id", ""))
    if not oauth_id:
        logger.warning("OAuth sign-in refused: no account id", extra={"provider": "github"})
        return _login_error("github_auth_failed")

    user = _find_or_create_oauth_user(
        db,
        provider="github",
        oauth_id=oauth_id,
        email=email.lower(),
        name=profile.get("name") or profile.get("login"),
        email_verified=True,
    )
    return _complete_oauth_login(user, "github")


# ── Microsoft ─────────────────────────────────────────────

@router.get(
    "/microsoft",
    summary="Initiate Microsoft OAuth login",
    description=(
        "Redirects to Microsoft's consent screen. The browser returns to "
        "`/microsoft/callback`."
    ),
    dependencies=[Depends(_oauth_initiate_limit)],
    **_LOGIN_REDIRECT,
)
async def microsoft_login(request: Request):
    return await _start_login(request, "microsoft")


@router.get(
    "/microsoft/callback",
    summary="Handle Microsoft OAuth callback",
    description=(
        "Exchanges Microsoft's authorization code for a token, reads the "
        "email from `userinfo` (falling back to `preferred_username`), and "
        "redirects into the app with a bearer token or an error."
    ),
    dependencies=[Depends(_oauth_callback_limit)],
    **_CALLBACK_REDIRECT,
)
async def microsoft_callback(request: Request, db: Session = Depends(get_db)):
    client = _configured_client("microsoft")
    try:
        token = await client.authorize_access_token(request)
    except Exception:
        logger.exception("Microsoft OAuth callback failed")
        return _login_error("microsoft_auth_failed")

    userinfo = token.get("userinfo", {})
    email = userinfo.get("email") or userinfo.get("preferred_username")
    if not email:
        return _login_error("no_email")

    oauth_id = _provider_id(userinfo.get("sub", ""))
    if not oauth_id:
        logger.warning("OAuth sign-in refused: no account id", extra={"provider": "microsoft"})
        return _login_error("microsoft_auth_failed")

    user = _find_or_create_oauth_user(
        db,
        provider="microsoft",
        oauth_id=oauth_id,
        email=email.lower(),
        name=userinfo.get("name"),
        email_verified=bool(userinfo.get("email_verified")),
    )
    return _complete_oauth_login(user, "microsoft")
