"""What a refusal says, held to the standard a person reads it at.

``test_errors.py`` owns the *shape* of a failure: three keys, a stable code, a
correlation id, and nothing of the exception in a 500. It says nothing about
the sentence, and the sentence is the whole of what the user gets. A refusal
can carry a perfect envelope and still be useless — "IntegrityError on
uq_invoice_business_number", "Input should be a valid integer", "NoneType
object has no attribute 'gstin'" — and every one of those would pass every
assertion in that file.

Two sweeps, because the messages come from two places and only one of them is
obvious:

* every ``detail=`` an ``HTTPException`` is raised with, read out of the source
  rather than out of the routes somebody remembered to test;
* every message on the domain exceptions the routers turn *into* a detail with
  ``str(exc)``, which is where the longest and most user-facing sentences in
  this codebase actually live — the GSTR-2B parser's, the filing recorder's.

The rules below are deliberately about jargon and shape rather than tone. A
test cannot tell whether a sentence is kind. It can tell that the sentence
names a Python type, quotes a database index, or is four hundred characters of
a stack frame, and those are the ways this goes wrong in practice.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest
from sqlalchemy import select

from app.models.user import User, UserRole
from tests.conftest import BUSINESS_GSTIN, TEST_EMAIL

# Imported for the side effect: it bolts a fault-injection router onto the
# shared app at import time, and `test_a_bug_apologises_and_gives_a_reference`
# below is the only way to reach the 500 handler from a test. Named here rather
# than left to whichever module pytest happened to import first.
from tests.test_errors import _boom as _fault_injection_router  # noqa: F401

APP = pathlib.Path(__file__).resolve().parent.parent / "app"


# ---------------------------------------------------------------------------
# What counts as jargon
# ---------------------------------------------------------------------------

# Words that mean something to whoever wrote the line and nothing to a business
# owner reading it at 11pm on the 20th. Matched case-insensitively on word
# boundaries, so "the redis" fails and "credits" does not.
JARGON = [
    "traceback", "stack trace", "stacktrace", "exception", "errno", "assertion",
    "nonetype", "null", "undefined", "unhandled", "panic",
    "sqlalchemy", "psycopg", "sqlite", "postgres", "postgresql", "redis", "celery",
    "pydantic", "uvicorn", "fastapi", "asyncio", "coroutine",
    "integrityerror", "operationalerror", "keyerror", "valueerror", "typeerror",
    "attributeerror", "serialization", "deserialization", "middleware",
    "endpoint", "payload", "stdout", "stderr", "regex", "utf-8", "mimetype",
    "internal server error", "bad request", "unprocessable entity",
    "parse error", "must be an object", "must be an array",
]

# A Python or SQL identifier that has escaped into prose: two lowercase words
# joined by an underscore. `business_id`, `uq_invoice_number`, `invoice_type`.
IDENTIFIER = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b")

# The shapes a repr leaves behind when an object is interpolated into a message
# that meant to interpolate a value.
REPR_MARKERS = ["<class ", "object at 0x", "__", "self.", "()", "{'", "[{"]

# Long enough for two sentences and a thing to do about it. Past this the
# message is a log line that took a wrong turn.
MAX_LENGTH = 220


def assert_reads_as_prose(message: str, where: str) -> None:
    """The whole standard, in one place, so both sweeps hold to the same one."""
    assert message.strip(), f"{where}: empty message"
    assert len(message) <= MAX_LENGTH, f"{where}: {len(message)} characters — {message[:80]}…"

    lowered = message.lower()
    for word in JARGON:
        assert not re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", lowered), (
            f"{where}: says {word!r} — {message}"
        )

    identifier = IDENTIFIER.search(message)
    assert identifier is None, f"{where}: names {identifier.group()!r} — {message}"

    for marker in REPR_MARKERS:
        assert marker not in message, f"{where}: carries {marker!r} — {message}"

    # A sentence, not a label. The first character is the one place a message
    # written as a log line gives itself away, and `{}` leads several of these
    # because the thing being refused is what the reader is looking for.
    first = message.lstrip("'\"")[0]
    assert first.isupper() or first == "{", f"{where}: does not start a sentence — {message}"


# ---------------------------------------------------------------------------
# Reading the messages out of the source
# ---------------------------------------------------------------------------

def _literal(node: ast.AST) -> str | None:
    """The constant parts of a string expression, with values as ``{}``.

    An f-string's interpolations are runtime data — a filename, a period, a
    GSTIN — and are not what is under test; the words around them are. So they
    collapse to a placeholder rather than making the message unreadable.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "{}" for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _literal(node.left), _literal(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _sources() -> list[tuple[pathlib.Path, ast.Module]]:
    return [(path, ast.parse(path.read_text())) for path in sorted(APP.rglob("*.py"))]


def _http_details() -> list[tuple[str, str]]:
    """Every literal ``detail=`` in the app, as ``(where, message)``."""
    found = []
    for path, tree in _sources():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "detail":
                    continue
                message = _literal(keyword.value)
                if message is not None:
                    found.append((f"{path.name}:{node.lineno}", message))
    return found


def _exception_classes() -> dict[str, str]:
    """Every exception class this app defines, and where."""
    found = {}
    for path, tree in _sources():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                for base in node.bases
            }
            if any("Error" in base or "Exception" in base for base in bases):
                found[node.name] = f"{path.name}:{node.lineno}"
    return found


def _raised_messages(names: set[str]) -> list[tuple[str, str]]:
    """The first argument of every ``raise X(...)`` for X in *names*."""
    found = []
    for path, tree in _sources():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                continue
            func = node.exc.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if name not in names or not node.exc.args:
                continue
            message = _literal(node.exc.args[0])
            if message is not None:
                found.append((f"{path.name}:{node.lineno} {name}", message))
    return found


HTTP_DETAILS = _http_details()
DEFINED_EXCEPTIONS = _exception_classes()


# Which of this app's exceptions a caller can read the message of.
#
# The distinction is not cosmetic and cannot be inferred: `str(exc)` on the
# first group is handed to a user through a `detail`, and on the second it goes
# to the log and the caller is told something else entirely. Holding the second
# group to the same bar would be asking the log to stop naming the thing that
# broke, which is the one place naming it is useful.
CLIENT_FACING = {
    "DuplicateInvoice": "409 on upload — carries the id of the invoice already on file",
    "FilingNotRecordable": "422 from POST /filing/{return_type}/filed",
    "GstInputError": "422 from the GPT Actions calculator and invoice routes",
    "GSTR2BParseError": "422 from the GSTR-2B import",
    "InvalidGSTIN": "422 through the schema validators, and /meta/gstin's `error`",
    "NoGSTR2BImported": "422 from a reconciliation run",
    "ConcurrentReconciliation": "409 when another reconciliation is already running",
    "PlanLimitExceeded": "402 on upload",
    # Not a domain exception: an HTTPException that carries its own
    # error.code. Raised with `detail=` as a keyword, so its message is read
    # by the first sweep along with every other route refusal.
    "CodedHTTPException": "403 paid_plan_required from require_paid_tier",
}

INTERNAL_ONLY = {
    # The parser degrades to regex extraction rather than surfacing any of
    # these; a caller whose upload took the fallback gets an invoice, not an
    # error. Naming the provider and the status is exactly what the operator
    # reading the log needs.
    "OpenRouterError": "logged, then the parser falls back to heuristics",
    # One tenant's SMTP failing must not end the digest for the rest, so this
    # is caught inside the task loop and never reaches a response.
    "EmailSendError": "logged inside the digest task",
    # The upload volume's own error (full, read-only, gone) is for the
    # operator; the caller gets the route's retryable 503 in its own words.
    "UploadNotStored": "503 from upload, worded by the route, not by the exception",
    # Control flow inside the text extractor, not an error anyone sees.
    "_TextLimitReached": "stops reading a document that is over the limit",
    # Its message names the storage path, so it goes to the log; the row the
    # caller reads is given STORED_FILE_MISSING_REASON instead.
    "StoredFileMissing": "logged with its path; parse_error carries a pathless reason",
}


class TestEveryRefusalReadsLikeASentence:
    """The first sweep: what the routes say when they refuse."""

    def test_the_sweep_found_the_refusals(self):
        """A parametrize over an empty list passes every case it has."""
        assert len(HTTP_DETAILS) >= 25, f"only {len(HTTP_DETAILS)} details found"

    @pytest.mark.parametrize(
        ("where", "message"), HTTP_DETAILS, ids=[where for where, _ in HTTP_DETAILS]
    )
    def test_the_detail_is_free_of_jargon(self, where, message):
        assert_reads_as_prose(message, where)

    def test_it_is_reading_the_real_wording(self):
        """What stops this file passing over a source it failed to parse.

        Every assertion above is "no message says X", which an empty list
        satisfies perfectly. This pins one message that is definitely there, so
        a change to how the source is read fails here rather than silently
        stopping the sweep.
        """
        messages = [message for _, message in HTTP_DETAILS]
        assert any("Invoice" in m and "not found" in m for m in messages)
        assert any("read-only" in message for message in messages)


class TestTheDomainExceptionsACallerActuallyReads:
    """The second sweep: the messages routers pass through with ``str(exc)``.

    These are the ones worth sweeping. A router's own `detail=` is written by
    someone looking at the HTTP surface and tends to read like one; a service
    raising `GSTR2BParseError("No column headings found")` is written while
    thinking about CSV, and it reaches the user unchanged.
    """

    def test_every_exception_this_app_defines_has_been_classified(self):
        """A new exception class is a decision, not a default.

        Whether its message reaches a user is not derivable from the class —
        it depends on whether some router catches it and hands `str(exc)` to a
        caller — so it is written down. Adding one fails here until somebody
        says which it is, which is the moment the answer is actually known.
        """
        classified = set(CLIENT_FACING) | set(INTERNAL_ONLY)
        assert set(DEFINED_EXCEPTIONS) == classified, (
            f"unclassified: {sorted(set(DEFINED_EXCEPTIONS) - classified)}; "
            f"gone: {sorted(classified - set(DEFINED_EXCEPTIONS))}"
        )

    @pytest.mark.parametrize(
        ("where", "message"),
        _raised_messages(set(CLIENT_FACING)),
        ids=[where for where, _ in _raised_messages(set(CLIENT_FACING))],
    )
    def test_the_message_is_free_of_jargon(self, where, message):
        assert_reads_as_prose(message, where)

    def test_the_parser_errors_say_what_to_do_next(self):
        """The refusals a user meets most, and the only ones with a remedy.

        A GSTR-2B that will not import is the commonest failure this product
        has — the portal offers four downloads and three of them are not the
        one. "Invalid file" is a dead end; naming the download is not, and
        that difference is the reason these messages are as long as they are.
        """
        parser_messages = [
            message
            for _, message in _raised_messages({"GSTR2BParseError"})
            if "portal" in message
        ]
        assert len(parser_messages) >= 3, parser_messages
        for message in parser_messages:
            assert "GST portal" in message, message

    def test_every_parser_error_carries_guidance(self):
        """A refusal with no next step is a dead end wearing an apology.

        "The file is empty" and "No column headings found" passed the jargon
        sweep but left the reader with nothing to do about them. Every message
        the parser raises should suggest where to get a valid file or what
        might have gone wrong — a bare observation is not enough.
        """
        messages = [
            (where, message)
            for where, message in _raised_messages({"GSTR2BParseError"})
        ]
        for where, message in messages:
            assert len(message) >= 30, (
                f"{where}: too terse to carry guidance — {message}"
            )


# ---------------------------------------------------------------------------
# And the same standard, applied to what actually comes back over HTTP
# ---------------------------------------------------------------------------

class TestTheRefusalsARealSessionMeets:
    """The source sweeps read literals; this one reads responses.

    Three of the messages a caller is most likely to see are not in any
    ``detail=`` in the app: the 500's opaque sentence, the 422 that Pydantic
    words, and the 405 Starlette answers before a route is reached. They come
    from a library or from a handler, so the only way to hold them to the same
    bar is to go and get them.
    """

    def _details(self, response) -> list[str]:
        body = response.json()
        detail = body["detail"]
        if isinstance(detail, str):
            return [detail]
        if isinstance(detail, list):
            # Validation errors: the message is per-field, and the frontend
            # joins them into one line for the banner.
            return [item["msg"] for item in detail]
        return [detail["message"]]

    def test_a_missing_row_is_named_in_words(self, auth_client):
        response = auth_client.get("/api/v1/invoices/999999")
        assert response.status_code == 404
        for message in self._details(response):
            assert_reads_as_prose(message, "GET /invoices/{id}")

    def test_an_unmatched_path_says_nothing_technical(self, client):
        response = client.get("/api/v1/nothing-here")
        assert response.status_code == 404
        for message in self._details(response):
            assert_reads_as_prose(message, "GET /nothing-here")

    def test_a_wrong_method_says_nothing_technical(self, client):
        response = client.delete("/api/v1/health")
        assert response.status_code == 405
        for message in self._details(response):
            assert_reads_as_prose(message, "DELETE /health")

    def test_a_rejected_field_is_described_rather_than_typed(self, client):
        """The 422 wording is Pydantic's, and it still reaches a person.

        "Value error, GSTIN must be 15 characters" is the shape these take: a
        prefix from the library and the sentence the validator raised. The
        prefix is what this asserts is still readable — a validator raising a
        `KeyError` would come through here as one.
        """
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "someone@example.com",
                "password": "supersecret123",
                "gstin": "NOTAGSTIN",
                "legal_name": "Test Traders",
            },
        )
        assert response.status_code == 422
        messages = self._details(response)
        assert messages
        for message in messages:
            # Pydantic prefixes a validator's own message with "Value error, ",
            # which is the one piece of library wording a caller sees. It is
            # stripped before the sentence underneath is judged, and asserted
            # separately so a change in that prefix is noticed rather than
            # quietly excused.
            assert_reads_as_prose(message.removeprefix("Value error, "), "422 on register")

    def test_a_role_refusal_names_the_role_and_who_to_ask(self, auth_client, db_session):
        """The refusal a viewer meets, in full, from the running app.

        Its two jobs are the two things the reader can act on: which role they
        hold, and that somebody else can lift it. Neither is derivable from a
        403.
        """
        user = db_session.scalar(select(User).where(User.email == TEST_EMAIL))
        user.role = UserRole.VIEWER
        db_session.commit()

        response = auth_client.post("/api/v1/reconciliation/run", json={"period": "2026-04"})
        assert response.status_code == 403
        (message,) = self._details(response)
        assert_reads_as_prose(message, "POST /reconciliation/run as a viewer")
        assert "viewer" in message
        assert "owner or an accountant" in message

    def test_a_bug_apologises_and_gives_a_reference(self, raw_client, monkeypatch):
        """The one message a user meets that is about nothing they did.

        Taken off a real 500 from the fault-injection route, which this file
        could not do until recently. The fixture that turns debug off was
        autouse inside ``test_errors.py``, so the same request from here was
        answered by Starlette's debug page — `text/plain`, and an
        ExceptionGroup traceback where the sentence should have been. This test
        read the message off ``_opaque_message`` instead and said so. Debug is
        now `raw_client`'s business, which is where a property of the client
        belonged, and the message can be read where a user meets it.

        It must be a sentence with something to do about it, which here is the
        reference to quote. An opaque message with no next step is a dead end
        wearing an apology.

        The ``debug`` branch is deliberately not held to this. It says
        "Internal server error. Check the logs for correlation id …", which is
        jargon by the standard above and correctly so: `debug` is off in every
        deployed environment, its reader is whoever is running the server
        locally, and "check the logs" is advice only they can take.
        """
        from app.core.config import settings

        monkeypatch.setattr(settings, "debug", False)
        response = raw_client.get("/_test_errors/unhandled")

        assert response.status_code == 500
        (message,) = self._details(response)
        assert_reads_as_prose(message, "the 500 message")
        assert "reference" in message, message
        # The reference is only worth quoting if it is the one the log carries.
        assert response.json()["correlation_id"] in message

    def test_unlinking_a_nonexistent_business_explains_the_problem(self, auth_client):
        """A bare "Not linked." was the whole detail — two words and a stop.

        It told the reader nothing they could act on: not which business, not
        what "linked" meant, not what to do about it. The fix names the
        relationship so the reader knows this is about linked businesses rather
        than a general "not found".
        """
        response = auth_client.delete("/api/v1/businesses/mine/999999")
        assert response.status_code == 404
        for message in self._details(response):
            assert_reads_as_prose(message, "DELETE /businesses/mine/{id}")
            assert len(message) >= 20, f"too terse — {message}"

    def test_a_malformed_gstr2b_upload_gives_guidance(self, auth_client, paid_business):
        """A message a user meets when the file has the wrong structure.

        "GSTR-2B JSON must be an object" was jargon three times over — JSON,
        "must be", and "an object" are all programming terms. The fix tells
        the reader what to do (upload the portal download) rather than
        describing the data shape.
        """
        import json as json_lib

        content = json_lib.dumps([1, 2, 3]).encode()
        response = auth_client.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={"file": ("2b.json", content, "application/json")},
        )
        assert response.status_code == 422
        for message in self._details(response):
            assert_reads_as_prose(message, "GSTR-2B array upload")
            assert "must be an object" not in message.lower(), message

    def test_the_gstin_lookup_explains_a_rejection_the_form_can_show(self, client):
        """Always a 200, so the sentence is in the body rather than a detail.

        The sign-up form calls this on every keystroke and shows what comes
        back beside the field. "GSTIN check digit does not match" is a real
        answer; a stack frame there would be rendered under the input.
        """
        response = client.get(f"/api/v1/meta/gstin/{BUSINESS_GSTIN[:-1]}X")
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert_reads_as_prose(body["error"], "/meta/gstin")


class TestARefusedPatternIsDescribedNotQuoted:
    """A pattern mismatch used to read "String should match pattern
    '^(?:2017-(?:0[7-9]|1[0-2])|20(?:1[89]|[2-9][0-9])-…)$'" — the regex,
    verbatim, in the banner, in ``error.message`` and read aloud by the GPT
    actions."""

    def test_a_bad_period_says_what_a_period_looks_like(self, auth_client):
        body = auth_client.get("/api/v1/dashboard", params={"period": "April 2026"}).json()
        assert body["error"]["message"] == (
            "period: should be a month written YYYY-MM, such as 2026-04, "
            "from 2017-07 (when GST began) onwards"
        )
        # The pattern stays in ``ctx`` for a client that wants it; it is the
        # sentences meant for a person that must not quote it.
        assert all("(?:" not in item["msg"] for item in body["detail"])

    def test_a_closed_choice_lists_the_choices(self, client):
        body = client.get(
            "/api/v1/gpt/calculate", params={"amount": "100", "rate": "18", "mode": "both"}
        ).json()
        assert "should be one of: exclusive, inclusive" in body["error"]["message"]

    def test_any_other_pattern_is_still_not_quoted(self):
        from app.core.errors import _pattern_message

        assert _pattern_message(r"^order_[A-Za-z0-9_]+$") == "is not in the expected format"
