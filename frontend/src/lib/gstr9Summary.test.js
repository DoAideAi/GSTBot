import { describe, expect, it } from "vitest";
import {
  applicability,
  emptyMonths,
  fyStartYear,
  gstr3bDueDate,
  gstr9DueDate,
  parsePastedMonths,
  summarizeGstr9,
} from "./gstr9Summary";

function monthsWith(overrides = {}) {
  return emptyMonths().map((m, i) => ({
    ...m,
    r1Taxable: 1000000,
    r1Tax: 180000,
    b3Taxable: 1000000,
    b3Tax: 180000,
    b3Itc: 120000,
    ...(overrides[i] || {}),
  }));
}

describe("due dates", () => {
  it("parses the April year of a financial year", () => {
    expect(fyStartYear("2025-26")).toBe(2025);
    expect(fyStartYear("junk")).toBeNull();
  });

  it("puts each month's GSTR-3B on the 20th of the next month", () => {
    expect(gstr3bDueDate("2025-26", 0)).toBe("2025-05-20");
    expect(gstr3bDueDate("2025-26", 7)).toBe("2025-12-20");
    expect(gstr3bDueDate("2025-26", 8)).toBe("2026-01-20");
    expect(gstr3bDueDate("2025-26", 11)).toBe("2026-04-20");
    expect(gstr3bDueDate("x", 0)).toBeNull();
  });

  it("puts GSTR-9 on 31 December after the year", () => {
    expect(gstr9DueDate("2025-26")).toBe("2026-12-31");
    expect(gstr9DueDate("")).toBeNull();
  });
});

describe("applicability", () => {
  it("is optional up to ₹2 Cr, GSTR-9 above, GSTR-9C above ₹5 Cr", () => {
    expect(applicability(2e7)).toMatchObject({ gstr9Mandatory: false, gstr9cRequired: false });
    expect(applicability(3e7)).toMatchObject({ gstr9Mandatory: true, gstr9cRequired: false });
    expect(applicability(6e7)).toMatchObject({ gstr9Mandatory: true, gstr9cRequired: true });
    expect(applicability(6e7).note).toMatch(/GSTR-9C are both mandatory/);
  });
});

describe("summarizeGstr9", () => {
  it("returns null when nothing has been entered", () => {
    expect(summarizeGstr9({ months: emptyMonths() })).toBeNull();
    expect(summarizeGstr9()).toBeNull();
  });

  it("totals the year into the GSTR-9 tables when GSTR-1 and 3B agree", () => {
    const s = summarizeGstr9({ months: monthsWith(), itc2b: 1440000, itcReversed: 20000, exempt: 500000 });
    expect(s.filledMonths).toBe(12);
    expect(s.table4).toEqual({ taxable: 12000000, tax: 2160000 });
    expect(s.table9.taxPaid).toBe(2160000);
    expect(s.table6.itcClaimed).toBe(1440000);
    expect(s.netItc).toBe(1420000);
    expect(s.table8.difference).toBe(0);
    expect(s.taxGap).toBe(0);
    expect(s.shortPaidMonths).toHaveLength(0);
    expect(s.drc03Total).toBe(0);
    expect(s.aggregateTurnover).toBe(12500000);
    expect(s.applicability.gstr9Mandatory).toBe(false);
  });

  it("flags months where GSTR-1 tax exceeds GSTR-3B and charges interest from the 3B due date", () => {
    // June (index 2) short by ₹10,000; due 20 July 2025, paid 20 July 2026 → 365 days.
    const s = summarizeGstr9({
      months: monthsWith({ 2: { b3Tax: 170000, b3Taxable: 944444 } }),
      fy: "2025-26",
      payOn: "2026-07-20",
    });
    expect(s.shortPaidMonths).toHaveLength(1);
    expect(s.shortPaidMonths[0]).toMatchObject({ month: "June", taxGap: 10000, interestDays: 365, interest: 1800 });
    expect(s.shortPaidTotal).toBe(10000);
    expect(s.interestTotal).toBe(1800);
    expect(s.drc03Total).toBe(11800);
    expect(s.valueGap).toBe(55556);
  });

  it("keeps over-declared months separate and never nets them against shortfalls", () => {
    const s = summarizeGstr9({
      months: monthsWith({ 0: { b3Tax: 170000 }, 1: { b3Tax: 190000 } }),
    });
    expect(s.taxGap).toBe(0);
    expect(s.shortPaidMonths.map((m) => m.month)).toEqual(["April"]);
    expect(s.overPaidMonths.map((m) => m.month)).toEqual(["May"]);
    expect(s.shortPaidTotal).toBe(10000);
    // No payment date → no interest computed yet.
    expect(s.interestTotal).toBe(0);
  });

  it("reports ITC claimed beyond GSTR-2B as a negative Table 8D difference", () => {
    const s = summarizeGstr9({ months: monthsWith(), itc2b: 1400000 });
    expect(s.table8.difference).toBe(-40000);
  });

  it("leaves Table 8D open when GSTR-2B is not entered", () => {
    const s = summarizeGstr9({ months: monthsWith(), itc2b: "" });
    expect(s.table8.difference).toBeNull();
  });

  it("counts a partly filled year and ignores non-numeric cells", () => {
    const months = emptyMonths();
    months[0] = { ...months[0], r1Taxable: "500000", r1Tax: "90000", b3Tax: "abc" };
    const s = summarizeGstr9({ months });
    expect(s.filledMonths).toBe(1);
    expect(s.table4.tax).toBe(90000);
    expect(s.table9.taxPaid).toBe(0);
    expect(s.shortPaidTotal).toBe(90000);
  });
});

describe("parsePastedMonths", () => {
  it("reads tab-separated rows with Indian digit grouping and skips headers", () => {
    const text = "Month\tR1 value\tR1 tax\t3B value\t3B tax\tITC\nApril\t10,00,000\t1,80,000\t10,00,000\t1,80,000\t1,20,000\nMay\t5\t1\t5\t1\t0";
    const { months, rows } = parsePastedMonths(text);
    expect(rows).toBe(2);
    expect(months[0]).toMatchObject({ month: "April", r1Taxable: "1000000", r1Tax: "180000", b3Itc: "120000" });
    expect(months[1]).toMatchObject({ month: "May", r1Taxable: "5", b3Itc: "0" });
    expect(months[2].r1Taxable).toBe("");
  });

  it("reads comma-separated rows and right-aligns short rows onto the last fields", () => {
    const { months, rows } = parsePastedMonths("100,18,100\n");
    expect(rows).toBe(1);
    expect(months[0]).toMatchObject({ r1Taxable: "", r1Tax: "", b3Taxable: "100", b3Tax: "18", b3Itc: "100" });
  });

  it("stops after twelve months and handles empty input", () => {
    const many = Array.from({ length: 14 }, () => "1,2,3,4,5").join("\n");
    expect(parsePastedMonths(many).rows).toBe(12);
    expect(parsePastedMonths("").rows).toBe(0);
    expect(parsePastedMonths(undefined).months).toHaveLength(12);
  });
});
