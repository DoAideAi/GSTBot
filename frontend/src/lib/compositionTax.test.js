import { describe, expect, it } from "vitest";
import {
  categoryFor,
  cmp08DueDate,
  compositionYear,
  emptyQuarters,
  gstr4DueDate,
  quarterTax,
  turnoverLimit,
} from "./compositionTax";

function quarters(rows) {
  return emptyQuarters().map((q, i) => ({ ...q, ...(rows[i] || {}) }));
}

describe("dates and limits", () => {
  it("puts CMP-08 on the 18th after each quarter and GSTR-4 on 30 April", () => {
    expect(cmp08DueDate("2025-26", 0)).toBe("2025-07-18");
    expect(cmp08DueDate("2025-26", 1)).toBe("2025-10-18");
    expect(cmp08DueDate("2025-26", 2)).toBe("2026-01-18");
    expect(cmp08DueDate("2025-26", 3)).toBe("2026-04-18");
    expect(cmp08DueDate("nope", 0)).toBeNull();
    expect(gstr4DueDate("2025-26")).toBe("2026-04-30");
    expect(gstr4DueDate("")).toBeNull();
  });

  it("uses ₹1.5 Cr for goods, ₹75 L in special category states, ₹50 L for services", () => {
    expect(turnoverLimit("trader")).toBe(15000000);
    expect(turnoverLimit("restaurant", true)).toBe(7500000);
    expect(turnoverLimit("service", true)).toBe(5000000);
  });

  it("falls back to manufacturer for an unknown category", () => {
    expect(categoryFor("x").key).toBe("manufacturer");
  });
});

describe("quarterTax", () => {
  const q = { taxable: "1000000", exempt: "200000", rcmValue: "50000", rcmRate: "18" };

  it("charges manufacturers 1% on total turnover including exempt supplies", () => {
    expect(quarterTax("manufacturer", q)).toMatchObject({ base: 1200000, compTax: 12000, cgst: 6000, sgst: 6000, rcmTax: 9000, total: 21000 });
  });

  it("charges traders 1% on taxable supplies only", () => {
    expect(quarterTax("trader", q)).toMatchObject({ base: 1000000, compTax: 10000 });
  });

  it("charges restaurants 5% on total and 10(2A) services 6% on taxable", () => {
    expect(quarterTax("restaurant", q).compTax).toBe(60000);
    expect(quarterTax("service", q).compTax).toBe(60000);
  });

  it("ignores blanks and negatives", () => {
    expect(quarterTax("trader", { taxable: "-5", exempt: "", rcmValue: "abc", rcmRate: "18" })).toMatchObject({ compTax: 0, rcmTax: 0, total: 0 });
  });
});

describe("compositionYear", () => {
  it("returns null with no figures", () => {
    expect(compositionYear({ quarters: emptyQuarters() })).toBeNull();
    expect(compositionYear()).toBeNull();
  });

  it("totals the year for GSTR-4 and tracks limit usage", () => {
    const y = compositionYear({
      category: "trader",
      quarters: quarters([{ taxable: "2000000" }, { taxable: "2500000" }, { taxable: "3000000" }, { taxable: "2500000", exempt: "500000" }]),
    });
    expect(y.annualTurnover).toBe(10500000);
    expect(y.totalCompTax).toBe(100000);
    expect(y.limitUsedPct).toBe(70);
    expect(y.breached).toBe(false);
    expect(y.gstr4DueDate).toBe("2026-04-30");
    expect(y.quarters[3].cumulative).toBe(10500000);
  });

  it("flags the quarter in which cumulative turnover crosses the limit", () => {
    const y = compositionYear({
      category: "service",
      quarters: quarters([{ taxable: "2000000" }, { taxable: "2000000" }, { taxable: "1500000" }]),
    });
    expect(y.limit).toBe(5000000);
    expect(y.breached).toBe(true);
    expect(y.breachQuarter).toBe(2);
  });

  it("charges 18% interest on the whole CMP-08 amount paid after the 18th", () => {
    // Q1 tax: 1% of ₹36.5 L = ₹36,500; paid 365 days late → ₹6,570 interest.
    const y = compositionYear({
      category: "manufacturer",
      quarters: quarters([{ taxable: "3650000", paidOn: "2026-07-18" }, { taxable: "100000", paidOn: "2025-10-10" }]),
    });
    expect(y.quarters[0]).toMatchObject({ compTax: 36500, daysLate: 365, interest: 6570, payable: 43070 });
    expect(y.quarters[1]).toMatchObject({ daysLate: 0, interest: 0 });
    expect(y.totalInterest).toBe(6570);
    expect(y.totalPayable).toBe(43070 + 1000);
  });

  it("counts a quarter with only reverse-charge purchases", () => {
    const y = compositionYear({ quarters: quarters([{ rcmValue: "100000", rcmRate: "5" }]) });
    expect(y.totalRcmTax).toBe(5000);
    expect(y.totalCompTax).toBe(0);
  });
});
