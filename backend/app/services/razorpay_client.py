"""Razorpay integration: subscription creation, verification, webhooks.

Degrades gracefully when credentials are not configured — the product works
without payments, the free tier is the default.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

import httpx

from app.core.config import settings
from app.models.subscription import SubscriptionTier

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.razorpay.com/v1"


def is_configured() -> bool:
    return bool(settings.razorpay_key_id and settings.razorpay_key_secret)


def _auth() -> tuple[str, str]:
    return (settings.razorpay_key_id, settings.razorpay_key_secret)


def _plan_id_for_tier(tier: SubscriptionTier) -> str | None:
    if tier == SubscriptionTier.PRO:
        return settings.razorpay_plan_id_pro or None
    if tier == SubscriptionTier.ENTERPRISE:
        return settings.razorpay_plan_id_enterprise or None
    return None


def _exc_context(exc: Exception, operation: str, **fields: Any) -> dict[str, Any]:
    """Structured fields for a Razorpay failure log line.

    Pulls the HTTP status from the exception when it wraps one, so transport
    errors (no response at all) carry ``status_code: None`` rather than
    raising a second time trying to read it.
    """
    status: int | None = None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    return {"operation": operation, "status_code": status, **fields}


def create_customer(email: str, name: str | None = None) -> dict[str, Any] | None:
    if not is_configured():
        return None
    try:
        resp = httpx.post(
            f"{_BASE_URL}/customers",
            json={"email": email, "name": name or email.split("@")[0]},
            auth=_auth(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.exception(
            "Razorpay create_customer failed",
            extra=_exc_context(exc, "create_customer"),
        )
        return None


def create_subscription(
    plan_id: str,
    customer_id: str | None = None,
    total_count: int = 12,
) -> dict[str, Any] | None:
    if not is_configured():
        return None
    payload: dict[str, Any] = {
        "plan_id": plan_id,
        "total_count": total_count,
    }
    if customer_id:
        payload["customer_id"] = customer_id
    try:
        resp = httpx.post(
            f"{_BASE_URL}/subscriptions",
            json=payload,
            auth=_auth(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.exception(
            "Razorpay create_subscription failed",
            extra=_exc_context(exc, "create_subscription", plan_id=plan_id),
        )
        return None


def create_order(
    amount_paise: int,
    currency: str = "INR",
    receipt: str | None = None,
) -> dict[str, Any] | None:
    """Create a one-time payment order (used for the checkout flow)."""
    if not is_configured():
        return None
    payload: dict[str, Any] = {
        "amount": amount_paise,
        "currency": currency,
    }
    if receipt:
        payload["receipt"] = receipt
    try:
        resp = httpx.post(
            f"{_BASE_URL}/orders",
            json=payload,
            auth=_auth(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.exception(
            "Razorpay create_order failed",
            extra=_exc_context(exc, "create_order", amount_paise=amount_paise),
        )
        return None


def verify_payment_signature(
    order_id: str,
    payment_id: str,
    signature: str,
) -> bool:
    """Verify the Razorpay payment signature using HMAC-SHA256."""
    if not settings.razorpay_key_secret:
        logger.error(
            "Payment signature verification skipped: RAZORPAY_KEY_SECRET not configured",
            extra={"order_id": order_id},
        )
        return False
    message = f"{order_id}|{payment_id}"
    expected = hmac.new(
        settings.razorpay_key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Verify a Razorpay webhook signature."""
    secret = settings.razorpay_webhook_secret
    if not secret:
        logger.error(
            "Webhook signature verification skipped: RAZORPAY_WEBHOOK_SECRET not configured"
        )
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def cancel_subscription(subscription_id: str) -> dict[str, Any] | None:
    if not is_configured():
        return None
    try:
        resp = httpx.post(
            f"{_BASE_URL}/subscriptions/{subscription_id}/cancel",
            auth=_auth(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.exception(
            "Razorpay cancel_subscription failed",
            extra=_exc_context(exc, "cancel_subscription", subscription_id=subscription_id),
        )
        return None


def order_receipt(business_id: int, tier: SubscriptionTier) -> str:
    """The receipt an order is created with, and checked against on verify."""
    return f"biz_{business_id}_{tier.value}"


# The PDF report of one reconciliation run, bought once.
REPORT_PRICE_PAISE = 9900


def report_receipt(business_id: int, run_id: int) -> str:
    """The receipt a report order is created with, and checked against on verify.

    Naming the run as well as the business is what makes a paid order buy one
    report: a payment for run 7 presented against run 8 fails this comparison.
    """
    return f"rpt_{business_id}_{run_id}"


def fetch_order(order_id: str) -> dict[str, Any] | None:
    """The order as Razorpay holds it, or ``None`` if it cannot be read."""
    if not is_configured():
        return None
    try:
        resp = httpx.get(f"{_BASE_URL}/orders/{order_id}", auth=_auth(), timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.exception(
            "Razorpay fetch_order failed",
            extra=_exc_context(exc, "fetch_order", order_id=order_id),
        )
        return None


def fetch_subscription(subscription_id: str) -> dict[str, Any] | None:
    if not is_configured():
        return None
    try:
        resp = httpx.get(
            f"{_BASE_URL}/subscriptions/{subscription_id}",
            auth=_auth(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.exception(
            "Razorpay fetch_subscription failed",
            extra=_exc_context(exc, "fetch_subscription", subscription_id=subscription_id),
        )
        return None


# Pricing data served to the frontend (amounts in paise for Razorpay, display in rupees).
TIER_PRICING = {
    SubscriptionTier.FREE: {
        "name": "Free",
        "price_monthly": 0,
        "price_annual": 0,
        "price_display": "Free forever",
        "features": [
            "GST calculator",
            "GSTIN lookup & verification (1 at a time)",
            "HSN/SAC code search",
            "GST rate finder",
            "Due dates calendar",
        ],
    },
    SubscriptionTier.PRO: {
        "name": "SMB",
        "price_monthly": 499_00,
        "price_annual": 4999_00,
        "price_display": "₹499/month",
        "features": [
            "Bulk GSTIN validation (up to 100)",
            "GSTR-2B reconciliation",
            "ITC optimization report",
            "Export to Tally/Excel",
            "Priority AI assistant",
            "No ads",
            "GST filing assistance",
            "Saved calculations & history",
            "Email reports",
        ],
    },
    SubscriptionTier.ENTERPRISE: {
        "name": "CA",
        "price_monthly": 2999_00,
        "price_annual": 29990_00,
        "price_display": "₹2,999/month",
        "features": [
            "Everything in SMB",
            "Multi-client management",
            "Bulk filing",
            "API access",
            "Priority support",
            "Custom reports",
        ],
    },
}
