import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  CATEGORY_A_STATES, daysBetween, deadlinesForPeriod, deadlinesInMonth, nextDeadlines, todayInIndia,
} from "./returnDueDates";

const forms = (list) => list.map((d) => `${d.form} ${d.due}`);

describe("CATEGORY_A_STATES", () => {
  it("matches the backend's list, which drives the deadline alerts", () => {
    const src = readFileSync(resolve(__dirname, "../../../backend/app/services/filing_dates.py"), "utf8");
    const body = src.slice(src.indexOf("CATEGORY_A_STATES = frozenset("));
    const backend = [...body.slice(0, body.indexOf(")")).matchAll(/"(\d{2})"/g)].map((m) => m[1]);
    expect(backend.length).toBeGreaterThan(10);
    expect([...CATEGORY_A_STATES].sort()).toEqual(backend.sort());
  });
});

describe("deadlinesForPeriod", () => {
  it("gives a monthly filer GSTR-1 on the 11th and GSTR-3B on the 20th of the next month", () => {
    expect(forms(deadlinesForPeriod(2026, 12, "monthly"))).toEqual(["GSTR-1 2027-01-11", "GSTR-3B 2027-01-20"]);
  });

  it("gives a QRMP filer IFF and PMT-06 in the first two months of a quarter", () => {
    const d = deadlinesForPeriod(2026, 10, "quarterly", "27");
    expect(forms(d)).toEqual(["IFF 2026-11-13", "PMT-06 2026-11-25"]);
    expect(d[0].optional).toBe(true);
  });

  it("puts a Category A state's quarterly GSTR-3B on the 22nd and a Category B state's on the 24th", () => {
    expect(forms(deadlinesForPeriod(2026, 12, "quarterly", "27"))).toEqual(["GSTR-1 2027-01-13", "GSTR-3B 2027-01-22"]);
    expect(forms(deadlinesForPeriod(2026, 12, "quarterly", "07"))).toEqual(["GSTR-1 2027-01-13", "GSTR-3B 2027-01-24"]);
  });

  it("lists both GSTR-3B dates when no state is chosen, rather than guessing", () => {
    expect(deadlinesForPeriod(2026, 12, "quarterly").map((d) => d.form)).toEqual([
      "GSTR-1", "GSTR-3B (Category A states)", "GSTR-3B (Category B states)",
    ]);
  });

  it("hangs GSTR-9 off March, due 31 December of the year the FY ends", () => {
    const g9 = deadlinesForPeriod(2026, 3, "monthly").find((d) => d.form === "GSTR-9");
    expect(g9).toEqual(expect.objectContaining({ covers: "FY 2025-26", due: "2026-12-31" }));
  });

  it("gives a composition dealer CMP-08 on the 18th after each quarter and GSTR-4 on 30 April", () => {
    expect(forms(deadlinesForPeriod(2027, 3, "composition"))).toEqual(["CMP-08 2027-04-18", "GSTR-4 2027-04-30"]);
    expect(deadlinesForPeriod(2027, 2, "composition")).toEqual([]);
  });
});

describe("deadlinesInMonth", () => {
  it("collects December's monthly dates and the GSTR-9 for the previous FY, in date order", () => {
    expect(forms(deadlinesInMonth(2026, 12, "monthly"))).toEqual([
      "GSTR-1 2026-12-11", "GSTR-3B 2026-12-20", "GSTR-9 2026-12-31",
    ]);
  });

  it("shows no IFF in a month after a quarter end", () => {
    expect(deadlinesInMonth(2027, 1, "quarterly", "27").map((d) => d.form)).toEqual(["GSTR-1", "GSTR-3B"]);
  });
});

describe("nextDeadlines", () => {
  it("returns every return due on the next deadline date", () => {
    expect(forms(nextDeadlines("2026-10-28", "monthly"))).toEqual(["GSTR-1 2026-11-11"]);
    expect(forms(nextDeadlines("2026-11-12", "monthly"))).toEqual(["GSTR-3B 2026-11-20"]);
  });

  it("counts a deadline due today as next", () => {
    expect(forms(nextDeadlines("2026-11-20", "monthly"))).toEqual(["GSTR-3B 2026-11-20"]);
  });

  it("skips the optional IFF for a QRMP filer", () => {
    expect(forms(nextDeadlines("2026-11-01", "quarterly", "27"))).toEqual(["PMT-06 2026-11-25"]);
  });

  it("finds a composition dealer's next date across months with nothing due", () => {
    expect(forms(nextDeadlines("2027-02-01", "composition"))).toEqual(["CMP-08 2027-04-18"]);
  });
});

describe("dates", () => {
  it("counts whole days between ISO dates across a month end", () => {
    expect(daysBetween("2026-10-28", "2026-11-11")).toBe(14);
  });

  it("reads today in IST, so 8 pm UTC is already the next day in India", () => {
    expect(todayInIndia(new Date("2026-10-28T20:00:00Z"))).toBe("2026-10-29");
  });
});
