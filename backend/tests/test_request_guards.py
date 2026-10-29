"""The guards that sit in front of a route rather than inside one.

Three separate defects, one shape: a bound the product believed it had and did
not, because the thing enforcing it was somewhere other than where it was being
read.

* ``POST /itc/set-off`` was the only endpoint outside ``/health*`` and
  ``/meta/*`` that answered without a bearer token, against a published
  contract saying otherwise and against its own comment.
* No route bounded the size of the body it was handed. The upload routes
  measured the file *after* Starlette had received and buffered it, and the
  JSON routes did not measure at all.
* ``/api/v1/health`` skipped the global rate limiter, because the limiter was
  reading the list of paths that exist to keep the *access log* quiet.

The last class here guards the same shape prospectively rather than
retrospectively: which routes are metered was, until it, a per-router habit
with nothing sweeping it.
"""
from __future__ import annotations

import io
import json

import pytest

from app.core.config import settings

# --------------------------------------------------------------------------
# The one route that never asked who was calling
# --------------------------------------------------------------------------

SET_OFF = "/api/v1/itc/set-off"
BODY = {
    "credit_igst": "100.00",
    "credit_cgst": "0.00",
    "credit_sgst": "0.00",
    "credit_cess": "0.00",
    "liability_igst": "50.00",
    "liability_cgst": "0.00",
    "liability_sgst": "0.00",
    "liability_cess": "0.00",
}


class TestSetOffNeedsAToken:
    """The set-off calculator is a business route and was reachable by anyone.

    It reads no database, which is exactly how it came to be the exception: a
    route that takes no tenant has nothing obviously missing from its
    signature. What it does have is a body to decode, eight ``Decimal`` s to
    construct and a settlement to run, 240 times a minute per address, because
    its limiter is keyed by identity and an anonymous caller falls back to
    theirs.
    """

    def test_without_a_token_it_is_refused(self, raw_client):
        assert raw_client.post(SET_OFF, json=BODY).status_code == 401

    def test_a_token_that_does_not_decode_is_refused(self, raw_client):
        response = raw_client.post(
            SET_OFF, json=BODY, headers={"Authorization": "Bearer not-a-token"}
        )
        assert response.status_code == 401

    def test_with_a_token_it_still_computes(self, auth_client):
        response = auth_client.post(SET_OFF, json=BODY)
        assert response.status_code == 200, response.text
        # IGST credit discharges IGST first, so ₹100 against ₹50 settles it
        # and carries ₹50 forward.
        assert response.json()["credit_carried_forward"]["igst"] == "50.00"

    def test_the_refusal_comes_before_the_body_is_validated(self, raw_client):
        # A 422 here would mean the arithmetic path had been entered by an
        # anonymous caller and only the shape of the numbers stopped it.
        assert raw_client.post(SET_OFF, json={"credit_igst": "nonsense"}).status_code == 401

    def test_no_route_outside_the_public_ones_answers_without_a_token(self):
        """The sweep this was found by, kept so a new route cannot repeat it."""
        from app.core.deps import get_current_business, get_current_user
        from tests.test_route_contracts import API_ROUTES

        public = {
            "/",
            "/api/v1/health",
            "/api/v1/health/live",
            "/api/v1/health/ready",
            # Same reasoning as /health: an operator watching the job queue
            # has no token to send, and the figures here are operational
            # (worker/queue/heartbeat state) rather than any tenant's data.
            "/api/v1/health/jobs",
            "/api/v1/meta/states",
            "/api/v1/meta/gstin/{gstin}",
            # Authentication is what these two hand out; they cannot require it.
            "/api/v1/auth/login",
            "/api/v1/auth/register",
            # Pricing is read by the landing page before sign-in.
            "/api/v1/subscriptions/pricing",
            # Razorpay webhook — called by Razorpay servers, not by users.
            "/api/v1/subscriptions/webhook",
            # Email capture for GST filing reminders, from the landing page.
            "/api/v1/meta/reminder-subscribe",
            # Subscriber endpoints — public email capture and unsubscribe.
            "/api/v1/subscribers",
            "/api/v1/subscribers/unsubscribe",
            # Recent GSTIN lookups for social proof on the lookup page.
            "/api/v1/meta/recent-lookups",
            # Aggregate usage counts for social proof on the public pages —
            # totals only, no tenant's data, and rendered before sign-in.
            "/api/v1/meta/stats",
            # Sitemap, robots.txt, and OG images for search engines / social.
            "/api/v1/seo/sitemap.xml",
            "/api/v1/seo/robots.txt",
            "/api/v1/seo/og-image",
            # OAuth SSO — redirects to provider, no token needed.
            "/api/v1/auth/google",
            "/api/v1/auth/google/callback",
            "/api/v1/auth/github",
            "/api/v1/auth/github/callback",
            "/api/v1/auth/microsoft",
            "/api/v1/auth/microsoft/callback",
            # Which of the three are configured, so the login page offers only those.
            "/api/v1/auth/providers",
            # WhatsApp webhook — called by Twilio / WhatsApp servers.
            "/api/v1/whatsapp/webhook",
            # Anonymous product feedback from the floating widget.
            "/api/v1/feedback",
            # Uncaught browser errors, reported by the page on its own.
            "/api/v1/feedback/error",
            # AI advisor chatbot — public, proxied through the backend.
            "/api/v1/advisor/ask",
            "/api/v1/advisor/ask/stream",
            # CA referral program — tracking and leaderboard are public.
            "/api/v1/referrals/track",
            "/api/v1/referrals/leaderboard",
            # GPT Actions — the free tools for ChatGPT Custom GPTs. Stateless
            # arithmetic and lookups over public tables; no tenant data.
            "/api/v1/gpt/gstin/{gstin}",
            "/api/v1/gpt/hsn",
            "/api/v1/gpt/calculate",
            "/api/v1/gpt/invoice",
            "/api/v1/gpt/filing-dates",
            "/api/v1/gpt/openapi.yaml",
            "/api/v1/gpt/privacy",
        }

        def calls(dependant):
            yield dependant.call
            for sub in dependant.dependencies:
                yield from calls(sub)

        unguarded = {
            route.path
            for route in API_ROUTES
            # ``tests/test_errors.py`` mounts a ``/_test_errors`` router on the
            # shared app to give the exception handlers something to catch, and
            # whether it is present here depends on which module imported
            # first. Excluded by prefix rather than by ``include_in_schema`` so
            # that a real route hidden from the docs is still swept.
            if not route.path.startswith("/_")
            and not {get_current_business, get_current_user} & set(calls(route.dependant))
        }
        assert unguarded <= public, f"reachable without a token: {sorted(unguarded - public)}"


# --------------------------------------------------------------------------
# The size of a body, measured before it is read
# --------------------------------------------------------------------------

def _oversized() -> bytes:
    return b"x" * (settings.max_request_bytes + 1024)


class TestABodyLargerThanTheCeiling:
    """Refused on its declared length, without being read.

    The upload routes did answer 413 — after ``await file.read()`` had pulled
    the whole body into memory to measure it, which is the cost the limit is
    supposed to avoid. The JSON routes answered 200: a 20 MB body to
    ``/itc/set-off`` was decoded and validated in full, because nothing in the
    application had ever looked at how big a request was. The edge caps bodies
    at 32 MB, which is above this product's own 15 MB upload limit and is not
    in the path at all for a caller reaching the API on the Docker bridge.
    """

    def test_a_json_body_over_the_ceiling_is_refused(self, raw_client, auth_client):
        response = raw_client.post(
            "/api/v1/itc/set-off",
            content=b'{"credit_igst": "1", "pad": "' + _oversized() + b'"}',
            headers={**auth_client.headers, "content-type": "application/json"},
        )
        assert response.status_code == 413, response.status_code

    def test_the_refusal_says_what_the_limit_is(self, raw_client, auth_client):
        response = raw_client.post(
            "/api/v1/itc/set-off",
            content=b'{"pad": "' + _oversized() + b'"}',
            headers={**auth_client.headers, "content-type": "application/json"},
        )
        assert "MB" in response.json()["detail"]
        assert response.json()["error"]["code"] == "payload_too_large"

    def test_it_carries_a_correlation_id_like_every_other_response(
        self, raw_client, auth_client
    ):
        response = raw_client.post(
            "/api/v1/itc/set-off",
            content=b'{"pad": "' + _oversized() + b'"}',
            headers={**auth_client.headers, "content-type": "application/json"},
        )
        assert response.headers["X-Request-ID"]

    def test_an_unauthenticated_caller_is_refused_on_size_too(self, raw_client):
        # The check is in front of routing, so it does not depend on the route
        # having got as far as resolving a token.
        response = raw_client.post(
            "/api/v1/auth/login",
            content=b"username=a&password=" + _oversized(),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 413

    def test_an_oversized_upload_is_refused_before_the_route_reads_it(
        self, raw_client, auth_client
    ):
        response = raw_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("big.txt", io.BytesIO(_oversized()), "text/plain")},
            headers=auth_client.headers,
        )
        assert response.status_code == 413

    def test_the_ceiling_leaves_room_for_the_multipart_envelope(
        self, raw_client, auth_client
    ):
        """A file at exactly ``MAX_UPLOAD_MB`` must still reach the route.

        The body carrying it is larger than the file — boundaries, part
        headers, the ``invoice_type`` field — so a ceiling set at the upload
        limit itself would refuse the largest upload the product advertises,
        and would do it with the wrong error.
        """
        at_limit = b"x" * settings.max_upload_bytes
        response = raw_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("big.txt", io.BytesIO(at_limit), "text/plain")},
            data={"invoice_type": "purchase"},
            headers=auth_client.headers,
        )
        # Whatever the route makes of a 15 MB text file, the middleware must
        # not have been what stopped it.
        assert response.status_code != 413, response.text

    def test_an_ordinary_body_is_untouched(self, auth_client):
        assert auth_client.post("/api/v1/itc/set-off", json=BODY).status_code == 200

    def test_a_get_with_a_large_query_string_is_not_a_body(self, raw_client, auth_client):
        response = raw_client.get(
            "/api/v1/invoices?search=" + "a" * 3000, headers=auth_client.headers
        )
        assert response.status_code != 413

    @pytest.mark.parametrize("declared", ["", "not-a-number", "-1", "1e6"])
    def test_an_unparseable_length_is_left_to_the_server_that_framed_it(
        self, raw_client, auth_client, declared
    ):
        """Guessing at a malformed header would refuse bodies over no number.

        The route still measures what it receives, so under-declaring buys a
        caller nothing.
        """
        response = raw_client.post(
            "/api/v1/itc/set-off",
            content=json.dumps(BODY).encode(),
            headers={
                **auth_client.headers,
                "content-type": "application/json",
                "content-length": declared,
            },
        )
        assert response.status_code != 413

    def test_the_upload_route_still_measures_what_it_receives(
        self, raw_client, auth_client, monkeypatch
    ):
        # The middleware ceiling is above MAX_UPLOAD_MB by design; the route's
        # own check is what enforces the smaller number, and removing it would
        # let a 16 MB invoice through.
        #
        # The file has to land in the gap between the two limits — over the
        # upload limit, under the ceiling — or the middleware answers first and
        # this proves nothing about the route. At a 1 MB upload limit the
        # ceiling is 2 MB, so 1.5 MB is inside the gap with room for the
        # multipart envelope on either side.
        monkeypatch.setattr(settings, "max_upload_mb", 1)
        between = b"x" * (1024 * 1024 + 512 * 1024)
        response = raw_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("big.txt", io.BytesIO(between), "text/plain")},
            data={"invoice_type": "purchase"},
            headers=auth_client.headers,
        )
        assert response.status_code == 413, response.text
        # The route's message names the upload limit, not the ceiling — which
        # is how this distinguishes which of the two refused it.
        assert "1 MB" in response.json()["detail"]


# --------------------------------------------------------------------------
# Which probes the global limiter is allowed to skip
# --------------------------------------------------------------------------

class TestTheHealthProbesAndTheGlobalLimit:
    """Only the probe that costs nothing to serve is exempt from counting.

    ``_QUIET_PATHS`` exists so a load balancer polling every few seconds is not
    the bulk of the access log. The rate limiter was reading the same list,
    which is a different decision: ``/api/v1/health`` runs a ``SELECT 1`` on a
    pooled connection and pings Redis on every call, and being in that list
    made it the one unauthenticated route in the product that could be hammered
    without limit into the pool every tenant is served from.

    ``/health/ready`` does the same work and was never exempt, which is what
    gives away that the sharing was accidental rather than a decision.
    """

    @pytest.fixture()
    def tight_limit(self, rate_limited, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_default", "3/minute")
        return rate_limited

    def _spend(self, client, times=5):
        for _ in range(times):
            client.get("/api/v1/meta/states")

    def test_liveness_is_still_exempt(self, client, tight_limit):
        # It touches no dependency, so an unlimited flood of it costs nothing —
        # and limiting it would eventually have an orchestrator kill a pod for
        # being healthy.
        self._spend(client)
        assert client.get("/api/v1/health/live").status_code == 200

    def test_the_full_report_is_now_counted(self, client, tight_limit):
        self._spend(client)
        assert client.get("/api/v1/health").status_code == 429

    def test_readiness_is_counted_as_it_always_was(self, client, tight_limit):
        self._spend(client)
        assert client.get("/api/v1/health/ready").status_code == 429

    def test_the_probes_still_answer_under_an_ordinary_budget(self, client, rate_limited):
        # The default is 300 a minute per address and a load balancer polling
        # every five seconds spends twelve, so nothing an operator runs meets
        # this.
        for _ in range(20):
            assert client.get("/api/v1/health").status_code == 200

    def test_the_full_report_is_still_quiet_in_the_access_log(self, client, caplog):
        # The two lists were split, not merged: what a request costs to serve
        # and whether it is worth a log line remain separate questions.
        from app.core.middleware import _QUIET_PATHS, _UNLIMITED_PATHS

        assert "/api/v1/health" in _QUIET_PATHS
        assert "/api/v1/health" not in _UNLIMITED_PATHS
        assert _UNLIMITED_PATHS < _QUIET_PATHS

    def test_nothing_is_exempted_from_counting_that_is_not_a_route(self):
        """An exemption for a path nothing serves is still a hole.

        ``/metrics`` sat in this set for as long as it existed, and no exporter
        has ever been mounted at it. The limiter matches the path before the
        router gets a say, so every request to it was answered 404 without
        being counted — an unmetered path, in the one set whose entire subject
        is which paths may go uncounted and why. Nothing failed, which is the
        point: an exemption is invisible until somebody uses it.

        Asserted of ``_UNLIMITED_PATHS`` alone. The quiet set answers a
        different question, and an entry there for a path that is not served
        costs nothing — which is why ``/health`` unprefixed legitimately sits
        in it, against a deployment that shortens ``API_V1_PREFIX``.
        """
        from app.core.middleware import _UNLIMITED_PATHS
        from app.core.routes import collect_api_routes
        from app.main import app

        served = {route.path for route in collect_api_routes(app)}
        assert served >= _UNLIMITED_PATHS, sorted(_UNLIMITED_PATHS - served)


# --------------------------------------------------------------------------
# Which routes carry a bucket of their own
# --------------------------------------------------------------------------

# Routes with no ``RateLimit`` dependency of their own. Two of the three are
# still counted by the global limiter in ``app.core.middleware``; only
# ``/health/live`` is exempt from both, and ``_UNLIMITED_PATHS`` is where that
# is decided. Adding to this set is the same kind of decision as adding to the
# public allowlist above — it says a route may be called without bound by
# anyone who can reach it.
UNMETERED = {
    # The index: a dict of literal strings naming the other URLs. No
    # dependency, no query, nothing per-caller to spend.
    "/",
    # Touches nothing. See ``_UNLIMITED_PATHS`` for why metering a liveness
    # probe eventually has an orchestrator kill a pod for being healthy.
    "/api/v1/health/live",
    # No bucket of its own, but not a hole: the global limiter counts it, which
    # ``test_readiness_is_counted_as_it_always_was`` above pins from the
    # outside. A per-route bucket on top would be a second number to retune
    # during an incident for no more protection than the first already gives.
    "/api/v1/health/ready",
}


class TestEveryRouteIsMetered:
    """A new endpoint cannot ship unmetered without this file going red.

    The three sweeps in ``tests/test_tenancy_contract.py`` and above exist
    because tenancy and authentication were per-router habits that a new route
    could quietly not have. Rate limiting was the third such habit and the only
    one with nothing sweeping it: every route today does carry a bucket, and
    nothing in the suite would have noticed a route added tomorrow that did
    not.

    That is the hole ``POST /itc/set-off`` came through in a different form —
    an endpoint whose signature looks complete because what it is missing is a
    dependency rather than an argument.
    """

    def test_no_route_outside_the_unmetered_ones_is_missing_a_bucket(self):
        from app.core.rate_limit import RateLimit
        from tests.test_route_contracts import API_ROUTES

        def calls(dependant):
            yield dependant.call
            for sub in dependant.dependencies:
                yield from calls(sub)

        unmetered = {
            route.path
            for route in API_ROUTES
            # Same exclusion as the token sweep: tests/test_errors.py mounts a
            # router on the shared app and whether it is here depends on import
            # order.
            if not route.path.startswith("/_")
            and not any(isinstance(call, RateLimit) for call in calls(route.dependant))
        }
        assert unmetered <= UNMETERED, f"no rate limit: {sorted(unmetered - UNMETERED)}"

    def test_the_sweep_is_reading_real_buckets(self):
        """Guards the sweep itself: a walk that finds nothing would pass it."""
        from app.core.rate_limit import RateLimit
        from tests.test_route_contracts import API_ROUTES

        def calls(dependant):
            yield dependant.call
            for sub in dependant.dependencies:
                yield from calls(sub)

        metered = [
            route
            for route in API_ROUTES
            if any(isinstance(call, RateLimit) for call in calls(route.dependant))
        ]
        # Every router declares at least one bucket, and there are ten of them.
        assert len(metered) >= 30, f"only {len(metered)} routes look metered"

    def test_the_unmetered_ones_that_are_not_exempt_are_still_counted_globally(self):
        """The allowlist is three routes, and only one is a genuine hole."""
        from app.core.middleware import _UNLIMITED_PATHS

        # /health/ready and / carry no bucket of their own, so the global
        # limiter is the only thing bounding them. If either were ever added to
        # _UNLIMITED_PATHS it would become reachable without any bound at all,
        # and this sweep would be the last place that was still true.
        assert "/" not in _UNLIMITED_PATHS
        assert "/api/v1/health/ready" not in _UNLIMITED_PATHS
        # And the one that is exempt from both layers is still only the one.
        exempt_from_both = sorted(path for path in UNMETERED if path in _UNLIMITED_PATHS)
        assert exempt_from_both == ["/api/v1/health/live"]
