import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import SaveResultsCTA from "./SaveResultsCTA";

vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/track", () => ({ track: () => {} }));

function renderCTA(props = {}) {
  return render(
    <MemoryRouter>
      <SaveResultsCTA resultSummary="Late fee: ₹1,550 for GSTR-3B" {...props} />
    </MemoryRouter>,
  );
}

describe("SaveResultsCTA", () => {
  it("renders save and share buttons when result is present", () => {
    renderCTA();
    expect(screen.getByText(/Save Results/)).toBeInTheDocument();
    expect(screen.getByText(/Share via WhatsApp/)).toBeInTheDocument();
  });

  it("does not render without resultSummary", () => {
    render(
      <MemoryRouter>
        <SaveResultsCTA resultSummary={null} />
      </MemoryRouter>,
    );
    expect(screen.queryByText(/Save Results/)).not.toBeInTheDocument();
  });

  it("dismisses when close button is clicked", () => {
    renderCTA();
    fireEvent.click(screen.getByLabelText("Dismiss"));
    expect(screen.queryByText(/Save Results/)).not.toBeInTheDocument();
  });

  it("includes WhatsApp share link with result summary", () => {
    renderCTA();
    const link = screen.getByText(/Share via WhatsApp/).closest("a");
    expect(link.href).toContain("wa.me");
    expect(link.href).toContain(encodeURIComponent("Late fee"));
  });

  it("links save button to registration", () => {
    renderCTA();
    const link = screen.getByText(/Save Results/).closest("a");
    expect(link).toHaveAttribute("href", "/login");
  });
});
