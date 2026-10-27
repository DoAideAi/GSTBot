import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import EwayBillPage from "./EwayBillPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
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
    <MemoryRouter initialEntries={["/eway-bill"]}>
      <EwayBillPage />
    </MemoryRouter>,
  );
}

describe("EwayBillPage", () => {
  it("renders the page title and subtitle", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "E-Way Bill Checker" })).toBeInTheDocument();
    expect(screen.getByText(/Check if your shipment requires an e-way bill/)).toBeInTheDocument();
  });

  it("shows supply type selector with three options", () => {
    renderPage();
    const select = screen.getByLabelText("Type of Supply");
    expect(select).toBeInTheDocument();
    expect(select.querySelectorAll("option")).toHaveLength(3);
  });

  it("shows the ToolsNav component", () => {
    renderPage();
    expect(screen.getByRole("navigation", { name: "GST tools" })).toBeInTheDocument();
  });

  it("shows not required for value below 50000", async () => {
    renderPage();
    const input = screen.getByPlaceholderText("Enter total consignment value");
    await userEvent.type(input, "30000");

    expect(screen.getByText("Not Required")).toBeInTheDocument();
  });

  it("shows required for value above 50000", async () => {
    renderPage();
    const input = screen.getByPlaceholderText("Enter total consignment value");
    await userEvent.type(input, "75000");

    expect(screen.getByText("Required")).toBeInTheDocument();
  });

  it("shows required for job work regardless of value", async () => {
    const user = userEvent.setup();
    renderPage();
    const select = screen.getByLabelText("Type of Supply");
    await user.selectOptions(select, "job_work");

    const input = screen.getByPlaceholderText("Enter total consignment value");
    await user.type(input, "1000");

    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(screen.getByText(/regardless of the consignment value/)).toBeInTheDocument();
  });

  it("shows validity in days when distance is entered", async () => {
    const user = userEvent.setup();
    renderPage();
    const valueInput = screen.getByPlaceholderText("Enter total consignment value");
    await user.type(valueInput, "100000");

    const distInput = screen.getByPlaceholderText("Enter distance in km");
    await user.type(distInput, "450");

    expect(screen.getByText(/3 days/)).toBeInTheDocument();
  });

  it("renders FAQ section", () => {
    renderPage();
    expect(screen.getByText("E-Way Bill Rules Under GST")).toBeInTheDocument();
    expect(screen.getByText("Frequently Asked Questions")).toBeInTheDocument();
  });

  it("a consignment of exactly ₹50,000 needs no bill", async () => {
    renderPage();
    await userEvent.type(screen.getByPlaceholderText("Enter total consignment value"), "50000");
    expect(screen.getByText("Not Required")).toBeInTheDocument();
  });

  it("over-dimensional cargo gets a day per 20 km, not 100", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByPlaceholderText("Enter total consignment value"), "100000");
    await user.type(screen.getByPlaceholderText("Enter distance in km"), "100");
    await user.selectOptions(screen.getByLabelText("Vehicle Type"), "over_dim");
    expect(screen.getByText("5 days")).toBeInTheDocument();
  });
});
