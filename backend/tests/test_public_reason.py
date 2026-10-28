"""``public_reason``: an exception's message, fit for a row the API returns."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.errors import DATABASE_FAILURE_REASON, STORAGE_FAILURE_REASON, public_reason


class TestWhatIsReplacedOutright:
    @pytest.mark.parametrize(
        "exc",
        [
            OperationalError("SELECT 1", {}, Exception("could not connect to 10.0.0.5")),
            IntegrityError("INSERT INTO invoices", {"id": 1}, Exception("duplicate key")),
        ],
    )
    def test_any_database_error_becomes_one_sentence(self, exc):
        assert public_reason(exc) == DATABASE_FAILURE_REASON

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError(2, "No such file", "/data/uploads/9/x.pdf"),
            PermissionError(13, "Permission denied", "/data/uploads"),
            IsADirectoryError(21, "Is a directory", "/data"),
        ],
    )
    def test_a_storage_error_becomes_one_sentence(self, exc):
        assert public_reason(exc) == STORAGE_FAILURE_REASON

    def test_a_network_timeout_is_not_called_a_storage_failure(self):
        # Both are OSError subclasses; only one is about the disk.
        assert public_reason(TimeoutError("model timed out")) == "model timed out"
        assert public_reason(ConnectionError("reset by peer")) == "reset by peer"


class TestWhatIsKept:
    def test_a_documents_own_dates_and_fractions_survive(self):
        message = "Tax on 15/04/2026 is 1/2 of the 18% slab"
        assert public_reason(ValueError(message)) == message

    def test_an_absolute_path_is_removed(self):
        reason = public_reason(RuntimeError("cannot open /opt/app/.venv/lib/x.so: bad ELF"))
        assert reason == "cannot open <path>: bad ELF"

    def test_an_empty_message_falls_back_to_the_exception_name(self):
        assert public_reason(RuntimeError()) == "RuntimeError"

    def test_it_is_bounded(self):
        assert len(public_reason(RuntimeError("x" * 5000))) == 2000
        assert len(public_reason(RuntimeError("x" * 50), limit=10)) == 10
