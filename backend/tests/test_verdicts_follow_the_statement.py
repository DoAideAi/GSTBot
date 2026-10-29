"""A new GSTR-2B withdraws the verdicts the old one earned.

Each purchase carries the last reconciliation's verdict — matched, mismatched,
missing from the 2B — judged against the statement then in force. Importing a
new statement for the period left them all standing. A supplier who had since
filed still had their invoices marked missing, and was quoted on the supplier
screen as owing credit at risk; an invoice the supplier had since amended away
kept "matched", its credit shown as safe. That screen is where a business
decides whether to hold a payment. The invoice edit route already withdraws a
verdict whose figures changed; a new statement changes the other side.
"""
from __future__ import annotations

from app.models.invoice import InvoiceStatus
from app.services import reconciliation
from tests.test_reconciliation import PERIOD, import_2b, portal, save


def test_a_matched_invoice_is_unjudged_once_the_statement_changes(db_session, business):
    invoice = save(db_session, business.id)
    import_2b(db_session, business.id, [portal()])
    reconciliation.run_reconciliation(db_session, business.id, PERIOD)
    db_session.refresh(invoice)
    assert invoice.status is InvoiceStatus.MATCHED

    import_2b(db_session, business.id, [portal(invoice_number="SOMETHING-ELSE")])

    db_session.refresh(invoice)
    assert invoice.status is InvoiceStatus.PARSED


def test_an_invoice_missing_from_the_old_statement_is_unjudged_too(db_session, business):
    invoice = save(db_session, business.id)
    import_2b(db_session, business.id, [portal(invoice_number="NOT-OURS")])
    reconciliation.run_reconciliation(db_session, business.id, PERIOD)
    db_session.refresh(invoice)
    assert invoice.status is InvoiceStatus.MISSING_IN_2B

    import_2b(db_session, business.id, [portal()])  # the supplier has filed since

    db_session.refresh(invoice)
    assert invoice.status is InvoiceStatus.PARSED


def test_the_same_statement_again_leaves_the_verdicts_alone(db_session, business):
    invoice = save(db_session, business.id)
    import_2b(db_session, business.id, [portal()])
    reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    import_2b(db_session, business.id, [portal()])

    db_session.refresh(invoice)
    assert invoice.status is InvoiceStatus.MATCHED


def test_another_periods_verdicts_are_left_alone(db_session, business):
    from datetime import date

    invoice = save(db_session, business.id)
    import_2b(db_session, business.id, [portal()])
    reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    import_2b(
        db_session, business.id,
        [portal(invoice_number="MAY-1", invoice_date=date(2026, 5, 3), period="2026-05")],
        period="2026-05",
    )

    db_session.refresh(invoice)
    assert invoice.status is InvoiceStatus.MATCHED
