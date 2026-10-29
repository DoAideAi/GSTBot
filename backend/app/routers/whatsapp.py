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
import re
from typing import Any
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.config import settings
from app.core.rate_limit import RateLimit
from app.core.sanitize import strip_control_chars
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
    # Bytes, not str: a non-ASCII header made compare_digest raise (a 500).
    return hmac.compare_digest(signature.encode("utf-8"), expected_b64.encode("utf-8"))


def _first_object(container: object, key: str) -> dict:
    """``container[key][0]`` when every step is the shape the Cloud API documents,
    else ``{}``."""
    items = container.get(key) if isinstance(container, dict) else None
    first = items[0] if isinstance(items, list) and items else None
    return first if isinstance(first, dict) else {}


def _cloud_api_message(data: object) -> tuple[str, str]:
    """``(sender, text)`` from a Cloud API envelope; empty strings for anything else.

    This route is unauthenticated on the JSON branch, so the body is whatever
    anyone sends. Each level used to be read with ``.get`` on the assumption it
    was an object: a top-level list, a ``null`` or string entry, a ``null``
    message or a numeric ``from`` each raised and answered a 500. Every level is
    now checked, and a shape that is not the documented one is simply no message.
    """
    entry = _first_object(data, "entry")
    change = _first_object(entry, "changes")
    value = change.get("value")
    message = _first_object(value, "messages")
    sender = message.get("from")
    sender = sender if isinstance(sender, str) else ""
    text = ""
    if message.get("type") == "text":
        content = message.get("text")
        candidate = content.get("body") if isinstance(content, dict) else None
        text = candidate if isinstance(candidate, str) else ""
    return sender, text


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
    responses={
        # Both, because both happen: the handshake echoes ``hub.challenge`` as
        # plain text, which is what Meta compares, and a request that is not a
        # handshake gets a JSON acknowledgement. Only the JSON was documented.
        200: {
            "description": (
                "The `hub.challenge` value as plain text when the token matches; "
                'otherwise `{"status": "ok"}`.'
            ),
            "content": {"text/plain": {"schema": {"type": "string"}}, "application/json": {}},
        },
        403: {"description": "`hub.verify_token` does not match the configured token."},
    },
)
def verify_webhook(
    response: Response,
    hub_mode: str | None = Query(None, alias="hub.mode", max_length=64),
    hub_token: str | None = Query(None, alias="hub.verify_token", max_length=256),
    hub_challenge: str | None = Query(None, alias="hub.challenge", max_length=256),
) -> dict[str, Any] | Response:
    verify_token = settings.whatsapp_verify_token
    if hub_mode == "subscribe" and hub_token and hub_challenge:
        if verify_token and hmac.compare_digest(
            hub_token.encode("utf-8"), verify_token.encode("utf-8")
        ):
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
    response_class=Response,
    responses={
        # TwiML to Twilio, JSON to the Cloud API — the reply is in the dialect
        # the request arrived in, and only the JSON one was documented.
        200: {
            "description": "TwiML for a Twilio request, JSON for a Cloud API one.",
            "content": {"application/xml": {"schema": {"type": "string"}}, "application/json": {}},
        },
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
        sender, body = _cloud_api_message(data)
    else:
        return Response(
            content="Unsupported content type",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # What the user typed is echoed back in the reply ("No codes found for
    # *...*"). Control characters in it made the TwiML invalid XML, and a long
    # message made a reply Twilio refuses (1,600 characters at most) — either
    # way the user got nothing back. Neither has any meaning to the parser.
    body = strip_control_chars(body, keep_newlines=True)[:MAX_INBOUND_CHARS]
    if not body.strip():
        body = "hi"

    parsed = parse_message(body)

    logger.info(
        "WhatsApp message",
        extra={
            "intent": parsed.intent.value,
            "sender_hash": hashlib.sha256(sender.encode()).hexdigest()[:12] if sender else "",
        },
    )

    reply_text = _fit(format_response(parsed))

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


# Longest inbound text worth reading: any real query is a few words, and the
# reply echoes it back.
MAX_INBOUND_CHARS = 1000

# Twilio refuses a WhatsApp message body over 1,600 characters, so a longer
# reply is not delivered at all.
MAX_REPLY_CHARS = 1600

# Characters XML 1.0 does not allow in a document at all, escaped or not.
_XML_ILLEGAL = re.compile("[^\t\n\r\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")


def _fit(reply: str) -> str:
    if len(reply) <= MAX_REPLY_CHARS:
        return reply
    return reply[: MAX_REPLY_CHARS - 1].rstrip() + "…"


def _escape_xml(text: str) -> str:
    # Dropped before escaping: entity-escaping cannot make these legal, and one
    # of them leaves Twilio a document it cannot parse.
    text = _XML_ILLEGAL.sub("", text)
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
