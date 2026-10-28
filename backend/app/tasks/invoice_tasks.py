"""Async invoice work.

Tasks open their own session — a Celery task runs outside any request, so
there is no ``get_db`` dependency to inherit — and always close it, because a
worker process is long-lived and a leaked connection there is permanent.
"""
from __future__ import annotations

import logging

from sqlalchemy import update

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.invoice import Invoice, InvoiceStatus
from app.services import invoice_service, job_health

logger = logging.getLogger(__name__)


@celery_app.task(name="invoices.parse", bind=True, max_retries=3, default_retry_delay=60)
def parse_invoice_task(self, invoice_id: int) -> dict:
    """Extract one stored invoice.

    ``process_invoice`` records its own failures on the row rather than
    raising, so a retry here would only ever repeat a permanent failure. The
    retry exists for the layer below that: a database that was unreachable
    when the task started.
    """
    db = SessionLocal()
    try:
        invoice = db.get(Invoice, invoice_id)
        if invoice is None or invoice.deleted_at is not None:
            logger.warning("Invoice %s is gone; nothing to parse", invoice_id)
            return {"invoice_id": invoice_id, "status": "missing"}

        # The user may have manually corrected the invoice, or another worker
        # may have already parsed it, between the upload and this task running.
        # Re-extracting would overwrite that work.  The explicit /reparse
        # endpoint bypasses this guard because the user chose to re-extract.
        if invoice.status is not InvoiceStatus.UPLOADED:
            logger.info(
                "Invoice %s is already %s; skipping auto-parse",
                invoice_id, invoice.status.value,
            )
            return {
                "invoice_id": invoice_id,
                "status": invoice.status.value,
                "skipped": True,
            }

        # The check above is a read; this is the claim. Celery redelivers a task
        # whose worker died, and the user can correct the row by hand, so
        # either can move it out of UPLOADED between that read and here — and
        # an unconditional write to PROCESSING then re-extracted over the
        # correction, or parsed one document twice. Only the writer that
        # actually moves the row out of UPLOADED goes on to parse it.
        claimed = db.execute(
            update(Invoice)
            .where(
                Invoice.id == invoice_id,
                Invoice.status == InvoiceStatus.UPLOADED,
                Invoice.deleted_at.is_(None),
            )
            .values(status=InvoiceStatus.PROCESSING)
            .execution_options(synchronize_session=False)
        ).rowcount
        db.commit()
        if not claimed:
            logger.info("Invoice %s was claimed elsewhere; skipping auto-parse", invoice_id)
            return {"invoice_id": invoice_id, "status": invoice.status.value, "skipped": True}

        invoice = invoice_service.process_invoice(db, invoice)
        return {
            "invoice_id": invoice.id,
            "status": invoice.status.value,
            "parsed_with": invoice.parsed_with,
            "confidence": invoice.extraction_confidence,
        }
    except Exception as exc:  # noqa: BLE001 - retried, then surfaced
        logger.exception(
            "parse_invoice_task failed",
            extra={
                "invoice_id": invoice_id,
                "celery_task_id": self.request.id,
                "retry": self.request.retries,
            },
        )
        raise self.retry(exc=exc) from exc
    finally:
        db.close()


@celery_app.task(name="invoices.reap_stalled", bind=True, max_retries=2, default_retry_delay=300)
def reap_stalled_parses_task(self) -> dict:
    """Fail invoices left in ``processing`` by a worker that stopped existing.

    The counterpart to :func:`parse_invoice_task`, and the reason it has to be a
    scheduled task rather than error handling: every failure the parse can catch
    is already written to the row, so what is left is the process dying — the
    hard time limit, the OOM killer, a redeploy mid-document. Nothing runs in the
    worker at that moment, so only a clock afterwards can notice, exactly as with
    a missed filing deadline.

    See :func:`app.services.invoice_service.reap_stalled_parses` for what the
    stranded row costs while it sits there.

    Retried twice, five minutes apart, then left alone: the sweep is idempotent
    and runs again within the hour, so the case worth covering is a database that
    happened to be unreachable, not a defect that would only be repeated.
    """
    db = SessionLocal()
    try:
        reaped = invoice_service.reap_stalled_parses(db)
        job_health.record_heartbeat("stalled-parse-sweep")
        return {"reaped": reaped}
    except Exception as exc:  # noqa: BLE001 - retried, then surfaced
        logger.exception(
            "reap_stalled_parses_task failed",
            extra={"celery_task_id": self.request.id, "retry": self.request.retries},
        )
        raise self.retry(exc=exc) from exc
    finally:
        db.close()
