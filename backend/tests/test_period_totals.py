"""A period's stored totals hold what its invoices can add up to.

``MONEY_MAX`` bounds a single invoice. The totals a filing and a reconciliation
store are sums of a month of them, and lived in the same numeric(16,2) as one
invoice — so three invoices each inside the bound summed past it, and Postgres
refused the write. SQLite (this suite) keeps whatever it is handed, so the
column definition is what is checked, alongside the round trip.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.models.gstr_return import GSTRReturn
from app.models.mixins import MONEY_MAX
from app.models.reconciliation_run import ReconciliationRun
from tests.conftest import make_paid

TOTALS = [
    (GSTRReturn, "total_taxable_value"),
    (GSTRReturn, "total_cgst"),
    (GSTRReturn, "total_sgst"),
    (GSTRReturn, "total_igst"),
    (GSTRReturn, "total_cess"),
    (ReconciliationRun, "itc_eligible"),
    (ReconciliationRun, "itc_at_risk"),
    (ReconciliationRun, "itc_claimed"),
]

# A month far past any plan's upload limit, every invoice at the ceiling.
INVOICES_AT_THE_CEILING = 1_000_000


@pytest.mark.parametrize(("model", "column"), TOTALS)
def test_a_total_column_holds_a_million_invoices_at_the_ceiling(model, column):
    numeric = model.__table__.c[column].type
    whole_digits = numeric.precision - numeric.scale
    assert whole_digits >= len(str(int(MONEY_MAX * INVOICES_AT_THE_CEILING)))


@pytest.mark.parametrize("model", [GSTRReturn, ReconciliationRun])
def test_the_postgres_ddl_is_the_wide_type(model):
    ddl = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
    for owner, column in TOTALS:
        if owner is model:
            assert f"{column} NUMERIC(22, 2)" in ddl


def test_filing_a_period_of_invoices_at_the_ceiling_stores_their_exact_sum(
    client, db_session, auth_client, business
):
    make_paid(db_session, business.id)
    at_the_ceiling = "99999999999999.98"
    for n in range(3):
        text = (
            f"Invoice No: INV-{n}\nDate: 01/04/2026\n"
            "Taxable Value: 1000\nIGST: 180\nTotal: 1180\n"
        )
        upload = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": (f"{n}.txt", text.encode(), "text/plain")},
            data={"invoice_type": "sales"},
        )
        invoice_id = upload.json()["invoice"]["id"]
        patched = auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={
            "invoice_date": "2026-04-01", "taxable_value": at_the_ceiling,
            "igst": at_the_ceiling, "cgst": "0", "sgst": "0", "total_value": at_the_ceiling,
            "counterparty_gstin": "29AAGCR4375J1ZU", "place_of_supply": "29", "tax_rate": "18",
        })
        assert patched.status_code == 200, patched.text

    filed = auth_client.post("/api/v1/filing/gstr1/filed", json={"period": "2026-04"})

    assert filed.status_code == 201, filed.text
    stored = db_session.query(GSTRReturn).filter_by(business_id=business.id).one()
    assert stored.total_taxable_value == Decimal(at_the_ceiling) * 3
    assert stored.total_taxable_value > MONEY_MAX
