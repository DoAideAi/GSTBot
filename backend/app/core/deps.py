"""Shared FastAPI dependencies: the current user, the tenant they act for, and
what they are allowed to do to it."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.params import MAX_ID, MIN_ID
from app.core.security import decode_access_token
from app.models.business import Business
from app.models.business_membership import BusinessMembership
from app.models.subscription import Subscription
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")

_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

# The three roles, ordered. Everything a higher role may do a lower one may
# not, which is the only relation between them this product needs — there are
# no orthogonal permissions to model, and a grid of them would be a lie about
# how the roles are actually used.
_RANK: dict[UserRole, int] = {
    UserRole.VIEWER: 0,
    UserRole.ACCOUNTANT: 1,
    UserRole.OWNER: 2,
}


@dataclass(frozen=True)
class ActiveTenant:
    """The business a request acts for, and the role it acts with.

    The two are resolved together because they are the same lookup. A request
    acting as its own tenant carries ``User.role``; one acting as a *linked*
    business through ``X-Business-Id`` carries that membership's role instead,
    and reading ``User.role`` in that case would apply the caller's authority
    on their own books to somebody else's.
    """

    business: Business
    role: UserRole


def get_current_user(
    request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """Resolve the authenticated user from the bearer token."""
    subject = decode_access_token(token)
    if subject is None:
        raise _credentials_exc
    try:
        user_id = int(subject)
    except (TypeError, ValueError) as exc:
        raise _credentials_exc from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _credentials_exc
    # Stamped for the access line, which is the only audit trail this product
    # keeps: no table records who filed a return or acknowledged an alert, so
    # a log line that says ``POST /filing/gstr3b/filed 201`` and nothing else
    # is a record that *something* happened to *somebody's* books. Stamped
    # here, before the tenant is resolved, so a refused ``X-Business-Id``
    # still names the login that tried it.
    request.state.user_id = user.id
    return user


def get_active_tenant(
    request: Request,
    x_business_id: int | None = Header(default=None, alias="X-Business-Id"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ActiveTenant:
    """The tenant the request acts for, and the role it acts with.

    Every business-scoped route reaches this — through
    :func:`get_current_business` for the tenant, through :class:`RequireRole`
    for the authority — so the tenant a request may touch is resolved in
    exactly one place. A route that forgets it has no ``business_id`` to filter
    on and fails loudly, instead of quietly reading across tenants.

    Defaults to the caller's own tenant, exactly as it always has — a request
    that never sends ``X-Business-Id`` is unaffected by any of what follows.
    A header naming a *different* business is only honoured when a live
    :class:`~app.models.business_membership.BusinessMembership` links this
    user to it; see ``POST /businesses/mine/link`` for how one gets created.
    Anything else — an id nobody granted, a stale membership, a business that
    has since gone inactive — is a 403 rather than a silent fall-back to the
    caller's own tenant, because a client that believes it is acting for one
    business must never be quietly handed another's data instead.

    FastAPI caches a dependency per request by the callable that declares it,
    so a route depending on both ``get_current_business`` and a
    ``RequireRole`` resolves this once and runs the membership query once.
    That is why the role is returned from here rather than from a second
    dependency that would repeat the lookup.
    """
    if x_business_id is not None and not (MIN_ID <= x_business_id <= MAX_ID):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"X-Business-Id must be between {MIN_ID} and {MAX_ID}.",
        )

    business_id = current_user.business_id
    # Acting as one's own tenant: the role on the login is the role, and there
    # is no membership row to read — the caller's own business is not linked to
    # them, it *is* them.
    role = current_user.role
    if x_business_id is not None and x_business_id != current_user.business_id:
        member = db.scalar(
            select(BusinessMembership).where(
                BusinessMembership.user_id == current_user.id,
                BusinessMembership.business_id == x_business_id,
                BusinessMembership.deleted_at.is_(None),
            )
        )
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to that business",
            )
        business_id = x_business_id
        # MembershipRole and UserRole carry the same three values on purpose
        # (see ``link_business``), so this is a rename rather than a mapping.
        role = UserRole(member.role.value)

    business = db.get(Business, business_id)
    if business is None or not business.is_reachable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This business has been deactivated. Contact support to reactivate it.",
        )
    # The business *acted for* and the role acted *with*, not the login's own.
    # A linked accountant recording a client's filing is the case the access
    # line exists to distinguish from the owner doing it, and once the
    # membership is unlinked nothing in the database can tell the two apart.
    request.state.business_id = business.id
    request.state.role = role.value
    return ActiveTenant(business=business, role=role)


def get_current_business(
    tenant: ActiveTenant = Depends(get_active_tenant),
) -> Business:
    """The tenant the request acts for.

    Kept as the name every business-scoped route depends on: what a route
    needs is almost always the business alone, and threading an
    :class:`ActiveTenant` through several dozen signatures to reach
    ``.business`` on each would obscure that. The role travels beside it and
    is read by :class:`RequireRole`, which is declared once per route rather
    than unpacked in its body — an authority check written inside a handler is
    one a new handler can be written without.
    """
    return tenant.business


class RequireRole:
    """Refuse the request unless the caller acts with at least *minimum*.

    A dependency rather than a check inside each handler, for the same reason
    ``get_current_business`` is one: a rule enforced in forty function bodies
    is a rule the forty-first can be written without, and
    ``tests/test_rbac.py`` can sweep a dependency off the assembled route
    table but cannot sweep an ``if`` statement.

    **403, not 404.** Cross-tenant reads answer 404 precisely so a refusal
    never confirms that somebody else's row exists. This refusal confirms
    nothing of the sort: the caller is a member of this business and knows it
    exists, and the answer does not depend on the id in the path — a viewer
    gets the same 403 whether the invoice they tried to patch is theirs, is
    another tenant's, or does not exist at all. What it tells them is the one
    thing they need in order to act on it: who to ask.
    """

    def __init__(self, minimum: UserRole) -> None:
        self.minimum = minimum

    def __call__(self, tenant: ActiveTenant = Depends(get_active_tenant)) -> ActiveTenant:
        if _RANK[tenant.role] < _RANK[self.minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                # Names the role held rather than the role required, because
                # the reader of this sentence cannot change what a route
                # demands and can ask somebody who holds more. A viewer who is
                # told "accountant required" still has to work out that they
                # are not one.
                detail=(
                    f"Your role on this business is '{tenant.role.value}', which is "
                    "read-only. Ask an owner or an accountant to make this change."
                ),
            )
        return tenant

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"RequireRole({self.minimum.value})"


# The one authority this product distinguishes: may this request change the
# tenant's books at all?
#
# Owner and accountant are deliberately not separated here. The difference
# between them is who pays the bill, not what they may file — an outside CA
# doing a client's GST work needs every write this API has, and a product that
# refused them one would be routed around by sharing the owner's password,
# which is strictly worse than granting the role. Viewer is the role that
# means something: the person who is shown the books and does not touch them.
require_writer = RequireRole(UserRole.ACCOUNTANT)

# Subscription billing operations — create-order, verify-payment, cancel —
# change what the business pays, not what it files. An accountant linked to
# manage invoices should not be able to downgrade a client's paid plan or
# commit the business to a new one. The comment above ``require_writer``
# says the owner/accountant line is "who pays the bill"; these endpoints are
# exactly the bill.
require_owner = RequireRole(UserRole.OWNER)

def require_paid_tier(
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
) -> Subscription:
    """Refuse unless the business has an active paid subscription.

    Returns the subscription so a handler can read the tier without a second
    query. 403 rather than 402 — HTTP 402 is reserved and no browser handles
    it, and the detail tells the caller what to do about it.
    """
    sub = db.scalar(select(Subscription).where(Subscription.business_id == business.id))
    # `is_paid` rather than the tier and status alone: a paid period that has
    # run out is not paid for, whatever the row's status still says.
    if sub is None or not sub.is_paid():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This feature requires a paid subscription. "
                "Visit /pricing to upgrade."
            ),
        )
    return sub


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Refuse unless the signed-in user is a site operator (``ADMIN_EMAILS``).

    Per-business roles do not answer this: everyone who registers owns their
    own business, so an owner is not an operator. 403, not 404 — the route is
    documented and its existence is not a secret, only its contents are.
    """
    admins = {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}
    if (user.email or "").lower() not in admins:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only site administrators can read this.",
        )
    return user


__all__ = [
    "ActiveTenant",
    "RequireRole",
    "get_active_tenant",
    "get_current_business",
    "get_current_user",
    "oauth2_scheme",
    "require_admin",
    "require_owner",
    "require_paid_tier",
    "require_writer",
]
