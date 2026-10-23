// Year-long input tax credit reconciliation: purchase books vs GSTR-2B vs
// what was actually claimed in GSTR-3B, month by month.
//
// Three gaps matter and they mean different things:
//   claimed − 2B   credit taken that the supplier side doesn't support. If it
//                  was utilised it carries 18% interest under s.50(3) and is
//                  the first thing an ASMT-10 notice asks about.
//   books − claimed eligible credit still sitting unclaimed — recoverable,
//                  but only until the s.16(4) deadline (30 November after the FY).
//   books − 2B     invoices your suppliers haven't reported. Chase them before
//                  claiming, or the credit lands in the first bucket.

import { calculateInterest, daysLate } from "./gstPenalties";
import { FY_MONTHS, fyStartYear, gstr3bDueDate } from "./gstr9Summary";

export const ITC_FIELDS = ["books", "gstr2b", "claimed"];

const round2 = (n) => Math.round(n * 100) / 100;
const num = (v) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : 0;
};

// Gaps under this are rounding, not a mismatch.
export const TOLERANCE = 100;

export function emptyItcMonths() {
  return FY_MONTHS.map((month) => ({ month, books: "", gstr2b: "", claimed: "" }));
}

/** Section 16(4): ITC for an FY can be claimed until 30 November of the next year. */
export function itcClaimDeadline(fy) {
  const start = fyStartYear(fy);
  return start === null ? null : `${start + 1}-11-30`;
}

/** Days from `today` until the deadline; negative once it has passed. */
export function daysUntil(deadline, today) {
  if (!deadline || !today) return null;
  const ahead = daysLate(today, deadline);
  if (ahead > 0) return ahead;
  const behind = daysLate(deadline, today);
  return behind > 0 ? -behind : 0;
}

export function monthStatus(row) {
  if (row.excess > TOLERANCE) return "excess";
  if (row.unclaimed > TOLERANCE || row.supplierGap > TOLERANCE) return "pending";
  return "matched";
}

/**
 * @param {object} input
 * @param {Array} input.months twelve rows of { books, gstr2b, claimed }
 * @param {string} input.fy "2025-26"
 * @param {string} input.today ISO date the dashboard is viewed on
 * @param {Array} [input.suppliers] [{ name, books, gstr2b }] for the follow-up list
 */
export function buildItcDashboard({ months, fy = "2025-26", today, suppliers = [] } = {}) {
  const rows = (months || []).map((m, i) => {
    const books = num(m.books);
    const gstr2b = num(m.gstr2b);
    const claimed = num(m.claimed);
    const filled = ITC_FIELDS.some((f) => String(m[f] ?? "").trim() !== "");
    const excess = round2(Math.max(0, claimed - gstr2b));
    // Interest exposure assumes excess credit was utilised against that
    // month's liability on its GSTR-3B due date — the usual case.
    const dueDate = gstr3bDueDate(fy, i);
    const exposureDays = excess > 0 && today ? daysLate(dueDate, today) : 0;
    const row = {
      month: m.month || FY_MONTHS[i],
      filled,
      books,
      gstr2b,
      claimed,
      excess,
      unclaimed: round2(Math.max(0, Math.min(books, gstr2b) - claimed)),
      supplierGap: round2(Math.max(0, books - gstr2b)),
      interestExposure: calculateInterest(excess, exposureDays),
    };
    return { ...row, status: filled ? monthStatus(row) : "empty" };
  });

  const filled = rows.filter((r) => r.filled);
  if (filled.length === 0) return null;

  const total = (key) => round2(rows.reduce((a, r) => a + r[key], 0));
  const totals = {
    books: total("books"),
    gstr2b: total("gstr2b"),
    claimed: total("claimed"),
    excess: total("excess"),
    unclaimed: total("unclaimed"),
    supplierGap: total("supplierGap"),
    interestExposure: rows.reduce((a, r) => a + r.interestExposure, 0),
  };
  const matchedMonths = filled.filter((r) => r.status === "matched").length;
  // Share of claimed credit that GSTR-2B backs — the figure a scrutiny officer computes.
  const coverage = totals.claimed > 0 ? Math.min(100, Math.round(((totals.claimed - totals.excess) / totals.claimed) * 1000) / 10) : 100;

  const deadline = itcClaimDeadline(fy);
  const daysLeft = daysUntil(deadline, today);

  const followUps = suppliers
    .map((s) => ({ name: String(s.name || "").trim(), books: num(s.books), gstr2b: num(s.gstr2b) }))
    .filter((s) => s.name)
    .map((s) => ({ ...s, gap: round2(s.books - s.gstr2b) }))
    .filter((s) => s.gap > TOLERANCE)
    .sort((a, b) => b.gap - a.gap);

  const maxValue = Math.max(1, ...rows.map((r) => Math.max(r.books, r.gstr2b, r.claimed)));

  return {
    months: rows,
    filledMonths: filled.length,
    matchedMonths,
    totals,
    coverage,
    deadline,
    daysLeft,
    deadlinePassed: daysLeft !== null && daysLeft < 0,
    followUps,
    maxValue,
    risk: totals.excess > TOLERANCE ? "high" : totals.unclaimed > TOLERANCE || totals.supplierGap > TOLERANCE ? "medium" : "low",
  };
}
