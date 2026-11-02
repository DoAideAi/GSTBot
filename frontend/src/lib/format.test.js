import { describe, expect, it } from "vitest";
import {
  currentPeriod,
  dateLabel,
  daysUntil,
  periodLabel,
  previousPeriod,
  rupees,
  rupeesShort,
  statusLabel,
  statusTone,
} from "./format";

describe("rupees", () => {
  it("uses the Indian digit grouping", () => {
    // 1,23,456 rather than 123,456 — this is what an Indian business reads.
    expect(rupees("123456.78")).toContain("1,23,456.78");
  });

  it("formats a string without going through a float", () => {
    expect(rupees("531000.00")).toContain("5,31,000.00");
  });

  it("falls back to zero on junk", () => {
    expect(rupees(null)).toContain("0.00");
    expect(rupees("not a number")).toContain("0.00");
  });
});

describe("rupeesShort", () => {
  it("uses lakh and crore", () => {
    expect(rupeesShort(12300000)).toBe("₹1.23Cr");
    expect(rupeesShort(531000)).toBe("₹5.31L");
    expect(rupeesShort(5310)).toBe("₹5.3K");
    expect(rupeesShort(531)).toBe("₹531");
  });

  it("handles zero and junk", () => {
    expect(rupeesShort(0)).toBe("₹0");
    expect(rupeesShort(undefined)).toBe("₹0");
  });

  it("falls back to zero rather than rendering NaN on a tile", () => {
    // The stat tiles feed this straight from the API. A total that arrived as
    // a word would otherwise read "₹NaNCr", which is worse than a wrong zero:
    // it looks like a display bug rather than like missing data.
    expect(rupeesShort("not a number")).toBe("₹0");
    expect(rupeesShort(Infinity)).toBe("₹0");
  });
});

describe("periodLabel", () => {
  it("expands a filing period", () => {
    expect(periodLabel("2026-04")).toBe("April 2026");
  });

  it("passes anything that is not a period straight through", () => {
    expect(periodLabel("garbage")).toBe("garbage");
    expect(periodLabel(null)).toBe("");
  });
});

describe("dateLabel", () => {
  it("formats an ISO date", () => {
    expect(dateLabel("2026-04-15")).toBe("15 Apr 2026");
  });

  it("shows a dash for nothing", () => {
    expect(dateLabel(null)).toBe("—");
  });

  it("does not shift an ISO date backwards in a western timezone", () => {
    // The reason toLocalDate exists: `new Date("2026-04-15")` is UTC midnight,
    // which is the 14th anywhere west of Greenwich. A GST invoice date is a
    // calendar date, and showing the wrong one moves it into another period.
    expect(dateLabel("2026-04-15")).toBe("15 Apr 2026");
    expect(dateLabel("2026-01-01")).toBe("01 Jan 2026");
  });

  it("formats a Date it is handed directly", () => {
    expect(dateLabel(new Date(2026, 3, 15))).toBe("15 Apr 2026");
  });

  it("leaves a full timestamp to the engine", () => {
    // created_at comes back as an instant rather than a calendar date, so it
    // keeps the normal parse — the date-only workaround would drop the time.
    expect(dateLabel("2026-04-15T09:30:00Z")).toMatch(/2026$/);
  });

  it("returns the original value when it is not a date at all", () => {
    expect(dateLabel("not a date")).toBe("not a date");
  });
});

describe("currentPeriod", () => {
  it("zero-pads the month", () => {
    expect(currentPeriod(new Date(2026, 0, 15))).toBe("2026-01");
    expect(currentPeriod(new Date(2026, 11, 1))).toBe("2026-12");
  });
});

describe("previousPeriod", () => {
  it("returns the month before the given date", () => {
    expect(previousPeriod(new Date(2026, 4, 15))).toBe("2026-04");
  });

  it("wraps around the year boundary", () => {
    expect(previousPeriod(new Date(2026, 0, 1))).toBe("2025-12");
  });

  it("zero-pads the month", () => {
    expect(previousPeriod(new Date(2026, 1, 28))).toBe("2026-01");
  });
});

describe("daysUntil", () => {
  const now = new Date(2026, 4, 15); // 15 May 2026

  it("counts forward to a due date", () => {
    expect(daysUntil("2026-05-20", now)).toBe(5);
  });

  it("goes negative once the deadline has passed", () => {
    expect(daysUntil("2026-05-10", now)).toBe(-5);
  });

  it("is zero on the day itself", () => {
    expect(daysUntil("2026-05-15", now)).toBe(0);
  });

  it("returns null when there is no date", () => {
    expect(daysUntil(null)).toBeNull();
  });

  it("returns null for a date it cannot parse", () => {
    // Callers render this as "due in N days" and compare it against zero to
    // decide overdue. NaN would satisfy neither branch and would print as
    // "due in NaN days"; null is the value they already handle as "no date".
    expect(daysUntil("not a date", now)).toBeNull();
  });
});

describe("status helpers", () => {
  it("labels every status the API can return", () => {
    expect(statusLabel("missing_in_2b")).toBe("Missing in 2B");
    expect(statusLabel("parsed")).toBe("Parsed");
  });

  it("renders nothing for a row with no status at all", () => {
    expect(statusLabel(null)).toBe("");
    expect(statusLabel(undefined)).toBe("");
  });

  it("maps a status to a tone", () => {
    expect(statusTone("matched")).toBe("good");
    expect(statusTone("mismatched")).toBe("warn");
    expect(statusTone("failed")).toBe("bad");
    expect(statusTone("uploaded")).toBe("neutral");
  });
});

describe("linkedPeriod", () => {
  it("keeps a valid linked period and falls back for absent or invalid values", async () => {
    const { linkedPeriod } = await import("./format");
    expect(linkedPeriod("?period=2026-10", "2026-11")).toBe("2026-10");
    for (const value of ["", "?period=2026-13", "?period=2017-06", "?period=https://evil.example"]) {
      expect(linkedPeriod(value, "2026-11")).toBe("2026-11");
    }
  });
});
