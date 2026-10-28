"""AI GST advisor — proxies the Gemini API so the frontend avoids CORS.

Public and stateless: the endpoint accepts a conversation history and returns
the model's next reply. The API key lives server-side, so it never reaches
the browser.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.rate_limit import RateLimit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["advisor"])

_advisor_limit = RateLimit("advisor_ask", "30/minute", by="ip")

# Tried in order. One model is a single point of failure the advisor has
# already met: gemini-3.8-flash answered 503 "high demand" for long enough that
# every visitor got the apology below and nothing else. Overload and quota are
# per model, so the next one in the list usually answers when the first will
# not. Only those two kinds of failure move on — a 400 means the request itself
# is wrong and every model would refuse it the same way.
_GEMINI_MODELS = ("gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite")
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_RETRYABLE = frozenset({429, 500, 502, 503, 504})

SYSTEM_PROMPT = (
    "You are GSTIndia AI Advisor, an expert on India's Goods and Services Tax. "
    "Help users with GST registration, GSTR-1/GSTR-3B/GSTR-9 filing, HSN and SAC codes, "
    "input tax credit (ITC) eligibility and reconciliation, composition scheme rules, "
    "e-way bill requirements, reverse charge mechanism, GST rates for goods and services, "
    "inter-state vs intra-state supply, TDS/TCS under GST, refund procedures, "
    "penalties and interest for late filing, and general GST compliance for Indian SMBs. "
    "Answer concisely and accurately. Cite relevant sections of the CGST/SGST/IGST Acts "
    "when applicable. If a question is outside GST or Indian tax law, politely decline "
    "and redirect to GST topics. Use simple language suited for small business owners."
)

_KEY_FILE = Path("/opt/GSTBot/keys/gemini-api-key")


def _get_api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    try:
        key = _KEY_FILE.read_text().strip()
        if key:
            return key
    except FileNotFoundError:
        pass  # the ordinary state of a machine configured through the environment
    except OSError as exc:
        # A key file that is there and cannot be read (permissions, a directory
        # where the file should be) is a deployment fault, not an absent key —
        # and the user only ever sees "temporarily unavailable".
        logger.error(
            "Advisor key file could not be read",
            extra={"path": str(_KEY_FILE), "error": str(exc)},
        )
    return None


#: Whether the "no key" error has been logged by this process. Once is the
#: signal; on every question it would be the noise that hides other lines.
_reported_missing_key = False


#: How many earlier messages are forwarded with a question. The widget sends
#: the whole conversation, and every one of up to fifty 4,000-character turns
#: was prompt the model had to read before it could start answering — the long
#: tail of a chat made each reply slower than the last. A dozen turns is more
#: context than a follow-up question needs.
HISTORY_TURNS_SENT = 12

#: One pooled client per event loop. A client per request meant a new TCP
#: connection and TLS handshake to Google on every question, which is most of a
#: second before the model sees anything on a cold path. Keyed by loop because
#: an httpx client is bound to the loop it first ran on.
_clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}


def _client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    # A loop that has closed can never run its client again, and nothing else
    # would remove its entry: any process that makes loops over its life (a
    # worker that restarts its loop, a test run) grew this dict by one client
    # and one dead loop per loop. Dropped rather than closed — aclose() needs
    # the loop that is gone; the sockets go with the objects.
    for dead in [other for other in _clients if other.is_closed()]:
        del _clients[dead]
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=10, keepalive_expiry=60.0),
        )
        _clients[loop] = client
    return client


async def close_clients() -> None:
    """Close every pooled client. Called from the app's lifespan shutdown."""
    clients = list(_clients.values())
    _clients.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception as exc:  # noqa: BLE001 - shutdown is not a place to fail
            logger.warning("Advisor HTTP client did not close cleanly: %s", exc)


class HistoryMessage(BaseModel):
    role: str = Field(max_length=20)
    text: str = Field(max_length=4000)


class AdvisorRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=50)


def _build_contents(history: list[HistoryMessage], message: str) -> list[dict]:
    contents: list[dict] = [
        {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
        {"role": "model", "parts": [{"text": "Understood. I'm your GST advisor. How can I help?"}]},
    ]
    for m in history[-HISTORY_TURNS_SENT:]:
        contents.append({
            "role": "user" if m.role == "user" else "model",
            "parts": [{"text": m.text}],
        })
    contents.append({"role": "user", "parts": [{"text": message}]})
    return contents


@router.post(
    "/advisor/ask",
    summary="Ask the GST AI Advisor a question",
    description=(
        "Proxies a question to the Gemini model with a GST-expert system prompt. "
        "Accepts the current message and conversation history. Public — called "
        "from the chatbot widget before and after sign-in."
    ),
    responses={
        502: {
            "description": (
                "The model refused the question, gave no answer, or failed "
                "upstream. `detail` says which, and whether rephrasing helps."
            )
        },
        503: {"description": "The model is overloaded, or no API key is configured."},
        504: {"description": "The model took too long to answer."},
    },
    dependencies=[Depends(_advisor_limit)],
)
async def ask_advisor(body: AdvisorRequest) -> dict[str, str]:
    global _reported_missing_key
    api_key = _get_api_key()
    if not api_key:
        if not _reported_missing_key:
            _reported_missing_key = True
            logger.error(
                "Advisor has no Gemini API key: every question is answered "
                "'temporarily unavailable' (set GEMINI_API_KEY or the key file)",
                extra={"key_file": str(_KEY_FILE)},
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The AI advisor is not set up on this server yet, so it cannot answer "
                "questions. The GSTIndia team has been alerted; the GST calculators and "
                "guides work in the meantime."
            ),
        )

    contents = _build_contents(body.history, body.message)
    payload = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.7},
    }

    started = time.monotonic()
    model = _GEMINI_MODELS[0]
    try:
        client = _client()
        for attempt, model in enumerate(_GEMINI_MODELS, start=1):
            response = await client.post(
                _GEMINI_URL.format(model=model),
                headers={"x-goog-api-key": api_key},
                json=payload,
            )
            if response.status_code == 200:
                logger.info(
                    "Advisor answered",
                    extra={
                        "model": model,
                        "attempt": attempt,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "history_turns": len(body.history),
                    },
                )
                try:
                    parsed = response.json()
                except ValueError:  # a 200 that is not JSON — a proxy's page
                    parsed = None
                reply = _reply_text(parsed)
                if reply is None:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            "The advisor produced no answer to that question. Try "
                            "rephrasing it, or asking about one GST topic at a time."
                        ),
                    )
                return {"reply": reply}
            logger.warning(
                "Gemini %s returned %d: %s",
                model,
                response.status_code,
                response.text[:200],
            )
            if response.status_code not in _RETRYABLE:
                break
        logger.error(
            "Advisor gave no answer: no Gemini model accepted the request",
            extra={
                "last_model": model,
                "last_status": response.status_code,
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
        # Which of three things the last refusal was decides what the user can
        # do about it: wait (overloaded), wait longer (the service is failing),
        # or change the question (it was refused as asked).
        if response.status_code in (429, 503):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The AI advisor is overloaded right now. Wait a minute and ask again.",
            )
        if response.status_code in _RETRYABLE:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "The AI service behind the advisor is having problems. Try again "
                    "in a few minutes."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI service refused this question. Try rephrasing it.",
        )

    except HTTPException:
        raise
    except httpx.TimeoutException:
        logger.warning(
            "Advisor request to Gemini timed out",
            extra={"model": model, "duration_ms": int((time.monotonic() - started) * 1000)},
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                "The AI advisor took too long to answer. Ask again — shorter "
                "questions are answered faster."
            ),
        ) from None
    except Exception:
        logger.exception("Advisor proxy error")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "The AI advisor could not answer because of a problem on our side. "
                "Try again in a minute."
            ),
        ) from None


def _reply_text(data: object) -> str | None:
    """The answer's text, or ``None`` when the 200 carries none.

    A 200 is not always an answer: a candidate stopped by a safety filter, or
    one that spent its whole budget thinking, arrives with no parts at all.
    Nor is it always the documented shape — a ``null`` candidate, a string
    where an object belongs, a non-string ``text`` — and each of those raised
    out of here into the catch-all, which told the user "a problem on our side"
    and logged a traceback for what is simply an unusable reply. Every shape
    that is not text now reads as no answer.
    """
    candidates = data.get("candidates") if isinstance(data, dict) else None
    first = candidates[0] if isinstance(candidates, list) and candidates else None
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return None
    text = "".join(
        p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)
    ).strip()
    return text or None
