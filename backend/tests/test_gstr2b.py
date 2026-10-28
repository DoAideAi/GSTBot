"""Reading GSTR-2B downloads: portal JSON, CSV exports, and the awkward ones."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from app.services import gstr2b
from tests.conftest import SUPPLIER_GSTIN_OTHER_STATE, SUPPLIER_GSTIN_SAME_STATE


def portal_json(**overrides) -> dict:
    """A GSTR-2B in the shape the portal actually hands out.

    Abbreviated keys, ``MMYYYY`` period, ``DD-MM-YYYY`` dates and rate-wise
    ``items`` under each invoice — copied from a real download's structure so
    the parser is tested against the format it will meet.
    """
    payload = {
        "chksum": "abc123",
        "data": {
            "gstin": "27AAPFU0939F1ZV",
            "rtnprd": "042026",
            "version": "1.0",
            "gendt": "14-05-2026",
            "docdata": {
                "b2b": [
                    {
                        "ctin": SUPPLIER_GSTIN_OTHER_STATE,
                        "trdnm": "Northwind Supplies",
                        "supfildt": "11-05-2026",
                        "supprd": "042026",
                        "inv": [
                            {
                                "inum": "INV-2026-0042",
                                "typ": "R",
                                "dt": "15-04-2026",
                                "val": 531000.00,
                                "pos": "27",
                                "rev": "N",
                                "itcavl": "Y",
                                "items": [
                                    {
                                        "num": 1,
                                        "rt": 18,
                                        "txval": 450000.00,
                                        "igst": 81000.00,
                                        "cgst": 0,
                                        "sgst": 0,
                                        "cess": 0,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        },
    }
    payload.update(overrides)
    return payload


def test_parses_the_portal_envelope():
    records = gstr2b.parse_json(portal_json())

    assert len(records) == 1
    record = records[0]
    assert record.supplier_gstin == SUPPLIER_GSTIN_OTHER_STATE
    assert record.supplier_name == "Northwind Supplies"
    assert record.invoice_number == "INV-2026-0042"
    assert record.invoice_date == date(2026, 4, 15)
    assert record.taxable_value == Decimal("450000.00")
    assert record.igst == Decimal("81000.00")
    assert record.total_tax == Decimal("81000.00")
    assert record.total_value == Decimal("531000.00")
    assert record.itc_available is True
    assert record.supplier_filing_date == date(2026, 5, 11)


def test_rate_wise_items_are_summed_into_one_invoice():
    """An invoice taxed at two rates is still one invoice to the buyer."""
    payload = portal_json()
    payload["data"]["docdata"]["b2b"][0]["inv"][0]["items"] = [
        {"num": 1, "rt": 18, "txval": 100000.00, "igst": 18000.00},
        {"num": 2, "rt": 5, "txval": 50000.00, "igst": 2500.00},
    ]
    (record,) = gstr2b.parse_json(payload)

    assert record.taxable_value == Decimal("150000.00")
    assert record.igst == Decimal("20500.00")
    assert len(record.rate_items) == 2


def test_period_comes_from_the_invoice_date_not_the_statement():
    """A late filing reconciles against its own month.

    A 2B for April routinely carries March invoices the supplier filed late.
    Booking those against April would compare them with the wrong month's
    purchase register and report both months as broken.
    """
    payload = portal_json()
    payload["data"]["docdata"]["b2b"][0]["inv"][0]["dt"] = "20-03-2026"
    (record,) = gstr2b.parse_json(payload)

    assert record.period == "2026-03"


def test_statement_period_is_the_fallback_when_a_date_is_missing():
    payload = portal_json()
    del payload["data"]["docdata"]["b2b"][0]["inv"][0]["dt"]
    (record,) = gstr2b.parse_json(payload)

    assert record.invoice_date is None
    assert record.period == "2026-04"


def test_intra_state_invoice_keeps_cgst_and_sgst_apart():
    payload = portal_json()
    supplier = payload["data"]["docdata"]["b2b"][0]
    supplier["ctin"] = SUPPLIER_GSTIN_SAME_STATE
    supplier["inv"][0]["items"] = [
        {"rt": 18, "txval": 100000.00, "cgst": 9000.00, "sgst": 9000.00, "igst": 0}
    ]
    (record,) = gstr2b.parse_json(payload)

    assert record.cgst == Decimal("9000.00")
    assert record.sgst == Decimal("9000.00")
    assert record.igst == Decimal("0.00")
    assert record.total_tax == Decimal("18000.00")


def test_itc_unavailable_flag_survives():
    payload = portal_json()
    payload["data"]["docdata"]["b2b"][0]["inv"][0]["itcavl"] = "N"
    (record,) = gstr2b.parse_json(payload)

    assert record.itc_available is False


def test_credit_notes_are_read_from_cdnr():
    payload = portal_json()
    payload["data"]["docdata"]["cdnr"] = [
        {
            "ctin": SUPPLIER_GSTIN_OTHER_STATE,
            "trdnm": "Northwind Supplies",
            "nt": [
                {
                    "nt_num": "CN-7",
                    "nt_dt": "28-04-2026",
                    "typ": "C",
                    "val": 11800.00,
                    "items": [{"rt": 18, "txval": 10000.00, "igst": 1800.00}],
                }
            ],
        }
    ]
    records = gstr2b.parse_json(payload)

    assert len(records) == 2
    note = next(r for r in records if r.invoice_number == "CN-7")
    assert note.document_type == "C"
    assert note.igst == Decimal("1800.00")
    # Stated positive, like every figure the portal writes. The type is the
    # only thing that says the credit moves the other way.
    assert note.is_credit_note is True


@pytest.mark.parametrize(
    ("document_type", "reverses"),
    [
        ("C", True),
        ("c", True),
        (" C ", True),
        # Credit note issued against a supply already reported — still a "C".
        ("CN", True),
        # A debit note raises the charge, so it moves with an invoice.
        ("D", False),
        ("R", False),
        ("ISD", False),
        ("IMPG", False),
    ],
)
def test_only_a_credit_note_takes_credit_back(document_type, reverses):
    record = gstr2b.GSTR2BRecord(document_type=document_type)
    assert record.is_credit_note is reverses


def test_total_value_is_derived_when_the_portal_omits_it():
    payload = portal_json()
    del payload["data"]["docdata"]["b2b"][0]["inv"][0]["val"]
    (record,) = gstr2b.parse_json(payload)

    assert record.total_value == Decimal("531000.00")


def test_bare_docdata_without_the_envelope_is_accepted():
    """Some exports and hand-built fixtures drop the outer wrapper."""
    payload = portal_json()["data"]["docdata"]
    records = gstr2b.parse_json(payload)

    assert len(records) == 1


def test_json_without_a_b2b_section_is_rejected():
    with pytest.raises(gstr2b.GSTR2BParseError, match="No b2b or cdnr section"):
        gstr2b.parse_json({"data": {"rtnprd": "042026"}})


def test_malformed_json_is_rejected_with_a_readable_message():
    with pytest.raises(gstr2b.GSTR2BParseError, match="not valid JSON"):
        gstr2b.parse_json("{not json")


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

CSV_EXPORT = f"""\
Goods and Services Tax - GSTR-2B,,,,,,,,,,,
B2B Invoices - Supplier Details,,,,,,,,,,,
GSTIN of supplier,Trade/Legal name,Invoice number,Invoice Date,Invoice Value(Rs),Place of supply,Supply Attract Reverse Charge,Rate(%),Taxable Value(Rs),Integrated Tax(Rs),Central Tax(Rs),State/UT Tax(Rs),Cess(Rs),GSTR-1/IFF/GSTR-5 Filing Date,ITC Availability
{SUPPLIER_GSTIN_OTHER_STATE},Northwind Supplies,INV-2026-0042,15-04-2026,531000.00,27-Maharashtra,N,18,450000.00,81000.00,0.00,0.00,0.00,11-05-2026,Yes
{SUPPLIER_GSTIN_SAME_STATE},Deccan Hardware,DH/451,18-04-2026,118000.00,27-Maharashtra,N,18,100000.00,0.00,9000.00,9000.00,0.00,10-05-2026,Yes
"""


def test_parses_a_csv_export():
    records = gstr2b.parse_csv(CSV_EXPORT)

    assert len(records) == 2
    northwind = next(r for r in records if r.supplier_gstin == SUPPLIER_GSTIN_OTHER_STATE)
    assert northwind.invoice_number == "INV-2026-0042"
    assert northwind.invoice_date == date(2026, 4, 15)
    assert northwind.taxable_value == Decimal("450000.00")
    assert northwind.igst == Decimal("81000.00")
    assert northwind.period == "2026-04"
    assert northwind.supplier_filing_date == date(2026, 5, 11)

    deccan = next(r for r in records if r.supplier_gstin == SUPPLIER_GSTIN_SAME_STATE)
    assert deccan.cgst == Decimal("9000.00")
    assert deccan.sgst == Decimal("9000.00")
    assert deccan.place_of_supply == "27"


def test_csv_title_rows_above_the_header_are_skipped():
    """The portal's CSV opens with title and section rows before the headings."""
    records = gstr2b.parse_csv(CSV_EXPORT)
    assert all(r.supplier_gstin for r in records)


def test_csv_rate_wise_rows_merge_into_one_invoice():
    csv_text = f"""\
GSTIN of supplier,Trade/Legal name,Invoice number,Invoice Date,Rate(%),Taxable Value(Rs),Integrated Tax(Rs)
{SUPPLIER_GSTIN_OTHER_STATE},Northwind,MULTI-1,15-04-2026,18,100000.00,18000.00
{SUPPLIER_GSTIN_OTHER_STATE},Northwind,MULTI-1,15-04-2026,5,50000.00,2500.00
"""
    (record,) = gstr2b.parse_csv(csv_text)

    assert record.taxable_value == Decimal("150000.00")
    assert record.igst == Decimal("20500.00")
    assert len(record.rate_items) == 2


def test_one_ineligible_line_makes_the_whole_invoice_ineligible():
    csv_text = f"""\
GSTIN of supplier,Invoice number,Invoice Date,Taxable Value(Rs),Integrated Tax(Rs),ITC Availability
{SUPPLIER_GSTIN_OTHER_STATE},SPLIT-1,15-04-2026,100000.00,18000.00,Yes
{SUPPLIER_GSTIN_OTHER_STATE},SPLIT-1,15-04-2026,50000.00,9000.00,No
"""
    (record,) = gstr2b.parse_csv(csv_text)

    assert record.itc_available is False


def test_csv_without_a_gstin_column_is_rejected():
    with pytest.raises(gstr2b.GSTR2BParseError, match="No supplier GSTIN column"):
        gstr2b.parse_csv("Invoice number,Taxable Value\nINV-1,100.00\n")


def test_csv_total_rows_are_ignored():
    csv_text = f"""\
GSTIN of supplier,Invoice number,Invoice Date,Taxable Value(Rs),Integrated Tax(Rs)
{SUPPLIER_GSTIN_OTHER_STATE},INV-1,15-04-2026,100000.00,18000.00
,,,100000.00,18000.00
"""
    records = gstr2b.parse_csv(csv_text)

    assert len(records) == 1


def test_empty_file_is_rejected():
    with pytest.raises(gstr2b.GSTR2BParseError, match="empty"):
        gstr2b.parse(b"")


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


def test_json_is_detected_by_content_not_extension():
    """Businesses rename these files; the bytes decide."""
    content = json.dumps(portal_json()).encode()
    records = gstr2b.parse(content, "gstr2b-april.txt")

    assert len(records) == 1


def test_csv_is_detected_by_content():
    records = gstr2b.parse(CSV_EXPORT.encode(), "2b.csv")
    assert len(records) == 2


def test_excel_is_refused_with_an_instruction():
    with pytest.raises(gstr2b.GSTR2BParseError, match="Save the sheet as CSV"):
        gstr2b.parse(b"PK\x03\x04 fake xlsx", "gstr2b.xlsx")


def test_utf8_bom_is_stripped():
    """Excel writes a BOM, which would otherwise corrupt the first heading."""
    records = gstr2b.parse(CSV_EXPORT.encode("utf-8-sig"), "2b.csv")
    assert len(records) == 2


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("042026", "2026-04"),
        ("122025", "2025-12"),
        ("2026-04", "2026-04"),
        ("", None),
        ("nonsense", None),
    ],
)
def test_portal_period_conversion(raw, expected):
    assert gstr2b.period_from_portal(raw) == expected


def test_a_credit_note_written_negative_is_stored_as_its_magnitude():
    """The sign is the document type's job. An ERP export that also signs the
    figures must not flip the note back into a grant of credit."""
    note = gstr2b.GSTR2BRecord(
        document_type="C",
        taxable_value=Decimal("-50000.00"),
        igst=Decimal("-9000.00"),
        total_value=Decimal("-59000.00"),
    )
    assert note.taxable_value == Decimal("50000.00")
    assert note.igst == Decimal("9000.00")
    assert note.total_tax == Decimal("9000.00")

    invoice = gstr2b.GSTR2BRecord(document_type="R", igst=Decimal("-1.00"))
    assert invoice.igst == Decimal("-1.00"), "only a credit note is normalised"


def test_a_signed_credit_note_takes_credit_away_in_the_summary():
    """₹18,000 of credit less a ₹9,000 note written as -9,000 is ₹9,000 — the
    signed note used to be subtracted as a negative and read as ₹27,000."""
    from app.services.reconciliation import summarise_records

    records = [
        gstr2b.GSTR2BRecord(document_type="R", taxable_value=Decimal("100000"), igst=Decimal("18000")),
        gstr2b.GSTR2BRecord(document_type="C", taxable_value=Decimal("-50000"), igst=Decimal("-9000")),
    ]
    summary = summarise_records(records)
    assert summary["total_igst"] == Decimal("9000")
