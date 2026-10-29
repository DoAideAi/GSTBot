"""The paid PDF report of one reconciliation run.

Built from what the run already stored — its counters, its ITC figures and the
per-invoice findings in ``run.report`` — and nothing read afresh. A report is
what this run concluded, so an invoice corrected since must not change a PDF
that was paid for as a record of that moment; re-running the period is how a
business gets a report of the books as they are now.
"""
from __future__ import annotations

import calendar
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
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
        # The font a plain-string cell is drawn in — the same face, size and
        # leading as _CELL, so it reads identically to a Paragraph beside it.
        ("FONT", (0, 1), (-1, -1), _CELL.fontName, _CELL.fontSize, _CELL.leading),
    ]
)
# Table's default left + right padding, in points.
_PADDING = 12
# Lines one findings cell may take: 300 pt of a landscape A4 frame about 515 pt
# tall, leaving room for the repeated header row.
_MAX_CELL_LINES = 30


def rupees(value: object) -> str:
    """``Rs. 1,23,456.00`` — Indian grouping.

    "Rs." rather than the rupee sign because the base-14 PDF fonts have no
    glyph for it, and embedding a font to get one would triple the file for a
    single character.
    """
    # Half-up, as every other money figure in the app is rounded: the default
    # context rounds half-even, so 0.005 printed as 0.00 here and as 0.01 on
    # the screen the report was bought from. And a non-finite value (a "NaN"
    # in the stored report) is unreadable like any other, not a crash: the
    # sign test below raises on NaN, which took the whole download down.
    try:
        parsed = Decimal(str(value))
        amount = (
            parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if parsed.is_finite()
            else Decimal("0.00")
        )
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


def _cell(text: object, width: float) -> str | Paragraph:
    """A plain string when *text* fits *width* on one line, else a wrapping Paragraph.

    Line-breaking a Paragraph is most of what a large report costs to build —
    every cell measured word by word, twice (once to size the row, once to
    draw it) — and most cells here are a GSTIN, a date or an amount that never
    wraps. A plain string is measured once and drawn as-is, and needs no
    escaping because a Table does not parse it as markup.
    """
    value = "-" if text is None or text == "" else str(text)
    # A row cannot be split across pages, so a cell that wraps taller than one
    # — a supplier name thousands of characters long, off an uploaded invoice
    # or the portal — stopped the whole report with a LayoutError, a 500 on a
    # download the business had paid for. At most _MAX_CELL_LINES lines of the
    # widest glyphs (about one em each) fit the column; anything past that is
    # cut, and the ellipsis says so.
    limit = _MAX_CELL_LINES * max(1, int((width - _PADDING) // _CELL.fontSize))
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    if "\n" not in value and stringWidth(value, _CELL.fontName, _CELL.fontSize) <= width - _PADDING:
        return value
    return _p(value)


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


# Rows per table. One table holding every finding is split again at each page
# break, and each split re-measures everything left below it, so a large run
# cost more than linearly; tables of this size keep each split small. Each one
# carries the header row, so a reader meets it at least every few pages.
_ROWS_PER_TABLE = 250


def _findings_tables(findings: list[dict]) -> list[Table]:
    return [
        _findings_table(findings[start : start + _ROWS_PER_TABLE])
        for start in range(0, len(findings), _ROWS_PER_TABLE)
    ]


def _findings_table(findings: list[dict]) -> Table:
    header = ["Invoice no.", "Supplier", "Supplier GSTIN", "Date", "Tax (books)",
              "Tax (2B)", "Notes"]
    widths = [x * mm for x in (32, 52, 36, 22, 28, 28, 70)]
    rows = [[_p(h, _HEAD) for h in header]]
    for finding in findings:
        values = (
            finding.get("invoice_number"),
            finding.get("supplier_name"),
            finding.get("supplier_gstin"),
            finding.get("invoice_date"),
            _tax(finding.get("books")),
            _tax(finding.get("gstr2b")),
            _note(finding),
        )
        rows.append([_cell(value, width) for value, width in zip(values, widths, strict=True)])
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
        # Counted as the summary counts: a finding carried from an earlier
        # period is listed (the supplier caught up on it) but is that period's,
        # and not in this run's figures. Counting it in the heading had the
        # report say "Mismatched 0" in the summary and "Mismatched (1)" below.
        carried = sum(1 for f in rows if f.get("carried"))
        count = f"{len(rows) - carried}" + (
            f", plus {carried} from an earlier period" if carried else ""
        )
        story += [
            Spacer(1, 6 * mm),
            _p(f"{heading} ({count})", _STYLES["Heading2"]),
            _p(explanation),
            Spacer(1, 2 * mm),
        ]
        story.extend(_findings_tables(rows) if rows else [_p("None.")])

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
