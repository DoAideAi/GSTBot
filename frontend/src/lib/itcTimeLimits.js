// Two clocks that take input tax credit away from a buyer who otherwise did
// everything right: section 16(4), which closes the window to claim it, and
// Rule 37, which takes it back when the supplier is not paid in 180 days.

import { calculateInterest, daysLate } from "./gstPenalties";

const round2 = (n) => Math.round(n * 100) / 100;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
  "August", "September", "October", "November", "December"];

function parseDay(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!m) return null;
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3]);
  // Date.UTC rolls 31 February into March and month 13 into January; a date
  // that moved was not a date.
  const d = new Date(t);
  return d.getUTCDate() === +m[3] && d.getUTCMonth() === +m[2] - 1 ? t : null;
}

const iso = (t) => new Date(t).toISOString().slice(0, 10);

export function addDays(day, n) {
  const t = parseDay(day);
  return t === null ? null : iso(t + n * 86400000);
}

/** "2026-11-30" → "30 November 2026". */
export function formatDay(day) {
  const t = parseDay(day);
  if (t === null) return "";
  const d = new Date(t);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/** Signed days from `from` to `to`: positive while `to` is ahead. */
function daysBetween(from, to) {
  const ahead = daysLate(from, to);
  return ahead > 0 ? ahead : -daysLate(to, from);
}

/** Financial year label for a date: 2026-02-10 → "2025-26". */
export function financialYear(day) {
  const t = parseDay(day);
  if (t === null) return null;
  const d = new Date(t);
  const start = d.getUTCMonth() >= 3 ? d.getUTCFullYear() : d.getUTCFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}

// FY 2017-18 to 2020-21: section 16(5), inserted by the Finance (No. 2) Act
// 2024 with effect from 1 July 2017, lets credit claimed in any return filed
// up to 30 November 2021 stand. Those years have no live window left, so the
// checker reports the 16(5) date rather than pretending the 30 November rule
// applies to them.
const SECTION_16_5_CUTOFF = "2021-11-30";
const FIRST_30_NOV_FY = 2021;

/**
 * Last day to claim ITC on an invoice or debit note under section 16(4):
 * 30 November after the end of the document's FY, or the day the annual
 * return for that FY was filed, if that came first. A debit note counts from
 * its own date, not the original invoice's, since the 2021 amendment.
 */
export function itcClaimWindow({ documentDate, annualReturnDate = "", today }) {
  const t = parseDay(documentDate);
  if (t === null) return null;
  if (annualReturnDate && parseDay(annualReturnDate) === null) return null;
  const fy = financialYear(documentDate);
  const fyStart = Number(fy.slice(0, 4));

  if (fyStart < FIRST_30_NOV_FY) {
    return { fy, deadline: SECTION_16_5_CUTOFF, basis: "16(5)", daysLeft: today ? daysBetween(today, SECTION_16_5_CUTOFF) : null };
  }

  const nov30 = `${fyStart + 1}-11-30`;
  // An annual return filed before 30 November closes the window on the day it
  // is filed, so the earlier of the two is the deadline.
  const earlyReturn = annualReturnDate && annualReturnDate < nov30 && annualReturnDate > `${fyStart + 1}-03-31`;
  const deadline = earlyReturn ? annualReturnDate : nov30;
  return {
    fy,
    deadline,
    basis: earlyReturn ? "annual-return" : "30-november",
    daysLeft: today ? daysBetween(today, deadline) : null,
  };
}

/**
 * Rule 37: credit on an invoice the buyer has not paid within 180 days of its
 * date is reversed in proportion to the unpaid share of the value *including
 * tax*, in the GSTR-3B for the period after the one in which day 180 falls,
 * with section 50 interest when the credit was already used. It comes back,
 * free of the 16(4) time limit, once the supplier is paid.
 *
 * `utilisedDate` is optional; without it no interest is estimated.
 */
export function rule37Reversal({ invoiceDate, invoiceValue, itc, paidWithin = 0, utilisedDate = "", today }) {
  const value = Number(invoiceValue);
  const credit = Number(itc);
  const paid = paidWithin === "" ? 0 : Number(paidWithin);
  if (parseDay(invoiceDate) === null) return { error: "date" };
  if (![value, credit, paid].every(Number.isFinite) || value <= 0 || credit < 0 || paid < 0) {
    return { error: "amount" };
  }
  if (credit > value) return { error: "itc-exceeds-value" };
  if (utilisedDate && parseDay(utilisedDate) === null) return { error: "date" };

  const payBy = addDays(invoiceDate, 180);
  const unpaid = round2(Math.max(value - paid, 0));
  const reversal = round2((credit * unpaid) / value);

  const [y, m] = payBy.split("-").map(Number);
  // Period after the one containing day 180; its monthly GSTR-3B is due on
  // the 20th of the month after that.
  const period = new Date(Date.UTC(y, m, 1));
  const due = new Date(Date.UTC(y, m + 1, 20));
  const reversalPeriod = `${MONTHS[period.getUTCMonth()]} ${period.getUTCFullYear()}`;
  const reverseBy = iso(due.getTime());

  const interestDays = utilisedDate && reversal > 0 ? daysLate(utilisedDate, reverseBy) : 0;
  return {
    payBy,
    unpaid,
    reversal,
    fullyPaid: unpaid === 0,
    reversalPeriod,
    reverseBy,
    interestDays,
    interest: calculateInterest(reversal, interestDays),
    daysToPay: today ? daysBetween(today, payBy) : null,
  };
}
