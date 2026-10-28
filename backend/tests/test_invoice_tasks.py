"""The worker-side half of an invoice upload.

An upload is answered 201 before anything is extracted, so this task is where
the actual work happens and it runs with nobody waiting on it. That changes
what correctness means: there is no caller to return an error to, so the only
outcomes that matter are "the row ends up in a state the user can act on" and
"the worker's database connection is released".

The task body is called directly rather than through a broker. What is under
test is this function's own decisions — the missing-row guard, the retry
boundary, the session lifecycle — and a live Redis would test Celery's
transport instead.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.invoice import Invoice, InvoiceSource, InvoiceStatus, InvoiceType
from app.services import invoice_service
from app.tasks import invoice_tasks
from app.tasks.invoice_tasks import parse_invoice_task


class _Retry(Exception):
    """Stands in for celery.exceptions.Retry, which is what .retry() raises."""


@pytest.fixture()
def task(monkeypatch):
    """Record ``self.retry()`` on the real registered task.

    The task is invoked as ``parse_invoice_task(invoice_id)``: Celery binds
    ``self`` itself, so there is no fake to hand in. Patching retry on the
    registered object is what makes the retry decision observable without a
    broker, and it keeps the code under test the object the worker runs.
    """
    retries: list[BaseException | None] = []

    def fake_retry(exc=None, **kwargs):
        retries.append(exc)
        return _Retry(str(exc))

    monkeypatch.setattr(parse_invoice_task, "retry", fake_retry)
    return SimpleNamespace(retries=retries)


@pytest.fixture()
def sessions(monkeypatch, db_session):
    """Hand the task the test's session and record open/close.

    The task builds its own session because it runs outside a request. Here it
    must get the one the test can assert against, and closing it for real
    would detach every object the test still holds — so close is counted, not
    performed. That count is the point: a leaked connection in a long-lived
    worker never comes back.
    """
    record = {"opened": 0, "closed": 0}

    class _Handle:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            record["closed"] += 1

    def factory():
        record["opened"] += 1
        return _Handle()

    monkeypatch.setattr(invoice_tasks, "SessionLocal", factory)
    return record


def _store_invoice(db_session, business, **overrides) -> Invoice:
    fields = {
        "business_id": business.id,
        "invoice_type": InvoiceType.PURCHASE,
        "source": InvoiceSource.UPLOAD,
        "status": InvoiceStatus.UPLOADED,
        "source_filename": "bill.txt",
        "storage_path": "/tmp/does-not-matter.txt",
        "content_type": "text/plain",
    }
    fields.update(overrides)
    invoice = Invoice(**fields)
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


class TestTheHappyPath:
    def test_the_invoice_is_processed_and_reported(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business)

        def fake_process(db, row):
            row.status = InvoiceStatus.PARSED
            row.parsed_with = "heuristic"
            row.extraction_confidence = 0.72
            return row

        monkeypatch.setattr(invoice_service, "process_invoice", fake_process)

        result = parse_invoice_task(invoice.id)

        assert result == {
            "invoice_id": invoice.id,
            "status": "parsed",
            "parsed_with": "heuristic",
            "confidence": 0.72,
        }
        assert task.retries == []

    def test_the_row_the_service_was_given_is_the_stored_one(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business, source_filename="april.pdf")
        seen: dict = {}

        def fake_process(db, row):
            seen["filename"] = row.source_filename
            row.status = InvoiceStatus.PARSED
            return row

        monkeypatch.setattr(invoice_service, "process_invoice", fake_process)
        parse_invoice_task(invoice.id)
        assert seen["filename"] == "april.pdf"

    def test_a_failed_extraction_is_reported_not_retried(
        self, monkeypatch, task, sessions, db_session, business
    ):
        # process_invoice records its own failures on the row. Retrying that
        # would only repeat a permanent failure three times and delay the row
        # reaching the user's review queue.
        invoice = _store_invoice(db_session, business)

        def fake_process(db, row):
            row.status = InvoiceStatus.FAILED
            return row

        monkeypatch.setattr(invoice_service, "process_invoice", fake_process)

        result = parse_invoice_task(invoice.id)
        assert result["status"] == "failed"
        assert task.retries == [], "a recorded failure must not be retried"


class TestTheAlreadyModifiedGuard:
    """A user can correct an invoice before the worker gets to it."""

    def test_a_manually_corrected_invoice_is_not_re_extracted(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business, status=InvoiceStatus.PARSED)
        called = {"n": 0}

        def fake_process(db, row):
            called["n"] += 1
            return row

        monkeypatch.setattr(invoice_service, "process_invoice", fake_process)
        result = parse_invoice_task(invoice.id)
        assert result["skipped"] is True
        assert result["status"] == "parsed"
        assert called["n"] == 0, "process_invoice was called on a non-UPLOADED invoice"

    def test_an_invoice_already_processing_is_skipped(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(
            db_session, business, status=InvoiceStatus.PROCESSING,
        )
        called = {"n": 0}
        monkeypatch.setattr(
            invoice_service, "process_invoice",
            lambda db, row: (called.__setitem__("n", called["n"] + 1), row)[-1],
        )
        result = parse_invoice_task(invoice.id)
        assert result["skipped"] is True
        assert called["n"] == 0

    def test_a_failed_invoice_is_not_re_extracted_automatically(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business, status=InvoiceStatus.FAILED)
        called = {"n": 0}
        monkeypatch.setattr(
            invoice_service, "process_invoice",
            lambda db, row: (called.__setitem__("n", called["n"] + 1), row)[-1],
        )
        result = parse_invoice_task(invoice.id)
        assert result["skipped"] is True
        assert result["status"] == "failed"
        assert called["n"] == 0

    def test_the_skip_is_logged(
        self, monkeypatch, task, sessions, db_session, business, caplog
    ):
        invoice = _store_invoice(db_session, business, status=InvoiceStatus.PARSED)
        monkeypatch.setattr(
            invoice_service, "process_invoice", lambda db, row: row,
        )
        with caplog.at_level("INFO"):
            parse_invoice_task(invoice.id)
        assert "skipping auto-parse" in caplog.text

    def test_the_skip_does_not_retry(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business, status=InvoiceStatus.PARSED)
        monkeypatch.setattr(
            invoice_service, "process_invoice", lambda db, row: row,
        )
        parse_invoice_task(invoice.id)
        assert task.retries == []


class TestTheMissingRowGuard:
    def test_an_unknown_id_is_reported_as_missing(self, task, sessions):
        assert parse_invoice_task(99_999) == {
            "invoice_id": 99_999,
            "status": "missing",
        }

    def test_an_unknown_id_is_not_retried(self, task, sessions):
        # The row will never appear; three retries would just be noise.
        parse_invoice_task(99_999)
        assert task.retries == []

    def test_a_soft_deleted_invoice_is_treated_as_missing(
        self, monkeypatch, task, sessions, db_session, business
    ):
        # The user deleted it between the upload and the worker picking it up.
        # Parsing it would resurrect it into their review queue.
        invoice = _store_invoice(db_session, business)
        invoice.soft_delete()
        db_session.commit()

        called = {"n": 0}

        def fake_process(db, row):
            called["n"] += 1
            return row

        monkeypatch.setattr(invoice_service, "process_invoice", fake_process)

        assert parse_invoice_task(invoice.id)["status"] == "missing"
        assert called["n"] == 0, "a deleted invoice was parsed anyway"

    def test_the_absence_is_logged_for_the_operator(self, task, sessions, caplog):
        with caplog.at_level("WARNING"):
            parse_invoice_task(99_999)
        assert "nothing to parse" in caplog.text


class TestTheRetryBoundary:
    def test_an_unexpected_error_is_retried(
        self, monkeypatch, task, sessions, db_session, business
    ):
        # This is what the retry is for: the layer below process_invoice — a
        # database that was unreachable when the task started.
        invoice = _store_invoice(db_session, business)
        boom = OSError("could not connect to the database")

        def fake_process(db, row):
            raise boom

        monkeypatch.setattr(invoice_service, "process_invoice", fake_process)

        with pytest.raises(_Retry):
            parse_invoice_task(invoice.id)
        assert task.retries == [boom]

    def test_the_original_exception_is_handed_to_the_retry(
        self, monkeypatch, task, sessions, db_session, business
    ):
        # Celery uses this to decide whether the failure is retryable and to
        # record the traceback on the final attempt.
        invoice = _store_invoice(db_session, business)
        boom = ValueError("something specific")
        monkeypatch.setattr(
            invoice_service, "process_invoice", lambda db, row: (_ for _ in ()).throw(boom)
        )

        with pytest.raises(_Retry):
            parse_invoice_task(invoice.id)
        assert task.retries[0] is boom

    def test_the_failure_is_logged_with_a_traceback(
        self, monkeypatch, task, sessions, db_session, business, caplog
    ):
        invoice = _store_invoice(db_session, business)
        monkeypatch.setattr(
            invoice_service,
            "process_invoice",
            lambda db, row: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        with caplog.at_level("ERROR"), pytest.raises(_Retry):
            parse_invoice_task(invoice.id)
        assert "parse_invoice_task failed" in caplog.text
        assert "RuntimeError" in caplog.text


class TestTheSessionLifecycle:
    """A worker is long-lived; a connection leaked here never comes back."""

    def test_the_session_is_closed_on_success(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business)
        monkeypatch.setattr(
            invoice_service, "process_invoice", lambda db, row: row
        )
        parse_invoice_task(invoice.id)
        assert sessions == {"opened": 1, "closed": 1}

    def test_the_session_is_closed_when_the_row_is_missing(self, task, sessions):
        parse_invoice_task(99_999)
        assert sessions == {"opened": 1, "closed": 1}

    def test_the_session_is_closed_when_the_task_retries(
        self, monkeypatch, task, sessions, db_session, business
    ):
        # The path most likely to leak: the exception leaves through a raise,
        # so only the finally block can close the session.
        invoice = _store_invoice(db_session, business)
        monkeypatch.setattr(
            invoice_service,
            "process_invoice",
            lambda db, row: (_ for _ in ()).throw(OSError("gone")),
        )
        with pytest.raises(_Retry):
            parse_invoice_task(invoice.id)
        assert sessions == {"opened": 1, "closed": 1}

    def test_each_run_opens_exactly_one_session(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business)
        monkeypatch.setattr(invoice_service, "process_invoice", lambda db, row: row)
        parse_invoice_task(invoice.id)
        parse_invoice_task(invoice.id)
        parse_invoice_task(99_999)
        assert sessions == {"opened": 3, "closed": 3}


class TestTheTaskRegistration:
    def test_it_is_registered_under_the_name_the_router_enqueues(self):
        # invoices.py sends "invoices.parse" by name; a rename here would
        # silently strand every upload in the queue.
        assert "invoices.parse" in invoice_tasks.celery_app.tasks

    def test_it_is_bound_so_self_carries_the_retry(self):
        # bind=True is what makes self.retry() available inside the task.
        # Celery signals it by binding `run` to the task instance, which is
        # why run's signature no longer shows a `self` parameter.
        registered = invoice_tasks.celery_app.tasks["invoices.parse"]
        assert registered.run.__self__ is registered

    def test_the_retry_budget_is_finite(self):
        # An unbounded retry on a permanently broken row is an infinite loop
        # in the worker.
        registered = invoice_tasks.celery_app.tasks["invoices.parse"]
        assert registered.max_retries == 3
        assert registered.default_retry_delay == 60


def test_a_row_moved_out_of_uploaded_after_the_check_is_not_reparsed(
    db_session, business, task, sessions, monkeypatch
):
    # The task read UPLOADED, then the user's correction (or a redelivered
    # copy of this task) landed before the claim. Written beneath the session
    # so the instance the task holds still says UPLOADED, as it would.
    invoice = _store_invoice(db_session, business)
    db_session.connection().execute(
        Invoice.__table__.update()
        .where(Invoice.__table__.c.id == invoice.id)
        .values(status=InvoiceStatus.PARSED)
    )
    parsed = []
    monkeypatch.setattr(
        invoice_service, "process_invoice", lambda db, inv, **kw: parsed.append(inv)
    )

    result = parse_invoice_task(invoice.id)

    assert parsed == []
    assert result["skipped"] is True
    db_session.refresh(invoice)
    assert invoice.status is InvoiceStatus.PARSED


class TestARetryCanActuallyRunAgain:
    """The claim is committed before ``process_invoice`` runs. A failure below
    it used to leave the row ``processing``, which the retry's own guard then
    skipped — so the retry never parsed anything."""

    @staticmethod
    def _fail_once(monkeypatch):
        real = invoice_service.process_invoice
        calls = []

        def flaky(db, row, **kw):
            calls.append(row.id)
            if len(calls) == 1:
                raise OSError("server closed the connection unexpectedly")
            return real(db, row, **kw)

        monkeypatch.setattr(invoice_service, "process_invoice", flaky)
        return calls

    def test_the_row_goes_back_to_uploaded_for_the_retry(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business)
        self._fail_once(monkeypatch)

        with pytest.raises(_Retry):
            parse_invoice_task(invoice.id)

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.UPLOADED

    def test_the_retry_then_parses_it(self, monkeypatch, task, sessions, db_session, business):
        invoice = _store_invoice(db_session, business)
        calls = self._fail_once(monkeypatch)

        with pytest.raises(_Retry):
            parse_invoice_task(invoice.id)
        result = parse_invoice_task(invoice.id)

        assert len(calls) == 2
        assert "skipped" not in result
        db_session.refresh(invoice)
        assert invoice.status not in (InvoiceStatus.UPLOADED, InvoiceStatus.PROCESSING)

    def test_the_last_attempt_fails_the_row_instead(
        self, monkeypatch, task, sessions, db_session, business
    ):
        from app.tasks import invoice_tasks

        invoice = _store_invoice(db_session, business)
        monkeypatch.setattr(
            invoice_service, "process_invoice",
            lambda db, row, **kw: (_ for _ in ()).throw(OSError("still down")),
        )
        parse_invoice_task.push_request(retries=parse_invoice_task.max_retries)
        try:
            with pytest.raises(_Retry):
                parse_invoice_task(invoice.id)
        finally:
            parse_invoice_task.pop_request()

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.FAILED
        assert invoice.parse_error == invoice_tasks.GAVE_UP_MESSAGE

    def test_an_outcome_another_writer_recorded_is_not_undone(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business)

        def parsed_elsewhere_then_raise(db, row, **kw):
            db.connection().execute(
                Invoice.__table__.update()
                .where(Invoice.__table__.c.id == row.id)
                .values(status=InvoiceStatus.PARSED)
            )
            db.commit()
            raise OSError("lost the connection after another writer finished")

        monkeypatch.setattr(invoice_service, "process_invoice", parsed_elsewhere_then_raise)

        with pytest.raises(_Retry):
            parse_invoice_task(invoice.id)

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.PARSED

    def test_a_failure_before_the_claim_releases_nothing(
        self, monkeypatch, task, sessions, db_session, business
    ):
        from app.tasks import invoice_tasks

        released = []
        monkeypatch.setattr(invoice_tasks, "_release_claim", lambda *a, **kw: released.append(a))
        invoice = _store_invoice(db_session, business, status=InvoiceStatus.PARSED)
        monkeypatch.setattr(
            db_session, "get", lambda *a, **kw: (_ for _ in ()).throw(OSError("db down"))
        )

        with pytest.raises(_Retry):
            parse_invoice_task(invoice.id)

        assert released == []

    def test_a_release_that_cannot_reach_the_database_still_retries(
        self, monkeypatch, task, sessions, db_session, business
    ):
        invoice = _store_invoice(db_session, business)
        monkeypatch.setattr(
            invoice_service, "process_invoice",
            lambda db, row, **kw: (_ for _ in ()).throw(OSError("down")),
        )
        real_commit = db_session.commit
        commits = []

        def commit_fails_after_the_claim():
            commits.append(1)
            if len(commits) > 1:
                raise OSError("still down")
            return real_commit()

        monkeypatch.setattr(db_session, "commit", commit_fails_after_the_claim)

        with pytest.raises(_Retry):
            parse_invoice_task(invoice.id)
        assert len(task.retries) == 1
