"""An exhausted connection pool answers 503 with Retry-After, not 500.

``DB_POOL_TIMEOUT`` exists so that a request queued behind a saturated pool
gets an answer it can retry. Waiting it out raises ``sqlalchemy.exc.TimeoutError``,
which is not an ``OperationalError``, so it used to fall through to the
catch-all and answer 500. This drives a real one-connection pool to its limit.
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

from app.main import app

_engine = create_engine(
    "sqlite:///file:pool_probe?mode=memory&uri=true",
    poolclass=QueuePool,
    pool_size=1,
    max_overflow=0,
    pool_timeout=0.1,
    connect_args={"check_same_thread": False},
)
_probe = APIRouter(prefix="/_test_pool", include_in_schema=False)


@_probe.get("/query")
def _query() -> dict:
    with _engine.connect() as conn:
        return {"one": conn.execute(text("SELECT 1")).scalar()}


app.include_router(_probe)


@pytest.fixture()
def saturated():
    held = _engine.connect()
    try:
        yield
    finally:
        held.close()


def test_a_free_pool_answers(client):
    assert client.get("/_test_pool/query").json() == {"one": 1}


def test_a_saturated_pool_is_a_retryable_503(client, saturated):
    response = client.get("/_test_pool/query")

    assert response.status_code == 503, response.text
    assert response.headers["Retry-After"] == "5"
    assert response.json()["error"]["code"] == "service_unavailable"
