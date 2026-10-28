"""What an upload pays when Redis, the broker, is down.

The upload hands the parse to a worker and, if the hand-off raises, parses
inline instead. That fallback is only as good as how quickly the hand-off
gives up. Before these settings an unreachable broker cost 19s per upload
(the result backend's reconnect loop, for results nothing reads) and an
address that drops packets did not answer within two minutes.

The suite's broker is a unix socket that does not exist, so the real enqueue
path is exercised here against a refused connection, with no Redis needed.
"""
from __future__ import annotations

import time

import pytest
from kombu.exceptions import OperationalError

from app.celery_app import celery_app
from app.core.config import settings
from app.tasks.invoice_tasks import parse_invoice_task


class TestTheSettings:
    def test_task_results_are_not_stored(self):
        assert celery_app.conf.task_ignore_result is True

    def test_the_broker_connect_is_bounded(self):
        options = celery_app.conf.broker_transport_options
        assert options["socket_connect_timeout"] == settings.redis_timeout_seconds
        assert options["socket_timeout"] > 1, "must outlast the worker's 1s BRPOP"

    def test_publishing_retries_once_at_most(self):
        policy = celery_app.conf.task_publish_retry_policy
        assert policy["max_retries"] <= 1
        assert policy["interval_max"] <= 0.5


class TestAnUnreachableBroker:
    def test_enqueueing_fails_fast(self):
        started = time.monotonic()
        with pytest.raises(OperationalError):
            parse_invoice_task.delay(1)
        assert time.monotonic() - started < 3

    def test_an_upload_falls_back_to_parsing_inline_promptly(
        self, monkeypatch, auth_client, sample_invoice_text
    ):
        monkeypatch.setattr(settings, "celery_enabled", True)
        started = time.monotonic()

        response = auth_client.post(
            "/api/v1/invoices/upload",
            files={"file": ("invoice.txt", sample_invoice_text.encode(), "text/plain")},
            data={"invoice_type": "purchase"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["invoice"]["status"] == "parsed"
        assert time.monotonic() - started < 5
