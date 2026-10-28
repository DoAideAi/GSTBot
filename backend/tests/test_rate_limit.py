"""Rate limiting: the spec parser, the key derivation, and the enforcement.

The key derivation is the part worth most of these tests. Getting it wrong is
not a performance bug — keying on the connection address means a whole office
behind one NAT shares a login budget, and trusting X-Forwarded-For without a
proxy in front means the limit can be bypassed by sending a header.
"""
from __future__ import annotations

import pytest

from app.core.ratespec import Rate, parse_rate

# ``pinned_window`` lives in conftest.py: the login tests in test_auth.py need
# the same clock pinned for the same reason.


class TestParseRate:
    @pytest.mark.parametrize(
        "spec,limit,window",
        [
            ("30/minute", 30, 60),
            ("30/min", 30, 60),
            ("30/m", 30, 60),
            ("1000/hour", 1000, 3600),
            ("5/second", 5, 1),
            ("100/day", 100, 86400),
            ("5/10s", 5, 10),
            ("60/90m", 60, 5400),
            ("  30 / minute  ", 30, 60),
            ("30/MINUTE", 30, 60),
        ],
    )
    def test_accepted_forms(self, spec, limit, window):
        rate = parse_rate(spec)
        assert (rate.limit, rate.window) == (limit, window)

    def test_a_bare_count_defaults_to_a_minute(self):
        assert parse_rate("30") == Rate(30, 60)

    @pytest.mark.parametrize(
        "spec",
        ["", "abc/minute", "30/fortnight", "-5/minute", "0/minute", "30/0s", "/minute"],
    )
    def test_rejected_forms_name_the_offending_spec(self, spec):
        # Both callers are reporting to an operator who has to find the entry.
        with pytest.raises(ValueError, match="Invalid rate|unknown period"):
            parse_rate(spec)

    def test_a_zero_limit_is_refused_rather_than_locking_everyone_out(self):
        with pytest.raises(ValueError):
            parse_rate("0/minute")

    @pytest.mark.parametrize(
        "window,label",
        [(60, "5/minute"), (3600, "5/hour"), (86400, "5/day"), (10, "5/10s")],
    )
    def test_the_label_is_what_the_caller_is_told(self, window, label):
        assert Rate(5, window).label == label

    # Every spelling `_UNITS` accepts, written out here rather than read off
    # the table under test. The accepted forms above cover one alias per unit,
    # which is enough to catch a unit that is missing entirely and not enough
    # to catch one mapped to the wrong number of seconds — and a `100/hours`
    # in the deployed configuration that quietly means a minute is a rate limit
    # that is sixty times tighter than the operator wrote.
    @pytest.mark.parametrize(
        "unit,window",
        [
            ("s", 1), ("sec", 1), ("second", 1), ("seconds", 1),
            ("m", 60), ("min", 60), ("minute", 60), ("minutes", 60),
            ("h", 3600), ("hour", 3600), ("hours", 3600),
            ("d", 86400), ("day", 86400), ("days", 86400),
        ],
    )
    def test_every_accepted_spelling_of_a_period_means_what_it_says(self, unit, window):
        assert parse_rate(f"7/{unit}") == Rate(7, window)

    def test_the_unit_table_has_no_spelling_that_is_not_tested_above(self):
        """Guards the list above against a unit being added and not covered."""
        from app.core.ratespec import _UNITS

        tested = {
            "s", "sec", "second", "seconds",
            "m", "min", "minute", "minutes",
            "h", "hour", "hours",
            "d", "day", "days",
        }
        assert set(_UNITS) == tested

    def test_a_limit_of_one_is_a_limit_rather_than_an_error(self):
        """`0` is refused; the boundary is that `1` is not.

        A `1/day` is a real configuration — it is what a destructive endpoint
        would be given — and refusing it would fail startup rather than the
        request.
        """
        assert parse_rate("1/day") == Rate(1, 86400)

    def test_a_one_second_window_is_a_window_rather_than_an_error(self):
        """The other boundary: `30/0s` is refused, so `30/1s` must not be."""
        assert parse_rate("30/1s") == Rate(30, 1)

    def test_a_number_glued_to_an_unknown_unit_is_refused_as_a_rate(self):
        """`10x` parses as a count and a suffix, and the suffix is not a unit.

        Without both halves of that check the suffix is looked up anyway, and
        the operator gets a KeyError out of configuration loading instead of
        the message naming the entry they mistyped.
        """
        with pytest.raises(ValueError, match="unknown period"):
            parse_rate("5/10x")

    def test_a_rate_cannot_be_edited_after_it_is_parsed(self):
        """One `Rate` is cached per limit and shared across every request."""
        rate = parse_rate("30/minute")
        with pytest.raises(Exception, match="assign|immutable|frozen"):
            rate.limit = 1_000_000  # type: ignore[misc]


class TestIdentity:
    """Who a request is charged to."""

    def _request(self, headers=None, client_host="10.0.0.1"):
        from starlette.datastructures import Headers
        from starlette.requests import Request

        raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": raw,
            "client": (client_host, 12345),
            "query_string": b"",
        }
        request = Request(scope)
        assert isinstance(request.headers, Headers)
        return request

    def test_an_anonymous_caller_is_keyed_by_address(self):
        from app.core.rate_limit import identity

        assert identity(self._request()) == "ip:10.0.0.1"

    def test_an_authenticated_caller_is_keyed_by_user(self, auth_client):
        # The whole point: an office behind one NAT must not share a budget.
        from app.core.rate_limit import identity

        token = auth_client.headers["Authorization"].split()[1]
        who = identity(self._request({"authorization": f"Bearer {token}"}))
        assert who.startswith("user:")

    def test_two_users_from_one_address_are_separate_buckets(self, auth_client, other_tenant):
        from app.core.rate_limit import identity

        mine = auth_client.headers["Authorization"].split()[1]
        theirs = other_tenant
        assert identity(self._request({"authorization": f"Bearer {mine}"})) != identity(
            self._request({"authorization": f"Bearer {theirs}"})
        )

    def test_a_forged_token_falls_back_to_the_address(self):
        # A signature check is all that stands between "attribute this" and
        # "let the caller pick their own bucket".
        from app.core.rate_limit import identity

        who = identity(self._request({"authorization": "Bearer not.a.token"}))
        assert who == "ip:10.0.0.1"

    def test_a_malformed_authorization_header_does_not_raise(self):
        from app.core.rate_limit import identity

        assert identity(self._request({"authorization": "Basic abc"})) == "ip:10.0.0.1"


class TestClientIp:
    def _request(self, headers=None, client_host="10.0.0.1"):
        from starlette.requests import Request

        raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
        return Request(
            {
                "type": "http", "method": "GET", "path": "/",
                "headers": raw, "client": (client_host, 1), "query_string": b"",
            }
        )

    def test_forwarded_headers_are_ignored_by_default(self, monkeypatch):
        # Without a proxy in front, X-Forwarded-For is just a header the caller
        # chose — honouring it means a fresh bucket per request.
        from app.core import rate_limit
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", False)
        request = self._request({"x-forwarded-for": "1.2.3.4"})
        assert rate_limit.client_ip(request) == "10.0.0.1"

    def test_forwarded_headers_are_honoured_when_a_proxy_is_declared(self, monkeypatch):
        from app.core import rate_limit
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        request = self._request({"x-forwarded-for": "1.2.3.4, 10.0.0.9"})
        # Left-most is the original client; the rest are hops.
        assert rate_limit.client_ip(request) == "1.2.3.4"

    def test_the_proxy_set_x_real_ip_beats_a_forwarded_for_the_client_wrote(
        self, monkeypatch
    ):
        """Caddy overwrites X-Real-IP with the connection's address; the
        left-most X-Forwarded-For is only the client's own claim if the proxy
        ever passes it through."""
        from app.core import rate_limit
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        request = self._request({"x-forwarded-for": "6.6.6.6", "x-real-ip": "5.6.7.8"})
        assert rate_limit.client_ip(request) == "5.6.7.8"

    def test_x_real_ip_is_used_alone(self, monkeypatch):
        from app.core import rate_limit
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        assert rate_limit.client_ip(self._request({"x-real-ip": "5.6.7.8"})) == "5.6.7.8"

    def test_a_declared_proxy_that_sent_neither_header_falls_back_to_the_socket(
        self, monkeypatch
    ):
        """Trusting a proxy must not mean requiring one to have spoken.

        ``TRUST_PROXY_HEADERS`` is a deployment-wide switch, and the box it is
        set on still serves requests that did not arrive through the proxy — a
        probe from the orchestrator, anything reaching the port directly.
        Neither header is on those, and the fall-through to the socket address
        is what keeps them keyed by who they are rather than collapsing every
        one of them into a single shared bucket.
        """
        from app.core import rate_limit
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        assert rate_limit.client_ip(self._request({})) == "10.0.0.1"

    def test_an_empty_x_real_ip_is_not_read_as_an_address(self, monkeypatch):
        """A proxy that sets the header unconditionally sends it empty when it
        has nothing to put in it. Reading that as the client would key every
        such request to ``""`` — one bucket shared by everyone who arrives that
        way, which meters real traffic against strangers and hands an attacker
        a way to exhaust somebody else's allowance."""
        from app.core import rate_limit
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        assert rate_limit.client_ip(self._request({"x-real-ip": ""})) == "10.0.0.1"

    def test_an_overlong_forwarded_value_is_bounded(self, monkeypatch):
        # It becomes a Redis key; an unbounded one is a memory-exhaustion lever.
        from app.core import rate_limit
        from app.core.config import settings

        monkeypatch.setattr(settings, "trust_proxy_headers", True)
        value = rate_limit.client_ip(self._request({"x-forwarded-for": "9" * 500}))
        assert len(value) == 64

    def test_a_request_with_no_client_does_not_raise(self, monkeypatch):
        from starlette.requests import Request

        from app.core import rate_limit

        request = Request(
            {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""}
        )
        assert rate_limit.client_ip(request) == "unknown"


class TestEnforcement:
    def test_the_limit_is_off_by_default_in_the_suite(self, client):
        # Otherwise the twentieth test fails rather than the code under it.
        for _ in range(30):
            assert client.post(
                "/api/v1/auth/login",
                data={"username": "nobody@example.com", "password": "wrong-password"},
            ).status_code != 429

    def test_repeated_logins_are_eventually_refused(self, client, rate_limited, pinned_window):
        # 20/minute, keyed by address for an anonymous caller. A different
        # account every time, so this trips the *address* budget rather than
        # the per-account one — which is the limit under test here.
        statuses = [
            client.post(
                "/api/v1/auth/login",
                data={"username": f"nobody{i}@example.com", "password": "wrong-password"},
            ).status_code
            for i in range(25)
        ]
        # Exact, now that the window cannot roll underneath it: the twenty-first
        # is the first refusal, not merely "a 429 happened somewhere".
        assert statuses == [401] * 20 + [429] * 5

    def test_a_429_tells_the_caller_when_to_come_back(self, client, rate_limited, pinned_window):
        response = None
        for i in range(25):
            response = client.post(
                "/api/v1/auth/login",
                data={"username": f"nobody{i}@example.com", "password": "wrong-password"},
            )
            if response.status_code == 429:
                break
        assert response is not None
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0
        assert response.headers["X-RateLimit-Remaining"] == "0"
        assert response.json()["error"]["code"] == "rate_limited"

    def test_separate_endpoints_have_separate_budgets(self, client, rate_limited):
        # A caller who has exhausted their login attempts must still be able to
        # look up a GSTIN; one shared pool would make any limit a global one.
        for _ in range(25):
            client.post(
                "/api/v1/auth/login",
                data={"username": "nobody@example.com", "password": "wrong"},
            )
        assert client.get("/api/v1/meta/gstin/27AAPFU0939F1ZV").status_code != 429

    def test_a_429_does_not_disclose_the_rate_limit_spec(
        self, client, rate_limited, pinned_window
    ):
        """The detail must not say "30/minute" or "120/minute" — the exact
        capacity tells an attacker how to pace requests just below the limit.

        The ``Retry-After`` and ``X-RateLimit-*`` headers already carry what a
        well-behaved client needs; the prose is for a person, and a person needs
        "try again in N seconds", not a configuration value they cannot act on.
        """
        response = None
        for i in range(25):
            response = client.post(
                "/api/v1/auth/login",
                data={"username": f"nobody{i}@example.com", "password": "wrong-password"},
            )
            if response.status_code == 429:
                break
        assert response is not None and response.status_code == 429

        detail = response.json()["detail"]
        assert "/" not in detail, (
            f"the detail discloses the rate spec — {detail}"
        )

    def test_the_counters_are_forgotten_between_tests(self, client, rate_limited):
        # Guards the fixture itself: a leaked bucket makes an unrelated test
        # fail with a 429 and sends someone hunting in the wrong module.
        assert client.get("/api/v1/meta/gstin/27AAPFU0939F1ZV").status_code == 200


class TestThePublicHealthEndpoints:
    """The operator views are metered; the orchestrator's probes are not.

    ``/health`` and ``/health/jobs`` are public and stay public — whoever is
    watching the queue at 3am has no token to send. But they are not free the
    way the probes are: ``/health`` makes a database round-trip, and
    ``/health/jobs`` opens a fresh Redis connection and then blocks the worker
    thread for up to a second waiting on a Celery broadcast ping. Public plus
    unmetered plus a held thread is a pool-exhaustion vector reachable from off
    the internet with no account to disable afterwards.

    The paired assertion about ``/health/live`` and ``/health/ready`` is the
    half that would actually cause an outage if it regressed: throttling a
    readiness probe reads to the orchestrator as an unready instance, so a
    limit applied one line too broadly takes pods out of rotation to defend
    against load that costs nothing to serve.
    """

    @staticmethod
    def _meter(monkeypatch, spec):
        """Tighten the ops budget to *spec* for one test.

        ``_rate`` is parsed once and cached on the dependency instance, so the
        override alone only lands if nothing has touched the limiter yet this
        process — which depends on test ordering. Clearing the cache is what
        makes this deterministic when the file is run on its own and when it is
        run after something that already hit ``/health``.
        """
        from app.core.config import settings
        from app.routers.misc import _ops_limit

        monkeypatch.setattr(settings, "rate_limit_overrides", f"ops_health={spec}")
        monkeypatch.setattr(_ops_limit, "_rate", None)

    @pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/health/jobs"])
    def test_an_operator_view_runs_out(
        self, client, rate_limited, pinned_window, monkeypatch, path
    ):
        self._meter(monkeypatch, "3/minute")

        statuses = [client.get(path).status_code for _ in range(5)]

        assert statuses[:3] == [200] * 3
        assert statuses[3:] == [429] * 2

    @pytest.mark.parametrize("path", ["/api/v1/health/live", "/api/v1/health/ready"])
    def test_a_probe_is_never_throttled(
        self, client, rate_limited, pinned_window, monkeypatch, path
    ):
        # Spend the ops budget several times over first: if the limit had been
        # hung on the router rather than on the two expensive routes, the probe
        # would be answering 429 by now and Kubernetes would be restarting the
        # pod over it.
        self._meter(monkeypatch, "3/minute")
        for _ in range(10):
            client.get("/api/v1/health")

        assert [client.get(path).status_code for _ in range(10)] == [200] * 10

    def test_the_budget_is_tunable_without_a_deploy(
        self, client, rate_limited, pinned_window, monkeypatch
    ):
        """Under the name the limiter registers it as — an operator who has to
        widen this during an incident cannot be made to ship code first."""
        self._meter(monkeypatch, "1/minute")

        assert [client.get("/api/v1/health").status_code for _ in range(3)] == [200, 429, 429]

    def test_the_budget_comes_back_when_the_window_rolls(
        self, client, rate_limited, pinned_window, monkeypatch
    ):
        """A health endpoint that latched off after one burst would blind the
        monitoring it exists to feed."""
        self._meter(monkeypatch, "2/minute")
        for _ in range(4):
            client.get("/api/v1/health")
        assert client.get("/api/v1/health").status_code == 429

        pinned_window(60)

        assert client.get("/api/v1/health").status_code == 200


class TestWindowsRollOver:
    """What happens at a boundary — the half of a fixed window nothing asserted.

    Every enforcement test above establishes that a budget runs out. None of
    them establish that it ever comes back, because doing so meant sleeping for
    a minute. A limiter that refuses correctly and never forgives is a far
    worse bug than one that is slightly too generous, and until the clock
    became injectable there was no test that could tell the two apart.
    """

    def test_a_spent_budget_is_restored_when_the_window_rolls(self, pinned_window):
        from app.core import rate_limit

        rate = Rate(3, 60)
        rate_limit.reset()
        for _ in range(3):
            rate_limit.charge("rollover:key", rate)
        assert not rate_limit.peek("rollover:key", rate).allowed

        pinned_window(60)

        assert rate_limit.peek("rollover:key", rate).allowed
        assert rate_limit.peek("rollover:key", rate).remaining == 3
        rate_limit.reset()

    def test_the_budget_holds_right_up_to_the_boundary(self, pinned_window):
        from app.core import rate_limit

        rate = Rate(3, 60)
        rate_limit.reset()
        for _ in range(3):
            rate_limit.charge("rollover:key", rate)

        # One second short of the roll, the refusal must still stand — an
        # off-by-one in the flooring would hand the budget back a window early.
        pinned_window(59)
        assert not rate_limit.peek("rollover:key", rate).allowed

        pinned_window(1)
        assert rate_limit.peek("rollover:key", rate).allowed
        rate_limit.reset()

    def test_retry_after_counts_down_towards_the_roll(self, pinned_window):
        """The number the caller is told to sleep for has to shrink as the
        window drains, and must never be zero — a client told to retry in zero
        seconds retries immediately and is refused again."""
        from app.core import rate_limit

        rate = Rate(1, 60)
        rate_limit.reset()

        assert rate_limit.charge("countdown:key", rate).retry_after == 60
        pinned_window(30)
        assert rate_limit.peek("countdown:key", rate).retry_after == 30
        pinned_window(29.5)
        assert rate_limit.peek("countdown:key", rate).retry_after == 1
        rate_limit.reset()

    def test_an_expired_window_is_not_reused_by_a_later_one(self, pinned_window):
        """Windows are keyed by their start, so a count from an old one must
        not be visible to the new one even though the rate key is identical."""
        from app.core import rate_limit

        rate = Rate(2, 60)
        rate_limit.reset()
        rate_limit.charge("rollover:key", rate)
        rate_limit.charge("rollover:key", rate)

        pinned_window(120)  # Two windows on, not one.

        assert rate_limit.charge("rollover:key", rate).remaining == 1
        rate_limit.reset()

    def test_a_login_budget_comes_back_after_its_minute(
        self, client, rate_limited, pinned_window
    ):
        """The same property end to end: a caller locked out of login is not
        locked out forever."""
        statuses = [
            client.post(
                "/api/v1/auth/login",
                data={"username": f"nobody{i}@example.com", "password": "wrong-password"},
            ).status_code
            for i in range(22)
        ]
        assert statuses[-1] == 429

        pinned_window(60)

        assert client.post(
            "/api/v1/auth/login",
            data={"username": "nobody-fresh@example.com", "password": "wrong-password"},
        ).status_code == 401


class TestMemoryFallback:
    """With Redis down the limiter degrades rather than failing the request."""

    def test_a_dead_redis_does_not_break_a_request(self, client):
        # The suite points REDIS_URL at a closed port, so this is the path that
        # runs for every other test in the file too.
        assert client.get("/api/v1/health").status_code == 200

    def test_the_fallback_still_counts(self):
        from app.core import rate_limit
        from app.core.ratespec import Rate

        rate_limit.reset()
        rate = Rate(3, 60)
        decisions = [rate_limit.charge("test:key", rate) for _ in range(5)]
        assert [d.allowed for d in decisions] == [True, True, True, False, False]
        assert decisions[0].remaining == 2
        assert decisions[-1].remaining == 0
        rate_limit.reset()

    def test_distinct_keys_do_not_share_a_counter(self):
        from app.core import rate_limit
        from app.core.ratespec import Rate

        rate_limit.reset()
        rate = Rate(1, 60)
        assert rate_limit.charge("a", rate).allowed
        assert rate_limit.charge("b", rate).allowed
        assert not rate_limit.charge("a", rate).allowed
        rate_limit.reset()

    def test_the_key_map_is_bounded(self):
        # A flood of distinct keys must not be a memory leak in a long-lived
        # worker; rolled-over windows are evicted oldest-first.
        from app.core.rate_limit import _MAX_MEMORY_KEYS, _MemoryWindows

        windows = _MemoryWindows()
        for i in range(_MAX_MEMORY_KEYS + 2000):
            windows.hit(f"key-{i}")
        assert len(windows._counts) <= _MAX_MEMORY_KEYS + 1


class TestFailureCounterVerbs:
    """``peek`` and ``forget``, the two verbs a failure budget needs.

    A request counter only ever charges. A failure budget has to answer "may
    another attempt be made" *without* spending one — otherwise asking the
    question is itself an attempt — and has to be droppable, because the caller
    who proves their identity must get their budget back. Login is the caller;
    these are the primitives underneath it.
    """

    @pytest.fixture(autouse=True)
    def _clean(self):
        from app.core import rate_limit

        rate_limit.reset()
        yield
        rate_limit.reset()

    def test_peek_reports_the_count_without_spending_one(self):
        from app.core import rate_limit

        rate = Rate(3, 60)
        rate_limit.charge("failures:acct", rate)

        first = rate_limit.peek("failures:acct", rate)
        second = rate_limit.peek("failures:acct", rate)

        # Two reads, still one charge — a peek that incremented would mean a
        # budget of N allowed only N/2 real attempts.
        assert first.remaining == second.remaining == 2
        assert rate_limit.charge("failures:acct", rate).remaining == 1

    def test_peek_on_an_untouched_key_reports_the_whole_budget(self):
        from app.core import rate_limit

        decision = rate_limit.peek("failures:never-seen", Rate(5, 60))
        assert decision.allowed
        assert decision.remaining == 5
        assert decision.limit == 5

    def test_peek_closes_one_attempt_before_charge_does(self):
        """The two answer different questions and must not be interchanged.

        ``charge`` says "was the attempt I just counted within budget", so on a
        budget of 2 it stays true for the second. ``peek`` says "is there room
        for one more", so after two charges it is false — which is what a
        pre-flight check needs. Swapping them would let one extra guess
        through on every window.
        """
        from app.core import rate_limit

        rate = Rate(2, 60)
        assert rate_limit.peek("failures:acct", rate).allowed

        assert rate_limit.charge("failures:acct", rate).allowed
        assert rate_limit.peek("failures:acct", rate).allowed

        assert rate_limit.charge("failures:acct", rate).allowed
        assert not rate_limit.peek("failures:acct", rate).allowed

    def test_forget_drops_the_count(self):
        from app.core import rate_limit

        rate = Rate(3, 60)
        for _ in range(3):
            rate_limit.charge("failures:acct", rate)
        assert not rate_limit.peek("failures:acct", rate).allowed

        rate_limit.forget("failures:acct", rate)

        assert rate_limit.peek("failures:acct", rate).allowed
        assert rate_limit.peek("failures:acct", rate).remaining == 3

    def test_forget_leaves_other_keys_alone(self):
        from app.core import rate_limit

        rate = Rate(2, 60)
        rate_limit.charge("failures:mine", rate)
        rate_limit.charge("failures:theirs", rate)

        rate_limit.forget("failures:mine", rate)

        assert rate_limit.peek("failures:mine", rate).remaining == 2
        assert rate_limit.peek("failures:theirs", rate).remaining == 1

    def test_forget_on_a_key_that_was_never_charged_is_not_an_error(self):
        from app.core import rate_limit

        rate_limit.forget("failures:never-seen", Rate(2, 60))

    def test_peek_and_forget_address_the_window_that_is_open_now(self, monkeypatch):
        """A budget is per window, so a forget must not reach back into an old
        one — and a peek must not read one that has already rolled over."""
        from app.core import rate_limit

        rate = Rate(2, 60)
        # ``_clock``, not ``rate_limit.time.time``: the latter is the stdlib
        # module itself, so patching it stops the clock for httpx, logging and
        # everything else running inside the test as well.
        monkeypatch.setattr(rate_limit, "_clock", lambda: 1_000_000.0)
        rate_limit.charge("failures:acct", rate)
        rate_limit.charge("failures:acct", rate)
        assert not rate_limit.peek("failures:acct", rate).allowed

        monkeypatch.setattr(rate_limit, "_clock", lambda: 1_000_060.0)
        assert rate_limit.peek("failures:acct", rate).remaining == 2


class TestRedisBackedCounters:
    """The path that actually runs in production.

    Everything above this runs on the in-process fallback, because the suite
    points REDIS_URL at a closed port. That fallback is per-process: two API
    instances behind a load balancer would each allow the full budget, which
    is the whole reason the Redis path exists. It needs its own cover.
    """

    class FakeRedis:
        """Enough of redis-py for the limiter: a pipeline that counts."""

        def __init__(self, *, fail: bool = False) -> None:
            self.counts: dict[str, int] = {}
            self.expiries: dict[str, int] = {}
            self.deleted: list[str] = []
            self.fail = fail

        def pipeline(self):
            if self.fail:
                raise ConnectionError("Connection refused")
            return self._Pipeline(self)

        class _Pipeline:
            def __init__(self, store) -> None:
                self.store = store
                self.queued: list[tuple[str, str, int]] = []

            def incr(self, key, amount=1):
                self.queued.append(("incr", key, amount))

            def expire(self, key, seconds):
                self.queued.append(("expire", key, seconds))

            def execute(self):
                results = []
                for op, key, value in self.queued:
                    if op == "incr":
                        self.store.counts[key] = self.store.counts.get(key, 0) + value
                        results.append(self.store.counts[key])
                    else:
                        self.store.expiries[key] = value
                        results.append(True)
                return results

        def get(self, key):
            if self.fail:
                raise ConnectionError("Connection refused")
            value = self.counts.get(key)
            # redis-py hands back bytes, not an int; a peek that forgets to
            # coerce would work here and fail against a real server.
            return None if value is None else str(value).encode()

        def scan_iter(self, match, count=None):
            prefix = match.rstrip("*")
            return [k for k in list(self.counts) if k.startswith(prefix)]

        def delete(self, *keys):
            if self.fail:
                raise ConnectionError("Connection refused")
            self.deleted.extend(keys)
            for key in keys:
                self.counts.pop(key, None)

    @pytest.fixture()
    def fake_redis(self, monkeypatch):
        from app.core import rate_limit, redis_client

        rate_limit.reset()
        store = self.FakeRedis()
        monkeypatch.setattr(redis_client, "get_redis", lambda: store)
        yield store
        monkeypatch.undo()
        rate_limit.reset()

    def test_the_counting_happens_in_redis(self, fake_redis):
        from app.core import rate_limit

        for _ in range(3):
            rate_limit.charge("uploads:user:1", Rate(10, 60))

        (bucket,) = fake_redis.counts
        assert bucket.startswith("ratelimit:uploads:user:1:")
        assert fake_redis.counts[bucket] == 3

    def test_the_budget_is_shared_rather_than_per_process(self, fake_redis):
        """Two instances, one counter — otherwise a 30/minute limit is really
        30 per pod and the number in the docs is fiction."""
        from app.core import rate_limit

        rate = Rate(3, 60)
        decisions = [rate_limit.charge("shared:key", rate) for _ in range(5)]

        assert [d.allowed for d in decisions] == [True, True, True, False, False]
        assert decisions[-1].remaining == 0

    def test_the_bucket_is_given_an_expiry(self, fake_redis):
        """Without a TTL every window ever opened stays in Redis for good."""
        from app.core import rate_limit

        rate_limit.charge("uploads:user:1", Rate(10, 60))

        (bucket,) = fake_redis.expiries
        # One second past the window, so a bucket cannot expire while the
        # window it belongs to is still open.
        assert fake_redis.expiries[bucket] == 61

    def test_each_window_gets_its_own_bucket(self, fake_redis, monkeypatch):
        from app.core import rate_limit

        monkeypatch.setattr(rate_limit, "_clock", lambda: 1_000_000.0)
        rate_limit.charge("uploads:user:1", Rate(10, 60))
        monkeypatch.setattr(rate_limit, "_clock", lambda: 1_000_060.0)
        rate_limit.charge("uploads:user:1", Rate(10, 60))

        assert len(fake_redis.counts) == 2
        assert set(fake_redis.counts.values()) == {1}

    def test_a_redis_that_fails_mid_flight_degrades_instead_of_502ing(
        self, monkeypatch, caplog
    ):
        """Redis going down must cost the limit's accuracy, not the request.

        Failing closed here would mean a Redis outage takes the whole API with
        it, which is a worse outcome than briefly counting per-process.
        """
        import logging

        from app.core import rate_limit, redis_client

        rate_limit.reset()
        monkeypatch.setattr(redis_client, "get_redis", lambda: self.FakeRedis(fail=True))

        with caplog.at_level(logging.WARNING):
            decision = rate_limit.charge("uploads:user:1", Rate(2, 60))

        assert decision.allowed
        assert "degraded" in caplog.text.lower()
        # And it kept counting, in memory, rather than silently allowing all.
        assert not [rate_limit.charge("uploads:user:1", Rate(2, 60)) for _ in range(3)][-1].allowed
        rate_limit.reset()

    def test_a_failure_takes_redis_out_of_the_path_for_the_next_request(
        self, monkeypatch
    ):
        """Degrading once is not enough — it has to stop *re-*discovering it.

        The global limit is middleware, so this runs in front of every request.
        A dead-but-cached client that is only ever caught and shrugged off costs
        each of those requests a connect timeout plus a socket timeout before
        the fallback, which is 4s of added latency on every call at the default
        settings. Reporting it to the breaker is what bounds that to one slow
        request per cooldown.
        """
        from app.core import rate_limit, redis_client

        rate_limit.reset()
        redis_client.reset()
        # A client that connected fine and then lost its server. get_redis()
        # hands it out without a probe, so this failure is only visible here.
        monkeypatch.setattr(redis_client, "_client", self.FakeRedis(fail=True))

        rate_limit.charge("uploads:user:1", Rate(2, 60))

        assert redis_client.get_redis() is None, "the dead client is still cached"
        assert redis_client._down_until > 0, "the breaker was never tripped"

        monkeypatch.undo()
        redis_client.reset()
        rate_limit.reset()

    def test_reset_clears_the_redis_keys_too(self, fake_redis):
        """Otherwise one test's counters leak into the next one's budget."""
        from app.core import rate_limit

        rate_limit.charge("uploads:user:1", Rate(10, 60))
        assert fake_redis.counts

        rate_limit.reset()

        assert fake_redis.deleted
        assert not fake_redis.counts

    def test_peek_reads_the_shared_counter_rather_than_a_local_one(self, fake_redis):
        """The whole point of the Redis path: a failure budget spent against
        one API process has to be visible to the next request, which will land
        on a different one."""
        from app.core import rate_limit

        rate = Rate(3, 60)
        rate_limit.charge("failures:acct", rate)
        rate_limit.charge("failures:acct", rate)

        assert rate_limit.peek("failures:acct", rate).remaining == 1
        # Read, not written: the count in Redis is still 2.
        (bucket,) = fake_redis.counts
        assert fake_redis.counts[bucket] == 2

    def test_forget_deletes_the_shared_bucket(self, fake_redis):
        from app.core import rate_limit

        rate = Rate(3, 60)
        rate_limit.charge("failures:acct", rate)
        (bucket,) = fake_redis.counts

        rate_limit.forget("failures:acct", rate)

        assert bucket in fake_redis.deleted
        assert not fake_redis.counts
        assert rate_limit.peek("failures:acct", rate).remaining == 3

    def test_a_peek_against_a_dead_redis_falls_back_instead_of_failing_the_login(
        self, monkeypatch
    ):
        """This runs in front of every sign-in. Raising here would mean a Redis
        outage locks every user out of the product, which is a far worse
        failure than counting per-process for the cooldown."""
        from app.core import rate_limit, redis_client

        rate_limit.reset()
        redis_client.reset()
        monkeypatch.setattr(redis_client, "_client", self.FakeRedis(fail=True))

        decision = rate_limit.peek("failures:acct", Rate(2, 60))

        assert decision.allowed
        assert decision.remaining == 2
        # And it told the breaker, so the next sign-in does not pay the same
        # socket timeout over again.
        assert redis_client.get_redis() is None
        assert redis_client._down_until > 0

        monkeypatch.undo()
        redis_client.reset()
        rate_limit.reset()

    def test_a_forget_against_a_dead_redis_does_not_fail_the_login_it_follows(
        self, monkeypatch
    ):
        """``forget`` runs *after* the password has been accepted. Letting it
        raise would turn a correct password into a 500."""
        from app.core import rate_limit, redis_client

        rate_limit.reset()
        redis_client.reset()
        monkeypatch.setattr(redis_client, "_client", self.FakeRedis(fail=True))

        rate_limit.forget("failures:acct", Rate(2, 60))  # Must not raise.

        assert redis_client._down_until > 0

        monkeypatch.undo()
        redis_client.reset()
        rate_limit.reset()

    def test_forget_clears_the_in_process_count_as_well_as_the_shared_one(
        self, fake_redis, monkeypatch
    ):
        """The two stores drift when Redis flaps: attempts counted in memory
        during an outage are still there when Redis returns. A forget that only
        reached Redis would leave a user locked out by a count nothing can
        clear until the window rolls."""
        from app.core import rate_limit, redis_client

        rate = Rate(2, 60)
        # Charged while Redis was unreachable, so it landed in memory.
        monkeypatch.setattr(redis_client, "get_redis", lambda: None)
        rate_limit.charge("failures:acct", rate)
        rate_limit.charge("failures:acct", rate)

        monkeypatch.setattr(redis_client, "get_redis", lambda: fake_redis)
        rate_limit.forget("failures:acct", rate)

        monkeypatch.setattr(redis_client, "get_redis", lambda: None)
        assert rate_limit.peek("failures:acct", rate).remaining == 2

    def test_reset_survives_a_redis_that_is_down(self, monkeypatch):
        """It is called from fixtures; raising here would fail unrelated tests
        for a reason that has nothing to do with them."""
        from app.core import rate_limit, redis_client

        class Broken:
            def scan_iter(self, *_args, **_kwargs):
                raise ConnectionError("Connection refused")

        monkeypatch.setattr(redis_client, "get_redis", lambda: Broken())

        rate_limit.reset()  # Must not raise.
