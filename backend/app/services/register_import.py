"""Invoice-level purchase registers: deterministic preview before atomic import."""

import csv
import io
import re
import zipfile
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import ParseError

from fastapi import HTTPException
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import func, select

from app.core.sanitize import clean_text
from app.models.invoice import Invoice, InvoiceSource, InvoiceStatus, InvoiceType
from app.models.mixins import MONEY_MAX
from app.services import gst_calendar, gstin, invoice_service

MAX_ROWS = 2000
MAX_BYTES = 5 * 1024 * 1024
FIELDS = {
    "invoice_number": ["invoice number", "invoice no", "invoice no.", "voucher no", "bill no"],
    "invoice_date": ["invoice date", "date", "bill date", "voucher date"],
    "supplier_gstin": ["supplier gstin", "gstin", "gstin of supplier", "party gstin"],
    "supplier_name": ["supplier name", "party name", "supplier", "particulars"],
    "taxable_value": ["taxable value", "taxable amount", "assessable value"],
    "cgst": ["cgst", "cgst amount", "central tax"],
    "sgst": ["sgst", "sgst amount", "state tax"],
    "igst": ["igst", "igst amount", "integrated tax"],
    "cess": ["cess", "cess amount"],
    "total_value": ["total value", "invoice value", "invoice amount", "total amount"],
    "place_of_supply": ["place of supply", "pos", "state code"],
    "itc_eligible": ["itc eligible", "eligible for itc"],
    "reverse_charge": ["reverse charge", "rcm"],
}
REQUIRED = {"invoice_number", "invoice_date", "supplier_gstin", "taxable_value"}
MONEY = ("taxable_value", "cgst", "sgst", "igst", "cess", "total_value")


def fail(message):
    raise HTTPException(422, message)


def read_file(content, filename):
    if not content or len(content) > MAX_BYTES:
        fail("Choose a non-empty CSV or XLSX file no larger than 5 MB.")
    try:
        if filename.lower().endswith(".csv"):
            raw = content.decode("utf-8-sig")
            try:
                dialect = csv.Sniffer().sniff(raw[:8192], delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.reader(io.StringIO(raw), dialect=dialect)
            values = []
            for line, row in enumerate(reader):
                if line > MAX_ROWS:
                    fail("A register can contain at most 2,000 invoice rows. Split the file first.")
                if any(str(v).strip() for v in row):
                    values.append(row)
        elif filename.lower().endswith(".xlsx"):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if (
                    len(archive.infolist()) > 512
                    or sum(i.file_size for i in archive.infolist()) > 20 * 1024 * 1024
                ):
                    fail("This workbook expands beyond the supported size. Export a smaller CSV.")
            workbook = load_workbook(
                io.BytesIO(content), read_only=True, data_only=False, keep_links=False
            )
            try:
                if len(workbook.sheetnames) != 1:
                    fail(
                        "Use a workbook with one sheet, or export the "
                        "purchase-register sheet as CSV."
                    )
                sheet = workbook.active
                values = []
                for line, row in enumerate(sheet.iter_rows()):
                    if line > MAX_ROWS or len(row) > 60:
                        fail("Use at most 2,000 invoice rows and 60 columns per register.")
                    cells = []
                    for cell in row:
                        value = cell.value
                        if isinstance(value, (date, datetime)):
                            value = value.strftime("%Y-%m-%d")
                        if cell.data_type == "f":
                            value = "=FORMULA: export values only"
                        cells.append("" if value is None else str(value))
                    if any(v.strip() for v in cells):
                        values.append(cells)
            finally:
                workbook.close()
        else:
            fail(
                "Use CSV or XLSX. Export legacy XLS and Tally registers to invoice-level CSV first."
            )
    except (
        UnicodeError, csv.Error, zipfile.BadZipFile, ValueError, OSError, KeyError,
        ParseError, InvalidFileException, RuntimeError,
    ):
        fail(
            "The register could not be read. Export it again as UTF-8 CSV or XLSX with values only."
        )
    if len(values) < 2:
        fail("Include a header row followed by at least one invoice row.")
    headers = [clean_text(str(v), max_length=100) or "" for v in values[0]]
    if len(headers) > 60 or any(not h for h in headers) or len(set(headers)) != len(headers):
        fail("Use at most 60 unique, non-empty column headings.")
    if any(len(row) != len(headers) for row in values[1:]):
        fail("Every row must contain the same number of columns as the header.")
    if any(len(str(v)) > 1000 for row in values for v in row):
        fail("A cell exceeds 1,000 characters. Remove notes or unrelated columns and try again.")
    return headers, values[1:]


def suggest(headers):
    normalized = {re.sub(r"[_\s]+", " ", h.lower()).strip(): h for h in headers}
    return {
        field: next(
            (normalized[a] for a in [field.replace("_", " "), *aliases] if a in normalized), ""
        )
        for field, aliases in FIELDS.items()
    }


def amount(value):
    raw = str(value).strip().replace("₹", "").replace(",", "").strip()
    if not raw:
        return Decimal("0.00")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw):
        raise ValueError(
            "Use a non-negative amount with at most two decimal places; "
            "formulas and credit notes are not accepted."
        )
    try:
        number = Decimal(raw)
        if not number.is_finite() or number > MONEY_MAX:
            raise ValueError("Amount is outside the supported range.")
        return number.quantize(Decimal(".01"))
    except InvalidOperation as exc:
        raise ValueError("Amount is outside the supported range.") from exc


def boolean(value, default):
    text = str(value).strip().lower()
    if not text:
        return default
    if text in ("yes", "y", "true", "1"):
        return True
    if text in ("no", "n", "false", "0"):
        return False
    raise ValueError("Use yes or no.")


def preview_rows(db, business, headers, values, mapping, date_format):
    if set(mapping) - set(FIELDS) or any(v and v not in headers for v in mapping.values()):
        fail("Choose mapping columns from this file only.")
    selected = [v for v in mapping.values() if v]
    if len(selected) != len(set(selected)):
        fail("Map each source column to only one field.")
    output = []
    missing = sorted(field for field in REQUIRED if not mapping.get(field))

    def incoming(field):
        column = mapping.get(field)
        return (
            {str(row[headers.index(column)]).strip().upper() for row in values} if column else set()
        )

    existing = set(
        db.execute(
            select(Invoice.counterparty_gstin, func.upper(Invoice.invoice_number)).where(
                Invoice.business_id == business.id,
                Invoice.deleted_at.is_(None),
                Invoice.invoice_type == InvoiceType.PURCHASE,
                Invoice.counterparty_gstin.in_(incoming("supplier_gstin")),
                func.upper(Invoice.invoice_number).in_(incoming("invoice_number")),
            )
        ).all()
    )
    for number, source in enumerate(values, start=2):
        cells = dict(zip(headers, source, strict=True))
        data = {key: str(cells.get(mapping.get(key), "")).strip() for key in FIELDS}
        errors = [f'Map {field.replace("_", " ")}.' for field in missing]
        result = {}
        for field in ("invoice_number", "supplier_name"):
            limit = 64 if field == "invoice_number" else 255
            value = data[field]
            if value.startswith(("=", "+", "@")) or len(value) > limit:
                errors.append(f"{field}: use plain text up to {limit} characters.")
            result[field] = clean_text(value, max_length=limit) or ""
        if not result["invoice_number"]:
            errors.append("Invoice number is required.")
        try:
            result["supplier_gstin"] = gstin.parse(data["supplier_gstin"]).gstin
            if result["supplier_gstin"] == business.gstin:
                errors.append("Supplier GSTIN is the selected business GSTIN; check the mapping.")
        except gstin.InvalidGSTIN:
            errors.append("Supplier GSTIN is missing or invalid.")
        try:
            fmt = (
                "%Y-%m-%d"
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["invoice_date"])
                else {"DMY": "%d/%m/%Y", "MDY": "%m/%d/%Y", "YMD": "%Y/%m/%d"}[date_format]
            )
            stamp = datetime.strptime(
                (
                    data["invoice_date"]
                    if fmt == "%Y-%m-%d"
                    else data["invoice_date"].replace(".", "/").replace("-", "/")
                ),
                fmt,
            ).date()
            if stamp.year < 2017 or stamp > gst_calendar.today_ist():
                raise ValueError()
            result["invoice_date"] = stamp.isoformat()
        except ValueError:
            errors.append(
                "Invoice date is invalid or in the future. Use the "
                "selected date order, or YYYY-MM-DD."
            )
        for field in MONEY:
            try:
                result[field] = str(amount(data[field]))
            except ValueError as exc:
                errors.append(f"{field}: {exc}")
        if not data["taxable_value"]:
            errors.append("Taxable value is required.")
        if all(field in result for field in MONEY):
            total = sum((Decimal(result[f]) for f in MONEY[:-1]), Decimal("0"))
            if not data["total_value"]:
                if total > MONEY_MAX:
                    errors.append("Calculated invoice total exceeds the supported range.")
                else:
                    result["total_value"] = str(total)
            elif abs(Decimal(result["total_value"]) - total) > Decimal("1.00"):
                errors.append(
                    "Invoice total differs from taxable value plus tax by"
                    " more than ₹1. Correct the row."
                )
            if Decimal(result["igst"]) and (Decimal(result["cgst"]) or Decimal(result["sgst"])):
                errors.append("IGST and CGST/SGST cannot both be populated for this invoice.")
            if Decimal(result["cgst"]) != Decimal(result["sgst"]):
                errors.append("CGST and SGST differ. Correct or review this row before importing.")
        pos = data["place_of_supply"] or business.state_code or ""
        if pos and pos not in gstin.STATE_CODES:
            errors.append("Place of supply must be a two-digit state code.")
        result["place_of_supply"] = pos or None
        for field, default in [("itc_eligible", False), ("reverse_charge", False)]:
            try:
                result[field] = boolean(data[field], default)
            except ValueError as exc:
                errors.append(f"{field}: {exc}")
        key = (result.get("supplier_gstin"), result.get("invoice_number", "").upper())
        output.append(
            {"row": number, "data": result, "errors": errors, "duplicate": key in existing}
        )
    counts = Counter(
        (r["data"].get("supplier_gstin"), r["data"]["invoice_number"].upper()) for r in output
    )
    for row in output:
        key = (row["data"].get("supplier_gstin"), row["data"]["invoice_number"].upper())
        if counts[key] > 1:
            row["errors"].append(
                "This invoice appears on multiple rows. Combine line "
                "items into one invoice-level row, or remove duplicate "
                "rows."
            )
    return output


def commit_rows(db, business, batch, skip_invalid):
    invoice_service._serialise_uploads(db, business.id)
    rows = batch.rows
    if any(r["errors"] for r in rows) and not skip_invalid:
        fail(
            "Some rows have errors. Correct the file or explicitly choose"
            " to import valid rows only."
        )
    ready, duplicates = [], 0
    for row in rows:
        if row["errors"]:
            continue
        data = row["data"]
        if invoice_service.find_duplicate(
            db,
            business.id,
            invoice_type=InvoiceType.PURCHASE,
            counterparty_gstin=data["supplier_gstin"],
            invoice_number=data["invoice_number"],
        ):
            duplicates += 1
        else:
            ready.append(row)
    tenant = invoice_service.TenantSnapshot.of(business)
    used = invoice_service.monthly_usage(
        db, business.id, include_deleted=tenant.plan.startswith("pilot_")
    )
    if tenant.monthly_limit and used + len(ready) > tenant.monthly_limit:
        raise HTTPException(
            402,
            f"This import needs {len(ready)} invoice places; "
            f"{max(0, tenant.monthly_limit - used)} remain this calendar month. "
            "No rows were imported.",
        )
    ids = []
    for row in ready:
        data = dict(row["data"])
        supplier = invoice_service.get_or_create_supplier(
            db, business.id, data.pop("supplier_gstin"), data.pop("supplier_name")
        )
        stamp = date.fromisoformat(data.pop("invoice_date"))
        invoice = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            status=InvoiceStatus.PARSED,
            source=InvoiceSource.UPLOAD,
            supplier_id=supplier.id,
            counterparty_gstin=supplier.gstin,
            counterparty_name=supplier.legal_name,
            invoice_date=stamp,
            period=stamp.strftime("%Y-%m"),
            source_filename=batch.filename,
            parsed_with="purchase_register",
            extraction_confidence=None,
            extraction={
                "method": "register_import",
                "import_id": batch.id,
                "source_row": row["row"],
                "original": row["data"],
            },
            **data,
        )
        db.add(invoice)
        db.flush()
        ids.append(invoice.id)
    return {
        "imported": len(ids),
        "invoice_ids": ids,
        "duplicates_skipped": duplicates,
        "invalid_skipped": sum(bool(r["errors"]) for r in rows),
    }


def aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value
