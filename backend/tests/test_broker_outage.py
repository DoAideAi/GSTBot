"""What an upload pays when Redis, the broker, is down.

The upload hands the parse to a worker and, if the hand-off raises, parses
inline instead. That fallback is only as good as how quickly the hand-off
gives up. Before these settings an unreachable broker cost 19s per upload
(the result backend's reconnect loop, for results nothing reads) and an
address that drops packets did not answer within two minutes.

The enqueue is exercised against a real refused TCP port, so no Redis is
needed.
"""
from __future__ import annotations

import socket
import time

import pytest
from celery import Celery
from kombu.exceptions import OperationalError

from app.celery_app import celery_app
from app.core.config import settings


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


_OUTAGE_SETTINGS = (
    "task_ignore_result",
    "broker_transport_options",
    "task_publish_retry_policy",
)


def _noop() -> None:
    """The task body; never runs, since it is never delivered."""


@pytest.fixture()
def refused_redis_url():
    """A local TCP port with nothing listening on it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"redis://127.0.0.1:{port}/0"


class TestAnUnreachableBroker:
    def test_enqueueing_fails_fast(self, monkeypatch, refused_redis_url):
        # The suite's own broker URL names no transport kombu has, so this is
        # an app with production's settings pointed at a real refused port.
        # Celery prefers the environment variable to the constructor argument.
        monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
        monkeypatch.delenv("CELERY_RESULT_BACKEND", raising=False)
        app = Celery("outage", broker=refused_redis_url, backend=refused_redis_url)
        app.conf.update({key: celery_app.conf[key] for key in _OUTAGE_SETTINGS})
        task = app.task(name="outage.noop", shared=False)(_noop)

        started = time.monotonic()
        with pytest.raises(OperationalError):
            task.delay()
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


class TestABatchDuringAnOutage:
    """Fifty files must not each pay for the dead broker and a model call.

    The single-file fallback, repeated per file, held a bulk request for over
    an hour: a publish timeout and an inline parse of up to the model budget,
    fifty times. The batch now asks the broker once and parses inline only for
    a bounded time; the rest are stored ``uploaded`` for the stall sweep.
    """

    @staticmethod
    def _files(text: str, count: int):
        return [
            ("files", (f"inv-{n}.txt", f"{text}\nInvoice No: BULK-{n}".encode(), "text/plain"))
            for n in range(count)
        ]

    @pytest.fixture()
    def dead_broker(self, monkeypatch):
        from app.tasks.invoice_tasks import parse_invoice_task

        calls = []

        def refuse(*args, **kwargs):
            calls.append(args)
            raise OperationalError("Connection refused")

        monkeypatch.setattr(settings, "celery_enabled", True)
        monkeypatch.setattr(parse_invoice_task, "delay", refuse)
        return calls

    def test_the_broker_is_asked_once_per_batch(
        self, dead_broker, auth_client, sample_invoice_text
    ):
        response = auth_client.post(
            "/api/v1/invoices/bulk",
            files=self._files(sample_invoice_text, 3),
            data={"invoice_type": "purchase"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["accepted"] == 3
        assert len(dead_broker) == 1
        # Within the inline budget, so all three are still parsed now.
        statuses = {i["invoice"]["status"] for i in response.json()["items"]}
        assert "uploaded" not in statuses and "processing" not in statuses

    def test_past_the_inline_budget_files_are_stored_for_the_sweep(
        self, dead_broker, monkeypatch, auth_client, sample_invoice_text
    ):
        from app.routers import invoices

        monkeypatch.setattr(invoices, "_BULK_INLINE_SECONDS", 0.0)

        response = auth_client.post(
            "/api/v1/invoices/bulk",
            files=self._files(sample_invoice_text, 3),
            data={"invoice_type": "purchase"},
        )

        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert all(item["accepted"] for item in items)
        assert {item["invoice"]["status"] for item in items} == {"uploaded"}
        assert not any(item["queued"] for item in items)
