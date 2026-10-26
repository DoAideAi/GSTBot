import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { allProducts } from "../lib/hsnData";
import GstRatesIndexPage, { FAQS, groupBySlab } from "./GstRatesIndexPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../lib/track", () => ({ track: () => {} }));

const rateLinks = () =>
  screen.queryAllByRole("link").filter((a) => a.getAttribute("href").startsWith("/gst-rate/"));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/gst-rates"]}>
      <GstRatesIndexPage />
    </MemoryRouter>,
  );
}

describe("groupBySlab", () => {
  it("orders slabs ascending and names A–Z within each", () => {
    const groups = groupBySlab([
      { product: "tea", hsn: "0902", rate: 5 },
      { product: "car", hsn: "8703", rate: 18 },
      { product: "milk", hsn: "0401", rate: 0 },
      { product: "coffee", hsn: "0901", rate: 5 },
    ]);
    expect(groups.map((g) => g.rate)).toEqual([0, 5, 18]);
    expect(groups[1].items.map((p) => p.product)).toEqual(["coffee", "tea"]);
  });
});

describe("GstRatesIndexPage", () => {
  it("links to a rate page for every listed product", () => {
    renderPage();
    expect(rateLinks()).toHaveLength(allProducts().length);
    expect(screen.getByRole("link", { name: "GST on Mobile Phone" })).toHaveAttribute("href", "/gst-rate/mobile-phone");
  });

  it("puts a product under its slab heading", () => {
    renderPage();
    const slab = screen.getByRole("region", { name: /^40% GST/ });
    expect(within(slab).getByRole("link", { name: "GST on Cigarettes" })).toBeInTheDocument();
  });

  it("filters by name and by HSN prefix", async () => {
    const user = userEvent.setup();
    renderPage();
    const box = screen.getByRole("searchbox");

    await user.type(box, "cement");
    expect(screen.getByRole("link", { name: "GST on Cement" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "GST on Laptop" })).not.toBeInTheDocument();

    await user.clear(box);
    await user.type(box, "8471");
    expect(screen.getByRole("link", { name: "GST on Laptop" })).toBeInTheDocument();
    expect(screen.getByText(/matching product/)).toBeInTheDocument();
  });

  it("points to the HSN finder when nothing matches", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByRole("searchbox"), "zzzz");
    expect(screen.getByRole("link", { name: "HSN code finder" })).toHaveAttribute("href", "/hsn");
    expect(rateLinks()).toHaveLength(0);
  });

  it("renders every FAQ visibly, matching the structured data", () => {
    renderPage();
    for (const f of FAQS) {
      expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
    }
  });
});
