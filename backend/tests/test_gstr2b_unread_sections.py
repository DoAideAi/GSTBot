"""A GSTR-2B's credit that this import does not read is named, not dropped.

The portal's 2B carries more than supplier invoices: ``impg``/``impgsez`` hold
the IGST paid on imports (bills of entry), ``isd``/``isda`` the credit an
input service distributor passed on, ``ecom``/``ecoma`` supplies made through
an e-commerce operator. The import reads only ``b2b``/``b2ba``/``cdnr``/
``cdnra`` and passed over the rest without a word. An importer whose credit
is all bill-of-entry IGST was told "Imported 0 invoices", and every importer
saw statement totals short by exactly the credit that was skipped — numbers
they compare against the portal, and act on.
"""
from __future__ import annotations

import json

from app.services import gstr2b
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE

IMPORT = "/api/v1/reconciliation/gstr2b/import"

_INVOICE = {
    "inum": "INV-1", "dt": "05-04-2026", "val": 1180, "typ": "R", "pos": "27",
    "rev": "N", "itcavl": "Y",
    "items": [{"rt": 18, "txval": 1000, "igst": 180, "cgst": 0, "sgst": 0, "cess": 0}],
}
_BOE = {"refdt": "10-04-2026", "portcode": "INNSA1", "boenum": "1234567",
        "boedt": "08-04-2026", "txval": 50000, "igst": 9000, "cess": 0}


def _statement(**docdata):
    return {"data": {"gstin": BUSINESS_GSTIN, "rtnprd": "042026", "docdata": docdata}}


def _bytes(payload) -> bytes:
    return json.dumps(payload).encode()


def test_it_counts_the_documents_in_each_section_it_does_not_read():
    content = _bytes(_statement(
        b2b=[{"ctin": SUPPLIER_GSTIN_OTHER_STATE, "inv": [_INVOICE]}],
        impg=[_BOE, {**_BOE, "boenum": "7654321"}],
        impgsez=[{"ctin": SUPPLIER_GSTIN_OTHER_STATE, "boe": [_BOE]}],
        isd=[{"ctin": SUPPLIER_GSTIN_OTHER_STATE, "doclist": [{"docnum": "ISD-1"}] * 3}],
    ))

    assert gstr2b.unread_sections(content, "2b.json") == {"impg": 2, "impgsez": 1, "isd": 3}


def test_a_statement_it_reads_whole_has_nothing_to_report():
    content = _bytes(_statement(b2b=[{"ctin": SUPPLIER_GSTIN_OTHER_STATE, "inv": [_INVOICE]}]))
    assert gstr2b.unread_sections(content, "2b.json") == {}
    assert gstr2b.unread_sections(b"GSTIN of supplier,Invoice number\n", "2b.csv") == {}


def test_the_import_says_what_it_left_out(auth_client, paid_business):
    content = _bytes(_statement(
        b2b=[{"ctin": SUPPLIER_GSTIN_OTHER_STATE, "inv": [_INVOICE]}],
        impg=[_BOE],
        isd=[{"ctin": SUPPLIER_GSTIN_OTHER_STATE, "doclist": [{"docnum": "ISD-1"}]}],
    ))
    response = auth_client.post(
        IMPORT, files={"file": ("2b.json", content, "application/json")}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["unread_sections"] == {"impg": 1, "isd": 1}
    assert "1 bill of entry (imports)" in body["message"]
    assert "1 ISD credit document" in body["message"]


def test_an_importers_statement_is_not_reported_as_empty(auth_client, paid_business):
    # No b2b at all: every rupee of this month's credit is on bills of entry.
    response = auth_client.post(
        IMPORT,
        files={"file": ("2b.json", _bytes(_statement(impg=[_BOE])), "application/json")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invoice_count"] == 0
    assert body["unread_sections"] == {"impg": 1}
    assert "bill of entry" in body["message"]
