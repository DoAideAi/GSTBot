import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import GstOnRentalIncome from "./GstOnRentalIncome";
import GstRatesIndia2026List from "./GstRatesIndia2026List";

vi.mock("../../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

const CASES = [
  [GstOnRentalIncome, "GST on Rental Income in India 2026: Rates, Exemptions & RCM", "/rcm-calculator"],
  [GstRatesIndia2026List, "GST Rates in India 2026: Complete List of All Slabs", "/hsn"],
];

describe.each(CASES)("%o", (Article, title, toolPath) => {
  it("renders the title, a tool link and FAQ JSON-LD", () => {
    render(
      <MemoryRouter>
        <Article />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(title);
    expect(document.querySelector(`a[href="${toolPath}"]`)).not.toBeNull();
    const ld = JSON.parse(document.getElementById("blog-ld-json").textContent);
    expect(ld.map((d) => d["@type"])).toEqual(["Article", "FAQPage"]);
  });
});
