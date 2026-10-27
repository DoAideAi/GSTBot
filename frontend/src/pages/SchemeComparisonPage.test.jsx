import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import SchemeComparisonPage from "./SchemeComparisonPage";

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
    <MemoryRouter initialEntries={["/scheme-comparison"]}>
      <SchemeComparisonPage />
    </MemoryRouter>,
  );
}

describe("SchemeComparisonPage", () => {
  it("renders the title", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GST Scheme Comparison Calculator" })).toBeInTheDocument();
  });

  it("shows no result when inputs are empty", () => {
    renderPage();
    expect(screen.queryByText("Output Tax")).not.toBeInTheDocument();
  });

  it("calculates and shows comparison when turnover is entered", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText("Enter annual turnover"), "1000000");
    await userEvent.type(screen.getByPlaceholderText(/annual purchases/), "500000");
    expect(screen.getByText(/Output Tax/)).toBeInTheDocument();
    expect(screen.getByText(/Net Tax \(Regular\)/)).toBeInTheDocument();
    expect(screen.getByText(/Tax \(Composition @/)).toBeInTheDocument();
  });

  it("shows composition ineligible message for high turnover", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText("Enter annual turnover"), "20000000");
    expect(screen.getByText(/exceeds the Composition Scheme limit/)).toBeInTheDocument();
  });

  it("shows the bar chart when result is computed", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText("Enter annual turnover"), "1000000");
    expect(screen.getByRole("img", { name: /Tax comparison chart/ })).toBeInTheDocument();
  });

  it("shows the feature comparison table", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText("Enter annual turnover"), "1000000");
    expect(screen.getByText("Input Tax Credit")).toBeInTheDocument();
    expect(screen.getByText("Interstate Supply")).toBeInTheDocument();
  });

  it("shows the how-it-works section", () => {
    renderPage();
    expect(screen.getByText("How It Works")).toBeInTheDocument();
    expect(screen.getByText("Enter Details")).toBeInTheDocument();
  });

  it("a goods business in a special category state is over the limit above ₹75 lakh", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText("Enter annual turnover"), "8000000");
    expect(screen.queryByText(/exceeds the Composition Scheme limit/)).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("State of Registration"), "Sikkim");
    expect(screen.getByText(/exceeds the Composition Scheme limit \(₹75,00,000.00 in Sikkim\)/)).toBeInTheDocument();
  });

  it("a service provider's ₹50 lakh limit is the same in a special category state", async () => {
    renderPage();
    await userEvent.selectOptions(screen.getByLabelText("Business Type"), "service");
    await userEvent.selectOptions(screen.getByLabelText("State of Registration"), "Sikkim");
    await userEvent.type(screen.getByPlaceholderText("Enter annual turnover"), "4000000");
    expect(screen.queryByText(/exceeds the Composition Scheme limit/)).not.toBeInTheDocument();
  });

  it("splits both schemes' tax into CGST and the state's own levy", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText("Enter annual turnover"), "1000000");
    await userEvent.type(screen.getByPlaceholderText(/annual purchases/), "500000");
    const table = screen.getByRole("table", { name: "Annual tax under each scheme" });
    const net = within(table).getByText("Net payable").closest("tr");
    expect(within(net).getByText("₹90,000.00")).toBeInTheDocument();
    expect(within(net).getByText("₹10,000.00")).toBeInTheDocument();
    expect(within(table).getByText("SGST")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("State of Registration"), "Chandigarh");
    expect(within(table).getByText("UTGST")).toBeInTheDocument();
  });

  it("offers neither retired state codes nor the non-state codes", () => {
    renderPage();
    const options = within(screen.getByLabelText("State of Registration")).getAllByRole("option").map((o) => o.textContent);
    expect(options).not.toContain("Daman and Diu");
    expect(options).not.toContain("Centre Jurisdiction");
    expect(options).toContain("Ladakh");
  });
});
