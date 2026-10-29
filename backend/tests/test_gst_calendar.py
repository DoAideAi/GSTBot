"""Return due dates: the day, the rollover, and the return that has none.

These dates decide whether an alert fires and whether a supplier is scored as
late, so they are asserted against literal dates rather than against a
recomputation of the same arithmetic — a test that rebuilds the rule agrees
with the bug.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.models.gstr_return import ReturnType
from app.services import gst_calendar


class TestTheDayEachReturnIsDue:
    def test_gstr1_is_due_on_the_eleventh_of_the_following_month(self):
        assert gst_calendar.gstr1_due_date("2026-04") == date(2026, 5, 11)

    def test_gstr3b_is_due_on_the_twentieth_of_the_following_month(self):
        assert gst_calendar.gstr3b_due_date("2026-04") == date(2026, 5, 20)

    def test_the_two_returns_for_one_period_are_nine_days_apart(self):
        # The gap is the whole reason both are tracked: a business that has
        # filed its GSTR-1 is not done, and the 3B is the one with the penalty.
        gap = gst_calendar.gstr3b_due_date("2026-04") - gst_calendar.gstr1_due_date("2026-04")
        assert gap.days == 9


class TestTheDecemberRollover:
    """A December period is due in the next calendar year."""

    def test_gstr1_for_december_is_due_in_january(self):
        assert gst_calendar.gstr1_due_date("2026-12") == date(2027, 1, 11)

    def test_gstr3b_for_december_is_due_in_january(self):
        assert gst_calendar.gstr3b_due_date("2026-12") == date(2027, 1, 20)

    def test_november_does_not_roll_over(self):
        # The boundary either side of it, so an off-by-one in the month test
        # cannot pass by rolling everything.
        assert gst_calendar.gstr3b_due_date("2026-11") == date(2026, 12, 20)

    def test_next_period_rolls_the_year_at_december(self):
        assert gst_calendar.next_period("2026-12") == "2027-01"

    def test_next_period_pads_a_single_digit_month(self):
        # "2026-9" would compare wrong against every other period string in
        # the product, all of which are zero-padded.
        assert gst_calendar.next_period("2026-08") == "2026-09"


class TestTodayIsAnIndianDate:
    def test_ist_is_five_and_a_half_hours_ahead_of_utc(self):
        assert gst_calendar.IST.utcoffset(None) == timedelta(hours=5, minutes=30)

    def test_today_is_read_in_india_rather_than_in_utc(self):
        # Between 18:30 and 24:00 UTC these two differ, and it is the Indian
        # one that decides whether a return is late. A server on UTC would
        # otherwise call a return on time for five and a half hours after the
        # penalty started running.
        assert gst_calendar.today_ist() == gst_calendar.ist_date(
            datetime.now(UTC)
        )


class TestWhichPeriodsHaveEnded:
    def test_the_month_in_progress_is_excluded(self):
        # A return covers a whole month and the portal does not open it until
        # the month is over, so asking for one is asking about sales that have
        # not happened yet.
        assert "2026-06" not in gst_calendar.completed_periods(date(2026, 6, 15), 6)

    def test_they_come_back_newest_first(self):
        assert gst_calendar.completed_periods(date(2026, 6, 15), 3) == [
            "2026-05",
            "2026-04",
            "2026-03",
        ]

    def test_the_walk_backwards_crosses_a_year_boundary(self):
        assert gst_calendar.completed_periods(date(2026, 2, 1), 3) == [
            "2026-01",
            "2025-12",
            "2025-11",
        ]

    def test_the_first_of_the_month_still_excludes_that_month(self):
        # The boundary: on 1 June nothing about June has happened, but May has
        # just become filable.
        assert gst_calendar.completed_periods(date(2026, 6, 1), 1) == ["2026-05"]

    def test_previous_period_rolls_the_year_at_january(self):
        assert gst_calendar.previous_period("2026-01") == "2025-12"


class TestTheFirstDayOfAPeriod:
    """``period_start`` — where a period's window opens.

    Needed alongside ``period_end`` to decide which month a rule fired in:
    Rule 37's 180 days run out on one particular day, and that day's month is
    the return the reversal belongs to.
    """

    def test_it_is_the_first_of_the_named_month(self):
        assert gst_calendar.period_start("2026-04") == date(2026, 4, 1)

    def test_january(self):
        assert gst_calendar.period_start("2026-01") == date(2026, 1, 1)

    def test_december(self):
        assert gst_calendar.period_start("2026-12") == date(2026, 12, 1)

    def test_it_is_the_day_after_the_previous_period_ends(self):
        for period in ("2025-11", "2026-01", "2026-03", "2026-12"):
            previous = gst_calendar.previous_period(period)
            assert gst_calendar.period_start(period) == gst_calendar.period_end(
                previous
            ) + timedelta(days=1)

    def test_the_two_ends_bracket_the_period_and_nothing_else(self):
        for period in ("2026-02", "2026-04", "2028-02"):
            start = gst_calendar.period_start(period)
            end = gst_calendar.period_end(period)
            assert start <= end
            assert gst_calendar.period_of(start) == period
            assert gst_calendar.period_of(end) == period
            assert gst_calendar.period_of(start - timedelta(days=1)) != period
            assert gst_calendar.period_of(end + timedelta(days=1)) != period


class TestTheLastDayOfAPeriod:
    """``period_end`` — the day a return for that period is a statement about."""

    def test_a_thirty_one_day_month(self):
        assert gst_calendar.period_end("2026-01") == date(2026, 1, 31)

    def test_a_thirty_day_month(self):
        assert gst_calendar.period_end("2026-04") == date(2026, 4, 30)

    def test_february_in_a_common_year(self):
        assert gst_calendar.period_end("2026-02") == date(2026, 2, 28)

    def test_february_in_a_leap_year(self):
        assert gst_calendar.period_end("2028-02") == date(2028, 2, 29)

    def test_february_in_the_century_that_is_not_a_leap_year(self):
        assert gst_calendar.period_end("2100-02") == date(2100, 2, 28)

    def test_december_does_not_roll_into_month_thirteen(self):
        assert gst_calendar.period_end("2026-12") == date(2026, 12, 31)

    def test_it_is_the_day_before_the_next_period_opens(self):
        for period in ("2025-11", "2026-02", "2026-06", "2026-12"):
            year, month = (int(part) for part in gst_calendar.next_period(period).split("-"))
            assert gst_calendar.period_end(period) == date(year, month, 1) - timedelta(days=1)

    def test_it_falls_inside_the_period_it_names(self):
        for period in ("2024-02", "2026-04", "2026-12"):
            assert gst_calendar.period_of(gst_calendar.period_end(period)) == period

    def test_it_is_before_every_due_date_for_that_period(self):
        """A return covers a month that has closed before it may be filed."""
        for period in ("2026-01", "2026-04", "2026-12"):
            assert gst_calendar.period_end(period) < gst_calendar.gstr1_due_date(period)
            assert gst_calendar.period_end(period) < gst_calendar.gstr3b_due_date(period)


class TestCountingBackWholeYears:
    """``months_before`` — the five-year window Rule 43 spreads credit over."""

    def test_no_months_back_is_the_period_itself(self):
        assert gst_calendar.months_before("2026-04", 0) == "2026-04"

    def test_it_agrees_with_previous_period_one_step_out(self):
        for period in ("2026-04", "2026-01", "2026-12"):
            assert gst_calendar.months_before(period, 1) == gst_calendar.previous_period(
                period
            )

    def test_it_crosses_the_january_boundary_without_landing_on_month_zero(self):
        # Three back from March is December, not "2026-00" — the off-by-one a
        # modulo over 1..12 rather than 0..11 would produce.
        assert gst_calendar.months_before("2026-03", 3) == "2025-12"
        assert gst_calendar.months_before("2026-03", 4) == "2025-11"

    def test_a_whole_year_back_keeps_the_month(self):
        assert gst_calendar.months_before("2026-07", 12) == "2025-07"

    def test_it_spans_the_fifty_nine_months_rule_43_needs(self):
        # A capital good bought in May 2021 is in its sixtieth and final
        # instalment in April 2026.
        assert gst_calendar.months_before("2026-04", 59) == "2021-05"

    def test_it_agrees_with_repeated_single_steps(self):
        period = "2026-04"
        for step in range(1, 61):
            period = gst_calendar.previous_period(period)
            assert gst_calendar.months_before("2026-04", step) == period

    def test_the_result_sorts_as_a_calendar(self):
        # The window is compared with ``<=`` against stored periods, so string
        # order has to be calendar order across the year boundary.
        assert gst_calendar.months_before("2026-01", 1) < "2026-01"
        assert gst_calendar.months_before("2026-01", 1) < "2026-10"

    def test_a_negative_count_walks_forward(self):
        assert gst_calendar.months_before("2026-12", -1) == "2027-01"


class TestDispatchingOnReturnType:
    @pytest.mark.parametrize(
        ("return_type", "expected"),
        [
            (ReturnType.GSTR1, date(2026, 5, 11)),
            (ReturnType.GSTR3B, date(2026, 5, 20)),
        ],
    )
    def test_due_date_agrees_with_the_named_helper(self, return_type, expected):
        assert gst_calendar.due_date("2026-04", return_type) == expected

    def test_a_gstr2b_has_no_due_date(self):
        # The portal generates it; nobody files it, so it can never be late.
        # Returning some date anyway would put a deadline alert on the screen
        # for a return the business cannot act on.
        with pytest.raises(ValueError, match="not a return this business files"):
            gst_calendar.due_date("2026-04", ReturnType.GSTR2B)

    def test_every_filed_return_type_has_a_day(self):
        # DUE_DAY is what the alerting iterates. If a return type is added to
        # the model and not here, the deadline alerts silently stop covering
        # it — so the omission is asserted rather than discovered.
        assert set(gst_calendar.DUE_DAY) == {ReturnType.GSTR1, ReturnType.GSTR3B}


class TestWhatCountsAsAPeriod:
    """``\\d{4}-\\d{2}`` is not a period validator, and every route used it.

    It admits ``2026-00`` and ``2026-13``, and both reached arithmetic that
    assumes the month exists. ``next_period("2026-13")`` is ``2026-14``, which
    ``date()`` refuses — so a due date computed from a query string was a 500
    rather than the 422 a malformed one has earned. The values that did not
    raise were the worse half: ``2026-13`` built a GSTR-1 stamped ``fp=132026``
    and ``2026-00`` aliased quietly onto January, each of them a return
    document about a month that does not exist.
    """

    @pytest.mark.parametrize("period", ["2026-01", "2026-09", "2026-10", "2026-12"])
    def test_a_real_month_is_a_period(self, period):
        assert gst_calendar.is_period(period)

    @pytest.mark.parametrize("period", ["2026-00", "2026-13", "2026-99", "2026-1"])
    def test_a_month_outside_1_to_12_is_not(self, period):
        assert not gst_calendar.is_period(period)

    @pytest.mark.parametrize(
        "value", ["", "2026", "202604", "04-2026", "2026-04-01", "abcd-ef", None, 202604]
    )
    def test_anything_that_is_not_yyyy_mm_is_not(self, value):
        assert not gst_calendar.is_period(value)

    def test_the_pattern_is_anchored_at_both_ends(self):
        # Pydantic matches rather than fullmatches, so an unanchored pattern
        # would accept "2026-04junk" — and a trailing-garbage period reaches
        # the database as a string nothing else in the product will match.
        assert not gst_calendar.is_period("x2026-04")
        assert not gst_calendar.is_period("2026-04x")

    @pytest.mark.parametrize("period", ["2026-00", "2026-13", "2026-99"])
    def test_the_months_the_old_pattern_let_through_break_the_arithmetic(
        self, period
    ):
        # Why this is validated at the edge rather than defended against
        # everywhere downstream: the arithmetic cannot give a sensible answer,
        # so the only place to say no is before it is reached.
        assert not gst_calendar.is_period(period)
        month = int(period.split("-")[1])
        if month in (13, 99):
            with pytest.raises(ValueError, match="month must be in 1..12"):
                gst_calendar.gstr3b_due_date(period)
        else:
            # 2026-00 does not raise, which is worse: it silently answers as
            # though the caller had asked about a month before January.
            assert gst_calendar.gstr3b_due_date(period) == date(2026, 1, 20)


class TestTheSpanAnInvoiceDateCanFallIn:
    """Both ends are typos, and both have the same consequence.

    The filing period is derived from the invoice date, so a date outside this
    span puts the invoice in a month no return will ever cover — which is why
    the two ends are one question rather than two checks.
    """

    def test_gst_commenced_on_the_first_of_july_2017(self):
        assert date(2017, 7, 1) == gst_calendar.GST_COMMENCEMENT

    def test_an_ordinary_date_is_inside_the_span(self):
        assert gst_calendar.is_filable_invoice_date(
            date(2026, 4, 15), today=date(2026, 5, 20)
        )

    def test_both_ends_are_inclusive(self):
        assert gst_calendar.is_filable_invoice_date(
            gst_calendar.GST_COMMENCEMENT, today=date(2026, 5, 20)
        )
        assert gst_calendar.is_filable_invoice_date(
            date(2026, 5, 20), today=date(2026, 5, 20)
        )

    def test_the_day_before_gst_is_outside_it(self):
        assert not gst_calendar.is_filable_invoice_date(
            gst_calendar.GST_COMMENCEMENT - timedelta(days=1), today=date(2026, 5, 20)
        )

    def test_tomorrow_is_outside_it(self):
        assert not gst_calendar.is_filable_invoice_date(
            date(2026, 5, 21), today=date(2026, 5, 20)
        )

    def test_today_defaults_to_the_indian_date(self):
        """Not the server's. A deadline product measures every day in IST."""
        assert gst_calendar.is_filable_invoice_date(gst_calendar.today_ist())
        assert not gst_calendar.is_filable_invoice_date(
            gst_calendar.today_ist() + timedelta(days=1)
        )


class TestTheSpanAPeriodCanFallIn:
    """The month check left both ends of the year wide open.

    ``\\d{4}`` reaches every year ``date()`` will construct and two it will not,
    because every question this module answers about a period is really about
    the month *next* to it. A due date is next month, so ``9999-12`` raised
    ``year must be in 1..9999, not 10000``; the previous period of ``0000-01``
    raised on the year before. Both arrived through a query string, and the
    dashboard asks for a GSTR-3B due date on every request — so the product's
    front page answered 500 to a seven-character URL parameter.

    The routes that did *not* raise are the worse half, exactly as they were
    when the month was unvalidated. ``9999-12`` built and exported a GSTR-1
    stamped ``fp=129999`` and the filing-validation screen called a return for
    the year 9999 ``ok: true`` — a document about a month that cannot exist,
    reported as safe to file.

    So the bound is the one an invoice date already had: a period is a month a
    return is filed for, and there is no return for a month before GST.
    """

    def test_the_span_starts_when_gst_commenced(self):
        commenced = gst_calendar.period_of(gst_calendar.GST_COMMENCEMENT)
        assert commenced == gst_calendar.FIRST_PERIOD

    @pytest.mark.parametrize(
        "period", ["2017-07", "2017-12", "2018-01", "2026-04", "2099-12"]
    )
    def test_a_month_a_return_covers_is_a_period(self, period):
        assert gst_calendar.is_period(period)

    @pytest.mark.parametrize(
        "period",
        [
            "2017-06",  # the month before GST commenced
            "2017-01",
            "2016-12",
            "1999-04",
            "0000-01",
            "0001-01",
            "2100-01",  # past the far end
            "9999-12",
        ],
    )
    def test_a_month_no_return_covers_is_not(self, period):
        assert not gst_calendar.is_period(period)

    def test_the_two_ends_are_the_ones_the_constants_name(self):
        # The constants exist to be quoted in an error message. If they drifted
        # from the pattern, the message would name a range that is not enforced.
        assert gst_calendar.is_period(gst_calendar.FIRST_PERIOD)
        assert gst_calendar.is_period(gst_calendar.LAST_PERIOD)
        assert not gst_calendar.is_period(
            gst_calendar.previous_period(gst_calendar.FIRST_PERIOD)
        )
        assert not gst_calendar.is_period(
            gst_calendar.next_period(gst_calendar.LAST_PERIOD)
        )

    @pytest.mark.parametrize("period", ["0000-01", "0001-01", "9999-12", "2100-01"])
    def test_the_years_the_old_pattern_let_through_break_the_arithmetic(self, period):
        # Why this is validated at the edge rather than defended against
        # downstream: there is no sensible due date for the month after
        # December 9999, so the only place to say no is before it is asked for.
        assert not gst_calendar.is_period(period)

    def test_every_period_the_pattern_accepts_has_a_due_date(self):
        """The invariant the 500 was a breach of.

        Nothing downstream re-checks a period, so ``is_period`` returning True
        is a promise that every function in this module will answer rather than
        raise. Walked over both ends of the span and both ends of the year,
        because the failures were all one month either side of a boundary.
        """
        for year in (2017, 2018, 2098, 2099):
            for month in range(1, 13):
                period = f"{year:04d}-{month:02d}"
                if not gst_calendar.is_period(period):
                    continue
                assert gst_calendar.gstr1_due_date(period)
                assert gst_calendar.gstr3b_due_date(period)
                assert gst_calendar.period_start(period)
                assert gst_calendar.period_end(period)
                assert gst_calendar.next_period(period)
                assert gst_calendar.previous_period(period)
                assert gst_calendar.months_before(period, 60)


class TestAPeriodIsSpelledInAsciiDigits:
    """``\\d`` in a pydantic or Python pattern also matches ``٦`` and ``６``.

    ``202٦-04`` used to pass every period parameter and was recorded as a
    filed GSTR-3B under that string, while April itself stayed unfiled.
    """

    @pytest.mark.parametrize("period", ["202٦-04", "202６-04", "२०२६-04"])
    def test_other_digits_are_not_a_period(self, period):
        assert not gst_calendar.is_period(period)

    def test_recording_one_is_refused(self, auth_client, db_session):
        from app.models.gstr_return import GSTRReturn

        response = auth_client.post("/api/v1/filing/gstr3b/filed", json={"period": "202٦-04"})

        assert response.status_code == 422
        assert db_session.query(GSTRReturn).count() == 0

    def test_the_gpt_patterns_refuse_them_too(self):
        from pydantic import ValidationError

        from app.schemas.gpt import InvoiceItem

        with pytest.raises(ValidationError):
            InvoiceItem(description="x", hsn_code="८४७१", quantity=1, unit_price=1, gst_rate=18)
