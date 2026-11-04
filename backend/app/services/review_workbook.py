"""A portable, formula-free Excel record of an approved reconciliation."""
import io
import re
from collections import Counter
from datetime import UTC
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services.supplier_followup import differences, money

_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")


def stamp(value):
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def sheet(book, name, headers, rows, currency=()):
    ws = book.create_sheet(name)
    ws.freeze_panes = "A2"
    for index, header in enumerate(headers, 1):
        ws.column_dimensions[get_column_letter(index)].width = (
            45 if "note" in header.lower() else 25
        )
    for row_number, row in enumerate(_with_header(headers, rows), 1):
        cells = []
        for index, value in enumerate(row):
            cell = WriteOnlyCell(ws, value=value)
            if isinstance(value, str):
                # Force text, including strings beginning with '=': an invoice
                # identifier or review note must never become an Excel formula.
                cell.value = _CONTROLS.sub("", value)
                cell.data_type = "s"
            if row_number == 1:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor="0F766E")
            elif index in currency and value is not None:
                cell.number_format = '#,##0.00;[Red]-#,##0.00'
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cells.append(cell)
        ws.append(cells)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{row_number}"


def _with_header(headers, rows):
    yield headers
    yield from rows


def build(run, business, reviews, approval, events):
    book = Workbook(write_only=True)
    book.properties.title = f"Reviewed reconciliation — {run.period} — run {run.id}"
    book.properties.creator = "DoAide GST"
    findings = (run.report or {}).get("findings", [])
    by_index = {r.finding_index: r for r in reviews}
    categories = Counter(f.get("category", "unknown") for f in findings)
    sheet(book, "Summary", ["Field", "Value"], [
        ["Business", business.trade_name or business.legal_name], ["GSTIN", business.gstin],
        ["Period", run.period], ["Run", run.id], ["Status", "Reviewed reconciliation"],
        ["Completed (UTC)", stamp(run.completed_at)],
        ["Reviewed (UTC)", stamp(approval.reviewed_at)], ["Reviewer user ID", approval.reviewed_by],
        ["Scope", "Recorded finding and review snapshot; not a GST return submission "
         "or confirmation of tax-credit eligibility."],
        ["Findings", len(findings)], *[[key.replace("_", " ").title(), value]
                                      for key, value in sorted(categories.items())],
    ])
    totals = {}
    for finding in findings:
        key = finding.get("supplier_gstin") or "Missing GSTIN"
        row = totals.setdefault(key, [key, finding.get("supplier_name") or "", 0, 0,
                                      Decimal("0.00"), Decimal("0.00"), Decimal("0.00")])
        books = money((finding.get("books") or {}).get("total_tax"))
        portal = money((finding.get("gstr2b") or {}).get("total_tax"))
        row[2] += 1
        row[3] += finding.get("category") != "matched"
        row[4] += books
        row[5] += portal
        row[6] += abs(books - portal)
    sheet(book, "Suppliers", ["GSTIN", "Supplier", "Findings", "Original exceptions",
          "Books tax in findings INR", "2B tax in findings INR", "Absolute tax difference INR"],
          (totals[key] for key in sorted(totals)), currency=(4, 5, 6))

    def finding_rows():
        for index, finding in enumerate(findings):
            review = by_index.get(index)
            books, portal = finding.get("books") or {}, finding.get("gstr2b") or {}
            yield [index, finding.get("supplier_gstin"), finding.get("supplier_name"),
                   finding.get("invoice_number"), finding.get("category"),
                   finding.get("invoice_date"), differences(finding),
                   money(books.get("total_tax")) if books else None,
                   money(portal.get("total_tax")) if portal else None,
                   finding.get("note") or "", review.status if review else "report_reviewed",
                   review.decision if review else "none", review.note if review else "",
                   review.updated_by if review else approval.reviewed_by,
                   stamp(review.updated_at if review else approval.reviewed_at)]
    sheet(book, "Findings", ["Finding index", "Supplier GSTIN", "Supplier", "Invoice",
          "Original match result", "Recorded invoice date", "Recorded differences", "Books tax INR",
          "2B tax INR", "Match explanation", "Review status", "Review decision", "Reviewer note",
          "Reviewer user ID", "Reviewed (UTC)"], finding_rows(), currency=(7, 8))
    by_id = {r.id: r for r in reviews}
    sheet(book, "Review history", ["Event", "Finding index", "Actor user ID", "At (UTC)",
          "Previous status", "New status", "Decision", "Note"], (
        [e.id, by_id[e.review_id].finding_index, e.actor_id, stamp(e.created_at),
         (e.previous or {}).get("status"), e.current.get("status"), e.current.get("decision"),
         e.current.get("note")] for e in events if e.review_id in by_id
    ))
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()
