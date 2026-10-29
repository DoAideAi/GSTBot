"""Supplier health: how much of a supplier's paperwork can be relied on.

The score answers a question with money attached — *how much of the credit
resting on this supplier should be provided against?* — so it is built from
observed filing behaviour rather than from a rating anyone assigns by hand.

Four components, weighted by how strongly each predicts a credit actually
surviving to be claimed:

======================  ======  ==================================================
Component               Weight  What it measures
======================  ======  ==================================================
Match rate               50%    Of this supplier's invoices, how many appeared in
                                GSTR-2B with the same figures. The single best
                                predictor: a supplier who files correctly keeps
                                filing correctly.
Filing timeliness        20%    Whether they file by the 11th, or two months late.
                                A late filer's credit arrives eventually — but not
                                in the period the buyer wanted to claim it.
Consistency              20%    Whether behaviour holds period to period. A
                                supplier who alternates between perfect and absent
                                is a worse risk than a steady 80%, and an average
                                hides that completely.
Recency                  10%    Whether they have filed lately at all. A supplier
                                last seen four periods ago is drifting toward
                                having deregistered.
======================  ======  ==================================================

Two deliberate refusals:

* **A supplier with no history is not scored.** ``None`` and a low score mean
  different things — "we have no evidence" and "the evidence is bad" — and
  collapsing them would have a business provisioning against a supplier they
  have simply not bought from yet.
* **The score is per-tenant.** The same GSTIN can be reliable to one buyer and
  a chronic late filer to another, and the product has no authority to publish
  a shared reputation.

Confidence is reported alongside the score, because three invoices and three
hundred do not support the same conclusion, and the provisioning recommendation
is deliberately gentler when the evidence is thin.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models.invoice import (
    UNCOUNTABLE_STATUSES,
    Invoice,
    InvoiceStatus,
    InvoiceType,
)
from app.models.supplier import RiskLevel, Supplier
from app.services import gst_calendar

ZERO = Decimal("0.00")

# Component weights. They sum to 100; a component with no evidence is dropped
# and the rest are renormalised, so a supplier with matches but no filing dates
# is still scored on what is known rather than penalised for what is not.
WEIGHT_MATCH_RATE = Decimal("50")
WEIGHT_TIMELINESS = Decimal("20")
WEIGHT_CONSISTENCY = Decimal("20")
WEIGHT_RECENCY = Decimal("10")

# A mismatch is a data problem — the invoice exists and the credit is mostly
# recoverable once someone reconciles the figures. A missing invoice is the
# supplier not having filed, and scores nothing.
MISMATCH_CREDIT = Decimal("0.5")

# Filing this many days past the due date scores zero for timeliness. Set at a
# full period: a supplier who is a month late has already cost the buyer the
# claim they wanted to make.
TIMELINESS_ZERO_AT_DAYS = 30

# Periods of silence before recency is exhausted.
RECENCY_ZERO_AT_PERIODS = 6

# Invoices observed before the score is treated as fully supported. Below this,
# confidence scales linearly and provisioning is softened toward the default.
FULL_CONFIDENCE_INVOICES = 20

# Score thresholds for the risk bands.
LOW_RISK_AT = 85
MEDIUM_RISK_AT = 60


def _q(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Component:
    """One scored dimension, kept so the number can be explained."""

    name: str
    score: Decimal | None  # 0-100, or None when there is no evidence.
    weight: Decimal
    detail: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "score": None if self.score is None else float(_q(self.score)),
            "weight": float(self.weight),
            "detail": self.detail,
        }


@dataclass
class Observation:
    """What one period showed about one supplier."""

    period: str
    matched: int = 0
    mismatched: int = 0
    missing: int = 0
    # Days between the GSTR-1 due date and when the supplier actually filed.
    # Negative is early, None is unknown.
    filing_delay_days: int | None = None

    @property
    def total(self) -> int:
        return self.matched + self.mismatched + self.missing

    @property
    def match_rate(self) -> Decimal | None:
        """Weighted share of this period's invoices that survived matching."""
        if self.total == 0:
            return None
        weighted = Decimal(self.matched) + MISMATCH_CREDIT * Decimal(self.mismatched)
        return weighted / Decimal(self.total) * Decimal("100")

    def as_dict(self) -> dict:
        return {
            "period": self.period,
            "matched": self.matched,
            "mismatched": self.mismatched,
            "missing": self.missing,
            "filing_delay_days": self.filing_delay_days,
        }


@dataclass
class SupplierScore:
    """A supplier's health, with the working shown."""

    gstin: str
    score: int | None
    risk_level: RiskLevel
    confidence: Decimal  # 0-1.
    # How much evidence the score rests on. Required rather than defaulted:
    # there is one place that builds a score and it counts both, and a zero
    # standing in for "nobody said" would read as a supplier with no history.
    invoices_observed: int
    periods_observed: int
    components: list[Component] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    recommended_provision_pct: Decimal = ZERO
    recommendation: str = ""

    def as_dict(self) -> dict:
        return {
            "gstin": self.gstin,
            "score": self.score,
            "risk_level": self.risk_level.value,
            "confidence": float(self.confidence.quantize(Decimal("0.01"))),
            "components": [component.as_dict() for component in self.components],
            "observations": [observation.as_dict() for observation in self.observations],
            "invoices_observed": self.invoices_observed,
            "periods_observed": self.periods_observed,
            "recommended_provision_pct": float(_q(self.recommended_provision_pct)),
            "recommendation": self.recommendation,
        }


def _periods_between(earlier: str, later: str) -> int:
    """Whole months from *earlier* to *later*, both ``YYYY-MM``."""
    ey, em = (int(part) for part in earlier.split("-"))
    ly, lm = (int(part) for part in later.split("-"))
    return (ly - ey) * 12 + (lm - em)


def _match_rate_component(observations: list[Observation]) -> Component:
    """Share of all observed invoices that matched, pooled across periods.

    Pooled rather than averaged per period: a period with one invoice and a
    period with two hundred are not equal evidence, and averaging their rates
    would let a single bad month with one invoice outweigh a good year.
    """
    total = sum(o.total for o in observations)
    if total == 0:
        return Component("match_rate", None, WEIGHT_MATCH_RATE, "No invoices observed")

    matched = sum(o.matched for o in observations)
    mismatched = sum(o.mismatched for o in observations)
    missing = sum(o.missing for o in observations)
    weighted = Decimal(matched) + MISMATCH_CREDIT * Decimal(mismatched)
    score = weighted / Decimal(total) * Decimal("100")
    return Component(
        "match_rate",
        score,
        WEIGHT_MATCH_RATE,
        f"{matched} matched, {mismatched} mismatched, {missing} never filed, of {total}",
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _timeliness_of(delay: int) -> Decimal:
    """Timeliness for a single period's filing delay.

    On or before the due date scores 100; a full period late scores 0; in
    between it falls off linearly. Filing early earns nothing extra — the
    buyer's claim is not improved by the supplier having filed on the 4th
    rather than the 11th.

    Both edges are inclusive, and at both of them the fall-through computes the
    same figure the shortcut returns — a delay of exactly 0 is 100 either way,
    and one of exactly 30 is zero either way. No test can tell the two apart,
    which is why the mutation run leaves a survivor on each and why it is not a
    missing assertion. The shortcuts are here for the early filer, whose
    negative delay the linear form would score above 100.
    """
    if delay <= 0:
        return Decimal("100")
    if delay >= TIMELINESS_ZERO_AT_DAYS:
        return ZERO
    return (
        Decimal("100")
        * (Decimal(TIMELINESS_ZERO_AT_DAYS) - Decimal(delay))
        / Decimal(TIMELINESS_ZERO_AT_DAYS)
    )


def _timeliness_component(observations: list[Observation]) -> Component:
    """How close to the due date the supplier files, period by period.

    Each period is scored on its own and the *scores* are averaged, which is
    not the same as scoring the average delay — and the difference is the whole
    reason this is spelled out.

    Averaging the delays first let an early filing pay for a late one. A
    supplier who filed a month early in March and a month late in April
    averaged to zero days and scored a clean 100, described as filing "on the
    due date", when half of what the buyer claimed had in fact arrived a full
    period after the deadline. That is precisely the supplier this component
    exists to mark: the buyer's April claim was not rescued by March's
    punctuality, because a claim is made in the period it belongs to and
    credit filed late does not arrive in time for it.

    Scoring each period first also makes the cap mean what it says. Filing
    early earns nothing above 100, so it cannot lend anything to another
    period, and a month that is a month late scores zero however early the
    supplier was either side of it.
    """
    delays = [o.filing_delay_days for o in observations if o.filing_delay_days is not None]
    if not delays:
        return Component("timeliness", None, WEIGHT_TIMELINESS, "No filing dates observed")

    score = sum((_timeliness_of(delay) for delay in delays), ZERO) / Decimal(len(delays))

    late = [delay for delay in delays if delay > 0]
    if not late:
        detail = "Files on or before the due date"
    else:
        average_late = float(_q(Decimal(sum(late)) / Decimal(len(late))))
        detail = (
            f"Late on {len(late)} of {_plural(len(delays), 'filing')}, "
            f"by {average_late:.0f} days on average"
        )
    return Component("timeliness", score, WEIGHT_TIMELINESS, detail)


def _consistency_component(observations: list[Observation]) -> Component:
    """Whether the match rate holds steady from period to period.

    Scored from the standard deviation of the per-period match rate: a steady
    80% is a supplier a business can plan around, while alternating 100% and
    40% averages the same and is not. Needs at least two periods; one period is
    a point, not a trend.
    """
    rates = [o.match_rate for o in observations if o.match_rate is not None]
    if len(rates) < 2:
        return Component(
            "consistency", None, WEIGHT_CONSISTENCY, "Needs two periods of history"
        )

    spread = Decimal(str(statistics.pstdev([float(rate) for rate in rates])))
    # A standard deviation of 50 points or more is as inconsistent as this
    # measure distinguishes; everything above scores zero.
    score = max(ZERO, Decimal("100") - spread * Decimal("2"))
    return Component(
        "consistency",
        score,
        WEIGHT_CONSISTENCY,
        f"Match rate varies by {float(_q(spread)):.0f} points across {len(rates)} periods",
    )


def _recency_component(observations: list[Observation], as_of_period: str) -> Component:
    """How recently the supplier was last seen filing anything.

    A supplier who has filed nothing for six periods scores zero: at that point
    the likeliest explanations are that they have stopped trading or had their
    registration cancelled, and either one puts the credit at risk.

    As in :func:`_timeliness_of`, the boundary itself is the same number by
    either route — a gap of exactly six periods scores zero whether the
    shortcut takes it or the linear form does — so the surviving mutant on this
    comparison is an equivalent one rather than an unasserted edge.
    """
    filed = [o.period for o in observations if o.matched or o.mismatched]
    if not filed:
        return Component("recency", None, WEIGHT_RECENCY, "Never seen filing")

    gap = max(0, _periods_between(max(filed), as_of_period))
    if gap >= RECENCY_ZERO_AT_PERIODS:
        score = ZERO
    else:
        score = (
            Decimal("100")
            * (Decimal(RECENCY_ZERO_AT_PERIODS) - Decimal(gap))
            / Decimal(RECENCY_ZERO_AT_PERIODS)
        )
    detail = "Filed this period" if gap == 0 else f"Last filed {gap} period(s) ago"
    return Component("recency", score, WEIGHT_RECENCY, detail)


def _confidence(invoices: int, periods: int) -> Decimal:
    """0-1, from how much evidence the score rests on.

    Volume and spread both count: twenty invoices in one month say less about a
    supplier than twenty across six, because a single good month is not a
    pattern.
    """
    if invoices == 0:
        return Decimal("0")
    volume = min(Decimal("1"), Decimal(invoices) / Decimal(FULL_CONFIDENCE_INVOICES))
    spread = min(Decimal("1"), Decimal(periods) / Decimal("3"))
    return (volume * Decimal("0.7") + spread * Decimal("0.3")).quantize(Decimal("0.01"))


def risk_level_for(score: int | None) -> RiskLevel:
    if score is None:
        return RiskLevel.UNKNOWN
    if score >= LOW_RISK_AT:
        return RiskLevel.LOW
    if score >= MEDIUM_RISK_AT:
        return RiskLevel.MEDIUM
    return RiskLevel.HIGH


def _provisioning(score: int | None, confidence: Decimal) -> tuple[Decimal, str]:
    """How much of this supplier's credit to hold back, and why.

    The provision is the complement of the score — a supplier whose invoices
    survive 70% of the time leaves 30% of their credit exposed — scaled by
    confidence, so a harsh judgement from thin evidence does not turn into a
    large provision on its own. Anything below one percent is not worth a
    journal entry and is reported as none.
    """
    if score is None:
        return ZERO, "No filing history yet. Reconcile a period to build a score."

    raw = (Decimal("100") - Decimal(score)) * confidence
    provision = _q(max(ZERO, raw))

    if provision < Decimal("1"):
        return ZERO, "Files reliably. No provision needed."
    if score >= LOW_RISK_AT:
        return provision, (
            f"Broadly reliable. Hold {provision}% of the credit until the 2B confirms it."
        )
    if score >= MEDIUM_RISK_AT:
        return provision, (
            f"Mixed record. Provide {provision}% against this supplier's credit and "
            "confirm the 2B before claiming."
        )
    return provision, (
        f"Unreliable filer. Provide {provision}% and consider holding payment until "
        "the invoice appears in GSTR-2B."
    )


def score_from_observations(
    gstin: str, observations: list[Observation], *, as_of_period: str
) -> SupplierScore:
    """Score a supplier from its observed periods. Pure: no database.

    Kept free of the session so the weighting can be asserted against plain
    lists — this is arithmetic that decides how much money a business holds
    back, and it should be testable without a fixture.
    """
    ordered = sorted(observations, key=lambda o: o.period)
    components = [
        _match_rate_component(ordered),
        _timeliness_component(ordered),
        _consistency_component(ordered),
        _recency_component(ordered, as_of_period),
    ]

    # Renormalise over the components that have evidence, so a missing
    # dimension neither scores zero nor silently caps the total.
    scored = [c for c in components if c.score is not None]
    total_weight = sum((c.weight for c in scored), ZERO)
    if total_weight > ZERO:
        weighted = sum((c.score * c.weight for c in scored), ZERO)  # type: ignore[operator]
        score: int | None = int(
            (weighted / total_weight).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    else:
        score = None

    invoices = sum(o.total for o in ordered)
    periods = len([o for o in ordered if o.total])
    confidence = _confidence(invoices, periods)
    provision, recommendation = _provisioning(score, confidence)

    return SupplierScore(
        gstin=gstin,
        score=score,
        risk_level=risk_level_for(score),
        confidence=confidence,
        components=components,
        observations=ordered,
        invoices_observed=invoices,
        periods_observed=periods,
        recommended_provision_pct=provision,
        recommendation=recommendation,
    )


def _safe_int(value: object, default: int = 0) -> int:
    """``int(value)`` that survives a non-numeric string in stored JSON."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def observations_from_history(supplier: Supplier) -> list[Observation]:
    """Rebuild observations from a supplier's stored ``filing_history``.

    The history is written by reconciliation as an audit trail for the score;
    reading it back is how the score is recomputed without re-running every
    past reconciliation.
    """
    observations: list[Observation] = []
    for entry in supplier.filing_history or []:
        if not isinstance(entry, dict) or not entry.get("period"):
            continue
        observations.append(
            Observation(
                period=str(entry["period"]),
                matched=_safe_int(entry.get("matched")),
                mismatched=_safe_int(entry.get("mismatched")),
                missing=_safe_int(entry.get("missing")),
                filing_delay_days=(
                    _safe_int(entry["filing_delay_days"], default=0)
                    if entry.get("filing_delay_days") is not None
                    else None
                ),
            )
        )
    return observations


def current_period() -> str:
    """The period the recency component measures the gap back from, in India.

    Read in UTC this is still last month until 05:30 IST on the 1st, which
    shortens every supplier's silence by a period and quietly marks a supplier
    who has stopped filing as more recent than they are.
    """
    return gst_calendar.period_of(gst_calendar.today_ist())


def score_supplier(supplier: Supplier, *, as_of_period: str | None = None) -> SupplierScore:
    """Score one supplier from its own stored history."""
    return score_from_observations(
        supplier.gstin,
        observations_from_history(supplier),
        as_of_period=as_of_period or current_period(),
    )


def apply_score(supplier: Supplier, score: SupplierScore) -> Supplier:
    """Write a score back onto the supplier row."""
    supplier.compliance_score = score.score
    supplier.risk_level = score.risk_level
    return supplier


# The second key of the per-tenant supplier-records lock. Uploads hold
# (business, 0), billing (business, 1) and a run's period claim (business,
# YYYYMM); no period is 2.
SUPPLIER_LOCK_KEY = 2


def lock_supplier_records(db: Session, business_id: int) -> None:
    """Serialise every write to this tenant's supplier histories and scores.

    Two writers: a reconciliation run, which rewrites each supplier's
    ``filing_history`` whole and rescores it, and :func:`rescore_all`. Held
    until the caller's transaction ends. See
    :func:`app.services.reconciliation._lock_supplier_records` for why runs of
    different months need it; it lives here because both writers can import
    this module. SQLite has one writer and no advisory locks.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(select(func.pg_advisory_xact_lock(business_id, SUPPLIER_LOCK_KEY)))


def rescore_all(
    db: Session, business_id: int, *, as_of_period: str | None = None
) -> list[SupplierScore]:
    """Recompute every supplier's score for one tenant.

    Exists because the weighting is expected to change: when it does, existing
    suppliers should reflect the new model without anyone re-running a year of
    reconciliations.
    """
    period = as_of_period or current_period()
    # Under the lock a run holds, and reloading what the session already has.
    # Without either, a rescore read the history a run was about to replace,
    # waited on the run's row lock, and wrote its stale score over the run's
    # fresh one — a score that disagreed with the history stored beside it.
    lock_supplier_records(db, business_id)
    suppliers = db.scalars(
        select(Supplier)
        .where(Supplier.business_id == business_id, Supplier.deleted_at.is_(None))
        .execution_options(populate_existing=True)
    ).all()

    scores: list[SupplierScore] = []
    for supplier in suppliers:
        score = score_supplier(supplier, as_of_period=period)
        apply_score(supplier, score)
        scores.append(score)
    db.commit()
    return scores


@dataclass
class SupplierExposure:
    """The money resting on one supplier right now."""

    # All four are read off one aggregate row, so all four are required. A
    # default would be a figure nothing measured, on a screen whose whole job
    # is to say how much money is resting on this supplier.
    invoice_count: int
    tax_total: Decimal
    tax_at_risk: Decimal
    unpaid_count: int

    def as_dict(self) -> dict:
        return {
            "invoice_count": self.invoice_count,
            "tax_total": str(_q(self.tax_total)),
            "tax_at_risk": str(_q(self.tax_at_risk)),
            "unpaid_count": self.unpaid_count,
        }


def exposure(db: Session, business_id: int, supplier: Supplier) -> SupplierExposure:
    """Credit currently resting on *supplier*'s invoices.

    "At risk" is credit on invoices this supplier has not filed — the
    ``missing_in_2b`` outcome — which is the amount the provisioning
    percentage is meant to be applied to.

    Only tax that is *credit* counts toward it. Blocked purchases under s.17(5)
    and reverse-charge ones carry no claimable credit
    (:attr:`~app.models.invoice.Invoice.claims_credit`), so the supplier's
    failure to file costs the buyer nothing on them and there is nothing to
    provide against. Counting them said otherwise, and said it in the one place
    a business decides whether to hold a payment: a builder whose supplier
    never filed a works-contract invoice was shown the whole of its tax as
    credit they were about to lose, when none of it was ever theirs to claim.

    It also put this figure in flat contradiction with the reconciliation's own
    ``itc_at_risk``, which has always excluded them — the dashboard and the
    supplier screen reporting two different numbers for the same money.

    ``tax_total`` still totals the tax on every one of their documents. That is
    what it says and what the count beside it is: how much of this supplier's
    paperwork is in the books, credit or not.

    Rows whose figures were never extracted or that duplicate another row are
    left out — every status in :data:`~app.models.invoice.UNCOUNTABLE_STATUSES`,
    which is the line the returns, the credit pool and the dashboard all draw. This was the last
    place still excluding ``FAILED`` alone, and the two ways past it are not
    symmetric. A row still queued for a worker carries columns of zeros, so it
    moved no money and inflated both the document count and the unpaid count
    beside it. A row being *re-extracted* is the expensive one: ``PROCESSING``
    is committed before anything is read, so the figures from the previous,
    successful parse sit on it for the length of the parse — counted in full
    here, and counted nowhere else. This screen is where a business decides
    whether to hold a payment, and it was quoting a supplier's exposure from
    rows the return it is about to file does not contain.

    Four figures, so four aggregates and no rows. This used to load every one
    of the supplier's invoices into the session to add up four columns, which
    is a read with no ceiling on it: the supplier a business buys from every
    week is exactly the one whose detail page someone opens, and after a few
    years that is tens of thousands of ORM objects built to produce four
    numbers. Expressed in SQL it is one round trip whatever the history.

    The two flags behind :attr:`~app.models.invoice.Invoice.claims_credit` are
    re-stated here in SQL rather than read off the property, the same way
    ``invoice_service`` states them for its grouped scan. That is a second copy
    of a rule this module's own docstring warns about having four of — it is
    kept honest by ``test_it_agrees_with_what_the_reconciliation_put_at_risk``,
    which asserts this figure against the reconciliation's ``itc_at_risk``,
    reached the other way.
    """
    # The four tax columns are NOT NULL and have been since the initial
    # revision, so they are added as they are. A per-column ``coalesce`` here
    # was defending against a row that cannot exist, and no test could reach
    # it. What can be null is the ``SUM`` over no rows at all, which is what
    # the coalesces below it are for — the same shape ``invoice_service``
    # sums its own money in.
    tax = Invoice.igst + Invoice.cgst + Invoice.sgst + Invoice.cess
    at_risk = and_(
        Invoice.status == InvoiceStatus.MISSING_IN_2B,
        Invoice.itc_eligible.is_(True),
        Invoice.reverse_charge.is_(False),
    )

    invoice_count, tax_total, tax_at_risk, unpaid_count = db.execute(
        select(
            func.count(Invoice.id),
            func.coalesce(func.sum(tax), 0),
            func.coalesce(func.sum(case((at_risk, tax), else_=0)), 0),
            func.count(case((Invoice.paid_at.is_(None), Invoice.id))),
        ).where(
            Invoice.business_id == business_id,
            Invoice.deleted_at.is_(None),
            Invoice.invoice_type == InvoiceType.PURCHASE,
            Invoice.counterparty_gstin == supplier.gstin,
            Invoice.status.not_in(UNCOUNTABLE_STATUSES),
        )
    ).one()

    # Through ``str`` rather than straight into ``Decimal``: SQLite hands a sum
    # over a NUMERIC column back as a float, and ``Decimal(float)`` would carry
    # the binary approximation into money. Same conversion, same reason, as
    # ``invoice_service._summarise``.
    return SupplierExposure(
        invoice_count=int(invoice_count),
        tax_total=Decimal(str(tax_total)),
        tax_at_risk=Decimal(str(tax_at_risk)),
        unpaid_count=int(unpaid_count),
    )
