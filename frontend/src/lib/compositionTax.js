// Composition scheme (Section 10) tax, quarter by quarter, as paid via CMP-08.
//
// The rate base differs by category (Rule 7 and Notf. 2/2019-CT(R)):
// manufacturers and restaurants pay on their whole turnover in the state,
// exempt supplies included; traders pay only on taxable supplies; service
// providers under s.10(2A) pay 6% on taxable supplies. Reverse-charge
// inward supplies are paid on top at the normal rate — the composition rate
// never applies to them, and no ITC is available against any of it.

import { calculateInterest, CRORE, daysLate } from "./gstPenalties";
import { fyStartYear } from "./gstr9Summary";

export const LAKH = 100000;

export const CATEGORIES = [
  { key: "manufacturer", label: "Manufacturer", rate: 1, base: "total", limit: 1.5 * CRORE },
  { key: "trader", label: "Trader / dealer", rate: 1, base: "taxable", limit: 1.5 * CRORE },
  { key: "restaurant", label: "Restaurant (no alcohol)", rate: 5, base: "total", limit: 1.5 * CRORE },
  { key: "service", label: "Service provider — Section 10(2A)", rate: 6, base: "taxable", limit: 50 * LAKH },
];

// Special category states where the goods limit is ₹75 lakh instead of ₹1.5 crore.
export const LOWER_LIMIT_STATES = ["Arunachal Pradesh", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Sikkim", "Tripura", "Uttarakhand"];

export const QUARTERS = [
  { key: "q1", label: "Q1 (Apr–Jun)" },
  { key: "q2", label: "Q2 (Jul–Sep)" },
  { key: "q3", label: "Q3 (Oct–Dec)" },
  { key: "q4", label: "Q4 (Jan–Mar)" },
];

const round2 = (n) => Math.round(n * 100) / 100;
const num = (v) => {
  const n = parseFloat(v);
  return Number.isFinite(n) && n > 0 ? n : 0;
};

export function emptyQuarters() {
  return QUARTERS.map((q) => ({ quarter: q.label, taxable: "", exempt: "", rcmValue: "", rcmRate: "18", paidOn: "" }));
}

export function categoryFor(key) {
  return CATEGORIES.find((c) => c.key === key) || CATEGORIES[0];
}

/** Turnover limit for the category, after the special-category-state reduction for goods. */
export function turnoverLimit(categoryKey, lowerLimitState = false) {
  const c = categoryFor(categoryKey);
  if (c.key === "service") return c.limit;
  return lowerLimitState ? 75 * LAKH : c.limit;
}

/** CMP-08 is due on the 18th of the month after the quarter. */
export function cmp08DueDate(fy, index) {
  const start = fyStartYear(fy);
  if (start === null) return null;
  const [month, year] = [[7, start], [10, start], [1, start + 1], [4, start + 1]][index];
  return `${year}-${String(month).padStart(2, "0")}-18`;
}

/** GSTR-4 annual return: 30 April after the financial year. */
export function gstr4DueDate(fy) {
  const start = fyStartYear(fy);
  return start === null ? null : `${start + 1}-04-30`;
}

export function quarterTax(categoryKey, { taxable, exempt, rcmValue, rcmRate }) {
  const c = categoryFor(categoryKey);
  const t = num(taxable);
  const e = num(exempt);
  const base = c.base === "total" ? t + e : t;
  const compTax = round2((base * c.rate) / 100);
  const rcmTax = round2((num(rcmValue) * num(rcmRate)) / 100);
  const half = round2(compTax / 2);
  return { base, compTax, cgst: half, sgst: round2(compTax - half), rcmTax, total: round2(compTax + rcmTax) };
}

/**
 * Full-year composition picture.
 * @returns per-quarter tax, CMP-08 due dates and interest, cumulative
 *   turnover against the limit, and the GSTR-4 totals.
 */
export function compositionYear({ category = "manufacturer", quarters, fy = "2025-26", lowerLimitState = false } = {}) {
  const limit = turnoverLimit(category, lowerLimitState);
  let cumulative = 0;
  let breachQuarter = null;

  const rows = (quarters || []).map((q, i) => {
    const tax = quarterTax(category, q);
    const turnover = num(q.taxable) + num(q.exempt);
    cumulative += turnover;
    if (breachQuarter === null && cumulative > limit) breachQuarter = i;
    const dueDate = cmp08DueDate(fy, i);
    const days = q.paidOn ? daysLate(dueDate, q.paidOn) : 0;
    // s.50(1) interest runs on the tax paid late; all of it is cash for a
    // composition dealer, since there is no credit to set off.
    const interest = calculateInterest(tax.total, days);
    return {
      quarter: q.quarter || QUARTERS[i].label,
      filled: turnover > 0 || num(q.rcmValue) > 0,
      turnover: round2(turnover),
      cumulative: round2(cumulative),
      ...tax,
      dueDate,
      daysLate: days,
      interest,
      payable: round2(tax.total + interest),
    };
  });

  if (!rows.some((r) => r.filled)) return null;

  const sum = (k) => round2(rows.reduce((a, r) => a + r[k], 0));
  return {
    category: categoryFor(category),
    limit,
    quarters: rows,
    annualTurnover: round2(cumulative),
    totalCompTax: sum("compTax"),
    totalRcmTax: sum("rcmTax"),
    totalInterest: rows.reduce((a, r) => a + r.interest, 0),
    totalPayable: sum("payable"),
    limitUsedPct: Math.round((cumulative / limit) * 1000) / 10,
    breachQuarter,
    breached: breachQuarter !== null,
    gstr4DueDate: gstr4DueDate(fy),
  };
}
