import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import GstRatePage from "./GstRatePage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text, url) => `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
  twitterUrl: (text, url) => `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));

function renderRate(product = "laptop") {
  return render(
    <MemoryRouter initialEntries={[`/gst-rate/${product}`]}>
      <Routes>
        <Route path="/gst-rate/:product" element={<GstRatePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("GstRatePage", () => {
  it("renders the product name in the title", () => {
    renderRate("laptop");

    expect(screen.getByText("GST Rate on Laptop")).toBeInTheDocument();
  });

  it("shows the GST rate for a known product", () => {
    renderRate("laptop");

    expect(screen.getByText("18%", { selector: ".rate-big" })).toBeInTheDocument();
  });

  it("shows the HSN code", () => {
    renderRate("laptop");

    expect(screen.getByText("8471")).toBeInTheDocument();
  });

  it("shows CGST and SGST breakdown", () => {
    renderRate("laptop");

    expect(screen.getByText("CGST")).toBeInTheDocument();
    expect(screen.getByText("SGST")).toBeInTheDocument();
    expect(screen.getAllByText("9%")).toHaveLength(2);
  });

  it("shows IGST rate", () => {
    renderRate("laptop");

    expect(screen.getByText("IGST")).toBeInTheDocument();
  });

  it("shows calculator link", () => {
    renderRate("laptop");

    expect(screen.getByText(/Calculate GST on Laptop/)).toBeInTheDocument();
  });

  it("shows share buttons for known product", () => {
    renderRate("laptop");

    expect(screen.getByLabelText("Share on WhatsApp")).toBeInTheDocument();
  });

  it("shows fallback for unknown product", () => {
    renderRate("xyznonexistent");

    expect(screen.getByText(/don't have a specific rate/)).toBeInTheDocument();
    expect(screen.getByText(/Search the HSN code directory/)).toBeInTheDocument();
  });

  it("shows related HSN codes when matches exist", () => {
    renderRate("cement");

    expect(screen.getByText("Related HSN Codes")).toBeInTheDocument();
  });

  it("handles hyphenated product names", () => {
    renderRate("mobile-phone");

    expect(screen.getByText("GST Rate on Mobile Phone")).toBeInTheDocument();
    expect(screen.getByText("8517")).toBeInTheDocument();
  });

  it("shows example GST calculation for taxable products", () => {
    renderRate("laptop");

    expect(screen.getByText("Example GST Calculation")).toBeInTheDocument();
    expect(screen.getByText("₹10,000")).toBeInTheDocument();
    expect(screen.getByText("₹1,800")).toBeInTheDocument();
    expect(screen.getByText("₹11,800")).toBeInTheDocument();
  });

  it("shows a fractional example amount to the paisa", () => {
    // 0.25% of ₹10,000 is ₹25, split ₹12.50 + ₹12.50; it printed "₹12.5".
    renderRate("diamond");

    expect(screen.getByText("₹25")).toBeInTheDocument();
    expect(screen.getAllByText("₹12.50")).toHaveLength(2);
    expect(screen.queryByText("₹12.5")).not.toBeInTheDocument();
  });

  it("does not show example calculation for zero-rate products", () => {
    renderRate("milk");

    expect(screen.queryByText("Example GST Calculation")).not.toBeInTheDocument();
  });

  it("shows cross-links to related products", () => {
    renderRate("laptop");

    expect(screen.getByText("Check GST Rates for Similar Products")).toBeInTheDocument();
  });

  it("shows breadcrumb navigation", () => {
    renderRate("laptop");

    expect(screen.getByRole("link", { name: "GST Rates List" })).toHaveAttribute("href", "/gst-rates");
    expect(screen.getByLabelText("Breadcrumb")).toBeInTheDocument();
  });

  it("shows product category when available", () => {
    renderRate("laptop");

    expect(screen.getByText("Category")).toBeInTheDocument();
    expect(screen.getByText("Electronics")).toBeInTheDocument();
  });

  it("injects JSON-LD structured data", () => {
    renderRate("laptop");

    const script = document.getElementById("seo-jsonld-0");
    expect(script).toBeTruthy();
    const data = JSON.parse(script.textContent);
    expect(data["@type"]).toBe("Product");
    expect(data.name).toBe("Laptop");
  });

  it("injects FAQPage schema", () => {
    renderRate("laptop");

    const script = document.getElementById("seo-jsonld-1");
    expect(script).toBeTruthy();
    const data = JSON.parse(script.textContent);
    expect(data["@type"]).toBe("FAQPage");
    expect(data.mainEntity.length).toBeGreaterThanOrEqual(2);
  });

  it("injects breadcrumb JSON-LD", () => {
    renderRate("laptop");

    const script = document.getElementById("seo-breadcrumb");
    expect(script).toBeTruthy();
    const data = JSON.parse(script.textContent);
    expect(data["@type"]).toBe("BreadcrumbList");
    expect(data.itemListElement[0].name).toBe("Home");
  });
});
