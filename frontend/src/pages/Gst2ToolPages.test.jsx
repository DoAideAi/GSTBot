import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Gst2MigrationCheckerPage from "./Gst2MigrationCheckerPage";
import Gst2RateComparisonPage from "./Gst2RateComparisonPage";
import InsuranceSavingsPage from "./InsuranceSavingsPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: () => "https://wa.me/",
  twitterUrl: () => "https://twitter.com/",
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/api", () => ({
  api: { subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }) },
}));
vi.mock("../lib/track", () => ({ track: vi.fn() }));

function renderIn(Page) {
  return render(
    <MemoryRouter>
      <Page />
    </MemoryRouter>,
  );
}

describe("Gst2MigrationCheckerPage", () => {
  it("shows the action note for the default contract type before any value", () => {
    renderIn(Gst2MigrationCheckerPage);
    expect(screen.getByRole("heading", { name: "GST 2.0 Migration Checker" })).toBeInTheDocument();
    expect(screen.getByText(/Renegotiate or add price adjustment clause/)).toBeInTheDocument();
    expect(screen.queryByText("GST Impact")).not.toBeInTheDocument();
  });

  it("computes the extra tax when a 12% contract moves to 18%", () => {
    renderIn(Gst2MigrationCheckerPage);
    fireEvent.change(screen.getByPlaceholderText("Enter base contract value"), { target: { value: "100000" } });
    expect(screen.getByText("Old GST (12%)")).toBeInTheDocument();
    expect(screen.getByText("₹12,000.00")).toBeInTheDocument();
    expect(screen.getByText("₹18,000.00")).toBeInTheDocument();
    expect(screen.getByText("+₹6,000.00")).toBeInTheDocument();
  });

  it("shows a saving when a 28% contract moves down to 18%", () => {
    renderIn(Gst2MigrationCheckerPage);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "supply_28" } });
    fireEvent.change(screen.getByPlaceholderText("Enter base contract value"), { target: { value: "100000" } });
    expect(screen.getByText("Old GST (28%)")).toBeInTheDocument();
    expect(screen.getByText("-₹10,000.00")).toBeInTheDocument();
  });

  it("zeroes the new GST for an insurance contract", () => {
    renderIn(Gst2MigrationCheckerPage);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "insurance_18" } });
    fireEvent.change(screen.getByPlaceholderText("Enter base contract value"), { target: { value: "50000" } });
    expect(screen.getByText("New GST (0%)")).toBeInTheDocument();
    expect(screen.getByText(/pass on full 18% savings/)).toBeInTheDocument();
  });
});

describe("Gst2RateComparisonPage", () => {
  it("stays quiet below two characters of query", () => {
    renderIn(Gst2RateComparisonPage);
    fireEvent.change(screen.getByPlaceholderText(/e.g. cement/), { target: { value: "c" } });
    expect(screen.queryByText("New Rate (GST 2.0)")).not.toBeInTheDocument();
    expect(screen.queryByText(/No matching products/)).not.toBeInTheDocument();
  });

  it("maps cement from the abolished 28% slab to 18%", () => {
    renderIn(Gst2RateComparisonPage);
    fireEvent.change(screen.getByPlaceholderText(/e.g. cement/), { target: { value: "cement" } });
    expect(screen.getByText("New Rate (GST 2.0)")).toBeInTheDocument();
    expect(screen.getAllByText(/cement/i).length).toBeGreaterThanOrEqual(1);
  });

  it("shows insurance dropping from 18% to 0%", () => {
    renderIn(Gst2RateComparisonPage);
    fireEvent.change(screen.getByPlaceholderText(/e.g. cement/), { target: { value: "insurance" } });
    expect(screen.getAllByText(/lower/).length).toBeGreaterThanOrEqual(1);
  });

  it("shows tobacco rising to the 40% demerit slab", () => {
    renderIn(Gst2RateComparisonPage);
    fireEvent.change(screen.getByPlaceholderText(/e.g. cement/), { target: { value: "tobacco" } });
    expect(screen.getAllByText(/higher/).length).toBeGreaterThanOrEqual(1);
  });

  it("says so when nothing matches", () => {
    renderIn(Gst2RateComparisonPage);
    fireEvent.change(screen.getByPlaceholderText(/e.g. cement/), { target: { value: "zzzzqqq" } });
    expect(screen.getByText(/No matching products found/)).toBeInTheDocument();
  });
});

describe("InsuranceSavingsPage", () => {
  it("shows no result before a premium is entered", () => {
    renderIn(InsuranceSavingsPage);
    expect(screen.getByRole("heading", { name: "Insurance GST Savings Calculator" })).toBeInTheDocument();
    expect(screen.queryByText("Annual Savings")).not.toBeInTheDocument();
  });

  it("backs the 18% GST out of an inclusive premium", () => {
    renderIn(InsuranceSavingsPage);
    fireEvent.change(screen.getByPlaceholderText("e.g. 25000"), { target: { value: "11800" } });
    expect(screen.getByText("₹10,000.00")).toBeInTheDocument();
    expect(screen.getAllByText("₹1,800.00/yr").length).toBe(2);
    expect(screen.queryByText(/Total Savings/)).not.toBeInTheDocument();
  });

  it("multiplies the saving across the remaining policy years", () => {
    renderIn(InsuranceSavingsPage);
    fireEvent.change(screen.getByPlaceholderText("e.g. 25000"), { target: { value: "11800" } });
    fireEvent.change(screen.getByPlaceholderText("1"), { target: { value: "3" } });
    expect(screen.getByText("Total Savings (3 years)")).toBeInTheDocument();
    expect(screen.getByText("₹5,400.00")).toBeInTheDocument();
  });

  it("falls back to one year when the term field is cleared", () => {
    renderIn(InsuranceSavingsPage);
    fireEvent.change(screen.getByPlaceholderText("e.g. 25000"), { target: { value: "11800" } });
    fireEvent.change(screen.getByPlaceholderText("1"), { target: { value: "" } });
    expect(screen.queryByText(/Total Savings/)).not.toBeInTheDocument();
    expect(screen.getAllByText("₹1,800.00/yr").length).toBe(2);
  });
});
