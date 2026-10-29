"""The model client, and the free-tier misbehaviour it exists to absorb.

Every AI feature in the product goes through this module, and the reason it is
hand-rolled over httpx rather than an SDK is that the free tier does not keep
the contract an SDK assumes. Three things go wrong constantly and all three
must be survivable, because an invoice upload cannot fail just because a free
model was busy or chatty:

*   ``content`` comes back ``null`` with the real answer parked in
    ``reasoning``. Reading ``content`` alone gets ``None`` and a crash.
*   ``response_format`` is ignored, so JSON arrives wrapped in prose, a
    markdown fence, or a reasoning model's scratchpad.
*   The endpoint rate-limits, times out, or answers with an HTML error page.

Every failure here must arrive as OpenRouterError specifically, because that
is the exception every caller catches to fall back to the deterministic path.
An httpx exception escaping this module would take the upload down with it.

The transport is stubbed rather than dialled: what is under test is this
module's reading of a response, not httpx's ability to make a request.
"""
from __future__ import annotations

import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.core.config import settings
from app.services import openrouter_client
from app.services.openrouter_client import (
    OpenRouterError,
    chat_completion,
    chat_json,
    extract_json_object,
    image_data_url,
    is_configured,
)

MESSAGES = [{"role": "user", "content": "Read this invoice"}]

# Captured at import, before the autouse fixture below can stub it out — the
# only way for a test to assert anything about the real jitter.
_REAL_JITTER = openrouter_client._jitter
# Same reason, for the same fixture: every retry test replaces ``_sleep``, so
# this is the only reference left that still reaches its body.
_REAL_SLEEP = openrouter_client._sleep


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch):
    """Retries are scheduled, not slept through.

    Several tests below drive a 429 or a 502 to its last attempt. Left alone
    that is seconds of real backoff per test, which is how a suite stops being
    run. The delays themselves are asserted in TestRetries, against this list.
    """
    slept: list[float] = []
    monkeypatch.setattr(openrouter_client, "_sleep", slept.append)
    # Jitter exists to decorrelate real workers; in a test it only makes the
    # asserted schedule unpredictable.
    monkeypatch.setattr(openrouter_client, "_jitter", lambda: 0.0)
    return slept


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    return settings


@pytest.fixture()
def transport(monkeypatch):
    """Script the HTTP layer and capture what was sent to it."""
    calls: list[dict] = []
    state: dict = {"response": _FakeResponse(payload=_completion("ok")), "raises": None}

    def fake_post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        if state["raises"] is not None:
            raise state["raises"]
        return state["response"]

    monkeypatch.setattr(httpx, "post", fake_post)
    return {"calls": calls, "state": state}


def _completion(content, *, reasoning=None):
    message: dict = {"content": content}
    if reasoning is not None:
        message["reasoning"] = reasoning
    return {"choices": [{"message": message}]}


# --------------------------------------------------------------------------
# is_configured
# --------------------------------------------------------------------------

class TestIsConfigured:
    def test_true_with_a_key(self, monkeypatch):
        monkeypatch.setattr(settings, "openrouter_api_key", "sk-test")
        assert is_configured() is True

    @pytest.mark.parametrize("value", ["", None])
    def test_false_without_one(self, monkeypatch, value):
        monkeypatch.setattr(settings, "openrouter_api_key", value)
        assert is_configured() is False


# --------------------------------------------------------------------------
# extract_json_object
# --------------------------------------------------------------------------

class TestExtractJsonObject:
    def test_a_bare_object(self):
        assert extract_json_object('{"invoice_number": "INV-1"}') == {"invoice_number": "INV-1"}

    def test_a_fenced_object(self):
        raw = '```json\n{"invoice_number": "INV-1"}\n```'
        assert extract_json_object(raw) == {"invoice_number": "INV-1"}

    def test_an_unlabelled_fence(self):
        assert extract_json_object('```\n{"a": 1}\n```') == {"a": 1}

    def test_surrounding_prose_is_ignored(self):
        raw = 'Sure! Here is the data you asked for:\n{"a": 1}\nLet me know if you need more.'
        assert extract_json_object(raw) == {"a": 1}

    def test_a_reasoning_scratchpad_before_the_answer(self):
        # The shape that motivated this function: the model thinks out loud,
        # mentions braces in passing, then answers.
        raw = (
            "Let me work through this. The taxable value is 450000 and the rate "
            "is 18%, so IGST is 81000.\n\nFinal answer:\n"
            '{"taxable_value": 450000, "igst": 81000}'
        )
        assert extract_json_object(raw) == {"taxable_value": 450000, "igst": 81000}

    def test_nested_objects_survive(self):
        raw = '{"supplier": {"gstin": "29AAGCB7383J1Z4"}, "total": 531000}'
        assert extract_json_object(raw)["supplier"]["gstin"] == "29AAGCB7383J1Z4"

    def test_the_outermost_object_wins_when_prose_follows(self):
        # find("{") to rfind("}") spans the whole object, not the first brace
        # pair, which would truncate any nested structure.
        raw = 'Answer: {"a": {"b": 1}, "c": 2}'
        assert extract_json_object(raw) == {"a": {"b": 1}, "c": 2}

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "I could not read this invoice.",
            "{",
            "}{",
            "{not valid json at all}",
            '{"unterminated": ',
        ],
    )
    def test_unusable_responses_return_none(self, raw):
        assert extract_json_object(raw) is None

    def test_a_single_object_wrapped_in_an_array_is_unwrapped(self):
        # The brace scan reaches past the brackets, so a model that answers
        # with a one-element list still yields a usable invoice rather than a
        # failed extraction. Worth pinning: it is the scan's behaviour, not an
        # intention expressed anywhere in the code.
        assert extract_json_object('[{"a": 1}]') == {"a": 1}

    def test_an_array_of_several_objects_is_rejected(self):
        # Slicing first-brace to last-brace across two objects produces
        # something that is not valid JSON, so this fails closed rather than
        # silently returning one of two invoices.
        assert extract_json_object('[{"a": 1}, {"a": 2}]') is None

    def test_a_json_scalar_is_rejected(self):
        assert extract_json_object("42") is None

    def test_an_empty_object_is_returned_not_rejected(self):
        # Falsy but valid: "the model found nothing" is a real answer and is
        # different from "the model did not answer in JSON".
        assert extract_json_object("{}") == {}


# --------------------------------------------------------------------------
# image_data_url
# --------------------------------------------------------------------------

class TestAReplyThatCannotBeStoredAsWritten:
    def test_a_half_pair_escape_is_replaced_before_it_reaches_a_row(self):
        # The reply echoes the uploaded document; stored as written, the lone
        # surrogate broke every response that serialised the invoice.
        parsed = extract_json_object('{"invoice_number": "A\\ud800B", "items": ["\\udc00"]}')
        assert parsed == {"invoice_number": "A\ufffdB", "items": ["\ufffd"]}

    def test_a_reply_nested_past_the_recursion_limit_is_no_object(self):
        assert extract_json_object('{"a":' + "[" * 50_000 + "]" * 50_000 + "}") is None


class TestImageDataUrl:
    def test_builds_a_data_url(self):
        assert image_data_url(b"abc", "image/png") == "data:image/png;base64,YWJj"

    def test_defaults_to_jpeg(self):
        assert image_data_url(b"abc").startswith("data:image/jpeg;base64,")

    def test_empty_content_still_produces_a_url(self):
        assert image_data_url(b"") == "data:image/jpeg;base64,"

    def test_binary_content_is_ascii_safe(self):
        # The result goes into a JSON body; a raw byte would break encoding.
        url = image_data_url(bytes(range(256)), "image/webp")
        url.encode("ascii")


# --------------------------------------------------------------------------
# chat_completion — the request
# --------------------------------------------------------------------------

class TestChatCompletionRequest:
    def test_no_key_means_no_round_trip(self, monkeypatch, transport):
        monkeypatch.setattr(settings, "openrouter_api_key", "")
        with pytest.raises(OpenRouterError, match="OPENROUTER_API_KEY"):
            chat_completion(MESSAGES)
        assert transport["calls"] == [], "asked the network without a key"

    def test_the_key_is_sent_as_a_bearer_token(self, configured, transport):
        chat_completion(MESSAGES)
        assert transport["calls"][0]["headers"]["Authorization"] == "Bearer test-key"

    def test_attribution_headers_are_sent(self, configured, transport):
        # OpenRouter attributes free-tier usage to these; without them the
        # quota is charged to nobody and the request can be refused.
        chat_completion(MESSAGES)
        headers = transport["calls"][0]["headers"]
        assert headers["HTTP-Referer"] == settings.openrouter_app_url
        assert headers["X-Title"] == settings.openrouter_app_title

    def test_the_configured_model_is_used_by_default(self, configured, transport):
        chat_completion(MESSAGES)
        assert transport["calls"][0]["json"]["model"] == settings.openrouter_model

    def test_an_explicit_model_overrides_the_default(self, configured, transport):
        chat_completion(MESSAGES, model="anthropic/claude-3-haiku")
        assert transport["calls"][0]["json"]["model"] == "anthropic/claude-3-haiku"

    def test_the_url_is_built_without_a_double_slash(self, configured, transport, monkeypatch):
        monkeypatch.setattr(settings, "openrouter_base_url", "https://example.test/api/")
        chat_completion(MESSAGES)
        assert transport["calls"][0]["url"] == "https://example.test/api/chat/completions"

    def test_temperature_and_max_tokens_are_passed_through(self, configured, transport):
        chat_completion(MESSAGES, temperature=0.7, max_tokens=42)
        body = transport["calls"][0]["json"]
        assert body["temperature"] == 0.7
        assert body["max_tokens"] == 42

    def test_the_configured_timeout_is_applied(self, configured, transport, monkeypatch):
        # When the call's budget has room for it — see TestTheCallBudget for
        # the attempt that is given only what is left.
        monkeypatch.setattr(settings, "openrouter_call_budget_seconds", 600.0)
        chat_completion(MESSAGES)
        assert transport["calls"][0]["timeout"] == settings.openrouter_timeout_seconds

    def test_an_explicit_timeout_overrides_it(self, configured, transport):
        chat_completion(MESSAGES, timeout=3.5)
        assert transport["calls"][0]["timeout"] == 3.5

    def test_the_messages_are_sent_verbatim(self, configured, transport):
        # A vision call passes a list of content parts; nothing here may
        # reshape it.
        vision = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        chat_completion(vision)
        assert transport["calls"][0]["json"]["messages"] == vision


# --------------------------------------------------------------------------
# chat_completion — reading the response
# --------------------------------------------------------------------------

class TestChatCompletionResponse:
    def test_returns_the_message_content(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(payload=_completion("  the answer  "))
        assert chat_completion(MESSAGES) == "the answer"

    def test_falls_back_to_reasoning_when_content_is_null(self, configured, transport):
        # gpt-oss-20b:free does this constantly. Reading content alone yields
        # None and the upload dies on a free-tier quirk.
        transport["state"]["response"] = _FakeResponse(
            payload=_completion(None, reasoning="the real answer")
        )
        assert chat_completion(MESSAGES) == "the real answer"

    def test_content_wins_over_reasoning_when_both_are_present(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(
            payload=_completion("the answer", reasoning="scratchpad")
        )
        assert chat_completion(MESSAGES) == "the answer"

    def test_content_delivered_as_typed_parts_is_joined(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(
            payload=_completion(
                [{"type": "text", "text": "part one "}, {"type": "text", "text": "part two"}]
            )
        )
        assert chat_completion(MESSAGES) == "part one part two"

    def test_non_dict_entries_in_a_part_list_are_skipped(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(
            payload=_completion([{"type": "text", "text": "kept"}, "dropped", None])
        )
        assert chat_completion(MESSAGES) == "kept"

    @pytest.mark.parametrize("status", [400, 401, 402, 429, 500, 502, 503])
    def test_an_error_status_becomes_an_openrouter_error(self, configured, transport, status):
        transport["state"]["response"] = _FakeResponse(
            status_code=status, payload={"error": "nope"}
        )
        with pytest.raises(OpenRouterError, match=str(status)):
            chat_completion(MESSAGES)

    def test_an_error_body_is_truncated_in_the_message(self, configured, transport):
        # An HTML error page is a plausible 502 body; the whole page must not
        # end up in the logs on every failed upload.
        transport["state"]["response"] = _FakeResponse(status_code=502, text="x" * 5000)
        with pytest.raises(OpenRouterError) as caught:
            chat_completion(MESSAGES)
        assert len(str(caught.value)) < 600

    def test_a_non_json_body_becomes_an_openrouter_error(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(payload=None, text="<html>502</html>")
        with pytest.raises(OpenRouterError, match="non-JSON"):
            chat_completion(MESSAGES)

    @pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": None}])
    def test_no_choices_becomes_an_openrouter_error(self, configured, transport, payload):
        transport["state"]["response"] = _FakeResponse(payload=payload)
        with pytest.raises(OpenRouterError, match="no choices"):
            chat_completion(MESSAGES)

    @pytest.mark.parametrize(
        "payload",
        [
            {"choices": [{"message": {"content": ""}}]},
            {"choices": [{"message": {"content": None}}]},
            {"choices": [{"message": {"content": None, "reasoning": None}}]},
            {"choices": [{"message": {"content": "   "}}]},
            {"choices": [{"message": {}}]},
            {"choices": [{}]},
        ],
    )
    def test_an_empty_completion_becomes_an_openrouter_error(
        self, configured, transport, payload
    ):
        transport["state"]["response"] = _FakeResponse(payload=payload)
        with pytest.raises(OpenRouterError, match="empty completion"):
            chat_completion(MESSAGES)

    @pytest.mark.parametrize(
        "error",
        [
            httpx.ConnectError("connection refused"),
            httpx.ReadTimeout("timed out"),
            httpx.ConnectTimeout("timed out connecting"),
            httpx.RemoteProtocolError("server disconnected"),
        ],
    )
    def test_every_transport_failure_becomes_an_openrouter_error(
        self, configured, transport, error
    ):
        # The contract the whole fallback chain rests on: callers catch
        # OpenRouterError, so an httpx exception escaping here would take the
        # upload down instead of falling back to heuristics.
        transport["state"]["raises"] = error
        with pytest.raises(OpenRouterError, match="request failed"):
            chat_completion(MESSAGES)

    def test_the_original_error_is_chained(self, configured, transport):
        transport["state"]["raises"] = httpx.ReadTimeout("timed out")
        with pytest.raises(OpenRouterError) as caught:
            chat_completion(MESSAGES)
        assert isinstance(caught.value.__cause__, httpx.ReadTimeout)


# --------------------------------------------------------------------------
# Retries
# --------------------------------------------------------------------------

class TestRetries:
    """The free tier rate-limits as a matter of course, and the caller's
    alternative to a completion is regex heuristics over the invoice.

    That makes a 429 worth asking again — the window it refers to has usually
    refilled — and makes a 401 worth failing immediately, because the answer is
    the same however many times it is asked and the caller is waiting.
    """

    @pytest.fixture()
    def scripted(self, monkeypatch):
        """A transport that plays a sequence: each entry a response or a raise."""
        calls: list[dict] = []
        queue: list = []

        def fake_post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            item = queue.pop(0) if queue else _FakeResponse(payload=_completion("ok"))
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(httpx, "post", fake_post)
        return {"calls": calls, "queue": queue}

    def test_a_rate_limit_is_retried_rather_than_fallen_back_from(
        self, configured, scripted
    ):
        # The whole point. Without this the invoice is parsed by regex because
        # the provider was busy for a second.
        scripted["queue"].append(_FakeResponse(status_code=429, payload={"error": "slow down"}))

        assert chat_completion(MESSAGES) == "ok"
        assert len(scripted["calls"]) == 2

    @pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
    def test_every_transient_status_is_retried(self, configured, scripted, status):
        scripted["queue"].append(_FakeResponse(status_code=status, payload={"error": "x"}))

        assert chat_completion(MESSAGES) == "ok"
        assert len(scripted["calls"]) == 2

    @pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
    def test_a_client_error_is_not_retried(self, configured, scripted, status):
        # A missing key or a malformed request fails the same way twice. Asking
        # again turns a fast, clear error into a slow one, and on a metered
        # endpoint it is a second charge for the same mistake.
        scripted["queue"].append(_FakeResponse(status_code=status, payload={"error": "x"}))

        with pytest.raises(OpenRouterError, match=str(status)):
            chat_completion(MESSAGES)
        assert len(scripted["calls"]) == 1

    def test_a_network_error_is_retried(self, configured, scripted):
        scripted["queue"].append(httpx.ConnectError("refused"))

        assert chat_completion(MESSAGES) == "ok"
        assert len(scripted["calls"]) == 2

    def test_a_timeout_is_retried(self, configured, scripted):
        scripted["queue"].append(httpx.ReadTimeout("timed out"))

        assert chat_completion(MESSAGES) == "ok"
        assert len(scripted["calls"]) == 2

    def test_attempts_are_bounded(self, configured, scripted, monkeypatch):
        monkeypatch.setattr(settings, "openrouter_max_attempts", 3)
        scripted["queue"].extend(
            _FakeResponse(status_code=429, payload={"error": "x"}) for _ in range(10)
        )

        with pytest.raises(OpenRouterError, match="429"):
            chat_completion(MESSAGES)
        assert len(scripted["calls"]) == 3

    def test_one_attempt_disables_retrying(self, configured, scripted, monkeypatch):
        # The escape hatch for a deployment that would rather fail fast.
        monkeypatch.setattr(settings, "openrouter_max_attempts", 1)
        scripted["queue"].append(_FakeResponse(status_code=429, payload={"error": "x"}))

        with pytest.raises(OpenRouterError, match="429"):
            chat_completion(MESSAGES)
        assert len(scripted["calls"]) == 1

    def test_the_error_raised_is_the_one_that_kept_happening(self, configured, scripted):
        # Not a generic "gave up": the operator needs to see the 503.
        scripted["queue"].extend(
            _FakeResponse(status_code=503, text="upstream down") for _ in range(5)
        )

        with pytest.raises(OpenRouterError, match="503"):
            chat_completion(MESSAGES)

    def test_a_network_failure_still_chains_its_cause(self, configured, scripted):
        # Raised after the loop rather than inside the handler, so the chaining
        # has to be explicit — otherwise the traceback loses which error it was.
        scripted["queue"].extend(httpx.ConnectError("refused") for _ in range(5))

        with pytest.raises(OpenRouterError) as caught:
            chat_completion(MESSAGES)
        assert isinstance(caught.value.__cause__, httpx.ConnectError)

    def test_the_backoff_doubles(self, configured, scripted, monkeypatch, no_real_sleeping):
        monkeypatch.setattr(settings, "openrouter_max_attempts", 4)
        scripted["queue"].extend(
            _FakeResponse(status_code=429, payload={"error": "x"}) for _ in range(10)
        )

        with pytest.raises(OpenRouterError):
            chat_completion(MESSAGES)
        # Jitter is stubbed to zero by the autouse fixture.
        assert no_real_sleeping == [1.0, 2.0, 4.0]

    def test_jitter_is_added_so_workers_do_not_re_collide(
        self, configured, scripted, monkeypatch, no_real_sleeping
    ):
        # Every worker throttled by the same window would otherwise wake at the
        # same instant and throttle each other again.
        monkeypatch.setattr(openrouter_client, "_jitter", lambda: 0.25)
        scripted["queue"].append(_FakeResponse(status_code=429, payload={"error": "x"}))

        chat_completion(MESSAGES)
        assert no_real_sleeping == [1.25]

    def test_jitter_stays_within_a_fraction_of_a_second(self):
        # It decorrelates retries; it is not a second backoff. A jitter that
        # can exceed the base delay makes the schedule unpredictable.
        #
        # Against _REAL_JITTER, not openrouter_client._jitter: the autouse
        # fixture has replaced the module attribute with a stub, so reading it
        # here would assert that 0.0 is between 0 and 0.5 — a test that passes
        # whatever the real function does.
        assert all(0 <= _REAL_JITTER() <= 0.5 for _ in range(200))

    def test_an_httpx_error_that_is_not_a_transport_error_is_not_retried(
        self, configured, scripted
    ):
        # httpx.HTTPError splits into RequestError (the network — retryable)
        # and HTTPStatusError (a response we already have). Retrying the latter
        # would rebuild an identical request and get an identical answer.
        failure = httpx.HTTPStatusError(
            "boom",
            request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            response=httpx.Response(400),
        )
        scripted["queue"].extend(failure for _ in range(5))

        with pytest.raises(OpenRouterError, match="request failed"):
            chat_completion(MESSAGES)
        assert len(scripted["calls"]) == 1


class TestRetryAfter:
    """The provider's own number beats a guess.

    Guessing shorter re-enters a window that has not refilled, which spends the
    next window's budget on a request that was always going to be refused.
    """

    @pytest.fixture()
    def scripted(self, monkeypatch):
        calls: list[dict] = []
        queue: list = []

        def fake_post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            item = queue.pop(0) if queue else _FakeResponse(payload=_completion("ok"))
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(httpx, "post", fake_post)
        return {"calls": calls, "queue": queue}

    def test_it_is_honoured_over_the_backoff(self, configured, scripted, no_real_sleeping):
        scripted["queue"].append(
            _FakeResponse(status_code=429, payload={"error": "x"}, headers={"retry-after": "7"})
        )

        assert chat_completion(MESSAGES) == "ok"
        assert no_real_sleeping == [7.0], "used its own backoff instead of the provider's"

    def test_a_fractional_value_is_kept(self, configured, scripted, no_real_sleeping):
        scripted["queue"].append(
            _FakeResponse(status_code=429, payload={"error": "x"}, headers={"retry-after": "1.5"})
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping == [1.5]

    def test_no_jitter_is_added_to_an_explicit_wait(
        self, configured, scripted, monkeypatch, no_real_sleeping
    ):
        # The provider said when; moving it is second-guessing a real answer.
        monkeypatch.setattr(openrouter_client, "_jitter", lambda: 0.4)
        scripted["queue"].append(
            _FakeResponse(status_code=429, payload={"error": "x"}, headers={"retry-after": "3"})
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping == [3.0]

    def test_an_http_date_is_understood(self, configured, scripted, no_real_sleeping):
        # The header is defined as seconds *or* an HTTP-date, and OpenRouter
        # has sent both. An unparsed date would fall back to the backoff.
        when = datetime.now(UTC) + timedelta(seconds=12)
        scripted["queue"].append(
            _FakeResponse(
                status_code=429,
                payload={"error": "x"},
                headers={"retry-after": format_datetime(when, usegmt=True)},
            )
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping and 10 <= no_real_sleeping[0] <= 13

    def test_a_date_in_the_past_is_not_a_negative_sleep(
        self, configured, scripted, no_real_sleeping
    ):
        # A clock skewed the wrong way, or a slow hop. time.sleep would raise.
        when = datetime.now(UTC) - timedelta(seconds=60)
        scripted["queue"].append(
            _FakeResponse(
                status_code=429,
                payload={"error": "x"},
                headers={"retry-after": format_datetime(when, usegmt=True)},
            )
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping == [0.0]

    def test_a_negative_number_is_not_a_negative_sleep(
        self, configured, scripted, no_real_sleeping
    ):
        scripted["queue"].append(
            _FakeResponse(status_code=429, payload={"error": "x"}, headers={"retry-after": "-5"})
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping == [0.0]

    @pytest.mark.parametrize("value", ["soon", "", "   ", "NaN-ish"])
    def test_an_unparseable_value_falls_back_to_the_backoff(
        self, configured, scripted, no_real_sleeping, value
    ):
        # Falling back to zero here would hammer a provider that just asked to
        # be left alone.
        scripted["queue"].append(
            _FakeResponse(status_code=429, payload={"error": "x"}, headers={"retry-after": value})
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping == [1.0]

    def test_a_response_without_headers_is_survived(self, configured, scripted):
        # httpx always has .headers; a stub in a caller's test may not.
        scripted["queue"].append(_FakeResponse(status_code=429, payload={"error": "x"}))

        assert chat_completion(MESSAGES) == "ok"

    def test_a_date_in_the_obsolete_asctime_format_is_read_as_utc(
        self, configured, scripted, no_real_sleeping
    ):
        # HTTP-date has three legal spellings and `parsedate_to_datetime`
        # returns *naive* for the asctime one — the other two carry GMT and
        # come back aware. Subtracting a naive from an aware datetime raises
        # TypeError, so without the UTC stamp this whole branch would fall
        # through to the backoff and quietly ignore a provider that had
        # answered precisely.
        when = datetime.now(UTC) + timedelta(seconds=12)
        # asctime: "Sun Nov  6 08:49:37 1994", no zone at the end.
        asctime = when.strftime("%a %b %d %H:%M:%S %Y")
        scripted["queue"].append(
            _FakeResponse(
                status_code=429, payload={"error": "x"}, headers={"retry-after": asctime}
            )
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping, "fell back to the backoff instead of reading the date"
        assert 10 <= no_real_sleeping[0] <= 13

    def test_an_obsolete_format_date_in_the_past_is_not_a_negative_sleep(
        self, configured, scripted, no_real_sleeping
    ):
        # The naive branch has to clamp for the same reason the aware one does.
        when = datetime.now(UTC) - timedelta(seconds=60)
        scripted["queue"].append(
            _FakeResponse(
                status_code=429,
                payload={"error": "x"},
                headers={"retry-after": when.strftime("%a %b %d %H:%M:%S %Y")},
            )
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping == [0.0]

    def test_a_date_that_parses_to_nothing_falls_back_to_the_backoff(
        self, configured, scripted, monkeypatch, no_real_sleeping
    ):
        # `parsedate_to_datetime` raises on bad input in current Python and
        # returned None in older ones. The guard stays because the fallback
        # this protects is the difference between waiting and hammering: a
        # `None` reaching the arithmetic below would be a TypeError inside the
        # retry path, not a graceful backoff.
        monkeypatch.setattr(openrouter_client, "parsedate_to_datetime", lambda raw: None)
        scripted["queue"].append(
            _FakeResponse(
                status_code=429,
                payload={"error": "x"},
                headers={"retry-after": "Sun, 06 Nov 1994 08:49:37 GMT"},
            )
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping == [1.0], "did not fall back to its own backoff"

    def test_a_date_too_far_out_to_subtract_falls_back_to_the_backoff(
        self, configured, scripted, monkeypatch, no_real_sleeping
    ):
        # A year that overflows the subtraction. Falling back to zero here
        # would hammer a provider that had just asked to be left alone, which
        # is the one outcome this function must never produce.
        class _Overflowing:
            tzinfo = UTC

            def __sub__(self, other):
                raise OverflowError("date value out of range")

        monkeypatch.setattr(
            openrouter_client, "parsedate_to_datetime", lambda raw: _Overflowing()
        )
        scripted["queue"].append(
            _FakeResponse(
                status_code=429,
                payload={"error": "x"},
                headers={"retry-after": "Sun, 06 Nov 9999 08:49:37 GMT"},
            )
        )

        chat_completion(MESSAGES)
        assert no_real_sleeping == [1.0]


class TestTheWaitingBudget:
    """Extraction runs inline in the upload request when Celery is off, so time
    spent between attempts is time a user is sitting through."""

    @pytest.fixture()
    def scripted(self, monkeypatch):
        calls: list[dict] = []
        queue: list = []

        def fake_post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            item = queue.pop(0) if queue else _FakeResponse(payload=_completion("ok"))
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(httpx, "post", fake_post)
        return {"calls": calls, "queue": queue}

    def test_a_retry_that_would_exceed_it_is_not_taken(
        self, configured, scripted, monkeypatch, no_real_sleeping
    ):
        monkeypatch.setattr(settings, "openrouter_retry_max_wait_seconds", 5.0)
        scripted["queue"].append(
            _FakeResponse(status_code=429, payload={"error": "x"}, headers={"retry-after": "600"})
        )

        with pytest.raises(OpenRouterError, match="429"):
            chat_completion(MESSAGES)
        assert no_real_sleeping == [], "slept past the budget"
        assert len(scripted["calls"]) == 1

    def test_it_is_a_total_not_a_per_wait_limit(
        self, configured, scripted, monkeypatch, no_real_sleeping
    ):
        # 1s then 2s is 3s; the third wait of 4s crosses a 5s budget.
        monkeypatch.setattr(settings, "openrouter_max_attempts", 6)
        monkeypatch.setattr(settings, "openrouter_retry_max_wait_seconds", 5.0)
        scripted["queue"].extend(
            _FakeResponse(status_code=503, payload={"error": "x"}) for _ in range(10)
        )

        with pytest.raises(OpenRouterError):
            chat_completion(MESSAGES)
        assert no_real_sleeping == [1.0, 2.0]
        assert sum(no_real_sleeping) <= 5.0

    def test_giving_up_early_is_logged(self, configured, scripted, monkeypatch, caplog):
        # Otherwise "it fell back to heuristics" and "it was throttled for
        # longer than we were willing to wait" look identical afterwards.
        monkeypatch.setattr(settings, "openrouter_retry_max_wait_seconds", 0.0)
        scripted["queue"].append(_FakeResponse(status_code=429, payload={"error": "x"}))

        with caplog.at_level(logging.WARNING), pytest.raises(OpenRouterError):
            chat_completion(MESSAGES)
        assert "budget" in caplog.text


# --------------------------------------------------------------------------
# what a call that worked leaves behind
# --------------------------------------------------------------------------

class TestTheCallBudget:
    """The whole call — attempts as well as waits — fits a wall-clock budget.

    Three 90s timeouts and their backoff were five minutes, and a parse can
    make two calls. Celery's soft limit cut the task at 180s by raising inside
    the call, which is not an ``OpenRouterError``, so the heuristic fallback was
    skipped and a slow provider turned invoices into failures.
    """

    @pytest.fixture()
    def clock(self, monkeypatch):
        now = {"t": 1000.0}
        fake_time = type("T", (), {"perf_counter": staticmethod(lambda: now["t"])})
        monkeypatch.setattr(openrouter_client, "time", fake_time)
        return now

    @pytest.fixture()
    def slow_provider(self, monkeypatch, clock):
        """Every request hangs for its whole timeout and then fails to read."""
        calls: list[dict] = []

        def fake_post(url, **kwargs):
            calls.append(kwargs)
            clock["t"] += kwargs["timeout"]
            raise httpx.ReadTimeout("read timed out")

        monkeypatch.setattr(httpx, "post", fake_post)
        return calls

    def test_a_slow_provider_is_given_up_on_within_the_budget(
        self, configured, slow_provider, clock, monkeypatch
    ):
        monkeypatch.setattr(settings, "openrouter_call_budget_seconds", 80.0)
        started = clock["t"]
        with pytest.raises(OpenRouterError, match="timed out"):
            chat_completion(MESSAGES)
        assert clock["t"] - started <= 80.0
        assert len(slow_provider) == 1, "retried into a budget that was already spent"

    def test_each_attempt_is_given_only_what_is_left(
        self, configured, slow_provider, monkeypatch
    ):
        monkeypatch.setattr(settings, "openrouter_timeout_seconds", 30.0)
        monkeypatch.setattr(settings, "openrouter_call_budget_seconds", 80.0)
        with pytest.raises(OpenRouterError):
            chat_completion(MESSAGES)
        timeouts = [c["timeout"] for c in slow_provider]
        assert timeouts[0] == 30.0
        assert sum(timeouts) <= 80.0

    def test_two_calls_fit_inside_the_parse_task_soft_limit(self):
        # A scanned invoice is a vision call, then OCR, then a text call. Both
        # must end as an ``OpenRouterError`` the parser falls back from, before
        # Celery raises its own exception inside the second one.
        from app.celery_app import celery_app

        soft_limit = celery_app.conf.task_soft_time_limit
        assert 2 * settings.openrouter_call_budget_seconds < soft_limit


class TestASuccessfulCallIsMeasured:
    """The only place the provider's latency is measured.

    The row records ``parsed_with`` and a confidence, not how long the model
    took or how many attempts it cost — and that is what tells "the free tier
    is slow today" from "the model is down" once uploads start taking a
    minute. Until GB003 a call that worked logged nothing at all.
    """

    @pytest.fixture()
    def scripted(self, monkeypatch):
        calls: list[dict] = []
        queue: list = []

        def fake_post(url, **kwargs):
            calls.append({"url": url, **kwargs})
            item = queue.pop(0) if queue else _FakeResponse(payload=_completion("ok"))
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(httpx, "post", fake_post)
        return {"calls": calls, "queue": queue}

    @staticmethod
    def _line(caplog):
        return next(
            record for record in caplog.records
            if record.name == "app.services.openrouter_client"
            and record.getMessage() == "OpenRouter call succeeded"
        )

    def test_the_model_and_the_latency_are_on_the_line(self, configured, transport, caplog):
        with caplog.at_level(logging.INFO):
            chat_completion(MESSAGES, model="vendor/some-model")

        line = self._line(caplog)
        assert line.model == "vendor/some-model"
        assert isinstance(line.latency_ms, float)
        assert line.latency_ms >= 0

    def test_the_default_model_is_named_rather_than_left_blank(
        self, configured, transport, caplog
    ):
        with caplog.at_level(logging.INFO):
            chat_completion(MESSAGES)
        assert self._line(caplog).model == settings.openrouter_model

    def test_a_call_that_needed_a_retry_says_so(self, configured, scripted, caplog):
        # ``attempt`` is what turns a latency figure into a diagnosis: two
        # attempts at 30s each is throttling, one attempt at 60s is a slow
        # model.
        scripted["queue"].append(_FakeResponse(status_code=429, payload={"error": "x"}))

        with caplog.at_level(logging.INFO):
            chat_completion(MESSAGES)

        line = self._line(caplog)
        assert line.attempt == 2
        assert line.attempts == settings.openrouter_max_attempts

    def test_a_call_that_failed_leaves_no_success_line(self, configured, transport, caplog):
        transport["state"]["response"] = _FakeResponse(status_code=401, payload={"error": "x"})
        with caplog.at_level(logging.INFO), pytest.raises(OpenRouterError):
            chat_completion(MESSAGES)
        with pytest.raises(StopIteration):
            self._line(caplog)


# --------------------------------------------------------------------------
# chat_json
# --------------------------------------------------------------------------

class TestChatJson:
    def test_returns_the_parsed_object(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(payload=_completion('{"a": 1}'))
        assert chat_json(MESSAGES) == {"a": 1}

    def test_digs_the_object_out_of_a_fence(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(
            payload=_completion('```json\n{"a": 1}\n```')
        )
        assert chat_json(MESSAGES) == {"a": 1}

    def test_reads_json_out_of_the_reasoning_field(self, configured, transport):
        # Both quirks at once, which is the common case for the free tier.
        transport["state"]["response"] = _FakeResponse(
            payload=_completion(None, reasoning='thinking...\n{"a": 1}')
        )
        assert chat_json(MESSAGES) == {"a": 1}

    def test_temperature_is_pinned_to_zero(self, configured, transport):
        # Extraction must be reproducible: the same invoice twice should not
        # produce two different taxable values.
        transport["state"]["response"] = _FakeResponse(payload=_completion('{"a": 1}'))
        chat_json(MESSAGES)
        assert transport["calls"][0]["json"]["temperature"] == 0.0

    def test_a_prose_answer_becomes_an_openrouter_error(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(
            payload=_completion("I'm sorry, I can't read that invoice.")
        )
        with pytest.raises(OpenRouterError, match="No JSON object"):
            chat_json(MESSAGES)

    def test_the_failing_response_is_quoted_but_truncated(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(payload=_completion("no json " * 500))
        with pytest.raises(OpenRouterError) as caught:
            chat_json(MESSAGES)
        assert len(str(caught.value)) < 400

    def test_a_transport_failure_propagates_as_openrouter_error(self, configured, transport):
        transport["state"]["raises"] = httpx.ConnectError("refused")
        with pytest.raises(OpenRouterError):
            chat_json(MESSAGES)

    def test_options_are_forwarded(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(payload=_completion('{"a": 1}'))
        chat_json(MESSAGES, model="some/model", max_tokens=99, timeout=2.0)
        call = transport["calls"][0]
        assert call["json"]["model"] == "some/model"
        assert call["json"]["max_tokens"] == 99
        assert call["timeout"] == 2.0


class TestEveryFailureIsCatchable:
    """One sweep over the whole surface: nothing escapes as another type."""

    @pytest.mark.parametrize(
        "setup",
        [
            {"raises": httpx.ConnectError("refused")},
            {"response": _FakeResponse(status_code=429, payload={"error": "rate limited"})},
            {"response": _FakeResponse(payload=None, text="<html>")},
            {"response": _FakeResponse(payload={"choices": []})},
            {"response": _FakeResponse(payload=_completion(""))},
            {"response": _FakeResponse(payload=_completion("not json"))},
        ],
    )
    def test_chat_json_raises_only_openrouter_error(self, configured, transport, setup):
        transport["state"].update(setup)
        with pytest.raises(OpenRouterError):
            chat_json(MESSAGES)

    def test_openrouter_error_is_a_runtime_error(self):
        # Callers written against RuntimeError still catch it.
        assert issubclass(OpenRouterError, RuntimeError)

    def test_the_module_exposes_what_callers_import(self):
        for name in ("is_configured", "chat_completion", "chat_json", "OpenRouterError"):
            assert hasattr(openrouter_client, name)


# --------------------------------------------------------------------------
# Bodies that are JSON, and still not a completion
# --------------------------------------------------------------------------

class TestABodyOfTheWrongShape:
    """200 OK, valid JSON, and nothing where the completion should be.

    A gateway in front of the free tier, or a provider having a bad day,
    answers with a bare list, a quoted string, or `null` — all of them valid
    JSON, none of them an object with `choices` in it. Reaching for `choices`
    on those raised `AttributeError`, and that is the one thing this module
    must never emit: every caller catches `OpenRouterError` to fall back to the
    deterministic extractor, so an exception of any other class does not
    degrade the upload, it fails it. The invoice lands in the error queue with
    a stack trace while the regex reader that would have read it stood by.
    """

    @pytest.mark.parametrize(
        "payload",
        [[], [{"message": {"content": "hi"}}], "a string", 7, 1.5, True],
        ids=["empty-list", "list-of-choices", "string", "int", "float", "bool"],
    )
    def test_a_body_that_is_not_an_object_is_an_openrouter_error(
        self, configured, transport, payload
    ):
        transport["state"]["response"] = _FakeResponse(payload=payload)
        with pytest.raises(OpenRouterError):
            chat_completion(MESSAGES)

    @pytest.mark.parametrize(
        "choices",
        [5, "abc", {"message": {"content": "hi"}}],
        ids=["int", "string", "object"],
    )
    def test_choices_that_is_not_a_list_is_an_openrouter_error(
        self, configured, transport, choices
    ):
        transport["state"]["response"] = _FakeResponse(payload={"choices": choices})
        with pytest.raises(OpenRouterError):
            chat_completion(MESSAGES)

    @pytest.mark.parametrize("choice", [5, "abc", None, [1, 2]])
    def test_a_choice_that_is_not_an_object_is_an_openrouter_error(
        self, configured, transport, choice
    ):
        transport["state"]["response"] = _FakeResponse(payload={"choices": [choice]})
        with pytest.raises(OpenRouterError):
            chat_completion(MESSAGES)

    @pytest.mark.parametrize("message", [5, "abc", None, [1, 2]])
    def test_a_message_that_is_not_an_object_is_an_openrouter_error(
        self, configured, transport, message
    ):
        transport["state"]["response"] = _FakeResponse(payload={"choices": [{"message": message}]})
        with pytest.raises(OpenRouterError):
            chat_completion(MESSAGES)

    def test_the_error_says_what_came_back(self, configured, transport):
        # The body is what tells whoever reads the log whether this was the
        # provider or a proxy in the way, so it belongs in the message.
        transport["state"]["response"] = _FakeResponse(payload=["nope"])
        with pytest.raises(OpenRouterError, match="nope"):
            chat_completion(MESSAGES)

    def test_a_wrong_shape_reaches_chat_json_as_an_openrouter_error_too(
        self, configured, transport
    ):
        # chat_json is what the invoice extractor actually calls.
        transport["state"]["response"] = _FakeResponse(payload=[])
        with pytest.raises(OpenRouterError):
            chat_json(MESSAGES)

    def test_a_well_formed_body_still_reads(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(payload=_completion("ok"))
        assert chat_completion(MESSAGES) == "ok"


class TestAContentPartThatIsNotText:
    """A list-shaped ``content`` whose parts do not hold strings.

    The typed-part format is the one place this module joins values it did not
    coerce, and ``str.join`` raises ``TypeError`` on anything that is not a
    string. A part carrying a number, a null or a nested object therefore left
    by a class no caller catches — the same escape the object-shape checks
    above exist to close, one level further in — and the upload failed where it
    should have fallen back to the regex reader.

    Coerced rather than skipped: a model that answered ``{"text": 42}`` said
    42, and dropping it would turn a readable completion into an empty one,
    which is a different error with the same result.
    """

    @pytest.mark.parametrize(
        "part",
        [{"text": 5}, {"text": 1.5}, {"text": True}, {"text": {"a": 1}}, {"text": [1]}],
        ids=["int", "float", "bool", "object", "list"],
    )
    def test_a_part_whose_text_is_not_a_string_does_not_raise_typeerror(
        self, configured, transport, part
    ):
        transport["state"]["response"] = _FakeResponse(
            payload={"choices": [{"message": {"content": [part]}}]}
        )
        # Whatever it makes of it, it must be a string or an OpenRouterError —
        # never TypeError, which is what escapes the caller's fallback.
        with contextlib.suppress(OpenRouterError):
            assert isinstance(chat_completion(MESSAGES), str)

    def test_the_number_in_the_part_is_read_rather_than_dropped(
        self, configured, transport
    ):
        transport["state"]["response"] = _FakeResponse(
            payload={"choices": [{"message": {"content": [{"text": 42}]}}]}
        )
        assert chat_completion(MESSAGES) == "42"

    def test_a_part_with_no_text_at_all_contributes_nothing(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(
            payload={"choices": [{"message": {"content": [{"type": "image"}, {"text": "hi"}]}}]}
        )
        assert chat_completion(MESSAGES) == "hi"

    def test_a_null_text_contributes_nothing(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(
            payload={"choices": [{"message": {"content": [{"text": None}, {"text": "hi"}]}}]}
        )
        assert chat_completion(MESSAGES) == "hi"

    def test_ordinary_typed_parts_still_concatenate(self, configured, transport):
        transport["state"]["response"] = _FakeResponse(
            payload={
                "choices": [
                    {"message": {"content": [{"text": "one "}, {"text": "two"}]}}
                ]
            }
        )
        assert chat_completion(MESSAGES) == "one two"

    def test_a_bad_part_reaches_chat_json_without_a_typeerror_either(
        self, configured, transport
    ):
        # chat_json is what the invoice extractor calls, and it is the caller
        # whose fallback the escaping TypeError was skipping past.
        transport["state"]["response"] = _FakeResponse(
            payload={"choices": [{"message": {"content": [{"text": 5}]}}]}
        )
        with pytest.raises(OpenRouterError):
            chat_json(MESSAGES)


def test_the_backoff_sleep_is_a_real_sleep():
    """Every retry test replaces ``_sleep``, so nothing else runs its body.

    The indirection exists so the schedule can be asserted without waiting it
    out, which means the one thing never exercised is that the seam actually
    sleeps. A ``_sleep`` that quietly did nothing would turn the backoff into
    three immediate retries against a provider that just asked for a pause.
    """
    import time as _time

    before = _time.perf_counter()
    _REAL_SLEEP(0.01)

    assert _time.perf_counter() - before >= 0.005


class TestAnErrorInsideA200IsNotASuccess:
    """P37 M13: OpenRouter's in-body errors were counted as the provider working.

    When the model provider behind OpenRouter fails after the request was
    accepted, OpenRouter answers HTTP 200 with ``{"error": {"code": 502, ...}}``
    and no ``choices``. The 2xx branch called ``BREAKER.succeeded()`` before
    reading the body. Each such call failed ("no choices") but counted as a
    success and cleared whatever failures the breaker had counted. The breaker
    could never open on the commonest outage a free model has, so every upload
    paid the whole call before falling back. A 502 or 429 in the body is also
    as transient as one in the status line, and it was never retried.
    """

    @staticmethod
    def _error_body(code, message="Provider returned error"):
        return _FakeResponse(200, payload={"error": {"code": code, "message": message}})

    def test_an_upstream_failure_in_the_body_is_retried(self, configured, monkeypatch):
        bodies = iter([self._error_body(502), _FakeResponse(payload=_completion("read it"))])
        calls = []

        def scripted(url, **kwargs):
            calls.append(url)
            return next(bodies)

        monkeypatch.setattr(httpx, "post", scripted)
        assert chat_completion(MESSAGES) == "read it"
        assert len(calls) == 2

    def test_repeated_upstream_failures_open_the_breaker(self, configured, transport):
        transport["state"]["response"] = self._error_body(502)
        for _ in range(openrouter_client.BREAKER_THRESHOLD):
            with pytest.raises(OpenRouterError):
                chat_completion(MESSAGES)
        sent = len(transport["calls"])

        with pytest.raises(OpenRouterError, match="unavailable"):
            chat_completion(MESSAGES)
        assert len(transport["calls"]) == sent, "an open breaker still called the provider"

    def test_an_error_about_the_request_is_not_retried_or_held_against_the_provider(
        self, configured, transport
    ):
        transport["state"]["response"] = self._error_body(400, "Invalid model")
        for _ in range(openrouter_client.BREAKER_THRESHOLD + 1):
            with pytest.raises(OpenRouterError, match="400"):
                chat_completion(MESSAGES)
        # One request per call, and the breaker never opened on our own mistake.
        assert len(transport["calls"]) == openrouter_client.BREAKER_THRESHOLD + 1
