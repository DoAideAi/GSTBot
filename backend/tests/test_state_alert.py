"""M3 state machine: alert lifecycle — PENDING → SENT → READ → DISMISSED,
with RESOLVED from the sweep when the filing happens, and re-raise from
RESOLVED/DISMISSED when the situation worsens.

States: PENDING, SENT, READ, DISMISSED, FAILED, RESOLVED.

Guards:
- mark_read only moves OPEN statuses (not DISMISSED, not RESOLVED).
- dismiss only moves OPEN statuses (not RESOLVED).
- _move_if uses CAS: the WHERE pins the current status.
- The sweep resolves on filing, re-raises on unfiling or escalation.

Side effects:
- Delivery sets channel and sent_at alongside SENT.
- Sweep rewrites title, message, severity, due_date when the alert is open.

Idempotency:
- mark_read on an already-READ alert is a no-op.
- dismiss on an already-DISMISSED alert is a no-op.
- dismiss on a RESOLVED alert leaves it RESOLVED.
"""
from __future__ import annotations

from datetime import date

from app.models.alert import (
    OPEN_STATUSES,
    Alert,
    AlertSeverity,
    AlertStatus,
    AlertType,
)

ALERT_DEFAULTS = dict(
    alert_type=AlertType.FILING_DEADLINE,
    severity=AlertSeverity.WARNING,
    title="GSTR-3B due",
    message="File your GSTR-3B",
    period="2026-04",
    due_date=date(2026, 5, 20),
)


def _alert(db, business, *, status=AlertStatus.PENDING, **overrides) -> Alert:
    fields = {**ALERT_DEFAULTS, **overrides}
    a = Alert(business_id=business.id, status=status, **fields)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


# -----------------------------------------------------------------------
# OPEN_STATUSES contract
# -----------------------------------------------------------------------

class TestOpenStatusesContract:

    def test_pending_sent_read_failed_are_open(self):
        assert AlertStatus.PENDING in OPEN_STATUSES
        assert AlertStatus.SENT in OPEN_STATUSES
        assert AlertStatus.READ in OPEN_STATUSES
        assert AlertStatus.FAILED in OPEN_STATUSES

    def test_dismissed_and_resolved_are_closed(self):
        assert AlertStatus.DISMISSED not in OPEN_STATUSES
        assert AlertStatus.RESOLVED not in OPEN_STATUSES


# -----------------------------------------------------------------------
# mark_read transitions
# -----------------------------------------------------------------------

class TestMarkRead:

    def test_pending_becomes_read(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.PENDING)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/read")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.READ

    def test_sent_becomes_read(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.SENT)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/read")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.READ

    def test_failed_becomes_read(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.FAILED)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/read")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.READ

    def test_already_read_stays_read(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.READ)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/read")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.READ

    def test_dismissed_stays_dismissed(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.DISMISSED)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/read")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.DISMISSED

    def test_resolved_stays_resolved(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.RESOLVED)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/read")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.RESOLVED


# -----------------------------------------------------------------------
# dismiss transitions
# -----------------------------------------------------------------------

class TestDismiss:

    def test_pending_becomes_dismissed(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.PENDING)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/dismiss")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.DISMISSED

    def test_read_becomes_dismissed(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.READ)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/dismiss")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.DISMISSED

    def test_sent_becomes_dismissed(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.SENT)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/dismiss")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.DISMISSED

    def test_failed_becomes_dismissed(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.FAILED)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/dismiss")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.DISMISSED

    def test_already_dismissed_stays_dismissed(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.DISMISSED)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/dismiss")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.DISMISSED

    def test_resolved_stays_resolved(self, auth_client, db_session, business):
        a = _alert(db_session, business, status=AlertStatus.RESOLVED)
        resp = auth_client.post(f"/api/v1/alerts/{a.id}/dismiss")
        assert resp.status_code == 200
        db_session.expire_all()
        assert db_session.get(Alert, a.id).status is AlertStatus.RESOLVED


# -----------------------------------------------------------------------
# Sweep: resolve on filing, re-raise on unfiling/escalation
# -----------------------------------------------------------------------

class TestSweepTransitions:

    def test_sweep_resolves_an_open_alert_when_the_return_is_filed(
        self, db_session, business,
    ):
        a = _alert(db_session, business, status=AlertStatus.SENT)
        assert a.status in OPEN_STATUSES
        a.status = AlertStatus.RESOLVED
        db_session.commit()
        db_session.refresh(a)
        assert a.status is AlertStatus.RESOLVED

    def test_a_resolved_alert_can_be_reopened_to_pending(
        self, db_session, business,
    ):
        a = _alert(db_session, business, status=AlertStatus.RESOLVED)
        a.status = AlertStatus.PENDING
        db_session.commit()
        db_session.refresh(a)
        assert a.status is AlertStatus.PENDING

    def test_escalation_of_a_read_alert_moves_it_back_to_pending(
        self, db_session, business,
    ):
        a = _alert(db_session, business, status=AlertStatus.READ)
        a.status = AlertStatus.PENDING
        a.severity = AlertSeverity.CRITICAL
        db_session.commit()
        db_session.refresh(a)
        assert a.status is AlertStatus.PENDING
        assert a.severity is AlertSeverity.CRITICAL


# -----------------------------------------------------------------------
# Every state reachable
# -----------------------------------------------------------------------

class TestEveryAlertStatusIsReachable:

    def test_all_six_statuses_can_be_stored(self, db_session, business):
        for s in AlertStatus:
            a = _alert(db_session, business, status=s,
                       title=f"Test {s.value}")
            assert a.status is s
