"""TypeSafe AI's Jev (System One): structured GST classifications.

Jev answers named questions about a piece of text with a label and calibrated
probabilities rather than prose — a ``Choice`` between labels, a ``Score`` on an
ordered rubric. Four questions are asked here:

* the HSN chapter a product or service description falls under,
* the invoice's supply category (B2B, B2C, export, SEZ, nil-rated, exempt),
* a compliance-risk rating on a four-level rubric,
* whether the supply reads as intra-state (CGST+SGST) or inter-state (IGST).

**Every answer is advisory.** A parsed invoice keeps the figures the parser
extracted; Jev's view is stored beside them under ``extraction["jev"]`` for a
reviewer, never written over a field. That matters most for the routing
question: which tax heads apply is decided by comparing the supplier's and the
buyer's state codes, not by trusting the invoice — and not by trusting a model
either. Jev's routing answer is recorded next to the state-code answer so a
disagreement is visible, and nothing acts on it.

External services degrade, never fail. With no ``TYPESAFE_API_KEY``, with the
SDK missing, on a timeout, an error or a malformed answer, every function here
returns ``None`` and the caller carries on exactly as it would without Jev.
After a failure Jev is skipped for ``jev_failure_cooldown_seconds``: parsing
runs inline in the upload request when Celery is off, and a fifty-file batch
during an outage would otherwise wait out fifty timeouts.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from typesafe_sdk import Choice, RetryPolicy, Score, TypeSafeClient

from app.core.config import settings
from app.models.invoice import Invoice, InvoiceType
from app.services import gstin as gstin_service
from app.services import hsn

logger = logging.getLogger(__name__)

INVOICE_CATEGORIES: dict[str, str] = {
    "B2B": "A taxable supply to a GST-registered business; the buyer's GSTIN is on the invoice.",
    "B2C": "A taxable supply to an unregistered buyer or a consumer; no buyer GSTIN.",
    "export": "A supply of goods or services to a buyer outside India.",
    "SEZ": "A supply to a unit or developer in a Special Economic Zone.",
    "nil_rated": "A supply of goods or services that carries a 0% GST rate.",
    "exempt": "A supply exempted from GST by notification.",
}

# Ordered lowest to highest: a Score's expected value is an index into this.
RISK_LEVELS: tuple[str, ...] = ("low_risk", "moderate_risk", "high_risk", "critical_risk")
_RISK_RUBRIC: tuple[str, ...] = (
    "low_risk: complete, internally consistent invoice; nothing a GST officer would query.",
    "moderate_risk: minor gaps or inconsistencies a reviewer should confirm before filing.",
    "high_risk: likely to cause an ITC denial, a GSTR-2B mismatch or a notice if filed as is.",
    "critical_risk: signs of a fake, duplicate or fundamentally wrong invoice.",
)

TAX_ROUTES: dict[str, str] = {
    "intra_state_cgst_sgst": "Supplier and place of supply are in the same state: CGST + SGST.",
    "inter_state_igst": (
        "Supplier and place of supply are in different states, or an import/export: IGST."
    ),
}

# Long OCR text costs tokens and adds nothing to these questions.
MAX_STATE_CHARS = 6000

# Monotonic time until which Jev is skipped. Process-local on purpose: each
# worker discovers an outage on its own first call.
_cooldown_until = 0.0


@dataclass(frozen=True)
class JevChoice:
    label: str
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
        }


@dataclass(frozen=True)
class JevScore:
    level: str
    # The probability-weighted index into the rubric, 0 .. len(rubric) - 1.
    score: float
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in self.probabilities.items()},
        }


@lru_cache(maxsize=1)
def hsn_chapters() -> dict[str, str]:
    """``{"84": "Appliances, Electronics, Machinery", ...}`` from the shipped table.

    Derived rather than written out so the chapters Jev chooses between are
    exactly the ones the HSN search can then show the user — a hand-kept list
    beside ``hsn_data.json`` would be a third copy of one table to drift.
    """
    chapters: dict[str, set[str]] = {}
    for entry in hsn.entries():
        chapters.setdefault(entry.code[:2], set()).add(entry.category)
    return {code: ", ".join(sorted(cats)) for code, cats in sorted(chapters.items())}


def is_configured() -> bool:
    """Whether a key is present. Callers skip the round trip without one."""
    return bool(settings.typesafe_api_key.strip())


def reset_cooldown() -> None:
    global _cooldown_until
    _cooldown_until = 0.0


def _truncate(text: str, limit: int = MAX_STATE_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def system_one(state: str, questions: Mapping[str, Any]) -> Any | None:
    """Ask Jev *questions* about *state*: the SDK response, or ``None``. Never raises."""
    global _cooldown_until
    if not is_configured() or time.monotonic() < _cooldown_until:
        return None
    try:
        with TypeSafeClient(
            api_key=settings.typesafe_api_key.strip(),
            model=settings.typesafe_model,
            timeout=settings.jev_timeout_seconds,
            retry=RetryPolicy(max_retries=0),
        ) as client:
            return client.system_one(state=_truncate(state), questions=dict(questions))
    except Exception as exc:  # noqa: BLE001 - advisory; the caller must not fail
        _cooldown_until = time.monotonic() + settings.jev_failure_cooldown_seconds
        logger.warning(
            "Jev call failed (%s); skipping Jev for %ss",
            type(exc).__name__, settings.jev_failure_cooldown_seconds,
        )
        return None


def _choice(response: Any, name: str, labels: Mapping[str, str]) -> JevChoice | None:
    try:
        answer = response.choices.get(name)
        # An out-of-vocabulary label is dropped rather than passed on: callers
        # dispatch on it, and a label they don't know is no answer at all.
        if answer is None or answer.choice not in labels:
            return None
        return JevChoice(
            answer.choice,
            max(0.0, min(1.0, answer.confidence)),
            {str(k): float(v) for k, v in answer.probabilities.items()},
        )
    except Exception as exc:  # noqa: BLE001 - a malformed answer is no answer
        logger.warning("Malformed Jev answer for %s: %s", name, exc)
        return None


def _risk(response: Any, name: str) -> JevScore | None:
    try:
        answer = response.scores.get(name)
        if answer is None:
            return None
        top = len(RISK_LEVELS) - 1
        score = max(0.0, min(float(top), answer.score))
        return JevScore(
            RISK_LEVELS[round(score)],
            score,
            max(0.0, min(1.0, answer.confidence)),
            # The SDK keys a score's probabilities by integer level already.
            {RISK_LEVELS[k]: float(v) for k, v in answer.probabilities.items() if 0 <= k <= top},
        )
    except Exception as exc:  # noqa: BLE001 - a malformed answer is no answer
        logger.warning("Malformed Jev answer for %s: %s", name, exc)
        return None


def _hsn_question(subject: str) -> Choice:
    return Choice(
        criteria=hsn_chapters(),
        instructions=(
            f"Which HSN/SAC chapter do the goods or services on this {subject} fall under?"
        ),
    )


def _category_question() -> Choice:
    return Choice(
        criteria=INVOICE_CATEGORIES,
        instructions="Which GST supply category does this invoice belong to?",
    )


def _risk_question() -> Score:
    return Score(
        criteria=list(_RISK_RUBRIC),
        instructions="How likely is this invoice to cause a GST compliance problem?",
    )


def _routing_question() -> Choice:
    return Choice(
        criteria=TAX_ROUTES,
        instructions="Is this an intra-state or an inter-state supply?",
    )


# ---------------------------------------------------------------------------
# Single questions
# ---------------------------------------------------------------------------


def classify_hsn_chapter(description: str) -> JevChoice | None:
    """The two-digit HSN/SAC chapter for a product or service description."""
    response = system_one(
        f"A product or service sold in India: {description}",
        {"hsn_chapter": _hsn_question("description")},
    )
    return None if response is None else _choice(response, "hsn_chapter", hsn_chapters())


def categorize_invoice(state: str) -> JevChoice | None:
    response = system_one(state, {"invoice_category": _category_question()})
    return None if response is None else _choice(response, "invoice_category", INVOICE_CATEGORIES)


def score_compliance_risk(state: str) -> JevScore | None:
    response = system_one(state, {"compliance_risk": _risk_question()})
    return None if response is None else _risk(response, "compliance_risk")


def route_transaction(state: str) -> JevChoice | None:
    response = system_one(state, {"tax_routing": _routing_question()})
    return None if response is None else _choice(response, "tax_routing", TAX_ROUTES)


# ---------------------------------------------------------------------------
# A parsed invoice
# ---------------------------------------------------------------------------


def _state_of(gstin: str | None) -> str | None:
    if not gstin:
        return None
    try:
        return gstin_service.parse(gstin).state_code
    except gstin_service.InvalidGSTIN:
        return None


def route_by_state_codes(invoice: Invoice, business_gstin: str | None) -> str | None:
    """The tax route the state codes decide, or ``None`` when one is unknown.

    The supplier is whoever issued the invoice: the counterparty on a
    purchase, this business on a sale. This is the rule, and the only thing
    allowed to pick the tax heads; it is computed here so Jev's routing answer
    can be stored next to it rather than on its own.
    """
    purchase = invoice.invoice_type == InvoiceType.PURCHASE
    supplier_gstin = invoice.counterparty_gstin if purchase else business_gstin
    supplier_state = _state_of(supplier_gstin)
    if supplier_state is None or not invoice.place_of_supply:
        return None
    if supplier_state == invoice.place_of_supply:
        return "intra_state_cgst_sgst"
    return "inter_state_igst"


def invoice_state(invoice: Invoice, business_gstin: str | None) -> str:
    """The parsed invoice as plain text for Jev."""
    if invoice.invoice_type == InvoiceType.PURCHASE:
        direction = "purchase (we are the buyer)"
    else:
        direction = "sale (we are the supplier)"
    rate = "unknown" if invoice.tax_rate is None else f"{invoice.tax_rate}%"
    lines = [
        f"An Indian GST invoice, recorded as a {direction}.",
        f"Our GSTIN: {business_gstin or 'unknown'}",
        f"Counterparty: {invoice.counterparty_name or 'unknown'}, "
        f"GSTIN {invoice.counterparty_gstin or 'none'}",
        f"Invoice number: {invoice.invoice_number or 'missing'}; "
        f"date: {invoice.invoice_date or 'missing'}",
        f"Place of supply (state code): {invoice.place_of_supply or 'unknown'}",
        f"HSN/SAC: {invoice.hsn_code or 'not stated'}; rate: {rate}",
        f"Taxable value: {invoice.taxable_value}; CGST {invoice.cgst}; SGST {invoice.sgst}; "
        f"IGST {invoice.igst}; cess {invoice.cess}; total {invoice.total_value}",
        f"Reverse charge: {'yes' if invoice.reverse_charge else 'no'}",
    ]
    items = [i for i in (invoice.line_items or []) if isinstance(i, dict)]
    if items:
        lines.append("Line items:")
        lines.extend(
            f"  - {i.get('description') or '?'} (HSN {i.get('hsn_code') or 'none'})"
            for i in items[:20]
        )
    if invoice.raw_text:
        lines.append("Invoice text:")
        lines.append(_truncate(invoice.raw_text, 3000))
    return "\n".join(lines)


def assess_invoice(invoice: Invoice, *, business_gstin: str | None = None) -> dict[str, Any] | None:
    """Jev's four answers for a parsed invoice in one call, or ``None``.

    One request rather than four: System One answers several named questions
    about one state together, and this runs inline in an upload. The HSN
    chapter is only asked when the parser found no code — a stated code is the
    supplier's declaration and outranks a guess.
    """
    questions: dict[str, Any] = {
        "invoice_category": _category_question(),
        "compliance_risk": _risk_question(),
        "tax_routing": _routing_question(),
    }
    if not invoice.hsn_code:
        questions["hsn_chapter"] = _hsn_question("invoice")
    response = system_one(invoice_state(invoice, business_gstin), questions)
    if response is None:
        return None
    category = _choice(response, "invoice_category", INVOICE_CATEGORIES)
    risk = _risk(response, "compliance_risk")
    routing = _choice(response, "tax_routing", TAX_ROUTES)
    # Read only when asked: an answer to a question we didn't put is not one
    # to store next to a code the supplier stated.
    chapter = _choice(response, "hsn_chapter", hsn_chapters()) if not invoice.hsn_code else None

    by_state_codes = route_by_state_codes(invoice, business_gstin)
    result: dict[str, Any] = {"model": getattr(response, "model", None)}
    if category is not None:
        result["invoice_category"] = category.as_dict()
    if risk is not None:
        result["compliance_risk"] = risk.as_dict()
    if routing is not None:
        result["tax_routing"] = {
            **routing.as_dict(),
            "by_state_codes": by_state_codes,
            # Only meaningful when the rule could decide; a reviewer reads a
            # True here as "check the place of supply", nothing more.
            "disagrees_with_state_codes": (
                by_state_codes is not None and routing.label != by_state_codes
            ),
        }
    if chapter is not None:
        result["hsn_chapter"] = {**chapter.as_dict(), "heading": hsn_chapters()[chapter.label]}
    return result if len(result) > 1 else None
