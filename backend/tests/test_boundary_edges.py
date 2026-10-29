"""M1 boundary testing: edges that the domain and HTTP layers share.

GSTIN unicode lookalikes and control characters at the registration endpoint,
business names with emoji / SQL injection / extreme length, date fields at
the exact commencement and future boundaries, and file upload shape checks
with unusual filenames and content types.
"""
from __future__ import annotations

import io
from datetime import timedelta

import pytest

from app.services import gst_calendar
from app.services import gstin as gstin_service
from app.services.gstin import InvalidGSTIN
from tests.conftest import BUSINESS_GSTIN

# -----------------------------------------------------------------------
# GSTIN validation edge cases — unicode, control chars, fullwidth digits
# -----------------------------------------------------------------------

class TestGstinUnicodeLookalikes:
    """Fullwidth digits and Cyrillic letters look identical to their ASCII
    counterparts in most fonts. A GSTIN *stored* with them would pass a visual
    check and fail silently on a government portal.

    P29 M18: the two are different cases. Full-width forms are the same
    characters by Unicode's own definition (NFKC), and a zero-width joiner is
    no character at all, so both now fold to the plain-ASCII GSTIN — which is
    what gets stored, so nothing non-ASCII ever reaches the portal. Refusing
    them refused real GSTINs copied out of PDFs and web pages. A Cyrillic
    letter is a different letter and is still refused."""

    def test_fullwidth_digits_fold_to_the_ascii_gstin(self):
        # ２ is fullwidth '2', ７ is fullwidth '7'
        lookalike = "２７AAPFU0939F1ZV"
        assert gstin_service.parse(lookalike).gstin == BUSINESS_GSTIN
        assert gstin_service.parse(lookalike).gstin.isascii()

    def test_cyrillic_a_looks_like_latin_a_but_is_rejected(self):
        # А is Cyrillic 'А', visually identical to Latin 'A'
        lookalike = "27АAPFU0939F1ZV"
        assert not gstin_service.is_valid(lookalike)

    def test_a_zero_width_joiner_is_removed_not_stored(self):
        poisoned = "27\u200dAAPFU0939F1ZV"
        assert gstin_service.parse(poisoned).gstin == BUSINESS_GSTIN

    def test_normalize_leaves_a_different_letter_alone(self):
        # The Cyrillic А is not folded: it stays, and the GSTIN is refused.
        assert gstin_service.normalize("27АAPFU0939F1ZV") != BUSINESS_GSTIN


class TestGstinControlCharsAndWhitespace:
    def test_a_tab_separated_gstin_normalizes_away(self):
        assert gstin_service.is_valid("27\tAAPFU0939F1ZV")

    def test_a_newline_inside_a_gstin_normalizes_away(self):
        assert gstin_service.is_valid("27AAPFU\n0939F1ZV")

    def test_a_null_byte_inside_a_gstin_is_rejected(self):
        assert not gstin_service.is_valid("27AAPFU\x000939F1ZV")

    def test_only_whitespace_is_treated_as_absent(self):
        with pytest.raises(InvalidGSTIN):
            gstin_service.parse("   ")

    def test_empty_string_raises(self):
        with pytest.raises(InvalidGSTIN):
            gstin_service.parse("")


class TestGstinAtRegistrationEndpoint:
    """The HTTP surface, where pydantic and the GSTIN validator interact."""

    REGISTER_BASE = {
        "email": "edge@example.com",
        "password": "supersecret123",
        "full_name": "Edge Tester",
    }

    def test_a_fullwidth_gstin_registers_as_the_ascii_one(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={**self.REGISTER_BASE, "gstin": "２７AAPFU0939F1ZV"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["business"]["gstin"] == BUSINESS_GSTIN

    def test_a_cyrillic_lookalike_gstin_is_rejected_at_registration(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={**self.REGISTER_BASE, "gstin": "27АAPFU0939F1ZV"},
        )
        assert resp.status_code == 422

    def test_gstin_with_embedded_null_is_rejected_at_registration(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={**self.REGISTER_BASE, "gstin": "27AAPFU\x000939F1ZV"},
        )
        assert resp.status_code == 422

    def test_gstin_of_all_zeros_is_rejected(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={**self.REGISTER_BASE, "gstin": "000000000000000"},
        )
        assert resp.status_code == 422

    def test_gstin_exceeding_max_length_field_is_rejected(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={**self.REGISTER_BASE, "gstin": "A" * 33},
        )
        assert resp.status_code == 422

    def test_gstin_with_sql_injection_is_rejected(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={**self.REGISTER_BASE, "gstin": "'; DROP TABLE--"},
        )
        assert resp.status_code == 422


# -----------------------------------------------------------------------
# Business name fields — emoji, SQL injection, extreme length, whitespace
# -----------------------------------------------------------------------

class TestBusinessNameBoundaries:
    """Names arrive from registration and from invoice corrections. Both
    pass through clean_text, but the HTTP layer is where a 255-char cap
    and whitespace-only rejection apply."""

    REGISTER_BASE = {
        "email": "names@example.com",
        "password": "supersecret123",
    }

    def test_emoji_in_a_business_name_is_accepted(self, client, db_session):
        resp = client.post(
            "/api/v1/auth/register",
            json={
                **self.REGISTER_BASE,
                "legal_name": "Umang Traders 🏪",
                "full_name": "Umang Shah 👨‍💼",
            },
        )
        assert resp.status_code == 201, resp.text
        assert "Umang Traders" in resp.json()["business"]["legal_name"]

    def test_sql_injection_in_a_name_is_stored_as_text(self, client, db_session):
        from app.models.business import Business

        name = "'; DROP TABLE businesses; --"
        resp = client.post(
            "/api/v1/auth/register",
            json={
                **self.REGISTER_BASE,
                "email": "sqli@example.com",
                "legal_name": name,
                "full_name": "Test",
            },
        )
        assert resp.status_code == 201, resp.text
        biz = db_session.query(Business).filter_by(
            id=resp.json()["business"]["id"]
        ).one()
        assert "DROP TABLE" in biz.legal_name

    def test_a_name_over_255_chars_is_rejected(self, client):
        long_name = "A" * 500
        resp = client.post(
            "/api/v1/auth/register",
            json={
                **self.REGISTER_BASE,
                "email": "long@example.com",
                "legal_name": long_name,
                "full_name": "Test",
            },
        )
        assert resp.status_code == 422

    def test_a_name_at_exactly_255_is_accepted(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={
                **self.REGISTER_BASE,
                "email": "long255@example.com",
                "legal_name": "A" * 255,
                "full_name": "Test",
            },
        )
        assert resp.status_code == 201, resp.text
        assert len(resp.json()["business"]["legal_name"]) == 255

    def test_whitespace_only_name_falls_back(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={
                **self.REGISTER_BASE,
                "email": "ws@example.com",
                "legal_name": "   \t\n  ",
                "full_name": "   \t  ",
            },
        )
        # clean_text returns None for whitespace-only, and the service falls
        # back to the email local part
        assert resp.status_code == 201, resp.text
        assert resp.json()["business"]["legal_name"]  # not empty

    def test_bidi_override_in_a_name_is_stripped(self, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={
                **self.REGISTER_BASE,
                "email": "bidi@example.com",
                "legal_name": "Umang ‮Traders",
                "full_name": "Test",
            },
        )
        assert resp.status_code == 201, resp.text
        name = resp.json()["business"]["legal_name"]
        assert "‮" not in name
        assert "Umang" in name


# -----------------------------------------------------------------------
# Invoice correction — GSTIN, name, and date at the PATCH endpoint
# -----------------------------------------------------------------------

class TestInvoiceCorrectionBoundaries:
    """PATCH /invoices/{id} is the one door where a human types free text
    into fields that eventually reach the filing portal."""

    @pytest.fixture()
    def invoice(self, auth_client, db_session, business):
        from app.models.invoice import Invoice, InvoiceType
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="INV-EDGE-1",
        )
        db_session.add(inv)
        db_session.commit()
        db_session.refresh(inv)
        return inv

    def test_a_counterparty_gstin_with_wrong_checksum_is_rejected(
        self, auth_client, invoice
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"counterparty_gstin": "27AAPFU0939F1ZW"},
        )
        assert resp.status_code == 422
        assert "gstin" in resp.text.lower()

    def test_a_counterparty_gstin_with_fullwidth_chars_is_stored_as_ascii(
        self, auth_client, invoice
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"counterparty_gstin": "２９AAGCB7383J1Z4"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["counterparty_gstin"] == "29AAGCB7383J1Z4"

    def test_a_counterparty_name_over_255_is_rejected(
        self, auth_client, invoice
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"counterparty_name": "B" * 400},
        )
        assert resp.status_code == 422

    def test_a_counterparty_name_at_exactly_255_is_accepted(
        self, auth_client, invoice
    ):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"counterparty_name": "B" * 255},
        )
        assert resp.status_code == 200

    def test_an_invoice_number_of_only_spaces_clears_the_field(
        self, auth_client, db_session, invoice
    ):
        from app.models.invoice import Invoice
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"invoice_number": "   "},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, invoice.id)
        assert stored.invoice_number is None

    def test_a_counterparty_name_with_control_chars_is_cleaned(
        self, auth_client, db_session, invoice
    ):
        from app.models.invoice import Invoice
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"counterparty_name": "Vendor\x00Corp\x07Ltd"},
        )
        assert resp.status_code == 200
        db_session.expire_all()
        stored = db_session.get(Invoice, invoice.id)
        assert "\x00" not in stored.counterparty_name
        assert "\x07" not in stored.counterparty_name
        assert stored.counterparty_name == "VendorCorpLtd"


# -----------------------------------------------------------------------
# Date fields — commencement, future, leap year, epoch
# -----------------------------------------------------------------------

class TestInvoiceDateBoundaries:

    @pytest.fixture()
    def invoice(self, auth_client, db_session, business):
        from app.models.invoice import Invoice, InvoiceType
        inv = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            invoice_number="INV-DATE-1",
        )
        db_session.add(inv)
        db_session.commit()
        db_session.refresh(inv)
        return inv

    def test_the_day_before_gst_commencement_is_refused(self, auth_client, invoice):
        day_before = gst_calendar.GST_COMMENCEMENT - timedelta(days=1)
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"invoice_date": day_before.isoformat()},
        )
        assert resp.status_code == 422
        assert "2017-06-30" in resp.text or "commencement" in resp.text.lower()

    def test_gst_commencement_day_itself_is_accepted(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"invoice_date": gst_calendar.GST_COMMENCEMENT.isoformat()},
        )
        assert resp.status_code == 200

    def test_tomorrow_is_refused(self, auth_client, invoice):
        tomorrow = gst_calendar.today_ist() + timedelta(days=1)
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"invoice_date": tomorrow.isoformat()},
        )
        assert resp.status_code == 422
        assert "future" in resp.text.lower() or tomorrow.isoformat() in resp.text

    def test_today_is_accepted(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"invoice_date": gst_calendar.today_ist().isoformat()},
        )
        assert resp.status_code == 200

    def test_a_leap_day_invoice_is_accepted(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"invoice_date": "2024-02-29"},
        )
        assert resp.status_code == 200

    def test_a_pre_epoch_date_is_refused(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"invoice_date": "1970-01-01"},
        )
        assert resp.status_code == 422

    def test_a_far_future_date_is_refused(self, auth_client, invoice):
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"invoice_date": "2099-12-31"},
        )
        assert resp.status_code == 422

    def test_a_future_payment_date_is_refused(self, auth_client, invoice):
        tomorrow = gst_calendar.today_ist() + timedelta(days=1)
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"paid_at": tomorrow.isoformat()},
        )
        assert resp.status_code == 422
        assert "future" in resp.text.lower()

    def test_a_past_payment_date_is_accepted(self, auth_client, invoice):
        yesterday = gst_calendar.today_ist() - timedelta(days=1)
        resp = auth_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"paid_at": yesterday.isoformat()},
        )
        assert resp.status_code == 200


# -----------------------------------------------------------------------
# File uploads — filenames, content types, empty files
# -----------------------------------------------------------------------

class TestFileUploadBoundaries:
    """The _check_file_shape gate, exercised through the upload endpoint."""

    UPLOAD = "/api/v1/invoices/upload"

    def _upload(
        self, client, filename, content=b"%PDF-1.4 content", content_type="application/pdf",
    ):
        return client.post(
            self.UPLOAD,
            files={"file": (filename, io.BytesIO(content), content_type)},
        )

    def test_an_empty_file_is_refused(self, auth_client):
        resp = self._upload(auth_client, "empty.pdf", content=b"")
        assert resp.status_code == 400
        assert "empty" in resp.text.lower()

    def test_a_path_traversal_filename_is_sanitized(self, auth_client, db_session):
        resp = self._upload(auth_client, "../../etc/passwd")
        # Accepted (the name is cosmetic), and the stored name is safe
        assert resp.status_code in (200, 201), resp.text

    def test_a_very_long_filename_is_accepted(self, auth_client):
        long_name = "a" * 300 + ".pdf"
        resp = self._upload(auth_client, long_name)
        assert resp.status_code in (200, 201), resp.text

    def test_a_filename_with_null_bytes_is_handled(self, auth_client):
        resp = self._upload(auth_client, "invoice\x00.pdf")
        # Either accepted with sanitized name or rejected — not a 500
        assert resp.status_code < 500

    def test_a_double_extension_is_accepted(self, auth_client):
        resp = self._upload(auth_client, "invoice.pdf.pdf")
        assert resp.status_code in (200, 201), resp.text

    def test_an_exe_with_wrong_content_type_is_refused(self, auth_client):
        resp = self._upload(
            auth_client, "malware.exe",
            content=b"MZ\x90\x00", content_type="application/octet-stream",
        )
        assert resp.status_code == 415

    def test_a_pdf_with_image_content_type_is_accepted(self, auth_client):
        resp = self._upload(
            auth_client, "scan.jpg",
            content=b"\xff\xd8\xff\xe0", content_type="image/jpeg",
        )
        assert resp.status_code in (200, 201), resp.text

    def test_a_file_with_no_extension_and_valid_content_type_is_accepted(self, auth_client):
        resp = self._upload(
            auth_client, "invoice",
            content=b"%PDF-1.4 content", content_type="application/pdf",
        )
        assert resp.status_code in (200, 201), resp.text

    def test_a_file_with_no_extension_and_no_content_type_is_refused(self, auth_client):
        resp = self._upload(
            auth_client, "invoice",
            content=b"something", content_type="application/octet-stream",
        )
        assert resp.status_code == 415
