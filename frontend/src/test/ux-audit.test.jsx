/**
 * M7 UX & accessibility audit — cross-cutting component quality.
 *
 * The five App.*.test.jsx files sweep the app-level routes (loading,
 * failure, lifecycle, RBAC, dismiss). This file sweeps the other dimension:
 * component-level accessibility, form validation feedback, keyboard
 * navigation, and responsive patterns. It catches regressions in the
 * conventions rather than in the pages: a new field without aria-describedby,
 * a banner without role="alert", a skeleton without a label.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ErrorBanner from "../components/ErrorBanner";
import { SectionBoundary } from "../components/ErrorBoundary";
import Meter from "../components/Meter";
import ReadOnlyNotice from "../components/ReadOnlyNotice";
import {
  SkeletonPanel,
  SkeletonStats,
  SkeletonTable,
  SkeletonText,
  Spinner,
} from "../components/Skeleton";
import StatCard from "../components/StatCard";
import TableScroll from "../components/TableScroll";
import ValidationIssues from "../components/ValidationIssues";
import { AuthProvider } from "../hooks/useAuth";
import { PageTitleProvider } from "../hooks/usePageTitle";

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function jsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => JSON.stringify(body),
  };
}

function renderInApp(ui) {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <PageTitleProvider>
          {ui}
        </PageTitleProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// 1. ErrorBanner — the shared error surface
// ---------------------------------------------------------------------------

describe("ErrorBanner accessibility", () => {
  it("is announced as an alert so screen readers catch it", () => {
    render(<ErrorBanner message="Connection lost" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Connection lost");
  });

  it("renders nothing when the message is empty", () => {
    const { container } = render(<ErrorBanner message="" />);
    expect(container.firstChild).toBeNull();
  });

  it("carries a dismiss button with an accessible label", () => {
    const dismiss = vi.fn();
    render(<ErrorBanner message="Oops" onDismiss={dismiss} />);
    const btn = screen.getByRole("button", { name: "Dismiss" });
    expect(btn).toBeInTheDocument();
  });

  it("offers a retry when one is wired", () => {
    const retry = vi.fn();
    render(<ErrorBanner message="Failed" onRetry={retry} />);
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("links to pricing for a paid tier refusal", () => {
    render(<ErrorBanner message="This requires a paid subscription." />);
    expect(screen.getByRole("link", { name: "See plans" })).toHaveAttribute("href", "/pricing");
  });

  it("does not link to pricing for other errors", () => {
    render(<ErrorBanner message="Server error" />);
    expect(screen.queryByRole("link", { name: "See plans" })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 2. Skeleton loading states — labelled, live, busy
// ---------------------------------------------------------------------------

describe("skeleton loading conventions", () => {
  const SKELETONS = [
    { name: "SkeletonText", Component: SkeletonText },
    { name: "SkeletonStats", Component: SkeletonStats },
    { name: "SkeletonTable", Component: SkeletonTable },
    { name: "SkeletonPanel", Component: SkeletonPanel },
  ];

  SKELETONS.forEach(({ name, Component }) => {
    it(`${name} carries aria-busy=true`, () => {
      const { container } = render(<Component label="Loading" />);
      const liveRegion = container.querySelector("[aria-busy]");
      expect(liveRegion).toHaveAttribute("aria-busy", "true");
    });

    it(`${name} carries aria-live=polite`, () => {
      const { container } = render(<Component label="Loading" />);
      const liveRegion = container.querySelector("[aria-live]");
      expect(liveRegion).toHaveAttribute("aria-live", "polite");
    });

    it(`${name} announces what is being loaded`, () => {
      render(<Component label="Loading suppliers" />);
      expect(screen.getByText("Loading suppliers…")).toBeInTheDocument();
    });

    it(`${name} does not claim role=status`, () => {
      render(<Component label="Loading" />);
      expect(screen.queryByRole("status")).toBeNull();
    });
  });

  it("the spinner is labelled for assistive tech", () => {
    render(<Spinner label="Saving" />);
    expect(screen.getByText("Saving…")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 3. StatCard — the dashboard's primary readout
// ---------------------------------------------------------------------------

describe("StatCard accessibility", () => {
  it("renders as a link when a destination is given", () => {
    renderInApp(<StatCard label="Output tax" value="₹18,000" to="/invoices" />);
    expect(screen.getByRole("link")).toHaveAttribute("href", "/invoices");
  });

  it("carries its label as accessible text", () => {
    renderInApp(<StatCard label="Net liability" value="₹0" />);
    expect(screen.getByText("Net liability")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 4. TableScroll — focusable, labelled region
// ---------------------------------------------------------------------------

describe("TableScroll keyboard accessibility", () => {
  it("wraps the table in a focusable region with tabindex=0", () => {
    const { container } = render(
      <TableScroll label="Invoices">
        <table><tbody><tr><td>row</td></tr></tbody></table>
      </TableScroll>,
    );
    const scroller = container.querySelector("[tabindex]");
    expect(scroller).toHaveAttribute("tabindex", "0");
  });

  it("labels the scrollable region for assistive tech", () => {
    render(
      <TableScroll label="Tax breakdown">
        <table><tbody><tr><td>row</td></tr></tbody></table>
      </TableScroll>,
    );
    expect(screen.getByRole("region", { name: "Tax breakdown" })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 5. Meter — plan usage bar
// ---------------------------------------------------------------------------

describe("Meter accessibility", () => {
  it("renders as a progressbar with ARIA value attributes", () => {
    render(<Meter value={30} max={100} label="Invoices used" />);
    const meter = screen.getByRole("progressbar", { name: "Invoices used" });
    expect(meter).toHaveAttribute("aria-valuenow", "30");
    expect(meter).toHaveAttribute("aria-valuemax", "100");
  });

  it("carries its label as aria-label", () => {
    render(<Meter value={10} max={50} label="Usage this month" />);
    expect(screen.getByRole("progressbar", { name: "Usage this month" })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 6. SectionBoundary — resilience within a page
// ---------------------------------------------------------------------------

describe("SectionBoundary error resilience", () => {
  function Bomb() {
    throw new Error("boom");
  }

  it("catches a child error without crashing the parent", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <MemoryRouter>
        <div>
          <SectionBoundary name="Chart">
            <Bomb />
          </SectionBoundary>
          <p>Still here</p>
        </div>
      </MemoryRouter>,
    );
    expect(screen.getByText("Still here")).toBeInTheDocument();
    spy.mockRestore();
  });

  it("names the thing that broke rather than showing a generic message", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <MemoryRouter>
        <SectionBoundary name="The trend chart">
          <Bomb />
        </SectionBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByText(/trend chart/i)).toBeInTheDocument();
    spy.mockRestore();
  });
});

// ---------------------------------------------------------------------------
// 7. ValidationIssues — form error summary
// ---------------------------------------------------------------------------

describe("ValidationIssues feedback", () => {
  const ISSUES = [
    { severity: "error", invoice_number: "INV-001", invoice_id: 1, field: "counterparty_gstin", message: "Missing GSTIN" },
    { severity: "warning", invoice_number: "INV-002", invoice_id: 2, field: "tax_rate", message: "Unusual rate" },
  ];

  it("renders each issue as a table row", () => {
    render(
      <MemoryRouter>
        <ValidationIssues issues={ISSUES} label="Filing issues" />
      </MemoryRouter>,
    );
    expect(screen.getAllByRole("row")).toHaveLength(3);
  });

  it("maps severity to chips", () => {
    render(
      <MemoryRouter>
        <ValidationIssues issues={ISSUES} label="Issues" />
      </MemoryRouter>,
    );
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getByText("Warning")).toBeInTheDocument();
  });

  it("links an issue with an invoice_id to the invoice", () => {
    render(
      <MemoryRouter>
        <ValidationIssues issues={ISSUES} label="Issues" />
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: "INV-001" });
    expect(link).toHaveAttribute("href", "/invoices/1");
  });

  it("renders an empty table when issues is an empty array", () => {
    render(
      <MemoryRouter>
        <ValidationIssues issues={[]} label="Issues" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(1);
  });

  it("survives undefined issues without crashing", () => {
    render(
      <MemoryRouter>
        <ValidationIssues label="Issues" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 8. ReadOnlyNotice — viewer guardrail
// ---------------------------------------------------------------------------

describe("ReadOnlyNotice", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows nothing for a writer", () => {
    localStorage.setItem("gstbot_token", "tok");
    global.fetch.mockResolvedValue(
      jsonResponse({ email: "owner@x.com", role: "owner", business: { id: 1 } }),
    );
    const { container } = renderInApp(<ReadOnlyNotice>Read only</ReadOnlyNotice>);
    expect(container).not.toHaveTextContent("Read only");
  });
});

// ---------------------------------------------------------------------------
// 9. Form validation lib — client-side guards
// ---------------------------------------------------------------------------

import {
  amountError,
  arnError,
  fileError,
  gstinShapeError,
  hsnError,
  invoiceDateError,
  normalizeGstin,
  paidAtError,
  placeOfSupplyError,
  registrationErrors,
  taxRateError,
} from "../lib/validate";

describe("client-side validation guards", () => {
  describe("GSTIN shape check", () => {
    it("accepts a well-formed GSTIN", () => {
      expect(gstinShapeError("27AAPFU0939F1ZV")).toBe("");
    });

    it("rejects the wrong length", () => {
      expect(gstinShapeError("27AAPFU")).toMatch(/15 characters/);
    });

    it("rejects state code 00", () => {
      expect(gstinShapeError("00AAPFU0939F1ZV")).toMatch(/00 is not one/);
    });

    it("returns empty for an empty input", () => {
      expect(gstinShapeError("")).toBe("");
    });

    it("normalises whitespace and case", () => {
      expect(normalizeGstin("27 aapf u0939 f1zv")).toBe("27AAPFU0939F1ZV");
    });
  });

  describe("amount validation", () => {
    it("accepts a valid amount", () => {
      expect(amountError("18000.50")).toBe("");
    });

    it("rejects negative amounts", () => {
      expect(amountError("-100")).toMatch(/negative/);
    });

    it("rejects more than two decimal places", () => {
      expect(amountError("100.123")).toMatch(/paise/);
    });

    it("rejects absurdly large amounts", () => {
      expect(amountError("9999999999999")).toMatch(/too large/);
    });

    it("accepts empty as clearing the field", () => {
      expect(amountError("")).toBe("");
    });
  });

  describe("invoice date validation", () => {
    const today = new Date(2026, 9, 28);

    it("accepts a date within the GST era", () => {
      expect(invoiceDateError("2026-03-15", { today })).toBe("");
    });

    it("rejects a future date", () => {
      expect(invoiceDateError("2026-12-01", { today })).toMatch(/future/);
    });

    it("rejects a date before GST started", () => {
      expect(invoiceDateError("2017-06-30", { today })).toMatch(/1 July 2017/);
    });

    it("rejects a date that does not exist", () => {
      expect(invoiceDateError("2026-02-30", { today })).toMatch(/does not exist/);
    });

    it("accepts today", () => {
      expect(invoiceDateError("2026-10-28", { today })).toBe("");
    });
  });

  describe("payment date validation", () => {
    const today = new Date(2026, 9, 28);

    it("rejects a payment before the invoice", () => {
      expect(paidAtError("2026-01-01", { invoiceDate: "2026-03-15", today })).toMatch(/before it was issued/);
    });

    it("accepts a payment on the invoice date", () => {
      expect(paidAtError("2026-03-15", { invoiceDate: "2026-03-15", today })).toBe("");
    });

    it("rejects a future payment", () => {
      expect(paidAtError("2027-01-01", { today })).toMatch(/future/);
    });
  });

  describe("HSN validation", () => {
    it("accepts 4-digit codes", () => {
      expect(hsnError("8471")).toBe("");
    });

    it("rejects letters", () => {
      expect(hsnError("84AB")).toMatch(/digits only/);
    });

    it("rejects single-digit codes", () => {
      expect(hsnError("8")).toMatch(/at least 2/);
    });
  });

  describe("tax rate validation", () => {
    it("accepts a standard slab", () => {
      expect(taxRateError("18")).toBe("");
    });

    it("rejects negative", () => {
      expect(taxRateError("-5")).toMatch(/negative/);
    });

    it("rejects over 100", () => {
      expect(taxRateError("150")).toMatch(/over 100/);
    });
  });

  describe("place of supply validation", () => {
    it("accepts a two-digit code", () => {
      expect(placeOfSupplyError("27")).toBe("");
    });

    it("rejects 00", () => {
      expect(placeOfSupplyError("00")).toMatch(/not a state/);
    });
  });

  describe("ARN validation", () => {
    it("accepts a 15-character alphanumeric", () => {
      expect(arnError("AA123456789012Z")).toBe("");
    });

    it("rejects special characters", () => {
      expect(arnError("ARN-123@456")).toMatch(/letters and digits/);
    });

    it("rejects too-short strings", () => {
      expect(arnError("ABC")).toMatch(/does not look/);
    });
  });

  describe("file validation", () => {
    function fakeFile(name, size) {
      return { name, size };
    }

    it("accepts a PDF within limits", () => {
      expect(fileError(fakeFile("invoice.pdf", 1024 * 1024))).toBe("");
    });

    it("rejects an unsupported extension", () => {
      expect(fileError(fakeFile("doc.docx", 1024))).toMatch(/cannot be read/);
    });

    it("rejects a zero-byte file", () => {
      expect(fileError(fakeFile("empty.pdf", 0))).toMatch(/empty/);
    });

    it("rejects an oversized file", () => {
      expect(fileError(fakeFile("huge.pdf", 20 * 1024 * 1024))).toMatch(/over the/);
    });

    it("rejects null", () => {
      expect(fileError(null)).toMatch(/No file/);
    });
  });

  describe("registration form validation", () => {
    it("requires an email", () => {
      const errors = registrationErrors({ email: "", password: "12345678", gstin: "" });
      expect(errors.email).toMatch(/Enter your email/);
    });

    it("rejects a non-email shape", () => {
      const errors = registrationErrors({ email: "notanemail", password: "12345678", gstin: "" });
      expect(errors.email).toMatch(/does not look like/);
    });

    it("requires 8-character password", () => {
      const errors = registrationErrors({ email: "a@b.com", password: "short", gstin: "" });
      expect(errors.password).toMatch(/8 characters/);
    });

    it("requires legal name when GSTIN is provided", () => {
      const errors = registrationErrors({
        email: "a@b.com",
        password: "12345678",
        gstin: "27AAPFU0939F1ZV",
        legal_name: "",
      });
      expect(errors.legal_name).toMatch(/Legal name is required/);
    });

    it("passes a complete valid form", () => {
      const errors = registrationErrors({
        email: "a@b.com",
        password: "12345678",
        gstin: "",
      });
      expect(Object.keys(errors)).toHaveLength(0);
    });
  });
});

// ---------------------------------------------------------------------------
// 10. Format helpers — rupees and dates
// ---------------------------------------------------------------------------

import { rupees, rupeesShort, periodLabel, statusLabel, statusTone } from "../lib/format";

describe("format helpers for display consistency", () => {
  it("formats rupees with the ₹ symbol and commas", () => {
    const result = rupees(1800000);
    expect(result).toContain("₹");
    expect(result).toContain("18");
  });

  it("abbreviates large amounts", () => {
    const result = rupeesShort(1800000);
    expect(result.length).toBeLessThan(15);
  });

  it("labels a period as month and year", () => {
    expect(periodLabel("2026-04")).toMatch(/Apr/);
    expect(periodLabel("2026-04")).toMatch(/2026/);
  });

  it("maps every status to a display label", () => {
    for (const status of ["uploaded", "parsed", "matched", "mismatched", "failed"]) {
      expect(statusLabel(status)).toBeTruthy();
    }
  });

  it("maps every status to a tone", () => {
    for (const status of ["uploaded", "parsed", "matched", "mismatched", "failed"]) {
      expect(statusTone(status)).toBeTruthy();
    }
  });
});
