"""Retention that holds on a quiet site.

The feedback sender address and the client-error log were pruned only when the
next feedback or the next new error arrived, so on days with neither, which is
most days, nothing was cleared and a 30-day policy kept addresses for good.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from app.celery_app import celery_app
from app.models.feedback import ClientError, Feedback, FeedbackCategory
from app.models.mixins import utcnow
from app.services import job_health, retention


def _seed(db_session):
    now = utcnow()
    old = retention.FEEDBACK_IP_RETENTION + timedelta(days=1)
    db_session.add_all(
        [
            Feedback(category=FeedbackCategory.BUG, message="old", email="a@example.com",
                     ip_address="203.0.113.7", created_at=now - old),
            Feedback(category=FeedbackCategory.BUG, message="recent",
                     ip_address="203.0.113.8", created_at=now - timedelta(days=2)),
            ClientError(fingerprint="f" * 64, page="/x", message="gone quiet",
                        first_seen_at=now - old, last_seen_at=now - old),
            ClientError(fingerprint="e" * 64, page="/y", message="still happening",
                        first_seen_at=now - old, last_seen_at=now - timedelta(hours=1)),
        ]
    )
    db_session.commit()


class TestPruningWithNothingNewArriving:
    def test_old_addresses_and_stale_errors_go_and_the_rest_stays(self, db_session):
        _seed(db_session)

        result = retention.prune_personal_data(db_session)

        assert result.as_dict() == {"feedback_ips_cleared": 1, "client_errors_deleted": 1}
        rows = {f.message: f for f in db_session.query(Feedback).all()}
        assert rows["old"].ip_address is None
        assert rows["old"].email == "a@example.com"  # the message and its sender stay
        assert rows["recent"].ip_address == "203.0.113.8"
        assert [e.message for e in db_session.query(ClientError).all()] == ["still happening"]

    def test_running_again_finds_nothing(self, db_session):
        _seed(db_session)
        retention.prune_personal_data(db_session)
        assert retention.prune_personal_data(db_session).as_dict() == {
            "feedback_ips_cleared": 0,
            "client_errors_deleted": 0,
        }


class TestTheDailyTask:
    def test_it_prunes_and_records_its_heartbeat(self, db_session, monkeypatch):
        from app.tasks import retention_tasks

        _seed(db_session)
        monkeypatch.setattr(retention_tasks, "SessionLocal", lambda: db_session)
        monkeypatch.setattr(db_session, "close", lambda: None)
        with patch.object(job_health, "record_heartbeat") as beat:
            result = retention_tasks.prune_personal_data_task.apply().get()
        assert result == {"feedback_ips_cleared": 1, "client_errors_deleted": 1}
        beat.assert_called_once_with("personal-data-retention")

    def test_it_is_scheduled_registered_and_watched(self):
        import app.tasks.retention_tasks  # noqa: F401 - registers the task

        entry = celery_app.conf.beat_schedule["personal-data-retention"]
        assert entry["task"] == "retention.prune_personal_data"
        assert entry["task"] in celery_app.tasks
        assert "app.tasks.retention_tasks" in celery_app.conf.include
        # A daily job the monitor would not miss if it stopped.
        assert job_health.JOB_STALE_AFTER_SECONDS["personal-data-retention"] == 26 * 3600
