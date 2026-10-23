import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import GstFilingMistakesToAvoid from "./GstFilingMistakesToAvoid";

vi.mock("../../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

function renderArticle() {
  return render(
    <MemoryRouter>
      <GstFilingMistakesToAvoid />
    </MemoryRouter>,
  );
}

describe("GstFilingMistakesToAvoid", () => {
  it("renders the title and all fifteen numbered mistakes", () => {
    renderArticle();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("GST Filing Mistakes to Avoid in 2026");
    const numbered = screen.getAllByRole("heading", { level: 3 }).filter((h) => /^\d+\./.test(h.textContent));
    expect(numbered).toHaveLength(15);
  });

  it("links to the new compliance tools", () => {
    renderArticle();
    for (const path of ["/gst-late-fee-interest-calculator", "/itc-reconciliation-dashboard", "/gstr9-summary", "/composition-tax-calculator"]) {
      expect(document.querySelector(`a[href="${path}"]`)).not.toBeNull();
    }
  });

  it("publishes Article and FAQ JSON-LD matching the on-page FAQs", () => {
    renderArticle();
    const ld = JSON.parse(document.getElementById("blog-ld-json").textContent);
    expect(ld.map((d) => d["@type"])).toEqual(["Article", "FAQPage"]);
    expect(ld[0].url).toBe("https://gst.doaide.com/blog/gst-filing-mistakes-to-avoid");
    for (const q of ld[1].mainEntity) {
      expect(screen.getByRole("heading", { level: 3, name: q.name })).toBeInTheDocument();
    }
  });

  it("states the current late fee caps, not the old flat ₹10,000", () => {
    renderArticle();
    expect(screen.getByText(/₹2,000 up to ₹1.5 crore/)).toBeInTheDocument();
  });

  it("removes its JSON-LD on unmount", () => {
    const { unmount } = renderArticle();
    unmount();
    expect(document.getElementById("blog-ld-json")).toBeNull();
  });
});
