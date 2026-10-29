"""A rescore and a reconciliation run cannot interleave on a supplier's score.

Runs take the per-tenant supplier lock before rewriting histories (P28 M4).
``rescore_all`` — ``POST /suppliers/rescore`` — writes every supplier's score
and risk level from its history and took no lock: on Postgres it could read
the history a run was about to replace, wait on the run's row lock, then write
its stale score over the run's fresh one, leaving a score that disagrees with
the history stored beside it until the next run.
"""
from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.models.supplier import Supplier
from app.services import reconciliation
from app.services import supplier_score as scoring
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE

PERIOD = "2026-04"


def test_rescore_takes_the_supplier_lock_before_reading(db_session, business, monkeypatch):
    db_session.add(Supplier(business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE))
    db_session.commit()
    order: list[str] = []
    real_lock, real_score = scoring.lock_supplier_records, scoring.score_supplier
    monkeypatch.setattr(
        scoring, "lock_supplier_records",
        lambda db, bid: (order.append(f"lock {bid}"), real_lock(db, bid))[1],
    )
    monkeypatch.setattr(
        scoring, "score_supplier",
        lambda s, **kw: (order.append("score"), real_score(s, **kw))[1],
    )

    scoring.rescore_all(db_session, business.id, as_of_period=PERIOD)

    assert order == [f"lock {business.id}", "score"]


def test_rescore_reads_the_history_another_session_committed(db_session, business):
    # Waiting on the lock is no use if the history then comes from this
    # session's identity map rather than from the row the run committed.
    supplier = Supplier(business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE)
    db_session.add(supplier)
    db_session.commit()
    assert supplier.filing_history in (None, [])  # loaded into this session

    other = sessionmaker(bind=db_session.get_bind())()
    row = other.get(Supplier, supplier.id)
    row.filing_history = [{"period": "2026-03", "matched": 5, "mismatched": 0, "missing": 0}]
    other.commit()
    other.close()

    [score] = scoring.rescore_all(db_session, business.id, as_of_period=PERIOD)
    assert score.invoices_observed == 5


def test_the_run_and_the_rescore_share_one_lock(db_session, business, monkeypatch):
    taken: list[int] = []
    monkeypatch.setattr(scoring, "lock_supplier_records", lambda db, bid: taken.append(bid))
    reconciliation._lock_supplier_records(db_session, business.id)
    scoring.rescore_all(db_session, business.id, as_of_period=PERIOD)
    assert taken == [business.id, business.id]
