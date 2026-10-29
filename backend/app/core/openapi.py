"""Make the published spec say what each route actually answers.

The two conditional error codes used to be declared once, on the ``FastAPI``
app, and inherited by all 44 routes. That is right for 500 — any route can fail
that way — and wrong for both of the others:

* A blanket **401** told a client that ``GET /health/live`` can answer "missing
  bearer token". It is on the public allowlist and has no token to miss. The
  same claim was published for both other probes, ``/health/jobs``, the two
  ``/meta/*`` lookups and ``/auth/register`` — the whole allowlist, none of
  which has ever returned a 401.
* A blanket **429** said ``/health/live`` can be rate limited. It is the one
  path in ``_UNLIMITED_PATHS``, exempt from the global limiter precisely so a
  throttled probe never reads as an unready pod — the failure that exemption
  exists to prevent is the one the spec was advertising.

A generated client believes the spec. One that retries on 429 grows a
back-off branch for a probe that cannot emit one, and one that refreshes a
token on 401 grows that branch for endpoints that take no token.

So the two are derived from the assembled route table rather than declared: a
route documents 401 when it actually depends on ``get_current_user`` or
``get_current_business``, and 429 when something actually counts it — its own
``RateLimit`` bucket, or the global limiter, which counts every path outside
``_UNLIMITED_PATHS``. Those are the same two properties
``tests/test_request_guards.py`` already sweeps for, so a new route earns a
correct spec by having correct dependencies rather than by remembering to
describe itself.

A route that declares its own 401 or 429 keeps its own wording — ``/auth/login``
returns 401 for a wrong password, which is a different event from an absent
token and says so. Only the absent code is filled in.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI

from app.core.routes import collect_api_routes, dependency_calls

# Wording for the codes this module adds. Kept here rather than at the call
# site so the description a client reads is identical on all 35 routes.
UNAUTHORIZED = {"description": "Missing, malformed or expired bearer token."}
RATE_LIMITED = {"description": "Rate limit exceeded. See the `Retry-After` header."}
FORBIDDEN = {
    "description": (
        "The caller's role on this business is read-only. Only an owner or an "
        "accountant may change the tenant's books."
    )
}


PAID_TIER_REQUIRED = {
    "description": (
        "The business has no active paid subscription, and this feature needs "
        "one. The detail points at /pricing."
    )
}
ROLE_OR_PAID_TIER = {
    "description": (
        "Either the caller's role on this business is read-only (only an owner "
        "or an accountant may change the tenant's books), or the business has no "
        "active paid subscription and this feature needs one. The detail says which."
    )
}
DATABASE_UNAVAILABLE = {
    "description": (
        "The database is unreachable or its pool is exhausted. Retryable; "
        "see the `Retry-After` header."
    )
}


# The body every error handler in ``app.core.errors`` returns, and until now
# described nowhere: every 4xx and 5xx in the spec was a description alone, so
# a generated client had no type for the ``error.code`` it is told to branch
# on, and 422 advertised FastAPI's own ``HTTPValidationError`` — a shape this
# app never sends, since its handler wraps the pydantic list in the same body.
ERROR_SCHEMA_NAME = "ErrorResponse"
ERROR_SCHEMA: dict[str, Any] = {
    "title": ERROR_SCHEMA_NAME,
    "type": "object",
    "required": ["detail", "error", "correlation_id"],
    "properties": {
        "detail": {
            "description": (
                "What went wrong, for a person: usually a sentence; a pydantic "
                "error list on a 422; an object with a `message` on a few 409s."
            ),
        },
        "error": {
            "type": "object",
            "required": ["code", "status", "message"],
            "properties": {
                "code": {"type": "string", "description": "Stable; branch on this."},
                "status": {"type": "integer"},
                "message": {"type": "string", "description": "`detail` as one line."},
                "fields": {
                    "type": "array",
                    "description": "On a 422: one entry per refused field.",
                    "items": {
                        "type": "object",
                        "required": ["field", "message", "type"],
                        "properties": {
                            "field": {"type": "string"},
                            "message": {"type": "string"},
                            "type": {"type": "string"},
                        },
                    },
                },
            },
        },
        "correlation_id": {
            "type": "string",
            "description": "Also in the `X-Request-ID` header; quote it to support.",
        },
    },
}
_ERROR_CONTENT = {
    "application/json": {"schema": {"$ref": f"#/components/schemas/{ERROR_SCHEMA_NAME}"}}
}


def describe_error_bodies(schema: dict[str, Any]) -> None:
    """Give every documented 4xx and 5xx the body the error handlers return.

    A response that already names its own content keeps it. 422 is the
    exception: FastAPI fills it with ``HTTPValidationError`` itself, which is
    wrong for this app, so it is replaced rather than kept.
    """
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components[ERROR_SCHEMA_NAME] = ERROR_SCHEMA
    for operations in schema.get("paths", {}).values():
        for operation in operations.values():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses", {})
            for code, response in list(responses.items()):
                if not (code.isdigit() and int(code) >= 400):
                    continue
                if code == "422" or "content" not in response:
                    # A new dict: the 403 wordings above are shared module
                    # constants, and setting a key on one would edit them all.
                    responses[code] = {**response, "content": _ERROR_CONTENT}
    for unused in ("HTTPValidationError", "ValidationError"):
        if not _referenced(schema, unused):
            components.pop(unused, None)


def _referenced(schema: dict[str, Any], name: str) -> bool:
    return f'"#/components/schemas/{name}"' in json.dumps(schema)


def is_guarded(route: Any) -> bool:
    """Does *route* actually require a token? Then it can answer 401."""
    from app.core.deps import get_current_business, get_current_user

    return any(
        call in (get_current_user, get_current_business)
        for call in dependency_calls(route.dependant)
    )


def is_metered(route: Any) -> bool:
    """Does anything count *route*? Then it can answer 429.

    Two layers, and either is enough: a ``RateLimit`` dependency of its own, or
    the global limiter in ``app.core.middleware``, which counts every path it
    is not explicitly told to skip.
    """
    from app.core.middleware import _UNLIMITED_PATHS
    from app.core.rate_limit import RateLimit

    if any(isinstance(call, RateLimit) for call in dependency_calls(route.dependant)):
        return True
    return route.path not in _UNLIMITED_PATHS


def is_role_gated(route: Any) -> bool:
    """Does *route* demand a role the caller may not hold? Then it can 403.

    Only the role check earns the code here. Every guarded route can already
    answer 403 for a business the caller is not a member of or one that has
    been deactivated — but that is a property of the ``X-Business-Id`` header
    rather than of the route, it applies uniformly to all thirty-odd of them,
    and documenting it on each would say nothing a client could branch on.
    A role refusal is the one 403 that distinguishes routes from each other:
    it is exactly the set a read-only session must not offer.
    """
    from app.core.deps import RequireRole

    return any(isinstance(call, RequireRole) for call in dependency_calls(route.dependant))


def is_paid_gated(route: Any) -> bool:
    """Does *route* need a paid subscription? Then it can 403 for that.

    Like the role check and unlike the ``X-Business-Id`` one, this distinguishes
    routes: it is exactly the set a free business is refused, and the frontend
    branches on it to offer the plans. It was documented on the one route that
    spelled it out by hand (``/meta/gstin/bulk``) and on none of the three ITC
    reads that carry the same gate.
    """
    from app.core.deps import require_paid_tier

    return require_paid_tier in dependency_calls(route.dependant)


def uses_database(route: Any) -> bool:
    """Does *route* open a session? Then it can answer 503.

    ``app.core.errors`` turns an ``OperationalError`` — a dropped connection,
    an exhausted pool — into a retryable 503 with ``Retry-After``. That can
    happen on any route that reaches the database and on none that does not,
    and it is the one failure a client should retry rather than report. Four
    routes documented it by hand; the other fifty-odd that can return it did not.
    """
    from app.core.database import get_db

    return get_db in dependency_calls(route.dependant)


def _forbidden_for(role_gated: bool, paid_gated: bool) -> dict[str, Any] | None:
    if role_gated and paid_gated:
        return dict(ROLE_OR_PAID_TIER)
    if role_gated:
        return dict(FORBIDDEN)
    if paid_gated:
        return dict(PAID_TIER_REQUIRED)
    return None


def describe_conditional_responses(application: FastAPI, schema: dict[str, Any]) -> None:
    """Add 401/403/429/503 to *schema* for the routes that can really return them."""
    paths = schema.get("paths", {})
    for route in collect_api_routes(application):
        operations = paths.get(route.path)
        if not operations:
            # ``/`` and anything else with include_in_schema=False.
            continue
        guarded = is_guarded(route)
        metered = is_metered(route)
        role_gated = is_role_gated(route)
        forbidden = _forbidden_for(role_gated, is_paid_gated(route))
        database = uses_database(route)
        for method in route.methods or ():
            operation = operations.get(method.lower())
            if not isinstance(operation, dict):
                continue
            responses = operation.setdefault("responses", {})
            # setdefault, not assignment: a route that documented the code
            # itself described a specific event and that wording wins.
            if guarded:
                responses.setdefault("401", dict(UNAUTHORIZED))
            if forbidden is not None:
                responses.setdefault("403", forbidden)
            if metered:
                responses.setdefault("429", dict(RATE_LIMITED))
            if database:
                responses.setdefault("503", dict(DATABASE_UNAVAILABLE))


def install_openapi(application: FastAPI) -> None:
    """Wrap *application*'s schema builder with the pass above.

    Wrapping rather than rebuilding: ``get_openapi`` takes a dozen arguments
    off the app, and restating them here is how the spec's title, tags or
    licence drift away from what ``create_app`` passed.
    """
    build = application.openapi

    def openapi() -> dict[str, Any]:
        if application.openapi_schema:
            return application.openapi_schema
        # ``build`` caches into ``application.openapi_schema`` and returns it,
        # so this mutates the cached object once and every later call is served
        # from the guard above.
        schema = build()
        describe_conditional_responses(application, schema)
        describe_error_bodies(schema)
        return schema

    application.openapi = openapi  # type: ignore[method-assign]


__all__ = [
    "DATABASE_UNAVAILABLE",
    "ERROR_SCHEMA",
    "ERROR_SCHEMA_NAME",
    "FORBIDDEN",
    "PAID_TIER_REQUIRED",
    "RATE_LIMITED",
    "ROLE_OR_PAID_TIER",
    "UNAUTHORIZED",
    "describe_conditional_responses",
    "describe_error_bodies",
    "install_openapi",
    "is_guarded",
    "is_metered",
    "is_paid_gated",
    "is_role_gated",
    "uses_database",
]
