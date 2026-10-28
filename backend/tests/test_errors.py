"""The error envelope, and what a failure is allowed to say.

The rule these tests defend: a bug is logged in full and answered with a
generic message. A stack trace, a failing SQL statement or a connection string
in an HTTP response is a gift to whoever is probing the service, and the
correlation id is what lets support find the real error without publishing it.

Everything here uses the ``raw_client`` fixture. The default TestClient
re-raises an unhandled exception into the test rather than letting the handler
turn it into a response, which would mean never reaching the code under test.
"""
from __future__ import annotations

import json
from typing import Literal

import pytest
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

from app.core.config import settings
from app.core.errors import error_body, error_code
from app.main import app
from tests.conftest import SUPPLIER_GSTIN_SAME_STATE

# A router of routes that fail in each of the ways the handlers care about.
# Mounted once at import; the paths are namespaced so they cannot collide with
# the real API. Kept out of the schema because this router is bolted onto the
# shared `app` object at import time, so it is visible to every other test in
# the session — including the ones in test_route_contracts.py that sweep the
# published surface. A fault-injection probe is not part of the API.
_boom = APIRouter(prefix="/_test_errors", include_in_schema=False)


@_boom.get("/unhandled")
async def _raise_unhandled() -> None:
    # The shape of a real bug: a None where a row was assumed.
    raise ValueError("connection to postgres://gstbot:hunter2@db:5432 failed")


@_boom.get("/integrity")
async def _raise_integrity() -> None:
    raise IntegrityError(
        "INSERT INTO invoices (invoice_number) VALUES ('INV-1')",
        {},
        Exception('duplicate key value violates unique constraint "ix_invoices_number"'),
    )


@_boom.get("/operational")
async def _raise_operational() -> None:
    raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))


@_boom.get("/sqlalchemy")
async def _raise_sqlalchemy() -> None:
    raise SQLAlchemyError("mapper failed on table invoices")


@_boom.get("/keyerror")
async def _raise_keyerror() -> None:
    raise KeyError("taxable_value")


# The three shapes a route here raises a detail in, each carrying a value the
# size the caller controls. ``query`` rather than a constant so one route can
# answer both the oversized and the ordinary case.
@_boom.get("/http-detail")
async def _raise_http_detail(
    shape: Literal["string", "dict", "list"], size: int = Query(ge=0, le=200_000)
) -> None:
    value = "V" * size
    if shape == "string":
        raise HTTPException(status_code=422, detail=f"Invoice {value} is not right.")
    if shape == "dict":
        raise HTTPException(status_code=409, detail={"message": value, "invoice_id": 7})
    raise HTTPException(status_code=422, detail=[value, "second line"])


app.include_router(_boom)


# Turning debug off — which is what makes the app's own handler the thing under
# test rather than Starlette's traceback page — belongs to `raw_client` and
# lives in conftest.py as `production_error_handling`. It was an autouse
# fixture in this file, which made every test here work and the identical
# request from any other file answer a traceback with the exception in it. See
# the note on that fixture for why the file a test sits in was the wrong thing
# for it to depend on.


def test_the_client_under_test_is_the_app_and_not_the_debugger(raw_client):
    """The trap that made this file's coverage of the 500 handler local to it.

    Under debug, Starlette answers the same route with the same status and a
    `text/plain` traceback — so the one assertion anybody writes first, that a
    bug is a 500, passes either way. Everything that distinguishes the two is
    in the body, which is why this looks at the envelope rather than the code:
    the app's handler is the only one of the two that produces JSON.
    """
    response = raw_client.get("/_test_errors/unhandled")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()) >= {"detail", "error", "correlation_id"}


# ---- the envelope ----

def test_every_error_carries_the_same_three_keys(client):
    response = client.get("/api/v1/invoices/999999")
    assert response.status_code in (401, 404)
    body = response.json()
    assert set(body) >= {"detail", "error", "correlation_id"}
    assert set(body["error"]) >= {"code", "status", "message"}


def test_detail_stays_the_primary_field(auth_client):
    """``detail`` is what FastAPI already returned and what clients read.

    ``error`` and ``correlation_id`` were added beside it rather than replacing
    it, so hardening the API did not break its consumers.
    """
    response = auth_client.get("/api/v1/invoices/999999")
    assert response.status_code == 404
    assert isinstance(response.json()["detail"], str)


def test_the_error_block_repeats_the_status(auth_client):
    response = auth_client.get("/api/v1/invoices/999999")
    assert response.json()["error"]["status"] == 404


def test_a_machine_readable_code_accompanies_the_prose(auth_client):
    # A client should branch on this rather than on the wording of ``detail``.
    assert auth_client.get("/api/v1/invoices/999999").json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, "bad_request"),
        (401, "unauthorized"),
        (404, "not_found"),
        (409, "conflict"),
        (413, "payload_too_large"),
        (422, "validation_error"),
        (429, "rate_limited"),
        (500, "internal_error"),
        (503, "service_unavailable"),
    ],
)
def test_known_statuses_map_to_stable_codes(status_code, expected):
    assert error_code(status_code) == expected


def test_an_unmapped_4xx_gets_a_generic_code():
    assert error_code(418) == "error"


def test_an_unmapped_5xx_is_still_an_internal_error():
    # A client must be able to tell "our fault" from "your fault" even for a
    # status this module has never heard of.
    assert error_code(599) == "internal_error"


def test_a_string_detail_is_reused_as_the_message():
    body = error_body(404, "Invoice not found")
    assert body["error"]["message"] == "Invoice not found"


def test_a_list_detail_is_summarised_into_one_line():
    body = error_body(422, [{"msg": "field required"}, {"msg": "not a valid date"}])
    assert body["error"]["message"] == "field required; not a valid date"


def test_a_dict_detail_is_summarised_by_its_message():
    body = error_body(409, {"message": "Already uploaded as invoice 3", "invoice_id": 3})
    assert body["error"]["message"] == "Already uploaded as invoice 3"


def test_correlation_id_is_never_absent():
    # "-" rather than null: the field is documented as a string, and a client
    # printing it into a support ticket should not render "None".
    assert error_body(500, "x")["correlation_id"] == "-"


# ---- what a bug is allowed to say ----

def test_a_bug_answers_with_a_500(raw_client):
    assert raw_client.get("/_test_errors/unhandled").status_code == 500


def test_a_bug_does_not_leak_the_exception_message(raw_client):
    body = raw_client.get("/_test_errors/unhandled").text
    # The route raises a message containing a password. None of it may appear.
    assert "hunter2" not in body
    assert "postgres://" not in body
    assert "ValueError" not in body


def test_a_bug_does_not_leak_a_traceback(raw_client):
    body = raw_client.get("/_test_errors/unhandled").text
    assert "Traceback" not in body
    assert "_raise_unhandled" not in body
    assert ".py" not in body


def test_a_500_still_offers_a_reference_to_quote(raw_client):
    body = raw_client.get("/_test_errors/unhandled").json()
    # The whole point of the opaque message: support can find the real error
    # without it having been published to the caller.
    assert body["correlation_id"]
    assert body["correlation_id"] in body["detail"]


def test_the_500_reference_matches_the_response_header(raw_client):
    response = raw_client.get("/_test_errors/unhandled")
    assert response.json()["correlation_id"] == response.headers["X-Request-ID"]


def test_a_supplied_correlation_id_is_what_the_500_quotes(raw_client):
    response = raw_client.get(
        "/_test_errors/unhandled", headers={"X-Request-ID": "trace-me-0001"}
    )
    # Support is given the id the *caller* already has, not a second one.
    assert response.json()["correlation_id"] == "trace-me-0001"


def test_any_exception_type_is_caught_not_just_valueerror(raw_client):
    response = raw_client.get("/_test_errors/keyerror")
    assert response.status_code == 500
    assert "taxable_value" not in response.text


def test_the_generic_message_does_not_change_between_bugs(raw_client):
    """Two different bugs must be indistinguishable from outside.

    A message that varied with the exception would let a prober tell a missing
    key from a bad cast, which is the leak this is meant to close.
    """
    first = raw_client.get("/_test_errors/unhandled").json()
    second = raw_client.get("/_test_errors/keyerror").json()
    strip = lambda body: body["detail"].replace(body["correlation_id"], "")  # noqa: E731
    assert strip(first) == strip(second)


@pytest.mark.parametrize("debug", [True, False])
def test_neither_debug_setting_leaks_the_exception(raw_client, monkeypatch, debug):
    # DEBUG changes the wording of the 500 but must never change what it
    # reveals — a staging box with DEBUG on is still on the internet.
    monkeypatch.setattr(settings, "debug", debug)
    body = raw_client.get("/_test_errors/unhandled").text
    assert "hunter2" not in body
    assert "Traceback" not in body


# ---- database failures are classified, not lumped into 500 ----

def test_a_constraint_violation_is_a_409_not_a_500(raw_client):
    # The database enforcing a rule the request broke is the caller's problem.
    assert raw_client.get("/_test_errors/integrity").status_code == 409


def test_a_constraint_violation_does_not_name_the_index(raw_client):
    response = raw_client.get("/_test_errors/integrity")
    # The driver's message names table and index; repeating it hands over the
    # schema.
    assert "ix_invoices_number" not in response.text
    assert "INSERT INTO" not in response.text
    assert response.json()["error"]["code"] == "conflict"


def test_a_dropped_connection_is_a_retryable_503(raw_client):
    response = raw_client.get("/_test_errors/operational")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_the_503_tells_the_caller_when_to_retry(raw_client):
    # Without Retry-After a client either gives up or hammers the recovering
    # database.
    assert raw_client.get("/_test_errors/operational").headers["Retry-After"] == "5"


def test_a_dropped_connection_does_not_leak_the_query(raw_client):
    assert "SELECT 1" not in raw_client.get("/_test_errors/operational").text


def test_an_unclassified_database_error_is_an_opaque_500(raw_client):
    response = raw_client.get("/_test_errors/sqlalchemy")
    assert response.status_code == 500
    assert "mapper failed" not in response.text
    assert "invoices" not in response.text


# ---- validation ----

def test_validation_errors_name_the_field_that_failed(client):
    # Registration is the widest JSON body the API takes, so it is the natural
    # place to exercise the validation handler.
    response = client.post("/api/v1/auth/register", json={"email": "not-an-email"})
    assert response.status_code == 422
    fields = response.json()["error"]["fields"]
    assert any(entry["field"] for entry in fields)
    assert all({"field", "message", "type"} <= set(entry) for entry in fields)


def test_validation_detail_stays_the_pydantic_list(client):
    """The frontend's error formatter walks ``detail`` as a list of {msg}.

    Replacing it with a string would break that formatter silently.
    """
    response = client.post("/api/v1/auth/register", json={"email": "not-an-email"})
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert all("msg" in entry for entry in detail)


def test_validation_errors_are_json_serialisable(client):
    """A validator that raises carries the exception object in ``ctx``.

    ``json.dumps`` cannot serialise that, so the handler runs the list through
    ``jsonable_encoder`` first. Without it this request returns a 500 while
    trying to report a 422.
    """
    # The GSTIN validator raises InvalidGSTIN, and pydantic puts that
    # exception object into the error's ``ctx``.
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner@example.com",
            "password": "supersecret123",
            "gstin": "NOT-A-VALID-GST",
            "legal_name": "Acme",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


class TestAnUnpairedSurrogateIsRefusedNotCrashedOn:
    """JSON may spell half of a UTF-16 pair, and Python parses it as written.

    The 422 quotes the rejected value back, and UTF-8 cannot encode a lone
    surrogate, so refusing it raised while writing the response: one escaped
    ``\\ud800`` in any validated string field was a 500 on every route.
    """

    def _post(self, client, path, raw):
        return client.post(path, content=raw, headers={"content-type": "application/json"})

    def test_a_rejected_value_is_quoted_with_the_half_pair_replaced(self, raw_client):
        response = self._post(
            raw_client, "/api/v1/auth/register", b'{"email": "a\\ud800b@example.com"}'
        )
        assert response.status_code == 422
        assert "\ufffd" in response.text or "\\ufffd" in response.text
        assert response.json()["error"]["code"] == "validation_error"

    def test_an_authenticated_route_refuses_it_too(self, raw_client, auth_client, paid_business):
        response = raw_client.post(
            "/api/v1/reconciliation/run",
            content=b'{"period": "\\ud800"}',
            headers={**dict(auth_client.headers), "content-type": "application/json"},
        )
        assert response.status_code == 422

    def test_a_real_pair_is_kept_whole(self):
        # Only the half that cannot be written is replaced; an emoji survives.
        body = error_body(422, "\U0001f600 and \ud800")
        assert body["detail"] == "\U0001f600 and \ufffd"


class TestA422DoesNotEchoTheWholeRequestBack:
    """Pydantic puts the rejected value in each error's ``input``.

    That field is what makes a 422 actionable — "we read '2026-13'" beats
    "invalid period" — so it is truncated rather than dropped. But it is the
    *caller's* value, and echoing it whole made every validation error in the
    API a reflector: a bound added to the public GSTIN lookup moved that route
    to a 422 and left the 20KB response body exactly as it was, because the
    reflection had moved into the error handler rather than gone away.

    Bounded here, in the one handler every 422 leaves through, rather than at
    each route that takes a string.
    """

    OVERSIZED = "A" * 20_000

    def test_a_rejected_query_value_is_not_echoed_whole(self, client):
        response = client.get(f"/api/v1/meta/gstin/{self.OVERSIZED}")
        assert response.status_code == 422
        assert len(response.content) < 2_000

    def test_a_rejected_body_field_is_not_echoed_whole(self, client):
        """The same hole through a JSON body rather than a path segment.

        The body-size middleware caps what can be sent at all, but a body well
        under that ceiling still round-tripped in full through the 422.
        """
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": self.OVERSIZED,
                "password": "supersecret123",
                "gstin": "27AAPFU0939F1ZV",
                "legal_name": self.OVERSIZED,
            },
        )
        assert response.status_code == 422
        assert len(response.content) < 4_000

    def test_what_survives_says_it_was_cut(self, client):
        """A silently truncated value would read as the value itself, which is
        worse than either the whole thing or nothing — a caller debugging a
        rejected field would compare it against what they sent and conclude
        the API had mangled it."""
        response = client.get(f"/api/v1/meta/gstin/{self.OVERSIZED}")
        assert "truncated" in response.text

    def test_a_value_short_enough_to_be_useful_is_still_quoted_in_full(self, auth_client):
        """The bound must not cost a 422 its usefulness. A real field — a
        GSTIN, a period, an invoice number — is nowhere near the ceiling and
        has to come back intact, or the truncation has broken the thing it was
        protecting."""
        response = auth_client.get("/api/v1/invoices", params={"period": "2026-13"})
        assert response.status_code == 422
        assert "2026-13" in response.text

    def test_the_detail_list_keeps_its_shape(self, client):
        """The frontend walks ``detail`` as a list of {msg}. Bounding the
        values must not turn the list into a string, which is the obvious way
        to implement this and would break that formatter silently."""
        response = client.post(
            "/api/v1/auth/register", json={"email": self.OVERSIZED}
        )
        detail = response.json()["detail"]
        assert isinstance(detail, list)
        assert all("msg" in entry for entry in detail)

    def test_an_oversized_container_is_described_rather_than_quoted(self, client):
        """A body that is the wrong *shape* has no meaningful prefix.

        The string case can be cut to its first 200 characters and stay useful.
        A rejected value that arrives as the whole parsed list or dict cannot:
        the first 200 entries of a 300-element array tell the caller nothing
        that its type and length do not, and serialising them is the reflection
        the bound exists to stop. So it is replaced by a note of what it was.
        """
        response = client.post(
            "/api/v1/auth/register", json=[{"email": "a@b.com"} for _ in range(300)]
        )
        assert response.status_code == 422
        assert len(response.content) < 1_000
        echoed = response.json()["detail"][0]["input"]
        assert echoed == "<list of 300 items…[truncated]>"

    def test_a_container_small_enough_to_read_is_still_quoted_in_full(self, client):
        """The same bound must not describe away a value a caller can act on.

        A three-element list in a rejected field is the whole of what they
        sent, and reading back ``<list of 3 items>`` would make the 422 less
        useful than saying nothing.
        """
        response = client.post("/api/v1/auth/register", json=[1, 2, 3])
        assert response.status_code == 422
        assert response.json()["detail"][0]["input"] == [1, 2, 3]

    def test_an_oversized_value_one_level_down_is_not_echoed_whole(self, client):
        """The ceiling only looked at the top level of a rejected body.

        A "missing field" error quotes the whole body it looked in, so a dict
        of three keys passed the item count and every value inside it came
        back in full — the reflector closed above, reopened one level down.
        """
        response = client.post(
            "/api/v1/auth/register",
            json={"a": self.OVERSIZED, "b": [self.OVERSIZED], "c": {"d": self.OVERSIZED}},
        )
        assert response.status_code == 422
        assert len(response.content) < 6_000
        assert "truncated" in response.text

    @pytest.mark.parametrize("depth", [1_000, 5_000])
    def test_a_deeply_nested_body_is_a_422_not_a_500(self, raw_client, depth):
        """The echo was encoded recursively, and a body a thousand objects
        deep took that past the interpreter's recursion limit inside the 422
        handler — so a malformed request answered 500 on every JSON route."""
        payload: dict = {}
        for _ in range(depth):
            payload = {"a": payload}
        response = raw_client.post(
            "/api/v1/feedback",
            content=json.dumps(payload),
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422
        assert len(response.content) < 2_000
        assert "truncated" in response.text

    def test_a_shallow_nested_value_is_still_quoted_in_full(self, client):
        """Depth is cut where no real field reaches, not at the first level."""
        response = client.post("/api/v1/auth/register", json={"x": {"y": [1, 2]}})
        assert response.status_code == 422
        assert response.json()["detail"][0]["input"] == {"x": {"y": [1, 2]}}


def test_a_404_from_a_route_keeps_its_own_wording(auth_client):
    # The generic handler must not overwrite a message a route wrote on purpose.
    body = auth_client.get("/api/v1/invoices/999999").json()
    assert body["detail"] != ""
    assert "went wrong on our side" not in body["detail"]


def test_a_detail_that_is_neither_string_list_nor_dict_still_gets_a_message():
    """``HTTPException(detail=...)`` takes any object, and one gets raised.

    The envelope promises ``error.message`` is always a string. A detail that
    is a bare scalar — a count, an enum, an exception object — reaches the
    summariser having matched none of its shapes, and the fallback is what
    keeps the promise instead of putting a non-string in a string field.
    """
    body = error_body(409, detail=42)

    assert body["error"]["message"] == "42"
    assert isinstance(body["error"]["message"], str)


def test_a_list_of_plain_strings_is_joined_rather_than_repr_d():
    body = error_body(422, detail=["first problem", "second problem"])

    assert body["error"]["message"] == "first problem; second problem"


def test_a_dict_detail_without_a_message_key_falls_back_to_the_whole_dict():
    # Better a readable dict than an empty message: the caller still has to be
    # able to tell one 409 from another.
    body = error_body(409, detail={"conflict": "arn already recorded"})

    assert "arn already recorded" in body["error"]["message"]


class TestEveryGuardedRouteRefusesInTheSameShape:
    """The envelope, swept over the route table rather than sampled.

    Every test above proves one *handler* produces the shape. None of them
    proves every *route* leaves through those handlers, and that is the half
    that rots: a route can answer 401 from somewhere other than the shared
    dependency — a middleware, a hand-rolled check, a `return JSONResponse(...)`
    — and be perfectly correct about the status while carrying none of
    ``error.code``, ``error.status`` or ``correlation_id``. A client that
    branches on ``error.code`` rather than on the prose then has one endpoint
    it cannot read, and nothing fails until someone hits that endpoint signed
    out.

    401 is the condition used because it is the only failure every guarded
    route can be put into without knowing anything about its body, its
    tenant's data, or what a valid request to it looks like.

    ``tests/test_request_guards.py`` sweeps the same table for whether each
    route *depends* on the guard. This one sweeps what the wire actually says,
    which is what a client sees.
    """

    # Enough to fill any path in the table. Ids are 1 rather than a real row's:
    # the refusal has to land before anything is looked up, so a value that
    # names no row is the stronger input — if one of these ever 404s, the auth
    # check ran after the lookup and the sweep has found that too.
    PATH_VALUES = {
        "alert_id": "1",
        "business_id": "1",
        "error_id": "1",
        "feedback_id": "1",
        "invoice_id": "1",
        "run_id": "1",
        "supplier_id": "1",
        "period": "2026-04",
        "return_type": "gstr3b",
        "extension": "json",
        "gstin": SUPPLIER_GSTIN_SAME_STATE,
    }

    def _guarded_routes(self):
        from app.core.deps import get_current_business, get_current_user
        from tests.test_route_contracts import API_ROUTES

        def calls(dependant):
            yield dependant.call
            for sub in dependant.dependencies:
                yield from calls(sub)

        for route in API_ROUTES:
            if route.path.startswith("/_"):
                continue
            if not {get_current_business, get_current_user} & set(calls(route.dependant)):
                continue
            path = route.path
            for name, value in self.PATH_VALUES.items():
                path = path.replace("{" + name + "}", value)
            for method in sorted(route.methods):
                yield method, path

    def test_the_sweep_finds_routes_to_check(self):
        # A generator that yields nothing passes everything below.
        found = list(self._guarded_routes())
        assert len(found) > 20, found
        assert "{" not in "".join(path for _, path in found), (
            "a path parameter had no stand-in value, so the URL is not real: "
            + str([p for _, p in found if "{" in p])
        )

    def test_every_guarded_route_refuses_with_the_full_envelope(self, raw_client):
        wrong = []
        for method, path in self._guarded_routes():
            response = raw_client.request(method, path, json={})
            if response.status_code != 401:
                wrong.append(f"{method} {path} -> {response.status_code}")
                continue
            body = response.json()
            if not {"detail", "error", "correlation_id"} <= set(body):
                wrong.append(f"{method} {path} -> keys {sorted(body)}")
            elif body["error"].get("code") != "unauthorized":
                wrong.append(f"{method} {path} -> code {body['error'].get('code')}")
            elif body["error"].get("status") != 401:
                wrong.append(f"{method} {path} -> status {body['error'].get('status')}")
            elif not body["correlation_id"]:
                wrong.append(f"{method} {path} -> empty correlation_id")
        assert not wrong, "these did not refuse in the shared shape: " + "; ".join(wrong)

    def test_every_refusal_carries_the_correlation_id_as_a_header_too(self, raw_client):
        """Support quotes the header when the body is what is in doubt."""
        missing = [
            f"{method} {path}"
            for method, path in self._guarded_routes()
            if not raw_client.request(method, path, json={}).headers.get("X-Request-ID")
        ]
        assert not missing, missing

    def test_no_refusal_names_what_it_was_protecting(self, raw_client):
        """A 401 must not distinguish "no such row" from "not yours".

        The tenancy rule is that a cross-tenant read is a 404 and never a 403,
        because ids are sequential and a confirmed id is a countable one. The
        same reasoning applies before sign-in: every one of these is asked for
        a row id that does not exist, and none of them may say so.
        """
        leaks = []
        for method, path in self._guarded_routes():
            detail = str(raw_client.request(method, path, json={}).json().get("detail", ""))
            if any(word in detail.lower() for word in ("not found", "no such", "does not exist")):
                leaks.append(f"{method} {path} -> {detail}")
        assert not leaks, leaks


class TestAPathNothingServesAndAMethodNothingAccepts:
    """Starlette answers these two before any route runs, and the envelope
    has to survive that.

    Every other refusal in this file leaves through a handler the app installs
    on its own routes. A request for a path the router never matched, and a
    request for a real path with a verb it does not take, are raised by
    Starlette itself — the app's ``StarletteHTTPException`` handler is the only
    thing that puts them back in the shared shape. A client branching on
    ``error.code`` is at its most likely to be doing so here, because a typo'd
    URL is the most common way to reach the API wrongly, and nothing pinned
    either shape until now.
    """

    def test_an_unmatched_path_answers_the_shared_envelope(self, client):
        response = client.get("/api/v1/no-such-collection")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "not_found"
        assert body["error"]["status"] == 404
        assert isinstance(body["detail"], str) and body["detail"]
        assert body["error"]["message"] == body["detail"]

    def test_an_unmatched_path_still_gets_a_correlation_id(self, client):
        """Support's only handle on "your API 404s me" is this id, and a 404
        raised before routing is exactly the report that arrives without a
        route name to search for."""
        response = client.get("/api/v1/no-such-collection")
        assert response.json()["correlation_id"] != "-"
        assert response.headers.get("X-Request-ID")

    def test_an_unmatched_path_does_not_echo_the_path_back(self, client):
        """The 404 body is written by the app, not assembled from the URL.

        Reflecting the requested path would make every unrouted URL a reflector
        on an endpoint that needs no account — the same hole the 422 bound in
        :class:`TestA422DoesNotEchoTheWholeRequestBack` closes.
        """
        response = client.get("/api/v1/" + "Z" * 4_000)
        assert response.status_code == 404
        assert "ZZZZ" not in response.text

    def test_a_wrong_method_on_a_real_path_answers_405_in_the_envelope(self, client):
        response = client.delete("/api/v1/auth/login")
        assert response.status_code == 405
        body = response.json()
        assert body["error"]["code"] == "method_not_allowed"
        assert body["error"]["status"] == 405
        assert body["correlation_id"] != "-"

    def test_a_wrong_method_still_names_the_methods_that_would_work(self, client):
        """``Allow`` is the whole value of a 405 over a 404, and it is set by
        Starlette on the exception rather than by the handler. Rebuilding the
        response body must not drop the header that came with it."""
        response = client.delete("/api/v1/auth/login")
        assert "POST" in response.headers.get("allow", "")

    def test_a_wrong_method_does_not_confirm_what_the_path_is_for(self, client):
        """A 405 is unauthenticated and says a path exists — which is fine, the
        route table is published — but it must not go on to describe the row
        behind it the way a route's own 404 does."""
        detail = str(client.delete("/api/v1/invoices/1").json()["detail"])
        assert "invoice" not in detail.lower()


class TestAnHTTPExceptionDetailIsBoundedToo:
    """The other handler every 4xx leaves through.

    The 422 handler above learned to cut what pydantic quotes. A route's own
    ``HTTPException`` was trusted, because its detail is a sentence somebody
    wrote — but a sentence built around a value out of the request is only as
    short as the value. A GSTR-2B statement with a 100KB invoice number in a
    line the import refused came back as a 200KB 422: the number once in
    ``detail`` and again in ``message``, with the 15MB upload allowance behind
    it. Bounded in the handler, so the guarantee does not depend on every
    ``detail=`` remembering.
    """

    OVERSIZED = 100_000

    @pytest.mark.parametrize("shape", ["string", "dict", "list"])
    def test_an_oversized_detail_is_cut_whatever_its_shape(self, client, shape):
        response = client.get(
            "/_test_errors/http-detail", params={"shape": shape, "size": self.OVERSIZED}
        )
        assert response.status_code in (409, 422)
        assert len(response.content) < 5_000
        assert "truncated" in response.text

    def test_the_message_is_bounded_as_well_as_the_detail(self, client):
        # ``message`` is a rendering of ``detail``; bounding one and not the
        # other would halve the reflection rather than close it.
        response = client.get(
            "/_test_errors/http-detail", params={"shape": "dict", "size": self.OVERSIZED}
        )
        assert len(response.json()["error"]["message"]) < 3_000

    def test_the_keys_beside_the_string_survive(self, client):
        # The dict shape carries an ``invoice_id`` a client links to; the cut
        # must touch the string and nothing else in the envelope.
        response = client.get(
            "/_test_errors/http-detail", params={"shape": "dict", "size": self.OVERSIZED}
        )
        assert response.json()["detail"]["invoice_id"] == 7

    @pytest.mark.parametrize("shape", ["string", "dict", "list"])
    def test_a_detail_the_length_a_route_writes_is_untouched(self, client, shape):
        # Every real detail is a few hundred characters; the ceiling has to
        # sit far enough above them that none is ever cut mid-sentence.
        response = client.get("/_test_errors/http-detail", params={"shape": shape, "size": 600})
        assert "truncated" not in response.text
        assert "V" * 600 in response.text

    def test_the_real_route_that_reflected_a_file_no_longer_does(self, auth_client, paid_business):
        """The upload that found this, end to end.

        A single cell past ``MONEY_MAX`` is clamped on the way in, so the
        refusal is reached by two rate lines that sum a paisa over it — the
        same route ``test_gstr2b_boundaries`` takes — with the invoice
        number the file quotes back set to the size an edited file can make it.
        """
        import json

        huge = "X" * self.OVERSIZED
        body = json.dumps(
            {
                "data": {
                    "rtnprd": "042026",
                    "docdata": {
                        "b2b": [
                            {
                                "ctin": SUPPLIER_GSTIN_SAME_STATE,
                                "inv": [
                                    {
                                        "inum": huge,
                                        "dt": "15-04-2026",
                                        "items": [
                                            {"txval": "99999999999999.99"},
                                            {"txval": "0.01"},
                                        ],
                                    }
                                ],
                            }
                        ]
                    },
                }
            }
        ).encode()
        response = auth_client.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={"file": ("gstr2b.json", body, "application/json")},
        )
        assert response.status_code == 422
        assert len(response.content) < 2_000
        # And the sentence that tells the reader what was wrong survived the
        # quoting: the number is cut at the source, not the message at the
        # handler.
        assert "larger than any invoice carries" in response.json()["detail"]


# ---- GB030: entity IDs in 404s, OAuth constants, payment guidance, webhook auth ----

class TestA404IncludesTheRequestedId:
    """A 404 that says only "not found" forces the caller to correlate the
    response with the request. Including the id makes a log entry or error
    toast self-contained."""

    def test_invoice_404_names_the_id(self, auth_client):
        r = auth_client.get("/api/v1/invoices/999999")
        assert r.status_code == 404
        assert "999999" in r.json()["detail"]

    def test_supplier_404_names_the_id(self, auth_client):
        r = auth_client.get("/api/v1/suppliers/999999")
        assert r.status_code == 404
        assert "999999" in r.json()["detail"]

    def test_alert_404_names_the_id(self, auth_client):
        r = auth_client.post("/api/v1/alerts/999999/read")
        assert r.status_code == 404
        assert "999999" in r.json()["detail"]

    def test_reconciliation_run_404_names_the_id(self, auth_client):
        r = auth_client.get("/api/v1/reconciliation/999999")
        assert r.status_code == 404
        assert "999999" in r.json()["detail"]


class TestOAuthNotConfiguredReturns501:
    """Unconfigured OAuth providers must return 501, not a bare integer."""

    def test_google_returns_501(self, client):
        r = client.get("/api/v1/auth/google", follow_redirects=False)
        assert r.status_code == 501

    def test_github_returns_501(self, client):
        r = client.get("/api/v1/auth/github", follow_redirects=False)
        assert r.status_code == 501

    def test_microsoft_returns_501(self, client):
        r = client.get("/api/v1/auth/microsoft", follow_redirects=False)
        assert r.status_code == 501


class TestSecretsAreNotEchoed:
    """A rejected password is named in a 422, never quoted back in it."""

    def test_a_short_password_is_redacted(self, client):
        response = client.post(
            "/api/v1/auth/register", json={"email": "a@b.com", "password": "hunter2"}
        )
        assert response.status_code == 422
        assert "hunter2" not in response.text
        (error,) = response.json()["detail"]
        assert error["loc"] == ["body", "password"]
        assert error["input"] == "[redacted]"

    def test_a_body_quoted_by_a_missing_field_keeps_its_password_out(self, client):
        response = client.post("/api/v1/auth/register", json={"password": "hunter22long"})
        assert response.status_code == 422
        assert "hunter22long" not in response.text
        echoed = response.json()["detail"][0]["input"]
        assert echoed == {"password": "[redacted]"}

    def test_an_ordinary_field_is_still_quoted(self, client):
        response = client.post(
            "/api/v1/auth/register", json={"email": "nope", "password": "longenough1"}
        )
        assert response.json()["detail"][0]["input"] == "nope"


def test_an_unhandled_500_carries_the_same_security_headers_as_any_response(
    raw_client, monkeypatch
):
    """The bare-Exception handler runs outside the user middleware, so it sets
    the headers itself. It used to copy the middleware's private dict and add
    its own CSP, and left HSTS off — the one response it most mattered on."""
    from app.core.config import settings
    from app.core.headers import security_headers

    monkeypatch.setattr(settings, "hsts_enabled", True)
    response = raw_client.get("/_test_errors/unhandled")

    assert response.status_code == 500
    for header, value in security_headers().items():
        assert response.headers.get(header) == value, header
    assert "Strict-Transport-Security" in response.headers


class TestAValidationMessageNamesItsField:
    """P16 M19: ``error.message`` is what an API client without this product's
    frontend shows — the GPT actions read it out — and it was pydantic's bare
    text: two missing fields read "Field required; Field required"."""

    def test_each_missing_field_is_named(self, client):
        response = client.post("/api/v1/auth/register", json={})
        assert response.status_code == 422
        message = response.json()["error"]["message"]
        assert "email: Field required" in message
        assert "password: Field required" in message

    def test_a_query_bound_is_named(self, client):
        response = client.get("/api/v1/gpt/calculate", params={"amount": "-1", "rate": "18"})
        assert response.status_code == 422
        assert response.json()["error"]["message"].startswith("amount: ")

    def test_a_message_that_already_names_its_field_is_left_alone(self):
        from app.core.errors import _summarise

        error = {"loc": ("body", "gstin"), "msg": "GSTIN check digit does not match"}
        assert _summarise([error]) == "GSTIN check digit does not match"

    def test_a_whole_body_error_has_no_field_to_name(self):
        from app.core.errors import _summarise

        assert _summarise([{"loc": ("body",), "msg": "JSON decode error"}]) == "JSON decode error"
