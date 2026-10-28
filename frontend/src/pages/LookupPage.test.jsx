import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import LookupPage from "./LookupPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text, url) => `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
  twitterUrl: (text, url) => `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));

const mockTrack = vi.fn();
vi.mock("../lib/track", () => ({ track: (...args) => mockTrack(...args) }));

const mockValidateGstin = vi.fn();
vi.mock("../lib/api", () => ({
  api: {
    validateGstin: (...args) => mockValidateGstin(...args),
    recentLookups: () => Promise.resolve({ lookups: [] }),
  },
}));
vi.mock("../components/DeadlineBanner", () => ({ default: () => null }));
vi.mock("../components/RecentLookups", () => ({ default: () => null }));

function renderLookup(route = "/lookup") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/lookup" element={<LookupPage />} />
        <Route path="/gstin/:gstin" element={<LookupPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LookupPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the lookup title and input", () => {
    renderLookup();

    expect(screen.getByRole("heading", { name: "GSTIN Lookup" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/27AAPFU0939F1ZV/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verify GSTIN" })).toBeInTheDocument();
  });

  it("shows valid result after verification", async () => {
    mockValidateGstin.mockResolvedValue({
      valid: true,
      gstin: "27AAPFU0939F1ZV",
      state_code: "27",
      state_name: "Maharashtra",
      pan: "AAPFU0939F",
    });
    renderLookup();

    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU0939F1ZV");
    await userEvent.click(screen.getByText("Verify GSTIN"));

    expect(await screen.findByText("Valid GSTIN")).toBeInTheDocument();
    const result = screen.getByText("Valid GSTIN").closest(".lookup-result");
    expect(result).toHaveTextContent(/Maharashtra/);
    expect(screen.getByText("AAPFU0939F")).toBeInTheDocument();
  });

  it("shows invalid result for bad GSTIN", async () => {
    mockValidateGstin.mockResolvedValue({
      valid: false,
      gstin: "INVALID123",
      error: "Invalid check digit",
    });
    renderLookup();

    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "INVALID123ABCDE");
    await userEvent.click(screen.getByText("Verify GSTIN"));

    expect(await screen.findByText("Invalid GSTIN")).toBeInTheDocument();
  });

  it("shows error message on network failure", async () => {
    mockValidateGstin.mockRejectedValue(new Error("Network error"));
    renderLookup();

    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU0939F1ZV");
    await userEvent.click(screen.getByText("Verify GSTIN"));

    expect(await screen.findByText(/Could not reach the server/)).toBeInTheDocument();
  });

  it("says what the server said when it refused, rather than blaming the network", async () => {
    const refused = Object.assign(new Error("Too many requests (429). Please wait a moment and try again."), {
      status: 429,
    });
    mockValidateGstin.mockRejectedValue(refused);
    renderLookup();

    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU0939F1ZV");
    await userEvent.click(screen.getByText("Verify GSTIN"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/too many requests/i);
    expect(screen.queryByText(/could not reach the server/i)).not.toBeInTheDocument();
  });

  it("asks for a GSTIN when Verify is pressed on an empty box", async () => {
    mockValidateGstin.mockClear();
    renderLookup();
    await userEvent.click(screen.getByText("Verify GSTIN"));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a 15-character gstin/i);
    expect(mockValidateGstin).not.toHaveBeenCalled();
  });

  it("does not leave the last verdict up while, or after, checking another number", async () => {
    mockValidateGstin.mockResolvedValueOnce({
      valid: true,
      gstin: "27AAPFU0939F1ZV",
      state_code: "27",
      state_name: "Maharashtra",
      pan: "AAPFU0939F",
    });
    renderLookup();
    const box = screen.getByPlaceholderText(/27AAPFU0939F1ZV/);
    await userEvent.type(box, "27AAPFU0939F1ZV");
    await userEvent.click(screen.getByText("Verify GSTIN"));
    expect(await screen.findByText("Valid GSTIN")).toBeInTheDocument();

    mockValidateGstin.mockRejectedValueOnce(new Error("offline"));
    await userEvent.clear(box);
    await userEvent.type(box, "29AAACB1234C1Z5");
    await userEvent.click(screen.getByText("Verify GSTIN"));

    expect(await screen.findByText(/could not reach the server/i)).toBeInTheDocument();
    expect(screen.queryByText("Valid GSTIN")).not.toBeInTheDocument();
  });

  it("keeps the result region in the page so its first verdict is announced", () => {
    const { container } = renderLookup();
    expect(container.querySelector('[aria-live="polite"]')).toBeInTheDocument();
  });

  it("renders the info section about GSTIN format", () => {
    renderLookup();

    expect(screen.getByText("What Is a GSTIN?")).toBeInTheDocument();
    expect(screen.getByText("GSTIN Format")).toBeInTheDocument();
  });

  it("fires gstin_lookup tracking event on verification", async () => {
    mockValidateGstin.mockResolvedValue({
      valid: true,
      gstin: "27AAPFU0939F1ZV",
      state_code: "27",
      state_name: "Maharashtra",
      pan: "AAPFU0939F",
    });
    renderLookup();

    await userEvent.type(screen.getByPlaceholderText(/27AAPFU0939F1ZV/), "27AAPFU0939F1ZV");
    await userEvent.click(screen.getByText("Verify GSTIN"));

    await waitFor(() => {
      expect(mockTrack).toHaveBeenCalledWith("gstin_lookup", { state: "27", valid: true });
      expect(JSON.stringify(mockTrack.mock.calls)).not.toContain("AAPFU0939F");
    });
  });
});
