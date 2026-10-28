"""`process_invoice` promises never to raise. This is that promise tested.

It runs on a Celery worker with nobody waiting on the result, so an exception
there is a log line nobody reads and a row left in PROCESSING forever. Every
failure has to land on the invoice instead, as FAILED with a reason — that row
is the only channel the user has.

The case exercised here is the stored file going missing, which is not
hypothetical: the API writes the upload and the worker reads it back, so the
two containers must share the volume. Get that wrong in a deployment and every
invoice takes this path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.models.invoice import Invoice, InvoiceStatus
from app.services import invoice_service


def upload(client, text: str, *, name: str = "invoice.txt"):
    return client.post(
        "/api/v1/invoices/upload",
        files={"file": (name, text.encode(), "text/plain")},
        data={"invoice_type": "purchase"},
    )


@pytest.fixture()
def orphaned(auth_client, db_session, sample_invoice_text):
    """A parsed invoice whose stored file has been deleted underneath it."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    invoice = db_session.get(Invoice, invoice_id)
    Path(invoice.storage_path).unlink()
    # raw_text is the other way process_invoice can get at the document; this
    # is about the file being gone, so both have to be.
    invoice.raw_text = None
    db_session.commit()
    return invoice_id


class TestAStoredFileThatIsGone:
    def test_reparsing_it_does_not_500(self, auth_client, orphaned):
        """The caller gets an answer. An unhandled exception here would be a
        500 on a button the UI offers for every failed invoice."""
        response = auth_client.post(f"/api/v1/invoices/{orphaned}/reparse")

        assert response.status_code == 200, response.text

    def test_the_row_is_marked_failed(self, auth_client, orphaned):
        body = auth_client.post(f"/api/v1/invoices/{orphaned}/reparse").json()

        assert body["status"] == InvoiceStatus.FAILED.value

    def test_it_does_not_linger_in_processing(self, auth_client, orphaned):
        body = auth_client.post(f"/api/v1/invoices/{orphaned}/reparse").json()

        assert body["status"] != InvoiceStatus.PROCESSING.value

    def test_the_reason_says_the_file_is_missing_without_naming_the_path(
        self, auth_client, orphaned, db_session
    ):
        """``parse_error`` goes back to the caller, and the server's storage
        layout is not theirs to read. It says what to do instead."""
        body = auth_client.post(f"/api/v1/invoices/{orphaned}/reparse").json()

        assert body["parse_error"] == invoice_service.STORED_FILE_MISSING_REASON
        assert db_session.get(Invoice, orphaned).storage_path not in body["parse_error"]

    def test_the_path_is_in_the_log_for_the_operator(
        self, auth_client, orphaned, db_session, caplog
    ):
        """An operator debugging a bad volume mount needs the path, and gets it
        where operators look."""
        with caplog.at_level("ERROR"):
            auth_client.post(f"/api/v1/invoices/{orphaned}/reparse")

        assert db_session.get(Invoice, orphaned).storage_path in caplog.text

    def test_the_service_returns_the_invoice_rather_than_raising(self, db_session, orphaned):
        """Called directly, the way the worker calls it."""
        invoice = db_session.get(Invoice, orphaned)

        result = invoice_service.process_invoice(db_session, invoice)

        assert result.id == orphaned
        assert result.status == InvoiceStatus.FAILED

    def test_the_session_still_works_afterwards(self, auth_client, orphaned, sample_invoice_text):
        """A worker reuses its session for the next task in the queue."""
        auth_client.post(f"/api/v1/invoices/{orphaned}/reparse")

        response = upload(
            auth_client,
            sample_invoice_text.replace("INV-2026-0042", "INV-2026-0500"),
            name="next.txt",
        )

        assert response.status_code == 201, response.text
        assert response.json()["invoice"]["status"] == InvoiceStatus.PARSED.value


class TestAParserThatBlowsUp:
    """Anything unexpected out of the extraction stack lands on the row too."""

    @pytest.fixture()
    def exploding_parser(self, monkeypatch):
        def boom(**kwargs):
            raise RuntimeError("tesseract segfaulted")

        monkeypatch.setattr(invoice_service, "parse_invoice", boom)

    def test_the_upload_still_succeeds(self, auth_client, sample_invoice_text, exploding_parser):
        response = upload(auth_client, sample_invoice_text)

        assert response.status_code == 201, response.text

    def test_the_failure_is_recorded_on_the_row(
        self, auth_client, sample_invoice_text, exploding_parser
    ):
        body = upload(auth_client, sample_invoice_text).json()["invoice"]

        assert body["status"] == InvoiceStatus.FAILED.value
        assert "tesseract segfaulted" in body["parse_error"]

    def test_the_reason_is_truncated_rather_than_unbounded(
        self, auth_client, db_session, sample_invoice_text, monkeypatch
    ):
        """`parse_error` is a column, and a repr of a huge payload would
        otherwise be what fails the insert."""
        def boom(**kwargs):
            raise RuntimeError("x" * 5000)

        monkeypatch.setattr(invoice_service, "parse_invoice", boom)

        invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

        assert len(db_session.get(Invoice, invoice_id).parse_error) == 2000



class TestAFailureReasonLeaksNothingAboutTheServer:
    """Whatever the extraction stack raises lands on a row the API returns."""

    @staticmethod
    def _raising(monkeypatch, exc):
        def boom(**kwargs):
            raise exc

        monkeypatch.setattr(invoice_service, "parse_invoice", boom)

    def test_a_database_error_does_not_show_its_sql(
        self, monkeypatch, auth_client, sample_invoice_text
    ):
        from sqlalchemy.exc import DataError

        self._raising(
            monkeypatch,
            DataError(
                "UPDATE invoices SET taxable_value=? WHERE invoices.id = ?",
                ("999999999999999999", 7),
                Exception("numeric field overflow"),
            ),
        )

        reason = upload(auth_client, sample_invoice_text).json()["invoice"]["parse_error"]

        assert "SQL" not in reason
        assert "UPDATE invoices" not in reason
        assert "999999999999999999" not in reason
        assert "problem on our side" in reason

    def test_an_os_error_does_not_show_its_path(
        self, monkeypatch, auth_client, sample_invoice_text
    ):
        self._raising(
            monkeypatch,
            PermissionError(13, "Permission denied", "/srv/gst/uploads/3/a1b2.pdf"),
        )

        reason = upload(auth_client, sample_invoice_text).json()["invoice"]["parse_error"]

        assert "/srv" not in reason
        assert "Permission denied" not in reason

    def test_a_librarys_own_message_keeps_its_words_but_not_its_paths(
        self, monkeypatch, auth_client, sample_invoice_text
    ):
        self._raising(
            monkeypatch,
            RuntimeError("tesseract failed on /usr/lib/tesseract/eng.traineddata"),
        )

        reason = upload(auth_client, sample_invoice_text).json()["invoice"]["parse_error"]

        assert reason == "tesseract failed on <path>"
