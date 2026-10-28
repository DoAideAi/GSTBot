import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import GstLatePenaltyCalculator from "./GstLatePenaltyCalculator";

vi.mock("../../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));

function renderArticle() {
  return render(
    <MemoryRouter>
      <GstLatePenaltyCalculator />
    </MemoryRouter>,
  );
}

describe("GstLatePenaltyCalculator", () => {
  it("renders the article title", () => {
    renderArticle();
    expect(screen.getByText("GST Late Filing Penalty Calculator 2026")).toBeInTheDocument();
  });

  it("renders key sections", () => {
    renderArticle();
    expect(screen.getByText("How GST Late Filing Penalties Work")).toBeInTheDocument();
    expect(screen.getByText("Late Fee Rates by Return Type (2026)")).toBeInTheDocument();
    expect(screen.getByText("Interest on Late GST Payment")).toBeInTheDocument();
  });

  it("renders the inline mini calculator", () => {
    renderArticle();
    expect(screen.getByText("Quick Penalty Estimate")).toBeInTheDocument();
    expect(screen.getByLabelText(/Days Late/)).toBeInTheDocument();
  });

  it("calculates penalty when days are entered", async () => {
    renderArticle();
    const user = userEvent.setup();
    const daysInput = screen.getByLabelText(/Days Late/);
    await user.type(daysInput, "30");
    const results = document.querySelectorAll(".calc-result");
    expect(results.length).toBeGreaterThan(0);
  });

  const lateFee = () =>
    [...document.querySelectorAll(".calc-result-row")]
      .find((row) => row.textContent.startsWith("Late Fee"))
      .querySelector("strong").textContent;

  it("charges a nil return ₹20 a day, capped at ₹500", async () => {
    renderArticle();
    const user = userEvent.setup();
    await user.click(screen.getByLabelText(/Nil return/));
    await user.type(screen.getByLabelText(/Days Late/), "20");
    expect(lateFee()).toBe("₹400");
    await user.clear(screen.getByLabelText(/Days Late/));
    await user.type(screen.getByLabelText(/Days Late/), "30");
    expect(lateFee()).toBe("₹500");
  });

  it("caps a GSTR-3B late fee by last year's turnover", async () => {
    renderArticle();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Days Late/), "300");
    expect(lateFee()).toBe("₹2,000");
    await user.type(screen.getByLabelText(/Turnover/), "40000000");
    expect(lateFee()).toBe("₹5,000");
    await user.clear(screen.getByLabelText(/Turnover/));
    await user.type(screen.getByLabelText(/Turnover/), "60000000");
    expect(lateFee()).toBe("₹10,000");
  });

  it("charges no interest on a nil return", async () => {
    renderArticle();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Unpaid Tax/), "100000");
    await user.click(screen.getByLabelText(/Nil return/));
    await user.type(screen.getByLabelText(/Days Late/), "10");
    expect(document.querySelector(".calc-result .calc-total strong").textContent).toBe("₹200.00");
  });

  it("renders FAQ section", () => {
    renderArticle();
    expect(screen.getByText("Frequently Asked Questions")).toBeInTheDocument();
    expect(screen.getByText("Can GST late fees be waived?")).toBeInTheDocument();
  });

  it("has internal links to penalty tools", () => {
    renderArticle();
    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/penalty-calculator");
    expect(hrefs).toContain("/late-fee-calculator");
  });

  it("has a CTA link to home", () => {
    renderArticle();
    const link = screen.getByText(/Try DoAide GST free/);
    expect(link.closest("a")).toHaveAttribute("href", "/");
  });
});
