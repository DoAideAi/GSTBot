import { describe, expect, it } from "vitest";
import {
  aatoBandFor,
  calculateInterest,
  calculateLateFee,
  calculateLateReturnCost,
  CRORE,
  daysLate,
  lateFeeRule,
} from "./gstPenalties";

describe("daysLate", () => {
  it("excludes the due date and includes the filing date", () => {
    expect(daysLate("2026-10-20", "2026-10-21")).toBe(1);
    expect(daysLate("2026-10-20", "2026-11-19")).toBe(30);
  });

  it("is zero on or before the due date and for missing input", () => {
    expect(daysLate("2026-10-20", "2026-10-20")).toBe(0);
    expect(daysLate("2026-10-20", "2026-10-01")).toBe(0);
    expect(daysLate("", "2026-10-01")).toBe(0);
    expect(daysLate("2026-10-20", "garbage")).toBe(0);
  });

  it("is not thrown off by month and leap-year boundaries", () => {
    expect(daysLate("2028-02-28", "2028-03-01")).toBe(2);
    expect(daysLate("2026-03-31", "2026-04-01")).toBe(1);
  });
});

describe("aatoBandFor", () => {
  it("places turnover in the right band, inclusive of the upper edge", () => {
    expect(aatoBandFor(1.5 * CRORE).key).toBe("upto1_5");
    expect(aatoBandFor(1.5 * CRORE + 1).key).toBe("upto5");
    expect(aatoBandFor(5 * CRORE).key).toBe("upto5");
    expect(aatoBandFor(6 * CRORE).key).toBe("above5");
    expect(aatoBandFor(undefined).key).toBe("upto1_5");
  });
});

describe("lateFeeRule / calculateLateFee — GSTR-1 and GSTR-3B", () => {
  it("charges ₹50/day split equally, capped at ₹2,000 up to ₹1.5 Cr", () => {
    const r = calculateLateFee("gstr3b", 10, { aato: CRORE });
    expect(r).toMatchObject({ perDay: 50, fee: 500, cgst: 250, sgst: 250, capped: false });
    expect(calculateLateFee("gstr3b", 100, { aato: CRORE })).toMatchObject({ fee: 2000, capped: true, uncapped: 5000 });
  });

  it("caps at ₹5,000 for ₹1.5–5 Cr and ₹10,000 above ₹5 Cr", () => {
    expect(calculateLateFee("gstr1", 365, { aato: 3 * CRORE }).fee).toBe(5000);
    expect(calculateLateFee("gstr1", 365, { aato: 8 * CRORE }).fee).toBe(10000);
  });

  it("uses ₹20/day capped at ₹500 for nil returns regardless of turnover", () => {
    expect(calculateLateFee("gstr3b", 5, { nil: true, aato: 8 * CRORE })).toMatchObject({ perDay: 20, fee: 100 });
    expect(calculateLateFee("gstr3b", 90, { nil: true }).fee).toBe(500);
  });

  it("treats non-numeric and negative days as zero", () => {
    expect(calculateLateFee("gstr3b", -4).fee).toBe(0);
    expect(calculateLateFee("gstr3b", "abc").fee).toBe(0);
  });
});

describe("lateFeeRule — GSTR-4 and GSTR-9", () => {
  it("caps GSTR-4 at ₹500 nil / ₹2,000 otherwise", () => {
    expect(calculateLateFee("gstr4", 100, { nil: true }).fee).toBe(500);
    expect(calculateLateFee("gstr4", 100).fee).toBe(2000);
  });

  it("charges GSTR-9 by turnover tier with a percentage-of-turnover cap", () => {
    const small = lateFeeRule("gstr9", { aato: 3 * CRORE });
    expect(small).toMatchObject({ perDay: 50, cap: 12000 });
    const mid = lateFeeRule("gstr9", { aato: 10 * CRORE });
    expect(mid).toMatchObject({ perDay: 100, cap: 40000 });
    const large = lateFeeRule("gstr9", { aato: 30 * CRORE, stateTurnover: 10 * CRORE });
    expect(large).toMatchObject({ perDay: 200, cap: 500000 });
  });

  it("leaves the GSTR-9 cap open when no turnover is given", () => {
    const r = calculateLateFee("gstr9", 30, {});
    expect(r.cap).toBeNull();
    expect(r.fee).toBe(1500);
    expect(r.capped).toBe(false);
  });

  it("applies the GSTR-9 cap once the daily fee exceeds it", () => {
    // ₹2.5 Cr turnover → cap 0.04% = ₹10,000; 300 days × ₹50 = ₹15,000.
    expect(calculateLateFee("gstr9", 300, { aato: 2.5 * CRORE })).toMatchObject({ fee: 10000, capped: true });
  });

  it("rejects an unknown return type", () => {
    expect(() => lateFeeRule("gstr99")).toThrow(/Unknown return type/);
  });
});

describe("calculateInterest", () => {
  it("computes 18% p.a. day-wise and rounds to the rupee", () => {
    expect(calculateInterest(100000, 30)).toBe(1479);
    expect(calculateInterest(100000, 365)).toBe(18000);
  });

  it("is zero without an amount or delay", () => {
    expect(calculateInterest(0, 30)).toBe(0);
    expect(calculateInterest(100000, 0)).toBe(0);
    expect(calculateInterest("", "")).toBe(0);
  });
});

describe("calculateLateReturnCost", () => {
  it("adds late fee, interest on cash tax, and interest on wrongly utilised ITC", () => {
    const r = calculateLateReturnCost({
      returnType: "gstr3b",
      dueDate: "2026-09-20",
      filingDate: "2026-10-20",
      aato: CRORE,
      cashTax: 100000,
      wrongItcUtilised: 50000,
      itcUtilisedSince: "2026-08-20",
    });
    expect(r.filedDays).toBe(30);
    expect(r.lateFee.fee).toBe(1500);
    expect(r.interestOnTax).toBe(1479);
    expect(r.itcDays).toBe(61);
    expect(r.interestOnItc).toBe(1504);
    expect(r.total).toBe(1500 + 1479 + 1504);
  });

  it("runs interest to a later payment date when tax is paid after filing", () => {
    const r = calculateLateReturnCost({
      returnType: "gstr3b",
      dueDate: "2026-09-20",
      filingDate: "2026-09-25",
      paymentDate: "2026-10-20",
      cashTax: 100000,
    });
    expect(r.filedDays).toBe(5);
    expect(r.paidDays).toBe(30);
    expect(r.interestOnTax).toBe(1479);
    expect(r.interestOnItc).toBe(0);
  });

  it("charges no interest on a nil return", () => {
    const r = calculateLateReturnCost({
      returnType: "gstr1",
      dueDate: "2026-09-11",
      filingDate: "2026-09-21",
      nil: true,
      cashTax: 5000,
    });
    expect(r.lateFee.fee).toBe(200);
    expect(r.interestOnTax).toBe(0);
    expect(r.total).toBe(200);
  });
});
