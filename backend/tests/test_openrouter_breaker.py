"""An OpenRouter outage is paid for once, not once per invoice.

Every call has its own budget — retries, backoff, up to 80 seconds — and
nothing remembered the last call failing. An image upload makes two calls
(extraction, then OCR), so while the provider was down every upload spent up
to a couple of minutes before falling back to the heuristics it was always
going to end on: a thirty-invoice batch held the one worker for over an hour,
and with Celery off each of those waits was a request held open.

After a run of calls that fail for availability's sake, the client stops
calling for a cooldown and fails at once — the cue every caller already
treats as "fall back". One probe goes through after the cooldown.
"""
from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services import openrouter_client
from app.services.openrouter_client import OpenRouterError, chat_completion


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = "" if payload is None else str(payload)
        self.headers = {}

    def json(self):
        return self._payload


OK = _Response(200, {"choices": [{"message": {"content": "fine"}}]})


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_max_attempts", 1)
    monkeypatch.setattr(openrouter_client, "_sleep", lambda s: None)
    clock = {"now": 1000.0}
    monkeypatch.setattr(openrouter_client, "_monotonic", lambda: clock["now"])
    state = {"calls": 0, "answer": httpx.ConnectError("connection refused")}

    def post(url, **kwargs):
        state["calls"] += 1
        if isinstance(state["answer"], Exception):
            raise state["answer"]
        return state["answer"]

    monkeypatch.setattr(httpx, "post", post)
    state["clock"] = clock
    return state


def _fail(times):
    for _ in range(times):
        with pytest.raises(OpenRouterError):
            chat_completion([{"role": "user", "content": "hi"}])


def test_after_a_run_of_outages_it_stops_calling(provider):
    _fail(openrouter_client.BREAKER_THRESHOLD)
    calls = provider["calls"]

    with pytest.raises(OpenRouterError, match="unavailable"):
        chat_completion([{"role": "user", "content": "hi"}])

    assert provider["calls"] == calls


def test_one_probe_goes_through_after_the_cooldown_and_success_closes_it(provider):
    _fail(openrouter_client.BREAKER_THRESHOLD)
    provider["clock"]["now"] += openrouter_client.BREAKER_COOLDOWN_SECONDS + 1
    provider["answer"] = OK

    assert chat_completion([{"role": "user", "content": "hi"}]) == "fine"
    assert chat_completion([{"role": "user", "content": "hi"}]) == "fine"


def test_a_failed_probe_opens_it_again(provider):
    _fail(openrouter_client.BREAKER_THRESHOLD)
    provider["clock"]["now"] += openrouter_client.BREAKER_COOLDOWN_SECONDS + 1
    _fail(1)  # the probe, still refused
    calls = provider["calls"]

    with pytest.raises(OpenRouterError, match="unavailable"):
        chat_completion([{"role": "user", "content": "hi"}])
    assert provider["calls"] == calls


def test_a_refused_request_is_not_an_outage(provider):
    # A 400 or 401 says the provider is up and our request is wrong.
    provider["answer"] = _Response(401, {"error": "bad key"})
    _fail(openrouter_client.BREAKER_THRESHOLD + 2)

    assert provider["calls"] == openrouter_client.BREAKER_THRESHOLD + 2


def test_a_success_between_failures_starts_the_count_again(provider):
    _fail(openrouter_client.BREAKER_THRESHOLD - 1)
    provider["answer"] = OK
    chat_completion([{"role": "user", "content": "hi"}])
    provider["answer"] = httpx.ConnectError("refused")
    _fail(openrouter_client.BREAKER_THRESHOLD - 1)
    calls = provider["calls"]

    provider["answer"] = OK
    assert chat_completion([{"role": "user", "content": "hi"}]) == "fine"
    assert provider["calls"] == calls + 1
