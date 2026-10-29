"""The product, driven the way a business drives it, over HTTP only.

Every other file in this suite tests one layer. This one tests the seams
between them, which is where the bugs that reach users actually live: an
invoice whose extracted period does not match the period the 2B import
derived, a reconciliation run whose ITC figure the summary endpoint recomputes
differently, an export that disagrees with the preview the user just approved.
Each of those passes every unit test on both sides of the seam.

So nothing here reaches into the database or calls a service directly. A
journey is a sequence of requests, each one using an id or a period that came
out of the previous response, and the assertions are on the handoffs rather
than on arithmetic that ``test_reconciliation.py`` and ``test_itc.py`` already
own.

The model is stubbed rather than absent (see ``stub_openrouter``): a
production deployment has ``OPENROUTER_API_KEY`` set, so the extraction path
these journeys run through is the one the server runs. ``CELERY_ENABLED`` is
false in this suite, so the parse that the worker would do happens inline —
which is the same code, called from the same place, and is exactly what the
API does when the broker is unreachable.
"""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models.business_membership import BusinessMembership, MembershipRole
from tests.conftest import (
    BUSINESS_GSTIN,
    SUPPLIER_GSTIN_OTHER_STATE,
    SUPPLIER_GSTIN_SAME_STATE,
    TEST_EMAIL,
    TEST_PASSWORD,
    hsn_rows,
    make_paid,
)

PERIOD = "2026-04"

# ---------------------------------------------------------------------------
# The two documents every journey below is built from
# ---------------------------------------------------------------------------

# Inter-state purchase: Karnataka supplier, Maharashtra buyer, so the credit
# is IGST and the intra-state split never applies.
PURCHASE_TEXT = f"""\
NORTHWIND SUPPLIES PRIVATE LIMITED
GSTIN: {SUPPLIER_GSTIN_OTHER_STATE}
MG Road, Bengaluru, Karnataka 560001

TAX INVOICE

Invoice No: INV-2026-0042
Invoice Date: 15/04/2026
Place of Supply: 27 Maharashtra

Bill To: UMANG TRADERS
GSTIN: {BUSINESS_GSTIN}

HSN Code: 84713010
Laptop computers   10 x 45,000.00 = 450,000.00

Taxable Value:  450000.00
IGST @ 18%:      81000.00
Grand Total:    531000.00
"""

PURCHASE_EXTRACTION = {
    "supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE,
    "supplier_name": "Northwind Supplies Private Limited",
    "buyer_gstin": BUSINESS_GSTIN,
    "invoice_number": "INV-2026-0042",
    "invoice_date": "2026-04-15",
    "place_of_supply": "27",
    "hsn_code": "84713010",
    "taxable_value": 450000,
    "cgst": 0,
    "sgst": 0,
    "igst": 81000,
    "cess": 0,
    "total_value": 531000,
    "tax_rate": 18,
    "confidence": 0.95,
}

# Intra-state sale: both parties in Maharashtra, so the liability splits into
# CGST and SGST — and the set-off below has to consume the IGST credit from
# the purchase across both heads in the statutory order.
SALES_TEXT = f"""\
UMANG TRADERS PRIVATE LIMITED
GSTIN: {BUSINESS_GSTIN}
Andheri East, Mumbai, Maharashtra 400069

TAX INVOICE

Invoice No: UT/2026/0101
Invoice Date: 22/04/2026
Place of Supply: 27 Maharashtra

Bill To: MEHTA ELECTRICALS
GSTIN: {SUPPLIER_GSTIN_SAME_STATE}

HSN Code: 85044090
Power adapters   400 x 500.00 = 200,000.00

Taxable Value:  200000.00
CGST @ 9%:       18000.00
SGST @ 9%:       18000.00
Grand Total:    236000.00
"""

SALES_EXTRACTION = {
    "supplier_gstin": BUSINESS_GSTIN,
    "supplier_name": "Umang Traders Private Limited",
    "buyer_gstin": SUPPLIER_GSTIN_SAME_STATE,
    "buyer_name": "Mehta Electricals",
    "invoice_number": "UT/2026/0101",
    "invoice_date": "2026-04-22",
    "place_of_supply": "27",
    "hsn_code": "85044090",
    "taxable_value": 200000,
    "cgst": 18000,
    "sgst": 18000,
    "igst": 0,
    "cess": 0,
    "total_value": 236000,
    "tax_rate": 18,
    "confidence": 0.93,
}


def portal_2b(*, include_the_purchase: bool = True) -> bytes:
    """The GSTR-2B the portal would hand back for April 2026.

    ``include_the_purchase=False`` is the case the whole product exists for:
    the business has the invoice and the supplier never declared it, so the
    credit is at risk.
    """
    suppliers = []
    if include_the_purchase:
        suppliers.append(
            {
                "ctin": SUPPLIER_GSTIN_OTHER_STATE,
                "trdnm": "Northwind Supplies",
                "inv": [
                    {
                        "inum": "INV-2026-0042",
                        "dt": "15-04-2026",
                        "val": 531000.00,
                        "itcavl": "Y",
                        "items": [{"rt": 18, "txval": 450000.00, "igst": 81000.00}],
                    }
                ],
            }
        )
    else:
        # A different supplier's invoice, so the file is a valid 2B with
        # content rather than an empty one the import would refuse.
        suppliers.append(
            {
                "ctin": SUPPLIER_GSTIN_SAME_STATE,
                "trdnm": "Mehta Electricals",
                "inv": [
                    {
                        "inum": "ME/771",
                        "dt": "09-04-2026",
                        "val": 11800.00,
                        "itcavl": "Y",
                        "items": [
                            {"rt": 18, "txval": 10000.00, "cgst": 900.00, "sgst": 900.00}
                        ],
                    }
                ],
            }
        )

    return json.dumps(
        {"data": {"rtnprd": "042026", "docdata": {"b2b": suppliers}}}
    ).encode()


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def register(client) -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "gstin": BUSINESS_GSTIN,
            "legal_name": "Umang Traders Private Limited",
            "trade_name": "Umang Traders",
            "full_name": "Umang Shah",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def upload(client, model, *, text: str, extraction: dict, invoice_type: str, name: str) -> dict:
    """Upload one document and return the invoice row the API answered with."""
    model.clear()
    model.update(extraction)
    response = client.post(
        "/api/v1/invoices/upload",
        files={"file": (name, io.BytesIO(text.encode()), "text/plain")},
        data={"invoice_type": invoice_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["invoice"]


def import_2b(client, content: bytes, *, expected: int = 201) -> dict:
    response = client.post(
        "/api/v1/reconciliation/gstr2b/import",
        files={"file": ("gstr2b.json", content, "application/json")},
    )
    assert response.status_code == expected, response.text
    return response.json()


def reconcile(client, period: str) -> dict:
    response = client.post("/api/v1/reconciliation/run", json={"period": period})
    assert response.status_code == 201, response.text
    return response.json()


def takes_the_pro_plan(db_session, gstin: str = BUSINESS_GSTIN) -> None:
    """The step a journey through a paid feature takes after signing up.

    Reconciliation and the ITC screens are on the paid tier, so a business that
    reaches them has paid. Stands in for the Razorpay round trip, which
    ``test_subscriptions`` drives on its own.
    """
    from app.models.business import Business

    make_paid(db_session, db_session.query(Business).filter_by(gstin=gstin).one().id)


def money(value) -> Decimal:
    return Decimal(str(value))


@pytest.fixture()
def signed_in(client):
    """A client carrying a fresh business's bearer token.

    Deliberately not ``auth_client``: a journey starts before the account
    exists, and the sign-up is one of the steps under test.
    """
    client.headers.update({"Authorization": f"Bearer {register(client)}"})
    return client


# ---------------------------------------------------------------------------
# The path the product is for
# ---------------------------------------------------------------------------

class TestABusinessSignsUpAndFilesItsFirstReturn:
    def test_the_whole_journey(self, client, db_session, stub_openrouter):
        # --- Before there is an account -----------------------------------
        assert client.get("/api/v1/health/live").json()["status"] == "alive"
        assert client.get("/api/v1/health/ready").status_code == 200

        # The sign-up form validates the GSTIN before it will submit, and it
        # has no token to do it with.
        lookup = client.get(f"/api/v1/meta/gstin/{BUSINESS_GSTIN}")
        assert lookup.status_code == 200
        assert lookup.json() == {
            "gstin": BUSINESS_GSTIN,
            "valid": True,
            "state_code": "27",
            "state_name": "Maharashtra",
            "pan": BUSINESS_GSTIN[2:12],
        }

        # --- Sign up ------------------------------------------------------
        token = register(client)
        client.headers.update({"Authorization": f"Bearer {token}"})
        takes_the_pro_plan(db_session)

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["business"]["gstin"] == BUSINESS_GSTIN
        # Registration returns a usable token, so there is no second login
        # round trip — but logging in again must produce one that works too.
        # Form-encoded, not JSON: the endpoint is the OAuth2 password flow,
        # which is what puts the Authorize button in the docs.
        again = client.post(
            "/api/v1/auth/login",
            data={"username": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert again.status_code == 200
        assert (
            client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {again.json()['access_token']}"},
            ).status_code
            == 200
        )

        # --- Upload the month's documents ---------------------------------
        purchase = upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        assert purchase["status"] == "parsed"
        assert purchase["counterparty_gstin"] == SUPPLIER_GSTIN_OTHER_STATE
        # The period is derived from the invoice date, and every later step
        # keys off it. This is the handoff the rest of the journey rests on.
        assert purchase["period"] == PERIOD
        assert money(purchase["igst"]) == Decimal("81000.00")

        sale = upload(
            client,
            stub_openrouter,
            text=SALES_TEXT,
            extraction=SALES_EXTRACTION,
            invoice_type="sales",
            name="ut-0101.txt",
        )
        assert sale["status"] == "parsed"
        assert sale["period"] == PERIOD
        assert money(sale["cgst"]) == money(sale["sgst"]) == Decimal("18000.00")

        listed = client.get("/api/v1/invoices", params={"period": PERIOD})
        assert listed.status_code == 200
        assert {row["id"] for row in listed.json()["items"]} == {purchase["id"], sale["id"]}

        # --- Import the portal's 2B and reconcile -------------------------
        imported = import_2b(client, portal_2b())
        # The period the import derived from the file, not one the client
        # supplied: a mismatch here is how a month reconciles against the
        # wrong statement and reports everything missing.
        assert imported["period"] == PERIOD
        assert imported["invoice_count"] == 1

        run = reconcile(client, PERIOD)
        assert run["status"] == "completed"
        assert run["matched_count"] == 1
        assert run["missing_in_2b_count"] == 0
        assert run["mismatched_count"] == 0
        assert money(run["itc_at_risk"]) == Decimal("0.00")

        # The run is retrievable afterwards by id and as "the latest for this
        # period" — the two ways the UI reaches it.
        by_id = client.get(f"/api/v1/reconciliation/{run['id']}")
        assert by_id.status_code == 200
        latest = client.get("/api/v1/reconciliation/latest", params={"period": PERIOD})
        assert latest.status_code == 200
        assert latest.json()["id"] == run["id"]

        # --- What credit is actually safe to claim ------------------------
        itc = client.get("/api/v1/itc", params={"period": PERIOD}).json()
        assert itc["reconciled"] is True
        assert money(itc["available"]["igst"]) == Decimal("81000.00")
        assert money(itc["itc_at_risk"]) == Decimal("0.00")
        assert money(itc["output_tax"]["cgst"]) == Decimal("18000.00")
        assert money(itc["output_tax"]["sgst"]) == Decimal("18000.00")

        # The point of the whole month: ₹81,000 of IGST credit against
        # ₹36,000 of CGST+SGST liability leaves nothing to pay in cash.
        set_off = itc["set_off"]
        assert money(set_off["total_cash"]) == Decimal("0.00")
        assert money(set_off["credit_carried_forward"]["total"]) == Decimal("45000.00")

        # --- The supplier this created ------------------------------------
        suppliers = client.get("/api/v1/suppliers").json()
        assert [s["gstin"] for s in suppliers["items"]] == [SUPPLIER_GSTIN_OTHER_STATE]
        supplier = suppliers["items"][0]
        assert supplier["risk_level"] == "low"

        detail = client.get(f"/api/v1/suppliers/{supplier['id']}", params={"period": PERIOD})
        assert detail.status_code == 200
        assert detail.json()["gstin"] == SUPPLIER_GSTIN_OTHER_STATE

        # --- File ---------------------------------------------------------
        validation = client.get(
            "/api/v1/filing/validate", params={"period": PERIOD, "invoice_type": "sales"}
        ).json()
        assert validation["period"] == PERIOD
        assert validation["error_count"] == 0
        assert validation["ok"] is True

        gstr1 = client.get("/api/v1/filing/gstr1", params={"period": PERIOD}).json()
        assert gstr1["validation"]["ok"] is True
        assert gstr1["document"]["gstin"] == BUSINESS_GSTIN
        assert gstr1["document"]["fp"] == "042026"
        b2b_counterparties = {block["ctin"] for block in gstr1["document"]["b2b"]}
        assert b2b_counterparties == {SUPPLIER_GSTIN_SAME_STATE}

        gstr3b = client.get("/api/v1/filing/gstr3b", params={"period": PERIOD}).json()
        assert gstr3b["document"]["gstin"] == BUSINESS_GSTIN
        assert gstr3b["document"]["ret_period"] == "042026"

        # --- Download it --------------------------------------------------
        export = client.get("/api/v1/filing/export/gstr1.json", params={"period": PERIOD})
        assert export.status_code == 200
        assert "attachment" in export.headers["content-disposition"]
        assert BUSINESS_GSTIN in export.headers["content-disposition"]
        # Byte-for-byte the document the preview showed. A user approves the
        # preview and files the download; if they can differ, the approval
        # was of something else.
        assert json.loads(export.content) == gstr1["document"]

        # --- The screen they land on next month ---------------------------
        dashboard = client.get("/api/v1/dashboard", params={"period": PERIOD}).json()
        assert dashboard["period"] == PERIOD
        assert dashboard["counts"]["total"] == 2
        assert dashboard["counts"]["sales"] == dashboard["counts"]["purchase"] == 1
        assert money(dashboard["purchase"]["igst"]) == Decimal("81000.00")
        assert money(dashboard["sales"]["cgst"]) == Decimal("18000.00")
        assert dashboard["last_reconciliation"]["id"] == run["id"]
        assert dashboard["last_reconciliation"]["matched"] == 1
        assert money(dashboard["itc_at_risk"]) == Decimal("0.00")
        assert dashboard["business_gstin"] == BUSINESS_GSTIN


# ---------------------------------------------------------------------------
# The path the product is actually for
# ---------------------------------------------------------------------------

class TestASupplierWhoDidNotFile:
    """The invoice is in the books and not in the portal's 2B.

    This is the leak GSTIndia exists to find, and it has to be visible from
    every screen a user might be on — not only from the reconciliation report
    that discovered it.
    """

    def test_the_risk_reaches_every_screen(self, client, db_session, stub_openrouter):
        client.headers.update({"Authorization": f"Bearer {register(client)}"})
        takes_the_pro_plan(db_session)
        purchase = upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )

        import_2b(client, portal_2b(include_the_purchase=False))
        run = reconcile(client, PERIOD)

        assert run["matched_count"] == 0
        assert run["missing_in_2b_count"] == 1
        assert money(run["itc_at_risk"]) == Decimal("81000.00")

        # The finding names the invoice, not just a count — the user has to
        # be able to go and chase this specific supplier.
        detail = client.get(f"/api/v1/reconciliation/{run['id']}").json()
        findings = detail["report"]["findings"]
        at_risk = [f for f in findings if f["category"] == "missing_in_2b"]
        assert len(at_risk) == 1
        assert at_risk[0]["invoice_number"] == purchase["invoice_number"]

        itc = client.get("/api/v1/itc", params={"period": PERIOD}).json()
        assert money(itc["itc_at_risk"]) == Decimal("81000.00")

        dashboard = client.get("/api/v1/dashboard", params={"period": PERIOD}).json()
        assert money(dashboard["itc_at_risk"]) == Decimal("81000.00")

        # And the supplier carries it, so the next purchase from them is a
        # decision made with this in hand.
        supplier = client.get("/api/v1/suppliers").json()["items"][0]
        assert supplier["gstin"] == SUPPLIER_GSTIN_OTHER_STATE
        assert supplier["risk_level"] in {"medium", "high"}
        assert supplier["compliance_score"] < 100

    def test_the_credit_appears_when_the_supplier_files_late(
        self, client, db_session, stub_openrouter
    ):
        """Re-importing a corrected 2B must move the credit, not double it.

        Runs accumulate rather than overwrite, so this is the case where a
        second run over the same period has to supersede the first one's
        conclusion while leaving its record intact.
        """
        client.headers.update({"Authorization": f"Bearer {register(client)}"})
        takes_the_pro_plan(db_session)
        upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )

        import_2b(client, portal_2b(include_the_purchase=False))
        first = reconcile(client, PERIOD)
        assert money(first["itc_at_risk"]) == Decimal("81000.00")

        # The supplier files. The portal now has the invoice.
        again = import_2b(client, portal_2b())
        assert again["replaced_previous"] is True

        second = reconcile(client, PERIOD)
        assert second["id"] != first["id"]
        assert second["matched_count"] == 1
        assert money(second["itc_at_risk"]) == Decimal("0.00")

        # Both runs are still on file — "what did we know, and when" is the
        # question an ITC reversal turns on months later.
        history = client.get("/api/v1/reconciliation", params={"period": PERIOD}).json()
        assert [row["id"] for row in history["items"]] == [second["id"], first["id"]]

        # And the latest is what every other screen now reads.
        assert money(
            client.get("/api/v1/itc", params={"period": PERIOD}).json()["itc_at_risk"]
        ) == Decimal("0.00")


# ---------------------------------------------------------------------------
# Two businesses on one deployment
# ---------------------------------------------------------------------------

class TestASaleTheExtractorCouldNotPlace:
    """The one blocking error a reviewer fixes by typing, start to finish.

    "Place of supply is missing and cannot be derived from a GSTIN" is raised
    per invoice and blocks the whole period, and it is the only error on that
    list with no second source to fall back on: a B2B sale gets the state off
    the buyer's GSTIN, and a B2C one has nothing. So this is the loop the
    invoice screen's place-of-supply field exists to close — validate, correct,
    validate again, file — and it crosses three modules that are otherwise
    tested apart.

    What makes it worth a journey rather than a unit test is what the export
    does *while* the period is blocked. ``gstr1`` does not refuse an invoice it
    cannot place; it falls back to the business's own state, so an unfixed sale
    is not missing from the return — it is in it, declared in the wrong state,
    under a heading that contradicts its own tax. The error is the only thing
    standing between that and the portal.
    """

    # Its own document rather than ``SALES_TEXT``: the parser fills anything
    # the model left out from what it can read off the page, so an extraction
    # claiming no CGST over a page printing some comes back with the page's
    # figures and three validation errors instead of the one under test.
    UNPLACEABLE_TEXT = f"""\
UMANG TRADERS PRIVATE LIMITED
GSTIN: {BUSINESS_GSTIN}
Andheri East, Mumbai, Maharashtra 400069

TAX INVOICE

Invoice No: UT/2026/0102
Invoice Date: 24/04/2026

Bill To: Cash sale

HSN Code: 85044090
Power adapters   600 x 500.00 = 300,000.00

Taxable Value:  300000.00
IGST @ 18%:      54000.00
Grand Total:    354000.00
"""

    # No buyer GSTIN, so there is no state to derive: an over-the-counter sale
    # to an unregistered customer. Inter-state, and above the B2CL threshold,
    # so where it lands in the return turns entirely on the missing field.
    UNPLACEABLE_SALE = {
        "supplier_gstin": BUSINESS_GSTIN,
        "supplier_name": "Umang Traders Private Limited",
        "buyer_gstin": None,
        "buyer_name": "Walk-in customer",
        "invoice_number": "UT/2026/0102",
        "invoice_date": "2026-04-24",
        "place_of_supply": None,
        "hsn_code": "85044090",
        "taxable_value": 300000,
        "cgst": 0,
        "sgst": 0,
        "igst": 54000,
        "cess": 0,
        "total_value": 354000,
        "tax_rate": 18,
        "confidence": 0.71,
    }

    def sale(self, client, model) -> dict:
        return upload(
            client,
            model,
            text=self.UNPLACEABLE_TEXT,
            extraction=self.UNPLACEABLE_SALE,
            invoice_type="sales",
            name="ut-2026-0102.txt",
        )

    def test_the_period_is_blocked_until_the_sale_is_placed(self, signed_in, stub_openrouter):
        sale = self.sale(signed_in, stub_openrouter)
        assert sale["place_of_supply"] is None

        blocked = signed_in.get(
            "/api/v1/filing/validate", params={"period": PERIOD, "invoice_type": "sales"}
        ).json()
        assert blocked["ok"] is False
        assert blocked["error_count"] == 1
        [issue] = [i for i in blocked["issues"] if i["severity"] == "error"]
        assert issue["field"] == "place_of_supply"
        # Named, not counted. The reviewer has to be able to open the one
        # invoice out of the month's sales that is holding the return up.
        assert issue["invoice_id"] == sale["id"]
        assert issue["invoice_number"] == "UT/2026/0102"

        # --- Correct it, which is the only fix there is -------------------
        patched = signed_in.patch(
            f"/api/v1/invoices/{sale['id']}", json={"place_of_supply": "29"}
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["place_of_supply"] == "29"

        cleared = signed_in.get(
            "/api/v1/filing/validate", params={"period": PERIOD, "invoice_type": "sales"}
        ).json()
        assert cleared["ok"] is True
        assert cleared["error_count"] == 0

    def test_the_corrected_state_is_what_the_return_declares(
        self, signed_in, stub_openrouter
    ):
        """The correction has to reach ``pos``, not just clear the error."""
        sale = self.sale(signed_in, stub_openrouter)

        # Before: placed in the seller's own state by the fallback, which puts
        # a ₹3.54 lakh inter-state supply into the summary block for small
        # local ones — carrying IGST under a heading that says INTRA.
        before = signed_in.get("/api/v1/filing/gstr1", params={"period": PERIOD}).json()
        assert before["validation"]["ok"] is False
        # An empty block is left out of the document rather than sent empty,
        # so "not in b2cl" is spelt as the key being absent.
        assert "b2cl" not in before["document"]
        [misplaced] = before["document"]["b2cs"]
        assert misplaced["pos"] == "27"
        assert misplaced["sply_ty"] == "INTRA"
        assert money(misplaced["iamt"]) == Decimal("54000.00")

        signed_in.patch(f"/api/v1/invoices/{sale['id']}", json={"place_of_supply": "29"})

        after = signed_in.get("/api/v1/filing/gstr1", params={"period": PERIOD}).json()
        assert after["validation"]["ok"] is True
        # Now an inter-state supply above the threshold: listed invoice by
        # invoice under Karnataka rather than summarised under Maharashtra.
        assert "b2cs" not in after["document"]
        [block] = after["document"]["b2cl"]
        assert block["pos"] == "29"
        assert [inv["inum"] for inv in block["inv"]] == ["UT/2026/0102"]

        # And the file a user downloads is that document, not a second render
        # of it from the pre-correction state.
        export = signed_in.get("/api/v1/filing/export/gstr1.json", params={"period": PERIOD})
        assert json.loads(export.content) == after["document"]

    def test_a_state_code_the_council_never_issued_is_refused(self, signed_in, stub_openrouter):
        """The picker cannot send this; a script and a stale client can.

        Worth refusing at the API rather than only in the form, because the
        portal rejects the whole return over one bad ``pos`` — there is no
        partial acceptance to fall back on.
        """
        sale = self.sale(signed_in, stub_openrouter)

        response = signed_in.patch(
            f"/api/v1/invoices/{sale['id']}", json={"place_of_supply": "45"}
        )

        assert response.status_code == 422
        assert "45" in response.text


class TestOneTenantsJourneyIsInvisibleToAnother:
    def test_no_read_endpoint_leaks_across_the_boundary(self, client, db_session, stub_openrouter):
        # Tenant A does the whole journey.
        client.headers.update({"Authorization": f"Bearer {register(client)}"})
        takes_the_pro_plan(db_session)
        purchase = upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        import_2b(client, portal_2b())
        run = reconcile(client, PERIOD)
        supplier_id = client.get("/api/v1/suppliers").json()["items"][0]["id"]

        # Tenant B signs up on the same deployment.
        other = client.post(
            "/api/v1/auth/register",
            json={
                "email": "rival@example.com",
                "password": "anothersecret123",
                "gstin": SUPPLIER_GSTIN_SAME_STATE,
                "legal_name": "Mehta Electricals",
            },
        )
        assert other.status_code == 201, other.text
        # B pays too, so an empty answer on a paid screen is the boundary
        # holding rather than B being refused the screen.
        takes_the_pro_plan(db_session, SUPPLIER_GSTIN_SAME_STATE)
        client.headers.update(
            {"Authorization": f"Bearer {other.json()['access_token']}"}
        )

        # Nothing of A's is listed.
        assert client.get("/api/v1/invoices").json()["items"] == []
        assert client.get("/api/v1/suppliers").json()["items"] == []
        assert client.get("/api/v1/reconciliation").json()["items"] == []
        empty = client.get("/api/v1/dashboard", params={"period": PERIOD}).json()
        assert empty["counts"]["total"] == 0
        assert empty["last_reconciliation"] is None

        # And nothing of A's is reachable by id. 404 rather than 403 on every
        # one of them: a 403 confirms the row exists, which is enough to probe
        # a competitor's invoice volume by walking the ids.
        for path in (
            f"/api/v1/invoices/{purchase['id']}",
            f"/api/v1/reconciliation/{run['id']}",
            f"/api/v1/suppliers/{supplier_id}",
        ):
            assert client.get(path).status_code == 404, path

        # Including the writes.
        assert client.patch(
            f"/api/v1/invoices/{purchase['id']}", json={"invoice_number": "STOLEN-1"}
        ).status_code == 404
        assert client.delete(f"/api/v1/invoices/{purchase['id']}").status_code == 404

        # B's own 2B import for the same period does not see A's statement.
        assert client.get("/api/v1/reconciliation/gstr2b/periods").json() == {"items": []}
        assert (
            client.post("/api/v1/reconciliation/run", json={"period": PERIOD}).status_code
            == 409
        )


# ---------------------------------------------------------------------------
# What the user downloads
# ---------------------------------------------------------------------------

class TestTheExportsAUserActuallyOpens:
    @pytest.fixture()
    def filed(self, client, db_session, stub_openrouter):
        client.headers.update({"Authorization": f"Bearer {register(client)}"})
        takes_the_pro_plan(db_session)
        upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        upload(
            client,
            stub_openrouter,
            text=SALES_TEXT,
            extraction=SALES_EXTRACTION,
            invoice_type="sales",
            name="ut-0101.txt",
        )
        import_2b(client, portal_2b())
        reconcile(client, PERIOD)
        return client

    @pytest.mark.parametrize("return_type", ["gstr1", "gstr3b"])
    def test_the_json_download_is_the_preview_verbatim(self, filed, return_type):
        preview = filed.get(f"/api/v1/filing/{return_type}", params={"period": PERIOD})
        download = filed.get(
            f"/api/v1/filing/export/{return_type}.json", params={"period": PERIOD}
        )

        assert download.status_code == 200
        assert json.loads(download.content) == preview.json()["document"]

    @pytest.mark.parametrize("return_type", ["gstr1", "gstr3b", "purchases"])
    def test_the_csv_download_opens_in_a_spreadsheet(self, filed, return_type):
        response = filed.get(
            f"/api/v1/filing/export/{return_type}.csv", params={"period": PERIOD}
        )
        assert response.status_code == 200

        body = response.content.decode("utf-8")
        # Excel reads a plain UTF-8 CSV as Latin-1 and mangles every trade
        # name with a rupee sign in it, so the BOM is load-bearing.
        assert body.startswith("﻿")

        rows = list(csv.reader(io.StringIO(body.lstrip("﻿"))))
        assert len(rows) >= 2, "a header and at least one invoice"
        assert all(len(row) == len(rows[0]) for row in rows), "ragged CSV"

    def test_a_purchase_register_has_no_portal_json_shape(self, filed):
        # The government's offline utility has no import for this; offering a
        # .json would produce a file that only looks like it can be filed.
        assert (
            filed.get(
                "/api/v1/filing/export/purchases.json", params={"period": PERIOD}
            ).status_code
            == 400
        )


# ---------------------------------------------------------------------------
# The credit that quietly runs out of time
# ---------------------------------------------------------------------------

class TestCreditNobodyGotRoundToClaiming:
    """s.16(4), from the invoice that carries the credit to the filing that saves it.

    ``test_itc_deadline.py`` owns the arithmetic — which financial year an
    invoice falls in, where the 30th of November lands, when the severity
    escalates. What it cannot see is the handoff this journey is about: the
    deadline screen names a *period*, the filing endpoint takes a *period*,
    and the credit only stops being at risk if those two are the same string.
    They are produced by different modules from different columns, and a
    disagreement between them would show up as an alert that a business
    cannot clear by doing exactly what it asks for.

    The dates are fixed rather than relative. The whole subject is a distance
    between an invoice date and a deadline nineteen months later, so a journey
    that read the clock would assert something different every morning and
    would stop exercising the expired branch the moment the calendar caught up.
    """

    # PERIOD is 2026-04, so FY 2026-27, so the credit dies on 30 Nov 2027.
    DEADLINE = "2027-11-30"
    # Exactly LEAD_DAYS before it — the day the alerting would first speak.
    SIXTY_DAYS_OUT = "2027-10-01"
    THE_DAY_AFTER = "2027-12-01"

    @pytest.fixture()
    def bought(self, client, db_session, stub_openrouter):
        """One purchase, ₹81,000 of IGST on it, and no return recorded."""
        client.headers.update({"Authorization": f"Bearer {register(client)}"})
        takes_the_pro_plan(db_session)
        invoice = upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        assert invoice["period"] == PERIOD
        return client

    def _lapsing(self, client, as_of: str) -> dict:
        response = client.get("/api/v1/itc/lapsing", params={"as_of": as_of})
        assert response.status_code == 200, response.text
        return response.json()

    def _record_3b(self, client, *, period: str = PERIOD):
        return client.post(
            "/api/v1/filing/gstr3b/filed",
            json={"period": period, "filed_at": "2026-05-20", "arn": "AA270426000001X"},
        )

    def test_the_period_the_deadline_names_is_the_one_that_clears_it(self, bought):
        lapsing = self._lapsing(bought, self.SIXTY_DAYS_OUT)
        (year,) = lapsing["years"]
        assert year["financial_year"] == "2026-27"
        assert year["deadline"] == self.DEADLINE
        assert year["days_remaining"] == 60
        assert year["expired"] is False
        assert money(lapsing["total_at_risk"]) == Decimal("81000.00")

        # The actionable half of the answer: not "you have credit at risk" but
        # "file these". Fed straight back into the filing endpoint, with
        # nothing in this test reshaping it — a period spelled one way here
        # and another way there is exactly the defect that survives both
        # modules' own tests.
        (period,) = year["periods"]
        assert self._record_3b(bought, period=period).status_code in (200, 201)

        after = self._lapsing(bought, self.SIXTY_DAYS_OUT)
        assert after["years"] == []
        assert money(after["total_at_risk"]) == Decimal("0")

    def test_the_credit_and_the_summary_are_talking_about_the_same_money(self, bought):
        summary = bought.get("/api/v1/itc", params={"period": PERIOD})
        assert summary.status_code == 200, summary.text

        (year,) = self._lapsing(bought, self.SIXTY_DAYS_OUT)["years"]
        # One screen says what may be claimed for the month, the other what is
        # lost if nobody does. A business reading both has to be able to put
        # them side by side, and two figures for one invoice would make the
        # deadline screen look like it is about some other purchase.
        assert money(year["tax"]["total"]) == money(
            summary.json()["available"]["total"]
        )
        assert year["invoice_count"] == 1

    def test_the_day_after_the_deadline_the_credit_is_reported_lost_rather_than_dropped(
        self, bought
    ):
        # The morning the loss becomes permanent is the morning it most needs
        # to be on the screen. A list that only showed savable credit would go
        # empty overnight and read as good news.
        lapsing = self._lapsing(bought, self.THE_DAY_AFTER)

        (year,) = lapsing["years"]
        assert year["expired"] is True
        assert year["days_remaining"] == -1
        assert money(lapsing["total_expired"]) == Decimal("81000.00")
        assert money(lapsing["total_at_risk"]) == Decimal("0")

    def test_recording_the_gstr1_does_not_claim_the_purchase_credit(self, bought):
        # Credit reaches a return through GSTR-3B table 4(A) and nowhere else,
        # so the outward return is not the one that saves it. Worth a journey
        # of its own because both are recorded through the same endpoint with
        # one path segment between them: a filing recorded against the wrong
        # return type must not quietly make the warning go away.
        recorded = bought.post(
            "/api/v1/filing/gstr1/filed",
            json={"period": PERIOD, "filed_at": "2026-05-11", "arn": "AA270426000002X"},
        )
        assert recorded.status_code in (200, 201), recorded.text

        (year,) = self._lapsing(bought, self.SIXTY_DAYS_OUT)["years"]
        assert year["periods"] == [PERIOD]
        assert money(year["tax"]["total"]) == Decimal("81000.00")


# ---------------------------------------------------------------------------
# The request as an operator sees it
# ---------------------------------------------------------------------------

class TestOneRequestIsTraceableEndToEnd:
    def test_the_id_a_user_reports_is_the_id_on_every_response(self, client, stub_openrouter):
        client.headers.update({"Authorization": f"Bearer {register(client)}"})

        # An id supplied by the caller survives, so a trace that starts in the
        # frontend or at Caddy stays one trace through the upload and the
        # parse it triggers.
        supplied = "e2e0000000000001"
        stub_openrouter.update(PURCHASE_EXTRACTION)
        response = client.post(
            "/api/v1/invoices/upload",
            files={"file": ("northwind.txt", io.BytesIO(PURCHASE_TEXT.encode()), "text/plain")},
            data={"invoice_type": "purchase"},
            headers={"X-Request-ID": supplied},
        )

        assert response.status_code == 201
        assert response.headers["X-Request-ID"] == supplied
        assert response.headers["X-Correlation-ID"] == supplied

    def test_a_failure_carries_the_same_id_into_the_body(self, client):
        client.headers.update({"Authorization": f"Bearer {register(client)}"})

        response = client.get("/api/v1/invoices/999999")

        assert response.status_code == 404
        body = response.json()
        # Support gets a screenshot; this is what turns it into a log query.
        assert body["correlation_id"] == response.headers["X-Request-ID"]
        assert body["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# The other person who touches these books
# ---------------------------------------------------------------------------

class TestAClientGivesTheirAccountantReadOnlyAccess:
    """A whole session held by someone who may look and may not touch.

    ``test_rbac.py`` sweeps the route table twice over: every mutating route
    carries the gate, and every gated route refuses a real viewer. Both are
    per-route questions asked of an empty request, and neither can answer the
    one a business actually asks — *if I give my CA read-only access, do they
    see my books, and are my books the same afterwards?*

    So this is the sequence rather than the surface: a month is prepared by
    its owner, a second login is granted access to it, every screen that login
    would open is read through the ``X-Business-Id`` header, every write it
    could reach is refused, and the whole read surface is compared against the
    snapshot taken before. A gate that refuses the request and a write that
    happens anyway are different failures, and only the comparison sees the
    second.
    """

    # The reads a session makes going round the app once, keyed by the name
    # the failure message needs. Every one is compared before and after.
    READS = {
        "dashboard": "/api/v1/dashboard?period=" + PERIOD,
        "invoices": "/api/v1/invoices?period=" + PERIOD,
        "reconciliation history": "/api/v1/reconciliation?period=" + PERIOD,
        "latest run": "/api/v1/reconciliation/latest?period=" + PERIOD,
        "itc": "/api/v1/itc?period=" + PERIOD,
        "lapsing credit": "/api/v1/itc/lapsing",
        "gstr1": "/api/v1/filing/gstr1?period=" + PERIOD,
        "gstr3b": "/api/v1/filing/gstr3b?period=" + PERIOD,
        "filing status": "/api/v1/filing/status",
        "suppliers": "/api/v1/suppliers",
        "alerts": "/api/v1/alerts",
    }

    @pytest.fixture()
    def clients_books(self, client, db_session, stub_openrouter) -> dict:
        """A month, prepared by the owner of the business it belongs to."""
        token = register(client)
        client.headers.update({"Authorization": f"Bearer {token}"})
        takes_the_pro_plan(db_session)

        purchase = upload(
            client, stub_openrouter,
            text=PURCHASE_TEXT, extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase", name="northwind-0042.txt",
        )
        upload(
            client, stub_openrouter,
            text=SALES_TEXT, extraction=SALES_EXTRACTION,
            invoice_type="sales", name="ut-0101.txt",
        )
        import_2b(client, portal_2b())
        run = reconcile(client, PERIOD)

        business_id = client.get("/api/v1/auth/me").json()["business"]["id"]
        return {"business_id": business_id, "invoice_id": purchase["id"], "run_id": run["id"]}

    @pytest.fixture()
    def accountant(self, clients_books, db_session):
        """A second login holding read-only access to the books above.

        The link is made over HTTP the only way this product offers — the
        other account's own email and password, which is what ``POST
        /businesses/mine/link`` exists for — and the membership it creates
        carries that account's role, which is owner. Demoting it here is not
        working around an API: there is no invitation endpoint, and a business
        that wants to *show* its books rather than hand them over is what the
        viewer role is for. What the demotion stands in for is the operator
        action a support request produces today.
        """
        from tests.test_businesses import register_second_business

        # A second client over the same app, rather than swapping headers on
        # the owner's: the point of the fixture is two live sessions, and a
        # single client that has to be re-pointed between them is one `del`
        # away from asserting the owner's authority against the viewer's name.
        # The `client` fixture already ran the lifespan and installed the
        # database override on the app, and both are app-wide.
        session = TestClient(app)
        second = register_second_business(session)
        session.headers.update({"Authorization": f"Bearer {second['access_token']}"})

        linked = session.post(
            "/api/v1/businesses/mine/link",
            json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        )
        assert linked.status_code == 201, linked.text
        assert linked.json()["id"] == clients_books["business_id"]
        # Carried over as owner, which is the role the linked account holds on
        # its own books. Read-only is the narrower grant, and it is the one
        # under test.
        assert linked.json()["role"] == "owner"

        membership = db_session.scalar(
            select(BusinessMembership).where(
                BusinessMembership.business_id == clients_books["business_id"],
                BusinessMembership.deleted_at.is_(None),
            )
        )
        membership.role = MembershipRole.VIEWER
        db_session.commit()

        session.headers.update({"X-Business-Id": str(clients_books["business_id"])})
        return session

    def test_the_session_reports_the_role_it_will_actually_be_held_to(
        self, accountant, clients_books
    ):
        """What the frontend gates its buttons on.

        Both roles are in one response and they differ: ``role`` is owner,
        because this login owns its own registration, and ``active_role`` is
        viewer, because that is the membership on the business the header
        names. A client gating on the first offers a full set of controls for
        the one business where every one of them is refused.
        """
        me = accountant.get("/api/v1/auth/me")
        assert me.status_code == 200, me.text
        body = me.json()

        assert body["business"]["id"] == clients_books["business_id"]
        assert body["business"]["gstin"] == BUSINESS_GSTIN
        assert body["role"] == "owner"
        assert body["active_role"] == "viewer"

    def test_every_screen_they_open_shows_the_clients_books(
        self, accountant, clients_books
    ):
        """Read-only is access, not a wall.

        A grant that refused the reads too would pass every 403 assertion in
        this file while being useless — and it is the failure a tenancy check
        applied to the header would produce, because the accountant is not a
        member of these books by registration, only by membership.
        """
        for name, path in self.READS.items():
            response = accountant.get(path)
            assert response.status_code == 200, (
                f"{name}: {response.status_code} {response.text[:200]}"
            )

        # And the figures are the client's, not an empty tenant's: this is what
        # a membership resolved to the wrong business would get wrong.
        dashboard = accountant.get(self.READS["dashboard"]).json()
        assert dashboard["business_gstin"] == BUSINESS_GSTIN
        assert dashboard["counts"]["total"] == 2
        assert dashboard["last_reconciliation"]["id"] == clients_books["run_id"]

        invoice = accountant.get(f"/api/v1/invoices/{clients_books['invoice_id']}")
        assert invoice.status_code == 200
        assert invoice.json()["counterparty_gstin"] == SUPPLIER_GSTIN_OTHER_STATE

    def test_every_write_the_screens_offer_is_refused(self, accountant, clients_books):
        """One refusal per area, each with the wording a person can act on.

        The exhaustive sweep is ``test_rbac.py``'s. What this asserts is that
        the refusal is the *role's* — a 403 naming the role held — rather than
        the tenancy 404 a login with no membership would get, because the two
        send the reader to entirely different places.
        """
        invoice_id = clients_books["invoice_id"]
        writes = [
            ("POST", "/api/v1/invoices/upload"),
            ("PATCH", f"/api/v1/invoices/{invoice_id}"),
            ("POST", f"/api/v1/invoices/{invoice_id}/reparse"),
            ("DELETE", f"/api/v1/invoices/{invoice_id}"),
            ("POST", "/api/v1/reconciliation/gstr2b/import"),
            ("POST", "/api/v1/reconciliation/run"),
            ("POST", "/api/v1/suppliers/rescore"),
            ("POST", "/api/v1/filing/gstr1/filed"),
            ("POST", "/api/v1/alerts/1/dismiss"),
        ]
        for method, path in writes:
            response = accountant.request(method, path)
            assert response.status_code == 403, (
                f"{method} {path} answered {response.status_code}: {response.text[:200]}"
            )
            body = response.json()
            assert "viewer" in body["detail"], f"{method} {path}: {body['detail']}"
            assert body["error"]["status"] == 403

    def test_the_books_are_byte_for_byte_what_they_were(
        self, client, accountant, clients_books
    ):
        """The assertion the per-route sweeps cannot make.

        A gate that answers 403 *after* the handler has already written is a
        passing test everywhere else in this suite and a data loss here. So the
        owner's own view of every screen is captured before the viewer's
        session and compared after it, through the owner's session rather than
        the viewer's — a write that also broke the viewer's reads would
        otherwise hide inside two matching wrong answers.
        """
        before = {name: client.get(path).json() for name, path in self.READS.items()}

        for method, path in [
            ("PATCH", f"/api/v1/invoices/{clients_books['invoice_id']}"),
            ("DELETE", f"/api/v1/invoices/{clients_books['invoice_id']}"),
            ("POST", "/api/v1/reconciliation/run"),
            ("POST", "/api/v1/filing/gstr1/filed"),
        ]:
            assert accountant.request(method, path).status_code == 403

        after = {name: client.get(path).json() for name, path in self.READS.items()}
        for name in self.READS:
            assert after[name] == before[name], f"{name} changed under a refused write"

    def test_their_own_books_are_still_theirs_in_the_same_session(self, accountant, db_session):
        """The other half, and the one a login-level role check gets wrong.

        Dropping the header is the whole difference: the same token, the same
        request, and an authority that comes back because the business it acts
        for has changed. A check that read the login's role would refuse this
        too, and a practice would find that taking on one read-only client had
        made their own registration read-only.
        """
        del accountant.headers["X-Business-Id"]

        me = accountant.get("/api/v1/auth/me").json()
        assert me["active_role"] == "owner"
        assert me["business"]["gstin"] != BUSINESS_GSTIN

        # A write that was 403 one line ago, on the books this login owns. The
        # practice is on a paid plan, so a 403 here could only be the role.
        from tests.test_businesses import SECOND_GSTIN

        takes_the_pro_plan(db_session, SECOND_GSTIN)
        response = accountant.post(
            "/api/v1/reconciliation/run", json={"period": PERIOD}
        )
        assert response.status_code != 403, response.text


# ---------------------------------------------------------------------------
# The money a supplier's unpaid bill costs, and where it is charged
# ---------------------------------------------------------------------------

class TestTheHundredAndEightyDayClockAndWhatItReverses:
    """Rule 37, from the screen that has no period to the return that has one.

    ``test_itc.py`` owns the arithmetic — when day 180 falls, which head the
    reversal lands on, how re-availment puts it back. What it cannot see is the
    handoff this journey is about, and it is a handoff between two *shapes* of
    answer rather than two figures.

    ``/itc/rule37`` is deliberately period-less: the invoice whose clock runs
    out this month was issued six months ago, and a period filter would never
    surface it. So it reports a standing exposure — everything unpaid past 180
    days, whenever it lapsed. ``/itc`` and the return built from it are
    period-scoped and must charge that exposure to exactly one month: the one
    the 180 days ran out in.

    The failure that shape difference invites is not a wrong total on either
    screen. It is the same invoice reversed again in every return that follows
    the lapse, each time as though it were new — every figure defensible read
    on its own, and a business that filed four months of returns giving back
    four times the credit the rule asks for. Nothing a single period's response
    contains can distinguish that from correct; only asking several periods in
    a row and adding them up can.

    The dates are ``as_of`` rather than the clock, for the reason the s.16(4)
    journey uses fixed dates: the subject is a distance of 180 days from an
    invoice date, so a test that read the clock would assert something
    different every morning and would stop exercising the overdue branch
    entirely on the days the calendar had not reached yet.
    """

    # PURCHASE_EXTRACTION is dated 15/04/2026. The Act allows the whole of day
    # 180, so the credit survives the 12th of October and lapses on the 13th.
    LAST_GOOD_DAY = "2026-10-12"
    THE_DAY_IT_LAPSES = "2026-10-13"
    # The month that lapse date falls in — the one return that gives the
    # credit back, out of the several this journey asks.
    LAPSE_PERIOD = "2026-10"
    IGST_ON_THE_PURCHASE = Decimal("81000.00")

    @pytest.fixture()
    def unpaid(self, client, db_session, stub_openrouter):
        """One purchase never paid for, and one sale in the same month.

        The sale is what gives April a liability for the credit to be set off
        against, so the settlement this journey round-trips through the
        what-if endpoint is a real one rather than an arithmetic identity over
        zeroes.
        """
        client.headers.update({"Authorization": f"Bearer {register(client)}"})
        takes_the_pro_plan(db_session)
        purchase = upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        upload(
            client,
            stub_openrouter,
            text=SALES_TEXT,
            extraction=SALES_EXTRACTION,
            invoice_type="sales",
            name="ut-0101.txt",
        )
        # Nothing in this journey pays it. `paid_at` staying null is the whole
        # premise, and an extraction that had guessed one would make every
        # assertion below vacuous rather than failing.
        assert purchase["paid_at"] is None
        return client

    def _rule_37(self, client, as_of: str) -> dict:
        response = client.get("/api/v1/itc/rule37", params={"as_of": as_of})
        assert response.status_code == 200, response.text
        return response.json()

    def _summary(self, client, period: str, as_of: str) -> dict:
        response = client.get("/api/v1/itc", params={"period": period, "as_of": as_of})
        assert response.status_code == 200, response.text
        return response.json()

    def test_the_day_the_credit_lapses_is_the_day_the_screen_changes_its_mind(self, unpaid):
        # Day 180: still claimable, and already worth warning about. The two
        # lists are not two severities of the same row — `reversal` is money
        # this business has to give back and `approaching_amount` is money it
        # can still keep by paying the supplier, and a screen that added them
        # together would overstate the loss by the whole of the second.
        day_180 = self._rule_37(unpaid, self.LAST_GOOD_DAY)
        assert day_180["overdue"] == []
        (warned,) = day_180["approaching"]
        assert warned["invoice_number"] == "INV-2026-0042"
        assert warned["days_outstanding"] == 180
        assert warned["days_remaining"] == 0
        assert warned["overdue"] is False
        assert money(day_180["reversal"]["total"]) == Decimal("0")
        assert money(day_180["approaching_amount"]["total"]) == self.IGST_ON_THE_PURCHASE

        # Day 181, and the same invoice has moved across.
        day_181 = self._rule_37(unpaid, self.THE_DAY_IT_LAPSES)
        assert day_181["approaching"] == []
        (lapsed,) = day_181["overdue"]
        assert lapsed["invoice_id"] == warned["invoice_id"]
        assert lapsed["days_outstanding"] == 181
        assert lapsed["overdue"] is True
        assert money(day_181["reversal"]["total"]) == self.IGST_ON_THE_PURCHASE
        assert money(day_181["approaching_amount"]["total"]) == Decimal("0")

    def test_the_standing_exposure_is_charged_to_one_return_and_not_the_rest(self, unpaid):
        """The claim no single period's response can support on its own.

        Asked of eight months in a row — the month the credit was claimed in,
        the month it lapsed in, and the six in between and after — exactly one
        return may carry the reversal, and it has to be the month the clock ran
        out rather than the month the invoice belongs to.
        """
        standing = money(
            self._rule_37(unpaid, self.THE_DAY_IT_LAPSES)["reversal"]["total"]
        )
        assert standing == self.IGST_ON_THE_PURCHASE

        months = [f"2026-{month:02d}" for month in range(4, 13)]
        charged = {
            period: money(
                self._summary(unpaid, period, self.THE_DAY_IT_LAPSES)["rule_37_reversal"][
                    "total"
                ]
            )
            for period in months
        }

        assert charged[self.LAPSE_PERIOD] == standing
        # Including PERIOD itself. April is the month that *claimed* the
        # credit, which makes it the plausible wrong answer rather than an
        # arbitrary one: the reversal belongs to the month the payment window
        # closed, not to the month the purchase was made.
        assert charged[PERIOD] == Decimal("0")
        assert sum(charged.values()) == standing

    def test_the_reversal_a_return_declares_is_the_credit_it_stops_claiming(self, unpaid):
        # Table 4(B) and table 4(C) of the same return. The reversal is
        # declared, and the net credit is what is left after it — a 3B that
        # showed the reversal in 4(B) and went on claiming the credit in 4(C)
        # is arithmetically inconsistent in the way the portal itself rejects.
        lapsed = self._summary(unpaid, self.LAPSE_PERIOD, self.THE_DAY_IT_LAPSES)
        assert money(lapsed["rule_37_reversal"]["total"]) == self.IGST_ON_THE_PURCHASE
        assert money(lapsed["total_reversal"]["total"]) == self.IGST_ON_THE_PURCHASE
        assert money(lapsed["net_available"]["total"]) == Decimal("0")

    def test_the_what_if_screen_and_the_books_are_one_settlement(self, unpaid):
        """``/itc/set-off`` reads no database, which is what makes this worth asking.

        It settles whatever the caller sends, so it is the one money endpoint
        in the product whose answer nothing else in a response can contradict.
        Fed the two figures this same API publishes for the period — the credit
        after every reversal, and the output tax — it has to reproduce the
        settlement that API published alongside them. Anything else means the
        screen a CA tries a what-if on and the return the business files are
        applying credit in two different orders, and the disagreement would
        first be noticed as cash that had already been paid.
        """
        summary = self._summary(unpaid, PERIOD, self.THE_DAY_IT_LAPSES)
        heads = ("igst", "cgst", "sgst", "cess")

        response = unpaid.post(
            "/api/v1/itc/set-off",
            json={f"credit_{head}": summary["net_available"][head] for head in heads}
            | {f"liability_{head}": summary["output_tax"][head] for head in heads},
        )
        assert response.status_code == 200, response.text

        # Compared whole rather than head by head. The steps are the part a
        # user reads as an explanation — "IGST credit paid your CGST" — and a
        # settlement that reached the same cash figure by a different order
        # would be a different answer to the question that was asked.
        assert response.json() == summary["set_off"]

        # And the settlement is a real one: IGST credit crossing into both
        # halves of an intra-state liability is the case the statutory order
        # exists for, so this is not an identity over zeroes.
        assert money(summary["output_tax"]["total"]) == Decimal("36000.00")
        assert money(summary["set_off"]["credit_used"]["total"]) == Decimal("36000.00")
        assert money(summary["set_off"]["total_cash"]) == Decimal("0")


# ---------------------------------------------------------------------------
# The credit a supplier took back
# ---------------------------------------------------------------------------

def portal_2b_with_a_credit_note(*, taxable: float, igst: float) -> bytes:
    """April's 2B, where the supplier also filed a credit note against it.

    A note in ``cdnr`` states its figures positive like every other document
    the portal writes; ``typ`` is the only thing that says the money moves the
    other way. It is issued in the same month as the invoice it corrects,
    which is the ordinary case — a short-shipped line credited back before the
    period closed.
    """
    payload = json.loads(portal_2b().decode())
    payload["data"]["docdata"]["cdnr"] = [
        {
            "ctin": SUPPLIER_GSTIN_OTHER_STATE,
            "trdnm": "Northwind Supplies",
            "nt": [
                {
                    "nt_num": "CN-2026-0009",
                    "nt_dt": "28-04-2026",
                    "typ": "C",
                    "val": taxable + igst,
                    "items": [{"rt": 18, "txval": taxable, "igst": igst}],
                }
            ],
        }
    ]
    return json.dumps(payload).encode()


class TestASupplierWhoCreditedPartOfWhatTheyBilled:
    """One credit note, from the portal's file to the figure on the return.

    Both ends of this are tested and the middle is not. ``test_gstr2b.py``
    reads the note out of ``cdnr``, ``test_reconciliation.py`` asserts it comes
    off ``itc_eligible``, and ``test_itc.py`` asserts the pool is capped at
    whatever the run found eligible. Nothing joins them up, and a note that
    reversed the credit in the run while the return went on declaring the full
    invoice would pass all three: the reconciliation screen would be right,
    and the business would over-claim ₹9,000 on the strength of it.

    Over-claimed ITC is recovered with interest under s.50, so the figure that
    matters is the one in 4(A) of the 3B — not the one in the run's report.
    """

    NOTE_TAXABLE = 50000.00
    NOTE_IGST = 9000.00

    @pytest.fixture()
    def credited(self, client, db_session, stub_openrouter):
        """The purchase booked, the 2B imported with the note, reconciled."""
        client.headers.update({"Authorization": f"Bearer {register(client)}"})
        takes_the_pro_plan(db_session)
        upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        import_2b(
            client,
            portal_2b_with_a_credit_note(taxable=self.NOTE_TAXABLE, igst=self.NOTE_IGST),
        )
        return client, reconcile(client, PERIOD)

    def test_the_note_is_reported_without_being_counted_as_a_missing_invoice(self, credited):
        """A note is not an invoice the supplier failed to declare.

        It arrives in the same file, against the same supplier, and the one
        thing it must not do is read as a document the books are short of —
        that would send a user chasing a supplier who has done nothing wrong.
        """
        client, run = credited

        assert run["matched_count"] == 1
        assert run["missing_in_2b_count"] == 0
        assert run["mismatched_count"] == 0

        report = client.get(f"/api/v1/reconciliation/{run['id']}").json()["report"]
        assert money(report["credit_notes"]) == money(self.NOTE_IGST)

    def test_the_credit_the_itc_screen_offers_is_net_of_the_note(self, credited):
        client, _ = credited

        itc = client.get("/api/v1/itc", params={"period": PERIOD}).json()
        assert itc["reconciled"] is True
        # ₹81,000 billed, ₹9,000 credited back.
        assert money(itc["available"]["igst"]) == Decimal("72000.00")

    def test_the_return_declares_the_net_figure_and_not_the_invoice(self, credited):
        """The assertion the seam exists for, in the field that is filed."""
        client, _ = credited

        document = client.get("/api/v1/filing/gstr3b", params={"period": PERIOD}).json()[
            "document"
        ]
        other_itc = next(
            row for row in document["itc_elg"]["itc_avl"] if row["ty"] == "OTH"
        )
        assert money(other_itc["iamt"]) == Decimal("72000.00")
        assert money(document["itc_elg"]["itc_net"]["iamt"]) == Decimal("72000.00")

    def test_the_books_still_hold_the_invoice_at_what_it_was_billed_at(self, credited):
        """The note is the supplier's document, not a correction to ours.

        Netting it into the stored invoice would lose the fact that ₹81,000
        was charged and ₹9,000 credited — which is what the purchase register
        has to show, and what an assessing officer compares against the return.
        """
        client, _ = credited

        (invoice,) = client.get("/api/v1/invoices").json()["items"]
        assert money(invoice["igst"]) == Decimal("81000.00")

        dashboard = client.get("/api/v1/dashboard", params={"period": PERIOD}).json()
        assert money(dashboard["purchase"]["igst"]) == Decimal("81000.00")


class TestAPurchaseRemovedAfterItWasReconciled:
    """M20: a delete has to reach every screen that counted the invoice, and no
    record that was already made from it.

    The later run is what the books say now; the earlier run is what they said
    when it ran, and a reconciliation report a business has already shown its
    accountant cannot change underneath them.
    """

    @pytest.fixture()
    def reconciled(self, signed_in, db_session, stub_openrouter):
        takes_the_pro_plan(db_session)
        purchase = upload(
            signed_in,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        import_2b(signed_in, portal_2b())
        first = reconcile(signed_in, PERIOD)
        assert first["matched_count"] == 1
        response = signed_in.delete(f"/api/v1/invoices/{purchase['id']}")
        assert response.status_code == 204
        return signed_in, first

    def test_the_next_run_reports_the_portal_invoice_missing_from_the_books(self, reconciled):
        client, _ = reconciled
        second = reconcile(client, PERIOD)
        assert second["matched_count"] == 0
        assert second["missing_in_books_count"] == 1
        assert money(second["itc_claimed"]) == Decimal("0.00")

    def test_the_earlier_run_is_left_as_it_was(self, reconciled):
        client, first = reconciled
        reconcile(client, PERIOD)
        again = client.get(f"/api/v1/reconciliation/{first['id']}")
        assert again.status_code == 200
        assert again.json()["matched_count"] == 1
        assert money(again.json()["itc_claimed"]) == Decimal("81000.00")

    def test_the_return_stops_claiming_its_credit(self, reconciled):
        client, _ = reconciled
        document = client.get("/api/v1/filing/gstr3b", params={"period": PERIOD}).json()["document"]
        assert money(document["itc_elg"]["itc_net"]["iamt"]) == Decimal("0.00")
        dashboard = client.get("/api/v1/dashboard", params={"period": PERIOD}).json()
        assert money(dashboard["purchase"]["igst"]) == Decimal("0.00")


class TestABusinessRemovedFromTheDatabase:
    """M20: deleting a business row takes every row it owns with it.

    There is no endpoint for this; it is what an operator erasing a tenant
    runs, and the database's ``ON DELETE CASCADE`` is the only thing doing it.
    The tables are found by their ``business_id`` column rather than listed,
    so a table added later is covered without anyone remembering to add it.
    """

    def test_every_owned_row_goes_and_the_neighbour_keeps_everything(
        self, client, db_session, stub_openrouter, other_tenant
    ):
        from datetime import date

        from sqlalchemy import inspect, text

        from app.models.alert import Alert, AlertType
        from app.models.business import Business
        from app.models.user import User

        client.headers.update({"Authorization": f"Bearer {register(client)}"})
        takes_the_pro_plan(db_session)
        upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        upload(
            client,
            stub_openrouter,
            text=SALES_TEXT,
            extraction=SALES_EXTRACTION,
            invoice_type="sales",
            name="sale-0101.txt",
        )
        import_2b(client, portal_2b())
        reconcile(client, PERIOD)
        filed = client.post(
            "/api/v1/filing/gstr1/filed", json={"period": PERIOD, "filed_on": "2026-05-10"}
        )
        assert filed.status_code == 201, filed.text

        gone = db_session.query(Business).filter_by(gstin=BUSINESS_GSTIN).one()
        gone_id = gone.id
        neighbour = db_session.query(Business).filter(Business.id != gone_id).one()
        neighbour_id = neighbour.id
        gone_user = db_session.query(User).filter_by(business_id=gone_id).one()
        neighbour_user = db_session.query(User).filter_by(business_id=neighbour_id).one()
        db_session.add_all(
            [
                Alert(
                    business_id=gone_id,
                    alert_type=AlertType.FILING_DEADLINE,
                    title="GSTR-3B due",
                    message="Due on the 20th.",
                    due_date=date(2026, 5, 20),
                ),
                # Both directions: their login into the neighbour, and the
                # neighbour's login into theirs.
                BusinessMembership(
                    user_id=gone_user.id, business_id=neighbour_id, role=MembershipRole.VIEWER
                ),
                BusinessMembership(
                    user_id=neighbour_user.id, business_id=gone_id, role=MembershipRole.VIEWER
                ),
            ]
        )
        db_session.commit()

        inspector = inspect(db_session.bind)
        owned = [
            table
            for table in inspector.get_table_names()
            if any(column["name"] == "business_id" for column in inspector.get_columns(table))
        ]

        def count(table: str, op: str, business_id: int) -> int:
            return db_session.execute(
                text(f"SELECT count(*) FROM {table} WHERE business_id {op} :b"),
                {"b": business_id},
            ).scalar_one()

        before = {table: count(table, "=", gone_id) for table in owned}
        # The journey has to have written the tables that matter, or "all
        # zero afterwards" proves nothing.
        for table in ("invoices", "suppliers", "reconciliation_runs", "gstr_returns",
                      "alerts", "subscriptions", "users", "business_memberships"):
            assert before[table] > 0, table
        neighbour_rows = {table: count(table, "<>", gone_id) for table in owned}

        db_session.execute(text("DELETE FROM businesses WHERE id = :b"), {"b": gone_id})
        db_session.commit()
        db_session.expire_all()

        assert {table: count(table, "=", gone_id) for table in owned} == dict.fromkeys(owned, 0)
        # The neighbour loses exactly one row: the membership the erased
        # business's login held into it, which went with that login.
        expected = {**neighbour_rows}
        expected["business_memberships"] -= 1
        assert {table: count(table, "<>", gone_id) for table in owned} == expected
        assert db_session.get(User, neighbour_user.id) is not None


class TestABusinessPaysAndThenCancels:
    """M20: the paywall, the payment and the cancellation as one journey.

    ``test_subscriptions`` drives each step on its own and every other journey
    here stands in for payment with ``make_paid``; this is the handoff between
    them — the subscription the payment writes is the one the paywall and the
    upload allowance read.
    """

    def test_the_paid_features_open_and_close_with_the_subscription(
        self, signed_in, db_session
    ):
        from unittest.mock import patch

        from app.models.business import Business
        from app.services import razorpay_client
        from tests.test_subscriptions import _paid_order

        client = signed_in
        business_id = db_session.query(Business).filter_by(gstin=BUSINESS_GSTIN).one().id

        def paywalled() -> int:
            return client.post("/api/v1/reconciliation/run", json={"period": PERIOD}).status_code

        def allowance() -> int:
            (row,) = client.get("/api/v1/subscriptions/usage").json()["usage"]
            return row["limit"]

        assert paywalled() == 403
        assert allowance() == 50

        payment = {
            "razorpay_order_id": "order_test",
            "razorpay_payment_id": "pay_test",
            "razorpay_signature": "sig",
            "tier": "pro",
        }
        with (
            patch.object(razorpay_client, "verify_payment_signature", return_value=True),
            patch.object(
                razorpay_client, "fetch_order", return_value=_paid_order(business_id, "pro")
            ),
        ):
            paid = client.post("/api/v1/subscriptions/verify-payment", json=payment)
            assert paid.status_code == 200, paid.text
            # The checkout callback can fire twice; the second must not buy a
            # second month.
            replay = client.post("/api/v1/subscriptions/verify-payment", json=payment)
        assert replay.status_code == 200
        assert replay.json()["current_period_end"] == paid.json()["current_period_end"]

        # Past the paywall: refused for want of a 2B now, not for want of a plan.
        assert paywalled() == 409
        assert allowance() == 0  # unlimited
        assert client.get("/api/v1/subscriptions/current").json()["tier"] == "pro"

        cancelled = client.post("/api/v1/subscriptions/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert paywalled() == 403
        assert allowance() == 50


class _FakeRazorpay:
    """Razorpay as far as checkout sees it: an order is remembered as it was
    created — receipt and amount from create-order — and comes back paid.

    So the journeys below hand the order id from create-order to
    verify-payment the way the browser does, and what verify checks is what
    create-order actually wrote, not a fixture built to match it.
    """

    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.fetches = 0

    def create_order(self, amount_paise, currency="INR", receipt=None):
        order_id = f"order_e2e{len(self.orders) + 1}"
        self.orders[order_id] = {
            "id": order_id,
            "receipt": receipt,
            "amount": amount_paise,
            "amount_paid": amount_paise,
            "currency": currency,
            "status": "paid",
        }
        return {"id": order_id, "amount": amount_paise, "currency": currency}

    def fetch_order(self, order_id):
        self.fetches += 1
        return self.orders.get(order_id)

    def patches(self):
        from contextlib import ExitStack
        from unittest.mock import patch

        from app.services import razorpay_client

        stack = ExitStack()
        stack.enter_context(patch.object(razorpay_client, "is_configured", return_value=True))
        stack.enter_context(
            patch.object(razorpay_client, "verify_payment_signature", return_value=True)
        )
        stack.enter_context(
            patch.object(razorpay_client, "create_order", side_effect=self.create_order)
        )
        stack.enter_context(
            patch.object(razorpay_client, "fetch_order", side_effect=self.fetch_order)
        )
        return stack


class TestABusinessChoosingBetweenPlans:
    """P21 M20: this pass's billing fixes as the journeys that found them.

    A business on Free opens checkout for SMB and for CA before paying either
    (two tabs, or a change of mind). Both orders are legitimate when opened, so
    create-order's downgrade guard cannot see the problem; what the business
    then pays, in what order, decides what it ends up with.
    """

    @staticmethod
    def _order(client, tier: str):
        return client.post("/api/v1/subscriptions/create-order", json={"tier": tier})

    @staticmethod
    def _pay(client, order_id: str, tier: str, payment_id: str):
        return client.post(
            "/api/v1/subscriptions/verify-payment",
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": "sig",
                "tier": tier,
            },
        )

    def test_two_tabs_then_the_lower_plan_is_refused_and_nothing_is_lost(self, signed_in):
        client = signed_in
        razorpay = _FakeRazorpay()

        def paywalled() -> int:
            return client.post("/api/v1/reconciliation/run", json={"period": PERIOD}).status_code

        with razorpay.patches():
            smb = self._order(client, "pro")
            ca = self._order(client, "enterprise")
            assert smb.status_code == ca.status_code == 200, (smb.text, ca.text)

            # CA is paid first: the plan the business wanted.
            paid = self._pay(client, ca.json()["order_id"], "enterprise", "pay_e2e_ca")
            assert paid.status_code == 200, paid.text
            assert paid.json()["tier"] == "enterprise"
            ca_ends = paid.json()["current_period_end"]
            assert paywalled() == 409  # past the paywall, short of a 2B

            # Then the stale SMB tab is paid too. The money is taken, but
            # applying it would end the CA plan at once: the CA plan stays.
            stale = self._pay(client, smb.json()["order_id"], "pro", "pay_e2e_smb")
            assert stale.status_code == 200, stale.text
            assert stale.json()["tier"] == "enterprise"
            assert stale.json()["current_period_end"] == ca_ends

            # And it is not applied on a retry either.
            retried = self._pay(client, smb.json()["order_id"], "pro", "pay_e2e_smb")
            assert retried.json()["tier"] == "enterprise"

            # Opening SMB checkout now is refused before any money moves.
            refused = self._order(client, "pro")
            assert refused.status_code == 409
            assert "CA plan is active until" in refused.json()["detail"]
            assert len(razorpay.orders) == 2  # no order was created for it

        current = client.get("/api/v1/subscriptions/current").json()
        assert current["tier"] == "enterprise"
        assert current["current_period_end"] == ca_ends
        assert paywalled() == 409

    def test_the_lower_plan_first_then_the_upgrade_goes_through(self, signed_in):
        client = signed_in
        razorpay = _FakeRazorpay()
        with razorpay.patches():
            smb = self._order(client, "pro").json()["order_id"]
            ca = self._order(client, "enterprise").json()["order_id"]
            assert self._pay(client, smb, "pro", "pay_e2e_smb").json()["tier"] == "pro"
            upgraded = self._pay(client, ca, "enterprise", "pay_e2e_ca")
        assert upgraded.status_code == 200, upgraded.text
        assert upgraded.json()["tier"] == "enterprise"

    def test_one_order_paid_twice_buys_one_period(self, signed_in):
        client = signed_in
        razorpay = _FakeRazorpay()
        with razorpay.patches():
            order_id = self._order(client, "pro").json()["order_id"]
            first = self._pay(client, order_id, "pro", "pay_e2e_one")
            assert first.status_code == 200, first.text
            ends = first.json()["current_period_end"]

            # The checkout callback firing again is the same payment: answered
            # from the ledger, without asking Razorpay.
            fetches = razorpay.fetches
            again = self._pay(client, order_id, "pro", "pay_e2e_one")
            assert again.status_code == 200
            assert again.json()["current_period_end"] == ends
            assert razorpay.fetches == fetches

            # A second, different payment captured on the same order is a
            # double charge, not a second month.
            double = self._pay(client, order_id, "pro", "pay_e2e_two")
            assert double.status_code == 409
            assert "already been paid for" in double.json()["detail"]

            # A renewal is a new order, and does extend the period.
            renewal = self._order(client, "pro").json()["order_id"]
            renewed = self._pay(client, renewal, "pro", "pay_e2e_renew")
        assert renewed.status_code == 200, renewed.text
        assert renewed.json()["current_period_end"] > ends
        assert client.get("/api/v1/subscriptions/current").json()["current_period_end"] == (
            renewed.json()["current_period_end"]
        )


class _FakeGemini:
    """Gemini as the advisor sees it: records every conversation it is sent
    and answers from a script, one entry per call. An entry is a status code,
    an answer string, or ``None`` for a 200 with no text."""

    def __init__(self, *script):
        self.script = list(script)
        self.sent: list[dict] = []

    def _next(self, request_json):
        self.sent.append(request_json)
        return self.script.pop(0) if self.script else "OK."

    def patches(self):
        from contextlib import ExitStack
        from unittest.mock import patch

        import httpx

        fake = self

        def sse(answer):
            if answer is None:
                return b'data: {"candidates": [{"finishReason": "MAX_TOKENS"}]}\n\n'
            words = [w + " " for w in answer.split(" ")]
            return "".join(
                "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": w}]}}]})
                + "\n\n"
                for w in words
            ).encode()

        class Stream:
            def __init__(self, status_code, body):
                self.status_code, self._body = status_code, body

            async def aiter_lines(self):
                for line in self._body.decode().splitlines():
                    yield line

            async def aread(self):
                return self._body

            async def aclose(self):
                pass

        async def send(client, request, *, stream=False):
            answer = fake._next(json.loads(request.content))
            if isinstance(answer, int):
                return Stream(answer, b'{"error": {}}')
            return Stream(200, sse(answer))

        stack = ExitStack()
        stack.enter_context(patch("app.routers.advisor._get_api_key", return_value="k"))
        stack.enter_context(patch.object(httpx.AsyncClient, "send", new=send))
        return stack


def _ask_stream(client, message, history):
    """One question the way the browser asks it; the answer and the events."""
    response = client.post(
        "/api/v1/advisor/ask/stream", json={"message": message, "history": history}
    )
    assert response.status_code == 200, response.text
    events = [
        json.loads(line[6:]) for line in response.text.split("\n") if line.startswith("data: ")
    ]
    return "".join(e.get("t", "") for e in events).strip(), events


class TestAConversationWithTheAdvisor:
    """P22 M20: a conversation as the chat keeps it — each answer appended to
    the history the next question carries — through the failures this pass
    fixed: an unanswered question, an empty bubble, a refusal, and a model
    that no longer exists."""

    def test_a_conversation_survives_a_failed_turn_and_reaches_the_model_clean(
        self, client
    ):
        gemini = _FakeGemini("ITC is input tax credit.", 503, 503, 503, "Yes, within limits.")
        history: list[dict] = []
        with gemini.patches():
            answer, events = _ask_stream(client, "What is ITC?", history)
            assert answer == "ITC is input tax credit." and events[-1] == {"done": True}
            history += [{"role": "user", "text": "What is ITC?"},
                        {"role": "model", "text": answer}]

            # Every model overloaded: the widget keeps the question, no reply.
            _, events = _ask_stream(client, "Can I claim it on a car?", history)
            assert "overloaded" in events[-1]["error"]
            history += [{"role": "user", "text": "Can I claim it on a car?"},
                        {"role": "model", "text": ""}]  # the bubble left empty

            answer, events = _ask_stream(client, "For a taxi business?", history)
        assert answer == "Yes, within limits."

        last = gemini.sent[-1]["contents"]
        roles = [turn["role"] for turn in last]
        assert roles == ["user", "model", "user"]  # alternating, no blank turn
        assert last[-1]["parts"][0]["text"] == (
            "Can I claim it on a car?\n\nFor a taxi business?"
        )
        assert "systemInstruction" in gemini.sent[-1]

    def test_the_plain_and_streamed_answers_agree_on_a_refusal(self, client):
        blocked = None  # a 200 with no text, from every model
        gemini = _FakeGemini(blocked, blocked, blocked)
        with gemini.patches():
            _, events = _ask_stream(client, "Something odd", [])
        from app.routers import advisor

        assert events == [{"error": advisor._NO_ANSWER}]

    def test_a_retired_model_is_skipped_mid_conversation(self, client, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "gemini_models", "gemini-gone,gemini-here")
        gemini = _FakeGemini(404, "18% on laptops.")
        with gemini.patches():
            answer, events = _ask_stream(client, "Rate on laptops?", [])
        assert answer == "18% on laptops." and events[-1] == {"done": True}
        assert len(gemini.sent) == 2


class TestABusinessThatGetsEachStepWrongFirst:
    """P16 M20: the error path as one journey.

    Every refusal below is followed by the corrected request succeeding, and
    each has to say what to do — the journey a first-time user actually takes
    is mostly this one. A step that is refused with nothing actionable, or that
    leaves state behind so the corrected request then fails too, breaks it.
    """

    def test_every_refusal_is_recoverable(self, client, db_session, stub_openrouter):
        def detail(response) -> str:
            body = response.json()
            assert body["error"]["message"], body  # always something to show
            return body["error"]["message"]

        # --- Sign-up with a mistyped GSTIN, then the right one -------------
        bad = client.post(
            "/api/v1/auth/register",
            json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
                "gstin": BUSINESS_GSTIN[:-1] + ("A" if BUSINESS_GSTIN[-1] != "A" else "B"),
                "legal_name": "Umang Traders Private Limited",
            },
        )
        assert bad.status_code == 422
        assert "gstin" in detail(bad).lower()
        token = register(client)  # the refused attempt left nothing in the way

        # --- Signing up twice is refused; signing in works ----------------
        again = client.post(
            "/api/v1/auth/register",
            json={
                "email": TEST_EMAIL,
                "password": TEST_PASSWORD,
                "gstin": BUSINESS_GSTIN,
                "legal_name": "Umang Traders Private Limited",
            },
        )
        assert again.status_code in (400, 409)
        detail(again)
        wrong = client.post(
            "/api/v1/auth/login", data={"username": TEST_EMAIL, "password": "not-the-password"}
        )
        assert wrong.status_code == 401
        assert detail(wrong) == "Incorrect email or password"
        client.headers.update({"Authorization": f"Bearer {token}"})

        # --- A file that is not an invoice, then the invoice, then it twice --
        exe = client.post(
            "/api/v1/invoices/upload",
            files={"file": ("bill.exe", b"MZ\x90\x00", "application/x-msdownload")},
            data={"invoice_type": "purchase"},
        )
        assert exe.status_code == 415
        assert "Accepted:" in detail(exe)
        purchase = upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        twice = client.post(
            "/api/v1/invoices/upload",
            files={
                "file": ("northwind-0042.txt", io.BytesIO(PURCHASE_TEXT.encode()), "text/plain")
            },
            data={"invoice_type": "purchase"},
        )
        assert twice.status_code == 409
        assert str(purchase["id"]) in detail(twice)

        # --- A paid feature on the free plan, then after paying ------------
        assert client.post("/api/v1/reconciliation/run", json={"period": PERIOD}).status_code == 403
        takes_the_pro_plan(db_session)
        no_2b = client.post("/api/v1/reconciliation/run", json={"period": PERIOD})
        assert no_2b.status_code == 409
        assert "Import one" in detail(no_2b)
        import_2b(client, portal_2b())
        assert reconcile(client, PERIOD)["matched_count"] == 1

        # --- A filing dated in the future, then the real date --------------
        future = client.post(
            "/api/v1/filing/gstr1/filed", json={"period": PERIOD, "filed_on": "2099-01-01"}
        )
        assert future.status_code == 422
        detail(future)
        filed = client.post(
            "/api/v1/filing/gstr1/filed", json={"period": PERIOD, "filed_on": "2026-05-10"}
        )
        assert filed.status_code == 201, filed.text

        # --- Deleting twice: the second says it is already gone ------------
        assert client.delete(f"/api/v1/invoices/{purchase['id']}").status_code == 204
        gone = client.delete(f"/api/v1/invoices/{purchase['id']}")
        assert gone.status_code == 404
        assert "deleted" in detail(gone).lower()


class TestACAsLinkBringsInAClient:
    """P17 M20: the referral journey, end to end — share, visit, sign up, see it.

    Each step is a different caller: the CA signed in, an anonymous visitor,
    the same visitor registering, then the CA again. The handoff under test is
    that the sign-up is credited to the visit the link recorded.
    """

    def test_the_ca_sees_the_visit_and_the_signup(self, client):
        ca_token = register(client)
        ca = {"Authorization": f"Bearer {ca_token}"}

        code = client.get("/api/v1/referrals/my-code", headers=ca).json()["referral_code"]
        assert code.startswith("CA-")

        # An anonymous visitor follows the link. A second visit is not a
        # second count, and a made-up code is refused rather than recorded.
        assert client.post("/api/v1/referrals/track", json={"referral_code": code}).json() == {
            "tracked": True
        }
        assert client.post("/api/v1/referrals/track", json={"referral_code": code}).json()[
            "reason"
        ] == "already_tracked"
        assert client.post(
            "/api/v1/referrals/track", json={"referral_code": "CA-nobody"}
        ).json()["reason"] == "unknown_code"

        # The visitor becomes a client.
        joined = client.post(
            "/api/v1/auth/register",
            json={
                "email": "client@example.com",
                "password": "a-long-passphrase",
                "gstin": SUPPLIER_GSTIN_SAME_STATE,
                "legal_name": "Mehta Electricals",
            },
        )
        assert joined.status_code == 201, joined.text

        stats = client.get("/api/v1/referrals/my-stats", headers=ca).json()
        assert stats == {"referral_code": code, "total_visits": 1, "conversions": 1}
        leaders = client.get("/api/v1/referrals/leaderboard").json()["leaders"]
        assert [leader["referral_count"] for leader in leaders] == [1]

        # The new client's own link starts from nothing.
        newcomer = {"Authorization": f"Bearer {joined.json()['access_token']}"}
        assert client.get("/api/v1/referrals/my-stats", headers=newcomer).json()[
            "total_visits"
        ] == 0


class TestASupplierRenumbersLastMonthsInvoice:
    """P17 M20: a supplier corrects an invoice from March and the correction
    carries a new number. April's GSTR-2B lists it under ``b2ba`` with the
    original in ``oinum``. The business's books still hold the March number.

    Before amendments were matched, April reported the correction as missing
    from the books and March's invoice stayed missing from 2B — a supplier
    chased for a filing they had made.
    """

    def test_the_correction_is_matched_to_the_booked_original(
        self, signed_in, db_session, stub_openrouter
    ):
        client = signed_in
        takes_the_pro_plan(db_session)
        march = dict(PURCHASE_EXTRACTION, invoice_date="2026-03-15")
        booked = upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT.replace("15/04/2026", "15/03/2026"),
            extraction=march,
            invoice_type="purchase",
            name="northwind-march.txt",
        )
        assert booked["period"] == "2026-03"

        statement = {
            "data": {
                "rtnprd": "042026",
                "docdata": {
                    "b2ba": [
                        {
                            "ctin": SUPPLIER_GSTIN_OTHER_STATE,
                            "inv": [
                                {
                                    "oinum": "INV-2026-0042",
                                    "oidt": "15-03-2026",
                                    "inum": "INV-2026-0042-R1",
                                    "dt": "15-04-2026",
                                    "val": 531000,
                                    "itcavl": "Y",
                                    "items": [{"rt": 18, "txval": 450000, "igst": 81000}],
                                }
                            ],
                        }
                    ]
                },
            }
        }
        import_2b(client, json.dumps(statement).encode())
        run = reconcile(client, PERIOD)
        assert run["missing_in_books_count"] == 0

        findings = client.get(f"/api/v1/reconciliation/{run['id']}").json()["report"]["findings"]
        (finding,) = findings
        assert finding["category"] == "matched"
        assert finding["matched_on"] == "amended"
        assert "INV-2026-0042-R1" in finding["note"]
        # March counted this credit; April must not count it again.
        assert money(run["itc_claimed"]) == Decimal("0.00")


class TestALockedPdfThenTheUnlockedCopy:
    """P17 M20: a business uploads a password-protected PDF, is told why it
    could not be read, and uploads the unlocked copy. The locked attempt must
    not block the real one, and the real one must read normally."""

    def test_the_user_is_told_and_the_unlocked_copy_goes_through(self, signed_in, db_session):
        from app.models.invoice import Invoice
        from app.services.invoice_parser import PASSWORD_PROTECTED_WARNING
        from tests.test_invoices import _pdf_locked

        client = signed_in

        def send(content, name):
            return client.post(
                "/api/v1/invoices/upload",
                files={"file": (name, content, "application/pdf")},
                data={"invoice_type": "purchase"},
            )

        locked = send(_pdf_locked("secret"), "bill.pdf")
        assert locked.status_code == 201
        locked_id = locked.json()["invoice"]["id"]
        assert db_session.get(Invoice, locked_id).extraction["warnings"][0] == (
            PASSWORD_PROTECTED_WARNING
        )

        # Same document, saved again without the password: different bytes, so
        # not the "already uploaded" refusal, and readable this time.
        unlocked = send(_pdf_locked(""), "bill-unlocked.pdf")
        assert unlocked.status_code == 201, unlocked.text
        row = db_session.get(Invoice, unlocked.json()["invoice"]["id"])
        assert "LOCK-1" in (row.raw_text or "")

        # The unreadable attempt is cleared away like any mistaken upload.
        assert client.delete(f"/api/v1/invoices/{locked_id}").status_code == 204
        listed = [item["id"] for item in client.get("/api/v1/invoices").json()["items"]]
        assert listed == [row.id]


class TestASupplierCorrectionArrivesAsCsv:
    """P18 M20: the same renumbered-amendment journey as above, but the 2B
    comes as the portal's CSV export, where the original number sits in an
    "Original Invoice number" column. That column was not read until P18."""

    def test_the_csv_correction_matches_the_booked_original(
        self, signed_in, db_session, stub_openrouter
    ):
        client = signed_in
        takes_the_pro_plan(db_session)
        upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT.replace("15/04/2026", "15/03/2026"),
            extraction=dict(PURCHASE_EXTRACTION, invoice_date="2026-03-15"),
            invoice_type="purchase",
            name="northwind-march.txt",
        )
        csv_body = (
            "GSTIN of supplier,Trade/Legal name,Original Invoice number,Original Invoice date,"
            "Invoice number,Invoice Date,Invoice Value,Place of supply,Rate,Taxable Value,"
            "Integrated Tax\n"
            f"{SUPPLIER_GSTIN_OTHER_STATE},Northwind,INV-2026-0042,15/03/2026,"
            "INV-2026-0042-R1,15/04/2026,531000,27,18,450000,81000\n"
        ).encode()
        imported = client.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={"file": ("gstr2b-042026.csv", csv_body, "text/csv")},
            data={"period": PERIOD},
        )
        assert imported.status_code == 201, imported.text

        run = reconcile(client, PERIOD)
        assert run["missing_in_books_count"] == 0
        report = client.get(f"/api/v1/reconciliation/{run['id']}").json()["report"]
        (finding,) = report["findings"]
        assert (finding["category"], finding["matched_on"]) == ("matched", "amended")


class TestAnUploadWhoseQueuedParseWasLost:
    """P18 M20: the broker loses the upload's parse task (Redis restarted
    between snapshots). Before P18 the invoice sat 'uploaded' for ever — out of
    the return and the credit pool, with nothing saying so. The hourly sweep
    now queues it again once the queue is empty, and it reaches the books."""

    def test_the_sweep_brings_it_into_the_return(
        self, signed_in, db_session, stub_openrouter, monkeypatch
    ):
        from datetime import UTC, datetime, timedelta
        from types import SimpleNamespace

        from sqlalchemy import update

        from app.core.config import settings
        from app.models.invoice import Invoice
        from app.tasks import invoice_tasks

        client = signed_in
        takes_the_pro_plan(db_session)

        # Queued with a working broker — and then the message is lost.
        monkeypatch.setattr(settings, "celery_enabled", True)
        monkeypatch.setattr(invoice_tasks.parse_invoice_task, "delay", lambda _id: None)
        stub_openrouter.update(PURCHASE_EXTRACTION)
        response = client.post(
            "/api/v1/invoices/upload",
            files={
                "file": ("northwind-0042.txt", io.BytesIO(PURCHASE_TEXT.encode()), "text/plain")
            },
            data={"invoice_type": "purchase"},
        )
        assert response.status_code == 201, response.text
        invoice_id = response.json()["invoice"]["id"]
        assert response.json()["invoice"]["status"] == "uploaded"

        def purchase_igst() -> Decimal:
            # The period's purchase register as the dashboard totals it: an
            # unread ('uploaded') invoice is not in it.
            dashboard = client.get("/api/v1/dashboard", params={"period": PERIOD}).json()
            return money(dashboard["purchase"]["igst"])

        # An hour later, nothing has moved it, and its credit is nowhere.
        db_session.execute(
            update(Invoice)
            .where(Invoice.id == invoice_id)
            .values(updated_at=datetime.now(UTC) - timedelta(hours=2))
        )
        db_session.commit()
        assert purchase_igst() == Decimal("0.00")

        # The sweep, with the queue drained: it requeues, and a worker parses.
        class _Handle:
            def __getattr__(self, name):
                return getattr(db_session, name)

            def close(self):
                pass

        monkeypatch.setattr(invoice_tasks, "SessionLocal", _Handle)
        monkeypatch.setattr(
            invoice_tasks.job_health,
            "queue_status",
            lambda: SimpleNamespace(reachable=True, depth=0),
        )
        monkeypatch.setattr(
            invoice_tasks.parse_invoice_task,
            "delay",
            lambda _id: invoice_tasks.parse_invoice_task(_id),
        )
        assert invoice_tasks.reap_stalled_parses_task()["requeued"] == 1

        db_session.expire_all()
        assert client.get(f"/api/v1/invoices/{invoice_id}").json()["status"] == "parsed"
        assert purchase_igst() == Decimal("81000.00")


class TestARecordedThreeBShowsWhatItDeclared:
    """P19 M20: a business whose period includes a reverse-charge sale records
    its GSTR-3B. The totals the filing screen shows beside the ARN must be the
    ones that 3B declared at 3.1(a) — not every sale's tax, which included tax
    the recipient pays."""

    def test_the_filed_totals_match_the_return(self, signed_in, db_session, stub_openrouter):
        from app.models.invoice import Invoice

        client = signed_in
        upload(
            client,
            stub_openrouter,
            text=SALES_TEXT,
            extraction=SALES_EXTRACTION,
            invoice_type="sales",
            name="sale-0101.txt",
        )
        rcm = upload(
            client,
            stub_openrouter,
            text=SALES_TEXT.replace("UT/2026/0101", "UT/2026/0102"),
            extraction=dict(SALES_EXTRACTION, invoice_number="UT/2026/0102"),
            invoice_type="sales",
            name="sale-0102-rcm.txt",
        )
        # The supply is under reverse charge: the recipient pays its tax.
        assert client.patch(
            f"/api/v1/invoices/{rcm['id']}", json={"reverse_charge": True}
        ).status_code == 200
        assert db_session.get(Invoice, rcm["id"]).reverse_charge is True

        preview = client.get("/api/v1/filing/gstr3b", params={"period": PERIOD}).json()
        declared = preview["document"]["sup_details"]["osup_det"]

        filed = client.post(
            "/api/v1/filing/gstr3b/filed", json={"period": PERIOD, "filed_on": "2026-05-18"}
        )
        assert filed.status_code == 201, filed.text
        record = filed.json()
        assert money(record["total_taxable_value"]) == money(declared["txval"]) == Decimal(
            "200000.00"
        )
        assert money(record["total_cgst"]) == money(declared["camt"]) == Decimal("18000.00")
        assert record["invoice_count"] == 2


class TestTheSameStatementUploadedTwice:
    """P19 M20: a user drops the same GSTR-2B file again. Every import is kept
    for assessments, but an identical one adds nothing, so nothing new is
    stored — and the period still reconciles against it."""

    def test_a_second_identical_upload_keeps_one_statement(
        self, signed_in, db_session, stub_openrouter
    ):
        from app.models.gstr_return import GSTRReturn, ReturnType

        client = signed_in
        takes_the_pro_plan(db_session)
        upload(
            client,
            stub_openrouter,
            text=PURCHASE_TEXT,
            extraction=PURCHASE_EXTRACTION,
            invoice_type="purchase",
            name="northwind-0042.txt",
        )
        first = import_2b(client, portal_2b())
        # The statement already on file: 200, not 201 — nothing was stored.
        second = import_2b(client, portal_2b(), expected=200)
        assert second["id"] == first["id"]
        assert second["unchanged"] is True and second["replaced_previous"] is False
        stored = db_session.query(GSTRReturn).filter_by(return_type=ReturnType.GSTR2B).count()
        assert stored == 1
        assert reconcile(client, PERIOD)["matched_count"] == 1


class TestAnHsnCodeFromTheInvoiceToTheReturn:
    """P20 M20: the model reads the tariff form printed on the invoice
    ('8504.40.90'). Before P20 an upload stored it cut to '8504.40.', which
    then went into the GSTR-1 HSN summary; the edit form already read it as
    digits. Upload, return, edit and refusal now follow one rule."""

    def test_the_printed_code_reaches_the_hsn_summary_as_digits(
        self, signed_in, db_session, stub_openrouter
    ):
        client = signed_in
        sale = upload(
            client,
            stub_openrouter,
            text=SALES_TEXT,
            extraction=dict(SALES_EXTRACTION, hsn_code="8504.40.90"),
            invoice_type="sales",
            name="sale-0101.txt",
        )
        assert sale["hsn_code"] == "85044090"

        document = client.get("/api/v1/filing/gstr1", params={"period": PERIOD}).json()["document"]
        codes = [row["hsn_sc"] for row in hsn_rows(document)]
        assert codes == ["85044090"]

        # The same rule on an edit: a labelled, dotted code is read as its
        # digits, and something that is not a code is refused with a reason.
        edited = client.patch(f"/api/v1/invoices/{sale['id']}", json={"hsn_code": "HSN: 8517.62"})
        assert edited.status_code == 200, edited.text
        assert edited.json()["hsn_code"] == "851762"
        refused = client.patch(f"/api/v1/invoices/{sale['id']}", json={"hsn_code": "N/A"})
        assert refused.status_code == 422
        assert "hsn_code: " in refused.json()["error"]["message"]
        assert "4 to 8 digits" in refused.json()["error"]["message"]
