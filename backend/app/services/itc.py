"""Input Tax Credit: what may be claimed, what must be reversed, what it settles.

Three separate questions, deliberately kept apart because they are governed by
different parts of the Act and fail in different ways:

* **How much credit is available.** Reconciliation already answers this per
  invoice — credit is capped by what the supplier declared in GSTR-2B. This
  module only pools that answer by tax head.
* **How much must be given back.** Rules 37, 42 and 43 reverse credit that was
  legitimately taken at the time and stopped being available later: because the
  supplier was never paid, because the input fed an exempt supply, or because a
  capital good's credit belongs to sixty months rather than one.
* **How the credit settles the liability.** Sections 49, 49A and 49B fix the
  order in which credit is set off against output tax. The order is not a
  preference — using the wrong head first leaves a business paying cash it did
  not need to pay while credit expires in the ledger.

The set-off is the part worth reading twice. CGST and SGST credit may never
touch each other's liability: they are levied by different governments, and the
ledger keeps them apart no matter how convenient the offset would be. IGST is
the only credit that crosses, and it must be exhausted first.

Every figure is ``Decimal``. GST is computed to the paisa, and a float cannot
hold 18% of ₹1,234.56.
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models.invoice import UNCOUNTABLE_STATUSES, Invoice, InvoiceType
from app.services import gst_calendar, reconciliation

ZERO = Decimal("0.00")

# Rule 37: credit is reversed when the supplier has not been paid within 180
# days of the invoice date. Counted from the invoice date, not the receipt date
# or the filing date — the Act ties it to the document.
RULE_37_DAYS = 180

# Invoices inside this window of the deadline are reported as approaching it,
# so a business can pay a supplier before the credit reverses rather than after.
RULE_37_WARNING_DAYS = 30

# Rule 43 spreads capital-goods credit over sixty months, starting with the
# month of purchase.
RULE_43_MONTHS = 60

# The heads, in the order every breakdown in this module reports them.
HEADS = ("igst", "cgst", "sgst", "cess")


def _q(value: Decimal) -> Decimal:
    """Round to paise, half-up — the rounding the GST rules specify."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class TaxHeads:
    """An amount split across the four tax heads."""

    igst: Decimal = ZERO
    cgst: Decimal = ZERO
    sgst: Decimal = ZERO
    cess: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.igst + self.cgst + self.sgst + self.cess

    def __add__(self, other: TaxHeads) -> TaxHeads:
        return TaxHeads(
            igst=self.igst + other.igst,
            cgst=self.cgst + other.cgst,
            sgst=self.sgst + other.sgst,
            cess=self.cess + other.cess,
        )

    def scaled(self, factor: Decimal) -> TaxHeads:
        """This split multiplied by *factor*, re-rounded to paise."""
        return TaxHeads(
            igst=_q(self.igst * factor),
            cgst=_q(self.cgst * factor),
            sgst=_q(self.sgst * factor),
            cess=_q(self.cess * factor),
        )

    def as_dict(self) -> dict:
        return {
            "igst": str(_q(self.igst)),
            "cgst": str(_q(self.cgst)),
            "sgst": str(_q(self.sgst)),
            "cess": str(_q(self.cess)),
            "total": str(_q(self.total)),
        }


# ---------------------------------------------------------------------------
# Section 49 / 49A / 49B — the set-off waterfall
# ---------------------------------------------------------------------------

@dataclass
class SetOffStep:
    """One application of credit from one head against one liability."""

    credit_head: str
    liability_head: str
    amount: Decimal

    def as_dict(self) -> dict:
        return {
            "credit_head": self.credit_head,
            "liability_head": self.liability_head,
            "amount": str(_q(self.amount)),
        }


@dataclass
class SetOffResult:
    """How credit settled a period's liability, and what is left on each side."""

    steps: list[SetOffStep] = field(default_factory=list)
    cash_payable: TaxHeads = field(default_factory=TaxHeads)
    credit_carried_forward: TaxHeads = field(default_factory=TaxHeads)
    credit_used: TaxHeads = field(default_factory=TaxHeads)

    @property
    def total_cash(self) -> Decimal:
        return self.cash_payable.total

    def as_dict(self) -> dict:
        return {
            "steps": [step.as_dict() for step in self.steps],
            "cash_payable": self.cash_payable.as_dict(),
            "credit_carried_forward": self.credit_carried_forward.as_dict(),
            "credit_used": self.credit_used.as_dict(),
            "total_cash": str(_q(self.total_cash)),
        }


def set_off(credit: TaxHeads, liability: TaxHeads) -> SetOffResult:
    """Apply *credit* against *liability* in the statutory order.

    The order, from s.49(5) as amended by 49A and 49B:

    1. IGST credit against IGST liability, then against CGST, then SGST. IGST
       must be exhausted before any other credit is touched — that is what 49A
       says, and it is the rule most often got wrong, because using CGST credit
       first looks equivalent and is not.
    2. CGST credit against CGST liability, then against IGST.
    3. SGST credit against SGST liability, then against IGST.
    4. Cess credit against cess liability only.

    CGST credit is never applied to SGST liability or the reverse. The two are
    levied by different governments and the ledger does not let them meet, so a
    business with CGST credit and only SGST liability pays the SGST in cash and
    carries the CGST forward. Reporting anything else would understate the cash
    a business has to find this month.

    Within step 1, IGST is spread across CGST and SGST in whatever proportion
    the taxpayer chooses (rule 88A), and the choice matters, because the CGST
    and SGST credit behind it cannot cross. Applying IGST to CGST first, as
    this used to, turned ₹100 IGST + ₹100 CGST credit against ₹100 CGST +
    ₹100 SGST liability into ₹100 of SGST paid in cash with the CGST credit
    stranded — when pointing the IGST at SGST settles both. So the IGST goes
    first to the part of each head its own credit cannot cover, and only then
    to what is left of either; within each of those, CGST before SGST, which
    is the portal's default and keeps the answer reproducible. IGST is still
    exhausted before any other credit is touched.
    """
    remaining_credit = TaxHeads(
        igst=max(ZERO, credit.igst),
        cgst=max(ZERO, credit.cgst),
        sgst=max(ZERO, credit.sgst),
        cess=max(ZERO, credit.cess),
    )
    remaining_liability = TaxHeads(
        igst=max(ZERO, liability.igst),
        cgst=max(ZERO, liability.cgst),
        sgst=max(ZERO, liability.sgst),
        cess=max(ZERO, liability.cess),
    )
    result = SetOffResult()
    used = {head: ZERO for head in HEADS}

    def apply(credit_head: str, liability_head: str, cap: Decimal | None = None) -> None:
        available = getattr(remaining_credit, credit_head)
        owed = getattr(remaining_liability, liability_head)
        amount = min(available, owed) if cap is None else min(available, owed, cap)
        if amount <= ZERO:
            return
        setattr(remaining_credit, credit_head, available - amount)
        setattr(remaining_liability, liability_head, owed - amount)
        used[credit_head] += amount
        result.steps.append(
            SetOffStep(
                credit_head=credit_head, liability_head=liability_head, amount=_q(amount)
            )
        )

    # 1. IGST first, and completely — s.49A.
    apply("igst", "igst")
    igst_left = remaining_credit.igst
    to_cgst = min(igst_left, max(ZERO, remaining_liability.cgst - remaining_credit.cgst))
    to_sgst = min(igst_left - to_cgst, max(ZERO, remaining_liability.sgst - remaining_credit.sgst))
    spare = igst_left - to_cgst - to_sgst
    extra_cgst = min(spare, remaining_liability.cgst - to_cgst)
    to_cgst += extra_cgst
    to_sgst += min(spare - extra_cgst, remaining_liability.sgst - to_sgst)
    apply("igst", "cgst", to_cgst)
    apply("igst", "sgst", to_sgst)
    # 2 and 3. Own head first, then IGST. Never each other's.
    apply("cgst", "cgst")
    apply("cgst", "igst")
    apply("sgst", "sgst")
    apply("sgst", "igst")
    # 4. Cess is ring-fenced.
    apply("cess", "cess")

    result.cash_payable = TaxHeads(
        igst=_q(remaining_liability.igst),
        cgst=_q(remaining_liability.cgst),
        sgst=_q(remaining_liability.sgst),
        cess=_q(remaining_liability.cess),
    )
    result.credit_carried_forward = TaxHeads(
        igst=_q(remaining_credit.igst),
        cgst=_q(remaining_credit.cgst),
        sgst=_q(remaining_credit.sgst),
        cess=_q(remaining_credit.cess),
    )
    result.credit_used = TaxHeads(
        igst=_q(used["igst"]),
        cgst=_q(used["cgst"]),
        sgst=_q(used["sgst"]),
        cess=_q(used["cess"]),
    )
    return result


# ---------------------------------------------------------------------------
# Rule 37 — credit on invoices left unpaid past 180 days
# ---------------------------------------------------------------------------

@dataclass
class Rule37Item:
    """One unpaid purchase, and where it stands against the 180-day clock."""

    invoice_id: int
    invoice_number: str | None
    supplier_gstin: str | None
    supplier_name: str | None
    invoice_date: date | None
    days_outstanding: int | None
    days_remaining: int | None
    tax: TaxHeads
    overdue: bool

    def as_dict(self) -> dict:
        return {
            "invoice_id": self.invoice_id,
            "invoice_number": self.invoice_number,
            "supplier_gstin": self.supplier_gstin,
            "supplier_name": self.supplier_name,
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "days_outstanding": self.days_outstanding,
            "days_remaining": self.days_remaining,
            "tax": self.tax.as_dict(),
            "overdue": self.overdue,
        }


@dataclass
class Rule37Result:
    """Credit that has reversed, and credit about to.

    ``reversal`` is the standing exposure: every rupee of credit currently
    resting on an invoice past its 180 days, however long ago it lapsed. That
    is the right figure for a screen asking "what am I carrying", and the wrong
    one for a return. See :meth:`reversal_in`.
    """

    overdue: list[Rule37Item] = field(default_factory=list)
    approaching: list[Rule37Item] = field(default_factory=list)
    reversal: TaxHeads = field(default_factory=TaxHeads)
    approaching_amount: TaxHeads = field(default_factory=TaxHeads)

    def reversal_in(self, period: str) -> TaxHeads:
        """Of the standing exposure, the part that lapsed *during* *period*.

        Rule 37 is paid once, in the return for the tax period in which the
        180 days elapse, and re-availed when the supplier is finally paid. It
        is not a balance that is re-declared every month — but ``reversal`` is
        cumulative, so a 3B built from it reversed the same invoice again in
        every return that followed. An invoice that lapsed in April was
        reversed in April, then in May, then in June, indefinitely, each time
        as though it were new; a business filing four months of returns gave
        back four times the credit the rule asks for.

        The lapse falls on the day *after* the 180th, because the Act allows
        the whole of day 180 — the same boundary :func:`rule_37` draws when it
        decides an invoice is overdue at all.
        """
        start = gst_calendar.period_start(period)
        end = gst_calendar.period_end(period)
        total = TaxHeads()
        for item in self.overdue:
            if item.invoice_date is None:
                continue
            if start <= lapse_date(item.invoice_date) <= end:
                total = total + item.tax
        return total

    def as_dict(self) -> dict:
        return {
            "overdue": [item.as_dict() for item in self.overdue],
            "approaching": [item.as_dict() for item in self.approaching],
            "reversal": self.reversal.as_dict(),
            "approaching_amount": self.approaching_amount.as_dict(),
            "days": RULE_37_DAYS,
            "warning_days": RULE_37_WARNING_DAYS,
        }


def lapse_date(invoice_date: date) -> date:
    """The day Rule 37's credit reverses on an invoice dated *invoice_date*.

    The day *after* the 180th, because the Act allows the whole of day 180.
    One definition, because two halves of the same rule read it — the reversal
    in :meth:`Rule37Result.reversal_in` and the re-availment in
    :func:`rule_37_reavailment` — and a boundary that differed by a day between
    them would reverse credit in one month and give it back in another, or give
    back credit that was never reversed.
    """
    return invoice_date + timedelta(days=RULE_37_DAYS + 1)


def rule_37_reavailment(invoices: list[Invoice], period: str) -> TaxHeads:
    """Credit reversed for non-payment that *period* is entitled to take back.

    The second half of Rule 37, and the half that was missing. The proviso to
    s.16(2)(d) is explicit that the reversal is not forfeiture: "the recipient
    shall be entitled to avail of the input tax credit on payment made by him".
    The credit comes back in the return for the tax period the supplier is
    actually paid in, at table 4(A)(5).

    Only the reversal existed here. :meth:`Rule37Result.reversal_in` gave the
    credit back to the government in the month the 180 days ran out, and
    :func:`rule_37` then dropped the invoice from every later calculation the
    moment ``paid_at`` was set — so paying the supplier in September stopped the
    reversal recurring and returned nothing. The credit simply left the books.
    For a business that pays late at all, that is a permanent overstatement of
    tax: every invoice that ever crossed 180 days costs its whole ITC, once,
    for good, whatever happens afterwards.

    Two conditions, and the second is what keeps this from inventing credit:

    * The supplier was paid *during* this period, so the entitlement arises now
      and arises exactly once.
    * The invoice had already lapsed *before* this period began. An invoice that
      crossed 180 days and was paid inside the same month was never reversed —
      ``rule_37`` reads ``paid_at`` as of the close of the period and excludes
      it — so re-availing it would hand back credit the return never gave up.

    Pure, and over the whole purchase register rather than the period's own
    invoices: the invoice being paid is by construction at least six months old
    and belongs to another period.
    """
    start = gst_calendar.period_start(period)
    end = gst_calendar.period_end(period)
    total = TaxHeads()
    for invoice in invoices:
        if invoice.paid_at is None or invoice.invoice_date is None:
            continue
        if not invoice.claims_credit:
            continue
        if not start <= invoice.paid_at <= end:
            continue
        if lapse_date(invoice.invoice_date) >= start:
            # Never reversed by a return this one follows: either it has not
            # lapsed at all, or it lapsed in this very period and was paid
            # before the period closed.
            continue
        tax = _invoice_tax(invoice)
        if tax.total <= ZERO:
            continue
        total = total + tax
    return total


def _invoice_tax(invoice: Invoice) -> TaxHeads:
    return TaxHeads(
        igst=invoice.igst or ZERO,
        cgst=invoice.cgst or ZERO,
        sgst=invoice.sgst or ZERO,
        cess=invoice.cess or ZERO,
    )


def rule_37(invoices: list[Invoice], *, as_of: date | None = None) -> Rule37Result:
    """Credit exposed by non-payment, from a list of purchase invoices.

    Pure: takes rows, returns an answer. An invoice counts when it is unpaid
    (``paid_at`` is None) and claims credit at all — a blocked-credit or
    reverse-charge purchase has no credit to reverse, and reporting one would
    send a business chasing a payment for no tax reason.

    "Unpaid" is judged as of *as_of*, not as of now. A payment made after the
    date being asked about had not happened yet on that date, and reading
    ``paid_at`` as a plain flag made a closed period's answer depend on what has
    happened since. That is not a display quirk: :func:`app.services.filing.build_gstr3b`
    anchors this to the close of the period precisely so that re-generating an
    old return reproduces it, and paying the supplier in February silently
    deleted the reversal from January's 3B — a return that had already been
    filed with it, and whose stored copy ``record_filing`` rewrites every time
    the ARN is corrected. Under-reversed credit is over-claimed credit, and it
    carries interest.

    An invoice with no date is skipped rather than assumed overdue. The clock
    runs from the invoice date, and a missing date means the extraction failed,
    not that 180 days have passed.

    The 180 days are counted in Indian calendar days, because that is the
    calendar the invoice date is written in and the one the Act is enforced in.
    Reading the day off a UTC clock is a day short for the five and a half
    hours after midnight IST, and the invoice that crosses day 180 in that
    window is reported as still inside it — which understates the reversal in
    GSTR-3B, and an understated reversal is over-claimed credit with interest
    on it.
    """
    today = as_of or gst_calendar.today_ist()
    result = Rule37Result()

    for invoice in invoices:
        if invoice.paid_at is not None and invoice.paid_at <= today:
            continue
        if not invoice.claims_credit:
            continue
        if invoice.invoice_date is None:
            continue

        tax = _invoice_tax(invoice)
        if tax.total <= ZERO:
            continue

        outstanding = (today - invoice.invoice_date).days
        remaining = RULE_37_DAYS - outstanding
        item = Rule37Item(
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            supplier_gstin=invoice.counterparty_gstin,
            supplier_name=invoice.counterparty_name,
            invoice_date=invoice.invoice_date,
            days_outstanding=outstanding,
            days_remaining=remaining,
            tax=tax,
            overdue=remaining < 0,
        )
        # Strictly past the 180th day: the Act allows the whole of day 180, so
        # an invoice exactly 180 days old has not yet reversed.
        if remaining < 0:
            result.overdue.append(item)
            result.reversal = result.reversal + tax
        elif remaining <= RULE_37_WARNING_DAYS:
            result.approaching.append(item)
            result.approaching_amount = result.approaching_amount + tax

    result.overdue.sort(key=lambda i: i.days_outstanding or 0, reverse=True)
    result.approaching.sort(key=lambda i: i.days_remaining or 0)
    return result


# ---------------------------------------------------------------------------
# Rules 42 and 43 — proportionate reversal on exempt supplies
# ---------------------------------------------------------------------------

@dataclass
class ProportionateResult:
    """The common-credit reversal for one period, under Rules 42 and 43."""

    exempt_turnover: Decimal = ZERO
    total_turnover: Decimal = ZERO
    exempt_ratio: Decimal = ZERO
    common_credit: TaxHeads = field(default_factory=TaxHeads)
    rule_42_reversal: TaxHeads = field(default_factory=TaxHeads)
    capital_credit: TaxHeads = field(default_factory=TaxHeads)
    capital_credit_this_month: TaxHeads = field(default_factory=TaxHeads)
    rule_43_reversal: TaxHeads = field(default_factory=TaxHeads)

    @property
    def total_reversal(self) -> TaxHeads:
        return self.rule_42_reversal + self.rule_43_reversal

    def as_dict(self) -> dict:
        return {
            "exempt_turnover": str(_q(self.exempt_turnover)),
            "total_turnover": str(_q(self.total_turnover)),
            "exempt_ratio": str(self.exempt_ratio.quantize(Decimal("0.000001"))),
            "common_credit": self.common_credit.as_dict(),
            "rule_42_reversal": self.rule_42_reversal.as_dict(),
            "capital_credit": self.capital_credit.as_dict(),
            "capital_credit_this_month": self.capital_credit_this_month.as_dict(),
            "rule_43_reversal": self.rule_43_reversal.as_dict(),
            "total_reversal": self.total_reversal.as_dict(),
            "capital_months": RULE_43_MONTHS,
        }


def proportionate_reversal(
    *,
    common_credit: TaxHeads,
    capital_credit: TaxHeads,
    exempt_turnover: Decimal,
    total_turnover: Decimal,
) -> ProportionateResult:
    """Rules 42 and 43: the share of common credit that fed exempt supplies.

    Rule 42 covers inputs and input services. The reversible share is

        D1 = (E / F) x C2

    where ``E`` is exempt turnover, ``F`` is total turnover, and ``C2`` is the
    common credit — credit on purchases used for both taxable and exempt
    supplies. Credit attributable *exclusively* to exempt supplies is not
    common credit at all; it was never available, and it should never have been
    included in ``common_credit`` by the caller.

    Rule 43 does the same for capital goods, except that the credit is spread
    over sixty months first: only ``Tm = Tc / 60`` belongs to this month, and
    the exempt share of that is what reverses.

    A zero total turnover gives a zero ratio rather than a division error. A
    period with no outward supply at all has no exempt proportion to compute,
    and guessing one would reverse credit on no evidence.
    """
    exempt = max(ZERO, exempt_turnover)
    total = max(ZERO, total_turnover)
    # Exempt turnover cannot exceed total turnover; if a caller passes figures
    # that say otherwise, cap the ratio at 1 rather than reversing more credit
    # than exists.
    ratio = min(Decimal("1"), exempt / total) if total > ZERO else Decimal("0")

    monthly_capital = capital_credit.scaled(Decimal("1") / Decimal(RULE_43_MONTHS))

    return ProportionateResult(
        exempt_turnover=exempt,
        total_turnover=total,
        exempt_ratio=ratio,
        common_credit=common_credit,
        rule_42_reversal=common_credit.scaled(ratio),
        capital_credit=capital_credit,
        capital_credit_this_month=monthly_capital,
        rule_43_reversal=monthly_capital.scaled(ratio),
    )


def capital_goods_in_service(invoices: list[Invoice], period: str) -> TaxHeads:
    """``Tc`` for *period*: every capital good still inside its sixty months.

    Rule 43 does not give a capital good's credit to the month it was bought.
    It gives one sixtieth of it to each of sixty months beginning with that
    one, so the instalment a business may claim in any period is a sixtieth of
    the *pool* of capital goods bought in that period or in the fifty-nine
    before it — not a sixtieth of what it happened to buy this month.

    Pooling matters because the caller divides once. Summing the goods still in
    service and dividing the total by sixty gives the same figure as dividing
    each good by sixty and adding, and it is the shape ``proportionate_reversal``
    already takes.

    A purchase with no period is skipped. The instalment schedule is anchored to
    the month of purchase, and a row whose date was never extracted cannot be
    placed on it; guessing a month would start the sixty running from the wrong
    end. Purchases *after* the period are skipped too, so re-opening an earlier
    month does not claim credit on a machine that had not been bought yet.

    Blocked and reverse-charge purchases carry no credit to spread, exactly as
    in the input pool.
    """
    oldest = gst_calendar.months_before(period, RULE_43_MONTHS - 1)
    pool = TaxHeads()
    for invoice in invoices:
        if not invoice.is_capital_good:
            continue
        if not invoice.claims_credit:
            continue
        if not invoice.period or not oldest <= invoice.period <= period:
            continue
        pool = pool + _invoice_tax(invoice)
    return pool


# ---------------------------------------------------------------------------
# Section 9(3)/9(4) — tax the buyer pays on the supplier's behalf
# ---------------------------------------------------------------------------

@dataclass
class ReverseChargePosition:
    """Tax owed on inward supplies under reverse charge, and what it earns.

    Reverse charge is the one place a *purchase* creates a liability. On a
    freight bill from a goods transport agency, on a lawyer's fee, on rent from
    an unregistered landlord, the supplier charges nothing and the buyer pays
    the tax to the government directly. It is declared in GSTR-3B table 3.1(d),
    and it is not optional.

    Two things follow, and they pull in opposite directions:

    * **It must be paid in cash.** s.49(4) lets the credit ledger settle
      "output tax", and s.2(82) defines output tax to exclude tax payable on
      reverse charge. A ledger full of credit does not reduce this by a rupee,
      which is why it is kept out of :class:`SetOffResult` and reported beside
      it instead.
    * **It becomes credit.** Once paid it is input tax like any other, claimed
      in the same return at table 4(A)(3) — unless the input is one s.17(5)
      blocks, which is what ``itc_eligible`` records.

    So the cash effect of an ordinary reverse-charge purchase is close to nil
    over the month, and the *declaration* is the whole point: leaving 3.1(d)
    empty understates the liability, and interest runs on the shortfall from
    the due date whether or not the credit was there to cover it.
    """

    taxable_value: Decimal = ZERO
    tax: TaxHeads = field(default_factory=TaxHeads)
    credit: TaxHeads = field(default_factory=TaxHeads)
    invoice_count: int = 0

    def as_dict(self) -> dict:
        return {
            "taxable_value": str(_q(self.taxable_value)),
            "tax": self.tax.as_dict(),
            "credit": self.credit.as_dict(),
            "invoice_count": self.invoice_count,
            "cash_payable": str(_q(self.tax.total)),
        }


def reverse_charge_position(invoices: list[Invoice]) -> ReverseChargePosition:
    """The reverse-charge liability carried by *invoices*, and its credit.

    Pure, over one period's purchases. An invoice counts when it is flagged
    reverse charge and carries tax; the credit half counts only the part
    s.17(5) does not block.
    """
    position = ReverseChargePosition()
    for invoice in invoices:
        if not invoice.reverse_charge:
            continue
        tax = _invoice_tax(invoice)
        if tax.total <= ZERO:
            # Nothing to declare and nothing to claim. A row whose tax boxes
            # are empty is an extraction that missed them, not a supply the
            # government is owed nothing on, and inventing a figure for it
            # would put a made-up liability on a return.
            continue
        position.invoice_count += 1
        position.taxable_value += invoice.taxable_value or ZERO
        position.tax = position.tax + tax
        if invoice.itc_eligible:
            position.credit = position.credit + tax
    return position


# ---------------------------------------------------------------------------
# The period summary the API serves
# ---------------------------------------------------------------------------

@dataclass
class ITCSummary:
    """Everything the ITC screen shows for one period."""

    period: str
    available: TaxHeads
    output_tax: TaxHeads
    rule_37: Rule37Result
    proportionate: ProportionateResult
    net_available: TaxHeads
    set_off: SetOffResult
    itc_at_risk: Decimal
    reconciled: bool
    invoice_count: int
    unclaimed_count: int
    # Of ``rule_37.reversal`` — the standing exposure over the whole register —
    # the part that lapsed during this period, and therefore the part this
    # period's return gives back. See :meth:`Rule37Result.reversal_in`.
    rule_37_reversal: TaxHeads = field(default_factory=TaxHeads)
    # The other direction of the same rule: credit reversed in an earlier
    # period on an invoice whose supplier was paid *in* this one. It is not in
    # ``available`` — that pool is built from this period's own purchases, and
    # the invoice being paid is six months old — so it is added to the credit
    # separately. See :func:`rule_37_reavailment`.
    rule_37_reavailment: TaxHeads = field(default_factory=TaxHeads)
    reverse_charge: ReverseChargePosition = field(default_factory=ReverseChargePosition)

    @property
    def total_reversal(self) -> TaxHeads:
        """What this period reverses, across all three rules.

        Rule 37's contribution is the period's share, not the standing
        exposure: the rest was already given back in the returns for the months
        it lapsed in.
        """
        return self.rule_37_reversal + self.proportionate.total_reversal

    @property
    def cash_payable(self) -> Decimal:
        """Every rupee this period has to be paid in cash, both liabilities.

        The set-off says what output tax the credit ledger could not settle.
        The reverse-charge liability is added whole, because credit may not
        settle any of it — see :class:`ReverseChargePosition`. Reported as one
        figure because it is one payment challan, and a screen that showed only
        the set-off's half told a business to find less money than it owes.
        """
        return _q(self.set_off.total_cash + self.reverse_charge.tax.total)

    def as_dict(self) -> dict:
        return {
            "period": self.period,
            "available": self.available.as_dict(),
            "output_tax": self.output_tax.as_dict(),
            "rule_37": self.rule_37.as_dict(),
            "rule_37_reversal": self.rule_37_reversal.as_dict(),
            "rule_37_reavailment": self.rule_37_reavailment.as_dict(),
            "proportionate": self.proportionate.as_dict(),
            "total_reversal": self.total_reversal.as_dict(),
            "net_available": self.net_available.as_dict(),
            "set_off": self.set_off.as_dict(),
            "reverse_charge": self.reverse_charge.as_dict(),
            "cash_payable": str(self.cash_payable),
            "itc_at_risk": str(_q(self.itc_at_risk)),
            "reconciled": self.reconciled,
            "invoice_count": self.invoice_count,
            "unclaimed_count": self.unclaimed_count,
        }


def _purchases(
    db: Session,
    business_id: int,
    period: str | None = None,
    *,
    narrowed_by: Sequence = (),
) -> list[Invoice]:
    """Purchase invoices that could carry credit, oldest first.

    *narrowed_by* is how a caller adds its own predicate without restating
    what a purchase register is. What belongs in one — undeleted, inward, and
    readable enough to carry a figure — is decided here and in one place, so a
    caller that narrows the register cannot quietly widen it.
    """
    conditions = [
        Invoice.business_id == business_id,
        Invoice.deleted_at.is_(None),
        Invoice.invoice_type == InvoiceType.PURCHASE,
        Invoice.status.not_in(UNCOUNTABLE_STATUSES),
        *narrowed_by,
    ]
    if period:
        conditions.append(Invoice.period == period)
    return list(
        db.scalars(
            select(Invoice)
            .where(*conditions)
            .order_by(Invoice.invoice_date.asc(), Invoice.id.asc())
        ).all()
    )


def purchase_invoices(
    db: Session,
    business_id: int,
    period: str | None = None,
    *,
    credit_only: bool = False,
) -> list[Invoice]:
    """Purchase invoices that could carry credit, oldest first.

    Public because Rule 37 is asked of the whole register from the router, not
    just of the period under review.

    *credit_only* narrows in SQL to invoices whose credit the buyer may
    actually take — ``itc_eligible`` and not ``reverse_charge`` — so the caller
    that only needs those does not hydrate rows it will skip.
    """
    narrowed_by = (
        (Invoice.itc_eligible.is_(True), Invoice.reverse_charge.is_(False))
        if credit_only
        else ()
    )
    return _purchases(db, business_id, period, narrowed_by=narrowed_by)


def purchases_outside_periods(
    db: Session,
    business_id: int,
    *,
    excluding: Collection[str],
    from_period: str | None = None,
) -> list[Invoice]:
    """The purchase register minus the months the caller has already settled.

    Exists for the s.16(4) sweep, which asks what credit is still unclaimed and
    so discards every invoice whose period is recorded as filed. Asked of the
    whole register, that is nearly all of them: a business two years in has
    filed twenty-three of its twenty-four months, and reading those rows out of
    the database to drop them in Python costs the same whether one month is
    outstanding or none. The daily alert sweep is what makes it matter — once
    per tenant, across every tenant, growing with how long each has been a
    customer rather than with anything the alert could be about.

    Rows with no ``period`` come back regardless of *excluding* and
    *from_period*. Their month is derived from the invoice date, which is the
    caller's rule rather than a column, so those rows are still decided where
    they always were; this narrows the query without moving the answer.
    """
    narrowing = []
    if excluding:
        narrowing.append(
            or_(Invoice.period.is_(None), Invoice.period.not_in(sorted(excluding)))
        )
    if from_period is not None:
        narrowing.append(or_(Invoice.period.is_(None), Invoice.period >= from_period))
    return _purchases(db, business_id, narrowed_by=narrowing)


def _outward_tax_and_turnover(
    db: Session, business_id: int, period: str
) -> tuple[TaxHeads, Decimal, Decimal]:
    """Output tax, exempt turnover and total turnover in one scan."""
    tax_col = Invoice.igst + Invoice.cgst + Invoice.sgst + Invoice.cess

    row = db.execute(
        select(
            func.coalesce(func.sum(Invoice.igst), 0),
            func.coalesce(func.sum(Invoice.cgst), 0),
            func.coalesce(func.sum(Invoice.sgst), 0),
            func.coalesce(func.sum(Invoice.cess), 0),
            func.coalesce(func.sum(Invoice.taxable_value), 0),
            func.coalesce(
                func.sum(
                    case(
                        (and_(tax_col == 0, Invoice.taxable_value > 0), Invoice.taxable_value),
                        else_=0,
                    )
                ),
                0,
            ),
        ).where(
            Invoice.business_id == business_id,
            Invoice.deleted_at.is_(None),
            Invoice.invoice_type == InvoiceType.SALES,
            Invoice.period == period,
            Invoice.status.not_in(UNCOUNTABLE_STATUSES),
        )
    ).one()
    output_tax = TaxHeads(
        igst=Decimal(str(row[0])),
        cgst=Decimal(str(row[1])),
        sgst=Decimal(str(row[2])),
        cess=Decimal(str(row[3])),
    )
    total_turnover = Decimal(str(row[4]))
    exempt_turnover = Decimal(str(row[5]))
    return output_tax, exempt_turnover, total_turnover


def _input_eligible(run) -> Decimal:
    """A run's eligible credit with the capital-goods share taken out.

    The capital share is written to the run's ``report`` rather than to a
    column. A run recorded before that field existed does not carry it, and is
    read as having none: that reproduces the old figure rather than inventing a
    new one, and re-running the period is what corrects it.
    """
    total = run.itc_eligible or ZERO
    report = run.report if isinstance(run.report, dict) else {}
    try:
        capital = Decimal(str(report.get("itc_eligible_capital") or "0"))
    except (ArithmeticError, ValueError):
        capital = ZERO
    return max(ZERO, total - capital)


def _combined_purchase_scan(
    invoices: list[Invoice],
    period: str,
    *,
    as_of: date | None = None,
) -> tuple[Rule37Result, TaxHeads, TaxHeads]:
    """rule_37 + rule_37_reavailment + capital_goods_in_service in one pass."""
    today = as_of or gst_calendar.today_ist()
    r37 = Rule37Result()
    reavail = TaxHeads()
    cap_pool = TaxHeads()

    p_start = gst_calendar.period_start(period)
    p_end = gst_calendar.period_end(period)
    oldest_cap = gst_calendar.months_before(period, RULE_43_MONTHS - 1)

    for invoice in invoices:
        if not invoice.claims_credit:
            continue

        idate = invoice.invoice_date

        # --- capital_goods_in_service ---
        if invoice.is_capital_good and invoice.period and oldest_cap <= invoice.period <= period:
            cap_pool = cap_pool + _invoice_tax(invoice)

        # --- rule_37 ---
        if idate is not None and (invoice.paid_at is None or invoice.paid_at > today):
            tax = _invoice_tax(invoice)
            if tax.total > ZERO:
                outstanding = (today - idate).days
                remaining = RULE_37_DAYS - outstanding
                item = Rule37Item(
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    supplier_gstin=invoice.counterparty_gstin,
                    supplier_name=invoice.counterparty_name,
                    invoice_date=idate,
                    days_outstanding=outstanding,
                    days_remaining=remaining,
                    tax=tax,
                    overdue=remaining < 0,
                )
                if remaining < 0:
                    r37.overdue.append(item)
                    r37.reversal = r37.reversal + tax
                elif remaining <= RULE_37_WARNING_DAYS:
                    r37.approaching.append(item)
                    r37.approaching_amount = r37.approaching_amount + tax

        # --- rule_37_reavailment ---
        if (
            invoice.paid_at is not None
            and idate is not None
            and p_start <= invoice.paid_at <= p_end
            and lapse_date(idate) < p_start
        ):
            tax = _invoice_tax(invoice)
            if tax.total > ZERO:
                reavail = reavail + tax

    r37.overdue.sort(key=lambda i: i.days_outstanding or 0, reverse=True)
    r37.approaching.sort(key=lambda i: i.days_remaining or 0)
    return r37, reavail, cap_pool


def summarise(
    db: Session,
    business_id: int,
    period: str,
    *,
    as_of: date | None = None,
    exempt_turnover: Decimal | None = None,
    total_turnover: Decimal | None = None,
) -> ITCSummary:
    """The full ITC position for *period*.

    Credit availability comes from the latest reconciliation *that finished*,
    because only the 2B knows what a supplier actually declared. Without one the
    books are all there is, so the figure is what has been *claimed* rather than
    what is safe — the ``reconciled`` flag says which, and the caller is
    expected to say so on screen. Presenting an unreconciled total as "eligible"
    is exactly the overstatement that produces a reversal with interest.

    A run that failed or is still running is not a reconciliation for this
    purpose, however recent it is: its figures are column defaults, and reading
    them here caps the period's credit at zero. See
    :func:`~app.services.reconciliation.latest_completed_run`.

    Rule 37 deliberately looks at the whole purchase register, not just this
    period: an invoice from eight months ago is the one that crosses 180 days,
    and scoping it to the period under review would never show it.

    Rule 43 looks past the period for the opposite reason. A capital good's
    credit is due in sixty monthly instalments starting with the month of
    purchase, so fifty-nine of them fall in periods later than the one that
    bought it. Reading only this period's purchases gave a business the first
    instalment and then nothing — see :func:`capital_goods_in_service`.
    """
    period_purchases = _purchases(db, business_id, period)
    # Rule 37, Rule 43 and rule_37_reavailment each check ``claims_credit``
    # and skip every invoice that fails it, so loading non-credit purchases
    # is pure waste.  Narrowing in SQL keeps those rows off the wire and out
    # of the session entirely.
    all_purchases = _purchases(
        db, business_id,
        narrowed_by=(Invoice.itc_eligible.is_(True), Invoice.reverse_charge.is_(False)),
    )

    last_run = reconciliation.latest_completed_run(db, business_id, period)

    # Claimable credit by head, from the books. Capital goods are excluded from
    # the input pool: their credit belongs to Rule 43's sixty months. So are
    # reverse-charge purchases: no supplier charged that tax, so it is not
    # credit on this document — it is credit on the payment the business is
    # about to make, and it is pooled with the liability that creates it.
    available = TaxHeads()
    unclaimed = 0
    for invoice in period_purchases:
        if invoice.reverse_charge:
            continue
        if not invoice.itc_eligible:
            # Exempt, nil-rated, or blocked under s.17(5): tax was paid and is
            # simply not creditable.
            unclaimed += 1
            continue
        if invoice.is_capital_good:
            continue
        available = available + _invoice_tax(invoice)

    # s.9(3)/9(4) inward supplies: a liability, and the credit it earns.
    # Counted before the blocked ones, because a reverse-charge purchase that
    # s.17(5) also blocks is the one case where the tax is paid in cash and no
    # credit comes back — the most expensive row on the register, and the one
    # a business most needs to see.
    reverse_charge = reverse_charge_position(period_purchases)
    unclaimed += sum(
        1
        for invoice in period_purchases
        if invoice.reverse_charge and not invoice.itc_eligible
    )

    rule_37_result, reavailment, capital_credit = _combined_purchase_scan(
        all_purchases, period, as_of=as_of,
    )

    # Where a reconciliation exists, cap the pool at what it found eligible.
    # The run reports one total rather than a per-head split, so scale the
    # book split down by the same proportion rather than inventing a shape the
    # evidence does not have.
    #
    # Capital goods come off the run's total first, because they are not in
    # ``available`` — Rule 43 holds their credit in its own pool above. Compared
    # against the whole of what the run found eligible, the cap stopped binding
    # the moment a business bought anything capital: a machine's ₹1.8 lakh sat
    # in the run's total, dwarfed the input pool, and the shortfall a supplier
    # had left in their own filing was claimed in full. The cap exists to catch
    # exactly that shortfall, so both sides of it have to mean inputs.
    if last_run is not None and available.total > ZERO:
        eligible_total = _input_eligible(last_run)
        if eligible_total < available.total:
            available = available.scaled(eligible_total / available.total)

    output_tax, exempt, total = _outward_tax_and_turnover(db, business_id, period)
    if exempt_turnover is not None:
        exempt = exempt_turnover
    if total_turnover is not None:
        total = total_turnover
    proportionate = proportionate_reversal(
        common_credit=available,
        capital_credit=capital_credit,
        exempt_turnover=exempt,
        total_turnover=total,
    )

    # What is left after every reversal, floored at zero per head: a reversal
    # larger than the period's credit produces a liability, not negative credit.
    #
    # Rule 37 contributes only what lapsed *in* this period. The standing
    # exposure stays on ``rule_37`` for the screen to list, but a period's
    # credit bears a reversal once, in the month the 180 days ran out — the
    # earlier ones were already given back in the returns for the months they
    # lapsed in, and charging them again here makes every month after the first
    # understate the credit by the whole of the running total.
    #
    # The reverse-charge credit joins the pool here rather than in
    # ``available``: it is credit this period may claim, at table 4(A)(3), but
    # it is not credit the *supplier* charged, so it has no place in the pool
    # the reconciliation caps against — GSTR-2B has nothing to say about tax
    # the buyer pays themselves — and it is not common credit for Rule 42's
    # ratio, which is applied to ``available`` above.
    #
    # Rule 37's re-availment joins it from the other side, and for the mirror
    # reason: an invoice paid this month after its credit lapsed is entitled to
    # that credit back (proviso to s.16(2)(d)), and it is not in ``available``
    # either — the invoice is at least six months old, so it belongs to another
    # period's purchases and to another period's reconciliation. Without it the
    # reversal was one-way and permanent, and a business that pays a supplier
    # late lost the whole of that invoice's credit for good.
    rule_37_reversal = rule_37_result.reversal_in(period)
    reversal = rule_37_reversal + proportionate.total_reversal
    net_available = TaxHeads(
        igst=max(ZERO, available.igst + proportionate.capital_credit_this_month.igst
                 + reverse_charge.credit.igst + reavailment.igst - reversal.igst),
        cgst=max(ZERO, available.cgst + proportionate.capital_credit_this_month.cgst
                 + reverse_charge.credit.cgst + reavailment.cgst - reversal.cgst),
        sgst=max(ZERO, available.sgst + proportionate.capital_credit_this_month.sgst
                 + reverse_charge.credit.sgst + reavailment.sgst - reversal.sgst),
        cess=max(ZERO, available.cess + proportionate.capital_credit_this_month.cess
                 + reverse_charge.credit.cess + reavailment.cess - reversal.cess),
    )

    return ITCSummary(
        period=period,
        available=available,
        output_tax=output_tax,
        rule_37=rule_37_result,
        proportionate=proportionate,
        net_available=net_available,
        set_off=set_off(net_available, output_tax),
        itc_at_risk=(last_run.itc_at_risk if last_run else ZERO) or ZERO,
        reconciled=last_run is not None,
        invoice_count=len(period_purchases),
        unclaimed_count=unclaimed,
        rule_37_reversal=rule_37_reversal,
        rule_37_reavailment=reavailment,
        reverse_charge=reverse_charge,
    )
