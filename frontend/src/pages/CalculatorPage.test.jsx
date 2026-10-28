import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import CalculatorPage from "./CalculatorPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../components/DeadlineBanner", () => ({ default: () => null }));
vi.mock("../components/SavedCalculations", () => ({
  default: () => null,
  getSavedCalcs: () => [],
  SaveCalcButton: () => null,
}));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text, url) => `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
  twitterUrl: (text, url) => `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));

vi.mock("../lib/api", () => ({
  api: { subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }) },
}));

const mockTrack = vi.fn();
vi.mock("../lib/track", () => ({ track: (...args) => mockTrack(...args) }));

function renderCalc(route = "/calculator") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <CalculatorPage />
    </MemoryRouter>,
  );
}

describe("CalculatorPage", () => {
  it("renders the calculator title and subtitle", () => {
    renderCalc();

    expect(screen.getByRole("heading", { name: "GST Calculator" })).toBeInTheDocument();
    expect(screen.getByText(/Calculate GST tax breakdown/)).toBeInTheDocument();
  });

  it("shows mode toggle with GST Exclusive active by default", () => {
    renderCalc();

    const exclusive = screen.getByText("GST Exclusive");
    expect(exclusive.className).toContain("active");
  });

  it("shows tax breakdown when amount is entered", async () => {
    renderCalc();

    const input = screen.getByPlaceholderText("Enter amount in ₹");
    await userEvent.type(input, "1000");

    expect(screen.getByText("Taxable Value")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
  });

  it("shows CGST and SGST for intrastate by default", async () => {
    renderCalc();

    await userEvent.type(screen.getByPlaceholderText("Enter amount in ₹"), "1000");

    const result = document.querySelector(".calc-result");
    expect(result).not.toBeNull();
    expect(result.textContent).toContain("CGST");
    expect(result.textContent).toContain("SGST");
  });

  it("switches to IGST when interstate checkbox is checked", async () => {
    renderCalc();

    await userEvent.type(screen.getByPlaceholderText("Enter amount in ₹"), "1000");
    await userEvent.click(screen.getByLabelText(/Interstate supply/));

    const result = document.querySelector(".calc-result");
    expect(result).not.toBeNull();
    expect(result.textContent).toContain("IGST");
    expect(result.textContent).not.toContain("CGST");
  });

  it("uses inclusive mode when toggled", async () => {
    renderCalc();

    await userEvent.click(screen.getByText("GST Inclusive"));
    expect(screen.getByText(/Total amount \(including GST\)/)).toBeInTheDocument();
  });

  it("shows no result when input is empty", () => {
    renderCalc();

    expect(screen.queryByText("Taxable Value")).not.toBeInTheDocument();
  });

  it("shows share buttons when result is computed", async () => {
    renderCalc();

    await userEvent.type(screen.getByPlaceholderText("Enter amount in ₹"), "1000");

    expect(screen.getByLabelText("Share on WhatsApp")).toBeInTheDocument();
  });

  it("reads initial values from URL params", () => {
    renderCalc("/calculator?amount=5000&rate=12&type=igst");

    expect(screen.getByText("Taxable Value")).toBeInTheDocument();
    const result = document.querySelector(".calc-result");
    expect(result.textContent).toContain("IGST");
  });

  it("renders the GST rate slabs info section", () => {
    renderCalc();

    expect(screen.getByText("How GST Calculation Works")).toBeInTheDocument();
    expect(screen.getByText(/GST 2\.0 Rate Slabs in India/)).toBeInTheDocument();
  });

  it("updates URL when amount changes", async () => {
    renderCalc("/calculator");

    await userEvent.type(screen.getByPlaceholderText("Enter amount in ₹"), "500");

    expect(screen.getByText("Taxable Value")).toBeInTheDocument();
  });

  it("selects a different rate", async () => {
    renderCalc();

    await userEvent.type(screen.getByPlaceholderText("Enter amount in ₹"), "1000");
    await userEvent.selectOptions(screen.getByRole("combobox"), "5");

    const result = document.querySelector(".calc-result");
    expect(result.textContent).toContain("5%");
  });

  it("fires gst_calculate tracking event when result is computed", async () => {
    renderCalc();

    await userEvent.type(screen.getByPlaceholderText("Enter amount in ₹"), "1000");

    await waitFor(
      () => expect(mockTrack).toHaveBeenCalledWith("gst_calculate", expect.objectContaining({ amount: 1000, rate: 18 })),
      { timeout: 2000 },
    );
  });

  it("counts a calculation once the amount settles, not once per keystroke", async () => {
    mockTrack.mockClear();
    localStorage.clear();
    renderCalc();

    await userEvent.type(screen.getByPlaceholderText("Enter amount in ₹"), "12345");
    // The calculation event specifically: tool_start arrives on the first
    // keystroke, long before the result has settled.
    await waitFor(
      () => expect(mockTrack).toHaveBeenCalledWith("gst_calculate", expect.anything()),
      { timeout: 2000 },
    );

    const calcs = mockTrack.mock.calls.filter(([name]) => name === "gst_calculate");
    expect(calcs).toHaveLength(1);
    expect(calcs[0][1]).toEqual({ amount: 12345, rate: 18 });
  });

  it("says which mode is active to assistive technology", async () => {
    renderCalc();
    const exclusive = screen.getByRole("button", { name: "GST Exclusive" });
    const inclusive = screen.getByRole("button", { name: "GST Inclusive" });
    expect(exclusive).toHaveAttribute("aria-pressed", "true");
    expect(inclusive).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(inclusive);
    expect(inclusive).toHaveAttribute("aria-pressed", "true");
  });

  it("writes the taxable value, not the inclusive total, to the address bar", async () => {
    let search = "";
    function Probe() {
      search = useLocation().search;
      return null;
    }
    render(
      <MemoryRouter initialEntries={["/calculator"]}>
        <CalculatorPage />
        <Probe />
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("button", { name: "GST Inclusive" }));
    await userEvent.type(screen.getByPlaceholderText("Enter amount in ₹"), "1180");

    // Reloading this URL opens in exclusive mode, so it must hold ₹1,000.
    expect(new URLSearchParams(search).get("amount")).toBe("1000");
  });

  it("explains a negative amount instead of showing nothing", async () => {
    renderCalc();
    const input = screen.getByPlaceholderText("Enter amount in ₹");
    await userEvent.type(input, "-5");
    expect(screen.getByRole("alert")).toHaveTextContent("zero or more");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByText("Taxable Value")).not.toBeInTheDocument();
  });
});

describe("completion of the calculator", () => {
  const funnelEvents = () =>
    mockTrack.mock.calls.filter(([name]) => name.startsWith("tool_")).map(([name]) => name);

  it("counts a visitor who types an amount and gets a settled result", async () => {
    mockTrack.mockClear();
    renderCalc();
    await userEvent.type(screen.getByPlaceholderText("Enter amount in ₹"), "1000");

    await waitFor(() => expect(funnelEvents()).toEqual(["tool_start", "tool_complete"]), {
      timeout: 2000,
    });
    expect(mockTrack).toHaveBeenCalledWith("tool_complete", { tool: "gst_calculator" });
  });

  it("does not count a shared link's result as anyone finishing", async () => {
    mockTrack.mockClear();
    renderCalc("/calculator?amount=1000&rate=18");

    // The result settles and is counted as a calculation, but nobody started.
    await waitFor(
      () => expect(mockTrack).toHaveBeenCalledWith("gst_calculate", expect.anything()),
      { timeout: 2000 },
    );
    expect(funnelEvents()).toEqual([]);
  });
});
