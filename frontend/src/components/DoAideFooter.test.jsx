import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DoAideFooter from "./DoAideFooter";

describe("DoAideFooter", () => {
  it("renders the heading", () => {
    render(<DoAideFooter />);
    expect(screen.getByText("More free tools from DoAide")).toBeInTheDocument();
  });

  it("renders the cross-product tools", () => {
    render(<DoAideFooter />);
    expect(screen.getByText("Invoicer")).toBeInTheDocument();
    expect(screen.getByText("Contracts")).toBeInTheDocument();
    expect(screen.getByText("InsureKit")).toBeInTheDocument();
    expect(screen.getByText("TaxFile")).toBeInTheDocument();
    expect(screen.getByText("Pulse")).toBeInTheDocument();
  });

  it("links to the correct domains", () => {
    render(<DoAideFooter />);
    expect(screen.getByText("Invoicer").closest("a")).toHaveAttribute(
      "href",
      "https://invoicer.doaide.com",
    );
    expect(screen.getByText("Contracts").closest("a")).toHaveAttribute(
      "href",
      "https://contracts.doaide.com",
    );
    expect(screen.getByText("InsureKit").closest("a")).toHaveAttribute(
      "href",
      "https://insure.doaide.com",
    );
    expect(screen.getByText("TaxFile").closest("a")).toHaveAttribute(
      "href",
      "https://tax.doaide.com",
    );
    expect(screen.getByText("Pulse").closest("a")).toHaveAttribute(
      "href",
      "https://pulse.doaide.com",
    );
  });

  it("opens links in new tabs", () => {
    render(<DoAideFooter />);
    const links = screen.getAllByRole("link");
    links.forEach((link) => {
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer");
    });
  });

  it("has the correct aria label", () => {
    render(<DoAideFooter />);
    expect(screen.getByRole("contentinfo", { name: "More free tools from DoAide" })).toBeInTheDocument();
  });

  it("shows descriptions for each tool", () => {
    render(<DoAideFooter />);
    expect(screen.getByText("Create GST invoices in seconds")).toBeInTheDocument();
    expect(screen.getByText("Draft & manage business contracts")).toBeInTheDocument();
    expect(screen.getByText("LIC insurance calculators & tools")).toBeInTheDocument();
    expect(screen.getByText("Income tax & financial calculators")).toBeInTheDocument();
    expect(screen.getByText("Newsletter growth & email tools")).toBeInTheDocument();
  });
});
