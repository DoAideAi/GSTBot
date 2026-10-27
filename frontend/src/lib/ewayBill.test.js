import { describe, expect, it } from "vitest";
import { ewayBillRequired, looksLikeVehicleNumber, validityDays, validUntil } from "./ewayBill";

describe("ewayBillRequired", () => {
  it("a consignment of exactly ₹50,000 does not need a bill, one rupee more does", () => {
    expect(ewayBillRequired(50000)).toBe(false);
    expect(ewayBillRequired(50000.01)).toBe(true);
  });
});

describe("validityDays", () => {
  it("normal cargo gets a day per 200 km or part of it", () => {
    expect(validityDays(1)).toBe(1);
    expect(validityDays(200)).toBe(1);
    expect(validityDays(201)).toBe(2);
    expect(validityDays(1000)).toBe(5);
  });

  it("over-dimensional cargo gets a day per 20 km", () => {
    expect(validityDays(20, true)).toBe(1);
    expect(validityDays(21, true)).toBe(2);
    expect(validityDays(200, true)).toBe(10);
  });

  it("no distance gives no validity rather than a guessed one", () => {
    expect(validityDays(0)).toBeNull();
    expect(validityDays(NaN)).toBeNull();
  });
});

describe("validUntil", () => {
  it("a one-day bill runs to the end of the day after generation", () => {
    expect(validUntil("2026-10-05", 1)).toBe("2026-10-06");
  });

  it("crosses month and year ends", () => {
    expect(validUntil("2026-12-30", 3)).toBe("2027-01-02");
  });

  it("is empty without a date or a validity", () => {
    expect(validUntil("", 2)).toBeNull();
    expect(validUntil("2026-10-05", null)).toBeNull();
  });
});

describe("looksLikeVehicleNumber", () => {
  it("accepts ordinary and Bharat-series registrations, spaced or not", () => {
    expect(looksLikeVehicleNumber("MH12AB1234")).toBe(true);
    expect(looksLikeVehicleNumber("dl 1c aa 1234")).toBe(true);
    expect(looksLikeVehicleNumber("22BH1234AB")).toBe(true);
  });

  it("rejects text that is not a registration", () => {
    expect(looksLikeVehicleNumber("TRUCK")).toBe(false);
    expect(looksLikeVehicleNumber("MH12AB123")).toBe(false);
  });
});
