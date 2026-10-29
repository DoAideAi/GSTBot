"""The correlation id and the redaction that keeps secrets out of the logs.

Two things are actually being defended here. The first is that a support ticket
can be traced: one id, bound at the edge, on every line the request produces.
The second is that the id is attacker-controlled — it arrives in a header — so
it must never be able to forge a log line or pad a log file.
"""
from __future__ import annotations

import json
import logging

import pytest

from app.core.logging import (
    AccessQueryFilter,
    ConsoleFormatter,
    CorrelationIdFilter,
    JsonFormatter,
    bind_correlation_id,
    configure_logging,
    get_correlation_id,
    new_correlation_id,
    reset_correlation_id,
    sanitize_correlation_id,
    set_correlation_id,
)


@pytest.fixture(autouse=True)
def _clear_context():
    """Never leak a bound id into the next test."""
    token = set_correlation_id("")
    yield
    reset_correlation_id(token)


def _record(**extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestSanitizeCorrelationId:
    def test_a_normal_id_is_accepted(self):
        assert sanitize_correlation_id("9f2c1a0b4e7d5a63") == "9f2c1a0b4e7d5a63"

    def test_a_uuid_with_dashes_is_accepted(self):
        # What an upstream gateway most often sends.
        value = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
        assert sanitize_correlation_id(value) == value

    @pytest.mark.parametrize(
        "forged",
        [
            "abc\nERROR fake log line",
            "abc\r\nERROR fake log line",
            "abc def",           # a space splits a console line into two fields
            "abc\x00def",
            "id;rm -rf /",
            "<script>alert(1)</script>",
            "abc def",      # a Unicode line separator, which some viewers honour
        ],
    )
    def test_anything_that_could_forge_a_line_is_rejected_outright(self, forged):
        # Rejected rather than escaped: a request id has no reason to contain
        # any of this, so there is nothing to preserve by escaping it.
        assert sanitize_correlation_id(forged) == ""

    def test_an_overlong_id_is_truncated_not_rejected(self):
        # An unbounded id would let a caller pad every line in the file.
        assert len(sanitize_correlation_id("a" * 500)) == 64

    def test_empty_and_none_give_empty(self):
        assert sanitize_correlation_id(None) == ""
        assert sanitize_correlation_id("") == ""
        assert sanitize_correlation_id("   ") == ""


class TestBinding:
    def test_bind_generates_one_when_absent(self):
        assert len(bind_correlation_id(None)) == 16

    def test_bind_reuses_a_valid_supplied_id(self):
        assert bind_correlation_id("upstream-id-1") == "upstream-id-1"

    def test_bind_replaces_a_hostile_id_rather_than_failing(self):
        # The worker must still be traceable; it just gets a fresh id.
        result = bind_correlation_id("bad\nid")
        assert result != "bad\nid"
        assert len(result) == 16

    def test_the_bound_id_is_what_get_returns(self):
        bind_correlation_id("abc123")
        assert get_correlation_id() == "abc123"

    def test_ids_are_unique(self):
        assert len({new_correlation_id() for _ in range(500)}) == 500


class TestJsonFormatter:
    def test_the_correlation_id_is_on_every_line(self):
        bind_correlation_id("trace-me")
        record = _record()
        CorrelationIdFilter().filter(record)
        payload = json.loads(JsonFormatter().format(record))
        assert payload["correlation_id"] == "trace-me"

    def test_a_line_outside_a_request_still_has_the_field(self):
        # A dash rather than a missing key: a log query that filters on the
        # field should not silently drop worker startup lines.
        record = _record()
        CorrelationIdFilter().filter(record)
        assert json.loads(JsonFormatter().format(record))["correlation_id"] == "-"

    def test_extra_fields_are_promoted_to_top_level(self):
        payload = json.loads(JsonFormatter().format(_record(invoice_id=42)))
        assert payload["invoice_id"] == 42

    def test_args_are_interpolated_into_the_message(self):
        assert json.loads(JsonFormatter().format(_record()))["message"] == "hello world"

    @pytest.mark.parametrize(
        "key",
        ["password", "token", "authorization", "api_key", "jwt_secret", "hashed_password"],
    )
    def test_secrets_are_redacted_by_key_name(self, key):
        # Logs are read by more people than the database is.
        payload = json.loads(JsonFormatter().format(_record(**{key: "hunter2"})))
        assert payload[key] == "[redacted]"
        assert "hunter2" not in json.dumps(payload)

    @pytest.mark.parametrize("key", ["recipient", "email_address", "email"])
    def test_pii_fields_are_redacted_by_key_name(self, key):
        payload = json.loads(JsonFormatter().format(_record(**{key: "owner@example.com"})))
        assert payload[key] == "[redacted]"
        assert "owner@example.com" not in json.dumps(payload)

    @pytest.mark.parametrize(
        "key, value",
        [
            ("phone", "+919876543210"),
            ("pan", "ABCDE1234F"),
            ("signature", "hmac_sha256_value_here"),
        ],
    )
    def test_sensitive_indian_tax_fields_are_redacted(self, key, value):
        payload = json.loads(JsonFormatter().format(_record(**{key: value})))
        assert payload[key] == "[redacted]"
        assert value not in json.dumps(payload)

    def test_redaction_is_case_insensitive(self):
        payload = json.loads(JsonFormatter().format(_record(Authorization="Bearer abc")))
        assert payload["Authorization"] == "[redacted]"

    def test_a_secret_nested_in_a_dict_is_redacted_too(self):
        payload = json.loads(JsonFormatter().format(_record(context={"password": "hunter2"})))
        assert payload["context"]["password"] == "[redacted]"
        assert "hunter2" not in json.dumps(payload)

    def test_an_unserialisable_value_does_not_lose_the_line(self):
        # A formatter that raises takes the log line with it, and the line is
        # usually the one explaining the failure.
        class Opaque:
            def __repr__(self) -> str:
                return "<opaque>"

        payload = json.loads(JsonFormatter().format(_record(thing=Opaque())))
        assert payload["thing"] == "<opaque>"

    def test_output_is_exactly_one_line(self):
        # One JSON object per line is the contract an aggregator parses; a
        # newline inside a value would split one event into two.
        formatted = JsonFormatter().format(_record(note="a\nb"))
        assert "\n" not in formatted
        assert json.loads(formatted)["note"] == "a\nb"

    def test_an_exception_is_rendered_into_the_payload(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = _record()
            record.exc_info = sys.exc_info()
        payload = json.loads(JsonFormatter().format(record))
        assert "ValueError: boom" in payload["exception"]


class TestConsoleFormatter:
    def test_the_id_is_in_front_of_the_message(self):
        bind_correlation_id("abc123")
        record = _record()
        CorrelationIdFilter().filter(record)
        assert "[abc123]" in ConsoleFormatter().format(record)


class TestConfigureLogging:
    def test_it_is_idempotent(self):
        # uvicorn and Celery both install their own handler; calling this from
        # every entrypoint must not mean every line twice.
        configure_logging("INFO", "json")
        configure_logging("INFO", "json")
        assert len(logging.getLogger().handlers) == 1

    def test_the_level_is_applied(self):
        configure_logging("WARNING", "console")
        assert logging.getLogger().level == logging.WARNING
        configure_logging("INFO", "console")

    def test_sqlalchemy_echo_is_kept_quiet(self):
        configure_logging("DEBUG", "console")
        assert logging.getLogger("sqlalchemy.engine").level == logging.WARNING
        configure_logging("INFO", "console")


class TestJsonFormatterEdges:
    """The shapes ``extra=`` can carry that ``json.dumps`` would refuse."""

    def test_a_list_of_values_survives_as_a_list(self):
        # The sweeps log the periods they touched, so a sequence in ``extra``
        # is routine rather than exotic. Flattening it to ``str`` would make
        # the field unqueryable in whatever ingests these lines.
        record = _record(periods=["2026-04", "2026-05"])
        payload = json.loads(JsonFormatter().format(record))

        assert payload["periods"] == ["2026-04", "2026-05"]

    def test_a_set_becomes_a_list_rather_than_failing_to_serialise(self):
        record = _record(states={"27"})
        payload = json.loads(JsonFormatter().format(record))

        assert payload["states"] == ["27"]

    def test_a_secret_nested_inside_a_list_of_dicts_is_still_redacted(self):
        """Redaction has to reach the value wherever it is, not just at the top.

        A single-element list is exactly how a batch of one arrives, and a
        password that is safe at depth 0 and leaked at depth 2 is worse than
        no redaction at all — nobody would think to check.
        """
        record = _record(accounts=[{"user": "ops", "password": "hunter2"}])
        payload = json.loads(JsonFormatter().format(record))

        assert "hunter2" not in json.dumps(payload)
        assert payload["accounts"][0]["user"] == "ops"

    def test_a_stack_trace_is_carried_on_its_own_key(self):
        # ``stack_info=True`` is what a "this should not have happened" log
        # asks for, and dropping the stack makes that line useless.
        record = _record()
        record.stack_info = 'Stack (most recent call last):\n  File "x.py", line 1\n'
        payload = json.loads(JsonFormatter().format(record))

        assert "x.py" in payload["stack"]

    def test_an_object_json_cannot_encode_is_stringified_not_raised(self):
        """A formatter that raises loses the line it was trying to write."""
        record = _record(supplier=object())
        payload = json.loads(JsonFormatter().format(record))

        assert payload["supplier"].startswith("<object object at")


class TestCorrelationIdFilterLeavesAnExplicitIdAlone:
    def test_an_id_already_on_the_record_is_not_overwritten(self):
        """The Celery task stamps the publishing request's id onto the record.

        Overwriting it with the worker's own context would break the only
        thread tying a queued task back to the request that queued it.
        """
        bind_correlation_id("from-the-api")
        record = _record(correlation_id="from-the-publisher")

        CorrelationIdFilter().filter(record)

        assert record.correlation_id == "from-the-publisher"


class TestIdentifiersAreMaskedWhereverTheyAppear:
    """Key redaction misses a value that travels somewhere else — a GSTIN in a
    URL path above all, since the public lookups take one there."""

    GSTIN = "27AAPFU0939F1ZV"

    def test_a_gstin_in_the_message_keeps_its_state_and_check_characters(self):
        record = _record()
        record.msg = "GET /api/v1/meta/gstin/%s 200"
        record.args = (self.GSTIN,)
        line = JsonFormatter().format(record)
        assert "AAPFU0939F" not in line
        assert "/meta/gstin/27**********1ZV" in json.loads(line)["message"]

    def test_a_gstin_under_an_unlisted_key_is_masked_too(self):
        line = JsonFormatter().format(_record(http_path=f"/api/v1/gpt/gstin/{self.GSTIN}"))
        assert json.loads(line)["http_path"] == "/api/v1/gpt/gstin/27**********1ZV"

    def test_a_lower_case_gstin_is_still_one(self):
        line = JsonFormatter().format(_record(http_path="/api/v1/meta/gstin/27aapfu0939f1zv"))
        assert "aapfu0939f" not in line.lower()

    def test_a_bare_pan_is_masked_whole(self):
        line = JsonFormatter().format(_record(note="holder AAPFU0939F filed"))
        assert json.loads(line)["note"] == "holder ********** filed"

    def test_the_console_format_is_masked_as_well(self):
        record = _record(correlation_id="-")
        record.msg = "lookup %s"
        record.args = (self.GSTIN,)
        assert "AAPFU0939F" not in ConsoleFormatter().format(record)

    def test_a_traceback_is_masked_as_well(self):
        try:
            raise ValueError(f"bad GSTIN {self.GSTIN}")
        except ValueError:
            import sys

            record = _record()
            record.exc_info = sys.exc_info()
        assert "AAPFU0939F" not in JsonFormatter().format(record)

    @pytest.mark.parametrize(
        "text",
        [
            "correlation 4f1c2a9b8e7d6c5b",
            "payment pay_NxABCDE1234FzQ",  # inside a longer id: no word boundary
            "order receipt rpt_12_34",
            "INV-2026-0042",
        ],
    )
    def test_ids_that_merely_share_the_alphabet_are_left_alone(self, text):
        assert json.loads(JsonFormatter().format(_record(note=text)))["note"] == text


class TestAccessQueryFilter:
    """uvicorn's access line logs the full path, and some queries are credentials."""

    def _access(self, full_path: str) -> logging.LogRecord:
        # The shape uvicorn.protocols.http emits: client, method, path, version, status.
        return logging.LogRecord(
            name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
            msg='%s - "%s %s HTTP/%s" %d',
            args=("1.2.3.4:5678", "GET", full_path, "1.1", 200), exc_info=None,
        )

    @pytest.mark.parametrize(
        "full_path",
        [
            "/api/v1/unsubscribe?email=a%40b.in&token=" + "f" * 64,
            "/api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=s3cr3t&hub.challenge=1",
            "/api/v1/auth/oauth/google/callback?code=4%2F0Abc&state=xyz",
        ],
    )
    def test_the_query_is_dropped_and_the_path_kept(self, full_path):
        record = self._access(full_path)
        assert AccessQueryFilter().filter(record) is True
        line = record.getMessage()
        assert "?" not in line
        assert full_path.split("?")[0] in line
        for secret in ("f" * 64, "s3cr3t", "4%2F0Abc", "xyz", "a%40b.in"):
            assert secret not in line

    def test_a_path_without_a_query_is_untouched(self):
        record = self._access("/api/v1/health")
        AccessQueryFilter().filter(record)
        assert record.args[2] == "/api/v1/health"

    def test_other_loggers_are_left_alone(self):
        record = _record()
        record.args = ("a?b",)
        AccessQueryFilter().filter(record)
        assert record.args == ("a?b",)

    def test_configure_logging_installs_it(self):
        configure_logging("INFO", "json")
        handler = logging.getLogger().handlers[0]
        assert any(isinstance(f, AccessQueryFilter) for f in handler.filters)


class TestPostgresDoesNotGetToQuoteTheRow:
    """P38 M2: a constraint violation logged the values it collided on.

    Postgres explains a violation in the exception's own text, and every
    handler logs these exceptions with their traceback. A duplicate signup
    logged ``Key (email)=(owner@example.com) already exists``, and a NOT NULL
    or CHECK failure logged ``Failing row contains (...)``, the whole row with
    its password hash. ``hide_parameters`` (P36 M2) keeps SQLAlchemy's
    ``[parameters: ...]`` out, but this text is the server's. The column names
    stay, because they say what went wrong. The values go.
    """

    UNIQUE = (
        'duplicate key value violates unique constraint "ix_users_email"\n'
        "DETAIL:  Key (email)=(owner@example.com) already exists."
    )
    FOREIGN = (
        'insert or update on table "invoices" violates foreign key constraint\n'
        'DETAIL:  Key (business_id, supplier_id)=(7, 912) is not present in table "suppliers".'
    )
    ROW = (
        'null value in column "full_name" violates not-null constraint\n'
        "DETAIL:  Failing row contains (12, owner@example.com, $2b$12$abcdefhash, null)."
    )

    @staticmethod
    def _formatted(formatter, message: str) -> str:
        try:
            raise RuntimeError(message)
        except RuntimeError:
            import sys

            record = _record()
            record.exc_info = sys.exc_info()
        CorrelationIdFilter().filter(record)
        return formatter.format(record)

    @pytest.mark.parametrize("formatter", [JsonFormatter(), ConsoleFormatter()],
                             ids=["json", "console"])
    def test_a_unique_violation_names_the_column_not_the_value(self, formatter):
        line = self._formatted(formatter, self.UNIQUE)
        assert "owner@example.com" not in line
        assert "Key (email)=(" in line and "already exists" in line

    @pytest.mark.parametrize("formatter", [JsonFormatter(), ConsoleFormatter()],
                             ids=["json", "console"])
    def test_a_foreign_key_violation_keeps_its_table_and_drops_the_ids(self, formatter):
        line = self._formatted(formatter, self.FOREIGN)
        assert "912" not in line
        assert "Key (business_id, supplier_id)=(" in line and "suppliers" in line

    @pytest.mark.parametrize("formatter", [JsonFormatter(), ConsoleFormatter()],
                             ids=["json", "console"])
    def test_a_failing_row_is_not_written_out(self, formatter):
        line = self._formatted(formatter, self.ROW)
        assert "owner@example.com" not in line and "abcdefhash" not in line
        assert "Failing row contains (" in line and "not-null constraint" in line
