"""The invoice API: upload, tenancy, dedup, plan limits, review."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.business import BusinessPlan
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.supplier import Supplier
from app.services import gst_calendar, invoice_service
from app.services import itc as itc_service
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE


def upload(client, text: str, *, name: str = "invoice.txt", invoice_type: str = "purchase"):
    return client.post(
        "/api/v1/invoices/upload",
        files={"file": (name, text.encode(), "text/plain")},
        data={"invoice_type": invoice_type},
    )


def _business_of(db, invoice_id: int) -> int:
    return db.get(Invoice, invoice_id).business_id


# --------------------------------------------------------------------------
# Upload
# --------------------------------------------------------------------------

def test_upload_extracts_and_stores_an_invoice(auth_client, sample_invoice_text):
    response = upload(auth_client, sample_invoice_text)
    assert response.status_code == 201, response.text
    body = response.json()

    # Celery is off in tests, so extraction has already run inline.
    assert body["queued"] is False
    invoice = body["invoice"]
    assert invoice["status"] == InvoiceStatus.PARSED.value
    assert invoice["invoice_type"] == InvoiceType.PURCHASE.value
    assert invoice["invoice_number"] == "INV-2026-0042"
    assert invoice["invoice_date"] == "2026-04-15"
    assert invoice["period"] == "2026-04"
    assert Decimal(invoice["igst"]) == Decimal("81000.00")
    assert Decimal(invoice["total_value"]) == Decimal("531000.00")


def test_upload_records_the_counterparty_not_the_tenant(auth_client, sample_invoice_text):
    """On a purchase the counterparty is the supplier, never ourselves.

    The invoice carries both GSTINs; picking the wrong one would file our own
    registration as the vendor on every purchase we make.
    """
    invoice = upload(auth_client, sample_invoice_text).json()["invoice"]
    assert invoice["counterparty_gstin"] == SUPPLIER_GSTIN_OTHER_STATE
    assert invoice["counterparty_gstin"] != BUSINESS_GSTIN


def test_a_purchase_billing_our_own_gstin_as_the_vendor_takes_the_other_side(auth_client):
    """A vendor who printed our GSTIN in the seller slot is not the seller.

    It happens when a supplier reuses a customer's copy of a document as a
    template and changes only the figures. Taken at face value the purchase is
    booked against ourselves: a supplier row for our own registration, our own
    GSTIN filed as the vendor in GSTR-1's counterpart, and a reconciliation
    that can never match because no GSTR-2B will ever declare it. The other
    GSTIN on the paper is the only one that can be theirs.
    """
    swapped = f"""\
UMANG TRADERS
GSTIN: {BUSINESS_GSTIN}

TAX INVOICE

Invoice No: SWAP-1
Invoice Date: 15/04/2026
Place of Supply: 27 Maharashtra

Bill To:
NORTHWIND SUPPLIES PRIVATE LIMITED
GSTIN: {SUPPLIER_GSTIN_OTHER_STATE}

Taxable Value:  450000.00
IGST @ 18%:      81000.00
Grand Total:    531000.00
"""
    invoice = upload(auth_client, swapped, name="swapped.txt").json()["invoice"]

    assert invoice["counterparty_gstin"] == SUPPLIER_GSTIN_OTHER_STATE
    assert invoice["counterparty_gstin"] != BUSINESS_GSTIN


def test_upload_creates_a_supplier_for_a_purchase(auth_client, db_session, sample_invoice_text):
    upload(auth_client, sample_invoice_text)
    supplier = db_session.query(Supplier).filter_by(gstin=SUPPLIER_GSTIN_OTHER_STATE).one()
    assert supplier.state_code == "29"


def test_two_invoices_from_one_supplier_share_a_supplier_row(auth_client, db_session):
    for number in ("A-1", "A-2"):
        upload(
            auth_client,
            f"GSTIN: {SUPPLIER_GSTIN_OTHER_STATE}\nInvoice No: {number}\n"
            f"Invoice Date: 01/04/2026\nTotal Amount: 1000.00",
            name=f"{number}.txt",
        )
    assert db_session.query(Supplier).filter_by(gstin=SUPPLIER_GSTIN_OTHER_STATE).count() == 1


class TestTwoWorkersMeetingAtANewSupplier:
    """Concurrent uploads from a supplier neither worker has seen before.

    ``get_or_create_supplier`` looks, finds nothing, and inserts. When a
    business drags in a folder of invoices from a new supplier, several workers
    do that at once and only the first insert survives ``uq_suppliers_business_gstin``.
    The loser's invoice was being marked ``failed`` and told the user its
    document was already on file — a statement about a duplicate that does not
    exist, over a supplier row the winner had already created correctly.
    """

    @staticmethod
    def _blind_the_lookup(monkeypatch, db_session):
        """Make the *next* supplier lookup miss, as a concurrent one would."""
        real_scalar = db_session.scalar
        missed = {"once": False}

        def blind(statement, *args, **kwargs):
            found = real_scalar(statement, *args, **kwargs)
            if isinstance(found, Supplier) and not missed["once"]:
                missed["once"] = True
                return None
            return found

        monkeypatch.setattr(db_session, "scalar", blind)

    def test_the_loser_of_the_race_still_gets_its_invoice(
        self, auth_client, db_session, business, sample_invoice_text, monkeypatch
    ):
        db_session.add(
            Supplier(
                business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE, state_code="29"
            )
        )
        db_session.flush()
        self._blind_the_lookup(monkeypatch, db_session)

        invoice = upload(auth_client, sample_invoice_text).json()["invoice"]

        assert invoice["status"] != InvoiceStatus.FAILED.value
        assert invoice["parse_error"] is None
        assert invoice["counterparty_gstin"] == SUPPLIER_GSTIN_OTHER_STATE

    def test_it_is_linked_to_the_row_the_winner_created(
        self, auth_client, db_session, business, sample_invoice_text, monkeypatch
    ):
        db_session.add(
            Supplier(
                business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE, state_code="29"
            )
        )
        db_session.flush()
        self._blind_the_lookup(monkeypatch, db_session)

        invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

        suppliers = db_session.query(Supplier).filter_by(
            gstin=SUPPLIER_GSTIN_OTHER_STATE
        ).all()
        assert len(suppliers) == 1
        assert db_session.get(Invoice, invoice_id).supplier_id == suppliers[0].id

    def test_the_lost_race_is_not_reported_as_a_duplicate_invoice(
        self, auth_client, db_session, business, sample_invoice_text, monkeypatch
    ):
        db_session.add(
            Supplier(
                business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE, state_code="29"
            )
        )
        db_session.flush()
        self._blind_the_lookup(monkeypatch, db_session)

        invoice = upload(auth_client, sample_invoice_text).json()["invoice"]

        assert "already on file" not in (invoice["parse_error"] or "")

    def test_a_genuine_duplicate_is_still_refused(self, auth_client, sample_invoice_text):
        """The race fix must not swallow the constraint it shares a handler with."""
        upload(auth_client, sample_invoice_text)
        # Same invoice number and supplier, different bytes, so the file-hash
        # check at upload cannot catch it and the natural key has to.
        second = upload(
            auth_client, sample_invoice_text + "\nDuplicate re-scan\n", name="rescan.txt"
        ).json()["invoice"]

        assert second["status"] == InvoiceStatus.FAILED.value
        assert "already on file" in second["parse_error"]


def test_a_sales_upload_does_not_create_a_supplier(auth_client, db_session, sample_invoice_text):
    upload(auth_client, sample_invoice_text, invoice_type="sales")
    assert db_session.query(Supplier).count() == 0


def test_upload_requires_authentication(client, sample_invoice_text):
    assert upload(client, sample_invoice_text).status_code == 401


def test_an_empty_file_is_rejected(auth_client):
    response = auth_client.post(
        "/api/v1/invoices/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
        data={"invoice_type": "purchase"},
    )
    assert response.status_code == 400
    # Named, and given the usual cause. Zero bytes is nearly always a download
    # that has not finished or a cloud-sync placeholder, not a file anyone
    # chose to send.
    detail = response.json()["detail"]
    assert "empty.txt" in detail
    assert "0 bytes" in detail


def test_an_unsupported_file_type_is_rejected(auth_client):
    response = auth_client.post(
        "/api/v1/invoices/upload",
        files={"file": ("virus.exe", b"MZ\x90\x00", "application/x-msdownload")},
        data={"invoice_type": "purchase"},
    )
    assert response.status_code == 415


def test_a_refused_file_type_is_told_what_would_have_worked(auth_client):
    """What someone does next is convert the file or pick another one.

    Neither is a decision they can make from "unsupported file type", and the
    callers who reach this are the ones the app's own check did not stop — a
    script posting at the API, a browser that typed the file differently.
    """
    response = auth_client.post(
        "/api/v1/invoices/upload",
        files={"file": ("scan.dwg", b"AC1027", "image/vnd.dwg")},
        data={"invoice_type": "purchase"},
    )

    assert response.status_code == 415
    detail = response.json()["detail"]
    assert "scan.dwg" in detail
    # The list comes off ALLOWED_EXTENSIONS, so a format added there is
    # offered here without anyone remembering to update a sentence.
    assert "PDF" in detail and "HEIC" in detail and "XLSX" in detail


class TestTheClientsContentTypeIsNotStoredAsSent:
    """P16 M5: ``invoices.content_type`` is ``VARCHAR(100)``. The part's
    Content-Type header was stored verbatim, so parameters or a long value
    overflowed it on Postgres — a 500 the SQLite suite could not see, because
    SQLite does not enforce the length. Asserted on what is stored."""

    COLUMN = Invoice.__table__.c.content_type.type.length

    @pytest.mark.parametrize(
        ("sent", "stored"),
        [
            ('text/plain; charset=utf-8; name="' + "x" * 200 + '"', "text/plain"),
            ("TEXT/PLAIN", "text/plain"),
            ("application/" + "x" * 150, None),
            ("not a media type at all", None),
        ],
    )
    def test_only_the_bare_media_type_is_kept(
        self, auth_client, db_session, sample_invoice_text, sent, stored
    ):
        response = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("bill.txt", sample_invoice_text.encode(), sent)},
            data={"invoice_type": "purchase"},
        )
        assert response.status_code == 201, response.text
        invoice = db_session.get(Invoice, response.json()["invoice"]["id"])
        assert invoice.content_type == stored
        assert invoice.content_type is None or len(invoice.content_type) <= self.COLUMN

    def test_the_bulk_path_stores_the_same(self, auth_client, db_session, sample_invoice_text):
        response = auth_client.post(
            "/api/v1/invoices/bulk",
            files=[
                ("files", ("bill.txt", sample_invoice_text.encode(), "text/plain; " + "p" * 200))
            ],
            data={"invoice_type": "purchase"},
        )
        assert response.status_code in (200, 201, 207), response.text
        (invoice,) = db_session.query(Invoice).all()
        assert invoice.content_type == "text/plain"

    def test_a_typed_pdf_with_parameters_is_still_a_pdf(self, auth_client):
        # Parameters no longer hide an allowed type: no extension to fall back on.
        response = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("scan", b"%PDF-1.4 not really", "application/pdf; name=scan")},
            data={"invoice_type": "purchase"},
        )
        assert response.status_code != 415, response.text


def test_an_oversized_file_is_rejected(auth_client):
    from app.core.config import settings

    oversized = b"x" * (settings.max_upload_mb * 1024 * 1024 + 1)
    response = auth_client.post(
        "/api/v1/invoices/upload",
        files={"file": ("big.txt", oversized, "text/plain")},
        data={"invoice_type": "purchase"},
    )
    assert response.status_code == 413


def test_an_oversized_file_is_told_how_far_over_it_is(auth_client):
    """By how much is what decides what to do about it.

    A phone scan a little over the limit is re-exported at a lower resolution;
    one at several times it is a batch that wants splitting. "Exceeds the
    limit" separates neither.
    """
    from app.core.config import settings

    # Only just over. `max_request_bytes` sits a megabyte above the file limit
    # and is enforced by the middleware before a route sees the body, so a
    # comfortably oversized file never reaches the message under test — it is
    # refused by the envelope ceiling instead, which reports its own number.
    over_by = 0.4
    oversized = b"x" * int((settings.max_upload_mb + over_by) * 1024 * 1024)
    response = auth_client.post(
        "/api/v1/invoices/upload",
        files={"file": ("ledger-scan.pdf", oversized, "application/pdf")},
        data={"invoice_type": "purchase"},
    )

    assert response.status_code == 413
    detail = response.json()["detail"]
    assert "ledger-scan.pdf" in detail
    assert f"{settings.max_upload_mb + over_by:.1f} MB" in detail
    assert f"{settings.max_upload_mb} MB limit" in detail


def test_an_unparseable_upload_is_kept_rather_than_refused(auth_client):
    """A file we cannot read is still the user's document.

    It comes back as a row with warnings, because a rejected upload means the
    business has to find the paper again.
    """
    response = upload(auth_client, "this text contains no invoice fields whatsoever")
    assert response.status_code == 201
    invoice = response.json()["invoice"]
    assert invoice["status"] == InvoiceStatus.PARSED.value
    assert invoice["warnings"]


# --------------------------------------------------------------------------
# Deduplication
# --------------------------------------------------------------------------

def test_the_same_file_twice_is_a_conflict(auth_client, sample_invoice_text):
    """Duplicate uploads are duplicate ITC claims, which draw a notice."""
    first = upload(auth_client, sample_invoice_text)
    assert first.status_code == 201

    second = upload(auth_client, sample_invoice_text)
    assert second.status_code == 409
    assert second.json()["detail"]["invoice_id"] == first.json()["invoice"]["id"]


def test_the_same_file_may_be_uploaded_by_a_different_tenant(
    client, auth_client, other_tenant, sample_invoice_text
):
    """Dedup is per tenant.

    Two businesses can legitimately hold the same invoice — one as a sale, the
    other as a purchase — and a global hash check would block the second.
    """
    assert upload(auth_client, sample_invoice_text).status_code == 201

    client.headers.update({"Authorization": f"Bearer {other_tenant}"})
    assert upload(client, sample_invoice_text).status_code == 201


class TestDeletingAnInvoiceFreesItsNumber:
    """Deleting is soft, and the natural key has to agree.

    Delete a badly-read invoice, re-scan the paper, upload it again: that is
    the ordinary way to fix one, and it is the only way, because a re-scan is
    different bytes and so the file-hash check never fires. A tombstone that
    kept holding the key turned the second upload into ``failed`` — "already
    on file", naming an invoice the API answers 404 for — and there was no way
    back, because the delete that was meant to undo it had already happened.
    """

    def _rescan(self, client, text: str, *, name: str):
        """The same invoice, photographed again: same fields, different bytes."""
        return upload(client, text + "\n \n", name=name).json()["invoice"]

    def test_the_same_invoice_can_be_uploaded_again_after_a_delete(
        self, auth_client, sample_invoice_text
    ):
        first = upload(auth_client, sample_invoice_text).json()["invoice"]
        assert auth_client.delete(f"/api/v1/invoices/{first['id']}").status_code == 204

        second = self._rescan(auth_client, sample_invoice_text, name="rescan.txt")
        assert second["status"] == "parsed", second
        assert second["id"] != first["id"]

    def test_the_replacement_carries_the_figures_rather_than_an_error(
        self, auth_client, sample_invoice_text
    ):
        first = upload(auth_client, sample_invoice_text).json()["invoice"]
        auth_client.delete(f"/api/v1/invoices/{first['id']}")

        second = self._rescan(auth_client, sample_invoice_text, name="rescan.txt")
        assert second["parse_error"] is None
        assert second["invoice_number"] == first["invoice_number"]
        assert Decimal(second["taxable_value"]) == Decimal(first["taxable_value"])

    def test_the_replacement_is_the_one_the_period_files(
        self, auth_client, sample_invoice_text
    ):
        """A ``failed`` row is out of the filing pool; the point is to be in it."""
        first = upload(auth_client, sample_invoice_text).json()["invoice"]
        auth_client.delete(f"/api/v1/invoices/{first['id']}")
        second = self._rescan(auth_client, sample_invoice_text, name="rescan.txt")

        listed = auth_client.get("/api/v1/invoices").json()["items"]
        assert [row["id"] for row in listed] == [second["id"]]

    def test_a_duplicate_is_still_refused_while_the_original_lives(
        self, auth_client, sample_invoice_text
    ):
        """The constraint still does its job — that is the whole reason it exists.

        Two live copies of one invoice are two claims of the same credit, which
        is what draws a departmental notice.
        """
        upload(auth_client, sample_invoice_text)
        second = self._rescan(auth_client, sample_invoice_text, name="rescan.txt")
        assert second["status"] == "failed"
        assert "already on file" in second["parse_error"]

    def test_deleting_twice_over_leaves_the_number_free_each_time(
        self, auth_client, sample_invoice_text
    ):
        """Two tombstones on one key, which a partial index has to tolerate."""
        for round_number in range(3):
            invoice = self._rescan(
                auth_client, sample_invoice_text + " " * round_number, name=f"r{round_number}.txt"
            )
            assert invoice["status"] == "parsed", invoice
            auth_client.delete(f"/api/v1/invoices/{invoice['id']}")

    def test_the_tombstones_are_kept_rather_than_overwritten(
        self, auth_client, db_session, sample_invoice_text
    ):
        """Soft delete is an audit record; freeing the key must not drop it."""
        first = upload(auth_client, sample_invoice_text).json()["invoice"]
        auth_client.delete(f"/api/v1/invoices/{first['id']}")
        self._rescan(auth_client, sample_invoice_text, name="rescan.txt")

        assert db_session.get(Invoice, first["id"]).deleted_at is not None


# --------------------------------------------------------------------------
# Plan limits
# --------------------------------------------------------------------------

def test_the_free_plan_caps_monthly_uploads(auth_client, db_session, business, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "plan_monthly_invoice_limits", "free=2,starter=500,pro=0")
    for i in range(2):
        assert upload(auth_client, f"Invoice No: A-{i}\nTotal Amount: 100.00",
                      name=f"a{i}.txt").status_code == 201

    blocked = upload(auth_client, "Invoice No: A-3\nTotal Amount: 100.00", name="a3.txt")
    assert blocked.status_code == 402
    assert "upgrade" in blocked.json()["detail"].lower()


def test_a_paid_plan_is_uncapped(auth_client, db_session, business, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "plan_monthly_invoice_limits", "free=1,pro=0")
    business.plan = BusinessPlan.PRO
    db_session.commit()

    for i in range(3):
        assert upload(auth_client, f"Invoice No: B-{i}\nTotal Amount: 100.00",
                      name=f"b{i}.txt").status_code == 201


def test_soft_deleted_invoices_do_not_count_against_the_plan(
    auth_client, db_session, monkeypatch
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "plan_monthly_invoice_limits", "free=1")
    first = upload(auth_client, "Invoice No: C-1\nTotal Amount: 100.00", name="c1.txt")
    assert first.status_code == 201

    auth_client.delete(f"/api/v1/invoices/{first.json()['invoice']['id']}")
    assert upload(auth_client, "Invoice No: C-2\nTotal Amount: 100.00",
                  name="c2.txt").status_code == 201


class TestThePlanMonthIsTheIndianMonth:
    """A business's allowance resets when *their* month rolls over.

    Counted against UTC midnight, the reset is 05:30 IST on the 1st: a business
    that used up October is told to upgrade for five and a half hours of a
    November they have already entered, and whatever they do upload in that
    window is charged to the month that closed.
    """

    def test_the_month_starts_at_midnight_in_india(self):
        start, end = invoice_service.month_bounds("2026-05")

        # 00:00 IST on 1 May is 18:30 UTC on 30 April.
        assert start == datetime(2026, 4, 30, 18, 30, tzinfo=UTC)
        assert end == datetime(2026, 5, 31, 18, 30, tzinfo=UTC)

    def test_december_rolls_into_january(self):
        start, end = invoice_service.month_bounds("2026-12")

        assert start == datetime(2026, 11, 30, 18, 30, tzinfo=UTC)
        assert end == datetime(2026, 12, 31, 18, 30, tzinfo=UTC)

    def test_the_bounds_are_utc_because_the_stored_timestamps_are(self):
        """Not merely cosmetic — an IST-aware bound is wrong on SQLite.

        SQLAlchemy's SQLite DateTime formats whatever wall clock the value
        carries and drops the offset, so handing the query 00:00+05:30 would
        compare "00:00" against UTC-stored rows: right on Postgres, five and a
        half hours out in the suite, and nothing would catch it.
        """
        start, end = invoice_service.month_bounds("2026-05")
        assert start.utcoffset() == timedelta(0)
        assert end.utcoffset() == timedelta(0)

    def test_an_upload_just_after_midnight_ist_counts_against_the_new_month(
        self, db_session, business
    ):
        db_session.add(
            Invoice(
                business_id=business.id,
                invoice_type=InvoiceType.PURCHASE,
                status=InvoiceStatus.PARSED,
                # 00:30 IST on 1 May 2026 — still 30 April in UTC.
                created_at=datetime(2026, 4, 30, 19, 0, tzinfo=UTC),
                updated_at=datetime(2026, 4, 30, 19, 0, tzinfo=UTC),
            )
        )
        db_session.commit()

        assert invoice_service.monthly_usage(db_session, business.id, "2026-05") == 1
        assert invoice_service.monthly_usage(db_session, business.id, "2026-04") == 0


# --------------------------------------------------------------------------
# Listing and tenancy
# --------------------------------------------------------------------------

def test_list_returns_only_the_callers_invoices(
    client, auth_client, other_tenant, sample_invoice_text
):
    upload(auth_client, sample_invoice_text)
    own_token = auth_client.headers["Authorization"]

    client.headers.update({"Authorization": f"Bearer {other_tenant}"})
    upload(client, "Invoice No: OTHER-1\nTotal Amount: 500.00", name="other.txt")
    rival = client.get("/api/v1/invoices").json()
    assert rival["total"] == 1
    assert rival["items"][0]["invoice_number"] == "OTHER-1"

    client.headers.update({"Authorization": own_token})
    mine = client.get("/api/v1/invoices").json()
    assert mine["total"] == 1
    assert mine["items"][0]["invoice_number"] == "INV-2026-0042"


def test_another_tenants_invoice_is_not_found(
    client, auth_client, other_tenant, sample_invoice_text
):
    """404 rather than 403.

    A 403 would confirm the id exists, which is enough to measure a
    competitor's invoice volume by probing.
    """
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    client.headers.update({"Authorization": f"Bearer {other_tenant}"})
    assert client.get(f"/api/v1/invoices/{invoice_id}").status_code == 404
    # A body that passes validation, so the 404 is the tenancy check answering
    # and not a malformed field being refused before the row is ever looked up.
    assert (
        client.patch(f"/api/v1/invoices/{invoice_id}", json={"hsn_code": "8471"}).status_code
        == 404
    )
    assert client.delete(f"/api/v1/invoices/{invoice_id}").status_code == 404


def test_list_filters(auth_client, sample_invoice_text):
    upload(auth_client, sample_invoice_text)
    upload(auth_client, "Invoice No: S-1\nInvoice Date: 10/05/2026\nTotal Amount: 200.00",
           name="s1.txt", invoice_type="sales")

    assert auth_client.get("/api/v1/invoices?invoice_type=sales").json()["total"] == 1
    assert auth_client.get("/api/v1/invoices?invoice_type=purchase").json()["total"] == 1
    assert auth_client.get("/api/v1/invoices?period=2026-04").json()["total"] == 1
    assert auth_client.get("/api/v1/invoices?period=2026-05").json()["total"] == 1
    assert auth_client.get("/api/v1/invoices?period=2026-06").json()["total"] == 0
    assert auth_client.get("/api/v1/invoices?search=INV-2026").json()["total"] == 1
    assert (
        auth_client.get(
            f"/api/v1/invoices?counterparty_gstin={SUPPLIER_GSTIN_OTHER_STATE}"
        ).json()["total"]
        == 1
    )


def test_list_rejects_a_malformed_period(auth_client):
    assert auth_client.get("/api/v1/invoices?period=April").status_code == 422


def test_list_paginates(auth_client):
    for i in range(5):
        upload(auth_client, f"Invoice No: P-{i}\nTotal Amount: 100.00", name=f"p{i}.txt")

    page = auth_client.get("/api/v1/invoices?limit=2&offset=0").json()
    assert page["total"] == 5
    assert len(page["items"]) == 2

    tail = auth_client.get("/api/v1/invoices?limit=2&offset=4").json()
    assert len(tail["items"]) == 1


class TestSorting:
    """`sort` orders the register; nulls land last regardless of direction."""

    def test_by_date_puts_undated_invoices_last_either_way(self, auth_client, db_session, business):
        db_session.add_all(
            [
                Invoice(
                    business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED, invoice_number="A",
                    invoice_date=date(2026, 4, 1),
                ),
                Invoice(
                    business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED, invoice_number="B",
                    invoice_date=date(2026, 4, 15),
                ),
                Invoice(
                    business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED, invoice_number="C", invoice_date=None,
                ),
            ]
        )
        db_session.commit()

        desc = auth_client.get("/api/v1/invoices?sort=date_desc").json()["items"]
        assert [i["invoice_number"] for i in desc] == ["B", "A", "C"]

        asc = auth_client.get("/api/v1/invoices?sort=date_asc").json()["items"]
        assert [i["invoice_number"] for i in asc] == ["A", "B", "C"]

    def test_by_value_uses_the_derived_figure_not_the_raw_column(
        self, auth_client, db_session, business
    ):
        """A bare "Total:" the heuristic misses leaves `total_value` at zero.

        Sorting by that raw column would put a real ₹590 supply after every
        invoice extraction happened to total correctly — the same fault
        `Invoice.invoice_value` exists to fix on the screens that read it.
        """
        db_session.add_all(
            [
                Invoice(
                    business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED, invoice_number="LOW",
                    total_value=Decimal("100.00"),
                ),
                Invoice(
                    business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED, invoice_number="DERIVED",
                    total_value=Decimal("0.00"), taxable_value=Decimal("500.00"),
                    cgst=Decimal("45.00"), sgst=Decimal("45.00"),
                ),
                Invoice(
                    business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED, invoice_number="HIGH",
                    total_value=Decimal("1000.00"),
                ),
            ]
        )
        db_session.commit()

        items = auth_client.get("/api/v1/invoices?sort=value_desc").json()["items"]
        assert [i["invoice_number"] for i in items] == ["HIGH", "DERIVED", "LOW"]

    def test_by_number_puts_numberless_invoices_last_either_way(
        self, auth_client, db_session, business
    ):
        db_session.add_all(
            [
                Invoice(
                    business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED, invoice_number="B-1",
                ),
                Invoice(
                    business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED, invoice_number="A-1",
                ),
                Invoice(
                    business_id=business.id, invoice_type=InvoiceType.PURCHASE,
                    status=InvoiceStatus.PARSED, invoice_number=None,
                ),
            ]
        )
        db_session.commit()

        items = auth_client.get("/api/v1/invoices?sort=number_asc").json()["items"]
        assert [i["invoice_number"] for i in items] == ["A-1", "B-1", None]

    def test_an_unknown_sort_is_rejected(self, auth_client):
        assert auth_client.get("/api/v1/invoices?sort=nonsense").status_code == 422


# --------------------------------------------------------------------------
# Review and correction
# --------------------------------------------------------------------------

def test_patch_applies_corrections(auth_client, sample_invoice_text):
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    response = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"invoice_number": "CORRECTED-1", "taxable_value": "450000.00"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["invoice_number"] == "CORRECTED-1"
    assert body["parsed_with"] == "manual"
    assert body["extraction_confidence"] == 1.0


def test_patch_leaves_unmentioned_fields_alone(auth_client, sample_invoice_text):
    """A user fixing one field must not blank the rest by omission."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"hsn_code": "84713090"}
    ).json()
    assert body["hsn_code"] == "84713090"
    assert Decimal(body["igst"]) == Decimal("81000.00")
    assert body["invoice_number"] == "INV-2026-0042"


def test_patch_recomputes_the_period_from_a_corrected_date(auth_client, sample_invoice_text):
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"invoice_date": "2026-05-20"}
    ).json()
    assert body["period"] == "2026-05"


def test_patch_rejects_an_invalid_gstin(auth_client, sample_invoice_text):
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    response = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"counterparty_gstin": "27AAPFU0939F1ZW"}
    )
    assert response.status_code == 422


class TestTheCodedFieldsAReviewerCanType:
    """``place_of_supply`` and ``hsn_code`` are codes, not free text.

    The extractor has always checked both. A correction did not, so the one
    path a person types into was the one that let anything through — and what
    it lets through is copied verbatim into the GSTR-1 the portal rejects.
    """

    @pytest.fixture()
    def invoice_id(self, auth_client, sample_invoice_text) -> int:
        return upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    def test_a_place_of_supply_that_is_not_a_state_is_refused(self, auth_client, invoice_id):
        response = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"place_of_supply": "ZZ"}
        )
        assert response.status_code == 422, response.text
        assert "state code" in response.text

    def test_a_state_number_that_does_not_exist_is_refused(self, auth_client, invoice_id):
        # 88 is inside the two-digit shape and is not a code GST assigns.
        response = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"place_of_supply": "88"}
        )
        assert response.status_code == 422, response.text

    def test_the_refused_code_never_reaches_the_return(self, auth_client, invoice_id):
        before = auth_client.get(f"/api/v1/invoices/{invoice_id}").json()["place_of_supply"]
        auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"place_of_supply": "ZZ"})
        after = auth_client.get(f"/api/v1/invoices/{invoice_id}").json()["place_of_supply"]
        assert after == before

    def test_a_single_digit_state_is_padded_rather_than_refused(self, auth_client, invoice_id):
        """``7`` is what a person types for Delhi; ``07`` is what the portal wants."""
        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"place_of_supply": "7"}
        ).json()
        assert body["place_of_supply"] == "07"

    def test_a_real_state_code_still_goes_through(self, auth_client, invoice_id):
        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"place_of_supply": "29"}
        ).json()
        assert body["place_of_supply"] == "29"

    def test_the_place_of_supply_can_still_be_cleared(self, auth_client, invoice_id):
        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"place_of_supply": None}
        ).json()
        assert body["place_of_supply"] is None

    # Two characters at most: the field carries ``max_length=2``, which is
    # checked before the validator, so a wider run of spaces is refused on
    # length and never reaches the clearing path this is about.
    @pytest.mark.parametrize("blank", ["", " ", "  ", "\t"])
    def test_emptying_the_box_clears_the_place_of_supply_rather_than_refusing_it(
        self, auth_client, invoice_id, blank
    ):
        """A cleared text box arrives as ``""``, not as ``null``.

        Which is the ordinary way a reviewer removes a code they should not
        have entered: select the contents, delete, save. Read as a *value* it
        is not a state code and 422s, and the reviewer is told to fix a field
        they were trying to empty, with no spelling of "empty" that the form
        will accept. Treated as clearing, it agrees with sending ``null``.
        """
        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"place_of_supply": blank}
        )
        assert body.status_code == 200, body.text
        assert body.json()["place_of_supply"] is None

    @pytest.mark.parametrize("bad", ["notdigit", "12345", "123", "8471301X"])
    def test_an_hsn_the_portal_will_not_take_is_refused(self, auth_client, invoice_id, bad):
        response = auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"hsn_code": bad})
        assert response.status_code == 422, response.text
        assert "HSN" in response.text

    @pytest.mark.parametrize("good", ["8471", "847130", "84713010"])
    def test_the_three_lengths_the_portal_takes_go_through(
        self, auth_client, invoice_id, good
    ):
        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"hsn_code": good}
        ).json()
        assert body["hsn_code"] == good

    def test_the_hsn_can_still_be_cleared(self, auth_client, invoice_id):
        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"hsn_code": None}
        ).json()
        assert body["hsn_code"] is None

    @pytest.mark.parametrize("blank", ["", "   ", "\t", "\n "])
    def test_emptying_the_box_clears_the_hsn_rather_than_refusing_it(
        self, auth_client, invoice_id, blank
    ):
        """Same clearing rule as ``place_of_supply`` above, and for the same
        reason — the two coded boxes sit next to each other on the review
        screen, and a reviewer who learns that one empties by being emptied
        should not find the other 422ing."""
        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"hsn_code": blank}
        )
        assert body.status_code == 200, body.text
        assert body.json()["hsn_code"] is None


@pytest.mark.parametrize(
    "field",
    ["taxable_value", "cgst", "sgst", "igst", "cess", "total_value",
     "itc_eligible", "reverse_charge"],
)
def test_patch_refuses_to_clear_a_field_the_invoice_must_have(
    auth_client, sample_invoice_text, field
):
    """Clearing a tax box is a validation error, not a duplicate.

    These columns are NOT NULL. The null went through to the database and came
    back as an integrity error, which the API reports as 409 "that record
    conflicts with one that already exists" — a reviewer is then hunting for a
    duplicate invoice that was never there. It also leaves the request's
    session needing a rollback.
    """
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    response = auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={field: None})

    assert response.status_code == 422, response.text
    assert field in response.text
    # And the invoice is untouched, not half-written.
    after = auth_client.get(f"/api/v1/invoices/{invoice_id}").json()
    assert Decimal(after["igst"]) == Decimal("81000.00")


def test_patch_still_zeroes_a_head_that_is_sent_as_zero(auth_client, sample_invoice_text):
    """Refusing null must not refuse the correction it stands in for."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"igst": "0.00", "cgst": "40500.00", "sgst": "40500.00"},
    ).json()

    assert Decimal(body["igst"]) == Decimal("0.00")
    assert Decimal(body["cgst"]) == Decimal("40500.00")


def test_patch_still_clears_a_field_that_can_be_empty(auth_client, sample_invoice_text):
    """A misread GSTIN is taken off the invoice by sending null."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"counterparty_gstin": None}
    ).json()

    assert body["counterparty_gstin"] is None


def test_a_correction_links_a_supplier(auth_client, db_session):
    invoice_id = upload(auth_client, "no fields here", name="blank.txt").json()["invoice"]["id"]
    auth_client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"counterparty_gstin": SUPPLIER_GSTIN_SAME_STATE, "counterparty_name": "Mumbai HW"},
    )
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.supplier_id is not None
    assert db_session.get(Supplier, invoice.supplier_id).gstin == SUPPLIER_GSTIN_SAME_STATE


# --------------------------------------------------------------------------
# The two facts the ITC reversal rules turn on
#
# Rule 37 reverses the credit on a purchase left unpaid 180 days past its
# invoice date; Rule 43 spreads a capital good's credit over sixty months
# rather than claiming it in the month of purchase. Both are read off the
# invoice row by app.services.itc, and neither was settable through the API —
# so a business could not prevent a reversal that was not due, and every
# capital good claimed its whole credit in one month.
# --------------------------------------------------------------------------

def test_recording_a_payment_takes_the_invoice_off_the_rule_37_clock(
    auth_client, db_session, sample_invoice_text
):
    """Nothing could set ``paid_at``, so the reversal was unavoidable.

    Every purchase reversed its credit 180 days after its invoice date and
    stayed reversed for good, which over-reverses table 4(B) of GSTR-3B: the
    business pays cash it does not owe on a supplier it has actually paid.
    """
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    as_of = date(2026, 4, 15) + timedelta(days=200)

    before = itc_service.rule_37(
        itc_service.purchase_invoices(db_session, _business_of(db_session, invoice_id)),
        as_of=as_of,
    )
    assert before.reversal.igst == Decimal("81000.00")

    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"paid_at": "2026-05-01"}
    ).json()
    assert body["paid_at"] == "2026-05-01"

    db_session.expire_all()
    after = itc_service.rule_37(
        itc_service.purchase_invoices(db_session, _business_of(db_session, invoice_id)),
        as_of=as_of,
    )
    assert after.reversal.igst == Decimal("0.00")
    assert after.overdue == []


def test_a_payment_can_be_taken_back_off_an_invoice(auth_client, sample_invoice_text):
    """``null`` means "not paid after all", which puts it back on the clock."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"paid_at": "2026-05-01"})

    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"paid_at": None}
    ).json()

    assert body["paid_at"] is None


def test_a_payment_date_in_the_future_is_refused(auth_client, sample_invoice_text):
    """A mistyped year would silently cancel a reversal that is genuinely due."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    tomorrow = gst_calendar.today_ist() + timedelta(days=1)

    response = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"paid_at": tomorrow.isoformat()}
    )

    assert response.status_code == 422, response.text
    assert "future" in response.text


def test_a_payment_before_the_invoice_was_issued_is_refused(
    auth_client, sample_invoice_text
):
    """Rule 37 counts from the invoice date, so this is not a payment at all."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    response = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"paid_at": "2025-04-01"}
    )

    assert response.status_code == 422, response.text
    assert "cannot be paid before it was issued" in response.text


def test_a_payment_and_a_corrected_date_are_judged_against_each_other(
    auth_client, sample_invoice_text
):
    """Both dates can arrive together, and the new one is what governs."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    response = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"invoice_date": "2026-01-10", "paid_at": "2026-02-01"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["paid_at"] == "2026-02-01"


def test_moving_the_invoice_past_a_recorded_payment_is_refused(
    auth_client, sample_invoice_text
):
    """The same rule, from the other side, where it was not being enforced.

    Only the *incoming* payment date was compared, so an edit that moved the
    invoice forward past a payment already on file produced exactly the state
    the check exists to refuse — and produced it silently. Correcting a misread
    year is the commonest reason anyone touches this field, so it is not an
    exotic route into it.
    """
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"paid_at": "2026-05-01"})

    response = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"invoice_date": "2026-06-01"}
    )

    assert response.status_code == 422, response.text
    assert "cannot be paid before it was issued" in response.text


def test_the_invoice_the_refusal_protects_is_left_untouched(
    auth_client, sample_invoice_text
):
    """What the silent version cost: a purchase that never reverses again.

    An invoice reading as paid is off the Rule 37 clock for good. Written with
    a payment predating it, the row asserts a payment that could not have
    happened and quietly suppresses a reversal that is genuinely due, however
    long the supplier goes unpaid.
    """
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"paid_at": "2026-05-01"})

    auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"invoice_date": "2026-06-01"}
    )

    body = auth_client.get(f"/api/v1/invoices/{invoice_id}").json()
    assert body["invoice_date"] == "2026-04-15"
    assert body["paid_at"] == "2026-05-01"
    assert body["period"] == "2026-04"


def test_clearing_the_payment_frees_the_invoice_date_to_move(
    auth_client, sample_invoice_text
):
    """The refusal names a real conflict, and says how to resolve it.

    Both dates travel in one PATCH, so a reviewer who has decided the invoice
    was never paid can say so and correct the date in the same request.
    """
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"paid_at": "2026-05-01"})

    response = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"invoice_date": "2026-06-01", "paid_at": None},
    )

    assert response.status_code == 200, response.text
    assert response.json()["invoice_date"] == "2026-06-01"
    assert response.json()["paid_at"] is None


def test_an_edit_touching_neither_date_is_still_allowed(
    auth_client, sample_invoice_text
):
    """Comparing the stored dates must not block edits that do not move them.

    The check now reads what the row *will* hold rather than what the request
    sends, and every PATCH goes through it — so a row already holding a
    consistent pair has to keep passing.
    """
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"paid_at": "2026-05-01"})

    response = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"hsn_code": "84713010"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["hsn_code"] == "84713010"
    assert response.json()["paid_at"] == "2026-05-01"


def test_marking_a_purchase_capital_goods_moves_its_credit_to_rule_43(
    auth_client, db_session, sample_invoice_text
):
    """Its credit belongs to sixty months, not to the month of purchase."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    business_id = _business_of(db_session, invoice_id)

    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"is_capital_good": True}
    ).json()
    assert body["is_capital_good"] is True

    db_session.expire_all()
    summary = itc_service.summarise(db_session, business_id, "2026-04")
    assert summary.available.igst == Decimal("0.00")
    assert summary.proportionate.capital_credit.igst == Decimal("81000.00")
    assert summary.proportionate.capital_credit_this_month.igst == Decimal("1350.00")


def test_is_capital_good_cannot_be_cleared_to_null(auth_client, sample_invoice_text):
    """The column is NOT NULL; ``false`` is how it is turned off."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    assert (
        auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"is_capital_good": None}
        ).status_code
        == 422
    )
    assert (
        auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"is_capital_good": False}
        ).json()["is_capital_good"]
        is False
    )


def test_recording_a_payment_does_not_claim_the_extraction_was_reviewed(
    auth_client, sample_invoice_text
):
    """A payment is a ledger fact, not a reading off the document.

    Every PATCH set ``parsed_with`` to manual and confidence to 1.0, which is an
    assertion that a human checked what the extractor made of the invoice.
    Recording a payment asserts nothing of the kind — and it took the row off
    the needs-review list, so a document nobody had looked at stopped being
    flagged for it.
    """
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    before = auth_client.get(f"/api/v1/invoices/{invoice_id}").json()

    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"paid_at": "2026-05-01", "is_capital_good": True},
    ).json()

    assert body["paid_at"] == "2026-05-01"
    assert body["parsed_with"] == before["parsed_with"]
    assert body["extraction_confidence"] == before["extraction_confidence"]


def test_a_payment_does_not_promote_a_failed_invoice_into_the_filing_pool(
    auth_client, db_session
):
    """A ``failed`` row has fields that were never extracted.

    Promoting it to ``parsed`` on a payment puts those blanks into a return,
    and takes the row out of the error queue where someone was going to fix it.
    """
    invoice_id = upload(auth_client, "nothing readable here", name="blank.txt").json()[
        "invoice"
    ]["id"]
    invoice = db_session.get(Invoice, invoice_id)
    invoice.status = InvoiceStatus.FAILED
    invoice.invoice_date = date(2026, 4, 15)
    db_session.commit()

    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"paid_at": "2026-05-01"}
    ).json()

    assert body["status"] == InvoiceStatus.FAILED.value
    # A real correction still promotes it, which is what that rule is for.
    promoted = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"invoice_number": "FIXED-1"}
    ).json()
    assert promoted["status"] == InvoiceStatus.PARSED.value


def test_blocking_the_credit_does_not_promote_a_failed_invoice_into_the_filing_pool(
    auth_client, db_session
):
    """Whether the credit is blocked under s.17(5) is a decision about the
    purchase, not a reading off the document — nothing on a motor-car invoice
    says its credit is barred. Marking it so on a row whose figures were never
    extracted must not put those blanks into the credit pool, and marking it
    on a row nobody has reviewed must not say somebody did."""
    invoice_id = upload(auth_client, "nothing readable here", name="blank.txt").json()[
        "invoice"
    ]["id"]
    invoice = db_session.get(Invoice, invoice_id)
    invoice.status = InvoiceStatus.FAILED
    invoice.invoice_date = date(2026, 4, 15)
    db_session.commit()
    before = auth_client.get(f"/api/v1/invoices/{invoice_id}").json()

    body = auth_client.patch(
        f"/api/v1/invoices/{invoice_id}", json={"itc_eligible": False}
    ).json()

    assert body["itc_eligible"] is False
    assert body["status"] == InvoiceStatus.FAILED.value
    assert body["parsed_with"] == before["parsed_with"]
    assert body["extraction_confidence"] == before["extraction_confidence"]


class TestCorrectingAReconciledInvoice:
    """A reconciliation verdict is about the figures it compared.

    ``matched`` says this row agrees with the supplier's filing. Correct the
    tax on it and that is no longer known — the run that said so never saw
    the new figure — yet the row went on wearing the badge, and the list
    filtered by ``matched`` went on offering it as credit that was safe.
    """

    def reconciled(self, auth_client, db_session, sample_invoice_text):
        invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
        invoice = db_session.get(Invoice, invoice_id)
        invoice.status = InvoiceStatus.MATCHED
        db_session.commit()
        return invoice_id

    @pytest.mark.parametrize(
        "change",
        [
            {"igst": "1.00"},
            {"taxable_value": "1.00"},
            {"invoice_number": "OTHER-1"},
            {"invoice_date": "2026-03-02"},
        ],
    )
    def test_correcting_what_the_run_compared_withdraws_its_verdict(
        self, auth_client, db_session, sample_invoice_text, change
    ):
        invoice_id = self.reconciled(auth_client, db_session, sample_invoice_text)

        body = auth_client.patch(f"/api/v1/invoices/{invoice_id}", json=change).json()

        assert body["status"] == InvoiceStatus.PARSED.value

    def test_a_ledger_entry_leaves_the_verdict_standing(
        self, auth_client, db_session, sample_invoice_text
    ):
        """Paying the supplier changes nothing the 2B was compared against."""
        invoice_id = self.reconciled(auth_client, db_session, sample_invoice_text)

        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}",
            json={"paid_at": "2026-05-01", "is_capital_good": True, "itc_eligible": False},
        ).json()

        assert body["status"] == InvoiceStatus.MATCHED.value

    def test_a_field_the_run_never_reads_leaves_the_verdict_standing(
        self, auth_client, db_session, sample_invoice_text
    ):
        """An HSN code is a filing detail; the 2B carries none to compare."""
        invoice_id = self.reconciled(auth_client, db_session, sample_invoice_text)

        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"hsn_code": "8471"}
        ).json()

        assert body["status"] == InvoiceStatus.MATCHED.value


class TestCorrectingARowAWorkerAbandoned:
    """A ``processing`` invoice is the one nothing else can rescue.

    ``FAILED`` is an extraction that gave up and ``UPLOADED`` is one that has
    not started; a worker that dies mid-parse leaves ``PROCESSING``, and no
    extraction is ever coming back to move it. The row sits in
    ``UNREADABLE_STATUSES`` for ever, which means filing, the ITC pool and the
    tax summary all skip it.

    Typing the figures in is the obvious thing to do about a document stuck on
    a spinner, and it used to change nothing: the PATCH answered 200 and
    recorded ``manual`` with a confidence of 1.0, and the supply stayed out of
    the return — while ``/filing/validate`` went on telling the user to wait
    for an extraction to finish.
    """

    def abandoned(self, auth_client, db_session):
        invoice_id = upload(
            auth_client, "nothing readable here", name="blank.txt"
        ).json()["invoice"]["id"]
        invoice = db_session.get(Invoice, invoice_id)
        invoice.status = InvoiceStatus.PROCESSING
        invoice.invoice_type = InvoiceType.SALES
        db_session.commit()
        return invoice_id

    def test_a_correction_promotes_it_into_the_filing_pool(
        self, auth_client, db_session
    ):
        invoice_id = self.abandoned(auth_client, db_session)

        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}",
            json={
                "invoice_number": "S-STUCK",
                "invoice_date": "2026-04-15",
                "counterparty_gstin": SUPPLIER_GSTIN_OTHER_STATE,
                "place_of_supply": "29",
                "hsn_code": "8471",
                "tax_rate": "18",
                "taxable_value": "100000.00",
                "igst": "18000.00",
                "total_value": "118000.00",
            },
        ).json()

        assert body["status"] == InvoiceStatus.PARSED.value

    def test_the_supply_then_actually_reaches_the_return(
        self, auth_client, db_session
    ):
        """The half that was silently wrong: the status is what filing reads."""
        invoice_id = self.abandoned(auth_client, db_session)
        auth_client.patch(
            f"/api/v1/invoices/{invoice_id}",
            json={
                "invoice_number": "S-STUCK",
                "invoice_date": "2026-04-15",
                "counterparty_gstin": SUPPLIER_GSTIN_OTHER_STATE,
                "place_of_supply": "29",
                "hsn_code": "8471",
                "tax_rate": "18",
                "taxable_value": "100000.00",
                "igst": "18000.00",
                "total_value": "118000.00",
            },
        )

        document = auth_client.get("/api/v1/filing/gstr1?period=2026-04").json()

        assert document["document"]["b2b"][0]["inv"][0]["inum"] == "S-STUCK"
        # And validation stops advising a wait that would never end.
        assert not any(
            "being extracted" in issue["message"]
            for issue in document["validation"]["issues"]
        )

    def test_recording_a_payment_still_does_not_promote_it(
        self, auth_client, db_session
    ):
        """The ledger fields are not a correction, whatever the status is."""
        invoice_id = self.abandoned(auth_client, db_session)

        body = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"is_capital_good": True}
        ).json()

        assert body["status"] == InvoiceStatus.PROCESSING.value


def test_reparse_reruns_extraction(auth_client, sample_invoice_text):
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    response = auth_client.post(f"/api/v1/invoices/{invoice_id}/reparse")
    assert response.status_code == 200
    assert response.json()["invoice_number"] == "INV-2026-0042"


def test_reparse_rejects_processing_invoice(auth_client, db_session, sample_invoice_text):
    """A reparse while a worker is mid-parse would race on the same row."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    inv = db_session.get(Invoice, invoice_id)
    inv.status = InvoiceStatus.PROCESSING
    db_session.commit()

    response = auth_client.post(f"/api/v1/invoices/{invoice_id}/reparse")
    assert response.status_code == 409
    assert "currently being processed" in response.json()["detail"]


def test_delete_is_soft(auth_client, db_session, sample_invoice_text):
    """The row survives: a filing can be reopened during an assessment."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    assert auth_client.delete(f"/api/v1/invoices/{invoice_id}").status_code == 204
    assert auth_client.get(f"/api/v1/invoices/{invoice_id}").status_code == 404

    row = db_session.get(Invoice, invoice_id)
    assert row is not None
    assert row.deleted_at is not None


def test_get_returns_the_extraction_and_warnings(auth_client):
    invoice_id = upload(auth_client, "nothing useful", name="junk.txt").json()["invoice"]["id"]
    body = auth_client.get(f"/api/v1/invoices/{invoice_id}").json()
    assert body["warnings"]
    assert body["extraction"] is not None


def test_a_missing_invoice_is_404(auth_client):
    assert auth_client.get("/api/v1/invoices/999999").status_code == 404


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def test_the_uploaded_file_is_stored_under_the_tenant(auth_client, db_session, business):
    from pathlib import Path

    invoice_id = upload(auth_client, "Invoice No: F-1\nTotal Amount: 10.00",
                        name="f1.txt").json()["invoice"]["id"]
    invoice = db_session.get(Invoice, invoice_id)

    path = Path(invoice.storage_path)
    assert path.exists()
    # Namespaced by tenant, and the stored name is not attacker-controlled.
    assert path.parent.name == str(business.id)
    assert path.name != "f1.txt"


def test_period_and_date_survive_the_round_trip(auth_client, db_session, sample_invoice_text):
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice.invoice_date == date(2026, 4, 15)
    assert invoice.period == "2026-04"
    assert invoice.total_tax == Decimal("81000.00")


class TestTheDateThatDecidesWhichReturnAnInvoiceIsIn:
    """`invoice_date` is not one field among several: the filing period is
    derived from it, so a slipped year does not put a wrong number on a return
    — it takes the invoice out of every return there is.

    And nothing downstream can notice, because every check there is scoped to
    a period and the invoice is no longer in one. A sale corrected to 2099 left
    April's GSTR-1 empty and its validation reporting `ok: true`,
    `invoice_count: 0`, no issues — under-declared output tax, arrived at in
    silence, on the screen whose job is to say whether a return is safe to file.
    """

    @pytest.fixture()
    def sale_id(self, auth_client, sample_invoice_text) -> int:
        return upload(auth_client, sample_invoice_text, invoice_type="sales").json()[
            "invoice"
        ]["id"]

    def test_a_date_after_today_is_refused(self, auth_client, sale_id):
        future = (gst_calendar.today_ist() + timedelta(days=1)).isoformat()
        response = auth_client.patch(
            f"/api/v1/invoices/{sale_id}", json={"invoice_date": future}
        )
        assert response.status_code == 422, response.text
        assert future in response.text

    def test_a_slipped_century_is_refused(self, auth_client, sale_id):
        response = auth_client.patch(
            f"/api/v1/invoices/{sale_id}", json={"invoice_date": "2099-01-15"}
        )
        assert response.status_code == 422, response.text

    def test_a_date_before_gst_existed_is_refused(self, auth_client, sale_id):
        """There was no GSTIN to put on an invoice and no return to file it in."""
        response = auth_client.patch(
            f"/api/v1/invoices/{sale_id}", json={"invoice_date": "2016-04-15"}
        )
        assert response.status_code == 422, response.text
        assert "2017-07-01" in response.text

    def test_the_invoice_stays_in_the_return_it_was_in(self, auth_client, sale_id):
        """The point of the refusal: the sale does not leave April."""
        auth_client.patch(f"/api/v1/invoices/{sale_id}", json={"invoice_date": "2099-01-15"})

        assert auth_client.get(f"/api/v1/invoices/{sale_id}").json()["period"] == "2026-04"
        assert auth_client.get("/api/v1/filing/validate?period=2026-04").json()[
            "invoice_count"
        ] == 1

    def test_the_return_still_carries_the_sale(self, auth_client, sale_id):
        auth_client.patch(f"/api/v1/invoices/{sale_id}", json={"invoice_date": "2099-01-15"})

        document = auth_client.get("/api/v1/filing/gstr1?period=2026-04").json()
        assert "b2b" in str(document)

    def test_the_day_gst_commenced_is_itself_allowed(self, auth_client, sale_id):
        response = auth_client.patch(
            f"/api/v1/invoices/{sale_id}", json={"invoice_date": "2017-07-01"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["period"] == "2017-07"

    def test_today_is_allowed(self, auth_client, sale_id):
        today = gst_calendar.today_ist()
        response = auth_client.patch(
            f"/api/v1/invoices/{sale_id}", json={"invoice_date": today.isoformat()}
        )
        assert response.status_code == 200, response.text
        assert response.json()["period"] == today.strftime("%Y-%m")

    def test_an_ordinary_correction_still_goes_through(self, auth_client, sale_id):
        body = auth_client.patch(
            f"/api/v1/invoices/{sale_id}", json={"invoice_date": "2026-03-31"}
        ).json()
        assert body["period"] == "2026-03"

    def test_the_date_can_still_be_cleared(self, auth_client, sale_id):
        body = auth_client.patch(
            f"/api/v1/invoices/{sale_id}", json={"invoice_date": None}
        ).json()
        assert body["invoice_date"] is None


# --------------------------------------------------------------------------
# Corrections that would collide with an invoice already on file
# --------------------------------------------------------------------------

class TestACorrectionOntoAnotherInvoicesKey:
    """A PATCH can walk an invoice onto another one's natural key.

    `(business, type, counterparty, number)` is unique, and two ordinary
    corrections reach it: retyping the document number, and fixing a
    counterparty GSTIN onto a supplier who already has an invoice by that
    number. Both are what a reviewer is *for*.

    The database refused them, but nothing caught the refusal. It surfaced from
    a flush inside `get_or_create_supplier` — which is looking for a *supplier*
    conflict and had no idea the pending invoice edit had been swept into its
    SAVEPOINT — whose handler then re-queried a session whose transaction was
    already dead. The reviewer got a 500 and a correlation id for a conflict
    the upload path has always reported as a 409 naming the other invoice.
    """

    @staticmethod
    def _invoice(db, business, *, number: str, gstin: str) -> Invoice:
        row = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            status=InvoiceStatus.PARSED,
            period="2026-04",
            invoice_number=number,
            counterparty_gstin=gstin,
            taxable_value=Decimal("1000.00"),
            total_value=Decimal("1180.00"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def test_renumbering_onto_an_existing_invoice_is_a_conflict(
        self, auth_client, db_session, business
    ):
        self._invoice(db_session, business, number="INV-A", gstin=SUPPLIER_GSTIN_SAME_STATE)
        target = self._invoice(
            db_session, business, number="INV-B", gstin=SUPPLIER_GSTIN_SAME_STATE
        )

        response = auth_client.patch(
            f"/api/v1/invoices/{target.id}", json={"invoice_number": "INV-A"}
        )
        assert response.status_code == 409, response.text

    def test_the_conflict_names_the_invoice_already_holding_the_number(
        self, auth_client, db_session, business
    ):
        # Without the id there is nothing for the reviewer to go and look at,
        # which is the whole difference between this and the 500 it replaced.
        existing = self._invoice(
            db_session, business, number="INV-A", gstin=SUPPLIER_GSTIN_SAME_STATE
        )
        target = self._invoice(
            db_session, business, number="INV-B", gstin=SUPPLIER_GSTIN_SAME_STATE
        )

        response = auth_client.patch(
            f"/api/v1/invoices/{target.id}", json={"invoice_number": "INV-A"}
        )
        assert response.json()["detail"]["invoice_id"] == existing.id

    def test_correcting_the_counterparty_onto_a_collision_is_a_conflict(
        self, auth_client, db_session, business
    ):
        self._invoice(db_session, business, number="INV-SAME", gstin=SUPPLIER_GSTIN_SAME_STATE)
        target = self._invoice(
            db_session, business, number="INV-SAME", gstin=SUPPLIER_GSTIN_OTHER_STATE
        )

        response = auth_client.patch(
            f"/api/v1/invoices/{target.id}",
            json={"counterparty_gstin": SUPPLIER_GSTIN_SAME_STATE},
        )
        assert response.status_code == 409, response.text

    def test_the_refused_correction_leaves_both_invoices_alone(
        self, auth_client, db_session, business
    ):
        # A refusal that had already written half of itself would be worse than
        # the 500: the check runs before anything is set.
        self._invoice(db_session, business, number="INV-A", gstin=SUPPLIER_GSTIN_SAME_STATE)
        target = self._invoice(
            db_session, business, number="INV-B", gstin=SUPPLIER_GSTIN_SAME_STATE
        )

        auth_client.patch(f"/api/v1/invoices/{target.id}", json={"invoice_number": "INV-A"})

        db_session.expire_all()
        assert db_session.get(Invoice, target.id).invoice_number == "INV-B"

    def test_the_session_survives_the_refusal(self, auth_client, db_session, business):
        # The old failure poisoned the request's transaction, so this is the
        # assertion that the 409 is a real refusal and not a dressed-up crash:
        # the API still works afterwards.
        self._invoice(db_session, business, number="INV-A", gstin=SUPPLIER_GSTIN_SAME_STATE)
        target = self._invoice(
            db_session, business, number="INV-B", gstin=SUPPLIER_GSTIN_SAME_STATE
        )

        auth_client.patch(f"/api/v1/invoices/{target.id}", json={"invoice_number": "INV-A"})

        assert auth_client.get("/api/v1/invoices").status_code == 200

    def test_renumbering_to_a_free_number_still_works(
        self, auth_client, db_session, business
    ):
        target = self._invoice(
            db_session, business, number="INV-B", gstin=SUPPLIER_GSTIN_SAME_STATE
        )

        response = auth_client.patch(
            f"/api/v1/invoices/{target.id}", json={"invoice_number": "INV-C"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["invoice_number"] == "INV-C"

    def test_patching_an_invoice_to_the_number_it_already_has_is_not_a_conflict(
        self, auth_client, db_session, business
    ):
        # The row it collides with is itself. A no-op correction is a no-op.
        target = self._invoice(
            db_session, business, number="INV-B", gstin=SUPPLIER_GSTIN_SAME_STATE
        )

        response = auth_client.patch(
            f"/api/v1/invoices/{target.id}", json={"invoice_number": "INV-B"}
        )
        assert response.status_code == 200, response.text

    def test_a_sale_may_reuse_a_purchases_number(self, auth_client, db_session, business):
        # The key includes the type, so a sales invoice numbered like a
        # purchase from the same GSTIN is not a collision.
        self._invoice(db_session, business, number="INV-A", gstin=SUPPLIER_GSTIN_SAME_STATE)
        sale = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.SALES,
            status=InvoiceStatus.PARSED,
            period="2026-04",
            invoice_number="INV-Z",
            counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
            taxable_value=Decimal("1000.00"),
            total_value=Decimal("1180.00"),
        )
        db_session.add(sale)
        db_session.commit()
        db_session.refresh(sale)

        response = auth_client.patch(
            f"/api/v1/invoices/{sale.id}", json={"invoice_number": "INV-A"}
        )
        assert response.status_code == 200, response.text


class TestTheSupplierSavepointHoldsOnlyTheSupplier:
    """`get_or_create_supplier` inserts inside a SAVEPOINT so a lost race costs
    that statement alone. A bare `db.flush()` broke that promise: it writes out
    *everything* the session has pending, so a caller part-way through an edit
    of its own had that edit dragged into the SAVEPOINT and judged by a handler
    written for supplier conflicts.

    The invoice PATCH route is exactly such a caller — it sets its fields, then
    reaches this function to link the supplier — and when the database refused
    the caller's change, `except IntegrityError` read it as a lost race,
    re-queried a session whose transaction was already dead, and raised
    `PendingRollbackError` from a function whose whole purpose is to leave the
    session usable.
    """

    @staticmethod
    def _invoice(db, business, *, number: str) -> Invoice:
        row = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            status=InvoiceStatus.PARSED,
            period="2026-04",
            invoice_number=number,
            counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
            taxable_value=Decimal("1000.00"),
            total_value=Decimal("1180.00"),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @pytest.fixture()
    def pending_conflict(self, db_session, business):
        """A dirty invoice whose pending change the database will refuse."""
        self._invoice(db_session, business, number="INV-A")
        target = self._invoice(db_session, business, number="INV-B")
        target.invoice_number = "INV-A"
        return target

    def test_a_new_supplier_is_still_created(self, db_session, business, pending_conflict):
        supplier = invoice_service.get_or_create_supplier(
            db_session, business.id, SUPPLIER_GSTIN_OTHER_STATE
        )
        assert supplier.gstin == SUPPLIER_GSTIN_OTHER_STATE

    def test_the_caller_s_pending_change_is_not_written_by_this_function(
        self, db_session, business, pending_conflict
    ):
        # It is the caller's to commit or discard. Writing it here is what put
        # it inside the SAVEPOINT in the first place.
        invoice_service.get_or_create_supplier(
            db_session, business.id, SUPPLIER_GSTIN_OTHER_STATE
        )
        assert pending_conflict in db_session.dirty

    def test_the_session_is_left_usable(self, db_session, business, pending_conflict):
        # The failure mode this replaces: PendingRollbackError on the next
        # statement, whatever it was.
        invoice_service.get_or_create_supplier(
            db_session, business.id, SUPPLIER_GSTIN_OTHER_STATE
        )
        assert db_session.query(Supplier).count() >= 1

    def test_an_existing_supplier_is_returned_without_touching_the_flush(
        self, db_session, business, pending_conflict
    ):
        first = invoice_service.get_or_create_supplier(
            db_session, business.id, SUPPLIER_GSTIN_OTHER_STATE
        )
        again = invoice_service.get_or_create_supplier(
            db_session, business.id, SUPPLIER_GSTIN_OTHER_STATE
        )
        assert again.id == first.id

    def test_a_conflict_that_is_not_a_lost_race_is_not_swallowed_as_one(
        self, db_session, business
    ):
        """A soft-deleted supplier still holds the GSTIN.

        ``uq_suppliers_business_gstin`` is a plain unique constraint, not one
        predicated on ``deleted_at IS NULL`` the way the invoice and return
        keys are — so a tombstone keeps the key occupied, while
        ``_find_supplier`` filters tombstones out and reports the GSTIN as
        free. Look, insert, conflict, look again, still nothing.

        That shape is indistinguishable from a lost race at the ``except``, and
        the difference is everything: a lost race means the row is there and
        the caller can have it, this means the row is *not* there and never
        will be until someone restores it. Returning ``None`` here would put
        the ``AttributeError`` two lines down instead, on a function documented
        never to hand back nothing; swallowing it would attach the invoice to
        no supplier at all. It has to surface.
        """
        tombstone = Supplier(
            business_id=business.id,
            gstin=SUPPLIER_GSTIN_OTHER_STATE,
            legal_name="Deleted Supplier Pvt Ltd",
        )
        db_session.add(tombstone)
        db_session.commit()
        tombstone.soft_delete()
        db_session.commit()

        with pytest.raises(IntegrityError):
            invoice_service.get_or_create_supplier(
                db_session, business.id, SUPPLIER_GSTIN_OTHER_STATE
            )

    def test_the_session_survives_that_conflict_for_the_caller_to_roll_back(
        self, db_session, business
    ):
        # The SAVEPOINT rolled back before the raise, so the error reaches the
        # caller as a failed statement rather than as a dead transaction the
        # request handler cannot even log against.
        supplier = Supplier(
            business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE, legal_name="X"
        )
        db_session.add(supplier)
        db_session.commit()
        supplier.soft_delete()
        db_session.commit()

        with pytest.raises(IntegrityError):
            invoice_service.get_or_create_supplier(
                db_session, business.id, SUPPLIER_GSTIN_OTHER_STATE
            )

        db_session.rollback()
        assert db_session.query(Supplier).count() == 1


class TestCorrectionBoundaries:
    """InvoiceUpdate checked only lengths on three fields GSTR-1 exports."""

    def test_an_extreme_rate_is_quoted_in_the_form_it_was_sent(self):
        # Positionally, 1E-999999 is a million characters of refusal.
        from pydantic import ValidationError

        from app.schemas.invoice import InvoiceUpdate

        with pytest.raises(ValidationError, match=r"1E-999999% is not a GST rate"):
            InvoiceUpdate(tax_rate="1E-999999")

    @pytest.mark.parametrize("rate", ["17", "12.5", "100", "0.18"])
    def test_a_rate_that_is_not_a_gst_slab_is_refused(self, rate):
        from pydantic import ValidationError

        from app.schemas.invoice import InvoiceUpdate

        with pytest.raises(ValidationError, match="is not a GST rate"):
            InvoiceUpdate(tax_rate=rate)

    @pytest.mark.parametrize("rate", ["0", "0.1", "1.5", "18", "18.00", "40"])
    def test_every_slab_is_accepted(self, rate):
        from app.schemas.invoice import InvoiceUpdate

        assert InvoiceUpdate(tax_rate=rate).tax_rate == Decimal(rate)

    @pytest.mark.parametrize("hsn", ["abcd", "N/A", "123", "123456789", "84７1"])
    def test_an_hsn_that_is_not_4_to_8_digits_is_refused(self, hsn):
        from pydantic import ValidationError

        from app.schemas.invoice import InvoiceUpdate

        with pytest.raises(ValidationError, match="4 to 8 digits"):
            InvoiceUpdate(hsn_code=hsn)

    def test_an_hsn_is_read_as_its_digits_and_blank_clears_it(self):
        from app.schemas.invoice import InvoiceUpdate

        assert InvoiceUpdate(hsn_code="8471.30").hsn_code == "847130"
        assert InvoiceUpdate(hsn_code="8471.30.10").hsn_code == "84713010"
        assert InvoiceUpdate(hsn_code=" 9983 ").hsn_code == "9983"
        assert InvoiceUpdate(hsn_code="  ").hsn_code is None

    def test_an_invoice_number_is_trimmed_and_an_all_space_one_cleared(self):
        from app.schemas.invoice import InvoiceUpdate

        assert InvoiceUpdate(invoice_number=" INV-1 ").invoice_number == "INV-1"
        assert InvoiceUpdate(invoice_number="   ").invoice_number is None


class TestTheAuditTrailOfAnInvoice:
    """The access line says who touched which invoice; these say what."""

    def test_an_edit_names_the_fields_it_touched_but_not_their_values(
        self, auth_client, sample_invoice_text, caplog
    ):
        import logging

        invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
        with caplog.at_level(logging.INFO, logger="app.routers.invoices"):
            auth_client.patch(
                f"/api/v1/invoices/{invoice_id}",
                json={"taxable_value": "450000.00", "paid_at": "2026-05-01"},
            )

        [line] = [r for r in caplog.records if r.getMessage() == "Invoice edited"]
        assert line.invoice_id == invoice_id
        assert line.corrected_fields == ["taxable_value"]
        assert line.ledger_fields == ["paid_at"]
        assert "450000" not in str(vars(line))

    def test_each_invoice_a_batch_stores_is_named(self, auth_client, caplog):
        import logging

        files = [
            ("files", (f"bill{n}.txt", f"Invoice No: B-{n}\nTotal: 1180".encode(), "text/plain"))
            for n in range(2)
        ]
        with caplog.at_level(logging.INFO, logger="app.services.invoice_service"):
            response = auth_client.post("/api/v1/invoices/bulk", files=files)
        assert response.status_code == 200

        stored = [r for r in caplog.records if r.getMessage() == "Invoice stored"]
        created = [item["invoice"]["id"] for item in response.json()["items"] if item["accepted"]]
        assert sorted(r.invoice_id for r in stored) == sorted(created)
        assert all(r.source == "upload" for r in stored)


def test_blanking_an_amount_is_refused_in_words_the_form_can_show(
    auth_client, sample_invoice_text
):
    """The form prefixes the field's label; the message must not repeat it as
    a snake_case name, and must say what to enter instead."""
    invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

    response = auth_client.patch(f"/api/v1/invoices/{invoice_id}", json={"taxable_value": None})

    assert response.status_code == 422
    [field] = response.json()["error"]["fields"]
    assert "taxable_value" not in field["message"]
    assert "Enter 0" in field["message"]


class TestBoundaryInputsReachTheDatabaseInAFormItAccepts:
    """SQLite stores a NUL character happily and PostgreSQL refuses it outright,
    in text columns and inside JSON — so on the database production runs, each
    of these was a failed write, and on the suite's database nothing showed."""

    def test_an_edited_name_and_number_are_stored_without_nul_or_bidi_overrides(
        self, auth_client, sample_invoice_text, db_session
    ):
        invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]

        response = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}",
            json={"counterparty_name": "Acme\x00 ‮Traders", "invoice_number": " INV\x00-7 "},
        )

        assert response.status_code == 200
        row = db_session.get(Invoice, invoice_id)
        db_session.refresh(row)
        assert row.counterparty_name == "Acme Traders"
        assert row.invoice_number == "INV-7"

    def test_text_read_out_of_a_document_is_stored_without_nul(
        self, auth_client, sample_invoice_text, db_session
    ):
        # pypdf emits NUL for glyphs it cannot map; a text upload carries it
        # through the same parse-and-store path.
        text = sample_invoice_text.replace("Invoice", "Inv\x00oice", 1) + "\nNote: a\x00b\n"
        invoice_id = upload(auth_client, text).json()["invoice"]["id"]

        row = db_session.get(Invoice, invoice_id)
        assert row.raw_text and "\x00" not in row.raw_text
        assert "\x00" not in json.dumps(row.extraction or {})
        assert "\x00" not in json.dumps(row.line_items or [])
        assert "\x00" not in (row.counterparty_name or "")

    def test_an_untyped_file_is_judged_by_its_extension(self, auth_client):
        """application/octet-stream is what a browser sends when it cannot
        type a file. It used to be an accepted type on its own, so a .exe sent
        untyped was stored as an invoice."""
        refused = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("bill.exe", b"MZ\x90\x00", "application/octet-stream")},
            data={"invoice_type": "purchase"},
        )
        assert refused.status_code == 415

        accepted = auth_client.post(
            "/api/v1/invoices/upload",
            files={
                "file": ("bill.txt", b"Invoice No: OCT-1\nTotal: 1180", "application/octet-stream")
            },
            data={"invoice_type": "purchase"},
        )
        assert accepted.status_code == 201

    @pytest.mark.parametrize("value", ["1.234", "1.005", "0.001"])
    def test_an_amount_finer_than_paise_is_refused_rather_than_rounded(
        self, auth_client, sample_invoice_text, value
    ):
        invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
        response = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"taxable_value": value}
        )
        assert response.status_code == 422

    @pytest.mark.parametrize("value", ["1.23", "1.230", "0", "999999999.99"])
    def test_an_amount_in_rupees_and_paise_is_accepted(
        self, auth_client, sample_invoice_text, value
    ):
        invoice_id = upload(auth_client, sample_invoice_text).json()["invoice"]["id"]
        response = auth_client.patch(
            f"/api/v1/invoices/{invoice_id}", json={"taxable_value": value}
        )
        assert response.status_code == 200


def test_a_spreadsheet_that_breaks_partway_fails_with_a_reason_a_person_can_use(auth_client):
    """M6: a sheet that opened and then failed mid-read escaped text extraction,
    and the row's ``parse_error`` became the exception text — "list index out
    of range" — instead of the parser's own account of an unreadable file."""
    from tests.test_document_text import _corrupt_sheet_xlsx

    response = auth_client.post(
        "/api/v1/invoices/upload",
        files={
            "file": (
                "register.xlsx",
                _corrupt_sheet_xlsx(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"invoice_type": "purchase"},
    )
    assert response.status_code in (200, 201, 202), response.text
    invoice = response.json()["invoice"]
    assert "index out of range" not in (invoice["parse_error"] or "")
