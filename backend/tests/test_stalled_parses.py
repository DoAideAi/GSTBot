"""Invoices a worker picked up and never put down.

``process_invoice`` writes every failure it can catch onto the row, so the only
way to stay in ``processing`` is for the process to stop existing between the
commit that claims the row and the one that records an outcome: the 240s hard
time limit, the OOM killer choosing the child holding a decoded PDF, or a
redeploy mid-document. No ``except`` runs in any of those.

What made that worth a sweep rather than a shrug is where the row then sits.
``PROCESSING`` is in ``UNREADABLE_STATUSES``, so the GSTR-1, the period's output
tax, the credit pool, the reconciliation and the supplier's exposure all skip
it — right, because nothing has read it. But the dashboard's needs-review count
is ``PARSED`` plus ``FAILED``, and the register renders the status as a neutral
"Processing" chip. So the one document missing from the return is the one
document the product shows as work in hand, on no screen, forever.

These tests are about that invisibility as much as about the status: the point
of reaping to ``FAILED`` is that the row starts being counted and complained
about, while not one rupee of any return moves.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.business import Business
from app.models.invoice import UNREADABLE_STATUSES, Invoice, InvoiceStatus, InvoiceType
from app.services import invoice_service
from app.services.invoice_service import STALLED_PARSE_MESSAGE, reap_stalled_parses


class _SweepRetry(Exception):
    """Stands in for celery.exceptions.Retry, which is what ``.retry()`` raises."""


def _invoice(db_session, business, *, status, age_seconds=0, **overrides) -> Invoice:
    """An invoice whose ``updated_at`` is *age_seconds* in the past.

    ``updated_at`` carries ``onupdate=func.now()``, so it cannot be aged by
    assignment through the ORM — the flush would overwrite it with the current
    time, which is exactly the write this is trying to simulate the absence of.
    It is stamped with an UPDATE afterwards instead.
    """
    fields = {
        "business_id": business.id,
        "invoice_type": InvoiceType.PURCHASE,
        "status": status,
        "source_filename": "bill.pdf",
        "storage_path": "/tmp/stored-bill.pdf",
        "content_type": "application/pdf",
    }
    fields.update(overrides)
    invoice = Invoice(**fields)
    db_session.add(invoice)
    db_session.commit()

    if age_seconds:
        db_session.query(Invoice).filter(Invoice.id == invoice.id).update(
            {"updated_at": datetime.now(UTC) - timedelta(seconds=age_seconds)},
            synchronize_session=False,
        )
        db_session.commit()
    db_session.refresh(invoice)
    return invoice


class TestWhatGetsReaped:
    def test_a_parse_stranded_past_the_deadline_is_failed(self, db_session, business):
        invoice = _invoice(
            db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200
        )

        assert reap_stalled_parses(db_session) == 1

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.FAILED

    def test_the_row_says_what_happened_and_what_to_do(self, db_session, business):
        # The stored file was committed before the parse ever started, so
        # nothing has been lost and re-parsing is still the fix. A row that only
        # said "failed" would send the user back to their filing cabinet.
        invoice = _invoice(
            db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200
        )

        reap_stalled_parses(db_session)

        db_session.refresh(invoice)
        assert invoice.parse_error == STALLED_PARSE_MESSAGE
        assert "Re-parse" in invoice.parse_error

    def test_the_stored_file_is_left_alone(self, db_session, business):
        # Reaping is a statement about the worker, not about the document.
        invoice = _invoice(
            db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200
        )

        reap_stalled_parses(db_session)

        db_session.refresh(invoice)
        assert invoice.storage_path == "/tmp/stored-bill.pdf"
        assert invoice.source_filename == "bill.pdf"

    def test_every_stranded_row_is_reaped_in_one_pass(self, db_session, business):
        # One OOM kill strands one row; a redeploy mid-queue strands several.
        for index in range(3):
            _invoice(
                db_session,
                business,
                status=InvoiceStatus.PROCESSING,
                age_seconds=7200,
                invoice_number=f"INV-{index}",
            )

        assert reap_stalled_parses(db_session) == 3

    def test_it_reaps_across_tenants(self, db_session, business, other_tenant):
        # The sweep runs on a schedule with no request behind it, so there is no
        # tenant to scope to. A worker dying strands whichever row it held.
        rival = db_session.scalars(
            select(Business).where(Business.id != business.id)
        ).one()

        _invoice(db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200)
        _invoice(db_session, rival, status=InvoiceStatus.PROCESSING, age_seconds=7200)

        assert reap_stalled_parses(db_session) == 2


class TestWhatIsLeftAlone:
    def test_a_parse_still_inside_the_deadline_is_untouched(self, db_session, business):
        # The whole risk of a sweep like this is failing an invoice that is
        # merely slow. A parse that started a minute ago is a parse.
        invoice = _invoice(
            db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=60
        )

        assert reap_stalled_parses(db_session) == 0

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.PROCESSING

    def test_a_retry_restamps_the_clock_and_buys_the_full_deadline_again(
        self, db_session, business
    ):
        # ``process_invoice`` re-commits ``PROCESSING`` on every attempt, and
        # ``updated_at`` is maintained by the database, so a task legitimately
        # retrying looks new. This is why the claim on the row is the clock
        # rather than the upload time: max_retries=3 at a 60s delay would
        # otherwise let a healthy retry be reaped out from under itself.
        invoice = _invoice(
            db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200
        )

        invoice.status = InvoiceStatus.PROCESSING
        invoice.parse_error = "attempt 2"
        db_session.commit()

        assert reap_stalled_parses(db_session) == 0

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.PROCESSING

    @pytest.mark.parametrize(
        "status",
        [
            InvoiceStatus.UPLOADED,
            InvoiceStatus.PARSED,
            InvoiceStatus.FAILED,
            InvoiceStatus.MATCHED,
            InvoiceStatus.MISMATCHED,
            InvoiceStatus.MISSING_IN_2B,
            InvoiceStatus.DUPLICATE,
        ],
    )
    def test_no_other_status_is_touched(self, db_session, business, status):
        # ``UPLOADED`` is the one worth naming: it is also unreadable and also
        # waiting on a worker, but it has not been claimed by one. Failing it
        # would fail every invoice sitting in a queue that is merely backed up.
        invoice = _invoice(db_session, business, status=status, age_seconds=7200)

        assert reap_stalled_parses(db_session) == 0

        db_session.refresh(invoice)
        assert invoice.status is status

    def test_a_deleted_invoice_is_not_resurrected_into_the_review_queue(
        self, db_session, business
    ):
        # Deleting is soft, so the row is still there to be found. Reaping it
        # would put a document the user removed back in front of them.
        invoice = _invoice(
            db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200
        )
        invoice.soft_delete()
        db_session.commit()

        assert reap_stalled_parses(db_session) == 0

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.PROCESSING

    def test_a_sweep_that_finds_nothing_is_a_no_op(self, db_session, business):
        # Runs hourly, and the ordinary case is an empty result. It must not
        # commit, log an alarm, or otherwise cost anything on a healthy box.
        _invoice(db_session, business, status=InvoiceStatus.PARSED, age_seconds=7200)

        assert reap_stalled_parses(db_session) == 0


class TestConcurrencyGuard:
    def test_a_row_parsed_between_select_and_update_keeps_its_status(
        self, db_session, business
    ):
        """The UPDATE re-checks status=PROCESSING so a reparse that finishes
        between the reaper's SELECT and UPDATE is not overwritten with FAILED."""
        invoice = _invoice(db_session, business, status=InvoiceStatus.PARSED)

        from sqlalchemy import update as sqla_update
        db_session.execute(
            sqla_update(Invoice)
            .where(
                Invoice.id.in_([invoice.id]),
                Invoice.status == InvoiceStatus.PROCESSING,
            )
            .values(status=InvoiceStatus.FAILED, parse_error=STALLED_PARSE_MESSAGE)
            .execution_options(synchronize_session=False)
        )
        db_session.commit()

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.PARSED


class TestTheDeadline:
    def test_the_configured_stall_window_decides(self, db_session, business):
        invoice = _invoice(
            db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=1800
        )

        # Inside the default hour, so nothing happens...
        assert reap_stalled_parses(db_session) == 0
        # ...and the same row is stranded under a tighter one.
        assert reap_stalled_parses(db_session, stall_seconds=600) == 1

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.FAILED

    def test_the_default_clears_a_full_parse_with_every_retry(self):
        # Four attempts at the 240s hard time limit plus three 60s retry delays
        # is about nineteen minutes, and that is the floor a legitimate parse
        # can reach. Anything at or under it would reap live work.
        worst_legitimate_parse = 4 * 240 + 3 * 60
        assert settings.invoice_parse_stall_seconds > worst_legitimate_parse

    def test_now_can_be_supplied(self, db_session, business):
        # So the sweep is assertable against a clock rather than against sleep.
        invoice = _invoice(db_session, business, status=InvoiceStatus.PROCESSING)

        reaped = reap_stalled_parses(
            db_session, now=datetime.now(UTC) + timedelta(days=1)
        )

        assert reaped == 1
        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.FAILED


class TestTheRowBecomesVisible:
    """The point of the reaping, rather than a side effect of it."""

    def test_it_starts_being_counted_as_needing_review(
        self, db_session, business, auth_client
    ):
        # ``needs_review`` on the dashboard is PARSED plus FAILED. A stranded
        # row was in neither, so the document missing from the return was on no
        # screen at all — not even as a problem.
        _invoice(db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200)

        def needs_review() -> int:
            return auth_client.get("/api/v1/dashboard").json()["counts"]["needs_review"]

        before = needs_review()
        reap_stalled_parses(db_session)

        assert (before, needs_review()) == (0, 1)

    def test_it_shows_up_under_the_failed_filter(self, db_session, business, auth_client):
        # Which is where a user goes looking for documents to deal with.
        invoice = _invoice(
            db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200
        )

        reap_stalled_parses(db_session)

        listed = auth_client.get("/api/v1/invoices", params={"status": "failed"}).json()
        assert [row["id"] for row in listed["items"]] == [invoice.id]
        assert listed["items"][0]["parse_error"] == STALLED_PARSE_MESSAGE

    def test_no_return_figure_moves(self, db_session, business):
        # Both statuses are unreadable, so this changes what the user is told
        # and nothing about what is filed. A sweep that could alter a return
        # would be a sweep nobody should run on a schedule.
        assert InvoiceStatus.PROCESSING in UNREADABLE_STATUSES
        assert InvoiceStatus.FAILED in UNREADABLE_STATUSES

        _invoice(
            db_session,
            business,
            status=InvoiceStatus.PROCESSING,
            age_seconds=7200,
            invoice_type=InvoiceType.SALES,
            period="2026-04",
            invoice_date=None,
            taxable_value="100000.00",
            igst="18000.00",
        )

        before = invoice_service.tax_summary(db_session, business.id, "2026-04")
        reap_stalled_parses(db_session)
        after = invoice_service.tax_summary(db_session, business.id, "2026-04")

        assert before == after

    def test_the_document_can_then_be_re_extracted(
        self, db_session, business, auth_client, monkeypatch
    ):
        # The stored file never went anywhere, so the reaped row is exactly as
        # recoverable as any other failure — which is what makes failing it the
        # honest answer rather than a destructive one.
        invoice = _invoice(
            db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200
        )
        reap_stalled_parses(db_session)

        # Takes the keyword the route now passes: the tenant's GSTIN is read
        # once by the caller rather than walked off the invoice per file.
        def fake_process(db, row, *, business_gstin=None):
            row.status = InvoiceStatus.PARSED
            row.parse_error = None
            db.commit()
            return row

        monkeypatch.setattr(invoice_service, "process_invoice", fake_process)

        response = auth_client.post(f"/api/v1/invoices/{invoice.id}/reparse")

        assert response.status_code == 200
        assert response.json()["status"] == "parsed"


class TestTheScheduledTask:
    def test_the_sweep_is_on_the_beat_schedule(self):
        # Nothing else can notice a process that stopped existing, so if this
        # is not scheduled the fix does not exist in production.
        from app.celery_app import celery_app

        entry = celery_app.conf.beat_schedule["stalled-parse-sweep"]
        assert entry["task"] == "invoices.reap_stalled"

    def test_it_runs_more_often_than_a_row_can_go_stale(self):
        # Hourly, against a stall window of an hour: a stranded row is visible
        # within about two hours of the worker dying rather than never.
        from app.celery_app import celery_app

        entry = celery_app.conf.beat_schedule["stalled-parse-sweep"]
        assert entry["schedule"].hour == set(range(24))

    def test_the_task_reports_what_it_reaped(self, db_session, business, monkeypatch):
        from app.tasks import invoice_tasks

        _invoice(db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200)

        class _Handle:
            def __getattr__(self, name):
                return getattr(db_session, name)

            def close(self):
                closed.append(True)

        closed: list[bool] = []
        monkeypatch.setattr(invoice_tasks, "SessionLocal", _Handle)

        assert invoice_tasks.reap_stalled_parses_task() == {"reaped": 1, "requeued": 0}
        # A leaked connection in a long-lived worker never comes back.
        assert closed == [True]


class TestTheSweepFailingAltogether:
    """What happens when the sweep itself cannot run.

    The sweep is the only thing that notices a stranded row, so its own failure
    is the failure that makes the invisibility above permanent. Its sibling
    ``parse_invoice_task`` has a class each for the retry boundary and the
    session lifecycle (see :mod:`tests.test_invoice_tasks`); this one had only
    its happy path, so the ``except`` that decides between "retried" and
    "swallowed" was running in production having never run here.

    The distinction matters more for the sweep than for the parse. A parse that
    gives up leaves a row saying ``failed``, which is on the dashboard's
    needs-review count and in the register with a red chip. A sweep that gives
    up leaves nothing at all — the stranded rows keep saying "Processing", and
    the next hourly run is the only thing between them and forever.
    """

    @pytest.fixture()
    def task(self, monkeypatch):
        """Record ``self.retry()`` on the real registered task.

        Celery binds ``self`` itself, so there is no fake to hand in; patching
        retry on the registered object is what makes the decision observable
        without a broker, and keeps the code under test the object the worker
        actually runs.
        """
        from app.tasks import invoice_tasks

        retries: list[BaseException | None] = []

        def fake_retry(exc=None, **kwargs):
            retries.append(exc)
            raise _SweepRetry

        monkeypatch.setattr(invoice_tasks.reap_stalled_parses_task, "retry", fake_retry)
        return SimpleNamespace(retries=retries)

    @pytest.fixture()
    def sessions(self, monkeypatch, db_session):
        """Count the sessions the task opens and closes."""
        from app.tasks import invoice_tasks

        counts = {"opened": 0, "closed": 0}

        class _Handle:
            def __init__(self):
                counts["opened"] += 1

            def __getattr__(self, name):
                return getattr(db_session, name)

            def close(self):
                counts["closed"] += 1

        monkeypatch.setattr(invoice_tasks, "SessionLocal", _Handle)
        return counts

    def test_an_unreachable_database_is_retried_rather_than_swallowed(
        self, monkeypatch, task, sessions
    ):
        # The case the retry is actually for. Swallowed, the beat schedule's
        # next run is an hour away and this hour's stranded rows stay invisible
        # for two; retried, they are picked up five minutes later.
        from app.tasks import invoice_tasks

        boom = OSError("could not connect to the database")
        monkeypatch.setattr(
            invoice_service,
            "reap_stalled_parses",
            lambda db: (_ for _ in ()).throw(boom),
        )

        with pytest.raises(_SweepRetry):
            invoice_tasks.reap_stalled_parses_task()
        assert task.retries == [boom]

    def test_the_original_exception_is_handed_to_the_retry(
        self, monkeypatch, task, sessions
    ):
        # Celery reads it to decide whether the failure is retryable at all,
        # and to record the traceback on the final attempt.
        from app.tasks import invoice_tasks

        boom = ValueError("something specific")
        monkeypatch.setattr(
            invoice_service,
            "reap_stalled_parses",
            lambda db: (_ for _ in ()).throw(boom),
        )

        with pytest.raises(_SweepRetry):
            invoice_tasks.reap_stalled_parses_task()
        assert task.retries[0] is boom

    def test_the_failure_is_logged_with_a_traceback(self, monkeypatch, task, sessions, caplog):
        # Nobody is waiting on this task, so the log is the only place its
        # failure is ever stated.
        from app.tasks import invoice_tasks

        monkeypatch.setattr(
            invoice_service,
            "reap_stalled_parses",
            lambda db: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        with caplog.at_level("ERROR"), pytest.raises(_SweepRetry):
            invoice_tasks.reap_stalled_parses_task()
        assert "reap_stalled_parses_task failed" in caplog.text
        assert "RuntimeError" in caplog.text

    def test_the_session_is_closed_when_the_sweep_retries(self, monkeypatch, task, sessions):
        # The path most likely to leak: the exception leaves through a raise,
        # so only the finally block can close the session. This task runs every
        # hour forever, so a connection leaked here is leaked on a timer.
        from app.tasks import invoice_tasks

        monkeypatch.setattr(
            invoice_service,
            "reap_stalled_parses",
            lambda db: (_ for _ in ()).throw(OSError("gone")),
        )
        with pytest.raises(_SweepRetry):
            invoice_tasks.reap_stalled_parses_task()
        assert sessions == {"opened": 1, "closed": 1}

    def test_each_run_opens_exactly_one_session(self, monkeypatch, task, sessions):
        from app.tasks import invoice_tasks

        monkeypatch.setattr(invoice_service, "reap_stalled_parses", lambda db: 0)
        invoice_tasks.reap_stalled_parses_task()
        invoice_tasks.reap_stalled_parses_task()
        assert sessions == {"opened": 2, "closed": 2}


class TestTheSweepsRegistration:
    """The wiring that decides whether the sweep runs at all."""

    def test_it_is_registered_under_the_name_the_beat_schedule_sends(self):
        # The schedule enqueues "invoices.reap_stalled" by name; a rename on
        # either side leaves the sweep never running, and the symptom is
        # invisible by construction — stranded rows simply stay stranded.
        from app.tasks import invoice_tasks

        assert "invoices.reap_stalled" in invoice_tasks.celery_app.tasks

    def test_it_is_bound_so_self_carries_the_retry(self):
        # bind=True is what makes self.retry() available inside the task;
        # without it the except above raises AttributeError instead.
        from app.tasks import invoice_tasks

        registered = invoice_tasks.celery_app.tasks["invoices.reap_stalled"]
        assert registered.run.__self__ is registered

    def test_the_retry_budget_is_finite_and_shorter_than_the_schedule(self):
        # An unbounded retry against a database that is down is a worker stuck
        # in a loop. The budget also has to expire well inside the hourly
        # schedule: the sweep is idempotent and runs again anyway, so retrying
        # past the next run would have two sweeps going at once.
        from app.tasks import invoice_tasks

        registered = invoice_tasks.celery_app.tasks["invoices.reap_stalled"]
        assert registered.max_retries == 2
        assert registered.default_retry_delay == 300
        assert registered.max_retries * registered.default_retry_delay < 3600


class TestAnUploadWhoseParseWasLost:
    """P18 M3: ``uploaded`` had no way out but the parse task. The broker is
    Redis with snapshots and no append-only log, so a restart loses whatever was
    queued since the last snapshot, and those rows stayed ``uploaded`` forever —
    unreadable, so silently out of every return and the credit pool, with no
    message. The hourly sweep now queues them again."""

    def test_only_an_old_uploaded_row_is_lost(self, db_session, business):
        old = _invoice(db_session, business, status=InvoiceStatus.UPLOADED, age_seconds=7200)
        _invoice(db_session, business, status=InvoiceStatus.UPLOADED, age_seconds=60)
        _invoice(db_session, business, status=InvoiceStatus.PROCESSING, age_seconds=7200)
        _invoice(
            db_session,
            business,
            status=InvoiceStatus.UPLOADED,
            age_seconds=7200,
            deleted_at=datetime.now(UTC),
        )
        assert invoice_service.lost_uploads(db_session) == [old.id]

    def test_the_sweep_queues_them_again(self, db_session, business, monkeypatch):
        from app.tasks import invoice_tasks

        lost = _invoice(db_session, business, status=InvoiceStatus.UPLOADED, age_seconds=7200)

        class _Handle:
            def __getattr__(self, name):
                return getattr(db_session, name)

            def close(self):
                pass

        queued: list[int] = []
        monkeypatch.setattr(invoice_tasks, "SessionLocal", _Handle)
        monkeypatch.setattr(
            invoice_tasks.parse_invoice_task, "delay", lambda invoice_id: queued.append(invoice_id)
        )
        monkeypatch.setattr(
            invoice_tasks.job_health,
            "queue_status",
            lambda: SimpleNamespace(reachable=True, depth=0),
        )

        assert invoice_tasks.reap_stalled_parses_task() == {"reaped": 0, "requeued": 1}
        assert queued == [lost.id]
        # Queued, not failed: the file is fine and the parse never ran.
        db_session.refresh(lost)
        assert lost.status is InvoiceStatus.UPLOADED

    @pytest.mark.parametrize(
        "queue",
        [SimpleNamespace(reachable=True, depth=40), SimpleNamespace(reachable=False, depth=None)],
        ids=["backlog", "unreachable"],
    )
    def test_nothing_is_requeued_while_the_queue_may_still_hold_it(
        self, db_session, business, monkeypatch, caplog, queue
    ):
        # P18 M9: behind a backlog, an hour-old upload may simply be waiting.
        # Requeueing then added a copy every hour for as long as the workers
        # were down or behind. P18 M11: and the wait is logged, not silent.
        from app.tasks import invoice_tasks

        _invoice(db_session, business, status=InvoiceStatus.UPLOADED, age_seconds=7200)

        class _Handle:
            def __getattr__(self, name):
                return getattr(db_session, name)

            def close(self):
                pass

        queued: list[int] = []
        monkeypatch.setattr(invoice_tasks, "SessionLocal", _Handle)
        monkeypatch.setattr(
            invoice_tasks.parse_invoice_task, "delay", lambda invoice_id: queued.append(invoice_id)
        )
        monkeypatch.setattr(invoice_tasks.job_health, "queue_status", lambda: queue)

        assert invoice_tasks.reap_stalled_parses_task() == {"reaped": 0, "requeued": 0}
        assert queued == []
        assert any("not requeued" in record.getMessage() for record in caplog.records)
