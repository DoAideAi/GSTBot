// Late fee (Section 47) and interest (Section 50) on delayed GST returns.
//
// The caps are the ones the CBIC notifications actually set, not the Act's
// headline ₹200/day: GSTR-1/3B by aggregate turnover (Notf. 19/2021 and
// 20/2021-CT), GSTR-4 (Notf. 21/2021-CT) and GSTR-9 from FY 2022-23
// (Notf. 7/2023-CT). Every figure here is the combined CGST + SGST amount;
// the split is always half and half (IGST-only returns pay the same total).

export const CRORE = 10000000;

// Aggregate annual turnover bands used by the GSTR-1/3B caps.
export const AATO_BANDS = [
  { key: "upto1_5", label: "Up to ₹1.5 crore", max: 1.5 * CRORE },
  { key: "upto5", label: "₹1.5 crore – ₹5 crore", max: 5 * CRORE },
  { key: "above5", label: "Above ₹5 crore", max: Infinity },
];

export const LATE_FEE_RETURNS = [
  { key: "gstr3b", label: "GSTR-3B" },
  { key: "gstr1", label: "GSTR-1" },
  { key: "gstr4", label: "GSTR-4 (Composition annual)" },
  { key: "gstr9", label: "GSTR-9 (Annual Return)" },
];

// Reference rows for the quick-reference table on the calculator pages.
export const LATE_FEE_TABLE = [
  { ret: "GSTR-3B / GSTR-1 — nil", perDay: 20, cap: "₹500" },
  { ret: "GSTR-3B / GSTR-1 — turnover up to ₹1.5 Cr", perDay: 50, cap: "₹2,000" },
  { ret: "GSTR-3B / GSTR-1 — ₹1.5 Cr to ₹5 Cr", perDay: 50, cap: "₹5,000" },
  { ret: "GSTR-3B / GSTR-1 — above ₹5 Cr", perDay: 50, cap: "₹10,000" },
  { ret: "GSTR-4 — nil", perDay: 50, cap: "₹500" },
  { ret: "GSTR-4 — with tax", perDay: 50, cap: "₹2,000" },
  { ret: "GSTR-9 — turnover up to ₹5 Cr", perDay: 50, cap: "0.04% of state turnover" },
  { ret: "GSTR-9 — ₹5 Cr to ₹20 Cr", perDay: 100, cap: "0.04% of state turnover" },
  { ret: "GSTR-9 — above ₹20 Cr", perDay: 200, cap: "0.5% of state turnover" },
];

// 18% for late payment (s.50(1)) and, since 5 July 2022 (Notf. 14/2022-CT),
// also for ITC wrongly availed *and utilised* (s.50(3)) — the old 24% is gone.
export const INTEREST_RATE = 18;

function toUtcDay(value) {
  if (!value) return null;
  const [y, m, d] = String(value).slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return null;
  return Date.UTC(y, m - 1, d);
}

/** Days from the due date (excluded) to the filing/payment date (included). */
export function daysLate(dueDate, actualDate) {
  const due = toUtcDay(dueDate);
  const actual = toUtcDay(actualDate);
  if (due === null || actual === null) return 0;
  return Math.max(0, Math.round((actual - due) / 86400000));
}

export function aatoBandFor(turnover) {
  const t = Number(turnover) || 0;
  return AATO_BANDS.find((b) => t <= b.max) || AATO_BANDS[AATO_BANDS.length - 1];
}

/**
 * Per-day fee and cap for one return.
 * @returns {{ perDay: number, cap: number|null, basis: string }}
 */
export function lateFeeRule(returnType, { nil = false, aato = 0, stateTurnover = 0 } = {}) {
  const t = Number(aato) || 0;
  if (returnType === "gstr1" || returnType === "gstr3b") {
    if (nil) return { perDay: 20, cap: 500, basis: "Nil return — ₹20/day, max ₹500" };
    if (t <= 1.5 * CRORE) return { perDay: 50, cap: 2000, basis: "Turnover up to ₹1.5 Cr — max ₹2,000" };
    if (t <= 5 * CRORE) return { perDay: 50, cap: 5000, basis: "Turnover ₹1.5–5 Cr — max ₹5,000" };
    return { perDay: 50, cap: 10000, basis: "Turnover above ₹5 Cr — max ₹10,000" };
  }
  if (returnType === "gstr4") {
    return nil
      ? { perDay: 50, cap: 500, basis: "Nil GSTR-4 — max ₹500" }
      : { perDay: 50, cap: 2000, basis: "GSTR-4 with tax — max ₹2,000" };
  }
  if (returnType === "gstr9") {
    // The cap is a share of the turnover *in the state/UT*; fall back to the
    // aggregate when the user has a single registration and gave only that.
    const st = Number(stateTurnover) || t;
    if (t <= 5 * CRORE) {
      return { perDay: 50, cap: st > 0 ? Math.round(st * 0.0004) : null, basis: "Turnover up to ₹5 Cr — ₹50/day, max 0.04% of state turnover" };
    }
    if (t <= 20 * CRORE) {
      return { perDay: 100, cap: st > 0 ? Math.round(st * 0.0004) : null, basis: "Turnover ₹5–20 Cr — ₹100/day, max 0.04% of state turnover" };
    }
    return { perDay: 200, cap: st > 0 ? Math.round(st * 0.005) : null, basis: "Turnover above ₹20 Cr — ₹200/day, max 0.5% of state turnover" };
  }
  throw new Error(`Unknown return type: ${returnType}`);
}

/**
 * Late fee for a return filed `days` after its due date.
 * @returns {{ days, perDay, uncapped, cap, fee, cgst, sgst, capped, basis }}
 */
export function calculateLateFee(returnType, days, opts = {}) {
  const d = Math.max(0, Math.floor(Number(days) || 0));
  const rule = lateFeeRule(returnType, opts);
  const uncapped = d * rule.perDay;
  const fee = rule.cap === null ? uncapped : Math.min(uncapped, rule.cap);
  const cgst = Math.round(fee / 2);
  return {
    days: d,
    perDay: rule.perDay,
    uncapped,
    cap: rule.cap,
    fee,
    cgst,
    sgst: fee - cgst,
    capped: rule.cap !== null && uncapped > rule.cap,
    basis: rule.basis,
  };
}

/** Simple day-wise interest: amount × rate × days / 365, rounded to the rupee. */
export function calculateInterest(amount, days, rate = INTEREST_RATE) {
  const a = Number(amount) || 0;
  const d = Math.max(0, Number(days) || 0);
  if (a <= 0 || d === 0) return 0;
  return Math.round((a * rate * d) / (365 * 100));
}

/**
 * Everything owed for one late return: late fee + s.50(1) interest on the
 * tax paid in cash + s.50(3) interest on ITC wrongly availed and utilised.
 * Interest on the late return runs to `paymentDate` (defaults to filing date).
 */
export function calculateLateReturnCost({
  returnType,
  dueDate,
  filingDate,
  paymentDate,
  nil = false,
  aato = 0,
  stateTurnover = 0,
  cashTax = 0,
  wrongItcUtilised = 0,
  itcUtilisedSince,
}) {
  const filedDays = daysLate(dueDate, filingDate);
  const paidDays = daysLate(dueDate, paymentDate || filingDate);
  const lateFee = calculateLateFee(returnType, filedDays, { nil, aato, stateTurnover });
  const interestOnTax = nil ? 0 : calculateInterest(cashTax, paidDays);
  const itcDays = itcUtilisedSince ? daysLate(itcUtilisedSince, paymentDate || filingDate) : 0;
  const interestOnItc = calculateInterest(wrongItcUtilised, itcDays);
  return {
    filedDays,
    paidDays,
    itcDays,
    lateFee,
    interestOnTax,
    interestOnItc,
    total: lateFee.fee + interestOnTax + interestOnItc,
  };
}
