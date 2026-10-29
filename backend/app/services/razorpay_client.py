"""Razorpay integration: subscription creation, verification, webhooks.

Degrades gracefully when credentials are not configured — the product works
without payments, the free tier is the default.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
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


def _object(resp: httpx.Response, *required: str) -> dict[str, Any]:
    """The response body, if it is a JSON object carrying *required*.

    A 2xx is not a promise about the body. A proxy or a degraded upstream can
    answer 200 with a list, a bare string or an error object, and returning
    that as the order sent the routes into ``order["id"]`` / ``order.get`` on
    something that is not an order — a 500 where a refusal to trust the
    response belongs. Raised here so the caller's ``except`` turns it into the
    ``None`` every route already answers with a retryable 502.
    """
    body = resp.json()
    if not isinstance(body, dict):
        raise ValueError(f"expected a JSON object, got {type(body).__name__}")
    missing = [key for key in required if key not in body]
    if missing:
        raise ValueError(f"response is missing {', '.join(missing)}")
    return body


# What verify-payment will accept back as the order id (``VerifyPaymentRequest``).
_ORDER_ID = re.compile(r"order_[A-Za-z0-9_]{1,58}")


def _require_order_shape(order: dict[str, Any]) -> None:
    """Refuse an order whose fields are not the types checkout hands on.

    ``_object`` checks the keys are present, not what is in them, and the
    route builds its response straight from them: an ``"amount": "x"`` failed
    the response model — a 500 for the customer — and an id that is not
    shaped like Razorpay's went to the browser, which paid it and then had
    the payment refused by verify-payment's id check. Raised here so the
    caller's ``except`` turns it into the retryable 502 every other bad
    answer gets, before any money moves.
    """
    if not (isinstance(order["id"], str) and _ORDER_ID.fullmatch(order["id"])):
        raise ValueError("order id is not a Razorpay order id")
    if paise(order["amount"]) is None or not isinstance(order["currency"], str):
        raise ValueError("order amount or currency has the wrong type")


def paise(value: object) -> int | None:
    """*value* as an amount in paise, or ``None`` when it is not one.

    ``_object`` checks that an order is an object, not what is in it. A proxy
    or a degraded upstream answering ``"amount_paid": "49900"`` (or a list, or
    an object) reached ``<`` against an int in the verify routes and answered a
    paying customer with a 500. ``bool`` is excluded: it is an ``int`` to Python
    and ``True`` is not one paisa.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


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
        order = _object(resp, "id", "amount", "currency")
        _require_order_shape(order)
        return order
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
            "Payment refused: RAZORPAY_KEY_SECRET is not configured, "
            "so its signature cannot be checked",
            extra={"order_id": order_id},
        )
        return False
    message = f"{order_id}|{payment_id}"
    expected = hmac.new(
        settings.razorpay_key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return _same(expected, signature)


def _same(expected: str, presented: str) -> bool:
    """Constant-time equality that cannot raise.

    ``hmac.compare_digest`` on two ``str`` raises ``TypeError`` when either
    holds a non-ASCII character, and the presented signature is whatever the
    client sent — so a signature with an accent in it was a 500 from
    verify-payment, the report verify and the webhook, rather than the refusal
    a wrong signature is. Compared as UTF-8 bytes it is simply unequal.
    """
    return hmac.compare_digest(expected.encode("utf-8"), presented.encode("utf-8"))


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Verify a Razorpay webhook signature."""
    secret = settings.razorpay_webhook_secret
    if not secret:
        logger.error(
            "Webhook refused: RAZORPAY_WEBHOOK_SECRET is not configured, "
            "so its signature cannot be checked"
        )
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return _same(expected, signature)


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
        return _object(resp, "id")
    except Exception as exc:
        logger.exception(
            "Razorpay fetch_order failed",
            extra=_exc_context(exc, "fetch_order", order_id=order_id),
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
