"""WhatsApp webhook — receives messages from Twilio or a WhatsApp Business API.

Two endpoints:

* ``GET /whatsapp/webhook`` — verification handshake. Twilio does not use
  this, but the WhatsApp Cloud API does (``hub.verify_token`` challenge).
  Included so the same router works with either provider.

* ``POST /whatsapp/webhook`` — incoming message. Parses the body as either
  Twilio form data (``From``, ``Body``) or WhatsApp Cloud API JSON, detects
  the user's intent, and returns a response.

Both are public: they are called by WhatsApp/Twilio servers, not by users.
The POST authenticates via ``X-Twilio-Signature`` when a Twilio auth token
is configured; without one it accepts anything, which is fine for development
and for providers that authenticate at the network level.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.config import settings
from app.core.rate_limit import RateLimit
from app.services.whatsapp import format_response, parse_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["health"])

_webhook_limit = RateLimit("whatsapp_webhook", "120/minute", by="ip")

# Twilio signs requests with HMAC-SHA1 of the full URL + sorted POST params.
# Only verified when WHATSAPP_TWILIO_AUTH_TOKEN is set; without it, signature
# checking is skipped (development / non-Twilio providers).
_TWILIO_SIGNATURE_HEADER = "X-Twilio-Signature"


def _verify_twilio_signature(
    request: Request,
    body_params: dict[str, str],
) -> bool:
    """Validate ``X-Twilio-Signature`` against the configured auth token."""
    auth_token = settings.whatsapp_twilio_auth_token
    if not auth_token:
        return True

    signature = request.headers.get(_TWILIO_SIGNATURE_HEADER, "")
    if not signature:
        return False

    url = str(request.url)
    # Twilio expects the *public* URL, which may differ from what the app sees
    # behind a reverse proxy. When a base URL is configured, reconstruct.
    webhook_base = settings.whatsapp_webhook_base_url
    if webhook_base:
        url = urljoin(webhook_base, request.url.path)

    # Sort post params by key and concatenate key+value.
    data_string = url + "".join(
        f"{k}{v}" for k, v in sorted(body_params.items())
    )
    expected = hmac.new(
        auth_token.encode("utf-8"),
        data_string.encode("utf-8"),
        hashlib.sha1,
    ).digest()

    import base64

    expected_b64 = base64.b64encode(expected).decode()
    return hmac.compare_digest(signature, expected_b64)


@router.get(
    "/webhook",
    summary="WhatsApp webhook verification (Cloud API handshake)",
    description=(
        "Responds to the WhatsApp Cloud API's ``hub.verify_token`` challenge. "
        "Twilio does not use this; it is here so the same endpoint works with "
        "either provider. Returns the ``hub.challenge`` value when the token "
        "matches, or 403 when it does not."
    ),
    dependencies=[Depends(_webhook_limit)],
    response_model=None,
    responses={403: {"description": "`hub.verify_token` does not match the configured token."}},
)
def verify_webhook(
    response: Response,
    hub_mode: str | None = Query(None, alias="hub.mode", max_length=64),
    hub_token: str | None = Query(None, alias="hub.verify_token", max_length=256),
    hub_challenge: str | None = Query(None, alias="hub.challenge", max_length=256),
) -> dict[str, Any] | Response:
    verify_token = settings.whatsapp_verify_token
    if hub_mode == "subscribe" and hub_token and hub_challenge:
        if verify_token and hmac.compare_digest(hub_token, verify_token):
            return Response(content=hub_challenge, media_type="text/plain")
        response.status_code = status.HTTP_403_FORBIDDEN
        return {"error": "Token mismatch"}
    return {"status": "ok"}


@router.post(
    "/webhook",
    summary="Receive a WhatsApp message",
    description=(
        "Accepts an incoming WhatsApp message via Twilio (form-encoded) or "
        "the WhatsApp Cloud API (JSON). Parses the message, detects the "
        "user's intent (GST rate, GSTIN verification, HSN lookup, or "
        "calculation), and returns the formatted reply.\n\n"
        "When WHATSAPP_TWILIO_AUTH_TOKEN is configured, the request is "
        "authenticated by its ``X-Twilio-Signature`` header."
    ),
    dependencies=[Depends(_webhook_limit)],
    responses={
        400: {"description": "A JSON body that does not parse, or a content type that is neither."},
        403: {
            "description": (
                "A Twilio (form-encoded) request whose `X-Twilio-Signature` is missing "
                "or does not verify, when a Twilio auth token is configured."
            )
        },
    },
)
async def receive_message(request: Request) -> Response:
    """Handle an incoming WhatsApp message from Twilio or Cloud API."""
    content_type = request.headers.get("content-type", "")

    sender = ""
    body = ""
    is_twilio = False

    if "application/x-www-form-urlencoded" in content_type:
        # Twilio sends form data.
        form = await request.form()
        sender = str(form.get("From", ""))
        body = str(form.get("Body", ""))
        is_twilio = True

        body_params = {k: str(v) for k, v in form.items()}
        if not _verify_twilio_signature(request, body_params):
            sender_hash = hashlib.sha256(sender.encode()).hexdigest()[:12] if sender else ""
            logger.warning(
                "Invalid Twilio signature",
                extra={"sender_hash": sender_hash},
            )
            return Response(
                content="Invalid signature",
                status_code=status.HTTP_403_FORBIDDEN,
            )
    elif "application/json" in content_type:
        # WhatsApp Cloud API sends JSON.
        try:
            data = await request.json()
        except Exception:
            return Response(
                content="Invalid JSON",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        # Navigate the Cloud API envelope.
        raw_entry = data.get("entry")
        entry = (raw_entry or [{}])[0] if isinstance(raw_entry, list) else {}
        raw_changes = entry.get("changes")
        changes = (raw_changes or [{}])[0] if isinstance(raw_changes, list) else {}
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if messages:
            msg = messages[0]
            sender = msg.get("from", "")
            if msg.get("type") == "text":
                body = msg.get("text", {}).get("body", "")
    else:
        return Response(
            content="Unsupported content type",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if not body:
        body = "hi"

    parsed = parse_message(body)

    logger.info(
        "WhatsApp message",
        extra={
            "intent": parsed.intent.value,
            "sender_hash": hashlib.sha256(sender.encode()).hexdigest()[:12] if sender else "",
        },
    )

    reply_text = format_response(parsed)

    if is_twilio:
        # Twilio expects TwiML.
        twiml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"<Message>{_escape_xml(reply_text)}</Message>"
            "</Response>"
        )
        return Response(content=twiml, media_type="application/xml")

    # For the Cloud API (or generic webhook), return JSON.
    return Response(
        content=_json_dumps({"reply": reply_text, "to": sender}),
        media_type="application/json",
    )


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _json_dumps(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
