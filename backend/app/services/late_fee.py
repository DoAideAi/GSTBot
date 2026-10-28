"""Late fee and interest on a return filed after its due date — ss.47 and 50.

Two different penalties, on two different bases, and conflating them is the
mistake this module exists to avoid:

* **Late fee** (s.47) is a flat per-day amount for filing *late*, regardless
  of what is owed. It runs from the day after the due date to the day the
  return is actually filed — or to today, projected, while it still sits
  unfiled — split evenly between CGST and SGST, and capped by a table the
  government has revised by notification more than once.
* **Interest** (s.50(1)) is 18% per annum, simple, on the tax actually *paid
  late* — the net cash liability, output tax less eligible ITC — and it has
  nothing to do with when the return was filed. A business that settles the
  cash ledger on the due date but files the return three days later owes a
  full late fee and no interest; one that files on time but pays a week later
  owes interest and no late fee. Only GSTR-3B carries interest, because it is
  the only return a cash payment is made through: GSTR-1 declares supplies
  and GSTR-2B is not even filed — see :mod:`app.services.gst_calendar` on why
  it has no due date at all.

Both are the ordinary-case flat rates. The notified relief rates for specific
past periods (the pandemic waivers of 2020-21, chiefly) are not modelled: which
of those applied turned on the filing date of a return that predates this
product, not on any figure it holds, and a period reconciled today still owes
the ordinary rate on the money it is short by.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.gstr_return import ReturnType
from app.models.mixins import ZERO
from app.services import filing as filing_service
from app.services import gst_calendar, invoice_service
from app.services import itc as itc_service

# Section 50(1): 18% per annum, simple interest, on the tax paid late.
INTEREST_RATE_PA = Decimal("0.18")
DAYS_PER_YEAR = Decimal("365")

# Section 47(1): flat per-day fee, split evenly between CGST and SGST. A nil
# return — nothing to declare, nothing to pay — is charged a lower rate; the
# split is the same shape either way.
LATE_FEE_PER_DAY = Decimal("50.00")
NIL_LATE_FEE_PER_DAY = Decimal("20.00")

# Nil return cap. Flat across every turnover band since the government
# collapsed the tiers for it: a return with nothing on it costs the same
# whether the filer is a shop or a conglomerate.
NIL_LATE_FEE_CAP = Decimal("500.00")


@dataclass(frozen=True)
class TurnoverTier:
    """A late-fee cap, and the turnover band it applies above."""

    label: str
    cap: Decimal


# Ordered by ascending threshold; the last tier has no ceiling. Aggregate
# turnover is the *previous financial year's*, which is a figure this product
# has no invoice history to derive — DoAide GST only ever holds what has been
# uploaded since a business signed up, not the years before — so it is always
# an input the caller supplies, never something computed here.
_TURNOVER_TIERS: list[tuple[Decimal | None, TurnoverTier]] = [
    (Decimal("15000000"), TurnoverTier("turnover up to ₹1.5 crore", Decimal("2000.00"))),
    (Decimal("50000000"), TurnoverTier("turnover ₹1.5–5 crore", Decimal("5000.00"))),
    (None, TurnoverTier("turnover above ₹5 crore", Decimal("10000.00"))),
]


def turnover_tier(previous_year_turnover: Decimal | None) -> TurnoverTier:
    """The late-fee cap for *previous_year_turnover*.

    ``None`` gets the highest cap rather than the lowest or an unbounded one.
    An estimate is read as a number to budget against, and the failure modes
    of guessing wrong are not symmetric: understating a real business's cap
    hands them a shortfall notice weeks after this screen told them they were
    covered, while overstating it costs nothing but a slightly conservative
    number. The highest tier is the only answer that cannot be an
    understatement.
    """
    if previous_year_turnover is not None:
        # The last tier's threshold is ``None`` — the top slab is open-ended —
        # so a real turnover always returns from inside the loop and never
        # falls out of it. The line below is reached only by ``None``, and
        # stands as the answer if that table ever loses its open end.
        for threshold, tier in _TURNOVER_TIERS:  # pragma: no branch
            if threshold is None or previous_year_turnover <= threshold:
                return tier
    return _TURNOVER_TIERS[-1][1]


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def interest(net_tax: Decimal, days_late: int) -> Decimal:
    """Section 50(1) simple interest on *net_tax*, over *days_late* days.

    Zero for a period that owes nothing, or one that is not yet late — a
    negative ``days_late`` is a due date still ahead, not a rebate.

    Both guards are stated at ``<=`` rather than ``<`` to say what they mean,
    not because the equal case would compute wrongly without them: zero days or
    zero tax multiplies out to zero anyway, and only a *negative* one needs
    catching. Nothing can distinguish the two forms, so the mutation run leaves
    two survivors here permanently — see the score note in ``tools/mutation.py``.
    """
    if days_late <= 0 or net_tax <= ZERO:
        return ZERO
    return _q(net_tax * INTEREST_RATE_PA * Decimal(days_late) / DAYS_PER_YEAR)


@dataclass(frozen=True)
class LateFee:
    """Section 47 late fee for one return, split by head."""

    cgst: Decimal
    sgst: Decimal
    tier: TurnoverTier

    @property
    def total(self) -> Decimal:
        return self.cgst + self.sgst


def late_fee(
    days_late: int, *, is_nil: bool, previous_year_turnover: Decimal | None = None
) -> LateFee:
    """Section 47(1) late fee for *days_late* days, capped by turnover.

    The per-day rate runs and is capped as one figure, then split into equal
    CGST and SGST halves — never computed per head and summed, which would
    let independent rounding drift the two heads apart by a paisa the portal
    would refuse to reconcile.
    """
    if days_late <= 0:
        return LateFee(cgst=ZERO, sgst=ZERO, tier=turnover_tier(previous_year_turnover))

    if is_nil:
        total = min(NIL_LATE_FEE_PER_DAY * Decimal(days_late), NIL_LATE_FEE_CAP)
        tier = TurnoverTier("nil return", NIL_LATE_FEE_CAP)
    else:
        tier = turnover_tier(previous_year_turnover)
        total = min(LATE_FEE_PER_DAY * Decimal(days_late), tier.cap)

    half = _q(total / 2)
    # The remaining paisa, if the total was odd, goes to CGST rather than
    # being dropped — the two heads must sum to exactly what was capped, and
    # SGST is the one the portal computes second.
    return LateFee(cgst=_q(total) - half, sgst=half, tier=tier)


def _net_cash_liability(sales: dict, credit: dict) -> Decimal:
    """What the period's GSTR-3B pays in cash: output tax after set-off.

    The same definition the dashboard's net-liability card uses (see
    :func:`app.routers.dashboard._net_liability`), and both go through
    :func:`app.services.itc.set_off`. Interest is charged on what was actually
    paid in cash, so credit has to cross heads the way the ledger lets it:
    IGST credit settles CGST and SGST, and each of those settles IGST. Netting
    head against head charged 18% on ₹2,000 of CGST and SGST that ₹2,000 of
    IGST credit had already paid.
    """
    def heads(bucket: dict) -> itc_service.TaxHeads:
        return itc_service.TaxHeads(
            **{head: Decimal(bucket[head]) for head in ("igst", "cgst", "sgst", "cess")}
        )

    return itc_service.set_off(heads(credit), heads(sales)).total_cash


@dataclass(frozen=True)
class LateFeeEstimate:
    """What ss.47 and 50 cost a period's GSTR-1 or GSTR-3B, as of one date."""

    period: str
    return_type: ReturnType
    due_date: date
    as_of: date
    filed_on: date | None
    days_late: int
    is_nil: bool
    net_tax_liability: Decimal
    fee: LateFee
    interest_amount: Decimal

    @property
    def projected(self) -> bool:
        """True while the return is unfiled and the clock is still running.

        The figures are as-of :attr:`as_of` either way; this only says whether
        that is a settled amount (the return was filed on :attr:`filed_on`) or
        an estimate that grows if nothing changes before tomorrow.
        """
        return self.filed_on is None

    @property
    def total_payable(self) -> Decimal:
        return self.fee.total + self.interest_amount

    def as_dict(self) -> dict:
        return {
            "period": self.period,
            "return_type": self.return_type.value,
            "due_date": self.due_date.isoformat(),
            "as_of": self.as_of.isoformat(),
            "filed_on": self.filed_on.isoformat() if self.filed_on else None,
            "days_late": self.days_late,
            "projected": self.projected,
            "is_nil": self.is_nil,
            "net_tax_liability": str(self.net_tax_liability),
            "late_fee_cgst": str(self.fee.cgst),
            "late_fee_sgst": str(self.fee.sgst),
            "late_fee_total": str(self.fee.total),
            "late_fee_tier": self.fee.tier.label,
            "interest": str(self.interest_amount),
            "total_payable": str(self.total_payable),
        }


def estimate_from_summary(
    db: Session,
    business: Business,
    period: str,
    return_type: ReturnType,
    summary: dict,
    *,
    as_of: date | None = None,
    is_nil: bool | None = None,
    previous_year_turnover: Decimal | None = None,
) -> LateFeeEstimate:
    """:func:`estimate`, given a tax summary the caller already has.

    Split out for the dashboard, which computes exactly this summary for
    every period on the trend chart in one grouped scan of the invoice table
    — see :func:`app.services.invoice_service.tax_summaries` — and must not
    pay for a second one just to price a fee card. Everything except the
    summary itself is recomputed here rather than passed through, because it
    is cheap enough (one query against ``gstr_returns``) that a second
    argument list for it would cost more to read than it saves.
    """
    if return_type not in gst_calendar.DUE_DAY:
        raise ValueError(
            f"{return_type.value} is not a return this business files, so it has "
            "no due date and no late fee or interest."
        )

    as_of = as_of or gst_calendar.today_ist()
    due = gst_calendar.due_date(period, return_type)

    standing = next(
        line
        for line in filing_service.standings(db, business.id, periods=[period], as_of=as_of)
        if line.return_type is return_type
    )
    filed_on = standing.filed_on
    reference_date = filed_on or as_of
    days_late = max(0, (reference_date - due).days)

    sales, purchase, credit = summary["sales"], summary["purchase"], summary["credit"]
    net_tax = _net_cash_liability(sales, credit)

    if is_nil is None:
        is_nil = int(sales["count"]) == 0 and int(purchase["count"]) == 0

    fee = late_fee(days_late, is_nil=is_nil, previous_year_turnover=previous_year_turnover)
    interest_amount = (
        interest(net_tax, days_late) if return_type is ReturnType.GSTR3B else ZERO
    )

    return LateFeeEstimate(
        period=period,
        return_type=return_type,
        due_date=due,
        as_of=as_of,
        filed_on=filed_on,
        days_late=days_late,
        is_nil=is_nil,
        net_tax_liability=net_tax,
        fee=fee,
        interest_amount=interest_amount,
    )


def estimate(
    db: Session,
    business: Business,
    period: str,
    return_type: ReturnType = ReturnType.GSTR3B,
    *,
    as_of: date | None = None,
    is_nil: bool | None = None,
    previous_year_turnover: Decimal | None = None,
) -> LateFeeEstimate:
    """Late fee and interest for one return, as of *as_of* (default: today).

    Reads the same filed-or-not answer :func:`app.services.filing.standings`
    gives the status screen and the deadline alerting, so this never disagrees
    with either about whether a return is actually late. While a return sits
    unfiled the estimate is a projection that grows by the day; once it is
    recorded filed, :attr:`LateFeeEstimate.projected` turns false and the
    figures are what was actually run up.

    Interest applies to GSTR-3B alone — see the module docstring — so a GSTR-1
    estimate always carries zero interest rather than a return type this
    function refuses outright: a caller building one status line per return
    type does not want a branch of its own for the one that has none.

    *is_nil* is inferred from the period's invoice counts when not given:
    zero sales and zero purchases on file is the closest this product can get
    to "nothing to declare" without a claim about liabilities it has never
    seen an invoice for. Pass it explicitly when it is known, because a
    business with invoices still mid-extraction can look empty by this
    heuristic when it is not.

    Queries the period's tax summary itself. A caller that already has one —
    the dashboard, computing six months of them in a single scan — should use
    :func:`estimate_from_summary` instead rather than pay for a second scan.
    """
    summary = invoice_service.tax_summary(db, business.id, period)
    return estimate_from_summary(
        db,
        business,
        period,
        return_type,
        summary,
        as_of=as_of,
        is_nil=is_nil,
        previous_year_turnover=previous_year_turnover,
    )
