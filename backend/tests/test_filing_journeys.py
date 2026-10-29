"""The half of the workflow that happens after the download.

``test_end_to_end.py`` drives the product up to the export and stops there,
which is where the user leaves for the portal. This file starts there — at the
one event GSTIndia cannot observe. Nothing in the API knows a return was filed
until the business says so, and almost everything the product does afterwards
turns on that one fact: the filing status screen, the deadline alerts, the late
fee, and whether tomorrow's sweep nags about a return that is already done.

Same rule as the other journey file: a step is an HTTP request, and each one
uses a period, an id or a figure that came out of the previous response, so
what is under test is the handoff rather than arithmetic ``test_filing.py`` and
``test_alerting.py`` already own.

**The one exception is the sweep.** It is the product's own step, not a user's
— Celery beat runs it nightly (see ``app/celery_app.py``) and there is no route
that triggers it, deliberately, because an endpoint that raises every tenant's
alerts is not a thing a tenant should be able to call. A journey about being
nagged and then left alone has to include it, so it is called directly and
marked at each call site.

**No hardcoded periods.** The filing status endpoint reports a window that
moves with the calendar, and the deadline alerts and s.16(4) sweep read the
same window. A period written into this file is one that eventually falls out
of it and takes these tests red for the date rather than for the code — so
every journey below asks the product which periods it is tracking and files one
of those.
"""
from __future__ import annotations

import io
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.business import Business
from app.services import alerting, gst_calendar
from app.services.filing import to_portal_period
from tests.conftest import (
    BUSINESS_GSTIN,
    SUPPLIER_GSTIN_OTHER_STATE,
    SUPPLIER_GSTIN_SAME_STATE,
    TEST_EMAIL,
    TEST_PASSWORD,
    make_paid,
)

# The ARN shape the portal issues: 15 characters of letters and digits.
ARN = "AA270426123456X"
CORRECTED_ARN = "AA270426999999Z"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def register(client, *, email=TEST_EMAIL, gstin=BUSINESS_GSTIN, name="Umang Traders") -> str:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "gstin": gstin,
            "legal_name": f"{name} Private Limited",
            "trade_name": name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def filing_status(client) -> list[dict]:
    response = client.get("/api/v1/filing/status")
    assert response.status_code == 200, response.text
    return response.json()["items"]


def standing(client, period: str, return_type: str) -> dict:
    """The one status line for a period and return type."""
    matches = [
        item
        for item in filing_status(client)
        if item["period"] == period and item["return_type"] == return_type
    ]
    assert len(matches) == 1, f"{return_type} for {period} appears {len(matches)} times"
    return matches[0]


def oldest_tracked_period(client) -> str:
    """The earliest period the status screen still reports on.

    Six periods back, so both its returns are months overdue whenever the suite
    runs — which is what makes the alert wording and ``filed_late`` assertions
    below stable rather than dependent on the day of the month.
    """
    items = filing_status(client)
    assert items, "the status endpoint reported no periods at all"
    return min(item["period"] for item in items)


def sale_in(period: str) -> tuple[str, dict]:
    """A Maharashtra-to-Maharashtra sale dated inside *period*.

    Day 15: the period has ended, so the date is in the past whenever this
    runs, and the invoice-date validator refuses anything dated after today.
    """
    invoice_date = f"{period}-15"
    number = f"UT/{period.replace('-', '')}/01"
    text = f"""\
UMANG TRADERS PRIVATE LIMITED
GSTIN: {BUSINESS_GSTIN}
Andheri East, Mumbai, Maharashtra 400069

TAX INVOICE

Invoice No: {number}
Invoice Date: {invoice_date}
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
    extraction = {
        "supplier_gstin": BUSINESS_GSTIN,
        "supplier_name": "Umang Traders Private Limited",
        "buyer_gstin": SUPPLIER_GSTIN_SAME_STATE,
        "buyer_name": "Mehta Electricals",
        "invoice_number": number,
        "invoice_date": invoice_date,
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
    return text, extraction


def purchase_in(period: str) -> tuple[str, dict]:
    """A Karnataka-to-Maharashtra purchase dated inside *period*, so IGST."""
    invoice_date = f"{period}-12"
    number = f"NW/{period.replace('-', '')}/77"
    text = f"""\
NORTHWIND SUPPLIES PRIVATE LIMITED
GSTIN: {SUPPLIER_GSTIN_OTHER_STATE}
MG Road, Bengaluru, Karnataka 560001

TAX INVOICE

Invoice No: {number}
Invoice Date: {invoice_date}
Place of Supply: 27 Maharashtra

Bill To: UMANG TRADERS
GSTIN: {BUSINESS_GSTIN}

HSN Code: 84713010
Laptop computers   10 x 45,000.00 = 450,000.00

Taxable Value:  450000.00
IGST @ 18%:      81000.00
Grand Total:    531000.00
"""
    extraction = {
        "supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE,
        "supplier_name": "Northwind Supplies Private Limited",
        "buyer_gstin": BUSINESS_GSTIN,
        "invoice_number": number,
        "invoice_date": invoice_date,
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
    return text, extraction


def upload(client, model, built: tuple[str, dict], *, invoice_type: str) -> dict:
    text, extraction = built
    model.clear()
    model.update(extraction)
    response = client.post(
        "/api/v1/invoices/upload",
        files={"file": ("invoice.txt", io.BytesIO(text.encode()), "text/plain")},
        data={"invoice_type": invoice_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["invoice"]


def portal_2b(period: str, *, include_the_purchase: bool) -> bytes:
    """The GSTR-2B the portal would return for *period*."""
    year, month = period.split("-")
    if include_the_purchase:
        supplier = {
            "ctin": SUPPLIER_GSTIN_OTHER_STATE,
            "trdnm": "Northwind Supplies",
            "inv": [
                {
                    "inum": f"NW/{period.replace('-', '')}/77",
                    "dt": f"12-{month}-{year}",
                    "val": 531000.00,
                    "itcavl": "Y",
                    "items": [{"rt": 18, "txval": 450000.00, "igst": 81000.00}],
                }
            ],
        }
    else:
        # Somebody else's invoice, so the file is a valid 2B with content
        # rather than an empty one the import refuses.
        supplier = {
            "ctin": SUPPLIER_GSTIN_SAME_STATE,
            "trdnm": "Mehta Electricals",
            "inv": [
                {
                    "inum": "ME/771",
                    "dt": f"09-{month}-{year}",
                    "val": 11800.00,
                    "itcavl": "Y",
                    "items": [{"rt": 18, "txval": 10000.00, "cgst": 900.00, "sgst": 900.00}],
                }
            ],
        }
    return json.dumps(
        {"data": {"rtnprd": f"{month}{year}", "docdata": {"b2b": [supplier]}}}
    ).encode()


def record_filed(client, return_type: str, period: str, **payload):
    return client.post(
        f"/api/v1/filing/{return_type}/filed", json={"period": period, **payload}
    )


def open_filing_alerts(client, period: str) -> list[dict]:
    """This period's outstanding deadline alerts.

    Scoped to the period and the type on purpose. The sweep covers six periods
    and also runs the s.16(4) pass over lapsing input credit, so an unscoped
    read would make these assertions depend on how much *else* the business has
    left undone — which is a different feature's test.
    """
    response = client.get(
        "/api/v1/alerts", params={"type": "filing_deadline", "period": period}
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def run_the_nightly_sweep(db_session) -> None:
    """Beat's step, not a user's. See this module's docstring."""
    alerting.sweep_filing_deadlines(db_session)


def money(value) -> Decimal:
    return Decimal(str(value))


def signed_up_before(db_session, gstin: str, period: str) -> None:
    """Backdate a tenant's sign-up to before *period* began.

    The deadline sweep will not raise an alert for a period that predates the
    account — see ``_first_period`` in ``app/services/alerting.py``: a business
    that signed up this morning is not told it is five months late for returns
    it was not our customer for. Every alert journey below is therefore about a
    tenant that has been here a while, and there is no request that makes an
    account older. So this is written rather than driven.

    Deliberately a fixture and not a step: it establishes the world the journey
    starts in, the same way registering does. The journey itself is still only
    HTTP.
    """
    business = db_session.query(Business).filter_by(gstin=gstin).one()
    business.created_at = business.created_at.replace(
        year=int(period[:4]), month=int(period[5:]), day=1
    )
    db_session.commit()


@pytest.fixture()
def signed_in(client):
    client.headers.update({"Authorization": f"Bearer {register(client)}"})
    return client


@pytest.fixture()
def established(signed_in, db_session):
    """A signed-in client whose business predates every period on the status
    screen, so the whole window is in scope for the sweep.
    """
    signed_up_before(db_session, BUSINESS_GSTIN, oldest_tracked_period(signed_in))
    return signed_in


@pytest.fixture()
def overdue_period(established, stub_openrouter):
    """A period with one sale in it, whose returns are months past due."""
    period = oldest_tracked_period(established)
    upload(established, stub_openrouter, sale_in(period), invoice_type="sales")
    return period


# ---------------------------------------------------------------------------
# The flow this half of the product exists for
# ---------------------------------------------------------------------------

class TestFilingBothReturnsForALatePeriod:
    """Prepare, export, file on the portal, record it — and stop being nagged.

    The two returns are recorded one at a time on purpose. GSTR-1 and GSTR-3B
    have different due dates and are filed in separate sittings, so the state
    between them — one done, one not — is the state a business is actually in
    for most of a week, and it is the one where a bug would be least visible.
    """

    def test_the_whole_submission_flow(self, signed_in, db_session, overdue_period):
        period = overdue_period

        # --- What the product says before anything is filed ----------------
        for return_type in ("gstr1", "gstr3b"):
            line = standing(signed_in, period, return_type)
            assert line["filed"] is False
            assert line["arn"] is None
            assert line["filed_late"] is False, "not filed at all is not filed late"
            assert line["days_until_due"] < 0, "the window's oldest period is past due"

        # --- The nightly sweep notices -------------------------------------
        run_the_nightly_sweep(db_session)

        raised = open_filing_alerts(signed_in, period)
        assert {alert["context"]["return_type"] for alert in raised} == {"gstr1", "gstr3b"}
        assert {alert["severity"] for alert in raised} == {"critical"}
        # The alert names the period it is about, so a user reading it knows
        # which return to go and file.
        assert all(period in alert["title"] for alert in raised)

        # --- Prepare and download GSTR-1 -----------------------------------
        preview = signed_in.get("/api/v1/filing/gstr1", params={"period": period}).json()
        assert preview["validation"]["ok"] is True
        export = signed_in.get(
            "/api/v1/filing/export/gstr1.json", params={"period": period}
        )
        assert export.status_code == 200
        assert json.loads(export.content) == preview["document"]

        # --- ...file it on the portal, and say so --------------------------
        response = record_filed(signed_in, "gstr1", period, arn=ARN)
        assert response.status_code == 201, response.text
        filed = response.json()
        assert filed["period"] == period
        assert filed["return_type"] == "gstr1"
        assert filed["status"] == "filed"
        assert filed["arn"] == ARN
        assert filed["filed_late"] is True, "the period's due date is months past"
        # The record carries the return as built at the moment of recording,
        # which is what makes it a record rather than a checkbox. It has to
        # agree with the document the user just downloaded and filed.
        assert filed["invoice_count"] == 1
        assert money(filed["total_taxable_value"]) == Decimal("200000.00")
        assert money(filed["total_cgst"]) == Decimal("18000.00")
        assert money(filed["total_sgst"]) == Decimal("18000.00")
        assert money(filed["total_igst"]) == Decimal("0.00")

        # --- The status screen agrees --------------------------------------
        line = standing(signed_in, period, "gstr1")
        assert line["filed"] is True
        assert line["arn"] == ARN
        assert line["filed_late"] is True
        assert line["filed_on"] == gst_calendar.today_ist().isoformat()
        # And the other return is untouched by it.
        assert standing(signed_in, period, "gstr3b")["filed"] is False

        # --- Tonight's sweep stops asking for the one that is done ---------
        run_the_nightly_sweep(db_session)

        still_open = open_filing_alerts(signed_in, period)
        assert [alert["context"]["return_type"] for alert in still_open] == ["gstr3b"]

        # --- File the second one -------------------------------------------
        assert record_filed(signed_in, "gstr3b", period, arn=CORRECTED_ARN).status_code == 201
        run_the_nightly_sweep(db_session)

        assert open_filing_alerts(signed_in, period) == []
        assert all(
            item["filed"] is True
            for item in filing_status(signed_in)
            if item["period"] == period
        )

    def test_a_return_recorded_late_does_not_go_on_getting_later(
        self, signed_in, overdue_period
    ):
        """``filed_late`` is a fact about the filing, not a running clock.

        The alert closes when the return is filed, so nothing else in the
        product is watching this number — if it drifted, the only place it
        would surface is a compliance history that quietly disagrees with
        itself between two page loads.
        """
        record_filed(signed_in, "gstr1", overdue_period, arn=ARN)
        first = standing(signed_in, overdue_period, "gstr1")

        # Recorded again with the same date: the ARN is already on file and
        # nothing about the filing has changed.
        record_filed(signed_in, "gstr1", overdue_period)
        second = standing(signed_in, overdue_period, "gstr1")

        assert second == first


class TestRecordingTheSameReturnTwice:
    """Idempotent per period and return type: the second call corrects the
    first rather than filing again. This is how an ARN that was not to hand at
    the time gets added, which is the reason it is optional at all.
    """

    def test_an_arn_supplied_later_is_added_without_filing_twice(
        self, signed_in, overdue_period
    ):
        first = record_filed(signed_in, "gstr1", overdue_period)
        assert first.status_code == 201
        assert first.json()["arn"] is None
        assert first.json()["status"] == "filed"

        second = record_filed(signed_in, "gstr1", overdue_period, arn=ARN)
        # A correction, not a creation: 200, where the first answered 201.
        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"], "a second row, not a correction"
        assert second.json()["arn"] == ARN

        assert standing(signed_in, overdue_period, "gstr1")["arn"] == ARN

    def test_omitting_the_arn_afterwards_does_not_erase_it(
        self, signed_in, overdue_period
    ):
        record_filed(signed_in, "gstr1", overdue_period, arn=ARN)

        # Correcting the date, with the acknowledgement not to hand. Clearing
        # the ARN as a side effect would drop the only proof the filing
        # happened, and nothing here can re-derive it — the portal issued it.
        yesterday = gst_calendar.today_ist() - timedelta(days=1)
        corrected = record_filed(
            signed_in, "gstr1", overdue_period, filed_on=yesterday.isoformat()
        )

        assert corrected.status_code == 200
        assert corrected.json()["arn"] == ARN
        line = standing(signed_in, overdue_period, "gstr1")
        assert line["arn"] == ARN
        assert line["filed_on"] == yesterday.isoformat()

    def test_a_different_arn_replaces_the_stored_one(self, signed_in, overdue_period):
        record_filed(signed_in, "gstr1", overdue_period, arn=ARN)
        record_filed(signed_in, "gstr1", overdue_period, arn=CORRECTED_ARN)

        assert standing(signed_in, overdue_period, "gstr1")["arn"] == CORRECTED_ARN

    def test_a_rejected_arn_leaves_the_recorded_filing_alone(
        self, signed_in, overdue_period
    ):
        record_filed(signed_in, "gstr1", overdue_period, arn=ARN)

        refused = record_filed(signed_in, "gstr1", overdue_period, arn="not-an-arn")

        assert refused.status_code == 422
        line = standing(signed_in, overdue_period, "gstr1")
        assert line["filed"] is True
        assert line["arn"] == ARN


class TestFilingsThePortalCouldNotHaveAcknowledged:
    def test_a_period_that_has_not_ended_yet_is_refused(self, signed_in):
        """The portal does not open a return until the month is over.

        A date inside the period is a mistyped year far more often than it is
        anything else, and recording one would close a deadline alert for a
        return that cannot have been filed.
        """
        current = gst_calendar.period_of(gst_calendar.today_ist())

        response = record_filed(signed_in, "gstr1", current, arn=ARN)

        assert response.status_code == 422
        assert current in response.json()["error"]["message"]

    def test_a_filing_date_in_the_future_is_refused(self, signed_in, overdue_period):
        tomorrow = gst_calendar.today_ist() + timedelta(days=1)

        response = record_filed(
            signed_in, "gstr1", overdue_period, filed_on=tomorrow.isoformat()
        )

        assert response.status_code == 422
        assert standing(signed_in, overdue_period, "gstr1")["filed"] is False

    def test_gstr2b_is_not_a_return_a_business_files(self, signed_in, overdue_period):
        """It is the portal's statement *to* the business, imported rather than
        submitted, and there is nowhere to file it. The 404 names what can be.
        """
        response = record_filed(signed_in, "gstr2b", overdue_period, arn=ARN)

        assert response.status_code == 404
        message = response.json()["error"]["message"]
        assert "gstr1" in message and "gstr3b" in message


# ---------------------------------------------------------------------------
# The GSTR-2B seam: what the portal's statement does to the return you file
# ---------------------------------------------------------------------------

class TestTheStatementDecidesWhatTheReturnMayClaim:
    """4(A) of GSTR-3B is credit *available*, and only the 2B establishes that.

    So the same purchase register produces two different returns depending on
    whether the supplier declared the invoice — and the difference has to
    survive the whole way out to the document a user files, not just to the
    reconciliation report that found it.
    """

    @pytest.fixture()
    def period(self, signed_in, db_session, stub_openrouter):
        # Reconciliation is a paid feature; this business has taken the plan.
        make_paid(db_session, db_session.query(Business).filter_by(gstin=BUSINESS_GSTIN).one().id)
        period = oldest_tracked_period(signed_in)
        upload(signed_in, stub_openrouter, purchase_in(period), invoice_type="purchase")
        upload(signed_in, stub_openrouter, sale_in(period), invoice_type="sales")
        return period

    def import_and_reconcile(self, client, period, *, declared: bool) -> dict:
        imported = client.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={
                "file": (
                    "gstr2b.json",
                    portal_2b(period, include_the_purchase=declared),
                    "application/json",
                )
            },
        )
        assert imported.status_code == 201, imported.text
        assert imported.json()["period"] == period, "the import derived the wrong period"
        run = client.post("/api/v1/reconciliation/run", json={"period": period})
        assert run.status_code == 201, run.text
        return run.json()

    def test_an_undeclared_purchase_is_not_claimed_in_the_3b(
        self, signed_in, period
    ):
        run = self.import_and_reconcile(signed_in, period, declared=False)
        assert money(run["itc_at_risk"]) == Decimal("81000.00")

        document = signed_in.get(
            "/api/v1/filing/gstr3b", params={"period": period}
        ).json()["document"]

        other_itc = next(
            row for row in document["itc_elg"]["itc_avl"] if row["ty"] == "OTH"
        )
        # The credit exists in the purchase register and not in the 2B, so the
        # return claims none of it. Claiming it would be the notice this
        # product exists to avoid.
        assert other_itc["iamt"] == 0.0
        assert document["itc_elg"]["itc_net"]["iamt"] == 0.0
        # ...and with no credit to set off, the CGST+SGST on the sale is cash.
        assert money(document["gstbot_cash_payable"]) == Decimal("36000.00")

        # The download a user files is that same document, byte for byte.
        export = signed_in.get(
            "/api/v1/filing/export/gstr3b.json", params={"period": period}
        )
        assert json.loads(export.content) == document

    def test_the_supplier_filing_late_moves_the_credit_into_the_return(
        self, signed_in, period
    ):
        self.import_and_reconcile(signed_in, period, declared=False)
        before = signed_in.get(
            "/api/v1/filing/gstr3b", params={"period": period}
        ).json()["document"]

        # The supplier files. The portal's statement now has the invoice, and
        # re-importing supersedes the earlier one rather than adding to it.
        run = self.import_and_reconcile(signed_in, period, declared=True)
        assert run["matched_count"] == 1
        assert money(run["itc_at_risk"]) == Decimal("0.00")

        after = signed_in.get(
            "/api/v1/filing/gstr3b", params={"period": period}
        ).json()["document"]

        other_itc = next(row for row in after["itc_elg"]["itc_avl"] if row["ty"] == "OTH")
        assert other_itc["iamt"] == 81000.0
        assert after["itc_elg"]["itc_net"]["iamt"] == 81000.0
        # ₹81,000 of IGST credit covers ₹36,000 of CGST+SGST, so nothing is
        # payable in cash — the whole point of reconciling before filing.
        assert money(after["gstbot_cash_payable"]) == Decimal("0.00")

        # Outward tax is the same in both: the statement decides what may be
        # claimed, never what was sold.
        assert after["sup_details"] == before["sup_details"]

    def test_the_return_recorded_as_filed_is_the_reconciled_one(
        self, signed_in, period
    ):
        """The stored figures come from the books either way — 3B's ITC lives
        in the document, not in the summary row — but the invoice count and
        outward totals are what a later dispute is checked against.
        """
        self.import_and_reconcile(signed_in, period, declared=True)

        filed = record_filed(signed_in, "gstr3b", period, arn=ARN).json()

        assert filed["invoice_count"] == 1, "3B is summarised from the sales side"
        assert money(filed["total_cgst"]) == Decimal("18000.00")
        assert money(filed["total_sgst"]) == Decimal("18000.00")


# ---------------------------------------------------------------------------
# What the delay cost
# ---------------------------------------------------------------------------

class TestTheLateFeeOnAReturnFiledMonthsLate:
    def test_the_estimate_is_offered_before_and_after_recording_it(
        self, signed_in, overdue_period
    ):
        """Both sides of the filing, because a business asks twice: what will
        this cost me, and then what did it. The answer must not depend on
        whether they have told us yet — the fee accrued while the return was
        outstanding either way.
        """
        before = signed_in.get(
            "/api/v1/filing/gstr3b/late-fee", params={"period": overdue_period}
        )
        assert before.status_code == 200, before.text
        estimate = before.json()
        assert estimate["projected"] is True, "still unfiled, so still running"
        assert estimate["days_late"] > 0
        assert money(estimate["total_payable"]) > 0, "months overdue and nothing owed"

        record_filed(signed_in, "gstr3b", overdue_period, arn=ARN)

        after = signed_in.get(
            "/api/v1/filing/gstr3b/late-fee", params={"period": overdue_period}
        ).json()
        # Recorded as filed today, and the estimate was as of today: the same
        # number, now settled rather than running.
        assert after["projected"] is False
        assert after["filed_on"] == gst_calendar.today_ist().isoformat()
        assert money(after["total_payable"]) == money(estimate["total_payable"])

    def test_a_nil_return_is_capped_lower_than_one_with_tax_on_it(
        self, signed_in, overdue_period
    ):
        """The statutory cap for a nil return is a fraction of the ordinary one,
        and it is the caller who says which this is — nothing in the books
        proves a business had no supplies, only that it recorded none.
        """
        ordinary = signed_in.get(
            "/api/v1/filing/gstr3b/late-fee", params={"period": overdue_period}
        ).json()
        nil = signed_in.get(
            "/api/v1/filing/gstr3b/late-fee",
            params={"period": overdue_period, "is_nil": True},
        ).json()

        assert nil["is_nil"] is True
        assert money(nil["late_fee_total"]) < money(ordinary["late_fee_total"])
        assert money(nil["late_fee_cgst"]) == money(nil["late_fee_sgst"]), "split evenly"


# ---------------------------------------------------------------------------
# Two businesses filing the same period
# ---------------------------------------------------------------------------

class TestOneTenantsFilingIsNotAnothers:
    def test_recording_a_period_leaves_the_other_tenants_standing_alone(
        self, client, stub_openrouter
    ):
        """Both tenants file the same calendar month, which is the normal case
        and not an edge one — every business in India files April in May. The
        records are keyed by business, so one recording it must not mark the
        other's as done, and the id space must not be walkable across the
        boundary either.
        """
        first_token = register(client)
        second_token = register(
            client,
            email="rival@example.com",
            gstin=SUPPLIER_GSTIN_SAME_STATE,
            name="Mehta Electricals",
        )

        client.headers.update({"Authorization": f"Bearer {first_token}"})
        period = oldest_tracked_period(client)
        upload(client, stub_openrouter, sale_in(period), invoice_type="sales")
        mine = record_filed(client, "gstr1", period, arn=ARN)
        assert mine.status_code == 201

        client.headers.update({"Authorization": f"Bearer {second_token}"})
        assert standing(client, period, "gstr1")["filed"] is False
        assert standing(client, period, "gstr1")["arn"] is None

        # The rival records the same period. Their own row, not a correction
        # of somebody else's — and the first tenant's ARN survives it.
        theirs = record_filed(client, "gstr1", period, arn=CORRECTED_ARN)
        assert theirs.status_code == 201
        assert theirs.json()["id"] != mine.json()["id"]
        assert standing(client, period, "gstr1")["arn"] == CORRECTED_ARN

        client.headers.update({"Authorization": f"Bearer {first_token}"})
        assert standing(client, period, "gstr1")["arn"] == ARN

    def test_one_sweep_raises_each_tenants_alerts_against_their_own_history(
        self, client, db_session, stub_openrouter
    ):
        """The sweep runs once for the whole deployment, so a tenant's alerts
        are only as isolated as that one pass makes them.

        The two tenants here differ in the thing that decides the answer: how
        long they have been customers. The signed_in one is months late; the
        one that signed up this morning is not late for anything, because a
        return that fell due before the account existed is not a promise this
        product broke. Getting that wrong greets every new sign-up with twelve
        critical alerts about a business we have never seen the books of.
        """
        first_token = register(client)
        second_token = register(
            client,
            email="rival@example.com",
            gstin=SUPPLIER_GSTIN_SAME_STATE,
            name="Mehta Electricals",
        )

        client.headers.update({"Authorization": f"Bearer {first_token}"})
        period = oldest_tracked_period(client)
        upload(client, stub_openrouter, sale_in(period), invoice_type="sales")
        signed_up_before(db_session, BUSINESS_GSTIN, period)

        run_the_nightly_sweep(db_session)

        assert len(open_filing_alerts(client, period)) == 2
        client.headers.update({"Authorization": f"Bearer {second_token}"})
        assert open_filing_alerts(client, period) == []


# ---------------------------------------------------------------------------
# The alert lifecycle a user drives by hand
# ---------------------------------------------------------------------------

class TestReadingAndDismissingADeadlineAlert:
    def test_dismissing_stops_tomorrows_sweep_raising_it_again(
        self, signed_in, db_session, overdue_period
    ):
        """An alert that reappears every morning is one that gets notifications
        turned off, so the sweep has to respect a dismissal — while leaving the
        return itself as unfiled as it was.
        """
        run_the_nightly_sweep(db_session)
        raised = open_filing_alerts(signed_in, overdue_period)
        assert len(raised) == 2

        for alert in raised:
            assert (
                signed_in.post(f"/api/v1/alerts/{alert['id']}/dismiss").status_code == 200
            )

        run_the_nightly_sweep(db_session)

        assert open_filing_alerts(signed_in, overdue_period) == []
        # Dismissed, not done: the return is still unfiled and the status
        # screen must not have been quietened along with the alert.
        assert standing(signed_in, overdue_period, "gstr1")["filed"] is False

    def test_marking_one_read_leaves_it_counting_towards_the_badge(
        self, signed_in, db_session, overdue_period
    ):
        """Seen is not handled. A deadline someone has looked at is exactly as
        unmet as one they have not, and the dashboard badge is what tells them
        so.
        """
        run_the_nightly_sweep(db_session)
        alert = open_filing_alerts(signed_in, overdue_period)[0]

        read = signed_in.post(f"/api/v1/alerts/{alert['id']}/read")
        assert read.status_code == 200
        assert read.json()["status"] == "read"

        listing = signed_in.get(
            "/api/v1/alerts", params={"type": "filing_deadline", "period": overdue_period}
        ).json()
        assert alert["id"] in {row["id"] for row in listing["items"]}
        assert listing["open_total"] >= 2

    def test_filing_resolves_the_alert_rather_than_dismissing_it(
        self, signed_in, db_session, overdue_period
    ):
        """The difference between an alert that worked and one that was swatted
        away is the only signal there is about whether the alerting is earning
        its place.
        """
        run_the_nightly_sweep(db_session)
        record_filed(signed_in, "gstr1", overdue_period, arn=ARN)
        run_the_nightly_sweep(db_session)

        closed = signed_in.get(
            "/api/v1/alerts",
            params={"scope": "closed", "type": "filing_deadline", "period": overdue_period},
        ).json()["items"]

        by_return = {row["context"]["return_type"]: row["status"] for row in closed}
        assert by_return == {"gstr1": "resolved"}


# ---------------------------------------------------------------------------
# A period with nothing in it
# ---------------------------------------------------------------------------

def test_a_period_with_no_invoices_still_files_and_records(signed_in):
    """A nil return is a return. A business with no supplies in a month still
    has to file, and the deadline alerting says so — so the whole path has to
    work with an empty period rather than 500 on the sum of no invoices.
    """
    period = oldest_tracked_period(signed_in)

    preview = signed_in.get("/api/v1/filing/gstr1", params={"period": period}).json()
    document = preview["document"]
    assert document["fp"] == to_portal_period(period)
    assert preview["validation"]["ok"] is True, "nothing to file is not an error"
    # The supply blocks are absent rather than present and empty: that is the
    # shape the portal's offline utility takes, and a nil return is the only
    # case where the difference is visible.
    assert not {"b2b", "b2cl", "b2cs", "hsn"} & document.keys()

    filed = record_filed(signed_in, "gstr1", period, arn=ARN)
    assert filed.status_code == 201
    assert filed.json()["invoice_count"] == 0
    assert money(filed.json()["total_taxable_value"]) == Decimal("0.00")
    assert standing(signed_in, period, "gstr1")["filed"] is True


def test_every_period_the_status_screen_reports_can_be_previewed_and_recorded(
    signed_in,
):
    """The status screen is a list of links. Each row offers a return to
    prepare and a filing to record, so a period it lists that either endpoint
    refuses is a dead link on the one screen a business files from.
    """
    items = filing_status(signed_in)
    assert len(items) == 2 * 6, "six periods, two returns each"

    for item in items:
        period, return_type = item["period"], item["return_type"]
        preview = signed_in.get(f"/api/v1/filing/{return_type}", params={"period": period})
        assert preview.status_code == 200, f"{return_type} {period}: {preview.text}"
        recorded = record_filed(signed_in, return_type, period)
        assert recorded.status_code == 201, f"{return_type} {period}: {recorded.text}"
        assert recorded.json()["period"] == period

    assert all(item["filed"] for item in filing_status(signed_in))


def test_the_status_window_never_offers_a_month_that_has_not_ended(signed_in):
    """The current month is excluded because the portal does not open its
    return yet — and recording it is refused for the same reason, so a row
    here would be a row whose action cannot succeed.
    """
    today = gst_calendar.today_ist()
    periods = {item["period"] for item in filing_status(signed_in)}

    assert gst_calendar.period_of(today) not in periods
    assert periods == set(gst_calendar.completed_periods(today, 6))
    assert max(periods) == gst_calendar.previous_period(gst_calendar.period_of(today))
    assert all(
        gst_calendar.period_end(period) < date(today.year, today.month, 1)
        for period in periods
    )
