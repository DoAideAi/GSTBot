"""Reconciliation's defensive edges: bad data, and the run that fails.

test_reconciliation.py covers the matching itself — what counts as the same
invoice, what the credit arithmetic does with it. This file covers what
happens when the inputs are not the clean case, which for a reconciliation
engine is most of the time: an invoice whose extraction produced neither a
GSTIN nor a number, a stored 2B whose JSON has been hand-edited, a finding
about a supplier nobody can identify, and the run that raises partway through.

The through-line is that none of these may lose a period. A reconciliation is
evidence for an ITC claim that may be questioned years later, so a run that
goes wrong has to leave a row saying so — a run that vanishes looks exactly
like a period nobody reconciled.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.models.gstr_return import GSTRReturn, ReturnType
from app.models.invoice import InvoiceStatus
from app.models.reconciliation_run import MatchCategory, ReconciliationRun, ReconciliationStatus
from app.models.supplier import Supplier
from app.services import reconciliation
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE
from tests.test_reconciliation import PERIOD, book, categories, import_2b, portal, save

# ---------------------------------------------------------------------------
# Invoices with nothing to identify them
# ---------------------------------------------------------------------------

class TestUnidentifiableInvoices:
    """Extraction failed on both identity fields. It still has to reconcile."""

    def test_two_invoices_with_no_gstin_and_no_number_are_not_duplicates(self):
        # Duplicate detection keys on (GSTIN, number). With both blank every
        # such invoice would collapse onto one key and the second would be
        # written off as a double claim — deleting a real credit because OCR
        # could not read a header.
        result = reconciliation.match(
            [
                book(id=1, counterparty_gstin=None, invoice_number=None),
                book(id=2, counterparty_gstin=None, invoice_number=None),
            ],
            [],
            period=PERIOD,
        )
        assert MatchCategory.DUPLICATE not in categories(result)
        assert categories(result) == [
            MatchCategory.MISSING_IN_2B,
            MatchCategory.MISSING_IN_2B,
        ]

    def test_an_empty_string_counts_as_blank_not_as_a_key(self):
        # OCR yields "" as often as it yields None.
        result = reconciliation.match(
            [
                book(id=1, counterparty_gstin="", invoice_number=""),
                book(id=2, counterparty_gstin="", invoice_number=""),
            ],
            [],
            period=PERIOD,
        )
        assert MatchCategory.DUPLICATE not in categories(result)

    def test_a_number_alone_is_still_enough_to_be_a_duplicate(self):
        # Only *both* fields blank disables the check. A missing GSTIN with a
        # real number is still the double-claim the check exists for.
        result = reconciliation.match(
            [
                book(id=1, counterparty_gstin=None, invoice_number="INV-2026-0042"),
                book(id=2, counterparty_gstin=None, invoice_number="INV-2026-0042"),
            ],
            [],
            period=PERIOD,
        )
        assert MatchCategory.DUPLICATE in categories(result)

    def test_a_gstin_alone_is_still_enough_to_be_a_duplicate(self):
        result = reconciliation.match(
            [
                book(id=1, invoice_number=None),
                book(id=2, invoice_number=None),
            ],
            [],
            period=PERIOD,
        )
        assert MatchCategory.DUPLICATE in categories(result)

    def test_an_unidentifiable_invoice_still_puts_its_credit_at_risk(self):
        # It cannot be matched, so the credit resting on it is unsupported.
        result = reconciliation.match(
            [book(id=1, counterparty_gstin=None, invoice_number=None)],
            [],
            period=PERIOD,
        )
        assert result.itc_at_risk == Decimal("81000.00")


class TestScoringWithoutASupplier:
    def test_a_finding_with_no_gstin_on_either_side_is_skipped(
        self, db_session, business
    ):
        # _score_suppliers keys on the GSTIN. A finding that has none belongs
        # to no supplier, and inventing a row for it would put an unnamed
        # entry in the user's supplier list.
        save(db_session, business.id, counterparty_gstin=None, invoice_number="NO-GSTIN-1")
        import_2b(db_session, business.id, [])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.status is ReconciliationStatus.COMPLETED
        assert run.report["suppliers"] == {}

    def test_the_run_still_counts_the_unattributable_invoice(
        self, db_session, business
    ):
        save(db_session, business.id, counterparty_gstin=None, invoice_number="NO-GSTIN-1")
        import_2b(db_session, business.id, [])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        assert run.total_invoices == 1
        assert run.missing_in_2b_count == 1

    def test_suppliers_that_can_be_identified_are_still_scored(
        self, db_session, business
    ):
        # The skip must not abort the loop and lose everyone after it. Scoring
        # only records against a supplier the tenant already has a row for, so
        # this one is created first.
        db_session.add(
            Supplier(
                business_id=business.id,
                gstin=SUPPLIER_GSTIN_OTHER_STATE,
                legal_name="Northwind Supplies",
            )
        )
        db_session.commit()

        save(db_session, business.id, counterparty_gstin=None, invoice_number="NO-GSTIN-1")
        save(db_session, business.id, invoice_number="INV-2026-0099")
        import_2b(db_session, business.id, [])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        assert SUPPLIER_GSTIN_OTHER_STATE in run.report["suppliers"]
        assert run.report["suppliers"][SUPPLIER_GSTIN_OTHER_STATE]["missing"] == 1


# ---------------------------------------------------------------------------
# Blocked credit that the supplier did declare
# ---------------------------------------------------------------------------

class TestBlockedCreditOnAMatchedInvoice:
    def test_a_matched_but_ineligible_invoice_claims_nothing(self):
        # s.17(5) credit is blocked whatever the portal says. Matching tells
        # the user the supplier filed it; it does not make the credit claimable.
        result = reconciliation.match(
            [book(itc_eligible=False)], [portal()], period=PERIOD
        )
        assert categories(result) == [MatchCategory.MATCHED]
        assert result.itc_claimed == Decimal("0.00")
        assert result.itc_at_risk == Decimal("0.00")

    def test_a_matched_reverse_charge_invoice_claims_nothing(self):
        # Reverse charge means the buyer pays the tax directly; there is no
        # supplier credit to reconcile even when the row is there.
        result = reconciliation.match(
            [book(reverse_charge=True)], [portal()], period=PERIOD
        )
        assert categories(result) == [MatchCategory.MATCHED]
        assert result.itc_claimed == Decimal("0.00")
        assert result.itc_at_risk == Decimal("0.00")

    def test_a_mismatched_but_ineligible_invoice_claims_nothing(self):
        # The figures differ *and* the credit is blocked: the user still wants
        # to see the mismatch, but no arithmetic follows from it.
        result = reconciliation.match(
            [book(itc_eligible=False)],
            [portal(igst=Decimal("70000.00"), total_value=Decimal("520000.00"))],
            period=PERIOD,
        )
        assert categories(result) == [MatchCategory.MISMATCHED]
        assert result.itc_claimed == Decimal("0.00")
        assert result.itc_at_risk == Decimal("0.00")

    def test_an_eligible_invoice_beside_it_is_unaffected(self):
        result = reconciliation.match(
            [book(id=1, itc_eligible=False), book(id=2, invoice_number="INV-2026-0099")],
            [portal(), portal(invoice_number="INV-2026-0099")],
            period=PERIOD,
        )
        assert result.itc_claimed == Decimal("81000.00")


# ---------------------------------------------------------------------------
# Which side of a finding each field is read off
# ---------------------------------------------------------------------------

class TestWhereAFindingsInvoiceDateComesFrom:
    """One key, filled from whichever side of the finding actually has it.

    The date is not a compared field — books and portal routinely disagree
    about it without that being a mismatch, because the buyer keys the date
    they received the invoice and the supplier keys the date they raised it.
    So it is reported rather than reconciled, and where it is read from is a
    decision: the books' copy when there is one, because that is the date the
    rest of the user's own records are filed under, and the portal's only when
    there is no invoice behind the finding at all.

    The key is always present either way. Every row on the reconciliation
    screen shows a date, and a finding that omitted the field would be the one
    row rendering blank.
    """

    def test_a_matched_finding_reports_the_date_the_books_hold(self):
        result = reconciliation.match(
            [book(invoice_date=date(2026, 4, 15))],
            [portal(invoice_date=date(2026, 4, 2))],
            period=PERIOD,
        )

        (finding,) = result.findings
        assert finding.category is MatchCategory.MATCHED
        assert finding.as_dict()["invoice_date"] == "2026-04-15"

    def test_a_finding_with_no_invoice_behind_it_reports_the_portals_date(self):
        # In the 2B and in no purchase register: there is no books' copy to
        # prefer, and the statement's date is the only one there is.
        result = reconciliation.match(
            [], [portal(invoice_date=date(2026, 4, 2))], period=PERIOD
        )

        (finding,) = result.findings
        assert finding.category is MatchCategory.MISSING_IN_BOOKS
        assert finding.as_dict()["invoice_date"] == "2026-04-02"

    def test_a_portal_row_with_no_date_still_carries_the_key(self):
        result = reconciliation.match([], [portal(invoice_date=None)], period=PERIOD)

        assert result.findings[0].as_dict()["invoice_date"] is None


# ---------------------------------------------------------------------------
# Reading a stored 2B back
# ---------------------------------------------------------------------------

def _stored_return(db_session, business_id, data) -> GSTRReturn:
    gstr_return = GSTRReturn(
        business_id=business_id,
        return_type=ReturnType.GSTR2B,
        period=PERIOD,
        data=data,
    )
    db_session.add(gstr_return)
    db_session.commit()
    db_session.refresh(gstr_return)
    return gstr_return


class TestRecordsFromReturn:
    def test_a_well_formed_row_round_trips(self, db_session, business):
        stored = _stored_return(
            db_session,
            business.id,
            {
                "invoices": [
                    {
                        "supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE,
                        "invoice_number": "INV-2026-0042",
                        "invoice_date": "2026-04-15",
                        "taxable_value": "450000.00",
                        "igst": "81000.00",
                        "total_value": "531000.00",
                    }
                ]
            },
        )
        records = reconciliation.records_from_return(stored)
        assert len(records) == 1
        assert records[0].invoice_number == "INV-2026-0042"
        assert records[0].igst == Decimal("81000.00")
        assert records[0].invoice_date == date(2026, 4, 15)

    @pytest.mark.parametrize(
        "junk",
        [
            ["not a dict"],
            [None],
            [42],
            [["nested", "list"]],
        ],
    )
    def test_non_dict_rows_are_skipped(self, db_session, business, junk):
        # The block is JSON in a column: a migration or a hand-edit can put
        # anything in it, and one bad row must not lose the whole statement.
        stored = _stored_return(db_session, business.id, {"invoices": junk})
        assert reconciliation.records_from_return(stored) == []

    def test_a_good_row_survives_beside_a_bad_one(self, db_session, business):
        stored = _stored_return(
            db_session,
            business.id,
            {
                "invoices": [
                    "garbage",
                    {"supplier_gstin": SUPPLIER_GSTIN_OTHER_STATE, "invoice_number": "INV-1"},
                    None,
                ]
            },
        )
        records = reconciliation.records_from_return(stored)
        assert [record.invoice_number for record in records] == ["INV-1"]

    @pytest.mark.parametrize(
        "data",
        [None, {}, {"invoices": None}, {"invoices": []}, {"other": "block"}, "a string"],
    )
    def test_a_missing_or_unusable_block_yields_no_records(
        self, db_session, business, data
    ):
        stored = _stored_return(db_session, business.id, data)
        assert reconciliation.records_from_return(stored) == []

    def test_missing_amounts_default_to_zero_rather_than_raising(
        self, db_session, business
    ):
        stored = _stored_return(
            db_session, business.id, {"invoices": [{"invoice_number": "INV-1"}]}
        )
        record = reconciliation.records_from_return(stored)[0]
        assert record.taxable_value == Decimal("0")
        assert record.total_value == Decimal("0")
        assert record.igst == Decimal("0")

    def test_non_numeric_money_strings_fall_back_to_zero(
        self, db_session, business
    ):
        stored = _stored_return(
            db_session,
            business.id,
            {
                "invoices": [
                    {
                        "invoice_number": "INV-1",
                        "taxable_value": "not a number",
                        "igst": "N/A",
                        "cgst": "---",
                        "sgst": "pending",
                        "cess": "TBD",
                        "total_value": "err",
                    }
                ]
            },
        )
        record = reconciliation.records_from_return(stored)[0]
        assert record.taxable_value == Decimal("0")
        assert record.igst == Decimal("0")
        assert record.cgst == Decimal("0")
        assert record.sgst == Decimal("0")
        assert record.cess == Decimal("0")
        assert record.total_value == Decimal("0")

    def test_an_unparseable_date_becomes_none_rather_than_raising(
        self, db_session, business
    ):
        stored = _stored_return(
            db_session,
            business.id,
            {"invoices": [{"invoice_number": "INV-1", "invoice_date": "not a date"}]},
        )
        assert reconciliation.records_from_return(stored)[0].invoice_date is None

    def test_the_itc_flag_defaults_to_available(self, db_session, business):
        # Absent means the portal did not restrict it; defaulting the other
        # way would silently move every credit into "at risk".
        stored = _stored_return(
            db_session, business.id, {"invoices": [{"invoice_number": "INV-1"}]}
        )
        assert reconciliation.records_from_return(stored)[0].itc_available is True

    def test_reverse_charge_defaults_to_off_when_the_row_does_not_say(
        self, db_session, business
    ):
        # The mirror of the flag above, and it defaults the other way for the
        # same reason: absent means the portal said nothing, and the ordinary
        # supply is forward charge. Defaulting to True would take every credit
        # in a statement that omits the field out of `claims_credit` and out of
        # the period's eligible pool — a business shown no ITC at all on a 2B
        # that granted it in full.
        stored = _stored_return(
            db_session, business.id, {"invoices": [{"invoice_number": "INV-1"}]}
        )
        assert reconciliation.records_from_return(stored)[0].reverse_charge is False

    def test_a_stated_reverse_charge_flag_is_read_rather_than_assumed(
        self, db_session, business
    ):
        stored = _stored_return(
            db_session,
            business.id,
            {"invoices": [{"invoice_number": "INV-1", "reverse_charge": True}]},
        )
        assert reconciliation.records_from_return(stored)[0].reverse_charge is True

    def test_the_rate_breakdown_survives_the_round_trip(self, db_session, business):
        # The per-rate split is what `filing` builds the rate-wise tables from.
        # Dropped here it is not recoverable from the totals beside it — 18% on
        # one line and 5% on another add to the same tax as one line at neither.
        stored = _stored_return(
            db_session,
            business.id,
            {
                "invoices": [
                    {
                        "invoice_number": "INV-1",
                        "rate_items": [
                            {"rate": "18", "taxable_value": "450000.00"},
                            {"rate": "5", "taxable_value": "10000.00"},
                        ],
                    }
                ]
            },
        )
        record = reconciliation.records_from_return(stored)[0]
        assert [item["rate"] for item in record.rate_items] == ["18", "5"]

    def test_a_row_with_no_rate_breakdown_gets_an_empty_list_not_none(
        self, db_session, business
    ):
        # A CSV export carries no rate split at all, and every reader of this
        # field iterates it. `None` would raise on a statement that is not
        # malformed, merely less detailed.
        stored = _stored_return(
            db_session, business.id, {"invoices": [{"invoice_number": "INV-1"}]}
        )
        assert reconciliation.records_from_return(stored)[0].rate_items == []


# ---------------------------------------------------------------------------
# A run that goes wrong
# ---------------------------------------------------------------------------

class TestAFailedRun:
    def test_the_run_row_records_the_failure(
        self, monkeypatch, db_session, business
    ):
        # The run row is the error channel: nobody is watching the return
        # value, and a period with no row looks like one nobody reconciled.
        save(db_session, business.id)
        import_2b(db_session, business.id, [portal()])
        monkeypatch.setattr(
            reconciliation,
            "match",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("matcher exploded")),
        )

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.status is ReconciliationStatus.FAILED
        assert "matcher exploded" in run.error
        assert run.completed_at is not None

    def test_the_failure_does_not_propagate_to_the_caller(
        self, monkeypatch, db_session, business
    ):
        save(db_session, business.id)
        import_2b(db_session, business.id, [portal()])
        monkeypatch.setattr(
            reconciliation,
            "match",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        # No pytest.raises: the point is that this returns.
        assert reconciliation.run_reconciliation(db_session, business.id, PERIOD) is not None

    def test_the_failed_run_is_persisted_and_readable(
        self, monkeypatch, db_session, business
    ):
        save(db_session, business.id)
        import_2b(db_session, business.id, [portal()])
        monkeypatch.setattr(
            reconciliation,
            "match",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        run_id = reconciliation.run_reconciliation(db_session, business.id, PERIOD).id

        db_session.expire_all()
        from app.models.reconciliation_run import ReconciliationRun

        reloaded = db_session.get(ReconciliationRun, run_id)
        assert reloaded.status is ReconciliationStatus.FAILED

    def test_a_very_long_error_is_truncated_to_fit_the_column(
        self, monkeypatch, db_session, business
    ):
        save(db_session, business.id)
        import_2b(db_session, business.id, [portal()])
        monkeypatch.setattr(
            reconciliation,
            "match",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x" * 5000)),
        )
        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        assert len(run.error) == 2000

    def test_a_missing_2b_still_raises_rather_than_recording_a_failure(
        self, db_session, business
    ):
        # This one is the caller's fault and is fixable by importing a 2B, so
        # it is an exception rather than a failed run the user has to read.
        with pytest.raises(reconciliation.NoGSTR2BImported):
            reconciliation.run_reconciliation(db_session, business.id, "2026-05")

    def test_a_failed_run_does_not_hide_the_previous_good_one(
        self, monkeypatch, db_session, business
    ):
        # Runs append rather than update, so the last successful reconciliation
        # of a period survives a later failure.
        save(db_session, business.id)
        import_2b(db_session, business.id, [portal()])
        good = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        assert good.status is ReconciliationStatus.COMPLETED

        monkeypatch.setattr(
            reconciliation,
            "match",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        bad = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert bad.id != good.id
        db_session.expire_all()
        from app.models.reconciliation_run import ReconciliationRun

        assert (
            db_session.get(ReconciliationRun, good.id).status
            is ReconciliationStatus.COMPLETED
        )


class TestAFailedRunLeavesNothingBehind:
    """A run that dies partway through must not half-reconcile the books.

    The tests above all fail inside ``match``, which is before anything has
    been written. The dangerous failure is the later one: ``_apply_statuses``
    has already rewritten every matched invoice's status, and
    ``_score_suppliers`` rewrites suppliers one at a time. Committing that
    beside a row saying the run failed leaves invoices reading MATCHED against
    a statement nobody finished comparing them to — and the next ITC summary
    reads those statuses as evidence.
    """

    @staticmethod
    def _explode_after_matching(monkeypatch, where: str):
        monkeypatch.setattr(
            reconciliation,
            where,
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("scoring exploded")),
        )

    def test_invoice_statuses_are_rolled_back(self, monkeypatch, db_session, business):
        invoice = save(db_session, business.id, invoice_number="INV-1")
        import_2b(db_session, business.id, [portal(invoice_number="INV-1")])
        before = invoice.status
        self._explode_after_matching(monkeypatch, "_score_suppliers")

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.status is ReconciliationStatus.FAILED
        db_session.expire_all()
        from app.models.invoice import Invoice

        # Not MATCHED: _apply_statuses had already set that before the failure.
        assert db_session.get(Invoice, invoice.id).status is before

    def test_supplier_scores_are_rolled_back(self, monkeypatch, db_session, business):
        supplier = Supplier(
            business_id=business.id,
            gstin=SUPPLIER_GSTIN_OTHER_STATE,
            compliance_score=90,
            filing_history=[],
        )
        db_session.add(supplier)
        db_session.commit()
        save(db_session, business.id, invoice_number="INV-1")
        import_2b(db_session, business.id, [portal(invoice_number="INV-1")])

        # Fail *after* the scoring pass has written the supplier's history.
        real_score = reconciliation._score_suppliers

        def score_then_die(*args, **kwargs):
            real_score(*args, **kwargs)
            raise RuntimeError("exploded after scoring")

        monkeypatch.setattr(reconciliation, "_score_suppliers", score_then_die)

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.status is ReconciliationStatus.FAILED
        db_session.expire_all()
        reloaded = db_session.get(Supplier, supplier.id)
        assert reloaded.compliance_score == 90
        assert reloaded.filing_history == []
        assert reloaded.last_filed_period is None

    def test_the_failure_receipt_still_survives_the_rollback(
        self, monkeypatch, db_session, business
    ):
        """The rollback discards the run row too, so it has to be re-recorded.

        A period with no row at all looks exactly like one nobody reconciled,
        which is the ambiguity the row exists to remove.
        """
        save(db_session, business.id, invoice_number="INV-1")
        import_2b(db_session, business.id, [portal(invoice_number="INV-1")])
        self._explode_after_matching(monkeypatch, "_score_suppliers")

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        run_id = run.id

        db_session.expire_all()
        from app.models.reconciliation_run import ReconciliationRun

        reloaded = db_session.get(ReconciliationRun, run_id)
        assert reloaded is not None
        assert reloaded.status is ReconciliationStatus.FAILED
        assert "scoring exploded" in reloaded.error
        assert reloaded.period == PERIOD
        assert reloaded.business_id == business.id
        assert reloaded.started_at is not None
        assert reloaded.completed_at is not None

    def test_a_successful_run_still_commits_its_statuses(self, db_session, business):
        """The guard against over-correcting: the good path must still write."""
        invoice = save(db_session, business.id, invoice_number="INV-1")
        import_2b(db_session, business.id, [portal(invoice_number="INV-1")])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.status is ReconciliationStatus.COMPLETED
        db_session.expire_all()
        from app.models.invoice import Invoice

        assert db_session.get(Invoice, invoice.id).status is InvoiceStatus.MATCHED


# ---------------------------------------------------------------------------
# What the run costs the database
# ---------------------------------------------------------------------------

def _valid_gstins(count: int) -> list[str]:
    """*count* distinct GSTINs that pass the check digit."""
    from app.services import gstin as gstin_service

    out = []
    for index in range(count):
        body = f"29AAGCB{1000 + index}J1Z"
        out.append(body + gstin_service.compute_check_digit(body))
    return out


class TestScoringDoesNotQueryPerSupplier:
    """The lookup was one statement per distinct counterparty in the period.

    A period is scored against every supplier appearing in the books or in the
    2B, so the count grew with the tenant rather than with anything about the
    work: a business buying from three hundred suppliers paid three hundred
    round trips inside a request someone is waiting on. On SQLite in a test
    that is invisible; against a Postgres across a network it is the run.
    """

    def statements(self, db, monkeypatch) -> list[str]:
        """Every SELECT against ``suppliers`` issued while the run executes.

        Both spellings are wrapped. The version this replaces asked with
        ``scalar`` and the batched one asks with ``scalars``, so watching
        either alone would count the wrong code's zero.
        """
        seen: list[str] = []

        for name in ("scalar", "scalars"):
            original = getattr(db, name)

            def _record(statement, *args, _original=original, **kwargs):
                if "FROM suppliers" in str(statement):
                    seen.append(str(statement))
                return _original(statement, *args, **kwargs)

            monkeypatch.setattr(db, name, _record)
        return seen

    def run_with(self, db, business, supplier_count, monkeypatch):
        gstins = _valid_gstins(supplier_count)
        for index, gstin in enumerate(gstins):
            db.add(Supplier(business_id=business.id, gstin=gstin))
            save(
                db,
                business.id,
                counterparty_gstin=gstin,
                invoice_number=f"INV-{index}",
            )
        import_2b(db, business.id, [portal(invoice_number="NONE-OF-THEM")])

        seen = self.statements(db, monkeypatch)
        run = reconciliation.run_reconciliation(db, business.id, PERIOD)
        assert run.status is ReconciliationStatus.COMPLETED
        return seen

    def test_thirty_suppliers_take_one_lookup_not_thirty(
        self, db_session, business, monkeypatch
    ):
        seen = self.run_with(db_session, business, 30, monkeypatch)
        assert len(seen) == 1

    def test_every_supplier_is_still_found_and_scored(self, db_session, business):
        gstins = _valid_gstins(30)
        for index, gstin in enumerate(gstins):
            db_session.add(Supplier(business_id=business.id, gstin=gstin))
            save(
                db_session,
                business.id,
                counterparty_gstin=gstin,
                invoice_number=f"INV-{index}",
            )
        import_2b(db_session, business.id, [portal(invoice_number="NONE-OF-THEM")])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        # Batching must not lose a supplier: each one filed nothing, so each
        # one carries a period of history saying so.
        assert set(run.report["suppliers"]) == set(gstins)
        db_session.expire_all()
        for gstin in gstins:
            supplier = db_session.query(Supplier).filter_by(gstin=gstin).one()
            assert supplier.missing_invoices == 1

    def test_more_suppliers_than_the_chunk_still_take_one_pass_each(
        self, db_session, business, monkeypatch
    ):
        # The chunk exists because every driver bounds a statement's
        # parameters. Shrunk here so the boundary is reachable in a test
        # instead of needing five hundred suppliers to cross it.
        monkeypatch.setattr(reconciliation, "_SUPPLIER_LOOKUP_CHUNK", 10)
        seen = self.run_with(db_session, business, 25, monkeypatch)
        assert len(seen) == 3


# ---------------------------------------------------------------------------
# What a statement reaches back into the other periods for
# ---------------------------------------------------------------------------

class TestWhichInvoicesAStatementCarriesIn:
    """`_carried_invoices` on its own, rather than through a whole run.

    Through a run this lookup is nearly invisible: an invoice it reaches for by
    mistake finds no counterpart in the statement and :func:`match` drops it
    without reporting anything, so the run's counts, findings and statuses come
    out identical whether the lookup returned one row or fifty. That is exactly
    what makes it worth asserting directly — the query it builds is a widening
    of a reconciliation across periods, and the only thing keeping it from
    dragging in a supplier's entire history is the number filter underneath it.

    Two halves do two different jobs and neither is sufficient alone: the GSTIN
    narrows the query, the number decides which rows survive it. `TestASupplierWhoFilesLate`
    in test_reconciliation.py covers what the run then does with them.
    """

    LATE = "2026-03"

    def _booked(self, db_session, business, number, **kwargs):
        kwargs.setdefault("period", self.LATE)
        kwargs.setdefault("invoice_date", date(2026, 3, 10))
        return save(db_session, business.id, invoice_number=number, **kwargs)

    def _declared(self, number, **kwargs):
        """A statement row for an earlier period — the late filing's shape."""
        return portal(
            invoice_number=number,
            period=self.LATE,
            invoice_date=date(2026, 3, 10),
            **kwargs,
        )

    def _carried(self, db_session, business, records):
        return reconciliation._carried_invoices(
            db_session, business.id, records, PERIOD
        )

    def test_only_the_invoices_the_statement_names_are_reached_for(
        self, db_session, business
    ):
        # The GSTIN query returns everything this supplier ever sold us. What
        # comes back from it is whichever of those rows the statement actually
        # names — invert that filter and a run for May carries in a supplier's
        # whole back catalogue.
        self._booked(db_session, business, "LATE-1")
        self._booked(db_session, business, "MARCH-9", invoice_date=date(2026, 3, 4))

        carried = self._carried(db_session, business, [self._declared("LATE-1")])

        assert [row.invoice_number for row in carried] == ["LATE-1"]

    def test_a_number_the_supplier_punctuated_differently_is_still_reached_for(
        self, db_session, business
    ):
        # The buyer's data entry and the supplier's portal entry punctuate the
        # same number differently, which is why `match` has a second pass at
        # all. Requiring both the exact and the loose form to agree here would
        # leave the late filing unfound and back to being reported as an
        # invoice the business never booked.
        self._booked(db_session, business, "LATE-1")

        carried = self._carried(db_session, business, [self._declared("late/001")])

        assert [row.invoice_number for row in carried] == ["LATE-1"]

    def test_an_invoice_with_no_number_of_its_own_is_left_where_it_is(
        self, db_session, business
    ):
        # OCR loses a number as readily as it loses a GSTIN, and the row is
        # still in the books with the supplier on it — so this query returns
        # it and the filter has to decide. Nothing identifies it as one of the
        # ones the statement declares, so it stays in its own period.
        self._booked(db_session, business, None)
        self._booked(db_session, business, "LATE-1")

        carried = self._carried(db_session, business, [self._declared("LATE-1")])

        assert [row.invoice_number for row in carried] == ["LATE-1"]

    def test_they_come_back_oldest_first(self, db_session, business):
        # Same order `_book_invoices` returns this period's own in, and for the
        # same reason: findings are read down the page in the order the
        # business incurred them, not the order rows happened to be inserted.
        newer = self._booked(db_session, business, "LATE-1", invoice_date=date(2026, 3, 20))
        older = self._booked(db_session, business, "LATE-2", invoice_date=date(2026, 3, 5))

        carried = self._carried(
            db_session,
            business,
            [self._declared("LATE-1"), self._declared("LATE-2")],
        )

        assert [row.id for row in carried] == [older.id, newer.id]

    def test_an_invoice_with_no_date_sorts_last_rather_than_raising(
        self, db_session, business
    ):
        # A date the parser never found cannot be ordered against one it did.
        # Sorted last rather than first: an undated row is not evidence that it
        # is the oldest thing here, and it must not head a list a user reads as
        # chronological.
        dated = self._booked(db_session, business, "LATE-1", invoice_date=date(2026, 3, 5))
        undated = self._booked(db_session, business, "LATE-2", invoice_date=None)

        carried = self._carried(
            db_session,
            business,
            [self._declared("LATE-1"), self._declared("LATE-2")],
        )

        assert [row.id for row in carried] == [dated.id, undated.id]

    def test_a_statement_naming_no_invoice_numbers_never_reaches_the_books(
        self, db_session, business, monkeypatch
    ):
        # Half-identified rows are ordinary in a portal export. With no number
        # among them there is nothing for the filter to keep, so the query is
        # skipped rather than run and thrown away — and skipping it is the
        # point: it is an unindexed scan of every purchase this tenant has ever
        # made from the suppliers named, inside a request someone is waiting on.
        self._booked(db_session, business, "LATE-1")

        statements: list[str] = []
        original = db_session.scalars

        def _record(statement, *args, **kwargs):
            statements.append(str(statement))
            return original(statement, *args, **kwargs)

        monkeypatch.setattr(db_session, "scalars", _record)

        assert self._carried(db_session, business, [self._declared(None)]) == []
        assert [s for s in statements if "FROM invoices" in s] == []


# ---------------------------------------------------------------------------
# What a run writes onto the supplier
# ---------------------------------------------------------------------------

class TestTheObservationARunRecords:
    """The tally `_score_suppliers` writes, and what it deliberately leaves out.

    Two tests asserted the *score* this produces and none asserted the record
    it is computed from, which is the wrong way round: the score is a weighted
    number that moves for a dozen reasons, and the counters under it are the
    facts. A mutation run bore that out — the tally increments, the
    missing-in-books exclusion, the earliest-filing-date rule, the lateness
    threshold and the re-run replacement could all be inverted with the whole
    suite still green.

    None of these is cosmetic. `total_invoices`, `matched_invoices`,
    `mismatched_invoices`, `missing_invoices` and `late_filings` are the entire
    evidence base `supplier_score` weighs, and what it produces is the
    provision a business is advised to hold against a supplier's credit. A
    counter that is quietly one out moves real money on the strength of a
    number nobody re-derives.
    """

    def _supplier(self, db_session, business, **kwargs):
        supplier = Supplier(business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE, **kwargs)
        db_session.add(supplier)
        db_session.commit()
        return supplier

    def _reload(self, db_session):
        db_session.expire_all()
        return db_session.query(Supplier).filter_by(gstin=SUPPLIER_GSTIN_OTHER_STATE).one()

    def test_the_period_s_observation_counts_each_outcome_separately(
        self, db_session, business
    ):
        self._supplier(db_session, business)
        save(db_session, business.id, invoice_number="M-1")
        save(db_session, business.id, invoice_number="X-1", taxable_value=Decimal("1.00"))
        save(db_session, business.id, invoice_number="G-1")
        import_2b(
            db_session,
            business.id,
            [portal(invoice_number="M-1"), portal(invoice_number="X-1")],
        )

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        observation = self._reload(db_session).filing_history[-1]
        assert observation["period"] == PERIOD
        assert observation["matched"] == 1
        assert observation["mismatched"] == 1
        assert observation["missing"] == 1

    def test_an_invoice_only_the_supplier_declared_is_not_evidence_against_them(
        self, db_session, business
    ):
        # MISSING_IN_BOOKS is the buyer not having booked what the supplier
        # filed. The supplier did their part, so counting it would mark them
        # down for the buyer's omission — and it is the one category excluded
        # from the tally before `total` is incremented.
        self._supplier(db_session, business)
        import_2b(db_session, business.id, [portal(invoice_number="ONLY-2B")])

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        observation = self._reload(db_session).filing_history[-1]
        assert observation == {"period": PERIOD, "matched": 0, "mismatched": 0, "missing": 0}

    def test_the_counters_total_the_whole_history_not_just_this_period(
        self, db_session, business
    ):
        # The counters are re-derived from the stored history on every run,
        # which is what stops a re-run compounding them.
        self._supplier(
            db_session,
            business,
            filing_history=[
                {"period": "2026-02", "matched": 2, "mismatched": 1, "missing": 3},
            ],
        )
        save(db_session, business.id, invoice_number="M-1")
        import_2b(db_session, business.id, [portal(invoice_number="M-1")])

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        supplier = self._reload(db_session)
        assert supplier.matched_invoices == 3
        assert supplier.mismatched_invoices == 1
        assert supplier.missing_invoices == 3
        # Total is the three outcomes added, not a fourth stored number.
        assert supplier.total_invoices == 7

    def test_re_running_a_period_replaces_its_observation(self, db_session, business):
        # Periods are reconciled repeatedly as suppliers file late. Appending
        # rather than replacing would count the same invoices once per run and
        # let a supplier's evidence base grow by re-reading one statement.
        self._supplier(db_session, business)
        save(db_session, business.id, invoice_number="M-1")
        import_2b(db_session, business.id, [portal(invoice_number="M-1")])

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        supplier = self._reload(db_session)
        assert [entry["period"] for entry in supplier.filing_history] == [PERIOD]
        assert supplier.matched_invoices == 1
        assert supplier.total_invoices == 1

    def test_the_history_is_bounded_at_three_years(self, db_session, business):
        # An audit trail for the score, not a ledger. 36 monthly observations
        # is the window the score weighs; the oldest fall off the front.
        self._supplier(
            db_session,
            business,
            filing_history=[
                {"period": f"{year}-{month:02d}", "matched": 1, "mismatched": 0, "missing": 0}
                for year in (2020, 2021, 2022, 2023)
                for month in range(1, 13)
            ],
        )
        save(db_session, business.id, invoice_number="M-1")
        import_2b(db_session, business.id, [portal(invoice_number="M-1")])

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        history = self._reload(db_session).filing_history
        assert len(history) == 36
        # Sorted by period, so it is the oldest that were dropped and this
        # period that survived.
        assert history[-1]["period"] == PERIOD
        assert history[0]["period"] == "2021-02"

    def test_a_supplier_who_matched_nothing_is_recorded_as_having_matched_nothing(
        self, db_session, business
    ):
        # Zero is a figure here, not an absence. Every counter is rebuilt from
        # the history with `int(entry.get(...) or 0)`, and the supplier who
        # filed nothing is the one whose `matched` is missing-shaped — read as
        # anything but zero it becomes the evidence `supplier_score` weighs
        # most heavily, and the worst filer a business has comes back scored as
        # one of its better ones.
        self._supplier(db_session, business)
        save(db_session, business.id, invoice_number="G-1")
        save(db_session, business.id, invoice_number="G-2")
        import_2b(db_session, business.id, [])

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        supplier = self._reload(db_session)
        assert supplier.matched_invoices == 0
        assert supplier.missing_invoices == 2
        # The total is the three outcomes added, so a matched that is not zero
        # shows up here too.
        assert supplier.total_invoices == 2

    def test_a_supplier_who_matched_nothing_is_scored_as_the_risk_they_are(
        self, db_session, business
    ):
        # The counters above are not decoration: this is what they buy.
        self._supplier(db_session, business)
        save(db_session, business.id, invoice_number="G-1")
        import_2b(db_session, business.id, [])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.report["suppliers"][SUPPLIER_GSTIN_OTHER_STATE]["matched"] == 0
        assert self._reload(db_session).compliance_score == 0

    def test_a_supplier_with_no_row_of_their_own_is_skipped_not_created(
        self, db_session, business
    ):
        # `_score_suppliers` scores suppliers the business already has a row
        # for. A GSTIN seen only in a statement is not silently promoted.
        save(db_session, business.id, invoice_number="M-1")
        import_2b(db_session, business.id, [portal(invoice_number="M-1")])

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert db_session.query(Supplier).filter_by(gstin=SUPPLIER_GSTIN_OTHER_STATE).count() == 0


class TestWhenTheSupplierFiled:
    """The filing date, the delay derived from it, and what counts as late.

    GSTR-1 for a period is due on the 11th of the following month, so for
    2026-04 that is 2026-05-11. The delay is what `supplier_score` weighs as
    timeliness, and it is signed: a supplier who filed early must not be
    recorded as having filed late by the same number of days.
    """

    DUE = date(2026, 5, 11)

    def _supplier(self, db_session, business):
        supplier = Supplier(business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE)
        db_session.add(supplier)
        db_session.commit()
        return supplier

    def _reload(self, db_session):
        db_session.expire_all()
        return db_session.query(Supplier).filter_by(gstin=SUPPLIER_GSTIN_OTHER_STATE).one()

    def _run_with_filing_date(self, db_session, business, *filing_dates):
        for index in range(len(filing_dates)):
            save(db_session, business.id, invoice_number=f"F-{index}")
        import_2b(
            db_session,
            business.id,
            [
                portal(invoice_number=f"F-{index}", supplier_filing_date=filed_on)
                for index, filed_on in enumerate(filing_dates)
            ],
        )
        reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        return self._reload(db_session)

    def test_filing_after_the_due_date_is_a_positive_delay(self, db_session, business):
        self._supplier(db_session, business)
        supplier = self._run_with_filing_date(db_session, business, date(2026, 5, 18))

        assert supplier.filing_history[-1]["filing_delay_days"] == 7
        assert supplier.filing_history[-1]["filed_on"] == "2026-05-18"
        assert supplier.late_filings == 1

    def test_filing_early_is_a_negative_delay_and_not_a_late_filing(
        self, db_session, business
    ):
        # Flipping the subtraction would turn a supplier who filed a week early
        # into one who filed a week late, and mark down the score of the most
        # reliable suppliers a business has.
        self._supplier(db_session, business)
        supplier = self._run_with_filing_date(db_session, business, date(2026, 5, 4))

        assert supplier.filing_history[-1]["filing_delay_days"] == -7
        assert supplier.late_filings == 0

    def test_filing_on_the_due_date_itself_is_not_late(self, db_session, business):
        # The boundary. A return filed on the 11th is filed on time; `> 0` is
        # what says so, and `>= 0` would make every punctual supplier late.
        self._supplier(db_session, business)
        supplier = self._run_with_filing_date(db_session, business, self.DUE)

        assert supplier.filing_history[-1]["filing_delay_days"] == 0
        assert supplier.late_filings == 0

    def test_filing_one_day_late_is_a_late_filing(self, db_session, business):
        # The other edge of the same threshold. `test_filing_on_the_due_date_itself_is_not_late`
        # holds the bottom of it; without this one the count could just as well
        # be "late by more than a day" — which sounds like a rounding
        # allowance and is not one. The 12th is a month's credit claimed in the
        # wrong period, and it is the commonest lateness there is.
        self._supplier(db_session, business)
        supplier = self._run_with_filing_date(db_session, business, date(2026, 5, 12))

        assert supplier.filing_history[-1]["filing_delay_days"] == 1
        assert supplier.late_filings == 1

    def test_the_earliest_date_in_the_statement_is_the_one_kept(
        self, db_session, business
    ):
        # A statement carries one filing date per supplier, but rows are read
        # one at a time and a supplier appears on many. The earliest is the one
        # the buyer's claim depends on — that is when the credit became
        # available — so it wins regardless of the order the rows arrive in.
        self._supplier(db_session, business)
        supplier = self._run_with_filing_date(
            db_session, business, date(2026, 5, 20), date(2026, 5, 13), date(2026, 5, 25)
        )

        assert supplier.filing_history[-1]["filed_on"] == "2026-05-13"
        assert supplier.filing_history[-1]["filing_delay_days"] == 2

    def test_a_statement_with_no_filing_date_records_no_delay(self, db_session, business):
        # Nothing is guessed from its absence: no delay recorded, and the
        # supplier is not marked late for a date the portal did not state.
        self._supplier(db_session, business)
        supplier = self._run_with_filing_date(db_session, business, None)

        assert "filing_delay_days" not in supplier.filing_history[-1]
        assert "filed_on" not in supplier.filing_history[-1]
        assert supplier.late_filings == 0
        assert supplier.last_seen_at is None

    def test_the_filing_date_becomes_when_the_supplier_was_last_seen(
        self, db_session, business
    ):
        # The suppliers screen falls back to this when a supplier has never
        # filed within the window the score covers.
        self._supplier(db_session, business)
        supplier = self._run_with_filing_date(db_session, business, date(2026, 5, 18))

        assert supplier.last_seen_at == date(2026, 5, 18)
        assert supplier.last_filed_period == PERIOD

    # -- M2: "Last filed" is a filing, not a reconciliation ------------------

    def _run_period(self, db_session, business, period, *, filed, filed_on=None):
        """Reconcile *period* with one book invoice from the supplier, which
        the 2B carries when *filed* and leaves out when not."""
        year, month = (int(part) for part in period.split("-"))
        dated = date(year, month, 10)
        number = f"P-{period}"
        save(db_session, business.id, invoice_number=number, invoice_date=dated, period=period)
        records = [
            portal(
                invoice_number=number if filed else f"OTHER-{period}",
                supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE if filed else SUPPLIER_GSTIN_SAME_STATE,
                invoice_date=dated,
                period=period,
                supplier_filing_date=filed_on,
            )
        ]
        import_2b(db_session, business.id, records, period=period)
        reconciliation.run_reconciliation(db_session, business.id, period)
        return self._reload(db_session)

    def test_a_month_the_supplier_filed_nothing_is_not_their_last_filing(
        self, db_session, business
    ):
        """Every invoice "never filed" this month used to read "Last filed:
        this month" — the opposite of the warning the column exists for."""
        self._supplier(db_session, business)
        supplier = self._run_period(db_session, business, "2026-04", filed=False)

        assert supplier.missing_invoices == 1
        assert supplier.last_filed_period is None

    def test_the_last_filing_survives_a_later_month_with_none(self, db_session, business):
        self._supplier(db_session, business)
        self._run_period(db_session, business, "2026-04", filed=True)
        supplier = self._run_period(db_session, business, "2026-05", filed=False)

        assert supplier.last_filed_period == "2026-04"

    def test_re_running_an_older_month_does_not_walk_the_date_backwards(
        self, db_session, business
    ):
        self._supplier(db_session, business)
        self._run_period(
            db_session, business, "2026-05", filed=True, filed_on=date(2026, 6, 10)
        )
        supplier = self._run_period(
            db_session, business, "2026-04", filed=True, filed_on=date(2026, 5, 10)
        )

        assert supplier.last_filed_period == "2026-05"
        assert supplier.last_seen_at == date(2026, 6, 10)


# ---------------------------------------------------------------------------
# GB034: Concurrent reconciliation guard
# ---------------------------------------------------------------------------

class TestConcurrentReconciliationGuard:
    """A second run for the same period must be rejected while one is RUNNING."""

    def test_running_run_blocks_a_second(self, db_session, business):
        import_2b(db_session, business.id, [portal()])
        stuck = ReconciliationRun(
            business_id=business.id,
            period=PERIOD,
            status=ReconciliationStatus.RUNNING,
        )
        db_session.add(stuck)
        db_session.commit()

        with pytest.raises(reconciliation.ConcurrentReconciliation):
            reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    def test_a_period_claimed_by_another_session_is_refused(
        self, db_session, business, monkeypatch
    ):
        """What a concurrent run looks like in production.

        Its RUNNING row is flushed and never committed, so the check above can
        never see it from another session; the advisory claim is what can.
        """
        import_2b(db_session, business.id, [portal()])
        monkeypatch.setattr(reconciliation, "_claim_period", lambda *_: False)

        with pytest.raises(reconciliation.ConcurrentReconciliation):
            reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        db_session.rollback()

        assert db_session.query(ReconciliationRun).filter_by(business_id=business.id).count() == 0

    def test_sqlite_always_gets_the_claim(self, db_session, business):
        assert reconciliation._claim_period(db_session, business.id, PERIOD) is True

    def test_completed_run_does_not_block(self, db_session, business):
        import_2b(db_session, business.id, [portal()])
        done = ReconciliationRun(
            business_id=business.id,
            period=PERIOD,
            status=ReconciliationStatus.COMPLETED,
        )
        db_session.add(done)
        db_session.commit()

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        assert run.status is ReconciliationStatus.COMPLETED

    def test_failed_run_does_not_block(self, db_session, business):
        import_2b(db_session, business.id, [portal()])
        failed = ReconciliationRun(
            business_id=business.id,
            period=PERIOD,
            status=ReconciliationStatus.FAILED,
        )
        db_session.add(failed)
        db_session.commit()

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        assert run.status is ReconciliationStatus.COMPLETED

    def test_running_run_for_different_period_does_not_block(
        self, db_session, business
    ):
        import_2b(db_session, business.id, [portal()])
        other = ReconciliationRun(
            business_id=business.id,
            period="2026-03",
            status=ReconciliationStatus.RUNNING,
        )
        db_session.add(other)
        db_session.commit()

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        assert run.status is ReconciliationStatus.COMPLETED


# ---------------------------------------------------------------------------
# A verdict only lands on the figures it was reached from
# ---------------------------------------------------------------------------

class TestAVerdictIsNotWrittenOverAConcurrentChange:
    """The run reads the books, compares, then writes — and another request can
    commit to an invoice in between. Simulated here by writing the row behind
    the session's back once matching has finished, which is what a committed
    correction looks like to the run: its loaded copy is stale, the table is
    not.
    """

    @staticmethod
    def _commit_behind_the_run(monkeypatch, invoice_id, **values):
        from sqlalchemy import update
        from sqlalchemy.orm import object_session

        from app.models.invoice import Invoice

        real_match = reconciliation.match

        def match_then_someone_else_writes(*args, **kwargs):
            result = real_match(*args, **kwargs)
            db = object_session(args[0][0])
            db.execute(
                update(Invoice)
                .where(Invoice.id == invoice_id)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            return result

        monkeypatch.setattr(reconciliation, "match", match_then_someone_else_writes)

    @staticmethod
    def _stored(db, invoice_id):
        from app.models.invoice import Invoice

        db.expire_all()
        return db.get(Invoice, invoice_id)

    def test_a_corrected_figure_is_not_stamped_matched(self, monkeypatch, db_session, business):
        invoice = save(db_session, business.id)
        import_2b(db_session, business.id, [portal()])
        self._commit_behind_the_run(
            monkeypatch, invoice.id, taxable_value=Decimal("400000.00")
        )

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.status is ReconciliationStatus.COMPLETED
        stored = self._stored(db_session, invoice.id)
        assert stored.taxable_value == Decimal("400000.00")
        assert stored.status is InvoiceStatus.PARSED

    def test_a_row_claimed_for_reparse_stays_processing(self, monkeypatch, db_session, business):
        invoice = save(db_session, business.id)
        import_2b(db_session, business.id, [portal()])
        self._commit_behind_the_run(monkeypatch, invoice.id, status=InvoiceStatus.PROCESSING)

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert self._stored(db_session, invoice.id).status is InvoiceStatus.PROCESSING

    def test_a_row_deleted_mid_run_is_not_given_a_verdict(self, monkeypatch, db_session, business):
        from datetime import UTC, datetime

        invoice = save(db_session, business.id)
        import_2b(db_session, business.id, [portal()])
        self._commit_behind_the_run(monkeypatch, invoice.id, deleted_at=datetime.now(UTC))

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert self._stored(db_session, invoice.id).status is InvoiceStatus.PARSED

    def test_an_untouched_row_still_gets_its_verdict(self, monkeypatch, db_session, business):
        invoice = save(db_session, business.id, invoice_number=None)
        import_2b(db_session, business.id, [portal()])
        # A write to an unrelated column: nothing the verdict was reached from.
        self._commit_behind_the_run(monkeypatch, invoice.id, hsn_code="9983")

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        # No number, so nothing in the statement can be it — and a null in a
        # judged field must still compare equal to itself.
        assert self._stored(db_session, invoice.id).status is InvoiceStatus.MISSING_IN_2B


# ---------------------------------------------------------------------------
# Two imports of one period at once
# ---------------------------------------------------------------------------

class TestTwoImportsOfOnePeriodAtOnce:
    """Both read the same live statement before either commits. Simulated by
    hiding the winner from the loser's first read, which is exactly what the
    loser saw: no live row to retire, so its INSERT meets the winner's."""

    @staticmethod
    def _miss_the_winner_once(monkeypatch):
        real = reconciliation.latest_gstr2b
        calls = []

        def stale_then_real(*args, **kwargs):
            calls.append(1)
            return None if len(calls) == 1 else real(*args, **kwargs)

        monkeypatch.setattr(reconciliation, "latest_gstr2b", stale_then_real)

    def test_the_later_import_replaces_the_one_that_won(self, monkeypatch, db_session, business):
        first = import_2b(db_session, business.id, [portal(invoice_number="A-1")])
        self._miss_the_winner_once(monkeypatch)

        second = import_2b(db_session, business.id, [portal(invoice_number="B-2")])

        db_session.expire_all()
        live = reconciliation.latest_gstr2b(db_session, business.id, PERIOD)
        assert live.id == second.id
        assert [row["invoice_number"] for row in live.data["invoices"]] == ["B-2"]
        assert db_session.get(GSTRReturn, first.id).deleted_at is not None

    def test_a_collision_that_persists_still_raises(self, monkeypatch, db_session, business):
        from sqlalchemy.exc import IntegrityError

        import_2b(db_session, business.id, [portal()])
        monkeypatch.setattr(reconciliation, "latest_gstr2b", lambda *a, **kw: None)

        with pytest.raises(IntegrityError):
            import_2b(db_session, business.id, [portal()])


class TestAFailedRunsErrorLeaksNothingAboutTheServer:
    def test_a_database_error_is_stored_without_its_sql(self, monkeypatch, db_session, business):
        from sqlalchemy.exc import DataError

        from app.core.errors import DATABASE_FAILURE_REASON

        save(db_session, business.id)
        import_2b(db_session, business.id, [portal()])

        def explode(*a, **kw):
            raise DataError("UPDATE suppliers SET compliance_score=?", (9e99,), Exception("x"))

        monkeypatch.setattr(reconciliation, "_score_suppliers", explode)

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.status is ReconciliationStatus.FAILED
        assert run.error == DATABASE_FAILURE_REASON


class TestASupplierAmendmentFindsTheInvoiceItAmends:
    """P17 M2: a b2ba row is a supplier's correction of an invoice from an
    earlier month, with the original number in ``oinum``. The import dropped
    that field, so when the correction changed the number the one invoice was
    reported twice — the booked original "missing in 2B", the amendment
    "missing in books"."""

    def test_the_import_keeps_the_original_number(self):
        import json

        from app.services import gstr2b

        statement = {
            "data": {
                "rtnprd": "042026",
                "docdata": {
                    "b2ba": [
                        {
                            "ctin": SUPPLIER_GSTIN_OTHER_STATE,
                            "inv": [
                                {
                                    "oinum": "INV-OLD-7",
                                    "oidt": "10-03-2026",
                                    "inum": "INV-NEW-7",
                                    "dt": "10-04-2026",
                                    "val": 118,
                                    "items": [{"rt": 18, "txval": 100, "igst": 18}],
                                }
                            ],
                        }
                    ]
                },
            }
        }
        (record,) = gstr2b.parse_json(json.dumps(statement))
        assert record.invoice_number == "INV-NEW-7"
        assert record.original_invoice_number == "INV-OLD-7"
        assert record.as_dict()["original_invoice_number"] == "INV-OLD-7"

    def test_a_renumbered_amendment_matches_the_booked_original(self):
        result = reconciliation.match(
            [book(invoice_number="INV-OLD-7")],
            [portal(invoice_number="INV-NEW-7", original_invoice_number="INV-OLD-7")],
            period=PERIOD,
        )
        assert categories(result) == [MatchCategory.MATCHED]
        assert result.findings[0].matched_on == "amended"
        # P17 M7: the number to follow up with appears nowhere else.
        assert "INV-NEW-7" in result.findings[0].note

    def test_an_invoice_matching_its_own_number_keeps_its_row(self):
        # The original number is the last thing tried, so it cannot take a row
        # that a booked invoice matches directly.
        result = reconciliation.match(
            [book(id=1, invoice_number="INV-NEW-7"), book(id=2, invoice_number="INV-OLD-7")],
            [portal(invoice_number="INV-NEW-7", original_invoice_number="INV-OLD-7")],
            period=PERIOD,
        )
        by_number = {f.invoice.invoice_number: (f.category, f.matched_on) for f in result.findings}
        assert by_number["INV-NEW-7"] == (MatchCategory.MATCHED, "exact")
        assert by_number["INV-OLD-7"][0] == MatchCategory.MISSING_IN_2B

    def test_the_original_booked_in_an_earlier_month_is_found_by_the_run(
        self, db_session, business
    ):
        save(
            db_session,
            business.id,
            invoice_number="INV-OLD-7",
            invoice_date=date(2026, 3, 10),
            period="2026-03",
        )
        import_2b(
            db_session,
            business.id,
            [portal(invoice_number="INV-NEW-7", original_invoice_number="INV-OLD-7")],
        )
        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        assert run.missing_in_books_count == 0
