import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import GstRateFinderGuide from "./GstRateFinderGuide";
import HowToFileNilGstReturn from "./HowToFileNilGstReturn";
import Gstr1Gstr3bMismatchFix from "./Gstr1Gstr3bMismatchFix";

vi.mock("../../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

const CASES = [
  [GstRateFinderGuide, "GST Rate Finder: How to Find the Correct GST Rate for Any Product in 2026", "/hsn"],
  [HowToFileNilGstReturn, "How to File a Nil GST Return Online (and by SMS) in 2026", "/late-fee-calculator"],
  [Gstr1Gstr3bMismatchFix, "GSTR-1 vs GSTR-3B Mismatch: Why It Happens and How to Fix It", "/gstr2b-reconciliation"],
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
