"""The published spec must describe what the routes actually answer.

The other sweeps in this suite check that a route *behaves* correctly — that it
resolves its tenant, that it carries a bucket, that a cross-tenant read 404s.
This one checks that the document we hand to client authors agrees with them.

It exists because the two conditional error codes were declared once on the
FastAPI app and inherited by all 44 routes, which published a 401 for the seven
public endpoints that take no token and a 429 for the one probe deliberately
exempt from the limiter. Nothing failed: a spec is only wrong when someone
believes it, and the people who believe it are downstream.
"""
from __future__ import annotations

import pytest

from app.core.openapi import RATE_LIMITED, UNAUTHORIZED, is_guarded, is_metered
from app.core.routes import collect_api_routes
from app.main import app


@pytest.fixture(scope="module")
def spec():
    return app.openapi()


@pytest.fixture(scope="module")
def documented(spec):
    """``{(path, method): {status codes}}`` as published."""
    return {
        (path, method): set(operation.get("responses", {}))
        for path, operations in spec["paths"].items()
        for method, operation in operations.items()
        if isinstance(operation, dict)
    }


def _real_routes():
    """The product's own routes.

    ``tests/test_errors.py`` mounts a ``/_test_errors`` router on the shared app
    to give the exception handlers something to catch, so whether it is in the
    table depends on which module imported first. The other sweeps in this suite
    drop the same prefix for the same reason.
    """
    return [
        route for route in collect_api_routes(app) if not route.path.startswith("/_")
    ]


def _schema_routes():
    return [route for route in _real_routes() if route.include_in_schema]


def _operations(route):
    for method in route.methods or ():
        if method.lower() in ("get", "post", "put", "patch", "delete"):
            yield route.path, method.lower()


class TestTheSweepIsReadingSomething:
    """A sweep over an empty table proves nothing; these say it is not."""

    def test_the_schema_has_every_route_in_it(self, documented):
        paths = {path for path, _ in documented}
        assert len(paths) >= 40, f"only {len(paths)} paths in the spec"

    def test_both_kinds_of_route_are_present_to_compare(self):
        routes = _schema_routes()
        guarded = [route for route in routes if is_guarded(route)]
        public = [route for route in routes if not is_guarded(route)]
        # If either side were empty the assertions below would hold vacuously.
        assert len(guarded) >= 30, f"only {len(guarded)} guarded routes"
        assert len(public) >= 5, f"only {len(public)} public routes"


class TestUnauthorizedIsDocumentedWhereItCanHappen:
    def test_every_route_that_requires_a_token_says_so(self, documented):
        missing = [
            f"{method.upper()} {path}"
            for route in _schema_routes()
            if is_guarded(route)
            for path, method in _operations(route)
            if "401" not in documented.get((path, method), set())
        ]
        assert missing == [], "guarded but no documented 401: " + ", ".join(missing)

    def test_no_public_route_advertises_a_401_it_cannot_return(self, documented):
        """The regression. ``/auth/login`` is the one legitimate exception."""
        offenders = [
            f"{method.upper()} {path}"
            for route in _schema_routes()
            if not is_guarded(route)
            for path, method in _operations(route)
            if "401" in documented.get((path, method), set())
            and path != "/api/v1/auth/login"
        ]
        assert offenders == [], (
            "these take no token and cannot answer 401: " + ", ".join(offenders)
        )

    def test_the_login_401_is_its_own_and_not_the_inherited_one(self, spec):
        # Login really does return 401 — for a wrong password, which is a
        # different event from an absent bearer token. The point of filling the
        # code in with setdefault is that this wording survives.
        described = spec["paths"]["/api/v1/auth/login"]["post"]["responses"]["401"]
        assert described["description"] != UNAUTHORIZED["description"]
        assert "password" in described["description"].lower()

    def test_the_public_allowlist_is_what_it_has_always_been(self):
        """Pins the set, so opening a route to the world is a visible diff."""
        public = sorted(
            route.path
            for route in _real_routes()
            if not is_guarded(route) and route.methods != {"HEAD"}
        )
        assert public == [
            "/",
            "/api/v1/advisor/ask",
            "/api/v1/advisor/ask/stream",
            "/api/v1/auth/github",
            "/api/v1/auth/github/callback",
            "/api/v1/auth/google",
            "/api/v1/auth/google/callback",
            "/api/v1/auth/login",
            "/api/v1/auth/microsoft",
            "/api/v1/auth/microsoft/callback",
            "/api/v1/auth/register",
            "/api/v1/feedback",
            "/api/v1/feedback/error",
            "/api/v1/gpt/calculate",
            "/api/v1/gpt/filing-dates",
            "/api/v1/gpt/gstin/{gstin}",
            "/api/v1/gpt/hsn",
            "/api/v1/gpt/invoice",
            "/api/v1/gpt/openapi.yaml",
            "/api/v1/gpt/privacy",
            "/api/v1/health",
            "/api/v1/health/jobs",
            "/api/v1/health/live",
            "/api/v1/health/ready",
            "/api/v1/meta/gstin/{gstin}",
            "/api/v1/meta/recent-lookups",
            "/api/v1/meta/reminder-subscribe",
            "/api/v1/meta/states",
            "/api/v1/meta/stats",
            "/api/v1/referrals/leaderboard",
            "/api/v1/referrals/track",
            "/api/v1/seo/og-image",
            "/api/v1/seo/robots.txt",
            "/api/v1/seo/sitemap.xml",
            "/api/v1/subscribers",
            "/api/v1/subscribers/unsubscribe",
            "/api/v1/subscriptions/pricing",
            "/api/v1/subscriptions/webhook",
            "/api/v1/whatsapp/webhook",
            "/api/v1/whatsapp/webhook",
        ]


class TestRateLimitedIsDocumentedWhereItCanHappen:
    def test_every_counted_route_says_it_can_be_limited(self, documented):
        missing = [
            f"{method.upper()} {path}"
            for route in _schema_routes()
            if is_metered(route)
            for path, method in _operations(route)
            if "429" not in documented.get((path, method), set())
        ]
        assert missing == [], "metered but no documented 429: " + ", ".join(missing)

    def test_the_liveness_probe_does_not_advertise_a_429(self, documented):
        """The other regression, and the one with a production consequence.

        ``/health/live`` is the single path in ``_UNLIMITED_PATHS``. It is
        exempt so that a throttled probe never reads as an unready instance and
        takes pods out of rotation — and the spec was telling client authors to
        write exactly the back-off branch that exemption exists to make
        unnecessary.
        """
        assert "429" not in documented[("/api/v1/health/live", "get")]

    def test_it_is_the_only_route_exempt_from_the_limiter(self):
        # The HEAD twins of the health probes (P16) mirror their GET route —
        # tests/test_misc.py holds each to its GET's dependencies — so each
        # path is counted once, by its GET.
        unmetered = sorted(
            route.path
            for route in _real_routes()
            if not is_metered(route) and route.methods != {"HEAD"}
        )
        assert unmetered == ["/api/v1/health/live"]

    def test_the_wording_is_the_shared_one(self, spec):
        described = spec["paths"]["/api/v1/health"]["get"]["responses"]["429"]
        assert described["description"] == RATE_LIMITED["description"]


class TestTheRefusalsTheClientsActOnAreDocumented:
    """Statuses that the pricing and advisor screens branch on, each raised by
    the route itself rather than inherited from a dependency, so no sweep above
    would notice one going undocumented."""

    @pytest.mark.parametrize(
        ("method", "path", "codes"),
        [
            ("post", "/api/v1/subscriptions/create-order", {"400", "409", "502", "503"}),
            ("post", "/api/v1/subscriptions/verify-payment", {"400", "409", "502"}),
            ("post", "/api/v1/subscriptions/cancel", {"400", "409", "502"}),
            ("post", "/api/v1/advisor/ask", {"502", "503", "504"}),
        ],
    )
    def test_each_status_the_route_raises_is_in_its_spec(
        self, documented, method, path, codes
    ):
        assert codes <= documented[(path, method)]


class TestFiveHundredStaysBlanket:
    """The one code that really does belong to every route."""

    def test_every_route_documents_a_500(self, documented):
        missing = [
            f"{method.upper()} {path}"
            for (path, method), codes in documented.items()
            if "500" not in codes
        ]
        assert missing == [], "no documented 500: " + ", ".join(missing)


class TestTheSchemaIsBuiltOnce:
    def test_a_second_call_returns_the_same_cached_object(self):
        # The customisation mutates the cached dict in place. Were the cache
        # guard wrong, this would append duplicates or rebuild on every /docs
        # hit — the spec is assembled from 40-odd routes and is not cheap.
        assert app.openapi() is app.openapi()

    def test_the_customisation_survives_a_rebuild(self):
        """A cleared cache must come back corrected, not raw."""
        from app.main import create_app

        fresh = create_app()
        first = fresh.openapi()
        fresh.openapi_schema = None
        assert (
            "429" not in fresh.openapi()["paths"]["/api/v1/health/live"]["get"]["responses"]
        )
        assert first["paths"].keys() == fresh.openapi_schema["paths"].keys()


class TestARouteTheSpecDoesNotPublish:
    """A route hidden from the schema must not have a response written for it.

    ``describe_conditional_responses`` walks the *route table* and writes into
    the *schema*, and the two do not have the same members: a route carrying
    ``include_in_schema=False`` is served but never documented. The walk looks
    the operation up by path, so a hidden route that shares a path with a
    documented one — which is how the errors-module probe router and any future
    internal verb on a public path both arrive — finds its sibling's entry and
    would describe *that* operation with its own dependencies.

    A 401 on a GET that takes no token is exactly the wrong-spec failure this
    file exists to catch, arriving through the back door.
    """

    def _app_with_a_hidden_sibling(self):
        from fastapi import Depends, FastAPI

        from app.core.deps import get_current_user

        application = FastAPI()

        @application.get("/thing")
        def _public() -> dict:
            return {}

        @application.post(
            "/thing", include_in_schema=False, dependencies=[Depends(get_current_user)]
        )
        def _hidden() -> dict:
            return {}

        return application

    def test_a_hidden_verb_does_not_write_401_onto_its_documented_sibling(self):
        application = self._app_with_a_hidden_sibling()
        schema = application.openapi()
        from app.core.openapi import describe_conditional_responses

        describe_conditional_responses(application, schema)
        assert "401" not in schema["paths"]["/thing"]["get"]["responses"]

    def test_the_hidden_verb_is_still_absent_from_the_document(self):
        """The point of the skip is that there is nothing to describe — not
        that the description went somewhere else."""
        application = self._app_with_a_hidden_sibling()
        schema = application.openapi()
        from app.core.openapi import describe_conditional_responses

        describe_conditional_responses(application, schema)
        assert set(schema["paths"]["/thing"]) == {"get"}


class TestThePaidTierRefusalIsDocumented:
    """``require_paid_tier`` refuses a free business with a 403 the frontend
    branches on. It was documented on the one route that wrote it out by hand
    and on none of the ITC reads that carry the same gate."""

    def test_every_paid_route_documents_a_403(self, documented):
        from app.core.openapi import is_paid_gated

        missing = [
            f"{method.upper()} {path}"
            for route in _schema_routes()
            if is_paid_gated(route)
            for path, method in _operations(route)
            if "403" not in documented[(path, method)]
        ]
        assert missing == []

    def test_a_paid_only_route_says_it_is_the_plan(self, spec):
        from app.core.openapi import PAID_TIER_REQUIRED

        described = spec["paths"]["/api/v1/itc"]["get"]["responses"]["403"]
        assert described["description"] == PAID_TIER_REQUIRED["description"]

    def test_a_route_behind_both_gates_names_both(self, spec):
        """The reconciliation run is role- *and* paid-gated; the role wording
        alone told a free owner their role was the problem."""
        from app.core.openapi import ROLE_OR_PAID_TIER

        described = spec["paths"]["/api/v1/reconciliation/run"]["post"]["responses"]["403"]
        assert described["description"] == ROLE_OR_PAID_TIER["description"]

    def test_a_route_that_words_its_own_403_keeps_it(self, spec):
        described = spec["paths"]["/api/v1/meta/gstin/bulk"]["post"]["responses"]["403"]
        assert described["description"] == "No active paid subscription."


class TestADatabaseOutageIsDocumentedWhereItCanHappen:
    """An ``OperationalError`` becomes a retryable 503 on any route that opens
    a session. Four routes said so; fifty-odd others could return it."""

    def test_every_route_with_a_session_documents_a_503(self, documented):
        from app.core.openapi import uses_database

        missing = [
            f"{method.upper()} {path}"
            for route in _schema_routes()
            if uses_database(route)
            for path, method in _operations(route)
            if "503" not in documented[(path, method)]
        ]
        assert missing == []

    def test_a_route_without_one_does_not_claim_it(self, spec):
        """It may document a 503 of its own — a readiness probe does — but not
        the database's."""
        from app.core.openapi import DATABASE_UNAVAILABLE, uses_database

        sessionless = [r for r in _schema_routes() if not uses_database(r)]
        assert sessionless, "every route uses the database — the check is vacuous"
        claimed = [
            f"{method.upper()} {path}"
            for route in sessionless
            for path, method in _operations(route)
            if spec["paths"][path][method]["responses"].get("503") == DATABASE_UNAVAILABLE
        ]
        assert claimed == []


class TestTheSignInRoutesSayTheyRedirect:
    """All six OAuth routes redirect, and all six raise 501 when the provider
    has no client id. The spec said 200 and nothing about 501."""

    PROVIDERS = ("google", "github", "microsoft")

    @pytest.mark.parametrize("provider", PROVIDERS)
    def test_starting_a_sign_in_is_a_302_or_a_501(self, spec, provider):
        responses = spec["paths"][f"/api/v1/auth/{provider}"]["get"]["responses"]
        assert {"302", "501"} <= set(responses)
        assert "200" not in responses

    @pytest.mark.parametrize("provider", PROVIDERS)
    def test_the_callback_is_a_307_or_a_501(self, spec, provider):
        responses = spec["paths"][f"/api/v1/auth/{provider}/callback"]["get"]["responses"]
        assert {"307", "501"} <= set(responses)
        assert "200" not in responses


class TestTheWhatsappWebhookRefusalsAreDocumented:
    def test_the_handshake_documents_its_403(self, spec):
        assert "403" in spec["paths"]["/api/v1/whatsapp/webhook"]["get"]["responses"]

    def test_the_receiver_documents_its_400_and_403(self, spec):
        assert {"400", "403"} <= set(spec["paths"]["/api/v1/whatsapp/webhook"]["post"]["responses"])


class TestEveryErrorDocumentsItsBody:
    """Every 4xx and 5xx was a description with no body schema.

    So a client generated from the spec had no type for ``error.code``, the
    field the API tells callers to branch on, and 422 advertised FastAPI's
    ``HTTPValidationError``, a shape this app never returns.
    """

    @pytest.fixture(scope="class")
    def spec(self):
        from app.main import app

        return app.openapi()

    def test_each_error_response_names_the_shared_body(self, spec):
        from app.core.openapi import ERROR_SCHEMA_NAME

        ref = f"#/components/schemas/{ERROR_SCHEMA_NAME}"
        missing = [
            f"{method.upper()} {path} {code}"
            for path, operations in spec["paths"].items()
            for method, op in operations.items()
            for code, response in op.get("responses", {}).items()
            if code.isdigit() and int(code) >= 400
            and response.get("content", {}).get("application/json", {}).get("schema")
            != {"$ref": ref}
        ]
        assert missing == []

    def test_the_validation_schema_fastapi_assumes_is_gone(self, spec):
        assert "HTTPValidationError" not in spec["components"]["schemas"]

    @pytest.mark.parametrize(
        "call",
        [
            lambda c: c.get("/api/v1/invoices"),  # 401
            lambda c: c.get("/api/v1/no-such-route"),  # 404
            lambda c: c.post("/api/v1/auth/login", json={}),  # 422
        ],
        ids=["401", "404", "422"],
    )
    def test_a_real_error_body_has_the_documented_keys(self, client, call):
        from app.core.openapi import ERROR_SCHEMA

        body = call(client).json()
        assert set(ERROR_SCHEMA["required"]) <= set(body)
        assert set(ERROR_SCHEMA["properties"]["error"]["required"]) <= set(body["error"])


class TestNonJsonRoutesSayWhatTheyReturn:
    @pytest.mark.parametrize(
        ("path", "media"),
        [
            ("/api/v1/seo/sitemap.xml", "application/xml"),
            ("/api/v1/seo/robots.txt", "text/plain"),
            ("/api/v1/seo/og-image", "image/png"),
            ("/api/v1/gpt/openapi.yaml", "application/yaml"),
        ],
    )
    def test_the_documented_media_type_is_the_served_one(self, path, media):
        from app.main import app

        content = app.openapi()["paths"][path]["get"]["responses"]["200"]["content"]
        assert list(content) == [media]
