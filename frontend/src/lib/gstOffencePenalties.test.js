import { describe, expect, it } from "vitest";
import { computeOffencePenalty, VIOLATIONS } from "./gstOffencePenalties";

const total = (violation, amount, interState = false) =>
  computeOffencePenalty({ violation, amount, interState }).total;

describe("computeOffencePenalty", () => {
  it("charges the tax evaded when it exceeds the floor, split across CGST and SGST", () => {
    const r = computeOffencePenalty({ violation: "evasion", amount: "500000" });
    expect(r.total).toBe(500000);
    expect(r.perAct).toEqual([
      { act: "CGST Act", penalty: 250000 },
      { act: "SGST/UTGST Act", penalty: 250000 },
    ]);
    expect(r.floorApplied).toBe(false);
  });

  it("applies the ₹10,000 floor in each Act, so a small intra-state evasion costs ₹20,000", () => {
    const r = computeOffencePenalty({ violation: "evasion", amount: "8000" });
    expect(r.total).toBe(20000);
    expect(r.floorApplied).toBe(true);
  });

  it("applies the floor once for an inter-state case under the IGST Act", () => {
    expect(total("evasion", "8000", true)).toBe(10000);
    expect(total("evasion", "300000", true)).toBe(300000);
  });

  it("treats fake invoices, unregistered trading and fraudulent refunds as greater-of", () => {
    expect(total("fake_invoice", "100000")).toBe(100000);
    expect(total("not_registered", "0")).toBe(20000);
    expect(total("refund", "750000")).toBe(750000);
    expect(total("refund", "12000")).toBe(20000);
  });

  it("gives Section 125 as a ceiling of ₹25,000 per Act, no amount needed", () => {
    const r = computeOffencePenalty({ violation: "general", amount: "" });
    expect(r.total).toBe(50000);
    expect(r.upTo).toBe(true);
    expect(total("invoice_error", "", true)).toBe(25000);
  });

  it("charges ₹100 a day per Act for a late information return, capped at ₹5,000", () => {
    expect(total("info_return", "10")).toBe(2000);
    expect(total("info_return", "10", true)).toBe(1000);
    expect(total("info_return", "400")).toBe(10000);
  });

  it("sends an unfiled return to the late fee instead of a penalty figure", () => {
    expect(computeOffencePenalty({ violation: "not_filed" })).toEqual({
      violation: VIOLATIONS.find((v) => v.key === "not_filed"),
      lateFee: true,
    });
  });

  it("refuses a missing, negative or non-numeric amount, and an unknown violation", () => {
    expect(computeOffencePenalty({ violation: "evasion", amount: "" })).toBeNull();
    expect(computeOffencePenalty({ violation: "evasion", amount: "-1" })).toBeNull();
    expect(computeOffencePenalty({ violation: "evasion", amount: "abc" })).toBeNull();
    expect(computeOffencePenalty({ violation: "nope", amount: "100" })).toBeNull();
  });

  it("cites a CGST Act section for every violation", () => {
    for (const v of VIOLATIONS) expect(v.section).toMatch(/^Section 12[235]|^Section 47/);
  });
});
