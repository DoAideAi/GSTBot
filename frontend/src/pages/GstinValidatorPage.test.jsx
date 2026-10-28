import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { track } from "../lib/track";
import GstinValidatorPage from "./GstinValidatorPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../components/DeadlineBanner", () => ({ default: () => null }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text, url) => `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
  twitterUrl: (text, url) => `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/api", () => ({
  api: { subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }) },
}));
vi.mock("../lib/track", () => ({ track: vi.fn() }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/gstin-validator"]}>
      <GstinValidatorPage />
    </MemoryRouter>,
  );
}

describe("GstinValidatorPage", () => {
  it("reports a checked GSTIN to analytics by its state alone, never the PAN in it", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU0939F1ZV");
    expect(track).toHaveBeenCalledWith("gstin_validate", { state: "27" });
    expect(JSON.stringify(track.mock.calls)).not.toContain("AAPFU0939F");
  });

  it("renders the title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GSTIN Validator" })).toBeInTheDocument();
    expect(screen.getByText(/Validate the format of any GSTIN/)).toBeInTheDocument();
  });

  it("shows no result when input is empty", () => {
    renderPage();
    expect(screen.queryByText("Valid GSTIN")).not.toBeInTheDocument();
    expect(screen.queryByText("Invalid GSTIN")).not.toBeInTheDocument();
  });

  it("validates a correct GSTIN", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU0939F1ZV");
    expect(screen.getByText("Valid GSTIN")).toBeInTheDocument();
  });

  it("shows state name for valid GSTIN", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU0939F1ZV");
    expect(screen.getAllByText(/Maharashtra/).length).toBeGreaterThanOrEqual(1);
  });

  it("shows entity type decoded from PAN", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU0939F1ZV");
    expect(screen.getByText("Partnership Firm / LLP")).toBeInTheDocument();
  });

  it("shows error for too-short input", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU");
    expect(screen.getByText("Invalid GSTIN")).toBeInTheDocument();
    expect(screen.getByText(/must be exactly 15 characters/)).toBeInTheDocument();
  });

  it("shows error for wrong check digit", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU0939F1ZA");
    expect(screen.getByText("Invalid GSTIN")).toBeInTheDocument();
    expect(screen.getByText(/Invalid check digit/)).toBeInTheDocument();
  });

  it("shows error for invalid state code", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "00AAPFU0939F1ZV");
    expect(screen.getByText("Invalid GSTIN")).toBeInTheDocument();
    expect(screen.getByText(/Invalid state code/)).toBeInTheDocument();
  });

  it("shows the how-it-works section", () => {
    renderPage();
    expect(screen.getByText("How It Works")).toBeInTheDocument();
    expect(screen.getByText("Enter GSTIN")).toBeInTheDocument();
  });

  it("renders the FAQ section", () => {
    renderPage();
    expect(screen.getByText("How GSTIN Validation Works")).toBeInTheDocument();
    expect(screen.getByText("Frequently Asked Questions")).toBeInTheDocument();
  });
});
