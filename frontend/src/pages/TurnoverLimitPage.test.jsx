import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import TurnoverLimitPage, { determineThreshold, LOWER_LIMIT_STATES } from "./TurnoverLimitPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text, url) => `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
  twitterUrl: (text, url) => `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/api", () => ({
  api: { subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }) },
}));
vi.mock("../lib/track", () => ({ track: () => {} }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/turnover-limit"]}>
      <TurnoverLimitPage />
    </MemoryRouter>,
  );
}

describe("TurnoverLimitPage", () => {
  it("renders the page title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GST Registration Threshold Checker" })).toBeInTheDocument();
    expect(screen.getByText(/Check whether your business needs GST registration/)).toBeInTheDocument();
  });

  it("shows the ToolsNav component", () => {
    renderPage();
    expect(screen.getByRole("navigation", { name: "GST tools" })).toBeInTheDocument();
  });

  it("shows state selector", () => {
    renderPage();
    expect(screen.getByLabelText(/State/)).toBeInTheDocument();
  });

  it("shows no result before state is selected", () => {
    renderPage();
    expect(screen.queryByText("Required")).not.toBeInTheDocument();
    expect(screen.queryByText("Not Mandatory")).not.toBeInTheDocument();
  });

  it("shows required when turnover exceeds threshold", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(screen.getByLabelText(/State/), "Maharashtra");
    const turnoverInput = screen.getByPlaceholderText("Enter your annual turnover");
    await user.type(turnoverInput, "5000000");

    expect(screen.getByText("Required")).toBeInTheDocument();
  });

  it("shows not mandatory when turnover is below threshold", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(screen.getByLabelText(/State/), "Maharashtra");
    const turnoverInput = screen.getByPlaceholderText("Enter your annual turnover");
    await user.type(turnoverInput, "1000000");

    expect(screen.getByText("Not Mandatory")).toBeInTheDocument();
  });

  it("shows required when interstate checkbox is checked", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(screen.getByLabelText(/State/), "Maharashtra");
    await user.click(screen.getByLabelText(/Interstate supply/));

    expect(screen.getByText("Required")).toBeInTheDocument();
  });

  it("does not require registration at exactly the limit", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText(/State/), "Maharashtra");
    await user.type(screen.getByLabelText(/Aggregate Annual Turnover/), "4000000");
    expect(screen.getByText("Not Mandatory")).toBeInTheDocument();
  });

  it("lets an intra-state marketplace seller below the limit stay unregistered", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText(/State/), "Karnataka");
    await user.type(screen.getByLabelText(/Aggregate Annual Turnover/), "800000");
    await user.click(screen.getByLabelText(/e-commerce platform/));
    expect(screen.getByText("Not Mandatory")).toBeInTheDocument();
    expect(screen.getByText(/Notification 34\/2023-CT/)).toBeInTheDocument();
  });

  it("renders FAQ section and thresholds table", () => {
    renderPage();
    expect(screen.getByText("GST Registration Thresholds")).toBeInTheDocument();
    expect(screen.getByText("Frequently Asked Questions")).toBeInTheDocument();
  });
});

describe("determineThreshold", () => {
  it("returns 40 lakh for goods in normal states", () => {
    expect(determineThreshold("Maharashtra", "goods")).toBe(4000000);
  });

  it("returns 20 lakh for goods in special category states", () => {
    expect(determineThreshold("Sikkim", "goods")).toBe(2000000);
  });

  it("returns 20 lakh for services in normal states", () => {
    expect(determineThreshold("Gujarat", "services")).toBe(2000000);
  });

  it("returns 10 lakh for services in special category states", () => {
    expect(determineThreshold("Mizoram", "services")).toBe(1000000);
  });

  it("returns 20 lakh, not 40, for a business supplying both goods and services", () => {
    expect(determineThreshold("Maharashtra", "both")).toBe(2000000);
  });

  it("holds Telangana goods sellers at 20 lakh", () => {
    expect(determineThreshold("Telangana", "goods")).toBe(2000000);
  });
});

describe("LOWER_LIMIT_STATES", () => {
  it("holds the ten states outside the ₹40 lakh goods limit and no others", () => {
    expect(LOWER_LIMIT_STATES).toEqual([
      "Arunachal Pradesh", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
      "Puducherry", "Sikkim", "Telangana", "Tripura", "Uttarakhand",
    ]);
  });

  it("leaves Assam, Himachal Pradesh, J&K and Ladakh on the normal limits", () => {
    for (const st of ["Assam", "Himachal Pradesh", "Jammu and Kashmir", "Ladakh"]) {
      expect(LOWER_LIMIT_STATES).not.toContain(st);
      expect(determineThreshold(st, "goods")).toBe(4000000);
      expect(determineThreshold(st, "services")).toBe(2000000);
    }
  });
});
