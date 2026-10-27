import { describe, expect, it } from "vitest";
import { checkRegistration, STATES, thresholdFor } from "./gstRegistration";

const check = (o) => checkRegistration({ type: "goods", state: "Maharashtra", ...o });

describe("thresholdFor", () => {
  it("gives exclusive goods suppliers ₹40 lakh in an opted-in state", () => {
    expect(thresholdFor("goods", "Maharashtra")).toEqual({ limit: 4000000, section: "Section 22(1) with Notification 10/2019-CT" });
  });

  it("keeps Assam, Himachal Pradesh and Jammu and Kashmir at ₹40 lakh for goods and ₹20 lakh for services", () => {
    for (const s of ["Assam", "Himachal Pradesh", "Jammu and Kashmir"]) {
      expect(thresholdFor("goods", s).limit).toBe(4000000);
      expect(thresholdFor("services", s).limit).toBe(2000000);
    }
  });

  it("holds goods at ₹20 lakh in the states that did not adopt ₹40 lakh, Telangana and Puducherry included", () => {
    for (const s of ["Telangana", "Puducherry", "Uttarakhand", "Sikkim", "Meghalaya", "Arunachal Pradesh"]) {
      expect(thresholdFor("goods", s)).toEqual({ limit: 2000000, section: "Section 22(1)" });
    }
  });

  it("applies ₹10 lakh to goods and services alike in Manipur, Mizoram, Nagaland and Tripura only", () => {
    for (const s of ["Manipur", "Mizoram", "Nagaland", "Tripura"]) {
      expect(thresholdFor("goods", s).limit).toBe(1000000);
      expect(thresholdFor("services", s).limit).toBe(1000000);
    }
    expect(thresholdFor("services", "Sikkim").limit).toBe(2000000);
  });

  it("uses the services limit for a business supplying both", () => {
    expect(thresholdFor("both", "Maharashtra").limit).toBe(2000000);
  });
});

describe("checkRegistration", () => {
  it("requires registration only when turnover exceeds the limit, not when it equals it", () => {
    expect(check({ turnover: "4000000" }).required).toBe(false);
    const over = check({ turnover: "4000001" });
    expect(over.required).toBe(true);
    expect(over.reasons[0].section).toBe("Section 22(1) with Notification 10/2019-CT");
  });

  it("makes inter-state goods sellers register from the first sale under Section 24(i)", () => {
    const r = check({ turnover: "100000", interState: true });
    expect(r.required).toBe(true);
    expect(r.reasons).toHaveLength(1);
    expect(r.reasons[0].section).toBe("Section 24(i)");
  });

  it("cites Section 24(ix) too when the inter-state goods go through a marketplace", () => {
    expect(check({ turnover: "100000", interState: true, ecommerce: true }).reasons[0].section).toBe("Section 24(i) and 24(ix)");
  });

  it("lets inter-state service providers stay unregistered below the limit", () => {
    const r = check({ type: "services", turnover: "1500000", interState: true });
    expect(r.required).toBe(false);
    expect(r.notes[0]).toMatch(/Notification 10\/2017-Integrated Tax/);
  });

  it("lets intra-state marketplace goods sellers stay unregistered below the limit", () => {
    const r = check({ turnover: "500000", ecommerce: true });
    expect(r.required).toBe(false);
    expect(r.notes[0]).toMatch(/Notification 34\/2023-CT/);
  });

  it("lets marketplace service sellers stay unregistered below the limit", () => {
    const r = check({ type: "services", turnover: "500000", ecommerce: true });
    expect(r.required).toBe(false);
    expect(r.notes[0]).toMatch(/Notification 65\/2017-CT/);
  });

  it("treats a 'both' business's inter-state sales as goods sales", () => {
    expect(check({ type: "both", turnover: "100000", interState: true }).required).toBe(true);
  });

  it("requires casual, non-resident and ISD registrations with no turnover or state", () => {
    expect(checkRegistration({ type: "casual" }).reasons[0].section).toBe("Section 24(ii)");
    expect(checkRegistration({ type: "nonresident" }).reasons[0].section).toBe("Section 24(v)");
    expect(checkRegistration({ type: "isd" }).reasons[0].section).toBe("Section 24(viii)");
  });

  it("reminds a ₹40 lakh goods supplier that ice cream, pan masala and tobacco are excluded", () => {
    expect(check({ turnover: "100000" }).notes.join(" ")).toMatch(/pan masala/);
    expect(check({ turnover: "100000", state: "Telangana" }).notes).toEqual([]);
  });

  it("waits for a valid turnover, a state and a known type", () => {
    expect(check({ turnover: "" })).toBeNull();
    expect(check({ turnover: "-1" })).toBeNull();
    expect(check({ turnover: "abc" })).toBeNull();
    expect(check({ turnover: "100", state: "" })).toBeNull();
    expect(check({ turnover: "100", type: "nope" })).toBeNull();
  });
});

describe("STATES", () => {
  it("lists every state and UT once, without the retired or non-state codes", () => {
    expect(STATES).toContain("Ladakh");
    expect(STATES).toContain("Telangana");
    expect(STATES).not.toContain("Other Territory");
    expect(STATES).not.toContain("Daman and Diu");
    expect(STATES.filter((s) => s.startsWith("Andhra Pradesh"))).toEqual(["Andhra Pradesh"]);
    expect(new Set(STATES).size).toBe(STATES.length);
  });
});
