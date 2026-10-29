"""Resolving the caller is one query, sign-out check included.

The revocation check (P29 M19) added a second round trip to every
authenticated request — the user, then ``revoked_tokens`` by ``jti`` — for a
table that is almost always empty. It rides on the user lookup as an EXISTS.
"""
from __future__ import annotations

from sqlalchemy import event


def _auth_queries(client, engine, path="/api/v1/auth/me"):
    seen: list[str] = []

    def record(_conn, _cursor, statement, *_):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(path)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return response, [s for s in seen if "users" in s or "revoked_tokens" in s]


def test_one_query_resolves_the_caller(auth_client, db_session):
    response, queries = _auth_queries(auth_client, db_session.get_bind())
    assert response.status_code == 200
    assert len(queries) == 1, queries
    assert "revoked_tokens" in queries[0]


def test_a_signed_out_token_is_still_refused(auth_client, db_session):
    token = auth_client.headers["Authorization"]
    assert auth_client.post("/api/v1/auth/logout").status_code == 204
    response, queries = _auth_queries(auth_client, db_session.get_bind())
    assert response.status_code == 401
    assert auth_client.headers["Authorization"] == token
