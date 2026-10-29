"""The ceiling on an amount, at every door a figure comes in through.

A money column here is ``Numeric(16, 2)`` — fourteen digits before the point.
Nothing enforced that. ``ge=0`` was on every amount a caller could send and
nothing was on the other end, so ``1E+100`` in a correction was a 200.

What makes this worth a file of its own is *where* it broke. Not at the write:

*   Postgres refuses the INSERT and SQLite keeps whatever it was handed, so the
    deployment and the suite disagree about whether there is a problem at all.
*   The failure lands on the **read**. Every figure in this product is
    quantized to the paisa on its way out, and ``Decimal.quantize`` raises
    ``InvalidOperation`` rather than rounding once the result needs more than
    the decimal context's 28 significant digits. One overlarge row is therefore
    not a wrong number on one screen — it is a 500 on the dashboard, the ITC
    summary and the GSTR-3B preview, for as long as the row is there, caused by
    a write that answered 200 an hour earlier.

So the tests below come in pairs: the door refuses the figure, *and* the
screens that would have broken still answer. The second half is the real
assertion — the bound exists to keep a read working, and a bound that stopped
the write while something else still poisoned the row would pass the first half
alone.

The doors are: a hand correction (``PATCH /invoices/{id}``), a what-if
(``POST /itc/set-off``), the Rule 42 turnovers in a query string, an uploaded
GSTR-2B, and whatever the extraction model decided to return.
"""
from __future__ import annotations

import io
import json
from decimal import Decimal

import pytest

from app.models.gstr_return import GSTRReturn
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.mixins import MONEY_MAX
from app.services import invoice_parser
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_SAME_STATE

# One paisa past what the column holds. Every refusal below is asserted against
# this rather than a round number, so a widened column that forgot to move
# MONEY_MAX shows up as a failure here instead of as a wrongly refused invoice.
JUST_OVER = MONEY_MAX + Decimal("0.01")

# What a caller actually sends. Scientific notation is how a spreadsheet export
# and a JSON serialiser both write a number this size, and it is what the
# original probe found: ``"1E+100"`` was accepted verbatim.
ABSURD = "1E+100"

PERIOD = "2026-04"

# The screens that a poisoned row used to take down. Read after every write
# below: a 500 on any of them is the bug this file exists for.
READ_PATHS = (
    f"/api/v1/dashboard?period={PERIOD}",
    f"/api/v1/itc?period={PERIOD}",
    f"/api/v1/filing/gstr3b?period={PERIOD}",
    f"/api/v1/filing/gstr1?period={PERIOD}",
    f"/api/v1/invoices?period={PERIOD}",
)

# GSTR-2B import, reconciliation and the ITC reads are paid features; this file
# is about what they do, so the business it drives is on a paid plan.
pytestmark = pytest.mark.usefixtures("paid_business")


@pytest.fixture()
def invoice(db_session, business) -> Invoice:
    """A purchase in the period every read below is scoped to."""
    row = Invoice(
        business_id=business.id,
        invoice_type=InvoiceType.PURCHASE,
        status=InvoiceStatus.PARSED,
        period=PERIOD,
        invoice_number="INV-CEILING-1",
        counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE,
        taxable_value=Decimal("1000.00"),
        cgst=Decimal("90.00"),
        sgst=Decimal("90.00"),
        igst=Decimal("0.00"),
        cess=Decimal("0.00"),
        total_value=Decimal("1180.00"),
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def assert_every_screen_answers(client, auth_client) -> None:
    """No read in the period 500s.

    Called after each refused write. The point is not that the screens are
    correct — other files assert that — but that they *answer*, which is
    exactly what an out-of-range amount in the books took away.
    """
    for path in READ_PATHS:
        response = client.get(path, headers=auth_client.headers)
        assert response.status_code < 500, f"{path} -> {response.status_code}"


# --------------------------------------------------------------------------
# The correction box
# --------------------------------------------------------------------------

class TestAHandCorrection:
    """``PATCH /invoices/{id}`` — a reviewer typing into a tax box.

    The one door where a human is expected to type a figure nothing upstream
    checked, and the one the original defect was found through.
    """

    @pytest.mark.parametrize(
        "field", ["taxable_value", "cgst", "sgst", "igst", "cess", "total_value"]
    )
    def test_an_amount_wider_than_the_column_is_refused(
        self, raw_client, auth_client, invoice, field
    ):
        response = raw_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={field: ABSURD},
            headers=auth_client.headers,
        )
        assert response.status_code == 422
        assert field in response.text

    @pytest.mark.parametrize(
        "field", ["taxable_value", "cgst", "sgst", "igst", "cess", "total_value"]
    )
    def test_the_refusal_is_at_the_paisa_the_column_ends(
        self, raw_client, auth_client, invoice, field
    ):
        # The largest figure that fits is accepted and the next one is not.
        # Asserted on every head, because ``le=`` was added six times by hand
        # and five out of six is a defect nobody would notice.
        ok = raw_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={field: str(MONEY_MAX)},
            headers=auth_client.headers,
        )
        assert ok.status_code == 200

        over = raw_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={field: str(JUST_OVER)},
            headers=auth_client.headers,
        )
        assert over.status_code == 422

    def test_the_refused_correction_changes_nothing(
        self, raw_client, auth_client, db_session, invoice
    ):
        before = invoice.taxable_value
        raw_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"taxable_value": ABSURD, "invoice_number": "INV-RENAMED"},
            headers=auth_client.headers,
        )
        db_session.expire_all()
        stored = db_session.get(Invoice, invoice.id)
        assert stored.taxable_value == before
        # The whole body is refused, not the offending field: a 422 that had
        # applied the rename would leave the reviewer's screen disagreeing with
        # the books about what was saved.
        assert stored.invoice_number == "INV-CEILING-1"

    def test_the_screens_the_write_would_have_broken_still_answer(
        self, raw_client, auth_client, invoice
    ):
        raw_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"taxable_value": ABSURD},
            headers=auth_client.headers,
        )
        assert_every_screen_answers(raw_client, auth_client)

    def test_a_negative_amount_is_still_refused(
        self, raw_client, auth_client, invoice
    ):
        # The lower bound was already there. Pinned so that adding the upper
        # one cannot be what quietly removes it.
        response = raw_client.patch(
            f"/api/v1/invoices/{invoice.id}",
            json={"taxable_value": "-1.00"},
            headers=auth_client.headers,
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------
# The what-if
# --------------------------------------------------------------------------

class TestTheSetOffWhatIf:
    """``POST /itc/set-off`` — figures that are not in the books at all.

    A caller is *supposed* to type numbers here that nothing validated
    upstream, which makes it the one endpoint where the bound cannot be
    inherited from a column.
    """

    @pytest.mark.parametrize(
        "field",
        [
            "credit_igst",
            "credit_cgst",
            "credit_sgst",
            "credit_cess",
            "liability_igst",
            "liability_cgst",
            "liability_sgst",
            "liability_cess",
        ],
    )
    def test_an_out_of_range_figure_is_refused(self, raw_client, auth_client, field):
        response = raw_client.post(
            "/api/v1/itc/set-off",
            json={field: ABSURD},
            headers=auth_client.headers,
        )
        assert response.status_code == 422
        assert field in response.text

    def test_the_largest_figure_that_fits_is_still_computed(
        self, raw_client, auth_client
    ):
        # The bound has to be wide enough to be useless in practice. If the
        # ceiling itself 500'd, the waterfall would be broken at exactly the
        # value the schema advertises as legal.
        response = raw_client.post(
            "/api/v1/itc/set-off",
            json={"credit_igst": str(MONEY_MAX), "liability_igst": str(MONEY_MAX)},
            headers=auth_client.headers,
        )
        assert response.status_code == 200
        assert Decimal(response.json()["cash_payable"]["igst"]) == Decimal("0.00")

    def test_an_ordinary_set_off_is_unaffected(self, raw_client, auth_client):
        response = raw_client.post(
            "/api/v1/itc/set-off",
            json={"credit_igst": "40", "liability_igst": "100"},
            headers=auth_client.headers,
        )
        assert response.status_code == 200
        assert Decimal(response.json()["cash_payable"]["igst"]) == Decimal("60.00")


# --------------------------------------------------------------------------
# The Rule 42 turnovers
# --------------------------------------------------------------------------

class TestTheTurnoversInAQueryString:
    """``GET /itc?exempt_turnover=…`` — a ratio, so it multiplies.

    These two are divided into each other and the result is quantized to
    paise, which is the operation that raises. A 500 from a URL parameter is
    also the cheapest denial of service in the product.
    """

    @pytest.mark.parametrize("field", ["exempt_turnover", "total_turnover"])
    def test_an_out_of_range_turnover_is_refused(self, raw_client, auth_client, field):
        response = raw_client.get(
            f"/api/v1/itc?period={PERIOD}&{field}=1E%2B100",
            headers=auth_client.headers,
        )
        assert response.status_code == 422
        assert field in response.text

    @pytest.mark.parametrize("field", ["exempt_turnover", "total_turnover"])
    def test_a_turnover_at_the_ceiling_is_answered(
        self, raw_client, auth_client, field
    ):
        response = raw_client.get(
            f"/api/v1/itc?period={PERIOD}&{field}={MONEY_MAX}",
            headers=auth_client.headers,
        )
        assert response.status_code == 200

    def test_a_negative_turnover_is_still_refused(self, raw_client, auth_client):
        response = raw_client.get(
            f"/api/v1/itc?period={PERIOD}&exempt_turnover=-1",
            headers=auth_client.headers,
        )
        assert response.status_code == 422


# --------------------------------------------------------------------------
# The uploaded statement
# --------------------------------------------------------------------------

def build_2b(txval: object, *, raw: str | None = None) -> bytes:
    """A valid GSTR-2B whose one line item carries *txval*.

    *raw* substitutes a bare JSON token — ``Infinity`` is not valid JSON and
    cannot be produced by ``json.dumps``, but ``json.loads`` accepts it by
    default, so a hand-edited or non-Python-generated file really can carry
    one and this is the only way to write that test.
    """
    payload = {
        "gstin": BUSINESS_GSTIN,
        "rtnprd": "042026",
        "docdata": {
            "b2b": [
                {
                    "ctin": SUPPLIER_GSTIN_SAME_STATE,
                    "inv": [
                        {
                            "inum": "INV-2B-1",
                            "dt": "05-04-2026",
                            "val": 1180,
                            "itms": [
                                {
                                    "itm_det": {
                                        "txval": txval,
                                        "iamt": 0,
                                        "camt": 90,
                                        "samt": 90,
                                        "csamt": 0,
                                        "rt": 18,
                                    }
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }
    body = json.dumps(payload)
    if raw is not None:
        body = body.replace('"__RAW__"', raw)
    return body.encode()


class TestAnUploadedStatement:
    """A GSTR-2B is a file, so nothing in it is an amount until it is checked.

    This one is the nastiest of the doors, because the import *committed* and
    only then failed serialising its own response: a 500 handed back for a row
    that is already in the database, and every later read of that period the
    same 500 with nothing in the request to explain it.
    """

    def _import(self, client, auth_client, content: bytes):
        return client.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={"file": ("2b.json", io.BytesIO(content), "application/json")},
            headers=auth_client.headers,
        )

    @pytest.mark.parametrize(
        "content",
        [
            build_2b(1e300),
            build_2b(float(10**20)),
            build_2b("__RAW__", raw="Infinity"),
            build_2b("__RAW__", raw="-Infinity"),
            build_2b("__RAW__", raw="NaN"),
            build_2b("9" * 40),
        ],
        ids=["1e300", "1e20", "infinity", "-infinity", "nan", "forty-digits"],
    )
    def test_an_amount_no_column_could_hold_refuses_the_file(
        self, raw_client, auth_client, content
    ):
        # Not clamped: that invents a figure of ninety-nine thousand crore. And
        # (P37 M18) not dropped to zero either, which this used to do. A
        # statement's records have no reviewer, so one bad line in five hundred
        # became a supplier "declaring" nothing, invisible inside a plausible
        # total, and reconciliation judged the books against it. Refused, and
        # nothing stored, so the user downloads the statement again.
        response = self._import(raw_client, auth_client, content)
        assert response.status_code == 422
        assert "INV-2B-1" in response.json()["detail"]
        later = raw_client.get(
            "/api/v1/reconciliation/gstr2b/periods", headers=auth_client.headers
        )
        assert PERIOD not in later.text

    @pytest.mark.parametrize(
        "content",
        [build_2b(1e300), build_2b("__RAW__", raw="Infinity")],
        ids=["1e300", "infinity"],
    )
    def test_every_later_read_of_that_period_still_answers(
        self, raw_client, auth_client, content
    ):
        assert self._import(raw_client, auth_client, content).status_code == 422
        assert_every_screen_answers(raw_client, auth_client)
        later = raw_client.get(
            f"/api/v1/reconciliation?period={PERIOD}", headers=auth_client.headers
        )
        assert later.status_code == 200

    def test_an_ordinary_amount_is_still_read(self, raw_client, auth_client):
        response = self._import(raw_client, auth_client, build_2b(1000))
        assert response.status_code == 201
        assert Decimal(response.json()["total_taxable_value"]) == Decimal("1000.00")

    def test_an_amount_at_the_ceiling_is_kept(self, raw_client, auth_client):
        # Fourteen digits, no paise. The exact ceiling cannot be asserted
        # through this door in the suite: SQLite has no decimal type, so
        # SQLAlchemy round-trips ``Numeric`` through a float and hands back
        # 99999999999999.98 for 99999999999999.99. That is the test database,
        # not the product — Postgres stores it exactly — and a value under
        # 2**53 is exact on both, so the assertion is about acceptance rather
        # than about a paisa. ``TestToMoney`` pins the exact ceiling directly.
        at_ceiling = Decimal("99999999999999.00")
        response = self._import(raw_client, auth_client, build_2b(str(at_ceiling)))
        assert response.status_code == 201
        assert Decimal(response.json()["total_taxable_value"]) == at_ceiling


# --------------------------------------------------------------------------
# What the cell-by-cell ceiling left open: the addition
# --------------------------------------------------------------------------

def build_statement(invoices: list[dict]) -> bytes:
    """A valid GSTR-2B holding *invoices*, each ``{"num": ..., "items": [...]}``.

    ``build_2b`` carries one line on one invoice, which is the shape the
    per-cell ceiling is about. This one is for the sums built on top of it.
    """
    payload = {
        "gstin": BUSINESS_GSTIN,
        "rtnprd": "042026",
        "docdata": {
            "b2b": [
                {
                    "ctin": SUPPLIER_GSTIN_SAME_STATE,
                    "inv": [
                        {
                            "inum": invoice["num"],
                            "dt": "05-04-2026",
                            "itms": [
                                {"txval": str(amount), "iamt": 0, "camt": 0, "samt": 0}
                                for amount in invoice["items"]
                            ],
                        }
                        for invoice in invoices
                    ],
                }
            ]
        },
    }
    return json.dumps(payload).encode()


def build_note_statement(invoice_amount: object, note_amount: object) -> bytes:
    """A 2B with one invoice and one credit note against it."""
    payload = {
        "gstin": BUSINESS_GSTIN,
        "rtnprd": "042026",
        "docdata": {
            "b2b": [
                {
                    "ctin": SUPPLIER_GSTIN_SAME_STATE,
                    "inv": [
                        {
                            "inum": "INV-BIG",
                            "dt": "05-04-2026",
                            "itms": [{"txval": str(invoice_amount)}],
                        }
                    ],
                }
            ],
            "cdnr": [
                {
                    "ctin": SUPPLIER_GSTIN_SAME_STATE,
                    "nt": [
                        {
                            "nt_num": "CN-BIG",
                            "nt_dt": "06-04-2026",
                            "typ": "C",
                            "itms": [{"txval": str(note_amount)}],
                        }
                    ],
                }
            ],
        },
    }
    return json.dumps(payload).encode()


# A figure a statement could plausibly carry, small enough that two of them
# still fit the column — so "several lines add up" can be asserted against
# the same ceiling the refusals are.
BIG_BUT_FINE = Decimal("40000000000000.00")


class TestTheSumOfAStatement:
    """The ceiling was on the cell, and every figure in a 2B is a sum.

    ``to_money`` checks each value it reads and stops there. A rate line is
    then summed onto its invoice, and every invoice into the period totals
    ``gstr_returns`` stores — so a handful of cells each just inside
    ``MONEY_MAX`` produce a stored figure several times wider than the column.
    Five rate items at the ceiling on one invoice was enough, and so were three
    ordinary invoices.

    Which is the same 500 as the rest of this file, arrived at by addition
    rather than by a single absurd cell: Postgres refuses the INSERT with
    ``numeric field overflow``, SQLite keeps the number, and the import that
    answers 201 in this suite answers 500 on the deployment. It is also
    committed before any response model looks at it, so there is no later
    refusal to catch it either.
    """

    def _import(self, client, auth_client, content: bytes):
        return client.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={"file": ("2b.json", io.BytesIO(content), "application/json")},
            headers=auth_client.headers,
        )

    def test_rate_lines_that_add_past_the_ceiling_are_refused(
        self, raw_client, auth_client
    ):
        content = build_statement([{"num": "INV-1", "items": [MONEY_MAX] * 5}])
        assert self._import(raw_client, auth_client, content).status_code == 422

    def test_invoices_that_add_past_the_ceiling_are_refused(self, raw_client, auth_client):
        content = build_statement(
            [{"num": f"INV-{i}", "items": [MONEY_MAX]} for i in range(3)]
        )
        assert self._import(raw_client, auth_client, content).status_code == 422

    def test_the_refusal_says_which_figure_it_is_about(self, raw_client, auth_client):
        # "the file is too big" is not actionable; "the taxable value totals
        # this" tells the sender which column of their export to look at.
        content = build_statement([{"num": "INV-1", "items": [MONEY_MAX] * 5}])
        assert "taxable value" in self._import(raw_client, auth_client, content).text

    def test_the_offending_invoice_is_named(self, raw_client, auth_client):
        content = build_statement([{"num": "INV-ODD", "items": [MONEY_MAX] * 5}])
        assert "INV-ODD" in self._import(raw_client, auth_client, content).text

    def test_nothing_is_stored_for_the_period(self, raw_client, auth_client, db_session):
        # The refusal happens in the reader, before the write — which is the
        # whole difference between this and the failure it replaces, where the
        # row was committed and only the response blew up.
        content = build_statement([{"num": "INV-1", "items": [MONEY_MAX] * 5}])
        self._import(raw_client, auth_client, content)

        db_session.expire_all()
        assert db_session.query(GSTRReturn).count() == 0

    def test_every_screen_still_answers_after_the_refusal(self, raw_client, auth_client):
        content = build_statement([{"num": "INV-1", "items": [MONEY_MAX] * 5}])
        self._import(raw_client, auth_client, content)
        assert_every_screen_answers(raw_client, auth_client)

    def test_a_credit_note_cannot_net_two_impossible_figures_back_into_range(
        self, raw_client, auth_client
    ):
        # Summed signed, an invoice and a note of the same absurd size cancel
        # to zero and the statement looks importable — while the two records
        # stored beside the totals each carry a figure the column cannot hold.
        # Magnitudes are what the check adds, so neither hides the other.
        content = build_note_statement(MONEY_MAX, MONEY_MAX)
        assert self._import(raw_client, auth_client, content).status_code == 422

    def test_a_statement_that_fits_is_still_imported(self, raw_client, auth_client):
        content = build_statement([{"num": "INV-1", "items": [BIG_BUT_FINE]}])
        response = self._import(raw_client, auth_client, content)
        assert response.status_code == 201, response.text
        assert Decimal(response.json()["total_taxable_value"]) == BIG_BUT_FINE

    def test_several_lines_that_together_fit_are_still_summed(
        self, raw_client, auth_client
    ):
        # The bound is on the total, not on the count: two lines adding to the
        # ceiling are a statement, and refusing them would be a regression of
        # its own.
        content = build_statement([{"num": "INV-1", "items": [BIG_BUT_FINE] * 2}])
        response = self._import(raw_client, auth_client, content)
        assert response.status_code == 201, response.text
        assert Decimal(response.json()["total_taxable_value"]) == BIG_BUT_FINE * 2

    def test_an_ordinary_multi_line_statement_is_untouched(self, raw_client, auth_client):
        content = build_statement(
            [
                {"num": "INV-1", "items": [Decimal("1000.00"), Decimal("2000.00")]},
                {"num": "INV-2", "items": [Decimal("500.00")]},
            ]
        )
        response = self._import(raw_client, auth_client, content)
        assert response.status_code == 201, response.text
        assert Decimal(response.json()["total_taxable_value"]) == Decimal("3500.00")

    def test_the_csv_reader_is_bounded_too(self, raw_client, auth_client):
        # Rate-wise rows of one invoice are merged and summed there as well, so
        # the door the export comes through has the same hole in it.
        rows = "\n".join(
            f"{SUPPLIER_GSTIN_SAME_STATE},INV-1,05/04/2026,{MONEY_MAX}" for _ in range(5)
        )
        content = (
            "GSTIN of supplier,Invoice number,Invoice date,Taxable Value\n" + rows
        ).encode()
        response = raw_client.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={"file": ("2b.csv", io.BytesIO(content), "text/csv")},
            headers=auth_client.headers,
        )
        assert response.status_code == 422, response.text

    def test_an_ordinary_csv_still_imports(self, raw_client, auth_client):
        content = (
            "GSTIN of supplier,Invoice number,Invoice date,Taxable Value\n"
            f"{SUPPLIER_GSTIN_SAME_STATE},INV-1,05/04/2026,1000.00\n"
        ).encode()
        response = raw_client.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={"file": ("2b.csv", io.BytesIO(content), "text/csv")},
            headers=auth_client.headers,
        )
        assert response.status_code == 201, response.text
        assert Decimal(response.json()["total_taxable_value"]) == Decimal("1000.00")


# --------------------------------------------------------------------------
# The coercion itself
# --------------------------------------------------------------------------

class TestToMoney:
    """``to_money`` — "is this an amount", which ``to_decimal`` does not ask.

    Unit-level, because the extraction model is the door with no schema in
    front of it: whatever the LLM returns goes straight into these functions,
    and there is no request to 422.
    """

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("1000.50", Decimal("1000.50")),
            (1000.5, Decimal("1000.5")),
            ("Rs. 1,000.50", Decimal("1000.50")),
            (0, Decimal("0")),
            (str(MONEY_MAX), MONEY_MAX),
        ],
    )
    def test_an_amount_is_returned_as_it_is(self, value, expected):
        assert invoice_parser.to_money(value) == expected

    @pytest.mark.parametrize(
        "value",
        [
            "1E+100",
            1e300,
            float("inf"),
            float("-inf"),
            float("nan"),
            Decimal("Infinity"),
            Decimal("NaN"),
            "9" * 40,
            str(JUST_OVER),
            str(-JUST_OVER),
        ],
    )
    def test_what_is_not_an_amount_falls_back(self, value):
        # Default, not the value: a figure this size is a parse artefact, and
        # zero in a tax box is visibly wrong where 1e300 is invisibly wrong.
        assert invoice_parser.to_money(value) == Decimal("0.00")
        assert invoice_parser.to_money(value, default=None) is None

    def test_to_decimal_also_refuses_the_infinities(self):
        # ``to_money`` is built on it, and ``Decimal("Infinity")`` is a Decimal
        # — so the ``isinstance`` shortcut used to hand one straight back.
        for value in (float("inf"), float("nan"), Decimal("Infinity"), Decimal("NaN")):
            assert invoice_parser.to_decimal(value) == Decimal("0.00")
            assert invoice_parser.to_decimal(value, default=None) is None

    def test_to_decimal_still_takes_a_number_too_wide_to_be_money(self):
        # The two functions are deliberately different. A tax *rate* and a
        # count go through ``to_decimal``, and bounding those by a money
        # column would be the wrong check in the wrong place.
        assert invoice_parser.to_decimal(1e100) == Decimal(str(1e100))
        assert invoice_parser.to_decimal("9" * 40) == Decimal("9" * 40)


class TestANumberThePatternCannotSpell:
    """Scientific notation, where a ceiling is no use because the figure shrinks.

    ``_NUMBER_PATTERN`` does not model an exponent, and ``re.search`` answers
    with a *prefix* rather than with nothing. So ``"1E+100"`` matched ``"1"``,
    and every check downstream — the ceiling in :func:`to_money`, the range on
    the correction schema, a reviewer reading the screen — was looking at the
    figure one and had no reason to object to it. The amount was not refused,
    it was invented.

    Both directions reach it: a model that quotes its numbers returns
    ``"1.2e5"`` as a string, and a spreadsheet exported to CSV writes any wide
    column in exactly this form.
    """

    @pytest.mark.parametrize(
        "value", ["1E+100", "1.5E+30", "2e5", "1000E5", "-1E+100", "1.2e-5"]
    )
    def test_a_mantissa_is_not_the_number(self, value):
        assert invoice_parser.to_decimal(value, default=None) is None
        assert invoice_parser.to_money(value, default=None) is None

    @pytest.mark.parametrize(
        "value, expected",
        [
            ("1,000.00", Decimal("1000.00")),
            ("Rs. 1000.50", Decimal("1000.50")),
            # A letter after a number is only an exponent if an exponent is
            # what it spells. These are the shapes that actually appear on an
            # invoice, and refusing them would be the worse bug.
            ("1000 EA", Decimal("1000")),
            ("Total 1,000.00 E-invoice", Decimal("1000.00")),
            ("1000E", Decimal("1000")),
            ("29AAGCB7383J1Z4", Decimal("29")),
        ],
    )
    def test_an_ordinary_figure_is_unaffected(self, value, expected):
        assert invoice_parser.to_decimal(value) == expected

    def test_the_reviewer_is_told_rather_than_shown_a_rupee(self):
        # The whole point. Before, this field read 1.00 with no warning.
        result = invoice_parser._from_model_payload(
            {"taxable_value": "1E+100"}, "text", "m"
        )
        assert result.taxable_value == Decimal("0.00")
        assert any("taxable value" in w for w in result.warnings)


class TestWhatTheModelReturned:
    """An extracted figure that is not an amount, and the reviewer's screen.

    The parser's contract is that a field it cannot believe is left empty
    *and said out loud* — the same trade it already makes for a GSTIN that
    fails its checksum. A silent zero in a tax box is indistinguishable from
    an invoice that genuinely had no IGST.
    """

    def _parse(self, payload: dict):
        return invoice_parser._from_model_payload(payload, "some invoice text", "m")

    def test_an_out_of_range_figure_is_left_at_zero(self):
        result = self._parse({"taxable_value": "1E+100", "igst": 1e300})
        assert result.taxable_value == Decimal("0.00")
        assert result.igst == Decimal("0.00")

    def test_and_the_reviewer_is_told_it_was_dropped(self):
        result = self._parse({"taxable_value": 1e300})
        assert any("taxable value" in w for w in result.warnings)

    @pytest.mark.parametrize("payload", [{}, {"cess": None}, {"cess": ""}, {"cess": "  "}])
    def test_a_field_the_model_left_out_is_not_warned_about(self, payload):
        # A missing key is the ordinary case — most invoices have no cess —
        # and warning on all six of them would bury the one that matters. An
        # empty string is the same statement in a model that fills every key.
        result = self._parse({"taxable_value": "1000.00", **payload})
        assert not [w for w in result.warnings if "Discarded an" in w]
        assert result.taxable_value == Decimal("1000.00")

    def test_a_figure_that_fits_is_kept_without_comment(self):
        result = self._parse({"taxable_value": str(MONEY_MAX)})
        assert result.taxable_value == MONEY_MAX
        assert not [w for w in result.warnings if "Discarded an" in w]

    def test_a_box_filled_with_something_that_is_not_a_number_is_announced(self):
        # "not an amount" and "not a number" are different findings and the
        # reviewer is told which: one means the extractor read the right box
        # and misjudged the size, the other that it read the wrong box.
        readable = self._parse({"igst": "1E+100"})
        assert any("invalid igst" in w for w in readable.warnings)
        oversized = self._parse({"igst": 1e300})
        assert any("out-of-range igst" in w for w in oversized.warnings)


class TestTheHeuristicParser:
    """The fallback path, which runs whenever no model key is configured.

    It reads amounts off text with a regex, and a regex matching digits will
    happily match forty of them — an OCR artefact or a barcode line is enough.
    """

    def test_an_absurd_total_in_the_text_does_not_become_the_total(self):
        text = (
            "TAX INVOICE\n"
            "Invoice No: INV-2026-001\n"
            f"Taxable Value: {'9' * 40}\n"
            f"Grand Total: {'9' * 40}\n"
        )
        result = invoice_parser.parse_heuristic(text)
        assert result.taxable_value == Decimal("0.00")
        assert result.total_value == Decimal("0.00")

    def test_an_ordinary_total_is_still_read(self):
        text = "TAX INVOICE\nTaxable Value: 1,000.00\nGrand Total: 1,180.00\n"
        result = invoice_parser.parse_heuristic(text)
        assert result.taxable_value == Decimal("1000.00")
        assert result.total_value == Decimal("1180.00")
