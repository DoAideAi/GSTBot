"""The single entry point every AI feature calls.

Free-tier models only, over plain httpx — no SDK, no hidden global state, so
tests mock one function. Two provider quirks shape this module:

* The free reasoning models (``openai/gpt-oss-20b:free`` in particular) often
  return ``content: null`` with the answer parked in ``reasoning``. The client
  falls back to that field rather than crashing on ``None``.
* Free models ignore ``response_format`` about as often as they honour it, so
  callers ask for JSON in the prompt and :func:`extract_json_object` digs the
  object out of whatever prose or markdown fence it arrives wrapped in.

Every caller is expected to handle :class:`OpenRouterError` by falling back to
something deterministic. A free tier is a free tier: it rate-limits, and an
invoice upload must not fail because a model was busy.

That fallback is a real downgrade, though, and it is worth not taking when the
failure is one that goes away by itself. A 429 from the free tier is a
per-minute window that has refilled by the time the caller could have asked
again; the caller's alternative is regex heuristics on the invoice, which is a
materially worse answer for something the model would have got right on the
second try. So transient failures are retried here, and only transient ones — a
401 is a missing key and a 400 is a malformed request, and asking twice turns a
fast, clear error into a slow one.

Two bounds keep that from becoming its own outage. ``Retry-After`` is honoured
when the provider sends it, because guessing shorter just burns the next window
too. And the total time spent waiting is capped, because this runs inline in the
upload request when Celery is off — a caller waiting on retries is a caller
whose request is still open.
"""
from __future__ import annotations

import base64
import json
import logging
import random
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from app.core.breaker import Breaker
from app.core.config import settings
from app.core.sanitize import encodable

logger = logging.getLogger(__name__)


class OpenRouterError(RuntimeError):
    """Raised when no completion could be obtained."""


# Failures that a second attempt can plausibly fix. 429 is the free tier's
# normal signalling; 408 and the 5xx gateway codes are the provider or the hop
# in front of it, not the request. Deliberately absent: 400, 401, 403 and 404,
# which are the same wrong answer however many times they are asked.
_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

# The circuit breaker. Every call has its own budget and nothing remembered the
# last one failing, so while the provider was down every upload paid up to that
# budget twice (extraction, then OCR) before falling back to the heuristics it
# was always going to end on: a thirty-invoice batch held the one worker for
# over an hour, and with Celery off each wait was a request held open. After
# BREAKER_THRESHOLD calls in a row fail for availability's sake, calls fail at
# once for BREAKER_COOLDOWN_SECONDS — the cue every caller already treats as
# "fall back" — and then one probe is let through. Per process, like the Redis
# breaker: each worker finds out for itself, which costs a few calls, not an
# outage's worth.
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 120.0


def _monotonic() -> float:
    return time.monotonic()


# Read through _monotonic at call time, so a test that replaces it moves this
# breaker's clock. See app/core/breaker.py.
BREAKER = Breaker(
    "OpenRouter",
    threshold=BREAKER_THRESHOLD,
    cooldown=BREAKER_COOLDOWN_SECONDS,
    clock=lambda: _monotonic(),
)


def reset_breaker() -> None:
    """Close the breaker. For tests, which must not inherit another's outage."""
    BREAKER.reset()


# The wait before the first retry when the provider does not say. Doubles per
# attempt, so attempts land at roughly 1s, 2s, 4s.
_BACKOFF_BASE_SECONDS = 1.0


def _sleep(seconds: float) -> None:
    """Indirection so tests can assert the schedule without living through it."""
    time.sleep(seconds)


def _jitter() -> float:
    """Spread retries so concurrent workers do not re-collide in lockstep.

    Every worker that got rate-limited by the same window would otherwise wake
    at the same instant and rate-limit each other again.
    """
    return random.uniform(0, 0.5)


def _retry_after_seconds(response: Any) -> float | None:
    """The provider's own ``Retry-After``, in seconds, if it sent a usable one.

    The header is defined as either a count of seconds or an HTTP-date, and
    OpenRouter has used both. Anything unparseable returns ``None`` so the
    caller falls back to its own backoff rather than to zero.
    """
    raw = (getattr(response, "headers", None) or {}).get("retry-after")
    if not raw:
        return None

    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        logger.debug("Retry-After header %r is not a plain number, trying HTTP-date", raw)

    try:
        when = parsedate_to_datetime(str(raw))
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    try:
        if when.tzinfo is None:
            # An HTTP-date is UTC by definition, but parsedate_to_datetime
            # returns naive for the obsolete formats, and subtracting a naive
            # from an aware datetime raises.
            when = when.replace(tzinfo=UTC)
        # Clamped: a clock skewed the wrong way, or a slow hop, otherwise gives
        # a negative delay and time.sleep raises on those.
        return max(0.0, (when - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def is_configured() -> bool:
    """Whether an API key is present. Callers skip the round trip without one."""
    return bool(settings.openrouter_api_key)


def extract_json_object(raw: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model response, or ``None``.

    Tolerates markdown fences and surrounding prose — including a reasoning
    model's scratchpad, which is why asking for JSON is the reliable way to get
    structured data out of the free tier.
    """
    if not raw:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
        # The reply echoes the uploaded document, so a half-pair escape in it
        # is the document's, and would be stored on the invoice as written.
        # Inside the guard: from Python 3.13 json.loads no longer recurses, so
        # a deeply nested reply parses and the overflow moves into the
        # recursive encodable() walk — raised past this function on 3.14, where
        # 3.12 (production today) raised it from json.loads and was caught.
        return encodable(parsed) if isinstance(parsed, dict) else None
    except (ValueError, TypeError, RecursionError):
        return None


def image_data_url(content: bytes, content_type: str = "image/jpeg") -> str:
    """Encode image bytes as a data URL for the vision message format."""
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        # OpenRouter attributes free-tier usage to the referring app.
        "HTTP-Referer": settings.openrouter_app_url,
        "X-Title": settings.openrouter_app_title,
    }


def _message_text(choice: Any) -> str:
    if not isinstance(choice, dict):
        return ""
    message = choice.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, list):
        # Some models return content as a list of typed parts. Each part's
        # ``text`` is coerced rather than trusted: ``str.join`` raises
        # ``TypeError`` on a part carrying a number or a nested object there,
        # and ``TypeError`` is not :class:`OpenRouterError` — so it escapes
        # past the caller's fallback for exactly the reason the shape checks
        # above exist, and the invoice fails instead of degrading.
        content = "".join(
            str(part.get("text") or "") for part in content if isinstance(part, dict)
        )
    if content:
        return str(content).strip()
    # Reasoning models park the whole answer here when content comes back null.
    return str(message.get("reasoning") or "").strip()


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 1500,
    timeout: float | None = None,
) -> str:
    """Return the assistant's text for *messages*.

    ``messages`` follows the OpenAI chat format; a vision call passes a list of
    content parts instead of a string. Raises :class:`OpenRouterError` when no
    key is configured or the request fails — the caller's cue to fall back.
    """
    if not is_configured():
        raise OpenRouterError("OPENROUTER_API_KEY is not set")
    if not BREAKER.allow():
        raise OpenRouterError(
            "OpenRouter is unavailable; not calling it again until the breaker's "
            f"{BREAKER_COOLDOWN_SECONDS:.0f}s cooldown has passed"
        )

    payload = {
        "model": model or settings.openrouter_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    request_timeout = timeout or settings.openrouter_timeout_seconds

    # Guarded, so the breaker's probe is released however the call ends — an
    # exception neither path below reports would otherwise hold it, and every
    # call after would be refused until the process restarted.
    with BREAKER.guard():
        return _call_with_retries(url, payload, request_timeout)


def _call_with_retries(url: str, payload: dict[str, Any], request_timeout: float) -> str:
    """The attempts for one completion; see :func:`chat_completion`."""
    attempts = max(1, settings.openrouter_max_attempts)
    budget = settings.openrouter_retry_max_wait_seconds
    waited = 0.0
    started = time.perf_counter()
    # Only ever set from a *transient* failure, so raising it after the last
    # attempt reports the thing that actually kept failing rather than a
    # generic "gave up".
    last_error: OpenRouterError | None = None

    # No exit arc to cover: ``attempts`` is at least 1 and the last iteration
    # always leaves through ``break`` on ``attempt == attempts``, so the raise
    # below is reached that way and never by exhausting the range.
    deadline = started + settings.openrouter_call_budget_seconds
    for attempt in range(1, attempts + 1):  # pragma: no branch
        retry_after: float | None = None
        # Each attempt gets what is left of the call's budget, not a fresh
        # full timeout — see ``openrouter_call_budget_seconds``.
        remaining = deadline - time.perf_counter()
        try:
            response = httpx.post(
                url,
                headers=_headers(),
                json=payload,
                timeout=max(1.0, min(request_timeout, remaining)),
            )
        except httpx.TransportError as exc:
            # Connect, read, write and timeout errors — the network, not the
            # request. A different socket may well behave differently.
            last_error = OpenRouterError(f"OpenRouter request failed: {exc}")
            # Raised later, outside this handler, so the implicit chaining that
            # a bare `raise` would give is not available. Set explicitly:
            # without it the traceback says the request failed and not which
            # of connect, read or timeout did it.
            last_error.__cause__ = exc
        except httpx.HTTPError as exc:
            # Everything else httpx raises is about the request we built, and
            # rebuilding it identically would fail identically.
            BREAKER.succeeded()
            raise OpenRouterError(f"OpenRouter request failed: {exc}") from exc
        else:
            if response.status_code in _RETRYABLE_STATUS:
                last_error = OpenRouterError(
                    f"OpenRouter returned {response.status_code}: {response.text[:500]}"
                )
                retry_after = _retry_after_seconds(response)
            elif response.status_code >= 400:
                BREAKER.succeeded()
                raise OpenRouterError(
                    f"OpenRouter returned {response.status_code}: {response.text[:500]}"
                )
            else:
                # The one line a successful call leaves behind, and the only
                # place the model's latency is measured. The row records
                # ``parsed_with`` and a confidence, but not how long the
                # provider took or how many attempts it cost — which is what
                # distinguishes "the free tier is slow today" from "the model
                # is down" when uploads start taking a minute. Wall-clock over
                # the whole call, retries and their sleeps included, because
                # that is what the user waited.
                logger.info(
                    "OpenRouter call succeeded",
                    extra={
                        "model": payload["model"],
                        "attempt": attempt,
                        "attempts": attempts,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                )
                BREAKER.succeeded()
                return _completion_text(response)

        if attempt == attempts:
            break

        delay = retry_after if retry_after is not None else (
            _BACKOFF_BASE_SECONDS * 2 ** (attempt - 1) + _jitter()
        )
        if waited + delay > budget or time.perf_counter() + delay >= deadline - 1.0:
            # Sleeping the rest of the budget and retrying into a window that
            # is still closed helps nobody: the caller gets the same failure,
            # later. Falling back to heuristics now is the better answer.
            logger.warning(
                "OpenRouter retry would exceed the %ss budget, giving up after "
                "attempt %s of %s",
                budget,
                attempt,
                attempts,
                extra={
                    "model": payload["model"],
                    "attempt": attempt,
                    "attempts": attempts,
                    "waited_seconds": round(waited, 2),
                    "budget_seconds": budget,
                },
            )
            break

        logger.info(
            "OpenRouter attempt %s of %s failed, retrying in %.1fs: %s",
            attempt,
            attempts,
            delay,
            last_error,
            extra={"model": payload["model"], "attempt": attempt, "attempts": attempts},
        )
        _sleep(delay)
        waited += delay

    BREAKER.failed()
    raise last_error or OpenRouterError("OpenRouter request failed")


def _completion_text(response: Any) -> str:
    """The assistant's text out of a 2xx body, or an error saying why not.

    Separate from the retry loop because none of these failures is transient:
    a body that is not JSON, or has no choices, is a response the same request
    would get again.

    Shape is checked as well as syntax. A gateway or a misbehaving provider can
    answer 200 with valid JSON that is not an object — a bare list, a string, a
    ``null`` — and reaching for ``choices`` on it raised ``AttributeError``.
    Every caller here is written to catch :class:`OpenRouterError` and fall
    back to the heuristic extractor, so a failure that arrives under any other
    class does not degrade, it escapes: the invoice ends up ``failed`` with a
    stack trace instead of parsed by the regex reader that was standing by.
    """
    try:
        data = response.json()
    except ValueError as exc:
        raise OpenRouterError("OpenRouter returned a non-JSON body") from exc

    if not isinstance(data, dict):
        raise OpenRouterError(f"OpenRouter returned a non-object body: {str(data)[:300]}")

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OpenRouterError(f"OpenRouter returned no choices: {str(data)[:300]}")

    text = _message_text(choices[0])
    if not text:
        raise OpenRouterError("OpenRouter returned an empty completion")
    return text


def chat_json(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    max_tokens: int = 1500,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Run a completion and return the JSON object in it.

    Temperature is pinned to 0 — every JSON caller in this product is doing
    extraction, where the same invoice should give the same answer twice.
    """
    raw = chat_completion(
        messages, model=model, temperature=0.0, max_tokens=max_tokens, timeout=timeout
    )
    parsed = extract_json_object(raw)
    if parsed is None:
        raise OpenRouterError(f"No JSON object in model response: {raw[:300]}")
    return parsed
