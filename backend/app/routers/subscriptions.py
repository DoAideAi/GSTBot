"""Subscription management, pricing, and Razorpay payment flow."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_business, get_current_user, require_owner
from app.core.rate_limit import RateLimit, client_ip
from app.models.business import Business
from app.models.subscription import (
    Subscription,
    SubscriptionStatus,
    SubscriptionTier,
    period_length,
)
from app.models.subscription_payment import SubscriptionPayment
from app.models.user import User
from app.schemas.subscription import (
    CreateOrderRequest,
    CreateOrderResponse,
    PricingResponse,
    SubscriptionOut,
    TierFeatures,
    UsageItem,
    UsageSummaryResponse,
    VerifyPaymentRequest,
)
from app.services import gst_calendar, invoice_service, razorpay_client
from app.services import usage as usage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])

_pricing_limit = RateLimit("pricing", "60/minute", by="ip")
_order_limit = RateLimit("create_order", "10/minute")
_verify_limit = RateLimit("verify_payment", "10/minute")
_cancel_limit = RateLimit("cancel_subscription", "10/minute")
_usage_limit = RateLimit("usage", "60/minute")
_webhook_limit = RateLimit("razorpay_webhook", "30/minute", by="ip")


@router.get(
    "/pricing",
    response_model=PricingResponse,
    summary="Available subscription tiers and pricing",
    description=(
        "Public — no sign-in required. Returns every tier's name, monthly and "
        "annual price in paise, invoice limit, and feature flags, plus the "
        "Razorpay key id the frontend needs to open the checkout modal."
    ),
    dependencies=[Depends(_pricing_limit)],
)
def pricing() -> PricingResponse:
    tiers = {
        tier.value: TierFeatures(**info)
        for tier, info in razorpay_client.TIER_PRICING.items()
    }
    return PricingResponse(
        tiers=tiers,
        razorpay_key_id=settings.razorpay_key_id,
    )


@router.get(
    "/current",
    response_model=SubscriptionOut | None,
    summary="The current business's subscription",
    description=(
        "Returns the active subscription for the business the request acts for, "
        "or null when the business is on the free tier and has never subscribed. "
        "The response synthesises an `effective_status` of `expired` when the row "
        "says active but the period has lapsed, so the frontend never has to "
        "compare dates."
    ),
    dependencies=[Depends(_usage_limit)],
)
def current_subscription(
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
) -> SubscriptionOut | None:
    sub = usage_service.get_subscription(db, business.id)
    if sub is None:
        return None
    return SubscriptionOut.model_validate(sub)


@router.post(
    "/create-order",
    response_model=CreateOrderResponse,
    summary="Create a Razorpay order for a tier upgrade",
    description=(
        "Owners only. Creates a Razorpay order for the requested tier and billing "
        "cycle (monthly or annual). The order id and the Razorpay key id go "
        "straight into the Razorpay checkout modal on the frontend; the "
        "receipt ties the order to this business and tier so `verify-payment` "
        "can refuse a tampered request."
    ),
    responses={
        400: {"description": "The free tier was requested; there is nothing to pay for."},
        502: {"description": "Razorpay did not create the order. Safe to retry."},
        503: {"description": "Payment processing is not configured on this server."},
    },
    dependencies=[Depends(require_owner), Depends(_order_limit)],
)
def create_order(
    payload: CreateOrderRequest,
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
) -> CreateOrderResponse:
    if payload.tier == SubscriptionTier.FREE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The Free plan costs nothing, so there is nothing to pay for. "
                "Choose SMB or CA to upgrade."
            ),
        )
    if not razorpay_client.is_configured():
        # A customer trying to pay and being turned away: the one 503 here
        # that is about money, so it is written down rather than left to the
        # access log's status code.
        logger.error(
            "Checkout refused: Razorpay is not configured",
            extra={"business_id": business.id, "tier": payload.tier.value},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Payments are not available right now, so the plan cannot be "
                "changed. Try again later, or contact support."
            ),
        )

    pricing = razorpay_client.TIER_PRICING[payload.tier]
    amount = (
        pricing["price_annual"]
        if payload.billing == "annual"
        else pricing["price_monthly"]
    )
    order = razorpay_client.create_order(
        amount_paise=amount,
        receipt=razorpay_client.order_receipt(business.id, payload.tier),
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Could not create payment order. Try again, or contact support "
                "if this persists."
            ),
        )
    # The first half of every dispute trail: "I was charged and have no plan"
    # starts from an order id, and nothing tied one to a business here.
    logger.info(
        "Payment order created",
        extra={
            "business_id": business.id,
            "razorpay_order_id": order["id"],
            "amount_paise": order["amount"],
            "tier": payload.tier.value,
            "billing": payload.billing,
        },
    )
    return CreateOrderResponse(
        order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        razorpay_key_id=settings.razorpay_key_id,
        tier=payload.tier,
    )


@router.post(
    "/verify-payment",
    response_model=SubscriptionOut,
    summary="Verify Razorpay payment and activate subscription",
    description=(
        "Owners only. Called by the frontend after the Razorpay checkout "
        "modal closes with a payment. Verifies the HMAC signature, confirms "
        "the order was created for this business and tier at the tier's price, "
        "and activates (or renews) the subscription. Idempotent: re-submitting "
        "the same payment id returns the existing subscription without extending "
        "it, so a network retry cannot buy a free period."
    ),
    responses={
        400: {
            "description": (
                "The signature does not verify, or the order was not created for "
                "this business, tier and price, or is not fully paid."
            )
        },
        409: {
            "description": (
                "The payment is already applied to another business, or this "
                "subscription has ended since the order was created."
            )
        },
        502: {"description": "Razorpay could not be asked about the order. Safe to retry."},
    },
    dependencies=[Depends(require_owner), Depends(_verify_limit)],
)
def verify_payment(
    payload: VerifyPaymentRequest,
    business: Business = Depends(get_current_business),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    if not razorpay_client.verify_payment_signature(
        payload.razorpay_order_id,
        payload.razorpay_payment_id,
        payload.razorpay_signature,
    ):
        logger.warning(
            "Payment signature verification failed",
            extra={
                "business_id": business.id,
                "user_id": current_user.id,
                "razorpay_order_id": payload.razorpay_order_id,
                "tier": payload.tier.value,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Payment verification failed. Contact support if you were charged, "
                "or try the payment again."
            ),
        )

    # The signature covers "order_id|payment_id" and nothing else, so on its own
    # it proves only that *some* order was paid. The tier came from the request
    # body and the business from the session, and neither was checked against
    # the order: pay for the cheapest paid tier and verify as the dearest, or
    # submit another business's paid order, and either became an active
    # subscription. The order says what was bought and for whom — its receipt
    # was written by create_order — so it is what decides.
    order = _require_order_matches(payload, business)
    holder = db.scalar(
        select(Subscription).where(
            Subscription.razorpay_subscription_id == payload.razorpay_payment_id,
            Subscription.business_id != business.id,
        )
    )
    if holder is not None:
        logger.warning(
            "Payment already redeemed by another business",
            extra={
                "business_id": business.id,
                "holder_business_id": holder.business_id,
                "razorpay_payment_id": payload.razorpay_payment_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This payment has already been applied to another account.",
        )

    _serialise_billing(db, business.id)
    sub = usage_service.get_subscription(db, business.id)
    applied = _applied_payment(db, payload.razorpay_payment_id)
    if applied is not None or (
        sub is not None and sub.razorpay_subscription_id == payload.razorpay_payment_id
    ):
        # Already applied: answered as it stands, never applied again. The row
        # alone could only recognise its *latest* payment, so re-verifying an
        # older one — genuine, paid, correctly signed — bought another period
        # each time. The second test is for the payment on a row from before
        # the ledger existed.
        if applied is not None and applied.business_id != business.id:
            logger.warning(
                "Payment already redeemed by another business",
                extra={
                    "business_id": business.id,
                    "holder_business_id": applied.business_id,
                    "razorpay_payment_id": payload.razorpay_payment_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This payment has already been applied to another account.",
            )
        if sub is not None:
            return SubscriptionOut.model_validate(sub)

    period_end = _period_end_for(order, payload, sub)
    renewal = sub is not None
    if sub is None:
        sub = Subscription(
            business_id=business.id,
            tier=payload.tier,
            status=SubscriptionStatus.ACTIVE,
            razorpay_subscription_id=payload.razorpay_payment_id,
            current_period_end=period_end,
        )
        db.add(sub)
    else:
        if sub.status in (
            SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED
        ) and not _order_postdates(order, sub, payload.razorpay_payment_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Subscription is {sub.status.value}. "
                    "Create a new order instead of verifying a payment against it."
                ),
            )
        sub.current_period_end = period_end
        sub.tier = payload.tier
        sub.status = SubscriptionStatus.ACTIVE
        sub.razorpay_subscription_id = payload.razorpay_payment_id
    db.add(
        SubscriptionPayment(
            business_id=business.id,
            razorpay_payment_id=payload.razorpay_payment_id,
            razorpay_order_id=payload.razorpay_order_id,
            tier=payload.tier.value,
            amount_paise=order.get("amount") or 0,
            period_end=period_end,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # Two verifies of one payment raced past the check above; the ledger's
        # unique key let one through. This one applies nothing.
        db.rollback()
        winner = _applied_payment(db, payload.razorpay_payment_id)
        if winner is None or winner.business_id != business.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This payment has already been applied to another account.",
            ) from None
        sub = usage_service.get_subscription(db, business.id)
        return SubscriptionOut.model_validate(sub)
    db.refresh(sub)

    # Enough to answer a dispute from the log alone: which payment bought what,
    # for whom, at what price, until when.
    logger.info(
        "Subscription activated",
        extra={
            "business_id": business.id,
            "user_id": current_user.id,
            "tier": payload.tier.value,
            "razorpay_payment_id": payload.razorpay_payment_id,
            "razorpay_order_id": payload.razorpay_order_id,
            "amount_paise": order.get("amount"),
            "period_end": period_end.isoformat(),
            "renewal": renewal,
        },
    )
    return SubscriptionOut.model_validate(sub)


# The second key of the per-business billing lock. Uploads hold (business, 0)
# and reconciliation (business, YYYYMM); no period is 1.
_BILLING_LOCK_KEY = 1


def _serialise_billing(db: Session, business_id: int) -> None:
    """Apply one payment per business at a time, until its commit.

    Everything verify-payment decides is read off the business's subscription
    before it writes: whether there is one to renew, and where the period it
    buys starts. Two payments verified at once — two tabs, or the owner and
    their CA each completing a checkout — both read the same answer. With no
    subscription yet both inserted one, the unique ``business_id`` refused the
    second, and that payment was told it belonged "to another account" and
    recorded nowhere. With one, both extended from the same period end and the
    later commit overwrote the earlier: two periods paid for, one granted.

    Taken after the order is fetched from Razorpay, so the lock is never held
    across a network call. SQLite has no concurrent writers to keep apart.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(select(func.pg_advisory_xact_lock(business_id, _BILLING_LOCK_KEY)))


def _applied_payment(db: Session, payment_id: str) -> SubscriptionPayment | None:
    return db.scalar(
        select(SubscriptionPayment).where(
            SubscriptionPayment.razorpay_payment_id == payment_id
        )
    )


def _period_end_for(
    order: dict, payload: VerifyPaymentRequest, sub: Subscription | None
) -> datetime:
    """When the period this payment buys ends.

    Monthly or annual is read off what was actually paid — the order's amount
    against the tier's prices, which `_require_order_matches` has already held
    to one of the two. A renewal of the same tier while the current period is
    still running starts where it ends, so paying a few days early does not
    forfeit them; anything else starts now.
    """
    pricing = razorpay_client.TIER_PRICING[payload.tier]
    billing = "annual" if order.get("amount") == pricing.get("price_annual") else "monthly"
    now = datetime.now(UTC)
    start = now
    if sub is not None and sub.tier == payload.tier and sub.is_paid(now) and sub.current_period_end:
        end = sub.current_period_end
        start = end.replace(tzinfo=UTC) if end.tzinfo is None else end
    return start + period_length(billing)


def _order_postdates(order: dict, sub: Subscription, payment_id: str) -> bool:
    """Whether a paid order is a fresh purchase rather than one the ended
    subscription already consumed.

    The refusal for cancelled/expired rows exists to stop a stale payment
    reviving a subscription the business ended — but it refused every payment,
    so a business that cancelled could never pay again, and the 409 told it to
    create a new order, which was refused the same way. A row's ``updated_at``
    is when it was cancelled or expired; an order Razorpay created after that,
    paid by a payment other than the one already on the row, is a new purchase.
    An order without ``created_at`` cannot show that, and stays refused.
    """
    if payment_id == sub.razorpay_subscription_id:
        return False
    created = order.get("created_at")
    if not isinstance(created, int | float) or sub.updated_at is None:
        return False
    ended = sub.updated_at
    if ended.tzinfo is None:  # SQLite hands back naive UTC
        ended = ended.replace(tzinfo=UTC)
    try:
        ordered = datetime.fromtimestamp(created, tz=UTC)
    except (OverflowError, OSError, ValueError):
        # NaN, or a timestamp outside what a datetime holds: not a date the
        # order can be shown to postdate anything by, so it stays refused.
        return False
    # >= rather than >: a cancel-then-resubscribe in the same wall-clock
    # second is a fresh purchase, and the payment_id check above already
    # prevents the old payment from being replayed.
    return ordered >= ended


def _require_order_matches(payload: VerifyPaymentRequest, business: Business) -> dict:
    """Refuse unless the order was created for this business and tier, at the
    tier's price, and has been paid in full. Returns the order."""
    order = razorpay_client.fetch_order(payload.razorpay_order_id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Could not confirm the payment with the payment provider. Try again "
                "in a moment — if you were charged, it will not be lost."
            ),
        )
    pricing = razorpay_client.TIER_PRICING[payload.tier]
    valid_amounts = {pricing["price_monthly"], pricing.get("price_annual", 0)} - {0}
    # Read through ``paise``: a string or a list here is a malformed order, to
    # be refused like any other mismatch rather than compared and 500ed on.
    order_amount = razorpay_client.paise(order.get("amount"))
    amount_paid = razorpay_client.paise(order.get("amount_paid"))
    problems = []
    if order.get("receipt") != razorpay_client.order_receipt(business.id, payload.tier):
        problems.append("receipt")
    if order_amount not in valid_amounts:
        problems.append("amount")
    if (
        order.get("status") != "paid"
        or amount_paid is None
        or order_amount is None
        or amount_paid < order_amount
    ):
        problems.append("status")
    if problems:
        logger.warning(
            "Payment verification refused: order does not match the request",
            extra={
                "business_id": business.id,
                "razorpay_order_id": payload.razorpay_order_id,
                "tier": payload.tier.value,
                "mismatch": problems,
                "order_receipt": order.get("receipt"),
                "order_status": order.get("status"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This payment does not match the plan it is being applied to. "
                "Contact support if you were charged."
            ),
        )
    return order


@router.post(
    "/cancel",
    response_model=SubscriptionOut,
    summary="Cancel the current subscription (reverts to free)",
    description=(
        "Owners only. Marks the subscription as cancelled and reverts the "
        "tier to free. If the subscription id is a Razorpay-managed one "
        "(`sub_…`), the cancellation is also forwarded to Razorpay; a "
        "one-time checkout (`pay_…`) has nothing to cancel at the provider. "
        "The remaining paid period is forfeit — there is no proration."
    ),
    responses={
        400: {"description": "There is no paid subscription to cancel."},
        409: {"description": "The subscription is already cancelled or expired."},
        502: {"description": "Razorpay did not cancel the subscription. Safe to retry."},
    },
    dependencies=[Depends(require_owner), Depends(_cancel_limit)],
)
def cancel_subscription(
    business: Business = Depends(get_current_business),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    sub = usage_service.get_subscription(db, business.id)
    if sub is None or sub.tier == SubscriptionTier.FREE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No active paid subscription to cancel: this business is "
                "already on the Free plan."
            ),
        )
    if sub.status in (SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This subscription is already {sub.status.value}, so there is "
                "nothing left to cancel."
            ),
        )
    # A paid period that has run out is not a paid subscription. The DB still
    # says ACTIVE/PRO because nothing wrote EXPIRED (one-time orders produce no
    # Razorpay webhook to do it), and the schema validator synthesises "expired"
    # for the API response. Cancelling it would move the row from ACTIVE to
    # CANCELLED, making resubscription harder (_order_postdates) for something
    # the business no longer has.
    #
    # Narrowed to ACTIVE: a PAST_DUE subscription whose period also lapsed is a
    # Razorpay-managed one with a billing relationship the business wants to end.
    if sub.status == SubscriptionStatus.ACTIVE and sub.lapsed():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No active paid subscription to cancel: this business is "
                "already on the Free plan."
            ),
        )
    old_tier = sub.tier
    # Only a Razorpay *subscription* has anything to cancel at the provider.
    # Checkout is a one-time order, and ``verify_payment`` stores the payment id
    # (``pay_…``) in this column — calling /subscriptions/pay_…/cancel was
    # refused every time, so every paying business that tried to cancel got a
    # 502 "try again" that no retry could ever get past.
    provider_id = sub.razorpay_subscription_id or ""
    if provider_id.startswith("sub_") and razorpay_client.is_configured():
        result = razorpay_client.cancel_subscription(provider_id)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Could not cancel subscription with payment provider. Try again, "
                    "or contact support if this persists."
                ),
            )
    # Everything above was read with no lock, and verify-payment may have
    # applied a renewal since: a new payment, a later period end. Cancelling
    # over it wrote FREE across a period the user had just paid for. Take the
    # same lock verify holds (after the provider call, so it is never held
    # across one), re-read, and refuse if the subscription is no longer the
    # one the user asked to cancel.
    seen = (provider_id, sub.current_period_end)
    _serialise_billing(db, business.id)
    db.refresh(sub)
    if (sub.razorpay_subscription_id or "", sub.current_period_end) != seen:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A payment was applied to this subscription while it was being "
                "cancelled. Review the renewed plan, then cancel again if you "
                "still want to."
            ),
        )
    sub.tier = SubscriptionTier.FREE
    sub.status = SubscriptionStatus.CANCELLED
    db.commit()
    db.refresh(sub)
    logger.info(
        "Subscription cancelled",
        extra={
            "business_id": business.id,
            "user_id": current_user.id,
            "old_tier": old_tier.value,
        },
    )
    return SubscriptionOut.model_validate(sub)


@router.get(
    "/usage",
    response_model=UsageSummaryResponse,
    summary="API usage for the current month",
    description=(
        "Invoice uploads, API calls, and advisor queries consumed this period, "
        "with each item's limit under the current tier. `period` defaults to the "
        "current calendar month (`MMYYYY`); pass an earlier one to review history."
    ),
    dependencies=[Depends(_usage_limit)],
)
def usage_summary(
    period: str | None = Query(default=None, pattern=gst_calendar.PERIOD_PATTERN),
    business: Business = Depends(get_current_business),
    db: Session = Depends(get_db),
) -> UsageSummaryResponse:
    tier = usage_service.get_tier(db, business.id)
    actual_period = period or usage_service.current_period()
    rows = usage_service.get_usage_summary(db, business.id, actual_period)
    # The one allowance that is enforced (check_plan_limit refuses an upload
    # past it), counted the way the dashboard counts it. Nothing wrote a usage
    # row for it, so this page — linked from the nav — said "No API calls
    # recorded this month" to a business that had uploaded all month.
    invoices = UsageItem(
        endpoint="invoice_uploads",
        call_count=invoice_service.monthly_usage(db, business.id, actual_period),
        limit=invoice_service.plan_limit(business),
        period=actual_period,
    )
    return UsageSummaryResponse(
        tier=tier,
        period=actual_period,
        usage=[invoices, *(UsageItem(**r) for r in rows)],
    )


def _dig(document: dict, *keys: str) -> dict:
    """``document[k1][k2]…`` when every step is a dict, else ``{}``."""
    node: object = document
    for key in keys:
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, dict) else {}


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
    summary="Razorpay webhook receiver",
    dependencies=[Depends(_webhook_limit)],
)
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not razorpay_client.verify_webhook_signature(body, signature):
        # Either somebody other than Razorpay is calling, or the webhook secret
        # here and in the Razorpay dashboard have drifted apart — in which case
        # every real event is being refused and nothing else will say so.
        logger.warning(
            "Razorpay webhook refused: signature did not verify",
            extra={
                "has_signature": bool(signature),
                "body_length": len(body),
                # The caller, not the proxy: behind Caddy ``request.client`` is
                # the same container address on every forged attempt.
                "client": client_ip(request),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )

    try:
        payload = json.loads(body)
    # JSONDecodeError and UnicodeDecodeError are both ValueErrors; a body nested
    # past the recursion limit is the one way json.loads fails without one.
    except (ValueError, RecursionError) as exc:
        logger.error(
            "Razorpay webhook body is not valid JSON",
            extra={
                "body_length": len(body),
                "body_prefix": body[:200].decode("utf-8", errors="replace"),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body is not valid JSON.",
        ) from exc
    if not isinstance(payload, dict):
        # Signed, so it came from Razorpay — but a JSON array or string here
        # would reach the `.get` chain below and come back as a 500, which
        # Razorpay retries for a day.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body must be a JSON object.",
        )

    # The same reasoning one level down. Only the top level was checked, so a
    # signed body whose ``payload``, ``payment`` or ``entity`` was a list, a
    # string or null — or whose id was not a string — raised in this chain and
    # was a 500 Razorpay retries for a day. Walked as dicts only; anything else
    # reads as absent and lands in the "no identifiable id" acknowledgement.
    event = payload.get("event")
    if not isinstance(event, str):
        event = ""
    entity = _dig(payload, "payload", "payment", "entity") or _dig(
        payload, "payload", "subscription", "entity"
    )
    razorpay_id = entity.get("id") or entity.get("subscription_id")
    if not isinstance(razorpay_id, str):
        razorpay_id = None

    if not razorpay_id:
        logger.warning(
            "Razorpay webhook contained no identifiable subscription or payment id",
            extra={"event": event},
        )
        return {"status": "ok"}

    sub = db.scalar(
        select(Subscription).where(
            Subscription.razorpay_subscription_id == razorpay_id
        )
    )
    if sub is None:
        logger.warning(
            "Webhook referenced unknown subscription",
            extra={"razorpay_id": razorpay_id, "event": event},
        )
        return {"status": "ok"}

    _TRANSITION: dict[str, SubscriptionStatus] = {
        "subscription.halted": SubscriptionStatus.PAST_DUE,
        "subscription.cancelled": SubscriptionStatus.CANCELLED,
        "subscription.expired": SubscriptionStatus.EXPIRED,
        "subscription.activated": SubscriptionStatus.ACTIVE,
        "subscription.charged": SubscriptionStatus.ACTIVE,
        "payment.failed": SubscriptionStatus.PAST_DUE,
    }

    _VALID_FROM: dict[SubscriptionStatus, frozenset[SubscriptionStatus]] = {
        SubscriptionStatus.ACTIVE: frozenset({
            SubscriptionStatus.PAST_DUE,
        }),
        SubscriptionStatus.PAST_DUE: frozenset({
            SubscriptionStatus.ACTIVE,
        }),
        SubscriptionStatus.CANCELLED: frozenset({
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
        }),
        SubscriptionStatus.EXPIRED: frozenset({
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
        }),
    }

    new_status = _TRANSITION.get(event)
    if new_status is None or sub.status == new_status:
        # Acknowledged so Razorpay stops retrying, and recorded so "the
        # webhook arrived and changed nothing" is distinguishable from "the
        # webhook never arrived".
        logger.info(
            "Webhook acknowledged without a status change",
            extra={
                "business_id": sub.business_id,
                "razorpay_id": razorpay_id,
                "event": event,
                "reason": "unhandled event" if new_status is None else "already in that status",
            },
        )
    if new_status is not None and sub.status != new_status:
        allowed_from = _VALID_FROM.get(new_status, frozenset())
        if sub.status not in allowed_from:
            logger.warning(
                "Webhook requested invalid transition %s → %s; ignored",
                sub.status.value, new_status.value,
                extra={
                    "business_id": sub.business_id,
                    "razorpay_id": razorpay_id,
                    "event": event,
                },
            )
            return {"status": "ok"}
        old = sub.status
        # Written only onto the subscription as it was read. Between the read
        # above and here the user can renew — verify-payment moving a halted
        # or cancelled subscription back to ``active`` under a new payment id —
        # and a plain assignment wrote this event's status over that by primary
        # key: a ``subscription.cancelled`` for the old mandate cancelled the
        # plan the user had just paid for. Matching the status and the id the
        # event was looked up by leaves a row that moved on alone; the event
        # was about a subscription that no longer exists in that form.
        moved = db.execute(
            update(Subscription)
            .where(
                Subscription.id == sub.id,
                Subscription.status == old,
                Subscription.razorpay_subscription_id == razorpay_id,
            )
            .values(status=new_status)
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()
        if not moved:
            logger.info(
                "Webhook skipped: the subscription changed while it was handled",
                extra={
                    "business_id": sub.business_id,
                    "razorpay_id": razorpay_id,
                    "event": event,
                },
            )
            return {"status": "ok"}
        logger.info(
            "Webhook transitioned subscription %s → %s",
            old.value, new_status.value,
            extra={
                "business_id": sub.business_id,
                "razorpay_id": razorpay_id,
                "event": event,
            },
        )
    return {"status": "ok"}
