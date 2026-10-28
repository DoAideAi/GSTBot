"""Bulk invoice upload: the same validation as a single upload, per file.

A batch is a person dragging a folder of paperwork in, and one bad or
duplicate page in it must not cost the other forty-nine — see
``POST /invoices/bulk`` in app/routers/invoices.py. The tests below are mostly
about that isolation: every file gets its own verdict, and the request itself
only fails for something that is wrong about the *batch* (too many files),
never about one file in it.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models.invoice import Invoice, InvoiceStatus
from app.routers.invoices import MAX_BULK_FILES
from tests.conftest import BUSINESS_GSTIN, SUPPLIER_GSTIN_OTHER_STATE


def bulk_upload(client, files: list[tuple[str, str]], *, invoice_type: str = "purchase"):
    """*files* is a list of ``(name, text)`` pairs."""
    return client.post(
        "/api/v1/invoices/bulk",
        files=[("files", (name, text.encode(), "text/plain")) for name, text in files],
        data={"invoice_type": invoice_type},
    )


def _invoice_text(number: str) -> str:
    return f"Invoice No: {number}\nTotal Amount: 100.00"


class TestAllFilesValid:
    def test_every_file_is_accepted(self, auth_client):
        response = bulk_upload(
            auth_client,
            [(f"inv-{i}.txt", _invoice_text(f"BULK-{i}")) for i in range(3)],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 3
        assert body["accepted"] == 3
        assert body["rejected"] == 0
        assert all(item["accepted"] for item in body["items"])
        assert all(item["invoice"] is not None for item in body["items"])

    def test_invoices_are_actually_stored(self, auth_client, db_session, business):
        bulk_upload(
            auth_client, [(f"inv-{i}.txt", _invoice_text(f"BULK-S-{i}")) for i in range(3)]
        )
        count = (
            db_session.query(Invoice)
            .filter_by(business_id=business.id)
            .count()
        )
        assert count == 3

    def test_the_invoice_type_applies_to_the_whole_batch(self, auth_client, db_session):
        bulk_upload(
            auth_client,
            [(f"sale-{i}.txt", _invoice_text(f"BULK-SALE-{i}")) for i in range(2)],
            invoice_type="sales",
        )
        types = {inv.invoice_type.value for inv in db_session.query(Invoice).all()}
        assert types == {"sales"}


class TestOneBadFileDoesNotSinkTheBatch:
    def test_an_empty_file_is_rejected_alone(self, auth_client):
        response = bulk_upload(
            auth_client,
            [
                ("good.txt", _invoice_text("BULK-GOOD")),
                ("empty.txt", ""),
            ],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 1
        bad = next(item for item in body["items"] if item["filename"] == "empty.txt")
        assert bad["accepted"] is False
        assert "empty" in bad["error"].lower()
        good = next(item for item in body["items"] if item["filename"] == "good.txt")
        assert good["accepted"] is True

    def test_an_unsupported_file_type_is_rejected_alone(self, auth_client):
        response = auth_client.post(
            "/api/v1/invoices/bulk",
            files=[
                ("files", ("good.txt", _invoice_text("BULK-OK").encode(), "text/plain")),
                ("files", ("virus.exe", b"MZ\x90\x00", "application/x-msdownload")),
            ],
            data={"invoice_type": "purchase"},
        )
        body = response.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 1
        bad = next(item for item in body["items"] if item["filename"] == "virus.exe")
        assert bad["error"] is not None

    def test_a_duplicate_within_the_batch_is_rejected_and_points_at_the_original(
        self, auth_client
    ):
        text = _invoice_text("BULK-DUP")
        response = bulk_upload(
            auth_client,
            [("first.txt", text), ("second.txt", text)],
        )
        body = response.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 1

        first = next(item for item in body["items"] if item["filename"] == "first.txt")
        second = next(item for item in body["items"] if item["filename"] == "second.txt")
        assert first["accepted"] is True
        assert second["accepted"] is False
        assert second["duplicate_of_invoice_id"] == first["invoice"]["id"]


class TestTheBatchSizeLimit:
    def test_a_batch_over_the_limit_is_refused_outright(self, auth_client):
        files = [(f"f{i}.txt", _invoice_text(f"OVER-{i}")) for i in range(MAX_BULK_FILES + 1)]
        response = bulk_upload(auth_client, files)
        assert response.status_code == 413
        assert str(MAX_BULK_FILES) in response.json()["detail"]

    def test_a_batch_at_exactly_the_limit_is_accepted(self, auth_client):
        files = [(f"f{i}.txt", _invoice_text(f"AT-{i}")) for i in range(MAX_BULK_FILES)]
        response = bulk_upload(auth_client, files)
        assert response.status_code == 200
        assert response.json()["total"] == MAX_BULK_FILES


class TestThePlanLimit:
    def test_files_past_the_monthly_allowance_are_rejected_not_the_batch(
        self, auth_client, monkeypatch
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "plan_monthly_invoice_limits", "free=2")
        response = bulk_upload(
            auth_client,
            [(f"p{i}.txt", _invoice_text(f"PLAN-{i}")) for i in range(4)],
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["accepted"] == 2
        assert body["rejected"] == 2
        # The two that fit are the first two attempted, not a scattered subset.
        assert [item["accepted"] for item in body["items"]] == [True, True, False, False]
        assert "plan" in body["items"][2]["error"].lower()


class TestAPaidPlanLiftsTheAllowance:
    """Buying a plan never wrote `business.plan`, which is what the cap reads,
    so a business that paid for Pro was still stopped at the free plan's limit
    and told to upgrade."""

    LIMITS = "free=2,pro=0,ca_bundle=0"

    def _subscribe(self, db_session, business, tier, period_end):
        from app.models.subscription import Subscription, SubscriptionStatus

        db_session.add(
            Subscription(
                business_id=business.id,
                tier=tier,
                status=SubscriptionStatus.ACTIVE,
                current_period_end=period_end,
            )
        )
        db_session.commit()

    @pytest.mark.parametrize("tier_name", ["PRO", "ENTERPRISE"])
    def test_a_paid_business_is_not_held_to_the_free_cap(
        self, auth_client, business, db_session, monkeypatch, tier_name
    ):
        from datetime import UTC, datetime, timedelta

        from app.core.config import settings
        from app.models.subscription import SubscriptionTier

        monkeypatch.setattr(settings, "plan_monthly_invoice_limits", self.LIMITS)
        tier = SubscriptionTier[tier_name]
        self._subscribe(db_session, business, tier, datetime.now(UTC) + timedelta(days=20))
        files = [(f"paid{i}.txt", _invoice_text(f"PAID-{tier_name}-{i}")) for i in range(4)]
        response = bulk_upload(auth_client, files)
        assert response.json()["accepted"] == 4

    def test_a_lapsed_plan_is_held_to_the_stored_plan_again(
        self, auth_client, business, db_session, monkeypatch
    ):
        from datetime import UTC, datetime, timedelta

        from app.core.config import settings
        from app.models.subscription import SubscriptionTier

        monkeypatch.setattr(settings, "plan_monthly_invoice_limits", self.LIMITS)
        self._subscribe(
            db_session, business, SubscriptionTier.PRO, datetime.now(UTC) - timedelta(days=1)
        )
        response = bulk_upload(
            auth_client, [(f"lapsed{i}.txt", _invoice_text(f"LAPSED-{i}")) for i in range(3)]
        )
        body = response.json()
        assert body["accepted"] == 2
        assert "plan 'free'" in body["items"][2]["error"].lower()

    def test_the_usage_page_shows_the_paid_allowance(
        self, auth_client, business, db_session, monkeypatch
    ):
        from datetime import UTC, datetime, timedelta

        from app.core.config import settings
        from app.models.subscription import SubscriptionTier

        monkeypatch.setattr(settings, "plan_monthly_invoice_limits", self.LIMITS)
        self._subscribe(
            db_session, business, SubscriptionTier.PRO, datetime.now(UTC) + timedelta(days=20)
        )
        usage = auth_client.get("/api/v1/subscriptions/usage").json()["usage"][0]
        assert usage["limit"] == 0  # unlimited


class TestAuthAndTenancy:
    def test_bulk_upload_requires_authentication(self, client):
        response = bulk_upload(client, [("a.txt", _invoice_text("AUTH-1"))])
        assert response.status_code == 401

    def test_files_land_under_the_uploading_tenant(self, auth_client, business, db_session):
        bulk_upload(auth_client, [("t.txt", _invoice_text("TENANT-1"))])
        invoice = db_session.query(Invoice).filter_by(invoice_number="TENANT-1").one()
        assert invoice.business_id == business.id


# ---------------------------------------------------------------------------
# The batch against the pipeline it claims to share
# ---------------------------------------------------------------------------
#
# Everything above this line is about the batch's own arithmetic, and every
# file in it is the two-line ``_invoice_text``. That leaves the endpoint's
# actual claim — "the same checks and the same extraction path as POST
# /invoices/upload, run once per file" — resting on the two routes calling the
# same helper today. These push a real document through the batch and assert
# the result, so a change that reaches only the single-upload path is a
# failure here rather than a field that quietly stops being extracted for
# anyone who dragged a folder in.


class TestTheBatchExtractsWhatASingleUploadWould:
    def test_a_real_invoice_is_extracted_through_the_batch(
        self, auth_client, sample_invoice_text
    ):
        response = bulk_upload(auth_client, [("inv.txt", sample_invoice_text)])
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["accepted"] is True
        # Celery is off in tests, so extraction has already run inline — the
        # same assertion test_invoices.py makes about the single upload.
        assert item["queued"] is False

        invoice = item["invoice"]
        assert invoice["status"] == InvoiceStatus.PARSED.value
        assert invoice["invoice_number"] == "INV-2026-0042"
        assert invoice["invoice_date"] == "2026-04-15"
        assert invoice["period"] == "2026-04"
        assert Decimal(invoice["total_value"]) == Decimal("531000.00")

    def test_the_tax_split_is_decided_in_a_batch_too(
        self, auth_client, sample_invoice_text
    ):
        """A Karnataka supplier billing Maharashtra is IGST, not CGST+SGST.

        The split is derived from the two state codes rather than read off the
        page, and it is the one extracted field a wrong answer files rather
        than merely displays: the heads are separate columns in the return.
        """
        item = bulk_upload(auth_client, [("inv.txt", sample_invoice_text)]).json()["items"][0]
        invoice = item["invoice"]
        assert Decimal(invoice["igst"]) == Decimal("81000.00")
        assert Decimal(invoice["cgst"]) == Decimal("0")
        assert Decimal(invoice["sgst"]) == Decimal("0")

    def test_the_counterparty_is_the_supplier_and_not_the_tenant(
        self, auth_client, sample_invoice_text
    ):
        # The document carries both GSTINs. Booking ours as the vendor is the
        # failure test_invoices.py pins for the single upload; the batch reads
        # the same two sides.
        invoice = bulk_upload(auth_client, [("inv.txt", sample_invoice_text)]).json()[
            "items"
        ][0]["invoice"]
        assert invoice["counterparty_gstin"] == SUPPLIER_GSTIN_OTHER_STATE
        assert invoice["counterparty_gstin"] != BUSINESS_GSTIN


class TestTheOrderOfTheAnswers:
    def test_items_come_back_in_the_order_the_files_were_sent(self, auth_client):
        """The list is positional, and the upload screen relies on it being so.

        ``UploadPage`` reverses each response before prepending it, because the
        results list reads newest-first and the server answers oldest-first.
        Nothing in the payload carries the send position otherwise — the
        filenames are the user's and can repeat — so a reordering here would
        show every row against the wrong document with nothing to notice it by.
        """
        names = [f"z{i}.txt" for i in range(5)]
        response = bulk_upload(
            auth_client, [(name, _invoice_text(f"ORDER-{i}")) for i, name in enumerate(names)]
        )
        body = response.json()
        assert [item["filename"] for item in body["items"]] == names
        assert [item["invoice"]["invoice_number"] for item in body["items"]] == [
            f"ORDER-{i}" for i in range(5)
        ]

    def test_a_rejected_file_holds_its_place_rather_than_being_moved_to_the_end(
        self, auth_client
    ):
        # The rejected item is appended from the same loop as an accepted one,
        # and the screen pairs rows to files by position. Collecting failures
        # separately would be the natural refactor and would silently break
        # that pairing, so the interleaving is asserted rather than assumed.
        response = bulk_upload(
            auth_client,
            [
                ("first.txt", _invoice_text("ORDER-A")),
                ("bad.txt", ""),
                ("third.txt", _invoice_text("ORDER-B")),
            ],
        )
        body = response.json()
        assert [item["filename"] for item in body["items"]] == [
            "first.txt",
            "bad.txt",
            "third.txt",
        ]
        assert [item["accepted"] for item in body["items"]] == [True, False, True]


class TestARejectionMidBatchLeavesTheRestAlone:
    def test_the_files_before_it_are_committed(self, auth_client, db_session, business):
        """A rejection is raised as an HTTPException the loop swallows.

        Everything already stored is in the same session, so a rollback taking
        the batch back with it would be invisible in the response — every
        earlier item still reads ``accepted`` — and would surface as invoices
        that were reported as stored and are not there.
        """
        bulk_upload(
            auth_client,
            [
                ("good-1.txt", _invoice_text("MID-1")),
                ("empty.txt", ""),
                ("good-2.txt", _invoice_text("MID-2")),
            ],
        )
        stored = {
            invoice.invoice_number
            for invoice in db_session.query(Invoice).filter_by(business_id=business.id)
        }
        assert {"MID-1", "MID-2"} <= stored

    def test_every_file_is_attempted_however_many_fail(self, auth_client):
        # Nothing short-circuits the loop: a batch of mostly-bad files still
        # answers for each one. The plan limit is the single exception, and it
        # rejects rather than stops — see TestThePlanLimit.
        response = bulk_upload(
            auth_client,
            [("e1.txt", ""), ("e2.txt", ""), ("ok.txt", _invoice_text("MID-3")), ("e3.txt", "")],
        )
        body = response.json()
        assert body["total"] == 4
        assert body["accepted"] == 1
        assert body["rejected"] == 3
        assert len(body["items"]) == 4


class TestTheNameTheAnswerCarries:
    def test_a_path_in_the_filename_is_reduced_to_its_leaf(self, auth_client):
        """The name is echoed back to the screen, so it is sanitised first.

        A browser does not send a path, but the endpoint is reachable by
        anything that speaks multipart, and this name is rendered as a row
        label. ``safe_filename`` is what the single upload runs too; asserting
        it here is asserting that the batch did not skip it.
        """
        response = auth_client.post(
            "/api/v1/invoices/bulk",
            files=[
                (
                    "files",
                    ("../../etc/passwd", _invoice_text("LEAF-1").encode(), "text/plain"),
                )
            ],
            data={"invoice_type": "purchase"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["filename"] == "passwd"

    def test_a_name_that_sanitises_away_falls_back_rather_than_coming_back_empty(
        self, auth_client
    ):
        """A name of three dots is all separators, and reduces to nothing.

        Reported rather than refused: the stored file is named after a UUID, so
        an unusable name costs a label and nothing else. The fallback is what
        keeps the item titled — an empty ``filename`` would be a row the screen
        has nothing to render, and the batch is the one route where a row is
        all the user has to tell one file's outcome from another's.

        A part sent with no filename at all cannot get this far: multipart
        without a filename is an ordinary form field, so it never reaches the
        route as a file and the request is refused for having none.
        """
        response = auth_client.post(
            "/api/v1/invoices/bulk",
            files=[("files", ("...", _invoice_text("NONAME-1").encode(), "text/plain"))],
            data={"invoice_type": "purchase"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["items"][0]["filename"] == "invoice"


class TestTheBatchAndTheSingleUploadAgree:
    def test_the_same_document_is_stored_the_same_way_either_way(
        self, auth_client, sample_invoice_text
    ):
        """One document, two routes, one result.

        The duplicate check makes this awkward to assert directly — the second
        copy of a document is refused whichever route it arrives by — so the
        two are compared on the fields the extractor filled rather than by
        uploading the same text twice. What is being pinned is that the batch
        is not a second, drifting implementation of the same parse.
        """
        single = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("one.txt", sample_invoice_text.encode(), "text/plain")},
            data={"invoice_type": "purchase"},
        )
        assert single.status_code == 201, single.text

        # The same document with a different number, so it is not a duplicate.
        batched_text = sample_invoice_text.replace("INV-2026-0042", "INV-2026-0043")
        batched = bulk_upload(auth_client, [("two.txt", batched_text)])
        assert batched.status_code == 200, batched.text

        compared = (
            "invoice_date",
            "period",
            "counterparty_gstin",
            "place_of_supply",
            "taxable_value",
            "igst",
            "cgst",
            "sgst",
            "total_value",
            "status",
            "invoice_type",
        )
        one = single.json()["invoice"]
        two = batched.json()["items"][0]["invoice"]
        assert {field: one[field] for field in compared} == {
            field: two[field] for field in compared
        }


class TestTheBatchDoesNotRereadTheTenantPerFile:
    """Nothing about the tenant changes between the files of one batch.

    Two separate reads used to happen per file, for the same reason and by
    different routes. ``apply_parsed`` walked ``invoice.business`` for the
    tenant's own GSTIN; ``check_plan_limit`` read ``business.plan``. Both are
    lazy loads off an instance that every file's commit expires, so both were a
    fresh ``SELECT`` on ``businesses`` for *every* file rather than just the
    first — fifty round trips each, through a fifty-file batch, for two values
    that cannot change between them.

    The fix that holds is not fetching either one earlier but not touching the
    row at all: expiry is per instance, so the first attribute read after a
    commit reloads the whole thing and removing one of the two would simply
    have moved the read onto the other. ``TenantSnapshot`` is taken once,
    before the loop, and the loop sees plain data.

    Only the inline path does this at all: with a live broker each file goes
    to its own Celery task, one invoice per task. The suite runs with Redis
    unreachable, which is exactly the degraded path where the batch parses in
    a loop — so this is measured where it actually happened.
    """

    @staticmethod
    def _business_reads(auth_client, db_session, count: int, tag: str) -> int:
        reads: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            squashed = " ".join(statement.split()).lower()
            if squashed.startswith("select") and "from businesses" in squashed:
                reads.append(squashed)

        engine = db_session.get_bind()
        event.listen(engine, "before_cursor_execute", _record)
        try:
            response = bulk_upload(
                auth_client,
                [(f"{tag}-{i}.txt", _invoice_text(f"{tag}-{i}")) for i in range(count)],
            )
            assert response.status_code == 200, response.text
            assert response.json()["accepted"] == count
        finally:
            event.remove(engine, "before_cursor_execute", _record)
        return len(reads)

    def test_a_batch_costs_the_same_reads_of_the_tenant_however_many_files(
        self, auth_client, db_session
    ):
        """Flat, not merely flatter.

        Stated as the *slope* rather than as a total, because the total is a
        fact about how many times a request resolves its tenant — which the
        role gate and the dependency cache both bear on — and this test is
        about none of that. Six more files must cost no more reads at all.
        """
        at_two = self._business_reads(auth_client, db_session, 2, "TWO")
        at_eight = self._business_reads(auth_client, db_session, 8, "EIGHT")

        assert at_eight == at_two, (
            f"{at_two} reads of businesses for two files and {at_eight} for eight — "
            f"{(at_eight - at_two) / 6:g} per extra file rather than 0. Something in "
            "the loop is touching the expired Business row again."
        )

    def test_the_tenant_is_read_once_for_the_whole_batch(self, auth_client, db_session):
        """And that the flat line above is flat at one, not at a stale zero.

        A cached ``Business`` that the session never expired would also make
        the slope zero while meaning the opposite — that the loop is reading a
        row nothing has refreshed since the request began. One read per
        request is the tenant being resolved by ``get_active_tenant``, which is
        exactly where it should happen and nowhere else.
        """
        assert self._business_reads(auth_client, db_session, 6, "SIX") == 1


class TestTheCallerThatPassesNoTenant:
    """The optimisation above must not be the only way the GSTIN is found.

    ``apply_parsed`` takes the tenant's own GSTIN as a parameter so the batch
    loop does not re-read it per file. The Celery path has no such loop and no
    such value: the task is handed an invoice id and nothing else, so it calls
    through without one and the fallback walk down ``invoice.business`` is what
    supplies it.

    That fallback is load-bearing rather than defensive. Without the tenant's
    own GSTIN the counterparty flip below cannot happen, and a purchase whose
    supplier printed our GSTIN in the supplier field would be filed with *our*
    GSTIN as the vendor — a purchase from ourselves, in the books the ITC claim
    is computed from. Deleting the parameter's default, or letting the walk
    become dead code behind an always-passing caller, would surface as wrong
    numbers on the worker path only.
    """

    @staticmethod
    def _parsed():
        from app.services.invoice_parser import ParsedInvoice

        # What a one-GSTIN invoice looks like after extraction: the supplier
        # filled in a single GSTIN field and put ours in it.
        return ParsedInvoice(
            supplier_gstin=BUSINESS_GSTIN,
            supplier_name="Us",
            buyer_gstin=SUPPLIER_GSTIN_OTHER_STATE,
            buyer_name="Them",
            invoice_number="INV-FALLBACK-1",
            taxable_value=Decimal("1000.00"),
            total_value=Decimal("1180.00"),
        )

    def test_the_tenant_gstin_is_read_off_the_row_when_none_is_passed(
        self, db_session, business
    ):
        from app.models.invoice import InvoiceSource, InvoiceType
        from app.services.invoice_service import apply_parsed

        invoice = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            source=InvoiceSource.UPLOAD,
            status=InvoiceStatus.UPLOADED,
            source_filename="bill.txt",
        )
        db_session.add(invoice)
        db_session.commit()

        apply_parsed(db_session, invoice, self._parsed())

        # Flipped, which is only possible if the walk found our own GSTIN.
        assert invoice.counterparty_gstin == SUPPLIER_GSTIN_OTHER_STATE
        assert invoice.counterparty_name == "Them"

    def test_the_walk_and_the_parameter_reach_the_same_answer(self, db_session, business):
        """The two callers must not file the same invoice two different ways.

        The parameter exists for the batch loop's sake alone. If it ever came
        to mean something the walk does not — a different value, a different
        precedence — the path an upload happened to take (inline batch, or a
        Celery task when the broker is up) would decide who the vendor was.
        """
        from app.models.invoice import InvoiceSource, InvoiceType
        from app.services.invoice_service import apply_parsed

        passed = Invoice(
            business_id=business.id,
            invoice_type=InvoiceType.PURCHASE,
            source=InvoiceSource.UPLOAD,
            status=InvoiceStatus.UPLOADED,
            source_filename="passed.txt",
        )
        db_session.add(passed)
        db_session.commit()

        apply_parsed(db_session, passed, self._parsed(), business_gstin=BUSINESS_GSTIN)

        assert passed.counterparty_gstin == SUPPLIER_GSTIN_OTHER_STATE
        assert passed.counterparty_name == "Them"
