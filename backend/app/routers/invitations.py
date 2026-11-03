"""Owner-created, email-bound invitations. Delivery is an explicit copy/share action."""

import hashlib
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_business, get_current_user, require_owner
from app.core.params import RowId
from app.core.rate_limit import RateLimit
from app.models.business import Business
from app.models.business_membership import BusinessMembership, MembershipRole
from app.models.mixins import utcnow
from app.models.practice import BusinessInvitation
from app.models.user import User
from app.schemas.practice import InviteCreate, InviteToken, MemberRoleChange
from app.services.register_import import aware

router = APIRouter(prefix="/invitations", tags=["client invitations"])


def out(invite):
    return {
        "id": invite.id,
        "email": invite.email,
        "role": invite.role,
        "expires_at": invite.expires_at,
        "accepted_at": invite.accepted_at,
        "revoked_at": invite.revoked_at,
    }


def by_token(db, token):
    invite = db.scalar(
        select(BusinessInvitation)
        .where(
            BusinessInvitation.token_hash == hashlib.sha256(token.encode()).hexdigest(),
            BusinessInvitation.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if (
        invite is None
        or invite.revoked_at
        or invite.accepted_at
        or aware(invite.expires_at) <= utcnow()
    ):
        raise HTTPException(
            404,
            "This invitation is invalid, expired or already used. Ask the owner for a new link.",
        )
    business = db.get(Business, invite.business_id)
    if business is None or not business.is_reachable:
        raise HTTPException(
            404, "This invitation is no longer available. Contact the business owner."
        )
    # A former owner cannot leave durable grants behind after losing authority.
    creator = db.get(User, invite.created_by)
    member = db.scalar(
        select(BusinessMembership).where(
            BusinessMembership.business_id == business.id,
            BusinessMembership.user_id == invite.created_by,
            BusinessMembership.deleted_at.is_(None),
        )
    )
    owns = (
        creator
        and creator.is_active
        and (
            (creator.business_id == business.id and creator.role.value == "owner")
            or (member and member.role == MembershipRole.OWNER)
        )
    )
    if not owns:
        raise HTTPException(
            404, "This invitation is no longer available. Ask a current owner for a new link."
        )
    return invite, business


@router.get(
    "",
    summary="List invitations for the selected business",
    dependencies=[Depends(require_owner), Depends(RateLimit("invitation_list", "60/minute"))],
)
def list_invitations(
    db: Session = Depends(get_db), business: Business = Depends(get_current_business)
) -> dict:
    return {
        "items": [
            out(r)
            for r in db.scalars(
                select(BusinessInvitation)
                .where(
                    BusinessInvitation.business_id == business.id,
                    BusinessInvitation.deleted_at.is_(None),
                )
                .order_by(BusinessInvitation.id.desc())
                .limit(100)
            )
        ]
    }


@router.post(
    "",
    summary="Create an expiring client invitation link",
    status_code=201,
    dependencies=[Depends(require_owner), Depends(RateLimit("invitation_create", "20/day"))],
)
def create_invitation(
    payload: InviteCreate,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
    user: User = Depends(get_current_user),
) -> dict:
    email = str(payload.email).lower()
    if email == user.email.lower():
        raise HTTPException(
            422, "You already have access. Invite the accountant or client using their own email."
        )
    db.scalar(select(Business.id).where(Business.id == business.id).with_for_update())
    db.execute(
        update(BusinessInvitation)
        .where(
            BusinessInvitation.business_id == business.id,
            BusinessInvitation.email == email,
            BusinessInvitation.accepted_at.is_(None),
            BusinessInvitation.revoked_at.is_(None),
            BusinessInvitation.deleted_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    token = secrets.token_urlsafe(32)
    invite = BusinessInvitation(
        business_id=business.id,
        created_by=user.id,
        email=email,
        role=payload.role,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=utcnow() + timedelta(days=7),
    )
    db.add(invite)
    db.commit()
    return {**out(invite), "token": token}


@router.post(
    "/inspect",
    summary="Read a valid invitation without granting access",
    dependencies=[Depends(RateLimit("invitation_inspect", "30/minute", by="ip"))],
)
def inspect_invitation(payload: InviteToken, db: Session = Depends(get_db)) -> dict:
    invite, business = by_token(db, payload.token)
    return {
        "business_name": business.trade_name or business.legal_name,
        "email": invite.email,
        "role": invite.role,
        "expires_at": invite.expires_at,
    }


@router.post(
    "/accept",
    summary="Accept an invitation addressed to this login",
    dependencies=[Depends(RateLimit("invitation_accept", "20/hour"))],
)
def accept_invitation(
    payload: InviteToken, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    invite, business = by_token(db, payload.token)
    if user.email.lower() != invite.email.lower():
        raise HTTPException(403, "Sign in using the email address this invitation was sent to.")
    if user.business_id == business.id:
        raise HTTPException(409, "This is already your own business. No invitation is needed.")
    membership = db.scalar(
        select(BusinessMembership).where(
            BusinessMembership.user_id == user.id,
            BusinessMembership.business_id == business.id,
            BusinessMembership.deleted_at.is_(None),
        )
    )
    # An old invitation must not overwrite a subsequently restricted role.
    if membership is not None:
        raise HTTPException(
            409, "You already have access. Ask the owner to change your role in Client access."
        )
    db.add(
        BusinessMembership(
            user_id=user.id, business_id=business.id, role=MembershipRole(invite.role)
        )
    )
    invite.accepted_at = utcnow()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Access was already granted. Refresh your client list.") from None
    return {"business_id": business.id, "role": invite.role}


@router.delete(
    "/{invitation_id}",
    summary="Revoke a pending invitation",
    status_code=204,
    dependencies=[Depends(require_owner), Depends(RateLimit("invitation_revoke", "60/minute"))],
)
def revoke_invitation(
    invitation_id: RowId,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> None:
    invite = db.scalar(
        select(BusinessInvitation)
        .where(
            BusinessInvitation.id == invitation_id,
            BusinessInvitation.business_id == business.id,
            BusinessInvitation.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if invite is None:
        raise HTTPException(404, "Invitation not found for this business.")
    if invite.accepted_at:
        raise HTTPException(
            409, "This invitation was accepted. Revoke the member’s access instead."
        )
    invite.revoked_at = utcnow()
    db.commit()


@router.patch(
    "/members/{membership_id}",
    summary="Change a linked accountant or viewer role",
    dependencies=[Depends(require_owner), Depends(RateLimit("member_role_change", "30/minute"))],
)
def change_member_role(
    membership_id: RowId,
    payload: MemberRoleChange,
    db: Session = Depends(get_db),
    business: Business = Depends(get_current_business),
) -> dict:
    member = db.scalar(
        select(BusinessMembership)
        .where(
            BusinessMembership.id == membership_id,
            BusinessMembership.business_id == business.id,
            BusinessMembership.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if member is None:
        raise HTTPException(404, "Member not found for this business.")
    if member.role == MembershipRole.OWNER:
        raise HTTPException(409, "Owner access cannot be changed through this screen.")
    member.role = MembershipRole(payload.role)
    db.commit()
    return {"id": member.id, "role": member.role.value}
