"""GSTR-2B files that are not the file the happy path assumes.

tests/test_gstr2b.py reads a well-formed portal download. This covers what
arrives instead: exports whose period is written the other way round, sections
holding nulls where objects were promised, CSVs with no headings, and the
question of what period a statement belongs to when nothing in it says.

The reason these matter more than usual is that a 2B is the *authority* in
reconciliation — it is what the tenant's own books are judged against. A file
half-read is worse than a file rejected, because the invoices it silently
dropped come back as "missing from the portal", which reads as a supplier who
failed to file and is the finding an accountant acts on.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from app.services import gstr2b
from app.services.gstr2b import GSTR2BParseError, parse_csv, parse_json, period_from_portal
from tests.conftest import (
    BUSINESS_GSTIN,
    SUPPLIER_GSTIN_OTHER_STATE,
    SUPPLIER_GSTIN_SAME_STATE,
)
from tests.test_gstr2b import portal_json
from tests.test_reconciliation import PERIOD, upload_2b

# --------------------------------------------------------------------------
# The portal's flags and periods
# --------------------------------------------------------------------------

class TestTheYesNoFlags:
    """`itcavl` and `rev` decide whether credit is claimable at all."""

    def test_a_real_boolean_from_a_json_export_is_used_as_is(self):
        payload = portal_json()
        payload["data"]["docdata"]["b2b"][0]["inv"][0]["itcavl"] = False
        assert gstr2b.parse_json(payload)[0].itc_available is False

    @pytest.mark.parametrize("raw", ["Y", "yes", "TRUE", "1", " y "])
    def test_the_spellings_an_export_uses_for_yes(self, raw):
        payload = portal_json()
        payload["data"]["docdata"]["b2b"][0]["inv"][0]["itcavl"] = raw
        assert gstr2b.parse_json(payload)[0].itc_available is True

    @pytest.mark.parametrize("raw", ["N", "no", "FALSE", "0"])
    def test_the_spellings_an_export_uses_for_no(self, raw):
        payload = portal_json()
        payload["data"]["docdata"]["b2b"][0]["inv"][0]["itcavl"] = raw
        assert gstr2b.parse_json(payload)[0].itc_available is False

    def test_an_unrecognised_word_falls_back_rather_than_guessing(self):
        # "Partially"/"Blocked" style text from a hand-edited export. Guessing
        # wrong here either invents credit or destroys it, so the field's
        # documented default is what stands.
        payload = portal_json()
        payload["data"]["docdata"]["b2b"][0]["inv"][0]["itcavl"] = "Partially"
        assert gstr2b.parse_json(payload)[0].itc_available is True

    def test_reverse_charge_defaults_to_off_when_the_word_is_unrecognised(self):
        payload = portal_json()
        payload["data"]["docdata"]["b2b"][0]["inv"][0]["rev"] = "maybe"
        assert gstr2b.parse_json(payload)[0].reverse_charge is False


class TestTheITCAnswerMeansTheSameInBothShapes:
    """The same word about the same credit, read the same way, either way in.

    A business uploads its 2B as the portal's JSON or as the CSV the portal
    also offers, and which one it picks is a matter of what its accountant
    downloaded — not a statement about the invoices. So a column that says
    credit is unavailable has to be read as unavailable in both, and the two
    readers here used to hold separate vocabularies for it: the CSV checked a
    private four-word set, the JSON went through the shared reader's eleven,
    and neither contained the other.

    The gaps ran one way, which is why this is a contract and not a tidy-up.
    Every word one reader missed was a *refusal* it read as consent, so tax the
    portal has withheld was counted claimable — it lands in ``itc_eligible``
    instead of ``itc_at_risk``, and the business is told a claim is safe in the
    precise case a notice is coming. Parametrised over both shapes rather than
    asserted twice, so a spelling added to one reader cannot quietly stay
    missing from the other.
    """

    @staticmethod
    def _from_json(raw: object) -> bool:
        payload = portal_json()
        payload["data"]["docdata"]["b2b"][0]["inv"][0]["itcavl"] = raw
        return parse_json(payload)[0].itc_available

    @staticmethod
    def _from_csv(raw: object) -> bool:
        csv_text = (
            "GSTIN of supplier,Invoice number,Invoice Date,"
            "Taxable Value(Rs),Integrated Tax(Rs),ITC Availability\n"
            f"{SUPPLIER_GSTIN_OTHER_STATE},AGREE-1,15-04-2026,"
            f'100000.00,18000.00,"{raw}"\n'
        )
        return parse_csv(csv_text)[0].itc_available

    def _read(self, shape: str, raw: object) -> bool:
        return self._from_json(raw) if shape == "json" else self._from_csv(raw)

    # The whole vocabulary of "no", not just the four the CSV used to know.
    # "N/A", "Nil", "None", "-" and "0" are what a hand-edited export carries
    # where the portal wrote "N"; "Not available" and "Unavailable" are the
    # words this column is actually about, and were the ones the JSON missed.
    @pytest.mark.parametrize("shape", ["json", "csv"])
    @pytest.mark.parametrize(
        "raw",
        [
            "N", "No", "NO", "FALSE", "0", "F", "NA", "N/A",
            "Not applicable", "None", "Nil", "-",
            "Not available", "Unavailable", "not available", " NOT AVAILABLE ",
        ],
    )
    def test_a_refusal_withholds_the_credit_whichever_shape_carries_it(self, shape, raw):
        assert self._read(shape, raw) is False

    @pytest.mark.parametrize("shape", ["json", "csv"])
    @pytest.mark.parametrize("raw", ["Y", "Yes", "TRUE", "1", "T", "Available", "Applicable"])
    def test_a_yes_leaves_the_credit_claimable_whichever_shape_carries_it(self, shape, raw):
        assert self._read(shape, raw) is True

    @pytest.mark.parametrize("shape", ["json", "csv"])
    @pytest.mark.parametrize("raw", ["", "Partially"])
    def test_saying_nothing_recognisable_defaults_to_available_in_both(self, shape, raw):
        # Not a refusal. Most exports leave the column empty on the rate lines
        # below the first, and the portal's own ``itcavl`` defaults this way —
        # so a blank must not start withholding credit that was never withheld.
        assert self._read(shape, raw) is True

    def test_one_refused_rate_line_still_latches_the_whole_document(self):
        # The widened vocabulary must not cost the latch: a document is one
        # credit decision, and a later line saying nothing cannot hand back
        # what an earlier line refused. "Nil" here is a word the CSV reader
        # could not previously read at all.
        csv_text = (
            "GSTIN of supplier,Invoice number,Invoice Date,"
            "Taxable Value(Rs),Integrated Tax(Rs),ITC Availability\n"
            f"{SUPPLIER_GSTIN_OTHER_STATE},LATCH-1,15-04-2026,100000.00,18000.00,Nil\n"
            f"{SUPPLIER_GSTIN_OTHER_STATE},LATCH-1,15-04-2026,50000.00,9000.00,\n"
            f"{SUPPLIER_GSTIN_OTHER_STATE},LATCH-1,15-04-2026,50000.00,9000.00,Yes\n"
        )
        (record,) = parse_csv(csv_text)

        assert record.itc_available is False
        assert record.taxable_value == Decimal("200000.00")


class TestPeriodFormats:
    def test_the_portals_mmyyyy_is_converted(self):
        assert period_from_portal("042026") == "2026-04"

    def test_an_export_that_writes_yyyymm_instead_is_still_read(self):
        # Both are six digits, so the only way to tell them apart is that one
        # of the two readings has a month in 1..12. 202604 has no month 26.
        assert period_from_portal("202604") == "2026-04"

    def test_a_period_already_in_the_internal_form_passes_through(self):
        assert period_from_portal("2026-04") == "2026-04"

    @pytest.mark.parametrize("raw", ["", None, "13-2026", "2026", "abcdef", "992026", "20261"])
    def test_anything_unreadable_becomes_none_rather_than_a_wrong_month(self, raw):
        assert period_from_portal(raw) is None

    def test_an_ambiguous_six_digits_prefers_the_portals_own_convention(self):
        # 012026 reads as MMYYYY (Jan 2026) and as YYYYMM only if year 0120.
        # MMYYYY is what the portal emits, so it wins.
        assert period_from_portal("012026") == "2026-01"

    # The YYYYMM fallback has its own 1..12 test, and the cases above only
    # reach it with a month of 04 — comfortably inside the range. Both ends of
    # a filing year go down this branch in practice: an annual export names
    # January and March, and a quarterly filer's is December.
    @pytest.mark.parametrize(
        "raw,period",
        [("202601", "2026-01"), ("202612", "2026-12"), ("202603", "2026-03")],
    )
    def test_the_yyyymm_fallback_accepts_both_ends_of_the_year(self, raw, period):
        assert period_from_portal(raw) == period

    @pytest.mark.parametrize("raw", ["132026", "002026", "202600", "202613"])
    def test_a_month_outside_the_year_is_refused_under_either_reading(self, raw):
        """Neither reading may be stretched to accept a thirteenth month.

        A period that parses to `2026-13` is worse than one that fails: it
        becomes a filing period no return can ever be filed for, and the
        invoices booked against it silently leave the reconciliation.
        """
        assert period_from_portal(raw) is None

    @pytest.mark.parametrize("raw", ["2026-13", "2026-00", "2026-99"])
    def test_the_passthrough_branch_checks_the_month_too(self, raw):
        """The six-digit readings both range-checked the month; this one did not.

        It matched on shape alone, so a hand-edited statement naming
        ``2026-13`` was accepted verbatim — and this is the one path by which
        a period reaches the database without passing a route's validation.
        Stored, it becomes a filing period no return can ever be filed for.
        """
        assert period_from_portal(raw) is None


# --------------------------------------------------------------------------
# JSON that is shaped wrong
# --------------------------------------------------------------------------

class TestMalformedJsonStructures:
    def test_a_json_array_is_rejected_with_a_readable_message(self):
        # A hand-built export sometimes ships just the b2b list.
        with pytest.raises(GSTR2BParseError, match="not a GSTR-2B download"):
            parse_json(json.dumps([{"ctin": SUPPLIER_GSTIN_OTHER_STATE}]))

    @pytest.mark.parametrize("junk", [None, "a string", 42, ["a", "list"]])
    def test_a_non_object_supplier_entry_is_skipped_not_fatal(self, junk):
        payload = portal_json()
        payload["data"]["docdata"]["b2b"].append(junk)
        # The good supplier beside it must survive; dropping the whole file
        # over one bad row loses every invoice in it.
        assert len(parse_json(payload)) == 1

    @pytest.mark.parametrize("junk", [None, "INV-1", 7, []])
    def test_a_non_object_invoice_entry_is_skipped_not_fatal(self, junk):
        payload = portal_json()
        payload["data"]["docdata"]["b2b"][0]["inv"].append(junk)
        assert len(parse_json(payload)) == 1

    def test_an_invoice_with_no_items_block_still_becomes_a_record(self):
        # Some exports omit the rate-wise lines entirely and give only the
        # invoice total. The invoice still has to appear, or it reconciles as
        # missing from the portal.
        payload = portal_json()
        del payload["data"]["docdata"]["b2b"][0]["inv"][0]["items"]
        records = parse_json(payload)
        assert len(records) == 1
        assert records[0].invoice_number == "INV-2026-0042"

    def test_items_under_the_abbreviated_key_are_read_too(self):
        payload = portal_json()
        invoice = payload["data"]["docdata"]["b2b"][0]["inv"][0]
        invoice["itms"] = invoice.pop("items")
        assert parse_json(payload)[0].igst == pytest.approx(81000.00)

    def test_items_nested_under_itm_det_are_flattened(self):
        payload = portal_json()
        invoice = payload["data"]["docdata"]["b2b"][0]["inv"][0]
        invoice["items"] = [{"num": 1, "itm_det": {"rt": 18, "txval": 450000.00,
                                                   "igst": 81000.00}}]
        assert parse_json(payload)[0].igst == pytest.approx(81000.00)

    def test_a_section_holding_null_instead_of_a_list_is_tolerated(self):
        payload = portal_json()
        payload["data"]["docdata"]["cdnr"] = None
        assert len(parse_json(payload)) == 1


# --------------------------------------------------------------------------
# CSV exports that are not quite exports
# --------------------------------------------------------------------------

class TestMalformedCsv:
    def test_an_entirely_empty_file_is_rejected(self):
        with pytest.raises(GSTR2BParseError, match="empty"):
            parse_csv("")

    def test_a_file_of_only_blank_lines_is_rejected(self):
        # Excel "save as CSV" on an empty sheet produces exactly this.
        with pytest.raises(GSTR2BParseError, match="empty"):
            parse_csv("\n\n,,,\n   \n")

    def test_a_file_whose_heading_row_is_only_punctuation_is_rejected(self):
        # Headings squash to alphanumerics before they are matched, so a rule
        # of dashes is non-blank to the reader and empty to the matcher. The
        # message has to say "no headings" rather than "no GSTIN column",
        # which would send someone looking for a column that is not missing.
        with pytest.raises(GSTR2BParseError, match="headings"):
            parse_csv("-,--,-\n1,2,3\n")

    def test_bytes_are_decoded_and_a_bom_is_stripped(self):
        # Excel writes UTF-8 with a BOM, which otherwise glues itself to the
        # first heading and makes the GSTIN column unfindable.
        csv_text = (
            "GSTIN of Supplier,Invoice Number,Invoice Date,Taxable Value,IGST,CGST,SGST\n"
            f"{SUPPLIER_GSTIN_OTHER_STATE},INV-1,15-04-2026,1000,180,0,0\n"
        )
        records = parse_csv(("﻿" + csv_text).encode("utf-8"))
        assert records[0].supplier_gstin == SUPPLIER_GSTIN_OTHER_STATE

    def test_a_row_with_fewer_cells_than_the_heading_keeps_what_it_has(self):
        """Short rows are ordinary, and losing one loses a real invoice.

        A portal export whose trailing columns are empty is commonly saved
        without the trailing commas — by Excel, by a hand-edit, by anything
        that round-trips the file — so its data rows are simply narrower than
        the heading. Each mapped column is read only when the row is long
        enough to have it, and what is read stays right: a row that stops
        after IGST is an invoice with no CGST or SGST on it, which is what an
        inter-state supply is.

        What this rules out is an IndexError on the first short row, which
        would reject the whole statement — and a rejected 2B is every invoice
        in it reported as one the supplier never filed.
        """
        csv_text = (
            "GSTIN of Supplier,Invoice Number,Invoice Date,Taxable Value,IGST,CGST,SGST\n"
            f"{SUPPLIER_GSTIN_OTHER_STATE},INV-SHORT,15-04-2026,1000,180\n"
        )
        (record,) = parse_csv(csv_text)

        assert record.supplier_gstin == SUPPLIER_GSTIN_OTHER_STATE
        assert record.invoice_number == "INV-SHORT"
        assert record.taxable_value == Decimal("1000")
        assert record.igst == Decimal("180")
        assert record.cgst == Decimal("0")
        assert record.sgst == Decimal("0")

    def test_a_row_too_short_to_name_a_document_is_skipped(self):
        """The other end of the same rule. A row that reaches neither
        identifying column names no document, and is the trailing total line
        or the note under the table rather than a supply — so it is dropped
        instead of being stored as a record with everything blank."""
        csv_text = (
            "Sr No,GSTIN of Supplier,Invoice Number,Invoice Date,Taxable Value,IGST\n"
            f"1,{SUPPLIER_GSTIN_OTHER_STATE},INV-1,15-04-2026,1000,180\n"
            "Total\n"
        )
        assert [r.invoice_number for r in parse_csv(csv_text)] == ["INV-1"]

    def test_undecodable_bytes_do_not_raise(self):
        # A latin-1 export. Replacement characters in a trade name are far
        # better than refusing the file.
        csv_text = (
            "GSTIN of Supplier,Supplier Name,Invoice Number,Invoice Date,Taxable Value,IGST\n"
            f"{SUPPLIER_GSTIN_OTHER_STATE},Caf\xe9 Supplies,INV-1,15-04-2026,1000,180\n"
        ).encode("latin-1")
        assert parse_csv(csv_text)[0].supplier_gstin == SUPPLIER_GSTIN_OTHER_STATE


# --------------------------------------------------------------------------
# The import endpoint's remaining branches
# --------------------------------------------------------------------------

class TestTheImportEndpointRefusals:
    def test_a_file_over_the_size_limit_is_refused_with_413(self, auth_client):
        from app.core.config import settings

        oversized = b"[" + b"0" * (settings.max_upload_mb * 1024 * 1024) + b"]"
        response = upload_2b(auth_client, content=oversized)

        assert response.status_code == 413
        assert str(settings.max_upload_mb) in response.json()["detail"]
        # The size, and no advice about reducing it: a 2B is one portal
        # download for one registration for one month, so there is nothing the
        # user can re-export or split. Meeting this means the deployment's
        # limit is under what a real statement weighs, and the number is what
        # they report to whoever can raise it.
        assert "gstr2b.json is " in response.json()["detail"]
        assert "split" not in response.json()["detail"]

    def test_an_empty_file_says_it_may_still_be_downloading(self, auth_client):
        response = upload_2b(auth_client, content=b"")

        assert response.status_code == 400
        assert "0 bytes" in response.json()["detail"]

    def test_a_file_that_is_not_a_2b_says_what_to_download_instead(self, auth_client):
        """The likeliest wrong file is a real GST download of another kind."""
        response = upload_2b(auth_client, content=b"%PDF-1.7", filename="gstr3b.pdf")

        assert response.status_code == 415
        detail = response.json()["detail"]
        assert "gstr3b.pdf" in detail
        assert "portal" in detail

    def test_a_valid_2b_containing_no_invoices_is_refused(self, auth_client):
        # Parses cleanly, and yields nothing — a period with no inward
        # supplies, or the wrong download. Importing it would silently mark
        # every booked invoice as missing from the portal.
        payload = portal_json()
        payload["data"]["docdata"]["b2b"] = []
        response = upload_2b(auth_client, content=json.dumps(payload).encode())

        assert response.status_code == 422
        assert "No invoices found" in response.json()["detail"]


class TestWhoseStatementThisIs:
    """A GSTR-2B is generated per registration and says so.

    Importing one into the wrong tenant is the mistake a practice with several
    clients on one login is placed to make, and nothing downstream can notice
    it: every purchase in the books reconciles as missing from the statement,
    every document in the statement as missing from the books, and the screen
    reports the period's whole credit at risk. Those numbers are all correct
    and the conclusion is nonsense.
    """

    @staticmethod
    def _addressed_to(gstin: str | None) -> bytes:
        payload = portal_json()
        if gstin is None:
            del payload["data"]["gstin"]
        else:
            payload["data"]["gstin"] = gstin
        return json.dumps(payload).encode()

    def test_a_statement_addressed_to_another_registration_is_refused(self, auth_client):
        response = upload_2b(auth_client, content=self._addressed_to(SUPPLIER_GSTIN_SAME_STATE))

        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert SUPPLIER_GSTIN_SAME_STATE in detail
        assert BUSINESS_GSTIN in detail

    def test_the_refusal_stores_nothing(self, auth_client):
        upload_2b(auth_client, content=self._addressed_to(SUPPLIER_GSTIN_SAME_STATE))

        assert auth_client.get("/api/v1/reconciliation/gstr2b/periods").json() == {"items": []}

    def test_the_tenants_own_statement_goes_through(self, auth_client):
        response = upload_2b(auth_client, content=self._addressed_to(BUSINESS_GSTIN))
        assert response.status_code in (200, 201), response.text

    def test_the_addressee_is_read_case_and_space_insensitively(self, auth_client):
        """Hand-edited exports arrive lower-cased and padded; that is not a mismatch."""
        response = upload_2b(
            auth_client, content=self._addressed_to(f"  {BUSINESS_GSTIN.lower()} ")
        )
        assert response.status_code in (200, 201), response.text

    def test_a_statement_that_names_nobody_is_still_accepted(self, auth_client):
        """A CSV export has no envelope, and neither do some JSON ones.

        Refusing what the file does not say would reject downloads the portal
        plainly produced, so an unknown addressee is not a mismatch.
        """
        response = upload_2b(auth_client, content=self._addressed_to(None))
        assert response.status_code in (200, 201), response.text

    def test_a_csv_export_carries_no_addressee(self):
        assert gstr2b.recipient_gstin(b"GSTIN of supplier,Invoice number\n", "x.csv") is None

    def test_an_unreadable_file_leaves_the_parser_to_say_so(self, auth_client):
        """A broken file is a parse error, not a "wrong registration" error."""
        response = upload_2b(auth_client, content=b"{not json")
        assert response.status_code == 422
        assert "GSTIN" not in response.json()["detail"]

    @pytest.mark.parametrize("payload", [b"", b"[]", b'{"data": []}', b'"a string"'])
    def test_shapes_that_carry_no_addressee_do_not_raise(self, payload):
        assert gstr2b.recipient_gstin(payload, "x.json") is None

    def test_an_envelope_without_the_data_wrapper_is_read_too(self):
        assert gstr2b.recipient_gstin(
            json.dumps({"gstin": BUSINESS_GSTIN, "docdata": {"b2b": []}}).encode(), "x.json"
        ) == BUSINESS_GSTIN


def _unstamped() -> bytes:
    """The portal fixture with neither period stamp — as a CSV export arrives."""
    payload = portal_json()
    del payload["data"]["rtnprd"]
    payload["data"]["docdata"]["b2b"][0]["supprd"] = ""
    return json.dumps(payload).encode()


class TestWhichPeriodAStatementBelongsTo:
    def test_an_explicit_period_on_the_form_wins_when_the_file_has_no_stamp(
        self, auth_client
    ):
        response = upload_2b(auth_client, content=_unstamped(), period="2026-05")
        assert response.status_code in (200, 201)
        assert response.json()["period"] == "2026-05"

    def test_a_form_period_contradicting_the_portal_stamp_is_refused(self, auth_client):
        # The fixture is stamped April. Stored as May it would have replaced
        # May's real statement and reconciled both months against the wrong one.
        response = upload_2b(auth_client, period="2026-05")
        assert response.status_code == 422
        assert "2026-04" in response.json()["detail"]
        assert "2026-05" in response.json()["detail"]
        periods = auth_client.get("/api/v1/reconciliation/gstr2b/periods").json()
        assert "2026-05" not in json.dumps(periods)

    def test_a_form_period_agreeing_with_the_stamp_is_accepted(self, auth_client):
        response = upload_2b(auth_client, period=PERIOD)
        assert response.status_code == 201, response.text
        assert response.json()["period"] == PERIOD

    def test_otherwise_the_period_the_portal_stamped_is_used(self, auth_client):
        assert upload_2b(auth_client).json()["period"] == PERIOD

    def test_with_no_stamp_the_commonest_invoice_period_is_inferred(self, auth_client):
        # A file with no rtnprd at all. Two invoices in April, one in March,
        # so the statement is April's.
        payload = portal_json()
        del payload["data"]["rtnprd"]
        supplier = payload["data"]["docdata"]["b2b"][0]
        supplier["supprd"] = ""
        invoice = supplier["inv"][0]
        supplier["inv"] = [
            {**invoice, "inum": "INV-A", "dt": "15-04-2026"},
            {**invoice, "inum": "INV-B", "dt": "20-04-2026"},
            {**invoice, "inum": "INV-C", "dt": "10-03-2026"},
        ]

        body = upload_2b(auth_client, content=json.dumps(payload).encode()).json()
        assert body["period"] == "2026-04"

    def test_a_tie_breaks_toward_the_later_month(self, auth_client):
        # Late filings drag earlier months in, and the statement is about the
        # newest of them. Left to dict ordering this would depend on which
        # invoice happened to be read first.
        payload = portal_json()
        del payload["data"]["rtnprd"]
        supplier = payload["data"]["docdata"]["b2b"][0]
        supplier["supprd"] = ""
        invoice = supplier["inv"][0]
        supplier["inv"] = [
            {**invoice, "inum": "INV-MAR", "dt": "10-03-2026"},
            {**invoice, "inum": "INV-APR", "dt": "15-04-2026"},
        ]

        body = upload_2b(auth_client, content=json.dumps(payload).encode()).json()
        assert body["period"] == "2026-04"

    def test_a_file_whose_period_cannot_be_determined_is_refused(self, auth_client):
        # No stamp and no readable invoice date. Guessing would file the
        # statement against the wrong month, which is worse than asking.
        payload = portal_json()
        del payload["data"]["rtnprd"]
        supplier = payload["data"]["docdata"]["b2b"][0]
        supplier["supprd"] = ""
        supplier["inv"][0]["dt"] = ""

        response = upload_2b(auth_client, content=json.dumps(payload).encode())
        assert response.status_code == 422
        assert "period" in response.json()["detail"].lower()


class TestAPeriodTheCallerNames:
    """The form value is the only way an unreal month reaches the column.

    Every other period input in the product is checked against
    ``PERIOD_PATTERN``; this one was not, and it is the one that *writes* a
    period. The two the file itself can offer are derived — one from an invoice
    date, one from a validated portal field — so nothing else could put a month
    that does not exist on a stored statement.
    """

    @pytest.mark.parametrize(
        "period",
        [
            "2026-13",  # No thirteenth month; every later screen divides by it.
            "2026-00",  # Quietly aliased onto January.
            "2026-4",   # Unpadded: sorts and compares wrongly against stored ones.
            "202604",   # The portal's own MMYYYY, pasted the wrong way round.
            "April 2026",
        ],
    )
    def test_a_period_that_is_not_one_is_refused(self, auth_client, period):
        assert upload_2b(auth_client, period=period).status_code == 422

    def test_a_blank_field_still_means_read_it_from_the_file(self, auth_client):
        # A form input the user never touched submits as an empty string, and
        # FastAPI reads that as the field being absent rather than as a period
        # of "". Tightening the pattern must not turn the ordinary case — drop
        # the file in, name nothing — into a validation error.
        response = upload_2b(auth_client, period="")
        assert response.status_code == 201, response.text
        assert response.json()["period"] == PERIOD

    def test_a_period_too_long_for_the_column_is_refused(self, auth_client):
        # ``gstr_returns.period`` is VARCHAR(7). Postgres refuses anything
        # longer and the API reports the failure as a 500; SQLite has no width
        # at all and keeps the whole string, so the suite would have seen
        # nothing wrong. Refusing it here is what makes the two agree.
        assert upload_2b(auth_client, period="2026-04-15").status_code == 422

    def test_a_real_period_still_wins_over_an_unstamped_file(self, auth_client):
        response = upload_2b(auth_client, content=_unstamped(), period="2026-05")
        assert response.status_code == 201, response.text
        assert response.json()["period"] == "2026-05"


class TestListingRunsByPeriod:
    def test_the_listing_can_be_filtered_to_one_period(self, auth_client):
        upload_2b(auth_client)
        auth_client.post("/api/v1/reconciliation/run", json={"period": PERIOD})

        matching = auth_client.get("/api/v1/reconciliation", params={"period": PERIOD})
        assert matching.status_code == 200
        assert matching.json()["total"] >= 1
        assert all(row["period"] == PERIOD for row in matching.json()["items"])

    def test_a_period_with_no_runs_lists_nothing(self, auth_client):
        upload_2b(auth_client)
        auth_client.post("/api/v1/reconciliation/run", json={"period": PERIOD})

        empty = auth_client.get("/api/v1/reconciliation", params={"period": "2019-01"})
        assert empty.json()["total"] == 0
        assert empty.json()["items"] == []


# --------------------------------------------------------------------------
# Shapes the portal never produces
# --------------------------------------------------------------------------

class TestASectionThatIsNotAList:
    """`b2b`, `cdnr` and a supplier's `inv` are lists, or they hold nothing.

    A hand-edited export, a truncated download, or a middleware that
    helpfully replaced an empty list with `0` puts something else there. The
    parser iterated it regardless, so `'int' object is not iterable` came out
    of the middle of the read and the upload — which the endpoint can see is
    malformed, and has a 400 ready to say so — was answered with a 500 and a
    correlation id instead. Nothing in that response tells the user their file
    is the problem, so the failure reads as an outage.
    """

    @pytest.mark.parametrize("section", ["b2b", "b2ba", "cdnr", "cdnra"])
    @pytest.mark.parametrize("value", [5, "abc", {"ctin": "x"}, None, 1.5])
    def test_a_section_holding_something_other_than_a_list_is_not_read(
        self, section, value
    ):
        payload = {"gstin": BUSINESS_GSTIN, "docdata": {section: value, "b2b": []}}
        payload["docdata"][section] = value
        # No invoice can be read out of it, but it must not raise TypeError.
        assert gstr2b.parse_json(payload) == []

    @pytest.mark.parametrize("value", [3, "abc", 2.5])
    def test_a_supplier_whose_documents_are_not_a_list_is_skipped(self, value):
        payload = {
            "gstin": BUSINESS_GSTIN,
            "docdata": {"b2b": [{"ctin": SUPPLIER_GSTIN_SAME_STATE, "inv": value}]},
        }
        assert gstr2b.parse_json(payload) == []

    def test_one_malformed_supplier_does_not_cost_the_others_their_invoices(self):
        # The point of skipping rather than refusing: a file with one bad
        # block still imports every invoice that is readable.
        payload = {
            "gstin": BUSINESS_GSTIN,
            "docdata": {
                "b2b": [
                    {"ctin": SUPPLIER_GSTIN_SAME_STATE, "inv": 7},
                    {
                        "ctin": SUPPLIER_GSTIN_OTHER_STATE,
                        "inv": [{"inum": "INV-9", "dt": "05-04-2026", "val": 1180}],
                    },
                ]
            },
        }
        records = gstr2b.parse_json(payload)
        assert [record.invoice_number for record in records] == ["INV-9"]

    @pytest.mark.parametrize("value", [4, "x", [1, 2], 1.5])
    def test_a_rate_line_whose_itm_det_is_not_an_object_still_reads(self, value):
        # ``{**4}`` is a TypeError. The rest of the line is readable, so the
        # bad nesting is dropped rather than the invoice.
        payload = {
            "gstin": BUSINESS_GSTIN,
            "docdata": {
                "b2b": [
                    {
                        "ctin": SUPPLIER_GSTIN_SAME_STATE,
                        "inv": [
                            {
                                "inum": "INV-1",
                                "dt": "05-04-2026",
                                "itms": [{"itm_det": value, "txval": 1000}],
                            }
                        ],
                    }
                ]
            },
        }
        records = gstr2b.parse_json(payload)
        assert len(records) == 1
        assert records[0].invoice_number == "INV-1"
        assert records[0].taxable_value == Decimal("1000.00")

    @pytest.mark.parametrize(
        "docdata",
        [
            {"b2b": 5},
            {"cdnr": 7},
            {"b2b": [{"ctin": SUPPLIER_GSTIN_SAME_STATE, "inv": 3}]},
            {
                "b2b": [
                    {
                        "ctin": SUPPLIER_GSTIN_SAME_STATE,
                        "inv": [{"inum": "1", "itms": [{"itm_det": 4}]}],
                    }
                ]
            },
        ],
        ids=["b2b-int", "cdnr-int", "inv-int", "itmdet-int"],
    )
    def test_the_endpoint_answers_a_malformed_file_without_a_server_error(
        self, auth_client, docdata
    ):
        payload = {"gstin": BUSINESS_GSTIN, "rtnprd": "042026", "docdata": docdata}
        response = upload_2b(auth_client, content=json.dumps(payload).encode())
        assert response.status_code < 500, response.text



class TestAFileThatIsNotAStatementIsRefusedNotCrashedOn:
    """Two shapes the readers raised on with something other than a parse
    error, each a 500 on an upload whose only fault is not being a GSTR-2B."""

    def test_json_nested_past_the_recursion_limit(self, auth_client):
        deep = b"[" * 100_000 + b"]" * 100_000
        response = upload_2b(auth_client, content=deep, filename="gstr2b.json")
        assert response.status_code == 422
        assert "not valid JSON" in response.json()["detail"]

    def test_a_csv_cell_past_the_field_limit(self, auth_client):
        huge = b"GSTIN of supplier,Invoice number\n" + b"x" * 200_000 + b",A1\n"
        response = upload_2b(auth_client, content=huge, filename="gstr2b.csv")
        assert response.status_code == 422
        assert "could not be read as CSV" in response.json()["detail"]

    def test_the_addressee_check_survives_it_too(self):
        assert gstr2b.recipient_gstin(b"[" * 100_000, "x.json") is None


class TestAHalfPairInTheFileIsNotStoredAsWritten:
    """JSON may spell half a UTF-16 pair. Stored in an invoice number it made
    every later response that serialised the row a 500 — reconciliation, the
    invoice list — and on Postgres the import itself."""

    def test_the_import_keeps_the_rest_of_the_value(self, auth_client):
        payload = portal_json()
        payload["data"]["docdata"]["b2b"][0]["inv"][0]["inum"] = "INV-\ud800-42"
        response = upload_2b(auth_client, content=json.dumps(payload).encode())
        assert response.status_code == 201, response.text
        records = gstr2b.parse_json(json.dumps(payload))
        assert records[0].invoice_number == "INV-\ufffd-42"

    def test_reconciliation_still_runs_afterwards(self, auth_client):
        payload = portal_json()
        payload["data"]["docdata"]["b2b"][0]["trdnm"] = "Northwind \udfff"
        payload["data"]["docdata"]["b2b"][0]["inv"][0]["inum"] = "INV-\ud800"
        assert upload_2b(auth_client, content=json.dumps(payload).encode()).status_code == 201
        run = auth_client.post("/api/v1/reconciliation/run", json={"period": PERIOD})
        assert run.status_code == 201, run.text
