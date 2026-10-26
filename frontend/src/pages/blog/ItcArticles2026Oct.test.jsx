import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ItcReversalRules from "./ItcReversalRules";
import LastDateToClaimItc from "./LastDateToClaimItc";

vi.mock("../../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

const CASES = [
  [LastDateToClaimItc, "Last Date to Claim ITC for FY 2025-26", "/itc-time-limit"],
  [ItcReversalRules, "ITC Reversal Under GST: Rule 37, 42 and 43", "/itc-reversal-rule-42"],
];

describe.each(CASES)("%o", (Article, title, toolPath) => {
  it("renders the title, links its tool, and publishes FAQ JSON-LD matching the visible FAQ", () => {
    render(<MemoryRouter><Article /></MemoryRouter>);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(title);
    expect(document.querySelector(`a[href="${toolPath}"]`)).not.toBeNull();
    const ld = JSON.parse(document.getElementById("blog-ld-json").textContent);
    expect(ld.map((d) => d["@type"])).toEqual(["Article", "FAQPage"]);
    for (const q of ld[1].mainEntity) expect(screen.getByRole("heading", { level: 3, name: q.name })).toBeInTheDocument();
  });

  it("writes its own meta description over the site default", () => {
    const meta = document.createElement("meta");
    meta.name = "description";
    meta.content = "site default";
    document.head.appendChild(meta);
    render(<MemoryRouter><Article /></MemoryRouter>);
    expect(meta.content).toMatch(/ITC|input tax credit/i);
    meta.remove();
  });
});
