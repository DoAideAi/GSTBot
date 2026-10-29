"""A superseded GSTR-2B is kept only if a reconciliation ever ran against it.

Every import supersedes the last and the superseded copy is soft-deleted, so
an assessment can see what each reconciliation ran against. But a copy no run
ever used evidences nothing, and was kept all the same: a business that
re-downloads its 2B each day as suppliers file late stored a full copy of the
statement — up to 15 MB of JSON — every day, forever, on a disk with a few GB
free.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.gstr_return import GSTRReturn, ReturnType
from app.models.reconciliation_run import ReconciliationRun, ReconciliationStatus
from app.services import gstr2b, reconciliation
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE

PERIOD = "2026-04"


def _statement(invoice_number: str):
    return gstr2b.parse_json({
        "data": {
            "gstin": BUSINESS_GSTIN,
            "rtnprd": "042026",
            "docdata": {"b2b": [{"ctin": SUPPLIER_GSTIN_OTHER_STATE, "inv": [{
                "inum": invoice_number, "dt": "05-04-2026", "val": 1180, "typ": "R",
                "pos": "27", "rev": "N", "itcavl": "Y",
                "items": [{"rt": 18, "txval": 1000, "igst": 180, "cgst": 0, "sgst": 0}],
            }]}]},
        }
    })


def _numbers(rows):
    """Which statement each copy is, by the invoice it carries (ids get reused)."""
    return sorted(row.data["invoices"][0]["invoice_number"] for row in rows)


def _copies(db_session, business_id):
    return db_session.scalars(
        select(GSTRReturn).where(
            GSTRReturn.business_id == business_id,
            GSTRReturn.period == PERIOD,
            GSTRReturn.return_type == ReturnType.GSTR2B,
        ).execution_options(include_deleted=True)
    ).all()


def test_a_copy_nothing_reconciled_against_is_not_kept(db_session, business):
    reconciliation.store_gstr2b(db_session, business.id, PERIOD, _statement("A-1"))
    reconciliation.store_gstr2b(db_session, business.id, PERIOD, _statement("A-2"))

    assert _numbers(_copies(db_session, business.id)) == ["A-2"]


def test_a_copy_a_reconciliation_ran_against_is_kept(db_session, business):
    reconciliation.store_gstr2b(db_session, business.id, PERIOD, _statement("A-1"))
    db_session.add(ReconciliationRun(
        business_id=business.id, period=PERIOD, status=ReconciliationStatus.COMPLETED,
        started_at=datetime.now(UTC) + timedelta(seconds=1),
    ))
    db_session.commit()
    reconciliation.store_gstr2b(db_session, business.id, PERIOD, _statement("A-2"))

    copies = _copies(db_session, business.id)
    assert _numbers(copies) == ["A-1", "A-2"]
    retired = next(row for row in copies if row.data["invoices"][0]["invoice_number"] == "A-1")
    assert retired.deleted_at is not None


def test_a_run_of_another_period_does_not_keep_it(db_session, business):
    reconciliation.store_gstr2b(db_session, business.id, PERIOD, _statement("A-1"))
    db_session.add(ReconciliationRun(
        business_id=business.id, period="2026-05", status=ReconciliationStatus.COMPLETED,
        started_at=datetime.now(UTC) + timedelta(seconds=1),
    ))
    db_session.commit()
    reconciliation.store_gstr2b(db_session, business.id, PERIOD, _statement("A-2"))

    assert _numbers(_copies(db_session, business.id)) == ["A-2"]
