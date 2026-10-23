// GSTR-9 annual return summary from twelve months of GSTR-1 and GSTR-3B.
//
// GSTR-9 reports outward supplies on the GSTR-1 basis (Tables 4 and 5) but
// tax *paid* on the GSTR-3B basis (Table 9), and ITC claimed in GSTR-3B
// (Table 6) against what GSTR-2B made available (Table 8A). The gaps between
// those pairs are what the department reads first, so they are the output:
// tax declared in GSTR-1 but never paid through GSTR-3B goes out via DRC-03
// with interest, and ITC claimed beyond GSTR-2B is the classic notice trigger.

import { calculateInterest, CRORE, daysLate } from "./gstPenalties";

export const FY_MONTHS = [
  "April", "May", "June", "July", "August", "September",
  "October", "November", "December", "January", "February", "March",
];

export const MONTH_FIELDS = ["r1Taxable", "r1Tax", "b3Taxable", "b3Tax", "b3Itc"];

const round2 = (n) => Math.round(n * 100) / 100;
const num = (v) => {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : 0;
};

export function emptyMonths() {
  return FY_MONTHS.map((month) => ({ month, r1Taxable: "", r1Tax: "", b3Taxable: "", b3Tax: "", b3Itc: "" }));
}

/** "2025-26" → 2025 (the April year). */
export function fyStartYear(fy) {
  const y = parseInt(String(fy).slice(0, 4), 10);
  return Number.isFinite(y) ? y : null;
}

/** GSTR-3B due date (monthly filer, 20th of the next month) for month index 0 = April. */
export function gstr3bDueDate(fy, index) {
  const start = fyStartYear(fy);
  if (start === null) return null;
  // April (0) → due 20 May of the start year; March (11) → due 20 April of the next.
  const monthNumber = ((3 + index + 1) % 12) + 1; // 1-12 calendar month of the due date
  const year = index >= 8 ? start + 1 : start; // Dec (index 8) is due 20 Jan of the next year
  return `${year}-${String(monthNumber).padStart(2, "0")}-20`;
}

/** GSTR-9 due date: 31 December after the financial year. */
export function gstr9DueDate(fy) {
  const start = fyStartYear(fy);
  return start === null ? null : `${start + 1}-12-31`;
}

/** Who must file what, by aggregate turnover for the year. */
export function applicability(aggregateTurnover) {
  const t = num(aggregateTurnover);
  return {
    gstr9Mandatory: t > 2 * CRORE,
    gstr9cRequired: t > 5 * CRORE,
    note:
      t > 5 * CRORE
        ? "GSTR-9 and the self-certified reconciliation statement GSTR-9C are both mandatory."
        : t > 2 * CRORE
          ? "GSTR-9 is mandatory. GSTR-9C is not required at this turnover."
          : "GSTR-9 is optional up to ₹2 crore aggregate turnover — but filing it voluntarily locks in your figures.",
  };
}

/**
 * Build the summary.
 * @param {object} input
 * @param {Array} input.months twelve rows of MONTH_FIELDS (strings or numbers)
 * @param {number} input.itc2b ITC available per GSTR-2B for the year (Table 8A)
 * @param {number} input.itcReversed ITC reversed in the year (Table 7)
 * @param {number} input.exempt exempt + nil-rated + non-GST outward supplies (Table 5D-5F)
 * @param {string} input.fy e.g. "2025-26"
 * @param {string} input.payOn date the shortfall will be paid via DRC-03
 */
export function summarizeGstr9({ months, itc2b = 0, itcReversed = 0, exempt = 0, fy = "2025-26", payOn } = {}) {
  const rows = (months || []).map((m, i) => {
    const r1Taxable = num(m.r1Taxable);
    const r1Tax = num(m.r1Tax);
    const b3Taxable = num(m.b3Taxable);
    const b3Tax = num(m.b3Tax);
    const b3Itc = num(m.b3Itc);
    const filled = MONTH_FIELDS.some((f) => String(m[f] ?? "").trim() !== "");
    const taxGap = round2(r1Tax - b3Tax);
    const shortPaid = taxGap > 0 ? taxGap : 0;
    const due = gstr3bDueDate(fy, i);
    const days = shortPaid > 0 && payOn ? daysLate(due, payOn) : 0;
    return {
      month: m.month || FY_MONTHS[i],
      filled,
      r1Taxable,
      r1Tax,
      b3Taxable,
      b3Tax,
      b3Itc,
      valueGap: round2(r1Taxable - b3Taxable),
      taxGap,
      dueDate: due,
      interest: calculateInterest(shortPaid, days),
      interestDays: days,
    };
  });

  const filledRows = rows.filter((r) => r.filled);
  if (filledRows.length === 0) return null;

  const sum = (key) => round2(rows.reduce((acc, r) => acc + r[key], 0));
  const outwardTaxable = sum("r1Taxable");
  const outwardTax = sum("r1Tax");
  const paidTaxable = sum("b3Taxable");
  const paidTax = sum("b3Tax");
  const itcClaimed = sum("b3Itc");
  const available = num(itc2b);
  const reversed = num(itcReversed);
  const exemptSupplies = num(exempt);

  const shortPaidMonths = rows.filter((r) => r.taxGap > 1);
  const overPaidMonths = rows.filter((r) => r.taxGap < -1);
  const shortPaidTotal = round2(shortPaidMonths.reduce((a, r) => a + r.taxGap, 0));
  const interestTotal = shortPaidMonths.reduce((a, r) => a + r.interest, 0);
  // Table 8D: positive = GSTR-2B had more than was claimed (credit at risk of
  // lapsing), negative = more claimed than GSTR-2B supports (notice risk).
  const itcDifference = itc2b === "" || itc2b === null ? null : round2(available - itcClaimed);
  const aggregateTurnover = round2(outwardTaxable + exemptSupplies);

  return {
    months: rows,
    filledMonths: filledRows.length,
    table4: { taxable: outwardTaxable, tax: outwardTax },
    table5: { exempt: exemptSupplies },
    table6: { itcClaimed },
    table7: { reversed },
    table8: { itc2b: available, difference: itcDifference },
    table9: { taxPaid: paidTax },
    netItc: round2(itcClaimed - reversed),
    valueGap: round2(outwardTaxable - paidTaxable),
    taxGap: round2(outwardTax - paidTax),
    shortPaidMonths,
    overPaidMonths,
    shortPaidTotal,
    interestTotal,
    drc03Total: round2(shortPaidTotal + interestTotal),
    aggregateTurnover,
    applicability: applicability(aggregateTurnover),
    dueDate: gstr9DueDate(fy),
  };
}

/**
 * Rows pasted from a spreadsheet → month rows. Each line is one month in FY
 * order; a leading month name is ignored and the last five numeric cells map
 * to MONTH_FIELDS. Tab-separated (Excel/Sheets) input may carry "1,00,000"
 * style numbers; otherwise commas separate cells.
 */
export function parsePastedMonths(text) {
  const lines = String(text || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const out = emptyMonths();
  let row = 0;
  for (const line of lines) {
    if (row >= 12) break;
    const cells = line.includes("\t") ? line.split("\t").map((c) => c.replace(/[,₹\s]/g, "")) : line.split(/[,;]/).map((c) => c.trim());
    const numbers = cells.filter((c) => c !== "" && Number.isFinite(Number(c)));
    if (numbers.length === 0) continue; // header row
    const values = numbers.slice(-MONTH_FIELDS.length);
    const offset = MONTH_FIELDS.length - values.length;
    MONTH_FIELDS.forEach((f, i) => {
      out[row][f] = i >= offset ? values[i - offset] : "";
    });
    row++;
  }
  return { months: out, rows: row };
}
