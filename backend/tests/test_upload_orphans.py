"""The file on disk when the row that names it is never written.

``create_pending_invoice`` writes the bytes before it inserts the row, and it
has to: ``storage_path`` is a column on that row, so the path must exist to be
stored. That ordering is fine as long as the commit succeeds. When it does not,
the file is left behind with nothing in the database pointing at it — and
nothing ever will:

* no query reads ``upload_dir``; every read starts from ``Invoice.storage_path``
* the delete route keeps stored files on purpose, so it is not a sweeper either
* there is no sweeper

So every upload that meets a full connection pool, a dropped connection, or a
constraint used to leave a permanent orphan, on a volume sized for the rows
that exist rather than for the ones that failed to be written.

The cleanup is best effort by design. These tests pin both halves of that: the
file goes away, and a cleanup that cannot run does not replace the failure the
caller is entitled to see.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.models.business import Business
from app.models.invoice import InvoiceType
from app.services import invoice_service
from tests.conftest import BUSINESS_GSTIN


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch) -> Path:
    """Point storage at a directory that starts empty and belongs to one test."""
    directory = tmp_path / "invoices"
    monkeypatch.setattr(settings, "upload_dir", str(directory))
    return directory


@pytest.fixture()
def business(db_session) -> Business:
    record = Business(
        gstin=BUSINESS_GSTIN,
        legal_name="Umang Traders Private Limited",
        state_code=BUSINESS_GSTIN[:2],
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    return record


def _create(db, business, *, content: bytes = b"a bill"):
    return invoice_service.create_pending_invoice(
        db,
        invoice_service.TenantSnapshot.of(business),
        content=content,
        filename="bill.txt",
        content_type="text/plain",
        invoice_type=InvoiceType.PURCHASE,
    )


def _stored_files(upload_dir: Path) -> list[Path]:
    return [p for p in upload_dir.rglob("*") if p.is_file()]


class _CommitFails:
    """A commit that raises the way a full pool or a dropped connection does.

    Patched on the session rather than on the engine because the point is what
    ``create_pending_invoice`` does with a failure, not which layer produced
    it. The rollback is left working — a session that cannot roll back is a
    different defect, and one this code cannot do anything about.

    ``restore`` puts the real commit back and nothing else, which is why this
    is not ``monkeypatch.undo()``: that would also revert ``upload_dir`` and
    send the next upload to the real storage directory.
    """

    error = OperationalError

    def __init__(self, session):
        self._session = session
        self._original = session.commit
        session.commit = self._boom

    @staticmethod
    def _boom():
        raise OperationalError("INSERT INTO invoices", {}, Exception("pool exhausted"))

    def restore(self):
        self._session.commit = self._original


@pytest.fixture()
def commit_fails(db_session):
    handle = _CommitFails(db_session)
    yield handle
    handle.restore()


class TestACommitThatFailsLeavesNothingBehind:
    def test_the_happy_path_still_stores_the_file(self, db_session, business, upload_dir):
        """The baseline the rest of this depends on: a good commit keeps it."""
        invoice = _create(db_session, business)
        assert Path(invoice.storage_path).is_file()
        assert len(_stored_files(upload_dir)) == 1

    def test_the_orphan_is_removed(self, db_session, business, upload_dir, commit_fails):
        with pytest.raises(commit_fails.error):
            _create(db_session, business)
        assert _stored_files(upload_dir) == []

    def test_the_original_failure_is_what_surfaces(
        self, db_session, business, upload_dir, commit_fails
    ):
        # The caller has to see the database error. A cleanup that raised on
        # top of it would replace the only useful thing in the traceback.
        with pytest.raises(commit_fails.error) as caught:
            _create(db_session, business)
        assert "pool exhausted" in str(caught.value)

    def test_a_later_upload_is_unaffected(
        self, db_session, business, upload_dir, commit_fails
    ):
        """The rollback has to leave the session usable, not just the disk."""
        with pytest.raises(commit_fails.error):
            _create(db_session, business)

        commit_fails.restore()
        invoice = _create(db_session, business, content=b"a different bill")
        assert invoice.id is not None
        assert Path(invoice.storage_path).is_file()
        # Only the second file: the first was cleaned up, and the two have
        # different digests so the duplicate check is not what is being seen.
        assert len(_stored_files(upload_dir)) == 1

    def test_a_duplicate_is_refused_before_anything_is_written(
        self, db_session, business, upload_dir
    ):
        """The other way out of this function must not store a file at all.

        ``DuplicateInvoice`` is raised above ``store_upload``, so there is no
        orphan to clean up — and if that order ever inverted, the cleanup would
        not catch it, because the raise is not inside the ``try``.
        """
        _create(db_session, business)
        with pytest.raises(invoice_service.DuplicateInvoice):
            _create(db_session, business)
        assert len(_stored_files(upload_dir)) == 1


class TestTheCleanupItselfIsBestEffort:
    def test_an_unlink_that_fails_does_not_mask_the_commit_error(
        self, db_session, business, upload_dir, monkeypatch, commit_fails
    ):
        """A read-only volume leaves the same orphan as before, and no more.

        This is the case the cleanup deliberately does not guarantee. What it
        must not do is turn a database failure into an ``OSError`` from the
        cleanup path, which is what the caller would otherwise be handed.
        """

        def cannot_unlink(self, missing_ok=False):
            raise OSError(30, "Read-only file system")

        monkeypatch.setattr(Path, "unlink", cannot_unlink)
        with pytest.raises(commit_fails.error):
            _create(db_session, business)

    def test_the_failure_to_clean_up_is_logged(
        self, db_session, business, upload_dir, monkeypatch, caplog, commit_fails
    ):
        # Silent to the caller, not silent to the operator: an orphan nobody
        # can see is how the volume filled up unnoticed in the first place.
        def cannot_unlink(self, missing_ok=False):
            raise OSError(30, "Read-only file system")

        monkeypatch.setattr(Path, "unlink", cannot_unlink)
        with (
            caplog.at_level("WARNING", logger="app.services.invoice_service"),
            pytest.raises(commit_fails.error),
        ):
            _create(db_session, business)
        assert any("orphaned upload" in record.message for record in caplog.records)

    def test_a_path_that_is_already_gone_is_not_an_error(self):
        # ``missing_ok`` covers the case where something else removed it first.
        invoice_service._discard_upload("/nonexistent/directory/nothing.txt")

    def test_no_path_is_not_an_error(self):
        invoice_service._discard_upload(None)


class TestStoredExtension:
    """``store_upload`` keeps only a plain alphanumeric extension.

    It took the client's suffix as-is, so ``shell.php;jpg`` was written as
    ``<uuid>.php;jpg``. ``safe_extension`` was written for this and unused.
    """

    @pytest.mark.parametrize(
        ("filename", "expected"),
        [
            ("invoice.PDF", ".pdf"),
            ("shell.php;jpg", ""),
            ("x.p df", ""),
            ("no-extension", ""),
            ("", ""),
        ],
    )
    def test_the_stored_name_carries_a_sanitised_extension(
        self, monkeypatch, tmp_path, filename, expected
    ):
        from app.services.invoice_service import store_upload

        monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
        stored = Path(store_upload(b"%PDF-1.4", filename, business_id=7))

        assert stored.parent == tmp_path / "7"
        assert stored.suffix == expected
        assert len(stored.stem) == 32  # the UUID, never the client's name
