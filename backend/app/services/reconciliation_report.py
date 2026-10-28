"""The paid PDF report of one reconciliation run.

Built from what the run already stored — its counters, its ITC figures and the
per-invoice findings in ``run.report`` — and nothing read afresh. A report is
what this run concluded, so an invoice corrected since must not change a PDF
that was paid for as a record of that moment; re-running the period is how a
business gets a report of the books as they are now.
"""
from __future__ import annotations

import calendar
from decimal import Decimal, InvalidOperation
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.business import Business
from app.models.reconciliation_run import MatchCategory, ReconciliationRun

# Most urgent first: what is costing credit now, then what is wrong in the
# books, and the invoices that need nothing last.
SECTIONS = (
    (
        MatchCategory.MISSING_IN_2B,
        "Missing in GSTR-2B",
        "In your books but not filed by the supplier. This credit is at risk until "
        "they file.",
    ),
    (
        MatchCategory.MISMATCHED,
        "Mismatched",
        "Filed by the supplier with figures that differ from your books.",
    ),
    (
        MatchCategory.MISSING_IN_BOOKS,
        "Missing in your books",
        "Declared in GSTR-2B but not in your purchase register.",
    ),
    (MatchCategory.DUPLICATE, "Duplicates", "The same invoice booked more than once."),
    (MatchCategory.MATCHED, "Matched", "Same invoice, same figures. Nothing to do."),
)

_STYLES = getSampleStyleSheet()
_CELL = _STYLES["BodyText"].clone("cell", fontSize=8, leading=10)
_HEAD = _CELL.clone("head", fontName="Helvetica-Bold")
_GRID = TableStyle(
    [
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
)


def rupees(value: object) -> str:
    """``Rs. 1,23,456.00`` — Indian grouping.

    "Rs." rather than the rupee sign because the base-14 PDF fonts have no
    glyph for it, and embedding a font to get one would triple the file for a
    single character.
    """
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        amount = Decimal("0.00")
    sign = "-" if amount < 0 else ""
    whole, fraction = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}Rs. {whole}.{fraction}"


def period_label(period: str) -> str:
    """``2026-04`` -> ``April 2026``; anything else as it came."""
    try:
        year, month = period.split("-")
        return f"{calendar.month_name[int(month)]} {int(year)}"
    except (ValueError, IndexError):
        return period


def _p(text: object, style=_CELL) -> Paragraph:
    # Paragraph parses its text as markup, and supplier names come from
    # uploaded invoices and the portal: an "&" or "<" in one is not a tag.
    return Paragraph(escape("" if text is None else str(text)), style)


def _tax(side: object) -> str:
    if not isinstance(side, dict):
        return "-"
    return rupees(side.get("total_tax"))


def _note(finding: dict) -> str:
    parts = []
    for diff in finding.get("differences") or []:
        if isinstance(diff, dict):
            parts.append(
                f"{str(diff.get('field', '')).replace('_', ' ')}: books "
                f"{rupees(diff.get('books'))}, 2B {rupees(diff.get('gstr2b'))}"
            )
    if finding.get("carried"):
        parts.append("Booked in an earlier period; not counted in this one.")
    if finding.get("note"):
        parts.append(str(finding["note"]))
    return "; ".join(parts)


def _findings_table(findings: list[dict]) -> Table:
    header = ["Invoice no.", "Supplier", "Supplier GSTIN", "Date", "Tax (books)",
              "Tax (2B)", "Notes"]
    rows = [[_p(h, _HEAD) for h in header]]
    for finding in findings:
        rows.append([
            _p(finding.get("invoice_number") or "-"),
            _p(finding.get("supplier_name") or "-"),
            _p(finding.get("supplier_gstin") or "-"),
            _p(finding.get("invoice_date") or "-"),
            _p(_tax(finding.get("books"))),
            _p(_tax(finding.get("gstr2b"))),
            _p(_note(finding)),
        ])
    widths = [x * mm for x in (32, 52, 36, 22, 28, 28, 70)]
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(_GRID)
    return table


def _pairs_table(pairs: list[tuple[str, str]]) -> Table:
    table = Table([[_p(k, _HEAD), _p(v)] for k, v in pairs], colWidths=[60 * mm, 50 * mm])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey)]))
    return table


def build_pdf(run: ReconciliationRun, business: Business) -> bytes:
    """The report for *run* as PDF bytes."""
    report = run.report if isinstance(run.report, dict) else {}
    findings = [f for f in report.get("findings") or [] if isinstance(f, dict)]

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"GSTR-2B reconciliation {run.period}",
        author="DoAide GST",
        # Fixed document id and timestamps, so the same run renders to the same
        # bytes — which is what lets a test compare two downloads.
        invariant=1,
    )

    when = run.completed_at.date().isoformat() if run.completed_at else "-"
    story = [
        _p("GSTR-2B Reconciliation Report", _STYLES["Title"]),
        _p(f"{business.legal_name}  |  GSTIN {business.gstin or 'not set'}", _STYLES["Heading3"]),
        _p(f"Period {period_label(run.period)}  |  Reconciled on {when}  |  Run #{run.id}"),
        Spacer(1, 6 * mm),
        _p("Summary", _STYLES["Heading2"]),
        _pairs_table([
            ("Purchase invoices", str(run.total_invoices)),
            ("Matched", str(run.matched_count)),
            ("Mismatched", str(run.mismatched_count)),
            ("Missing in GSTR-2B", str(run.missing_in_2b_count)),
            ("Missing in your books", str(run.missing_in_books_count)),
            ("Duplicates", str(run.duplicate_count)),
        ]),
        Spacer(1, 4 * mm),
        _p("ITC impact", _STYLES["Heading2"]),
        _pairs_table([
            ("ITC eligible (safe to claim)", rupees(run.itc_eligible)),
            ("ITC at risk", rupees(run.itc_at_risk)),
            ("ITC claimed in your books", rupees(run.itc_claimed)),
            ("Credit notes netted off", rupees(report.get("credit_notes", "0"))),
        ]),
    ]

    for category, heading, explanation in SECTIONS:
        rows = [f for f in findings if f.get("category") == category.value]
        story += [
            Spacer(1, 6 * mm),
            _p(f"{heading} ({len(rows)})", _STYLES["Heading2"]),
            _p(explanation),
            Spacer(1, 2 * mm),
        ]
        story.append(_findings_table(rows) if rows else _p("None."))

    story += [
        Spacer(1, 8 * mm),
        _p(
            "Prepared by DoAide GST from the purchase register and the GSTR-2B "
            "imported for this period. It is a working paper for your review, "
            "not a filing."
        ),
    ]
    doc.build(story)
    return buffer.getvalue()
