import { describe, expect, it } from "vitest";
import { addDays, financialYear, formatDay, itcClaimWindow, rule37Reversal } from "./itcTimeLimits";

describe("date helpers", () => {
  it("places January to March in the previous financial year", () => {
    expect(financialYear("2026-02-10")).toBe("2025-26");
    expect(financialYear("2026-04-01")).toBe("2026-27");
    expect(financialYear("1999-12-31")).toBe("1999-00");
  });

  it("rejects dates that do not exist", () => {
    expect(financialYear("2026-02-31")).toBeNull();
    expect(addDays("not a date", 1)).toBeNull();
    expect(formatDay("")).toBe("");
  });

  it("formats a day in words", () => {
    expect(formatDay("2026-11-30")).toBe("30 November 2026");
  });
});

describe("itcClaimWindow", () => {
  it("closes on 30 November after the invoice's financial year", () => {
    const w = itcClaimWindow({ documentDate: "2026-03-15", today: "2026-10-26" });
    expect(w).toEqual({ fy: "2025-26", deadline: "2026-11-30", basis: "30-november", daysLeft: 35 });
  });

  it("closes earlier when the annual return was filed first", () => {
    const w = itcClaimWindow({ documentDate: "2025-06-01", annualReturnDate: "2026-09-10", today: "2026-10-26" });
    expect(w.deadline).toBe("2026-09-10");
    expect(w.basis).toBe("annual-return");
    expect(w.daysLeft).toBe(-46);
  });

  it("ignores an annual return date that cannot belong to that year", () => {
    expect(itcClaimWindow({ documentDate: "2025-06-01", annualReturnDate: "2027-01-10" }).basis).toBe("30-november");
    expect(itcClaimWindow({ documentDate: "2025-06-01", annualReturnDate: "2026-02-10" }).basis).toBe("30-november");
  });

  it("reports the section 16(5) date for FY 2020-21 and earlier", () => {
    const w = itcClaimWindow({ documentDate: "2019-08-01", today: "2021-11-29" });
    expect(w).toEqual({ fy: "2019-20", deadline: "2021-11-30", basis: "16(5)", daysLeft: 1 });
    expect(itcClaimWindow({ documentDate: "2019-08-01" }).daysLeft).toBeNull();
  });

  it("returns nothing for an unusable date", () => {
    expect(itcClaimWindow({ documentDate: "" })).toBeNull();
    expect(itcClaimWindow({ documentDate: "2025-06-01", annualReturnDate: "2026-13-01" })).toBeNull();
  });
});

describe("rule37Reversal", () => {
  const INVOICE = { invoiceDate: "2026-01-10", invoiceValue: 118_000, itc: 18_000 };

  it("needs nothing reversed when the invoice was paid in full", () => {
    const r = rule37Reversal({ ...INVOICE, paidWithin: 118_000 });
    expect(r.fullyPaid).toBe(true);
    expect(r.reversal).toBe(0);
    expect(r.interest).toBe(0);
  });

  it("reverses in proportion to the unpaid share of the value including tax", () => {
    const r = rule37Reversal({ ...INVOICE, paidWithin: 59_000 });
    expect(r.unpaid).toBe(59_000);
    expect(r.reversal).toBe(9_000);
  });

  it("reverses in the GSTR-3B for the period after the one in which day 180 falls", () => {
    const r = rule37Reversal({ ...INVOICE, today: "2026-06-30" });
    expect(r.payBy).toBe("2026-07-09");
    expect(r.reversalPeriod).toBe("August 2026");
    expect(r.reverseBy).toBe("2026-09-20");
    expect(r.daysToPay).toBe(9);
  });

  it("rolls the reversal period over a year end", () => {
    const r = rule37Reversal({ ...INVOICE, invoiceDate: "2026-06-20" });
    expect(r.payBy).toBe("2026-12-17");
    expect(r.reversalPeriod).toBe("January 2027");
    expect(r.reverseBy).toBe("2027-02-20");
  });

  it("charges 18% interest from utilisation to the reversal due date", () => {
    const r = rule37Reversal({ ...INVOICE, utilisedDate: "2026-02-20" });
    expect(r.interestDays).toBe(212);
    expect(r.interest).toBe(Math.round((18_000 * 18 * 212) / 36_500));
  });

  it("estimates no interest without a utilisation date", () => {
    expect(rule37Reversal(INVOICE).interest).toBe(0);
  });

  it("refuses unusable input", () => {
    expect(rule37Reversal({ ...INVOICE, invoiceDate: "x" })).toEqual({ error: "date" });
    expect(rule37Reversal({ ...INVOICE, utilisedDate: "2026-02-30" })).toEqual({ error: "date" });
    expect(rule37Reversal({ ...INVOICE, invoiceValue: 0 })).toEqual({ error: "amount" });
    expect(rule37Reversal({ ...INVOICE, paidWithin: -1 })).toEqual({ error: "amount" });
    expect(rule37Reversal({ ...INVOICE, itc: 200_000 })).toEqual({ error: "itc-exceeds-value" });
  });
});
