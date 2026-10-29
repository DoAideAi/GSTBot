"""Every parse leaves one structured line, and it names the tenant.

Until GB003 a parse that *worked* logged nothing: the task's return value went
to a result backend nobody reads, so the one number that says whether the
model provider is earning its keep — how often extraction fell back to the
heuristics — could only be had by querying ``parsed_with`` off the rows. The
failure line existed but named the invoice id alone, in a product where every
support question starts with which business asked it.

Written against the upload route rather than ``process_invoice`` directly,
because with no broker in the test environment the upload parses inline and
that is the path an ordinary deployment without Redis takes too.
"""
from __future__ import annotations

import logging

import pytest

from app.models.invoice import InvoiceStatus
from app.services import invoice_service
from tests.test_invoice_duplicate_writeback import invoice_text, upload

_LOGGER = "app.services.invoice_service"


def _outcome_line(caplog, invoice_id: int) -> logging.LogRecord:
    # "Invoice stored" names the same invoice and comes first; it is the
    # upload's line, not the parse's.
    return next(
        record
        for record in caplog.records
        if record.name == _LOGGER
        and getattr(record, "invoice_id", None) == invoice_id
        and record.getMessage() != "Invoice stored"
    )


# Not fixtures: a record logged while a fixture is being set up lands in
# caplog's "setup" phase, and ``caplog.records`` reads only the call phase.
def _parse_one(auth_client, caplog) -> tuple[logging.LogRecord, dict]:
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        body = upload(auth_client, invoice_text(), name="one.txt").json()["invoice"]
    return _outcome_line(caplog, body["id"]), body


class TestAParseThatWorked:
    def test_it_is_logged_at_all(self, auth_client, caplog):
        record, body = _parse_one(auth_client, caplog)
        assert body["status"] == InvoiceStatus.PARSED.value
        assert record.levelno == logging.INFO
        assert record.getMessage() == f"Invoice {body['id']} parsed"

    def test_it_names_the_business_and_the_path_taken(self, auth_client, business, caplog):
        record, body = _parse_one(auth_client, caplog)
        assert record.business_id == business.id
        assert record.status == InvoiceStatus.PARSED.value
        # No key in the test environment, so the heuristics did the work; a
        # dashboard grouping on this field is how a fallback rate is read.
        assert record.parsed_with == body["parsed_with"]
        assert record.confidence == body["extraction_confidence"]
        assert record.content_type == "text/plain"

    def test_it_is_timed(self, auth_client, caplog):
        record, _ = _parse_one(auth_client, caplog)
        assert isinstance(record.duration_ms, float)
        assert record.duration_ms >= 0


class TestAParseThatBlewUp:
    @pytest.fixture()
    def exploding_parser(self, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("tesseract segfaulted")

        monkeypatch.setattr(invoice_service, "parse_invoice", boom)

    def test_it_still_carries_the_traceback(self, auth_client, exploding_parser, caplog):
        # ``logger.exception`` became ``logger.error(exc_info=exc)`` so the
        # line could be written after the write-back; the stack must not
        # have been lost in the move.
        record, body = _parse_one(auth_client, caplog)
        assert body["status"] == InvoiceStatus.FAILED.value
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None
        assert record.exc_info[0] is RuntimeError

    def test_it_names_the_business_and_the_status_the_row_was_left_in(
        self, auth_client, business, exploding_parser, caplog
    ):
        record, _ = _parse_one(auth_client, caplog)
        assert record.business_id == business.id
        assert record.status == InvoiceStatus.FAILED.value


class TestAParseThatFoundADuplicate:
    def test_the_line_names_both_rows_and_the_business(self, auth_client, business, caplog):
        first = upload(auth_client, invoice_text(), name="original.txt").json()["invoice"]
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            second = upload(
                auth_client, invoice_text(total="531001.00"), name="rescan.txt"
            ).json()["invoice"]
        assert second["status"] == InvoiceStatus.FAILED.value

        line = _outcome_line(caplog, second["id"])
        assert line.business_id == business.id
        assert line.duplicate_of == first["id"]
        assert line.status == InvoiceStatus.FAILED.value


class TestAParseOvertakenByAnEdit:
    """P24 M8: invoice_parse_superseded was counted but not one of the known
    metrics events, and count() raises on an unknown name. So every parse
    an edit had overtaken, which is a correct outcome, was caught as a failure:
    logged at ERROR with a traceback and counted as invoice_parse_failed."""

    def test_it_is_logged_as_superseded_not_as_a_failure(
        self, auth_client, monkeypatch, caplog
    ):
        counted = []
        monkeypatch.setattr(invoice_service, "_still_processing", lambda db, invoice_id: False)
        monkeypatch.setattr(invoice_service.metrics, "get_redis", lambda: None)
        real_count = invoice_service.metrics.count
        monkeypatch.setattr(
            invoice_service.metrics,
            "count",
            lambda event, n=1, **kw: (counted.append(event), real_count(event, n, **kw)),
        )
        with caplog.at_level(logging.INFO, logger=_LOGGER):
            upload(auth_client, invoice_text(), name="overtaken.txt")
        messages = [r.getMessage() for r in caplog.records if r.name == _LOGGER]
        assert any("changed while it was parsed" in m for m in messages)
        assert not [r for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.ERROR]
        assert counted == ["invoice_parse_superseded"]


def test_every_counted_event_is_a_known_one():
    """The guard in count() only fires when the line runs; this reads them all."""
    import re
    from pathlib import Path

    from app.core import metrics

    app_dir = Path(metrics.__file__).parents[1]
    named = {
        match.group(1)
        for path in app_dir.rglob("*.py")
        for match in re.finditer(r'metrics\.count\(\s*"([a-z_]+)"', path.read_text())
    }
    assert named, "found no metrics.count calls to check"
    assert named <= set(metrics.EVENTS), named - set(metrics.EVENTS)
