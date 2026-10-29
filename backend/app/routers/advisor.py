"""AI GST advisor — proxies the Gemini API so the frontend avoids CORS.

Public and stateless: the endpoint accepts a conversation history and returns
the model's next reply. The API key lives server-side, so it never reaches
the browser.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings
from app.core.rate_limit import RateLimit
from app.core.sanitize import encodable, visible_text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["advisor"])

_advisor_limit = RateLimit("advisor_ask", "30/minute", by="ip")
# Every question is a paid Gemini call, and 30 a minute from one address is
# still 43,200 a day: the per-minute limit stops a burst, not a bill. A daily
# allowance per address, and a ceiling on everyone together so that many
# addresses cannot do what one cannot. Both are RATE_LIMIT_OVERRIDES names.
_advisor_daily = RateLimit(
    "advisor_daily",
    "100/day",
    by="ip",
    detail=(
        "You have asked the AI advisor its daily limit of questions. It resets within "
        "24 hours; the free calculators and lookups still work in the meantime."
    ),
)
_advisor_site_daily = RateLimit(
    "advisor_site_daily",
    "5000/day",
    by="site",
    detail=(
        "The AI advisor has answered as many questions as it can today. It will be "
        "back tomorrow; the free calculators and lookups still work in the meantime."
    ),
)
# In this order: a caller refused for their own minute or day is never
# charged against everyone's ceiling.
_ADVISOR_LIMITS = [
    Depends(_advisor_limit),
    Depends(_advisor_daily),
    Depends(_advisor_site_daily),
]

# Tried in order. One model is a single point of failure the advisor has
# already met: gemini-3.8-flash answered 503 "high demand" for long enough that
# every visitor got the apology below and nothing else. Overload and quota are
# per model, so the next one in the list usually answers when the first will
# not. Only those two kinds of failure move on — a 400 means the request itself
# is wrong and every model would refuse it the same way.
_GEMINI_MODELS = ("gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite")
_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_GEMINI_STREAM_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:streamGenerateContent?alt=sse"
)
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

def _get_api_key() -> str | None:
    # Through Settings, not ``os.environ``: a key in ``.env`` was invisible to a
    # direct environment read, so the advisor answered "not set up" on a machine
    # whose configuration said otherwise.
    key = settings.gemini_api_key.strip()
    if key:
        return key
    if not settings.gemini_api_key_file:
        return None
    key_file = Path(settings.gemini_api_key_file)
    try:
        key = key_file.read_text().strip()
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
            extra={"path": str(key_file), "error": str(exc)},
        )
    return None


def is_configured() -> bool:
    """Whether the advisor has a Gemini key to answer with. For /health."""
    return _get_api_key() is not None


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
            timeout=20.0,
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

    # Refused here rather than sent: every question is a paid model call, and
    # one of spaces or zero-width characters bought an answer to nothing.
    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = visible_text(value)
        if not stripped:
            raise ValueError("Type a question for the advisor to answer.")
        return stripped


def _build_contents(history: list[HistoryMessage], message: str) -> list[dict]:
    # The system prompt is now a top-level ``systemInstruction`` (see
    # ``_build_payload``), so it no longer takes a fake user/model turn pair
    # that grew every request by two turns the model had to read. The Gemini
    # API requires the first content to have role "user"; slicing into the
    # middle of a long history can land on a model turn, so those are skipped.
    recent = history[-HISTORY_TURNS_SENT:]
    contents: list[dict] = []
    for m in recent:
        role = "user" if m.role == "user" else "model"
        if not contents and role == "model":
            continue
        contents.append({"role": role, "parts": [{"text": m.text}]})
    contents.append({"role": "user", "parts": [{"text": message}]})
    return contents


def _build_payload(history: list[HistoryMessage], message: str) -> dict:
    return {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": _build_contents(history, message),
        "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.7},
    }


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
    dependencies=_ADVISOR_LIMITS,
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
                extra={"key_file": settings.gemini_api_key_file},
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The AI advisor is not set up on this server yet, so it cannot answer "
                "questions. The GSTIndia team has been alerted; the GST calculators and "
                "guides work in the meantime."
            ),
        )

    payload = _build_payload(body.history, body.message)

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


# Far above what ``maxOutputTokens`` lets a real answer reach (1,024 tokens is a
# few kilobytes); only a misbehaving upstream gets near it. Without a bound a
# 3 MB body was relayed whole to the browser.
MAX_REPLY_CHARS = 32_000


def _clean_reply(text: str) -> str:
    """*text* safe to serialise: unpaired surrogates replaced, length bounded.

    ``json.loads`` accepts a lone ``\\ud800`` escape in the upstream reply and
    hands back an unpaired surrogate, which cannot be encoded as UTF-8 — the
    response model then failed to serialise and the user got a 500 for one bad
    character in an otherwise good answer.
    """
    return encodable(text)[:MAX_REPLY_CHARS]


def _reply_parts(data: object) -> str | None:
    """The answer's text exactly as written, or ``None`` when there is none."""
    candidates = data.get("candidates") if isinstance(data, dict) else None
    first = candidates[0] if isinstance(candidates, list) and candidates else None
    content = first.get("content") if isinstance(first, dict) else None
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        return None
    text = _clean_reply(
        "".join(p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str))
    )
    return text or None


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
    text = _clean_reply(
        "".join(
            p["text"] for p in parts if isinstance(p, dict) and isinstance(p.get("text"), str)
        ).strip()
    )
    return text or None


# ---------------------------------------------------------------------------
# Streaming endpoint — tokens appear in the chat as the model writes them
# ---------------------------------------------------------------------------

_STREAM_TIMEOUT = httpx.Timeout(5.0, read=30.0)


def _chunk_text(raw: str) -> str | None:
    """Extract text from one Gemini SSE ``data:`` line.

    Unstripped, unlike a whole reply: the model splits its answer mid-sentence,
    so the space after "GST " belongs to this chunk, and stripping each one
    printed "GSTis18%." for "GST is 18%.".
    """
    try:
        data = _json.loads(raw)
    except (ValueError, TypeError):
        return None
    return _reply_parts(data)


async def _stream_from_gemini(
    api_key: str,
    payload: dict,
    started: float,
) -> AsyncIterator[str]:
    """Try models in order; yield ``data: …`` SSE lines as text arrives."""
    client = _client()
    last_model = _GEMINI_MODELS[0]
    last_status = 0
    # Once any text has reached the browser, falling through to the next model
    # would start a second answer from its first word, appended to the first
    # answer's half. From then on a failure ends the stream with an error.
    sent_text = False

    for attempt, model in enumerate(_GEMINI_MODELS, start=1):
        last_model = model
        url = _GEMINI_STREAM_URL.format(model=model)
        try:
            req = client.build_request(
                "POST", url,
                headers={"x-goog-api-key": api_key},
                json=payload,
                timeout=_STREAM_TIMEOUT,
            )
            response = await client.send(req, stream=True)
            last_status = response.status_code

            if response.status_code != 200:
                body = (await response.aread()).decode(errors="replace")[:200]
                await response.aclose()
                logger.warning(
                    "Gemini %s stream returned %d: %s", model, response.status_code, body,
                )
                if response.status_code not in _RETRYABLE:
                    break
                continue

            try:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    text = _chunk_text(line[6:])
                    if text:
                        sent_text = True
                        yield f"data: {_json.dumps({'t': text})}\n\n"
            finally:
                await response.aclose()

            if not sent_text:
                # A 200 with no text — a safety block, an empty candidate. The
                # next model may answer; if none does, the error below says so
                # rather than a "done" over an empty bubble.
                logger.warning("Gemini %s streamed no text", model)
                continue

            logger.info(
                "Advisor streamed",
                extra={
                    "model": model,
                    "attempt": attempt,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            yield f"data: {_json.dumps({'done': True})}\n\n"
            return

        except httpx.TimeoutException:
            logger.warning(
                "Advisor stream to %s timed out",
                model,
                extra={"duration_ms": int((time.monotonic() - started) * 1000)},
            )
            if sent_text:
                break
            continue
        except Exception:
            logger.exception("Advisor stream error with %s", model)
            break

    duration = int((time.monotonic() - started) * 1000)
    logger.error(
        "Advisor stream gave no answer",
        extra={"last_model": last_model, "last_status": last_status, "duration_ms": duration},
    )
    if sent_text:
        msg = "The answer was cut off. Ask again for the rest."
    elif last_status in (429, 503):
        msg = "The AI advisor is overloaded right now. Wait a minute and ask again."
    else:
        msg = "The AI advisor could not answer just now. Try again in a minute."
    yield f"data: {_json.dumps({'error': msg})}\n\n"


@router.post(
    "/advisor/ask/stream",
    summary="Stream a GST AI Advisor answer token by token",
    description=(
        "Same question shape as ``/advisor/ask`` but the answer arrives as "
        "server-sent events: ``{t: text}`` chunks, then ``{done: true}`` or "
        "``{error: message}``. The first token appears in under a second."
    ),
    responses={503: {"description": "No API key is configured."}},
    dependencies=_ADVISOR_LIMITS,
)
async def ask_advisor_stream(body: AdvisorRequest) -> StreamingResponse:
    global _reported_missing_key
    api_key = _get_api_key()
    if not api_key:
        if not _reported_missing_key:
            _reported_missing_key = True
            logger.error(
                "Advisor has no Gemini API key (stream)",
                extra={"key_file": settings.gemini_api_key_file},
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "The AI advisor is not set up on this server yet, so it cannot answer "
                "questions. The GSTIndia team has been alerted."
            ),
        )

    payload = _build_payload(body.history, body.message)
    started = time.monotonic()
    return StreamingResponse(
        _stream_from_gemini(api_key, payload, started),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
