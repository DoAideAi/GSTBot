"""Getting text off an upload: the layer under the parser.

This is the first thing that touches a customer's file, and everything
downstream is shaped by what it returns. Two of its contracts matter more than
the rest and most of this file is about them:

*   It never raises. A corrupt PDF, a truncated spreadsheet, a JPEG renamed to
    .xlsx — every one of those is something a user will upload, and the answer
    to all of them is ``""`` and a warning in the log, not a 500. The parser
    turns ``""`` into an invoice the user can correct by hand.

*   ``""`` means "needs the vision path". A scanned invoice is a PDF whose
    embedded text is a page number and nothing else, and returning that as if
    it were the invoice is worse than returning nothing: the parser would
    accept it and never OCR the page.
"""
from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest
from openpyxl import Workbook

from app.services import document_text

# --------------------------------------------------------------------------
# Fixtures: real files, built in memory
# --------------------------------------------------------------------------

def make_pdf(*pages: str) -> bytes:
    """A minimal but genuinely valid PDF carrying *pages* of text.

    Built by hand rather than with a PDF library so the test depends only on
    the reader under test. pypdf really does parse this and really does pull
    the text back out.
    """
    objects: list[bytes] = []
    page_count = len(pages)
    # 1 catalog, 2 pages tree, then per page: page object + content stream.
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(page_count))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode()
    )
    font_obj = 3 + page_count * 2
    for i, text in enumerate(pages):
        content_obj = 4 + i * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_obj} 0 R "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>".encode()
        )
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def make_xlsx(rows: list[list], *, sheets: dict[str, list[list]] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Purchases"
    for row in rows:
        sheet.append(row)
    for name, extra_rows in (sheets or {}).items():
        other = workbook.create_sheet(name)
        for row in extra_rows:
            other.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


INVOICE_LINE = "TAX INVOICE INV-2026-001 GSTIN 29AAGCB7383J1Z4 Grand Total 531000.00"


# --------------------------------------------------------------------------
# is_image
# --------------------------------------------------------------------------

class TestIsImage:
    @pytest.mark.parametrize(
        "content_type",
        ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic"],
    )
    def test_recognised_image_content_types(self, content_type):
        assert document_text.is_image(content_type) is True

    def test_content_type_is_matched_case_insensitively(self):
        # Browsers and curl both send these in whatever case they please.
        assert document_text.is_image("IMAGE/JPEG") is True

    @pytest.mark.parametrize(
        "filename",
        ["scan.jpg", "scan.JPEG", "photo.png", "shot.webp", "IMG_0042.HEIC"],
    )
    def test_falls_back_to_the_extension(self, filename):
        # A phone upload often arrives as application/octet-stream.
        assert document_text.is_image("application/octet-stream", filename) is True

    @pytest.mark.parametrize("filename", ["books.pdf", "register.xlsx", "notes.txt", "data.csv"])
    def test_documents_are_not_images(self, filename):
        assert document_text.is_image(None, filename) is False

    def test_nothing_to_go_on_is_not_an_image(self):
        assert document_text.is_image(None, None) is False

    def test_a_bare_name_with_no_extension_is_not_an_image(self):
        assert document_text.is_image(None, "scan") is False

    def test_the_content_type_wins_over_a_misleading_name(self):
        assert document_text.is_image("image/png", "invoice.pdf") is True


# --------------------------------------------------------------------------
# from_pdf
# --------------------------------------------------------------------------

class TestFromPdf:
    def test_reads_embedded_text(self):
        assert "INV-2026-001" in document_text.from_pdf(make_pdf(INVOICE_LINE))

    def test_joins_every_page(self):
        text = document_text.from_pdf(
            make_pdf(INVOICE_LINE, "Page two continues the line items here")
        )
        assert "INV-2026-001" in text
        assert "Page two" in text

    def test_a_scan_reads_as_empty(self):
        # The whole point of the threshold: a scanned invoice's only embedded
        # text is page furniture. Returning "Page 1 of 2" as the invoice would
        # stop the caller ever sending this to OCR.
        assert document_text.from_pdf(make_pdf("Page 1 of 2")) == ""

    def test_the_threshold_is_on_the_whole_document_not_one_page(self):
        # Two pages, each on its own below the threshold, together above it.
        # A per-page test would throw this invoice away.
        pages = ("INV-2026-001 Northwind", "GSTIN 29AAGCB7383J1Z4")
        assert all(len(page) < document_text._MIN_PDF_TEXT_CHARS for page in pages)
        text = document_text.from_pdf(make_pdf(*pages))
        assert "INV-2026-001" in text and "29AAGCB7383J1Z4" in text

    def test_text_at_exactly_the_threshold_is_kept(self):
        payload = "A" * document_text._MIN_PDF_TEXT_CHARS
        assert document_text.from_pdf(make_pdf(payload)) == payload

    def test_text_one_character_short_is_dropped(self):
        payload = "A" * (document_text._MIN_PDF_TEXT_CHARS - 1)
        assert document_text.from_pdf(make_pdf(payload)) == ""

    def test_a_corrupt_pdf_returns_empty_rather_than_raising(self):
        assert document_text.from_pdf(b"%PDF-1.4\nthis is not a pdf") == ""

    def test_a_truncated_pdf_returns_empty(self):
        assert document_text.from_pdf(make_pdf(INVOICE_LINE)[:120]) == ""

    def test_empty_bytes_return_empty(self):
        assert document_text.from_pdf(b"") == ""

    def test_a_jpeg_renamed_to_pdf_returns_empty(self):
        assert document_text.from_pdf(b"\xff\xd8\xff\xe0garbage") == ""

    def test_a_failure_is_logged_for_the_operator(self, caplog):
        with caplog.at_level("WARNING"):
            document_text.from_pdf(b"not a pdf at all")
        assert "PDF text extraction failed" in caplog.text


# --------------------------------------------------------------------------
# from_excel
# --------------------------------------------------------------------------

class TestFromExcel:
    def test_flattens_rows_to_tabs(self):
        text = document_text.from_excel(
            make_xlsx([["Invoice", "GSTIN", "Total"], ["INV-1", "29AAGCB7383J1Z4", 531000]])
        )
        assert text.splitlines()[0] == "Invoice\tGSTIN\tTotal"
        assert "INV-1\t29AAGCB7383J1Z4\t531000" in text

    def test_blank_rows_are_dropped(self):
        # openpyxl pads every row out to the widest one, so the surviving rows
        # carry trailing tabs. What matters is that the two empty rows are
        # gone and the two real ones are not.
        text = document_text.from_excel(
            make_xlsx([["Invoice"], [None, None], ["", "  "], ["INV-2"]])
        )
        assert [line.strip() for line in text.splitlines()] == ["Invoice", "INV-2"]

    def test_none_cells_become_empty_not_the_string_none(self):
        text = document_text.from_excel(make_xlsx([["INV-3", None, "531000"]]))
        assert "None" not in text
        assert text == "INV-3\t\t531000"

    def test_every_sheet_is_read(self):
        # A purchase register routinely puts each month on its own tab.
        text = document_text.from_excel(
            make_xlsx([["April", "INV-1"]], sheets={"May": [["May", "INV-2"]]})
        )
        assert "INV-1" in text and "INV-2" in text

    def test_an_empty_workbook_returns_empty(self):
        assert document_text.from_excel(make_xlsx([])) == ""

    def test_a_corrupt_workbook_returns_empty_rather_than_raising(self):
        assert document_text.from_excel(b"PK\x03\x04 not really a workbook") == ""

    def test_a_csv_renamed_to_xlsx_returns_empty(self):
        assert document_text.from_excel(b"Invoice,GSTIN\nINV-1,29AAGCB7383J1Z4\n") == ""

    def test_a_failure_is_logged_for_the_operator(self, caplog):
        with caplog.at_level("WARNING"):
            document_text.from_excel(b"nonsense")
        assert "Spreadsheet read failed" in caplog.text


def _corrupt_sheet_xlsx() -> bytes:
    """A workbook that opens, then fails while its sheet is walked.

    ``read_only`` parses sheets lazily, so the damage — a shared-string index
    past the end of the table — is only reached inside ``iter_rows``.
    """
    import zipfile

    source = zipfile.ZipFile(io.BytesIO(make_xlsx([["Invoice"]])))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(
                    b"</sheetData>",
                    b"<row r='2'><c r='A2' t='s'><v>999</v></c></row></sheetData>",
                )
            target.writestr(info, data)
    return out.getvalue()


def _full_grid_xlsx() -> bytes:
    """Five kilobytes on disk that declare a 1,048,576 x 16,384 sheet."""
    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "Invoice"
    sheet.cell(row=1_048_576, column=16_384, value="x")
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class TestASpreadsheetCannotOutlastItsRead:
    """Two ways a sheet escaped the bounds the read already had (M6)."""

    def test_a_sheet_that_fails_partway_returns_empty_rather_than_raising(self):
        assert document_text.from_excel(_corrupt_sheet_xlsx()) == ""

    def test_a_partway_failure_is_logged_for_the_operator(self, caplog):
        with caplog.at_level("WARNING"):
            document_text.from_excel(_corrupt_sheet_xlsx())
        assert "Spreadsheet read failed partway" in caplog.text

    def test_a_declared_full_grid_is_not_walked_cell_by_cell(self):
        import time

        content = _full_grid_xlsx()
        assert len(content) < 10_000
        started = time.monotonic()
        text = document_text.from_excel(content)
        # Unbounded, this is minutes; bounded, a fraction of a second. The
        # margin is for a slow CI box, not for the bound.
        assert time.monotonic() - started < 5
        assert text.startswith("Invoice")

    def test_blank_cells_count_against_the_budget(self, monkeypatch, caplog):
        monkeypatch.setattr(document_text, "MAX_CELLS", 10)
        rows = [["Invoice", None, None]] + [[None, None, None]] * 10 + [["INV-9", None, None]]
        with caplog.at_level("WARNING"):
            text = document_text.from_excel(make_xlsx(rows))
        assert "INV-9" not in text
        assert "stopped after 10 cells" in caplog.text

    def test_a_real_register_is_inside_the_budget(self):
        assert document_text.MAX_CELLS >= 10_000 * 50


# --------------------------------------------------------------------------
# from_csv
# --------------------------------------------------------------------------

class TestFromCsv:
    def test_converts_commas_to_tabs(self):
        text = document_text.from_csv(b"Invoice,GSTIN\nINV-1,29AAGCB7383J1Z4\n")
        assert text == "Invoice\tGSTIN\nINV-1\t29AAGCB7383J1Z4"

    def test_a_utf8_bom_is_stripped(self):
        # Excel's "Save as CSV" writes a BOM, so this is the common case, not
        # the exotic one. Left in, it corrupts the first column heading.
        text = document_text.from_csv("﻿Invoice,Total\nINV-1,531000\n".encode())
        assert text.startswith("Invoice\t")

    def test_a_quoted_comma_stays_inside_its_field(self):
        text = document_text.from_csv(b'Name,Total\n"Northwind Supplies, Pvt Ltd",531000\n')
        assert "Northwind Supplies, Pvt Ltd\t531000" in text

    def test_latin1_bytes_do_not_raise(self):
        # A register exported from an old Tally install is not always UTF-8.
        text = document_text.from_csv(b"Name,Total\nCaf\xe9 Supplies,1000\n")
        assert "Supplies" in text and "1000" in text

    def test_blank_rows_are_dropped(self):
        text = document_text.from_csv(b"Invoice\n\n,,\nINV-2\n")
        assert text.splitlines() == ["Invoice", "INV-2"]

    def test_empty_input_returns_empty(self):
        assert document_text.from_csv(b"") == ""

    def test_embedded_newlines_in_a_quoted_field_are_handled(self):
        text = document_text.from_csv(b'Name,Total\n"Northwind\nSupplies",531000\n')
        assert "531000" in text


# --------------------------------------------------------------------------
# ocr_image
# --------------------------------------------------------------------------

class _FakeImage:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_ocr(monkeypatch, *, returns=None, raises=None):
    """Put a scriptable pytesseract/PIL pair in sys.modules.

    ``ocr_image`` imports them inside the function precisely so a deployment
    without Tesseract still starts, which is what makes this patchable at all.
    """
    def image_to_string(image):
        if raises is not None:
            raise raises
        return returns

    monkeypatch.setitem(
        sys.modules, "pytesseract", SimpleNamespace(image_to_string=image_to_string)
    )
    monkeypatch.setitem(
        sys.modules,
        "PIL",
        SimpleNamespace(Image=SimpleNamespace(open=lambda buffer: _FakeImage())),
    )


class TestOcrImage:
    def test_returns_what_tesseract_read(self, monkeypatch):
        _install_fake_ocr(monkeypatch, returns="  TAX INVOICE INV-2026-001  \n")
        assert document_text.ocr_image(b"\x89PNG fake") == "TAX INVOICE INV-2026-001"

    def test_a_blank_scan_returns_empty(self, monkeypatch):
        _install_fake_ocr(monkeypatch, returns="   \n\n  ")
        assert document_text.ocr_image(b"\x89PNG fake") == ""

    def test_a_missing_tesseract_binary_returns_empty(self, monkeypatch):
        # pytesseract raises at call time when the binary is absent. A
        # deployment without it must still ingest invoices.
        _install_fake_ocr(monkeypatch, raises=RuntimeError("tesseract is not installed"))
        assert document_text.ocr_image(b"\x89PNG fake") == ""

    def test_an_unreadable_image_returns_empty(self, monkeypatch):
        _install_fake_ocr(monkeypatch, raises=OSError("cannot identify image file"))
        assert document_text.ocr_image(b"not an image") == ""

    def test_a_failure_is_logged_for_the_operator(self, monkeypatch, caplog):
        _install_fake_ocr(monkeypatch, raises=RuntimeError("tesseract exploded"))
        with caplog.at_level("WARNING"):
            document_text.ocr_image(b"\x89PNG fake")
        assert "OCR failed" in caplog.text

    def test_an_uninstalled_binding_returns_empty(self, monkeypatch):
        # The other half of optional: the Python package itself is absent.
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
            else __builtins__.__import__

        def refuse(name, *args, **kwargs):
            if name in {"pytesseract", "PIL"}:
                raise ImportError(f"No module named {name!r}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", refuse)
        assert document_text.ocr_image(b"\x89PNG fake") == ""

    def test_the_result_is_always_a_string(self, monkeypatch):
        # pytesseract can hand back a non-str; the caller does regex on this.
        _install_fake_ocr(monkeypatch, returns=12345)
        assert document_text.ocr_image(b"\x89PNG fake") == "12345"


# --------------------------------------------------------------------------
# extract — the dispatcher
# --------------------------------------------------------------------------

class TestExtractDispatch:
    def test_pdf_by_content_type(self):
        assert "INV-2026-001" in document_text.extract(
            make_pdf(INVOICE_LINE), "application/pdf", "books.pdf"
        )

    def test_pdf_by_extension_when_the_type_is_generic(self):
        assert "INV-2026-001" in document_text.extract(
            make_pdf(INVOICE_LINE), "application/octet-stream", "books.pdf"
        )

    def test_excel_by_content_type(self):
        content = make_xlsx([["INV-1", 531000]])
        assert "INV-1" in document_text.extract(
            content,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "register.xlsx",
        )

    @pytest.mark.parametrize("filename", ["register.xlsx", "register.xlsm", "register.xls"])
    def test_excel_by_extension(self, filename):
        content = make_xlsx([["INV-1", 531000]])
        assert "INV-1" in document_text.extract(content, None, filename)

    def test_csv_by_content_type(self):
        assert document_text.extract(b"a,b\n1,2\n", "text/csv", None) == "a\tb\n1\t2"

    def test_csv_by_extension(self):
        assert document_text.extract(b"a,b\n1,2\n", None, "register.csv") == "a\tb\n1\t2"

    def test_plain_text_is_returned_as_is(self):
        text = document_text.extract(INVOICE_LINE.encode(), "text/plain", "bill.txt")
        assert text == INVOICE_LINE

    def test_plain_text_by_extension(self):
        assert document_text.extract(b"  hello  ", None, "notes.txt") == "hello"

    def test_undecodable_text_is_replaced_not_raised(self):
        assert document_text.extract(b"total \xff\xfe 100", "text/plain", None) != ""

    def test_content_type_case_does_not_matter(self):
        assert "INV-2026-001" in document_text.extract(
            make_pdf(INVOICE_LINE), "APPLICATION/PDF", None
        )

    def test_an_image_returns_empty_so_the_caller_uses_vision(self):
        # extract() deliberately does not OCR: that decision belongs to the
        # parser, which may have a vision model available and prefer it.
        assert document_text.extract(b"\x89PNG fake", "image/png", "scan.png") == ""

    def test_an_unknown_type_returns_empty(self):
        assert document_text.extract(b"\x00\x01\x02", "application/zip", "books.zip") == ""

    def test_nothing_known_about_the_upload_returns_empty(self):
        assert document_text.extract(b"some bytes", None, None) == ""

    def test_a_scanned_pdf_returns_empty_so_the_caller_uses_vision(self):
        assert document_text.extract(make_pdf("Page 1"), "application/pdf", "scan.pdf") == ""

    def test_the_content_type_is_preferred_over_the_extension(self):
        # A CSV uploaded as invoice.pdf: the declared type is checked first,
        # so this goes down the PDF path and yields nothing rather than
        # silently succeeding as a CSV.
        assert document_text.extract(b"a,b\n1,2\n", "application/pdf", "invoice.csv") == ""

    def test_a_corrupt_file_of_every_type_returns_empty(self):
        junk = b"\x00\xff\x00\xff not a document"
        for content_type in ("application/pdf", "application/vnd.ms-excel", "application/zip"):
            assert document_text.extract(junk, content_type, None) == ""

    def test_empty_upload_of_every_type_returns_empty(self):
        for content_type in ("application/pdf", "text/csv", "text/plain", None):
            assert document_text.extract(b"", content_type, None) == ""


# --------------------------------------------------------------------------
# The ceiling on how much text an upload may become
# --------------------------------------------------------------------------

class TestTheTextCeiling:
    """``MAX_UPLOAD_MB`` bounds the bytes on the wire and bounds nothing here.

    A spreadsheet is a zip of shared strings: one cell value repeated across a
    sheet costs almost nothing on disk and a full copy per cell once read, so a
    file comfortably inside the upload limit flattens to hundreds of megabytes
    of text. That string is not passed through and dropped — the heuristic
    parser regex-scans it field by field and it is then written whole into
    ``invoices.raw_text`` — so one upload is a worker's memory, a long
    CPU-bound stretch of it, and a row the database carries from then on. With
    Celery off the upload runs inline, which makes it one request holding all
    three.

    The cap is asserted with the constant patched down rather than by building
    a two-million-character file, because the assertion is about the ceiling
    being applied, and a test that spends the cost the cap exists to avoid is
    the wrong shape.
    """

    LIMIT = 400

    @pytest.fixture(autouse=True)
    def _small_limit(self, monkeypatch):
        monkeypatch.setattr(document_text, "MAX_TEXT_CHARS", self.LIMIT)

    def test_a_spreadsheet_is_cut_off_at_the_ceiling(self):
        content = make_xlsx([[f"INV-{i}", "9" * 200] for i in range(200)])
        text = document_text.from_excel(content)
        assert len(text) <= self.LIMIT

    def test_the_rows_before_the_ceiling_are_still_read(self):
        # Truncated, not discarded: whatever fitted is still an invoice the
        # parser can read and a reviewer can correct.
        content = make_xlsx([["INV-FIRST", "1000"], *[[f"INV-{i}", "9" * 200] for i in range(200)]])
        assert document_text.from_excel(content).startswith("INV-FIRST")

    def test_the_internal_break_never_reaches_the_caller(self):
        # The sheet/row walk is broken out of with an exception. If it escaped
        # from_excel it would be a 500 on an upload, which is the one thing
        # this module promises never to do.
        content = make_xlsx(
            [["9" * 200] for _ in range(200)],
            sheets={"May": [["9" * 200] for _ in range(200)]},
        )
        assert isinstance(document_text.extract(content, None, "register.xlsx"), str)

    def test_a_spreadsheet_under_the_ceiling_is_untouched(self):
        text = document_text.from_excel(make_xlsx([["INV-1", "531000"], ["INV-2", "1180"]]))
        assert text == "INV-1\t531000\nINV-2\t1180"

    def test_a_pdf_is_cut_off_at_the_ceiling(self):
        pages = ["INV-2026-001 " + "9" * 300 for _ in range(20)]
        assert len(document_text.from_pdf(make_pdf(*pages))) <= self.LIMIT

    def test_a_pdf_under_the_ceiling_keeps_every_page(self):
        text = document_text.from_pdf(make_pdf(INVOICE_LINE, "Page two line items here"))
        assert "INV-2026-001" in text and "Page two" in text

    def test_a_csv_is_cut_off_at_the_ceiling(self):
        content = b"".join(f"INV-{i},{'9' * 200}\n".encode() for i in range(200))
        assert len(document_text.from_csv(content)) <= self.LIMIT

    def test_plain_text_is_cut_off_at_the_ceiling(self):
        content = ("TAX INVOICE " + "9" * 200).encode() * 50
        assert len(document_text.extract(content, "text/plain", "bill.txt")) <= self.LIMIT

    def test_a_truncated_pdf_still_has_to_clear_the_scan_threshold(self):
        # The two limits are independent and both still apply: a document cut
        # short must still carry enough text to be a document rather than a
        # scan's page furniture.
        assert document_text.from_pdf(make_pdf("Page 1 of 9")) == ""


def test_the_real_text_ceiling_is_far_past_any_real_register():
    # Outside the class above, so the patched-down limit cannot be what this
    # reads. A ceiling lowered to something a genuine purchase register would
    # hit belongs in a failure here, not in a truncated invoice — the
    # extraction prompt itself only ever sends the first 12,000 characters.
    assert document_text.MAX_TEXT_CHARS >= 1_000_000
