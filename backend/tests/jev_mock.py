"""A fake TypeSafe API for the Jev tests.

The real SDK runs — question validation, the request body, response parsing —
against an in-process ``httpx2.MockTransport``. Faking one level lower than our
own helpers is what makes a request or response shape the SDK disagrees with
fail here rather than on the first real call.
"""
from __future__ import annotations

import json

import httpx2
import typesafe_sdk

from app.core.config import settings
from app.services import jev_service


class JevMock:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.answers: dict = {}
        self.status = 200
        self.raise_exc: Exception | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        body = request.content
        # The SDK zstd-compresses bodies over 1 KiB wherever zstd is available
        # (stdlib from Python 3.14), and the 90-chapter HSN question is one.
        if request.headers.get("content-encoding") == "zstd":
            from compression.zstd import decompress

            body = decompress(body)
        self.requests.append(json.loads(body))
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.status != 200:
            return httpx2.Response(self.status, json={"error": {"message": "boom"}})
        return httpx2.Response(200, json={
            "model": "jev-test",
            "usage": {"input_tokens": 10, "output_tokens": 1},
            "answers": self.answers,
        })

    @property
    def calls(self) -> int:
        return len(self.requests)

    def questions(self, n: int = -1) -> dict:
        return self.requests[n]["questions"]

    def state(self, n: int = -1) -> str:
        return self.requests[n]["state"]


def choice(label: str, confidence: float = 0.9, probabilities: dict | None = None) -> dict:
    return {
        "type": "choice", "choice": label, "confidence": confidence,
        "probabilities": probabilities or {label: confidence},
    }


def score(value: float, confidence: float = 0.8, probabilities: dict | None = None) -> dict:
    probs = probabilities or {"0": 0.1, "1": 0.2, "2": 0.6, "3": 0.1}
    return {
        "type": "score", "score": value, "confidence": confidence,
        "legend": {k: f"level {k}" for k in probs}, "probabilities": probs,
    }


def install(monkeypatch, *, api_key: str = "test-typesafe-key") -> JevMock:
    """Turn Jev on against the fake. Returns the fake to program and inspect."""
    mock = JevMock()

    def _client(**kwargs):
        return typesafe_sdk.TypeSafeClient(transport=httpx2.MockTransport(mock.handler), **kwargs)

    monkeypatch.setattr(jev_service, "TypeSafeClient", _client)
    monkeypatch.setattr(settings, "typesafe_api_key", api_key)
    jev_service.reset_cooldown()
    return mock
