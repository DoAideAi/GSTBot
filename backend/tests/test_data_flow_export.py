"""M2 data flow: export round-trip fidelity — what goes in is what comes out.

``export_business`` is the right-of-access dump: every row this product holds
about one business, serialised as JSON. The contract is that the figures a
business reads back are identical to the figures stored, not rounded, clipped,
or transformed. This traces values through the ``_value`` serialiser and the
full export path, checking that money, dates, enums, and soft-deleted rows
survive the round trip.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.services.data_export import (
    WITHHELD,
    _value,
    export_business,
    exported_tables,
)

EXPORTED_AT = datetime(2026, 4, 30, 12, 0, 0)


# -----------------------------------------------------------------------
# _value serialiser: every type comes out as what JSON can carry
# -----------------------------------------------------------------------

class TestValueSerialiser:

    def test_decimal_becomes_a_string_not_a_float(self):
        assert _value(Decimal("12345.67")) == "12345.67"
        assert isinstance(_value(Decimal("0.10")), str)

    def test_decimal_preserves_trailing_zero(self):
        assert _value(Decimal("100.00")) == "100.00"
        assert _value(Decimal("0.10")) == "0.10"

    def test_date_becomes_iso_string(self):
        assert _value(date(2026, 4, 15)) == "2026-04-15"

    def test_datetime_becomes_iso_string(self):
        assert _value(datetime(2026, 4, 15, 10, 30, 0)) == "2026-04-15T10:30:00"

    def test_enum_becomes_its_value(self):
        assert _value(InvoiceType.SALES) == InvoiceType.SALES.value
        assert _value(InvoiceStatus.PARSED) == InvoiceStatus.PARSED.value

    def test_string_passes_through(self):
        assert _value("hello") == "hello"

    def test_integer_passes_through(self):
        assert _value(42) == 42

    def test_none_passes_through(self):
        assert _value(None) is None

    def test_boolean_passes_through(self):
        assert _value(True) is True


# -----------------------------------------------------------------------
# Withheld columns — the contract about what never leaves
# -----------------------------------------------------------------------

class TestWithheldColumns:

    def test_password_hash_is_withheld(self):
        assert ("users", "hashed_password") in WITHHELD

    def test_oauth_id_is_withheld(self):
        assert ("users", "oauth_id") in WITHHELD

    def test_storage_path_is_withheld(self):
        assert ("invoices", "storage_path") in WITHHELD


# -----------------------------------------------------------------------
# Full export: money round-trips exactly
# -----------------------------------------------------------------------

class TestExportMoneyRoundTrips:

    def test_invoice_amounts_survive_the_export(self, db_session, business):
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            status=InvoiceStatus.PARSED,
            invoice_number="EXP-1",
            invoice_date=date(2026, 4, 15),
            period="2026-04",
            taxable_value=Decimal("99999.99"),
            cgst=Decimal("9000.00"),
            sgst=Decimal("9000.00"),
            igst=Decimal("0.00"),
            cess=Decimal("0.00"),
            total_value=Decimal("117999.99"),
        )
        db_session.add(inv)
        db_session.commit()

        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        [row] = [r for r in doc["tables"]["invoices"] if r["invoice_number"] == "EXP-1"]

        assert row["taxable_value"] == "99999.99"
        assert row["cgst"] == "9000.00"
        assert row["sgst"] == "9000.00"
        assert row["total_value"] == "117999.99"

    def test_enum_fields_are_human_readable_values(self, db_session, business):
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.SALES,
            status=InvoiceStatus.PARSED,
            invoice_number="EXP-ENUM",
        )
        db_session.add(inv)
        db_session.commit()

        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        [row] = [r for r in doc["tables"]["invoices"] if r["invoice_number"] == "EXP-ENUM"]

        assert row["invoice_type"] == InvoiceType.SALES.value
        assert row["status"] == InvoiceStatus.PARSED.value

    def test_date_fields_are_iso_formatted(self, db_session, business):
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="EXP-DATE",
            invoice_date=date(2026, 4, 15),
        )
        db_session.add(inv)
        db_session.commit()

        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        [row] = [r for r in doc["tables"]["invoices"] if r["invoice_number"] == "EXP-DATE"]

        assert row["invoice_date"] == "2026-04-15"


# -----------------------------------------------------------------------
# Soft-deleted rows are included
# -----------------------------------------------------------------------

class TestSoftDeletedRowsAreIncluded:

    def test_a_deleted_row_appears_with_its_timestamp(self, db_session, business):
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="EXP-DEL",
            deleted_at=datetime(2026, 4, 20, 14, 0, 0),
        )
        db_session.add(inv)
        db_session.commit()

        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        [row] = [r for r in doc["tables"]["invoices"] if r["invoice_number"] == "EXP-DEL"]

        assert row["deleted_at"] == "2026-04-20T14:00:00"


# -----------------------------------------------------------------------
# Withheld columns are absent from the exported rows
# -----------------------------------------------------------------------

class TestWithheldColumnsAreAbsentFromExport:

    def test_storage_path_is_not_in_invoice_rows(self, db_session, business):
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="EXP-WH",
            storage_path="/some/secret/path.pdf",
        )
        db_session.add(inv)
        db_session.commit()

        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        [row] = [r for r in doc["tables"]["invoices"] if r["invoice_number"] == "EXP-WH"]

        assert "storage_path" not in row

    def test_user_password_hash_is_not_in_user_rows(self, db_session, business):
        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        for user_row in doc["tables"]["users"]:
            assert "hashed_password" not in user_row
            assert "oauth_id" not in user_row


# -----------------------------------------------------------------------
# Export metadata
# -----------------------------------------------------------------------

class TestExportMetadata:

    def test_format_version_is_present(self, db_session, business):
        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        assert doc["format_version"] == 1

    def test_exported_at_is_the_requested_timestamp(self, db_session, business):
        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        assert doc["exported_at"] == "2026-04-30T12:00:00"

    def test_withheld_list_documents_what_was_omitted(self, db_session, business):
        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        assert "users.hashed_password" in doc["withheld"]
        assert "invoices.storage_path" in doc["withheld"]

    def test_every_table_with_business_id_is_present(self, db_session, business):
        doc = export_business(db_session, business, exported_at=EXPORTED_AT)
        expected = {t.name for t in exported_tables()}
        assert set(doc["tables"]) == expected
