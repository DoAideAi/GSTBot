"""The matching engine, the ITC arithmetic, and the endpoints over them."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.gstr_return import ReturnType
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.reconciliation_run import MatchCategory, ReconciliationStatus
from app.models.subscription import Subscription, SubscriptionStatus, SubscriptionTier
from app.models.supplier import RiskLevel, Supplier
from app.services import reconciliation
from app.services.gstr2b import GSTR2BRecord
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE

PERIOD = "2026-04"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def book(**kwargs) -> Invoice:
    """An unsaved purchase invoice, as it sits in the books."""
    defaults = dict(
        id=kwargs.pop("id", 1),
        business_id=1,
        invoice_type=InvoiceType.PURCHASE,
        status=InvoiceStatus.PARSED,
        counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        counterparty_name="Northwind Supplies",
        invoice_number="INV-2026-0042",
        invoice_date=date(2026, 4, 15),
        period=PERIOD,
        taxable_value=Decimal("450000.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        igst=Decimal("81000.00"),
        cess=Decimal("0.00"),
        total_value=Decimal("531000.00"),
        itc_eligible=True,
        reverse_charge=False,
    )
    defaults.update(kwargs)
    return Invoice(**defaults)


def portal(**kwargs) -> GSTR2BRecord:
    """The same invoice, as the supplier declared it."""
    defaults = dict(
        supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE,
        supplier_name="Northwind Supplies",
        invoice_number="INV-2026-0042",
        invoice_date=date(2026, 4, 15),
        period=PERIOD,
        taxable_value=Decimal("450000.00"),
        cgst=Decimal("0.00"),
        sgst=Decimal("0.00"),
        igst=Decimal("81000.00"),
        cess=Decimal("0.00"),
        total_value=Decimal("531000.00"),
        itc_available=True,
    )
    defaults.update(kwargs)
    return GSTR2BRecord(**defaults)


def categories(result) -> list[MatchCategory]:
    return [finding.category for finding in result.findings]


# ---------------------------------------------------------------------------
# Invoice number normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("INV-2026-0042", "INV202642"),
        ("inv/2026/42", "INV202642"),
        ("INV 2026 0042", "INV202642"),
        # No separators at all: the letter/digit boundary still splits it.
        ("INV00042", "INV42"),
        ("DH/451", "DH451"),
        ("0042", "42"),
        ("INV-0000", "INV0"),
        ("", ""),
        (None, ""),
    ],
)
def test_invoice_number_normalisation(raw, expected):
    assert reconciliation.normalize_invoice_number(raw) == expected


def test_normalisation_does_not_collapse_different_trailing_numbers():
    """Leading zeros go; significant digits must not."""
    assert reconciliation.normalize_invoice_number("INV-0042") != (
        reconciliation.normalize_invoice_number("INV-4200")
    )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_identical_invoice_matches():
    result = reconciliation.match([book()], [portal()], period=PERIOD)

    assert categories(result) == [MatchCategory.MATCHED]
    assert result.findings[0].matched_on == "exact"
    assert result.itc_eligible == Decimal("81000.00")
    assert result.itc_at_risk == Decimal("0.00")
    assert result.itc_claimed == Decimal("81000.00")


def test_punctuation_differences_still_match():
    """Suppliers type their own numbers into the portal by hand."""
    result = reconciliation.match(
        [book(invoice_number="INV-2026-0042")],
        [portal(invoice_number="inv/2026/42")],
        period=PERIOD,
    )

    assert categories(result) == [MatchCategory.MATCHED]
    assert result.findings[0].matched_on == "normalized"


def test_an_exact_counterpart_wins_over_a_fuzzy_one():
    """Two invoices that normalise together must not be matched at random.

    ``INV-01`` and ``INV/1`` normalise to the same key. Each still has an exact
    counterpart in the 2B, and each must get its own.
    """
    invoices = [book(id=1, invoice_number="INV-01"), book(id=2, invoice_number="INV/1")]
    records = [portal(invoice_number="INV/1"), portal(invoice_number="INV-01")]

    result = reconciliation.match(invoices, records, period=PERIOD)

    assert categories(result) == [MatchCategory.MATCHED, MatchCategory.MATCHED]
    assert all(f.matched_on == "exact" for f in result.findings)


def test_missing_from_the_portal_puts_the_whole_credit_at_risk():
    result = reconciliation.match([book()], [], period=PERIOD)

    assert categories(result) == [MatchCategory.MISSING_IN_2B]
    assert result.itc_eligible == Decimal("0.00")
    assert result.itc_at_risk == Decimal("81000.00")


def test_amount_difference_is_a_mismatch_with_the_field_named():
    result = reconciliation.match(
        [book()], [portal(igst=Decimal("72000.00"))], period=PERIOD
    )

    (finding,) = result.findings
    assert finding.category is MatchCategory.MISMATCHED
    fields = {d.field: d for d in finding.differences}
    assert set(fields) == {"igst"}
    assert fields["igst"].books == Decimal("81000.00")
    assert fields["igst"].gstr2b == Decimal("72000.00")
    assert fields["igst"].delta == Decimal("9000.00")


def test_rounding_within_tolerance_is_not_a_mismatch():
    """The portal and the books round independently, at line and at invoice."""
    result = reconciliation.match(
        [book()],
        [portal(igst=Decimal("81000.60"), taxable_value=Decimal("450000.40"))],
        period=PERIOD,
    )

    assert categories(result) == [MatchCategory.MATCHED]


def test_a_gap_of_exactly_the_tolerance_is_still_agreement():
    """The rupee itself is inside the rupee.

    The comparison is strict on purpose. GST is computed to the paisa and
    reported to the rupee, so a one-rupee gap is what independent rounding on
    the two sides produces — the difference the tolerance exists to absorb.
    Comparing with ``>=`` would report exactly that difference as a mismatch,
    and every invoice the tolerance was written for would come back as an
    argument to have with a supplier.
    """
    result = reconciliation.match(
        [book()], [portal(igst=Decimal("81001.00"))], period=PERIOD
    )

    assert categories(result) == [MatchCategory.MATCHED]


def test_a_paisa_past_the_tolerance_is_a_mismatch():
    """The other edge: the tolerance absorbs a rupee, not a rupee and one paisa."""
    result = reconciliation.match(
        [book()], [portal(igst=Decimal("81001.01"))], period=PERIOD
    )

    (finding,) = result.findings
    assert finding.category is MatchCategory.MISMATCHED
    assert [d.field for d in finding.differences] == ["igst"]


class TestAnInvoiceWithNoGrandTotalOnIt:
    """A total the parser never found is not a difference with the supplier.

    ``total_value`` is the only compared field that is not null and not
    reliable. The column defaults to zero and the parser only fills it when the
    document carried a total-shaped label, so an invoice whose total was printed
    as "Amount Payable" is stored with a total of zero while every other figure
    on it is right. The 2B side, meanwhile, derives its own when the portal row
    does not carry one.

    Compared literally, that zero is a difference of the whole invoice value
    against a row nobody disputes — the worst false positive this engine can
    produce. The user is sent to argue with a supplier about an invoice that
    agrees to the paisa, the row is stamped MISMATCHED, and the supplier's
    compliance score takes a mismatch that never happened.
    """

    def test_a_missing_books_total_does_not_invent_a_mismatch(self):
        result = reconciliation.match(
            [book(total_value=Decimal("0.00"))], [portal()], period=PERIOD
        )

        (finding,) = result.findings
        assert finding.category is MatchCategory.MATCHED
        assert finding.differences == []

    def test_the_credit_on_it_is_still_claimed_in_full(self):
        """The consequence that costs money: a mismatch is not a cap, but a
        MISMATCHED row is what a business chases instead of claiming."""
        result = reconciliation.match(
            [book(total_value=Decimal("0.00"))], [portal()], period=PERIOD
        )

        assert result.itc_eligible == Decimal("81000.00")
        assert result.itc_at_risk == Decimal("0.00")

    def test_a_missing_portal_total_is_derived_the_same_way(self):
        result = reconciliation.match(
            [book()], [portal(total_value=Decimal("0.00"))], period=PERIOD
        )

        assert categories(result) == [MatchCategory.MATCHED]

    def test_neither_side_having_one_still_matches(self):
        result = reconciliation.match(
            [book(total_value=Decimal("0.00"))],
            [portal(total_value=Decimal("0.00"))],
            period=PERIOD,
        )

        assert categories(result) == [MatchCategory.MATCHED]

    def test_a_total_that_is_genuinely_wrong_is_still_a_mismatch(self):
        """Derived only when absent. A present total is compared as it stands."""
        result = reconciliation.match(
            [book(total_value=Decimal("500000.00"))], [portal()], period=PERIOD
        )

        (finding,) = result.findings
        assert finding.category is MatchCategory.MISMATCHED
        assert [d.field for d in finding.differences] == ["total_value"]

    def test_a_derived_total_still_catches_a_real_tax_difference(self):
        """Filling the gap must not paper over the difference underneath it.

        Each side derives from its own figures, so when neither carries a total
        and the tax disagrees, the derived totals disagree too — the difference
        is reported on both fields rather than swallowed.
        """
        result = reconciliation.match(
            [book(total_value=Decimal("0.00"))],
            [portal(igst=Decimal("72000.00"), total_value=Decimal("0.00"))],
            period=PERIOD,
        )

        (finding,) = result.findings
        assert finding.category is MatchCategory.MISMATCHED
        assert {d.field for d in finding.differences} == {"igst", "total_value"}

    def test_a_stated_portal_total_still_anchors_the_comparison(self):
        """The books derive; the portal's own figure is used as it stands.

        The books are short ₹9,000 of IGST, so the total derived from them is
        short by the same ₹9,000 against the total the portal actually states.
        Deriving the missing side does not make the invoice agree — it only
        stops a *present* agreement being read as a disagreement.
        """
        result = reconciliation.match(
            [book(total_value=Decimal("0.00"), igst=Decimal("72000.00"))],
            [portal()],
            period=PERIOD,
        )

        (finding,) = result.findings
        assert finding.category is MatchCategory.MISMATCHED
        assert {d.field for d in finding.differences} == {"igst", "total_value"}

    def test_the_supplier_is_not_scored_for_a_mismatch_that_never_happened(
        self, db_session, business
    ):
        """The lasting damage: the score feeds the risk level and the provision."""
        result = reconciliation.match(
            [book(total_value=Decimal("0.00"))], [portal()], period=PERIOD
        )

        assert result.counts()[MatchCategory.MISMATCHED] == 0
        assert result.counts()[MatchCategory.MATCHED] == 1


def test_tolerance_of_zero_surfaces_every_paisa():
    result = reconciliation.match(
        [book()],
        [portal(igst=Decimal("81000.60"))],
        period=PERIOD,
        tolerance=Decimal("0"),
    )

    assert categories(result) == [MatchCategory.MISMATCHED]


def test_claiming_more_than_the_supplier_declared_is_capped_and_flagged():
    """Credit is limited to what the portal shows; the excess is exposed."""
    result = reconciliation.match(
        [book()], [portal(igst=Decimal("72000.00"))], period=PERIOD
    )

    assert result.itc_eligible == Decimal("72000.00")
    assert result.itc_at_risk == Decimal("9000.00")


def test_claiming_less_than_declared_claims_only_what_was_booked():
    """The supplier declared more than we booked; we cannot claim their figure."""
    result = reconciliation.match(
        [book()], [portal(igst=Decimal("90000.00"))], period=PERIOD
    )

    assert result.itc_eligible == Decimal("81000.00")
    assert result.itc_at_risk == Decimal("0.00")


def test_portal_marking_the_credit_unavailable_exposes_it():
    """Filed, matched, and still not claimable."""
    result = reconciliation.match([book()], [portal(itc_available=False)], period=PERIOD)

    assert categories(result) == [MatchCategory.MATCHED]
    assert result.itc_eligible == Decimal("0.00")
    assert result.itc_at_risk == Decimal("81000.00")


def test_blocked_credit_is_neither_claimed_nor_at_risk():
    """A s.17(5) purchase was never going to yield credit either way."""
    result = reconciliation.match([book(itc_eligible=False)], [], period=PERIOD)

    assert categories(result) == [MatchCategory.MISSING_IN_2B]
    assert result.itc_claimed == Decimal("0.00")
    assert result.itc_at_risk == Decimal("0.00")


def test_reverse_charge_invoices_are_left_out_of_the_itc_arithmetic():
    """Under reverse charge the buyer pays the tax; the supplier declares no output."""
    result = reconciliation.match([book(reverse_charge=True)], [], period=PERIOD)

    assert result.itc_claimed == Decimal("0.00")
    assert result.itc_at_risk == Decimal("0.00")


def test_unbooked_portal_invoice_is_missing_in_books():
    result = reconciliation.match([], [portal()], period=PERIOD)

    assert categories(result) == [MatchCategory.MISSING_IN_BOOKS]
    assert result.findings[0].record is not None
    assert result.total_invoices == 0


def test_the_same_invoice_booked_twice_is_reported_as_a_duplicate():
    """Two claims off one document is what a departmental notice is issued over."""
    invoices = [book(id=1), book(id=2)]
    result = reconciliation.match(invoices, [portal()], period=PERIOD)

    assert sorted(c.value for c in categories(result)) == ["duplicate", "matched"]


def test_a_duplicate_does_not_consume_the_original_s_portal_row():
    """The original must still match; only the copy is flagged."""
    invoices = [book(id=1), book(id=2)]
    result = reconciliation.match(invoices, [portal()], period=PERIOD)

    matched = [f for f in result.findings if f.category is MatchCategory.MATCHED]
    assert len(matched) == 1
    assert matched[0].invoice.id == 1
    # The credit is counted once, not twice.
    assert result.itc_eligible == Decimal("81000.00")


def test_same_number_from_different_suppliers_is_not_a_duplicate():
    """Invoice numbers are only unique within an issuer."""
    invoices = [
        book(id=1, counterparty_gstin=SUPPLIER_GSTIN_OTHER_STATE, invoice_number="001"),
        book(id=2, counterparty_gstin=SUPPLIER_GSTIN_SAME_STATE, invoice_number="001"),
    ]
    records = [
        portal(supplier_gstin=SUPPLIER_GSTIN_OTHER_STATE, invoice_number="001"),
        portal(supplier_gstin=SUPPLIER_GSTIN_SAME_STATE, invoice_number="001"),
    ]
    result = reconciliation.match(invoices, records, period=PERIOD)

    assert categories(result) == [MatchCategory.MATCHED, MatchCategory.MATCHED]


def test_intra_state_tax_heads_are_compared_separately():
    """CGST and SGST swapped is a real error, not a rounding difference."""
    invoice = book(
        cgst=Decimal("9000.00"), sgst=Decimal("9000.00"), igst=Decimal("0.00"),
        taxable_value=Decimal("100000.00"), total_value=Decimal("118000.00"),
    )
    record = portal(
        cgst=Decimal("0.00"), sgst=Decimal("0.00"), igst=Decimal("18000.00"),
        taxable_value=Decimal("100000.00"), total_value=Decimal("118000.00"),
    )
    result = reconciliation.match([invoice], [record], period=PERIOD)

    (finding,) = result.findings
    assert finding.category is MatchCategory.MISMATCHED
    assert {d.field for d in finding.differences} == {"cgst", "sgst", "igst"}


def test_a_mixed_period_reconciles_every_category_at_once():
    invoices = [
        book(id=1, invoice_number="A-1"),
        book(id=2, invoice_number="B-2"),
        book(id=3, invoice_number="C-3"),
    ]
    records = [
        portal(invoice_number="A-1"),
        portal(invoice_number="B-2", igst=Decimal("70000.00")),
        portal(invoice_number="Z-9"),
    ]
    result = reconciliation.match(invoices, records, period=PERIOD)
    counts = result.counts()

    assert counts[MatchCategory.MATCHED] == 1
    assert counts[MatchCategory.MISMATCHED] == 1
    assert counts[MatchCategory.MISSING_IN_2B] == 1
    assert counts[MatchCategory.MISSING_IN_BOOKS] == 1
    # The denominator is our books, not the portal's rows.
    assert result.total_invoices == 3


def test_report_serialises_to_json():
    """The report is stored as JSON, so Decimals must already be strings."""
    result = reconciliation.match(
        [book()], [portal(igst=Decimal("72000.00"))], period=PERIOD
    )
    payload = [f.as_dict() for f in result.findings]

    assert json.loads(json.dumps(payload))[0]["differences"][0]["books"] == "81000.00"


# ---------------------------------------------------------------------------
# Persistence and the endpoints
# ---------------------------------------------------------------------------

def save(db, business_id, **kwargs) -> Invoice:
    invoice = book(id=None, business_id=business_id, **kwargs)
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def import_2b(db, business_id, records, period=PERIOD):
    return reconciliation.store_gstr2b(db, business_id, period, records)


def test_run_requires_an_imported_2b(db_session, business):
    with pytest.raises(reconciliation.NoGSTR2BImported):
        reconciliation.run_reconciliation(db_session, business.id, PERIOD)


def test_run_writes_counts_itc_and_statuses(db_session, business):
    matched = save(db_session, business.id, invoice_number="A-1")
    missing = save(db_session, business.id, invoice_number="B-2")
    import_2b(db_session, business.id, [portal(invoice_number="A-1")])

    run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    assert run.status is ReconciliationStatus.COMPLETED
    assert run.matched_count == 1
    assert run.missing_in_2b_count == 1
    assert run.total_invoices == 2
    assert run.itc_eligible == Decimal("81000.00")
    assert run.itc_at_risk == Decimal("81000.00")

    db_session.refresh(matched)
    db_session.refresh(missing)
    assert matched.status is InvoiceStatus.MATCHED
    assert missing.status is InvoiceStatus.MISSING_IN_2B


def test_a_successful_run_emits_a_structured_log_line(db_session, business, caplog):
    save(db_session, business.id, invoice_number="A-1")
    import_2b(db_session, business.id, [portal(invoice_number="A-1")])

    with caplog.at_level("INFO", logger="app.services.reconciliation"):
        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    assert run.status is ReconciliationStatus.COMPLETED
    completed = [r for r in caplog.records if "completed" in r.message.lower()]
    assert completed, "No success log line emitted for a completed reconciliation"
    record = completed[0]
    assert record.business_id == business.id
    assert record.period == PERIOD
    assert record.matched == 1
    assert record.duration_ms >= 0


def test_only_purchases_are_reconciled(db_session, business):
    """GSTR-2B is a statement of inward supply; a sale has no counterpart."""
    save(db_session, business.id, invoice_type=InvoiceType.SALES, invoice_number="S-1")
    import_2b(db_session, business.id, [])

    run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    assert run.total_invoices == 0


def test_failed_extractions_are_left_out(db_session, business):
    """An invoice whose fields were never read cannot be compared with anything."""
    save(db_session, business.id, invoice_number="F-1", status=InvoiceStatus.FAILED)
    import_2b(db_session, business.id, [])

    run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    assert run.total_invoices == 0
    assert run.missing_in_2b_count == 0


def test_other_periods_are_untouched(db_session, business):
    save(db_session, business.id, invoice_number="M-1", period="2026-03",
         invoice_date=date(2026, 3, 12))
    import_2b(db_session, business.id, [portal()])

    run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    assert run.total_invoices == 0
    assert run.missing_in_books_count == 1


class TestARowThatIsStillBeingRead:
    """A reconciliation started mid-upload must not touch what nothing has read.

    Only ``FAILED`` was excluded, so a row still queued for a worker went into
    the comparison — and ``_apply_statuses`` wrote the verdict back onto it.
    Reconciling and uploading are the two things a business does in one sitting.
    """

    @pytest.mark.parametrize(
        "status", [InvoiceStatus.UPLOADED, InvoiceStatus.PROCESSING]
    )
    def test_it_is_left_out_of_the_run(self, db_session, business, status):
        save(db_session, business.id, invoice_number="Q-1", status=status)
        import_2b(db_session, business.id, [])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.total_invoices == 0
        assert run.missing_in_2b_count == 0

    def test_its_status_is_not_rewritten(self, db_session, business):
        """The damage was not confined to the run.

        ``missing_in_2b`` is not one of the statuses the rest of the product
        treats as unreadable, so a row promoted into it left the blind spot
        every other module keeps it in — and its untouched columns of zeros
        became a line in the return and a supply in the period's output tax.
        """
        pending = save(
            db_session, business.id, invoice_number="Q-1", status=InvoiceStatus.UPLOADED
        )
        import_2b(db_session, business.id, [])

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        db_session.refresh(pending)
        assert pending.status is InvoiceStatus.UPLOADED


class TestASupplierWhoFilesLate:
    """The late invoice turns up in a later month's statement, dated earlier.

    A 2B is not confined to its own month: when a supplier finally files, the
    invoice appears in the statement for the month they filed in, carrying its
    original date. The buyer booked it when it arrived, under its own period —
    so compared against one period's books it had nowhere to land, and the
    business was told an invoice it entered months ago was not in its own
    purchase register.
    """

    LATE = "2026-03"

    def late_book(self, db, business_id) -> Invoice:
        return save(
            db,
            business_id,
            invoice_number="LATE-1",
            period=self.LATE,
            invoice_date=date(2026, 3, 10),
        )

    def late_record(self, **kwargs) -> GSTR2BRecord:
        return portal(
            invoice_number="LATE-1",
            period=self.LATE,
            invoice_date=date(2026, 3, 10),
            **kwargs,
        )

    def test_it_is_no_longer_reported_as_absent_from_the_books(
        self, db_session, business
    ):
        self.late_book(db_session, business.id)
        import_2b(db_session, business.id, [self.late_record()])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.missing_in_books_count == 0

    def test_the_finding_says_where_it_was_booked(self, db_session, business):
        self.late_book(db_session, business.id)
        import_2b(db_session, business.id, [self.late_record()])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        (finding,) = run.report["findings"]
        assert finding["carried"] is True
        assert finding["category"] == MatchCategory.MATCHED.value
        assert self.LATE in finding["note"]

    def test_it_counts_towards_nothing_in_this_period(self, db_session, business):
        """March's run already counted it. May must not count it again."""
        self.late_book(db_session, business.id)
        import_2b(db_session, business.id, [self.late_record()])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.total_invoices == 0
        assert run.matched_count == 0
        assert run.itc_eligible == Decimal("0.00")
        assert run.itc_claimed == Decimal("0.00")

    def test_the_invoice_keeps_the_status_its_own_period_gave_it(
        self, db_session, business
    ):
        """Otherwise the answer depends on which month was reconciled last."""
        invoice = self.late_book(db_session, business.id)
        invoice.status = InvoiceStatus.MISSING_IN_2B
        db_session.commit()
        import_2b(db_session, business.id, [self.late_record()])

        reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        db_session.refresh(invoice)
        assert invoice.status is InvoiceStatus.MISSING_IN_2B

    def test_the_supplier_is_not_scored_twice_for_one_invoice(
        self, db_session, business
    ):
        """A matched here plus the missing March already recorded is two verdicts."""
        self.late_book(db_session, business.id)
        import_2b(db_session, business.id, [self.late_record()])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.report["suppliers"] == {}

    def test_a_record_this_period_has_no_invoice_for_is_still_reported(
        self, db_session, business
    ):
        """The false alarm goes; the real one stays."""
        import_2b(db_session, business.id, [portal(invoice_number="GHOST-1")])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.missing_in_books_count == 1

    def test_an_out_of_period_invoice_the_statement_does_not_name_is_untouched(
        self, db_session, business
    ):
        """Only the invoices the statement actually names are pulled in.

        Dragging in a whole earlier period would have every one of its other
        invoices find no counterpart here and be rewritten to
        ``missing_in_2b`` — a run for May destroying March's verdicts.
        """
        other = save(
            db_session,
            business.id,
            invoice_number="MARCH-9",
            period=self.LATE,
            invoice_date=date(2026, 3, 4),
            status=InvoiceStatus.MATCHED,
        )
        self.late_book(db_session, business.id)
        import_2b(db_session, business.id, [self.late_record()])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        db_session.refresh(other)
        assert other.status is InvoiceStatus.MATCHED
        assert len(run.report["findings"]) == 1

    def test_a_statement_row_naming_only_a_supplier_carries_nothing_in(
        self, db_session, business
    ):
        """Half-identified rows are ordinary in a portal export, and the two
        halves do different work here: the GSTIN narrows the query and the
        number decides which row it was. A statement whose out-of-period rows
        name a supplier but no invoice number therefore identifies nothing —
        and must carry nothing, because the alternative is dragging in every
        invoice that supplier ever sold us. Each of those would then find no
        counterpart in this run and have its own period's verdict rewritten.
        """
        older = self.late_book(db_session, business.id)
        import_2b(
            db_session,
            business.id,
            [
                portal(
                    invoice_number=None,
                    period=self.LATE,
                    invoice_date=date(2026, 3, 10),
                )
            ],
        )

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        db_session.refresh(older)
        assert older.status is InvoiceStatus.PARSED
        # The row itself is still reported — it is in the 2B and in no books
        # this run compared it against — but nothing was carried in for it.
        assert [f["category"] for f in run.report["findings"]] == ["missing_in_books"]
        assert all(f["carried"] is False for f in run.report["findings"])

    def test_a_statement_row_naming_only_a_number_carries_nothing_in(
        self, db_session, business
    ):
        """The mirror image, and the more dangerous one.

        An invoice number without a supplier is not unique — ``INV-001`` is
        every small supplier's first bill of the year — so widening the query
        on it alone would reach across suppliers, not merely across periods.
        """
        older = self.late_book(db_session, business.id)
        import_2b(db_session, business.id, [self.late_record(supplier_gstin=None)])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        db_session.refresh(older)
        assert older.status is InvoiceStatus.PARSED
        assert all(f["carried"] is False for f in run.report["findings"])

    def test_this_period_gets_first_claim_on_a_shared_number(self):
        """A carried invoice must never take a row this period's books own.

        Numbers that normalise together are the way this collides in practice,
        since the unique index rules out two rows carrying the same number
        literally. Within a pass the period's own books go first; across passes
        the older rule still holds, and an exact counterpart beats a fuzzy one
        whichever period it was booked in.
        """
        mine = book(id=1, invoice_number="LATE/1")
        theirs = book(
            id=2,
            invoice_number="LATE_1",
            period=self.LATE,
            invoice_date=date(2026, 3, 10),
        )

        result = reconciliation.match(
            [mine],
            [portal(invoice_number="LATE-1")],
            period=PERIOD,
            carried=[theirs],
        )

        (finding,) = result.findings
        assert finding.invoice is mine
        assert finding.category is MatchCategory.MATCHED
        assert finding.carried is False

    def test_a_late_invoice_the_books_disagree_with_is_still_a_mismatch(
        self, db_session, business
    ):
        self.late_book(db_session, business.id)
        import_2b(db_session, business.id, [self.late_record(igst=Decimal("72000.00"))])

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        (finding,) = run.report["findings"]
        assert finding["category"] == MatchCategory.MISMATCHED.value
        assert finding["carried"] is True
        assert run.mismatched_count == 0


def test_runs_accumulate_rather_than_overwrite(db_session, business):
    """A period is reconciled again as suppliers file late."""
    save(db_session, business.id, invoice_number="A-1")
    import_2b(db_session, business.id, [])
    first = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    import_2b(db_session, business.id, [portal(invoice_number="A-1")])
    second = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    assert first.id != second.id
    assert first.missing_in_2b_count == 1
    assert second.matched_count == 1


def test_reimporting_supersedes_the_previous_2b(db_session, business):
    import_2b(db_session, business.id, [portal(invoice_number="OLD-1")])
    import_2b(db_session, business.id, [portal(invoice_number="NEW-1")])

    current = reconciliation.latest_gstr2b(db_session, business.id, PERIOD)
    records = reconciliation.records_from_return(current)

    assert [r.invoice_number for r in records] == ["NEW-1"]
    assert reconciliation.periods_with_2b(db_session, business.id) == [PERIOD]


def test_supplier_score_reflects_the_run(db_session, business):
    db_session.add(
        Supplier(business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE, legal_name="Northwind")
    )
    db_session.commit()

    save(db_session, business.id, invoice_number="A-1")
    save(db_session, business.id, invoice_number="B-2")
    import_2b(db_session, business.id, [portal(invoice_number="A-1")])

    reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    supplier = db_session.query(Supplier).filter_by(gstin=SUPPLIER_GSTIN_OTHER_STATE).one()
    assert supplier.matched_invoices == 1
    assert supplier.missing_invoices == 1
    # One of two invoices filed is a 50% match rate, which carries half the
    # weight of the score; the supplier did file this period, so recency scores
    # full marks on its 10%. Timeliness and consistency have no evidence from a
    # single period with no filing date, so they drop out and the rest are
    # renormalised: (50x50 + 100x10) / 60.
    assert supplier.compliance_score == 58
    assert supplier.risk_level is RiskLevel.HIGH
    assert supplier.filing_history[-1]["period"] == PERIOD


def test_a_reliable_supplier_scores_low_risk(db_session, business):
    db_session.add(Supplier(business_id=business.id, gstin=SUPPLIER_GSTIN_OTHER_STATE))
    db_session.commit()

    for index in range(4):
        save(db_session, business.id, invoice_number=f"OK-{index}")
    import_2b(
        db_session, business.id, [portal(invoice_number=f"OK-{i}") for i in range(4)]
    )
    reconciliation.run_reconciliation(db_session, business.id, PERIOD)

    supplier = db_session.query(Supplier).filter_by(gstin=SUPPLIER_GSTIN_OTHER_STATE).one()
    assert supplier.compliance_score == 100
    assert supplier.risk_level is RiskLevel.LOW


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _activate_pro(db_session, business_id: int) -> None:
    sub = db_session.scalar(
        select(Subscription).where(Subscription.business_id == business_id)
    )
    if sub is None:
        sub = Subscription(
            business_id=business_id,
            tier=SubscriptionTier.PRO,
            status=SubscriptionStatus.ACTIVE,
        )
        db_session.add(sub)
    else:
        sub.tier = SubscriptionTier.PRO
        sub.status = SubscriptionStatus.ACTIVE
    db_session.commit()


def portal_file_json() -> bytes:
    return json.dumps(
        {
            "data": {
                "rtnprd": "042026",
                "docdata": {
                    "b2b": [
                        {
                            "ctin": SUPPLIER_GSTIN_OTHER_STATE,
                            "trdnm": "Northwind Supplies",
                            "inv": [
                                {
                                    "inum": "INV-2026-0042",
                                    "dt": "15-04-2026",
                                    "val": 531000.00,
                                    "itcavl": "Y",
                                    "items": [
                                        {"rt": 18, "txval": 450000.00, "igst": 81000.00}
                                    ],
                                }
                            ],
                        }
                    ]
                },
            }
        }
    ).encode()


_DEFAULT = object()


def upload_2b(auth_client, content=_DEFAULT, filename="gstr2b.json", **data):
    # Sentinel rather than `content or ...`: b"" is falsy, and the empty-file
    # test needs the empty body to actually reach the endpoint.
    if content is _DEFAULT:
        content = portal_file_json()
    return auth_client.post(
        "/api/v1/reconciliation/gstr2b/import",
        files={"file": (filename, content, "application/json")},
        data=data,
    )


def test_import_endpoint_requires_authentication(client):
    assert client.post("/api/v1/reconciliation/gstr2b/import").status_code == 401


def test_a_free_user_cannot_import_a_2b(auth_client):
    response = upload_2b(auth_client)
    assert response.status_code == 403
    assert "paid subscription" in response.json()["detail"].lower()


def test_a_free_user_cannot_run_reconciliation(auth_client):
    response = auth_client.post("/api/v1/reconciliation/run", json={"period": PERIOD})
    assert response.status_code == 403
    assert "paid subscription" in response.json()["detail"].lower()


def test_import_reads_the_period_from_the_file(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    response = upload_2b(auth_client)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["period"] == PERIOD
    assert body["invoice_count"] == 1
    assert Decimal(body["total_igst"]) == Decimal("81000.00")
    assert body["return_type"] == ReturnType.GSTR2B.value
    assert body["replaced_previous"] is False


def test_import_rejects_a_file_that_is_not_a_2b(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    response = upload_2b(auth_client, content=b'{"hello": "world"}')

    assert response.status_code == 422
    assert "b2b" in response.json()["detail"]


def test_import_rejects_an_empty_file(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    response = upload_2b(auth_client, content=b"")
    assert response.status_code == 400


def test_import_rejects_an_unsupported_extension(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    response = upload_2b(auth_client, filename="gstr2b.pdf")
    assert response.status_code == 415


def test_reimport_reports_that_it_replaced(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    upload_2b(auth_client)
    body = upload_2b(auth_client).json()

    assert body["replaced_previous"] is True
    assert "replacing the previous import" in body["message"]


def test_import_flags_late_filings_from_other_periods(auth_client, db_session, business):
    """Not an error: they reconcile against the month they belong to."""
    _activate_pro(db_session, business.id)
    payload = json.loads(portal_file_json())
    payload["data"]["docdata"]["b2b"][0]["inv"].append(
        {
            "inum": "LATE-1",
            "dt": "20-03-2026",
            "val": 11800.00,
            "items": [{"rt": 18, "txval": 10000.00, "igst": 1800.00}],
        }
    )
    body = upload_2b(auth_client, content=json.dumps(payload).encode()).json()

    assert body["period"] == PERIOD
    assert body["other_periods"] == ["2026-03"]


def test_run_endpoint_conflicts_without_an_import(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    response = auth_client.post("/api/v1/reconciliation/run", json={"period": PERIOD})

    assert response.status_code == 409
    assert "No GSTR-2B" in response.json()["detail"]


def test_run_endpoint_returns_the_report(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    save(db_session, business.id, invoice_number="INV-2026-0042")
    upload_2b(auth_client)

    response = auth_client.post("/api/v1/reconciliation/run", json={"period": PERIOD})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["matched_count"] == 1
    assert Decimal(body["itc_eligible"]) == Decimal("81000.00")
    assert body["report"]["findings"][0]["category"] == "matched"


def test_run_endpoint_honours_a_custom_tolerance(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    save(db_session, business.id, invoice_number="INV-2026-0042",
         igst=Decimal("81000.50"))
    upload_2b(auth_client)

    default = auth_client.post(
        "/api/v1/reconciliation/run", json={"period": PERIOD}
    ).json()
    strict = auth_client.post(
        "/api/v1/reconciliation/run", json={"period": PERIOD, "tolerance": "0"}
    ).json()

    assert default["matched_count"] == 1
    assert strict["mismatched_count"] == 1


def test_run_endpoint_validates_the_period(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    response = auth_client.post("/api/v1/reconciliation/run", json={"period": "April"})
    assert response.status_code == 422


def test_listing_and_fetching_runs(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    save(db_session, business.id, invoice_number="INV-2026-0042")
    upload_2b(auth_client)
    created = auth_client.post(
        "/api/v1/reconciliation/run", json={"period": PERIOD}
    ).json()

    listed = auth_client.get("/api/v1/reconciliation").json()
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == created["id"]

    fetched = auth_client.get(f"/api/v1/reconciliation/{created['id']}").json()
    assert fetched["report"]["findings"]

    latest = auth_client.get(f"/api/v1/reconciliation/latest?period={PERIOD}").json()
    assert latest["id"] == created["id"]


def test_latest_is_404_before_any_run(auth_client):
    response = auth_client.get(f"/api/v1/reconciliation/latest?period={PERIOD}")
    assert response.status_code == 404


def test_imported_periods_are_listed(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    upload_2b(auth_client)
    assert auth_client.get("/api/v1/reconciliation/gstr2b/periods").json() == {"items": [PERIOD]}


def test_imported_2b_can_be_fetched_by_period(auth_client, db_session, business):
    _activate_pro(db_session, business.id)
    upload_2b(auth_client)
    body = auth_client.get(f"/api/v1/reconciliation/gstr2b/{PERIOD}").json()

    assert body["invoice_count"] == 1


def test_fetching_a_2b_that_was_never_imported_is_404(auth_client):
    assert auth_client.get("/api/v1/reconciliation/gstr2b/2026-01").status_code == 404


def test_one_tenant_cannot_read_another_s_run(auth_client, client, db_session, business,
                                              other_tenant):
    _activate_pro(db_session, business.id)
    save(db_session, business.id, invoice_number="INV-2026-0042")
    upload_2b(auth_client)
    created = auth_client.post(
        "/api/v1/reconciliation/run", json={"period": PERIOD}
    ).json()

    client.headers.update({"Authorization": f"Bearer {other_tenant}"})
    response = client.get(f"/api/v1/reconciliation/{created['id']}")

    # 404 rather than 403: a 403 confirms the id exists.
    assert response.status_code == 404
    assert client.get("/api/v1/reconciliation").json()["total"] == 0


def test_a_tenant_s_2b_is_not_visible_to_another(
    auth_client, client, db_session, business, other_tenant,
):
    _activate_pro(db_session, business.id)
    upload_2b(auth_client)

    client.headers.update({"Authorization": f"Bearer {other_tenant}"})
    assert client.get("/api/v1/reconciliation/gstr2b/periods").json() == {"items": []}
    assert client.get(f"/api/v1/reconciliation/gstr2b/{PERIOD}").status_code == 404


def test_reconciliation_feeds_the_dashboard(auth_client, db_session, business):
    """The dashboard's itc_at_risk comes from the latest run for the period."""
    _activate_pro(db_session, business.id)
    save(db_session, business.id, invoice_number="GHOST-1")
    upload_2b(auth_client)
    auth_client.post("/api/v1/reconciliation/run", json={"period": PERIOD})

    body = auth_client.get(f"/api/v1/dashboard?period={PERIOD}").json()

    assert Decimal(body["itc_at_risk"]) == Decimal("81000.00")
    assert body["last_reconciliation"]["missing_in_2b"] == 1


# ---------------------------------------------------------------------------
# Credit notes
# ---------------------------------------------------------------------------

def note(**kwargs) -> GSTR2BRecord:
    """A credit note as the portal states it: positive figures, type "C"."""
    defaults = dict(
        invoice_number="CN-7",
        invoice_date=date(2026, 4, 28),
        document_type="C",
        taxable_value=Decimal("50000.00"),
        igst=Decimal("9000.00"),
        total_value=Decimal("59000.00"),
    )
    defaults.update(kwargs)
    return portal(**defaults)


class TestACreditNoteTakesCreditBack:
    """A credit note reverses part of a supply, and the credit goes with it.

    The portal states a note's amounts as positive figures and leaves the sign
    to the document type, so a reader going by the money alone counts a
    reduction as a second supply. Read that way, a business whose supplier had
    withdrawn ₹9,000 of tax was still shown the whole ₹81,000 as eligible — an
    over-claim the 2B itself contradicts, which is the exact reversal-with-
    interest this module exists to prevent.
    """

    def test_it_comes_off_the_eligible_pool(self):
        result = reconciliation.match(
            [book(invoice_number="INV-1")],
            [portal(invoice_number="INV-1"), note()],
            period=PERIOD,
        )

        assert result.credit_notes == Decimal("9000.00")
        assert result.itc_eligible == Decimal("72000.00")

    def test_it_is_not_mistaken_for_an_unbooked_supply(self):
        """The finding has to say what it is, or it reads as chase the supplier."""
        result = reconciliation.match(
            [book(invoice_number="INV-1")],
            [portal(invoice_number="INV-1"), note()],
            period=PERIOD,
        )

        found = next(f for f in result.findings if f.record and f.record.is_credit_note)
        assert found.category is MatchCategory.MISSING_IN_BOOKS
        assert "Credit note" in (found.note or "")

    def test_a_debit_note_still_adds_credit(self):
        """"D" raises the supplier's charge; it moves the same way an invoice does."""
        result = reconciliation.match(
            [book(invoice_number="INV-1")],
            [portal(invoice_number="INV-1"), note(document_type="D")],
            period=PERIOD,
        )

        assert result.credit_notes == Decimal("0.00")
        assert result.itc_eligible == Decimal("81000.00")

    def test_notes_beyond_the_period_s_credit_leave_nothing_rather_than_less(self):
        """A pool cannot go negative; the excess belongs to another period."""
        result = reconciliation.match(
            [book(invoice_number="INV-1")],
            [portal(invoice_number="INV-1"), note(igst=Decimal("200000.00"))],
            period=PERIOD,
        )

        assert result.itc_eligible == Decimal("0.00")

    def test_a_note_never_pairs_with_a_booked_invoice(self):
        """It is not an invoice, so it cannot be the counterpart of one.

        Held in the matching index, a note whose number normalised onto a
        booked invoice's could be consumed as that invoice's declaration —
        leaving the real invoice reported as never filed.
        """
        result = reconciliation.match(
            [book(invoice_number="CN-7")],
            [note()],
            period=PERIOD,
        )

        assert categories(result) == [
            MatchCategory.MISSING_IN_2B,
            MatchCategory.MISSING_IN_BOOKS,
        ]
        assert result.itc_eligible == Decimal("0.00")

    def test_a_note_alone_reverses_nothing_it_cannot_reach(self):
        """No invoices booked at all: there is no pool to take it out of."""
        result = reconciliation.match([], [note()], period=PERIOD)

        assert result.credit_notes == Decimal("9000.00")
        assert result.itc_eligible == Decimal("0.00")

    def test_the_run_records_why_the_pool_shrank(self, db_session, business):
        save(db_session, business.id, invoice_number="INV-1")
        import_2b(
            db_session, business.id, [portal(invoice_number="INV-1"), note()]
        )

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.itc_eligible == Decimal("72000.00")
        assert run.report["credit_notes"] == "9000.00"
        # The statement's own record count is unchanged: the note is in it.
        assert run.report["gstr2b_record_count"] == 2

    def test_the_stored_statement_totals_net_it_too(self):
        """The import screen and the run that follows must agree.

        Summing the money alone read the note as a second supply, so a
        statement carrying one ₹18,000 invoice and a ₹9,000 note against it
        was stored — and shown back on import — as ₹27,000 of tax, while the
        reconciliation that followed found ₹9,000.
        """
        totals = reconciliation.summarise_records(
            [portal(invoice_number="INV-1"), note()]
        )

        assert totals["total_igst"] == Decimal("72000.00")
        assert totals["total_taxable_value"] == Decimal("400000.00")

    def test_a_debit_note_still_adds_to_the_stored_totals(self):
        totals = reconciliation.summarise_records(
            [portal(invoice_number="INV-1"), note(document_type="D")]
        )

        assert totals["total_igst"] == Decimal("90000.00")

    def test_the_stored_totals_floor_at_zero(self):
        """The month after a large return, the notes can outweigh the invoices."""
        totals = reconciliation.summarise_records([note(igst=Decimal("200000.00"))])

        assert totals["total_igst"] == Decimal("0.00")
        assert totals["total_taxable_value"] == Decimal("0.00")

    def test_the_document_count_still_counts_the_note(self):
        """It answers "did the whole file come through", and the note is in it."""
        totals = reconciliation.summarise_records(
            [portal(invoice_number="INV-1"), note()]
        )

        assert totals["invoice_count"] == 2

    def test_the_import_endpoint_reports_the_net_statement(
        self, auth_client, db_session, business
    ):
        """What the user is shown the moment the file lands."""
        _activate_pro(db_session, business.id)
        payload = {
            "data": {
                "rtnprd": "042026",
                "docdata": {
                    "b2b": [
                        {
                            "ctin": SUPPLIER_GSTIN_OTHER_STATE,
                            "inv": [
                                {
                                    "inum": "INV-1",
                                    "dt": "15-04-2026",
                                    "val": 531000,
                                    "itms": [{"txval": 450000, "igst": 81000}],
                                }
                            ],
                        }
                    ],
                    "cdnr": [
                        {
                            "ctin": SUPPLIER_GSTIN_OTHER_STATE,
                            "nt": [
                                {
                                    "nt_num": "CN-7",
                                    "nt_dt": "28-04-2026",
                                    "typ": "C",
                                    "val": 59000,
                                    "itms": [{"txval": 50000, "igst": 9000}],
                                }
                            ],
                        }
                    ],
                },
            }
        }
        response = auth_client.post(
            "/api/v1/reconciliation/gstr2b/import",
            files={"file": ("2b.json", json.dumps(payload), "application/json")},
        )

        assert response.status_code == 201
        body = response.json()
        assert Decimal(body["total_igst"]) == Decimal("72000.00")
        assert body["invoice_count"] == 2

    def test_the_matched_invoice_is_still_matched(self, db_session, business):
        """Netting the note must not disturb the invoice's own verdict."""
        invoice = save(db_session, business.id, invoice_number="INV-1")
        import_2b(
            db_session, business.id, [portal(invoice_number="INV-1"), note()]
        )

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        db_session.refresh(invoice)

        assert run.matched_count == 1
        assert run.itc_at_risk == Decimal("0.00")
        assert invoice.status is InvoiceStatus.MATCHED


# ---------------------------------------------------------------------------
# Which pool the eligible credit belongs to
# ---------------------------------------------------------------------------

class TestCapitalCreditIsCountedApart:
    """A capital good's eligible credit is reported separately from an input's.

    Both are credit the supplier declared, so both belong in ``itc_eligible``.
    But Rule 43 gives a capital good's credit to sixty months rather than to
    this one, and the ITC screen therefore holds it in a different pool — where
    it cannot be compared against a total that has capital credit folded in.
    """

    def test_the_split_is_reported(self):
        result = reconciliation.match(
            [
                book(invoice_number="INV-1"),
                book(invoice_number="CAP-1", is_capital_good=True),
            ],
            [portal(invoice_number="INV-1"), portal(invoice_number="CAP-1")],
            period=PERIOD,
        )

        assert result.itc_eligible == Decimal("162000.00")
        assert result.itc_eligible_capital == Decimal("81000.00")
        assert result.input_itc_eligible == Decimal("81000.00")

    def test_the_capital_share_is_capped_by_the_2b_like_any_other(self):
        """Only what the supplier declared reaches either pool."""
        result = reconciliation.match(
            [book(invoice_number="CAP-1", is_capital_good=True)],
            [portal(invoice_number="CAP-1", igst=Decimal("50000.00"))],
            period=PERIOD,
        )

        assert result.itc_eligible_capital == Decimal("50000.00")
        assert result.input_itc_eligible == Decimal("0.00")

    def test_a_capital_good_the_supplier_never_filed_reaches_neither(self):
        result = reconciliation.match(
            [book(invoice_number="CAP-1", is_capital_good=True)], [], period=PERIOD
        )

        assert result.itc_eligible_capital == Decimal("0.00")
        assert result.itc_at_risk == Decimal("81000.00")

    def test_credit_notes_cannot_drive_the_input_share_negative(self):
        """The notes come off the total after the split, so the floor matters."""
        result = reconciliation.match(
            [book(invoice_number="CAP-1", is_capital_good=True)],
            [portal(invoice_number="CAP-1"), note()],
            period=PERIOD,
        )

        assert result.itc_eligible == Decimal("72000.00")
        assert result.itc_eligible_capital == Decimal("81000.00")
        assert result.input_itc_eligible == Decimal("0.00")

    def test_the_run_records_the_split(self, db_session, business):
        save(db_session, business.id, invoice_number="INV-1")
        save(db_session, business.id, invoice_number="CAP-1", is_capital_good=True)
        import_2b(
            db_session,
            business.id,
            [portal(invoice_number="INV-1"), portal(invoice_number="CAP-1")],
        )

        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)

        assert run.itc_eligible == Decimal("162000.00")
        assert run.report["itc_eligible_capital"] == "81000.00"


class TestADuplicateThroughAWholeRun:
    """A duplicate is a verdict about our books, not about the supplier.

    ``match`` produces the DUPLICATE finding and ``test_the_same_invoice_
    booked_twice_is_reported_as_a_duplicate`` covers that. What no test reached
    was the two functions the finding then passes through on a real run, both of
    which have to decline to act on it and both of which do so by falling off
    the end of a chain of ``if``s rather than by naming the category.

    That is the shape that rots quietly. A fifth category added to
    ``MatchCategory``, or a ``status_for`` grown an entry, changes what these do
    with no test failing — and the two wrong answers are a supplier marked down
    for our double entry, and an invoice whose status says it was reconciled
    against a portal row that belongs to the other copy.
    """

    def _run_with_a_double_entry(self, db_session, business):
        """The same bill entered twice, with the separator typed differently.

        That is what a duplicate looks like by the time it reaches a run. The
        partial unique index refuses a second row carrying the byte-identical
        number, so any pair that survives to be reconciled is one the index
        could not see and only ``normalize_invoice_number`` can — here ``D-1``
        and ``D/01``, which both key to ``D1``.
        """
        original = save(db_session, business.id, invoice_number="D-1")
        copy = save(db_session, business.id, invoice_number="D/01")
        import_2b(db_session, business.id, [portal(invoice_number="D-1")])
        run = reconciliation.run_reconciliation(db_session, business.id, PERIOD)
        return run, original, copy

    def test_the_duplicate_is_counted_as_a_duplicate_and_nothing_else(
        self, db_session, business
    ):
        run, _, _ = self._run_with_a_double_entry(db_session, business)

        assert run.duplicate_count == 1
        assert run.matched_count == 1
        assert run.mismatched_count == 0
        assert run.missing_in_2b_count == 0

    def test_the_second_copy_is_marked_duplicate(
        self, db_session, business
    ):
        """``_apply_statuses`` writes DUPLICATE so the copy is excluded from the
        ITC pool, Rule 37, capital goods and the filing register. Writing
        MATCHED would claim the portal row covers both copies; writing
        MISSING_IN_2B would send the user looking for a supplier who filed
        exactly what they owed."""
        _, original, copy = self._run_with_a_double_entry(db_session, business)
        db_session.refresh(original)
        db_session.refresh(copy)

        assert original.status is InvoiceStatus.MATCHED
        assert copy.status is InvoiceStatus.DUPLICATE

    def test_the_supplier_is_not_marked_down_for_our_double_entry(
        self, db_session, business
    ):
        """The duplicate is in the supplier's denominator — they are one of the
        invoices we hold against them — but it is neither matched, mismatched
        nor missing. Counting it as missing would score a supplier who filed
        everything they owed as one who did not, off a mistake in our own
        books; scoring it as matched would inflate them for the same reason.
        """
        db_session.add(
            Supplier(
                business_id=business.id,
                gstin=SUPPLIER_GSTIN_OTHER_STATE,
                legal_name="Northwind",
            )
        )
        db_session.commit()

        run, _, _ = self._run_with_a_double_entry(db_session, business)
        tally = run.report["suppliers"][SUPPLIER_GSTIN_OTHER_STATE]

        assert tally["total"] == 2
        assert tally["matched"] == 1
        assert tally["mismatched"] == 0
        assert tally["missing"] == 0

        supplier = db_session.query(Supplier).filter_by(
            gstin=SUPPLIER_GSTIN_OTHER_STATE
        ).one()
        # The recorded observation is the three real outcomes, so the history
        # the score is computed from never sees our double entry at all.
        assert supplier.missing_invoices == 0
        assert supplier.matched_invoices == 1


class TestReconciliationRunAlwaysStartsRunning:
    """``ReconciliationStatus.QUEUED`` exists in the enum but is never assigned.

    A run enters the database as ``RUNNING`` — there is no queueing step before
    it — and ends as ``COMPLETED`` or ``FAILED``. This test pins that contract:
    if a queuing mechanism is added, the guard in ``latest_completed_run`` and
    the ``QUEUED`` rows' interaction with the ITC screen need auditing.
    """

    def test_a_new_run_starts_at_running(self, db_session, business):
        from app.models.gstr_return import GSTRReturn
        from app.models.gstr_return import ReturnType as RT
        g = GSTRReturn(
            business_id=business.id, period="2026-04",
            return_type=RT.GSTR2B, status="imported",
            data={"invoices": []},
        )
        db_session.add(g)
        db_session.commit()
        run = reconciliation.run_reconciliation(db_session, business.id, "2026-04")
        assert run.status in (
            ReconciliationStatus.RUNNING,
            ReconciliationStatus.COMPLETED,
            ReconciliationStatus.FAILED,
        )
        assert run.status is not ReconciliationStatus.QUEUED

    def test_queued_is_never_used_across_the_codebase(self):
        import ast
        import pathlib
        app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
        for py_file in app_dir.rglob("*.py"):
            source = py_file.read_text()
            if "QUEUED" not in source:
                continue
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Attribute) and node.attr == "QUEUED"
                        and isinstance(node.value, ast.Attribute)
                        and node.value.attr == "ReconciliationStatus"):
                    raise AssertionError(
                        f"{py_file.relative_to(app_dir.parent)}:{node.lineno} "
                        "assigns or reads ReconciliationStatus.QUEUED"
                    )
