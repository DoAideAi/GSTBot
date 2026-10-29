"""Emailing the alerts the sweep raises: who gets one, and what it changes.

Every test drives :func:`send_pending_alerts` directly against a real (SQLite)
session, and stands in for the SMTP server by monkeypatching
``app.services.alert_delivery.send_email`` — the module-level name the service
imported, not the one on ``email_sender``, since that is the one a call inside
this module actually resolves.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import event

from app.core.config import settings
from app.core.security import hash_password
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.business import Business
from app.models.user import User
from app.services import alert_delivery
from app.services.alert_delivery import send_pending_alerts
from app.services.email_sender import EmailSendError
from app.services.gstin import compute_check_digit
from tests.conftest import BUSINESS_GSTIN

NOW = datetime(2026, 5, 14, 7, 15)


def _valid_gstin(index: int) -> str:
    """A distinct checksum-valid GSTIN, for the tests that need many tenants."""
    # 2 state + 10 PAN (5 letters, 4 digits, 1 letter) + 1 entity + "Z" = 14.
    first14 = f"27AAGCB{7000 + index:04d}J1Z"
    return first14 + compute_check_digit(first14)


def make_business(db, *, gstin=BUSINESS_GSTIN, **kwargs) -> Business:
    business = Business(
        gstin=gstin,
        legal_name="Umang Traders Private Limited",
        state_code=gstin[:2],
        **kwargs,
    )
    db.add(business)
    db.commit()
    db.refresh(business)
    return business


def make_user(db, business, *, email="owner@example.com", is_active=True) -> User:
    user = User(
        business_id=business.id,
        email=email,
        hashed_password=hash_password("correct horse battery staple"),
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_alert(
    db,
    business,
    *,
    status=AlertStatus.PENDING,
    title="GSTR-1 for 2026-04 is overdue",
    message="GSTR-1 for 2026-04 was due on 2026-05-11.",
    due_date=date(2026, 5, 11),
) -> Alert:
    alert = Alert(
        business_id=business.id,
        alert_type=AlertType.FILING_DEADLINE,
        status=status,
        title=title,
        message=message,
        due_date=due_date,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@pytest.fixture(autouse=True)
def _email_enabled(monkeypatch):
    """The configuration every test starts from: on, and a relay named."""
    monkeypatch.setattr(settings, "alerts_email_enabled", True)
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")


@pytest.fixture()
def sent(monkeypatch):
    """Replace the SMTP call with a recorder; sends succeed unless told otherwise."""
    calls: list[dict] = []

    def fake_send_email(*, to, subject, body):
        calls.append({"to": to, "subject": subject, "body": body})

    monkeypatch.setattr(alert_delivery, "send_email", fake_send_email)
    return calls


@pytest.fixture()
def business(db_session) -> Business:
    return make_business(db_session)


class TestWhenEmailIsNotConfigured:
    def test_disabled_entirely_sends_nothing(self, db_session, business, sent, monkeypatch):
        monkeypatch.setattr(settings, "alerts_email_enabled", False)
        make_user(db_session, business)
        alert = make_alert(db_session, business)

        result = send_pending_alerts(db_session, now=NOW)

        assert sent == []
        assert result.businesses == 0
        db_session.refresh(alert)
        assert alert.channel is None
        assert alert.sent_at is None
        assert alert.status is AlertStatus.PENDING

    def test_enabled_with_no_relay_named_sends_nothing(
        self, db_session, business, sent, monkeypatch
    ):
        monkeypatch.setattr(settings, "smtp_host", "")
        make_user(db_session, business)
        make_alert(db_session, business)

        result = send_pending_alerts(db_session, now=NOW)

        assert sent == []
        assert result == alert_delivery.AlertEmailResult()


class TestASuccessfulSend:
    def test_one_email_covers_every_open_alert_for_the_business(
        self, db_session, business, sent
    ):
        make_user(db_session, business)
        make_alert(db_session, business, title="GSTR-1 for 2026-04 is overdue")
        make_alert(
            db_session,
            business,
            title="GSTR-3B for 2026-04 is due in 6 days",
            due_date=date(2026, 5, 20),
        )

        result = send_pending_alerts(db_session, now=NOW)

        assert len(sent) == 1
        assert "GSTR-1 for 2026-04 is overdue" in sent[0]["body"]
        assert "GSTR-3B for 2026-04 is due in 6 days" in sent[0]["body"]
        assert result.businesses == 1
        assert result.emails_sent == 1
        assert result.alerts_sent == 2

    def test_the_subject_counts_the_alerts_it_covers(self, db_session, business, sent):
        make_user(db_session, business)
        make_alert(db_session, business)
        make_alert(db_session, business, title="Second alert", due_date=date(2026, 5, 20))

        send_pending_alerts(db_session, now=NOW)

        assert sent[0]["subject"] == "2 GST alerts need your attention"

    def test_a_single_alert_gets_a_singular_subject(self, db_session, business, sent):
        make_user(db_session, business)
        make_alert(db_session, business)

        send_pending_alerts(db_session, now=NOW)

        assert sent[0]["subject"] == "1 GST alert needs your attention"

    def test_sent_alerts_are_stamped_and_marked_sent(self, db_session, business, sent):
        make_user(db_session, business)
        alert = make_alert(db_session, business)

        send_pending_alerts(db_session, now=NOW)

        db_session.refresh(alert)
        assert alert.channel == "email"
        assert alert.sent_at == NOW
        assert alert.status is AlertStatus.SENT

    def test_every_active_user_is_emailed(self, db_session, business, sent):
        make_user(db_session, business, email="owner@example.com")
        make_user(db_session, business, email="accountant@example.com")
        make_alert(db_session, business)

        send_pending_alerts(db_session, now=NOW)

        assert {call["to"] for call in sent} == {
            "owner@example.com",
            "accountant@example.com",
        }

    def test_an_inactive_user_is_not_emailed(self, db_session, business, sent):
        make_user(db_session, business, email="owner@example.com")
        make_user(db_session, business, email="ex-employee@example.com", is_active=False)
        make_alert(db_session, business)

        send_pending_alerts(db_session, now=NOW)

        assert {call["to"] for call in sent} == {"owner@example.com"}

    def test_the_clock_is_read_when_no_now_is_given(self, db_session, business, sent):
        make_user(db_session, business)
        alert = make_alert(db_session, business)

        send_pending_alerts(db_session)

        db_session.refresh(alert)
        assert alert.sent_at is not None


class TestWhatIsExcluded:
    def test_a_read_alert_is_not_emailed(self, db_session, business, sent):
        make_user(db_session, business)
        alert = make_alert(db_session, business, status=AlertStatus.READ)

        result = send_pending_alerts(db_session, now=NOW)

        assert sent == []
        assert result.businesses == 0
        db_session.refresh(alert)
        assert alert.channel is None

    def test_a_dismissed_alert_is_not_emailed(self, db_session, business, sent):
        make_user(db_session, business)
        make_alert(db_session, business, status=AlertStatus.DISMISSED)

        send_pending_alerts(db_session, now=NOW)

        assert sent == []

    def test_a_resolved_alert_is_not_emailed(self, db_session, business, sent):
        make_user(db_session, business)
        make_alert(db_session, business, status=AlertStatus.RESOLVED)

        send_pending_alerts(db_session, now=NOW)

        assert sent == []

    def test_a_deleted_alert_is_not_emailed(self, db_session, business, sent):
        make_user(db_session, business)
        alert = make_alert(db_session, business)
        alert.deleted_at = NOW
        db_session.commit()

        send_pending_alerts(db_session, now=NOW)

        assert sent == []

    def test_a_deactivated_business_is_skipped(self, db_session, business, sent):
        make_user(db_session, business)
        make_alert(db_session, business)
        business.is_active = False
        db_session.commit()

        result = send_pending_alerts(db_session, now=NOW)

        assert sent == []
        assert result.businesses == 0

    def test_a_business_with_no_users_is_counted_as_skipped_not_sent(
        self, db_session, business, sent
    ):
        make_alert(db_session, business)

        result = send_pending_alerts(db_session, now=NOW)

        assert sent == []
        assert result.businesses == 0
        assert result.skipped_no_recipient == 1


class TestAlertsThatVanishBetweenTheTwoQueries:
    """``send_pending_alerts`` asks twice: once for the business ids that have
    something outstanding, then once per business for the alerts themselves.
    The sweep, the alerts API and a tenant deletion all write to the same rows
    from other connections, so the two answers are not guaranteed to agree —
    a business can be named by the first query and have nothing left by the
    second. The guard for that is unreachable from ordinary fixtures, because
    fixtures cannot write in the gap between two statements one function issues
    back to back. A cursor-level listener can.
    """

    @pytest.fixture()
    def vanish_after_the_scan(self, db_session):
        """Hand back a way to soft-delete alerts the instant the id scan runs.

        Call it with the business ids whose alerts should be gone by the time
        the per-business fetch asks for them; call it with none for all of
        them. Hooked to the ``DISTINCT`` scan specifically and fired once —
        the statement after it is the one whose answer this is meant to
        change, and re-firing there would only be a second no-op write.

        The ``UPDATE`` goes through a second cursor on the same DBAPI
        connection rather than the one SQLAlchemy is holding, which still has
        the scan's rows to hand back.
        """
        fired: list[str] = []
        bind = db_session.get_bind()
        listeners: list = []

        def arm(*business_ids: int):
            where = ""
            if business_ids:
                ids = ", ".join(str(int(i)) for i in business_ids)
                where = f" WHERE business_id IN ({ids})"

            def _soft_delete_mid_flight(
                conn, cursor, statement, parameters, context, executemany
            ):
                if fired or "DISTINCT" not in statement:
                    return
                fired.append(statement)
                writer = conn.connection.cursor()
                try:
                    writer.execute(
                        f"UPDATE alerts SET deleted_at = '2026-05-14 07:15:00'{where}"
                    )
                finally:
                    writer.close()

            event.listen(bind, "after_cursor_execute", _soft_delete_mid_flight)
            listeners.append(_soft_delete_mid_flight)
            return fired

        try:
            yield arm
        finally:
            for listener in listeners:
                event.remove(bind, "after_cursor_execute", listener)

    def test_a_business_whose_alerts_are_gone_by_the_second_query_is_skipped(
        self, db_session, business, sent, vanish_after_the_scan
    ):
        make_user(db_session, business)
        make_alert(db_session, business)
        fired = vanish_after_the_scan()

        result = send_pending_alerts(db_session, now=NOW)

        # The scan did name the business - without this the test proves
        # nothing about the guard, only that an empty table sends no email.
        assert fired, "the DISTINCT scan never ran"
        assert sent == []
        assert result == alert_delivery.AlertEmailResult()

    def test_the_business_whose_alerts_survived_still_gets_its_digest(
        self, db_session, sent, vanish_after_the_scan
    ):
        """The skip is a ``continue``, not a ``return``.

        A row disappearing under one business says nothing about the next one
        in the scan, and ending the run there would silently cost every
        business after it today's send - the same failure the per-business
        commit exists to rule out.
        """
        first = make_business(db_session, gstin=BUSINESS_GSTIN)
        second = make_business(db_session, gstin="29AABCU9603R1ZM")
        make_user(db_session, first, email="first@example.com")
        make_user(db_session, second, email="second@example.com")
        make_alert(db_session, first)
        second_alert = make_alert(db_session, second)
        vanish_after_the_scan(first.id)

        result = send_pending_alerts(db_session, now=NOW)

        assert [call["to"] for call in sent] == ["second@example.com"]
        assert result.businesses == 1
        assert result.alerts_sent == 1
        db_session.refresh(second_alert)
        assert second_alert.status is AlertStatus.SENT


class TestARelayFailure:
    def test_every_recipient_failing_marks_the_alerts_failed_not_sent(
        self, db_session, business, monkeypatch
    ):
        make_user(db_session, business)
        alert = make_alert(db_session, business)

        def always_fails(*, to, subject, body):
            raise EmailSendError("relay unreachable")

        monkeypatch.setattr(alert_delivery, "send_email", always_fails)

        result = send_pending_alerts(db_session, now=NOW)

        db_session.refresh(alert)
        assert alert.channel == "email"
        assert alert.sent_at is None
        assert alert.status is AlertStatus.FAILED
        assert result.alerts_failed == 1
        assert result.alerts_sent == 0

    def test_a_previously_failed_alert_is_retried_the_next_run(
        self, db_session, business, sent
    ):
        make_user(db_session, business)
        alert = make_alert(db_session, business, status=AlertStatus.FAILED)

        send_pending_alerts(db_session, now=NOW)

        db_session.refresh(alert)
        assert alert.status is AlertStatus.SENT
        assert len(sent) == 1

    def test_one_recipient_failing_does_not_stop_another_from_being_reached(
        self, db_session, business, monkeypatch
    ):
        make_user(db_session, business, email="bad@example.com")
        make_user(db_session, business, email="good@example.com")
        alert = make_alert(db_session, business)

        def selective(*, to, subject, body):
            if to == "bad@example.com":
                raise EmailSendError("mailbox does not exist")

        monkeypatch.setattr(alert_delivery, "send_email", selective)

        send_pending_alerts(db_session, now=NOW)

        db_session.refresh(alert)
        assert alert.status is AlertStatus.SENT
        assert alert.sent_at == NOW


class TestAnUnexpectedSendFailure:
    """``send_email`` promises to raise only :class:`EmailSendError` — see its
    own docstring — but a misconfigured relay does not keep every promise: an
    SMTP username set with no password makes ``smtplib.SMTP.login`` raise
    ``AttributeError``, not ``SMTPException``. Nothing about that is specific
    to one tenant, so it must not be allowed to behave as if it were.
    """

    def test_one_businesss_broken_config_does_not_stop_the_next_business(
        self, db_session, monkeypatch
    ):
        first = make_business(db_session, gstin=BUSINESS_GSTIN)
        second = make_business(db_session, gstin="29AABCU9603R1ZM")
        make_user(db_session, first, email="first@example.com")
        make_user(db_session, second, email="second@example.com")
        first_alert = make_alert(db_session, first)
        second_alert = make_alert(db_session, second)

        def broken_for_first(*, to, subject, body):
            if to == "first@example.com":
                raise AttributeError("'NoneType' object has no attribute 'encode'")

        monkeypatch.setattr(alert_delivery, "send_email", broken_for_first)

        result = send_pending_alerts(db_session, now=NOW)

        db_session.refresh(first_alert)
        db_session.refresh(second_alert)
        # The broken business is rolled back and its alerts left exactly as
        # the sweep found them, but it still counts in the result so the
        # summary log and the Celery task see the true number of failures.
        assert first_alert.status is AlertStatus.PENDING
        assert first_alert.channel is None
        # The second business is unaffected by the first one's crash.
        assert second_alert.status is AlertStatus.SENT
        assert second_alert.sent_at == NOW
        assert result.businesses == 2
        assert result.emails_sent == 1
        assert result.alerts_failed == 1


class TestAcrossSeveralBusinesses:
    def test_each_business_gets_its_own_digest(self, db_session, sent):
        first = make_business(db_session, gstin=BUSINESS_GSTIN)
        second = make_business(db_session, gstin="29AABCU9603R1ZM")
        make_user(db_session, first, email="first@example.com")
        make_user(db_session, second, email="second@example.com")
        make_alert(db_session, first)
        make_alert(db_session, second)

        result = send_pending_alerts(db_session, now=NOW)

        assert result.businesses == 2
        assert {call["to"] for call in sent} == {"first@example.com", "second@example.com"}

    def test_a_business_with_nothing_open_is_left_alone(self, db_session, sent):
        first = make_business(db_session, gstin=BUSINESS_GSTIN)
        second = make_business(db_session, gstin="29AABCU9603R1ZM")
        make_user(db_session, first, email="first@example.com")
        make_user(db_session, second, email="second@example.com")
        make_alert(db_session, first)
        # second has no alerts at all — should generate no query result for it.

        result = send_pending_alerts(db_session, now=NOW)

        assert result.businesses == 1
        assert len(sent) == 1

    def test_no_read_at_all_grows_with_the_number_of_tenants(self, db_session, sent):
        """Not the business, not its recipients, and not the alerts either.

        This is the one caller in the product that deliberately loops over
        every tenant at once, so a per-tenant read here is multiplied by the
        whole customer list rather than by anything about the work. Three of
        them were: ``db.get(Business, ...)`` per id, ``business.users`` inside
        ``_recipients``, which is a lazy relationship and so a second
        statement again, and the digest's own fetch of the alerts.

        The last of those was left in deliberately once, on the grounds that
        it was the unit the per-tenant commit isolates. It is not — the commit
        isolates the *send and the write*, which are still one tenant at a
        time. A SELECT that fails fails the run wherever it sits, so hoisting
        it costs nothing and it is now hoisted, leaving no read in this module
        that scales with the customer list.
        """

        def _reads_for(tenant_count: int, first_gstin: int) -> int:
            db_session.query(Alert).delete()
            db_session.query(User).delete()
            db_session.query(Business).delete()
            db_session.commit()
            for index in range(first_gstin, first_gstin + tenant_count):
                tenant = make_business(db_session, gstin=_valid_gstin(index))
                make_user(db_session, tenant, email=f"owner-{index}@example.com")
                make_alert(db_session, tenant)

            # The sweep runs in a worker with a session of its own. Left in the
            # identity map, the rows just written answer the lazy loads with no
            # SQL at all, and the N+1 is invisible here.
            db_session.expunge_all()

            reads: list[str] = []

            def _record(conn, cursor, statement, parameters, context, executemany):
                squashed = " ".join(statement.split()).lower()
                if squashed.startswith("select") and (
                    "from businesses" in squashed
                    or "from users" in squashed
                    or "from alerts" in squashed
                ):
                    reads.append(squashed)

            engine = db_session.get_bind()
            event.listen(engine, "before_cursor_execute", _record)
            try:
                result = send_pending_alerts(db_session, now=NOW)
            finally:
                event.remove(engine, "before_cursor_execute", _record)

            assert result.businesses == tenant_count
            return len(reads)

        at_three = _reads_for(3, first_gstin=0)
        at_fifteen = _reads_for(15, first_gstin=100)
        assert at_three == at_fifteen, (
            f"{at_three} reads of businesses/users/alerts for three tenants, "
            f"{at_fifteen} for fifteen: the sweep is reading per tenant."
        )

    def test_the_per_business_commit_does_not_re_read_the_alerts_one_by_one(
        self, db_session, sent
    ):
        """The trap the prefetch had to avoid, asserted rather than assumed.

        ``db.commit()`` at the end of each tenant expires every ORM instance in
        the session. Had the alerts been prefetched as ``Alert`` objects, the
        first commit would have expired the rest, and composing the *next*
        tenant's digest would re-read every one of them attribute by attribute
        — one statement per alert, which is worse than the per-tenant read the
        prefetch replaced. Reading columns into ``Row``s is what rules that
        out, and nothing about that choice is self-evident from the call.

        So: hold the tenant count still and grow the alerts instead. The
        per-tenant version of this bug is invisible that way; only the
        per-instance one moves the number.
        """

        def _reads_for(alerts_each: int, first_gstin: int) -> int:
            db_session.query(Alert).delete()
            db_session.query(User).delete()
            db_session.query(Business).delete()
            db_session.commit()
            # Three tenants throughout, so every commit but the last is
            # followed by more digest-composing work to expire.
            for index in range(first_gstin, first_gstin + 3):
                tenant = make_business(db_session, gstin=_valid_gstin(index))
                make_user(db_session, tenant, email=f"owner-{index}@example.com")
                for _ in range(alerts_each):
                    make_alert(db_session, tenant)
            db_session.expunge_all()

            reads: list[str] = []

            def _record(conn, cursor, statement, parameters, context, executemany):
                squashed = " ".join(statement.split()).lower()
                if squashed.startswith("select") and "from alerts" in squashed:
                    reads.append(squashed)

            engine = db_session.get_bind()
            event.listen(engine, "before_cursor_execute", _record)
            try:
                result = send_pending_alerts(db_session, now=NOW)
            finally:
                event.remove(engine, "before_cursor_execute", _record)

            assert result.alerts_sent == 3 * alerts_each
            return len(reads)

        at_one = _reads_for(1, first_gstin=200)
        at_eight = _reads_for(8, first_gstin=300)
        assert at_one == at_eight, (
            f"{at_one} reads of alerts at one alert per tenant, {at_eight} at eight: "
            "the digest is going back to the database for rows the commit expired."
        )


class TestAnAlertResolvedBetweenReadAndWrite:
    """The prefetch reads PENDING alerts; the sweep or a user action can
    resolve one before the UPDATE stamps it SENT.  Without a status guard
    the UPDATE overwrites RESOLVED with SENT, reopening a closed alert.
    """

    @pytest.fixture()
    def resolve_before_the_stamp(self, db_session):
        """Resolve an alert the instant the UPDATE is about to fire."""
        fired: list[str] = []
        bind = db_session.get_bind()
        listeners: list = []

        def arm(alert_id: int):
            def _resolve_mid_flight(
                conn, cursor, statement, parameters, context, executemany
            ):
                if fired or "UPDATE" not in statement.upper():
                    return
                fired.append(statement)
                writer = conn.connection.cursor()
                try:
                    writer.execute(
                        f"UPDATE alerts SET status = 'RESOLVED' WHERE id = {int(alert_id)}"
                    )
                finally:
                    writer.close()

            event.listen(bind, "before_cursor_execute", _resolve_mid_flight)
            listeners.append(_resolve_mid_flight)
            return fired

        try:
            yield arm
        finally:
            for listener in listeners:
                event.remove(bind, "before_cursor_execute", listener)

    def test_a_resolved_alert_is_not_overwritten_with_sent(
        self, db_session, business, sent, resolve_before_the_stamp
    ):
        make_user(db_session, business)
        alert = make_alert(db_session, business)
        resolve_before_the_stamp(alert.id)

        send_pending_alerts(db_session, now=NOW)

        db_session.refresh(alert)
        assert alert.status is AlertStatus.RESOLVED, (
            "the email sender overwrote a concurrently resolved alert"
        )


def test_the_result_is_json_serialisable_for_the_task_backend():
    assert alert_delivery.AlertEmailResult(businesses=1, emails_sent=1).as_dict() == {
        "businesses": 1,
        "emails_sent": 1,
        "alerts_sent": 0,
        "alerts_failed": 0,
        "skipped_no_recipient": 0,
    }


class TestTheAccountantWhoFilesIsTold:
    """P38 M10: a CA who linked a client's business never got its deadlines.

    The digest went to ``business.users``, the logins whose own business it is.
    Someone who files for a business reaches it through a link
    (``/businesses/mine/link``), a membership row rather than a user of that
    business, so they got none of its deadline mail, although the recipient
    rule says the accountant "is exactly who should hear about a deadline they
    may be the one filing". Linked logins that can act on an alert (owner and
    accountant links, still live, on an active login) now get it. Viewers
    cannot file and are left out, as is a link someone has removed.
    """

    def _link(self, db, business, *, email, role, removed=False, active=True):
        from app.models.business_membership import BusinessMembership, MembershipRole
        from app.models.mixins import utcnow

        self.homes = getattr(self, "homes", 0) + 1
        home = make_business(db, gstin=_valid_gstin(500 + self.homes))
        user = make_user(db, home, email=email, is_active=active)
        db.add(
            BusinessMembership(
                user_id=user.id,
                business_id=business.id,
                role=MembershipRole(role),
                deleted_at=utcnow() if removed else None,
            )
        )
        db.commit()

    def test_linked_logins_that_can_file_are_emailed_and_no_one_else(
        self, db_session, business, sent
    ):
        make_user(db_session, business, email="owner@example.com")
        self._link(db_session, business, email="ca@firm.example", role="accountant")
        self._link(db_session, business, email="partner@firm.example", role="owner")
        self._link(db_session, business, email="viewer@firm.example", role="viewer")
        self._link(db_session, business, email="gone@firm.example", role="accountant",
                   removed=True)
        self._link(db_session, business, email="left@firm.example", role="accountant",
                   active=False)
        make_alert(db_session, business)

        send_pending_alerts(db_session, now=NOW)

        assert {call["to"] for call in sent} == {
            "owner@example.com",
            "ca@firm.example",
            "partner@firm.example",
        }
