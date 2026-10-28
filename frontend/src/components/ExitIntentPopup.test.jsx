import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ExitIntentPopup from "./ExitIntentPopup";

vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/track", () => ({ track: () => {} }));

function renderPopup() {
  return render(
    <MemoryRouter>
      <ExitIntentPopup />
    </MemoryRouter>,
  );
}

describe("ExitIntentPopup", () => {
  it("does not render initially", () => {
    renderPopup();
    expect(screen.queryByText("Never Miss a GST Filing Deadline")).not.toBeInTheDocument();
  });

  it("appears on mouse leaving the viewport", () => {
    renderPopup();
    fireEvent.mouseOut(document, { clientY: -1 });
    expect(screen.getByText("Never Miss a GST Filing Deadline")).toBeInTheDocument();
  });

  it("dismisses when close button is clicked", () => {
    renderPopup();
    fireEvent.mouseOut(document, { clientY: -1 });
    expect(screen.getByText("Never Miss a GST Filing Deadline")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Close"));
    expect(screen.queryByText("Never Miss a GST Filing Deadline")).not.toBeInTheDocument();
  });

  it("takes focus when it opens, so a keyboard user is in the dialog", () => {
    renderPopup();
    fireEvent.mouseOut(document, { clientY: -1 });
    expect(screen.getByLabelText("Close")).toHaveFocus();
  });

  it("closes on Escape", () => {
    renderPopup();
    fireEvent.mouseOut(document, { clientY: -1 });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Never Miss a GST Filing Deadline")).not.toBeInTheDocument();
  });

  it("dismisses when skip text is clicked", () => {
    renderPopup();
    fireEvent.mouseOut(document, { clientY: -1 });
    fireEvent.click(screen.getByText(/No thanks/i));
    expect(screen.queryByText("Never Miss a GST Filing Deadline")).not.toBeInTheDocument();
  });

  it("has a link to the reminders signup", () => {
    renderPopup();
    fireEvent.mouseOut(document, { clientY: -1 });
    const link = screen.getByText("Get Free Filing Reminders");
    expect(link.closest("a")).toHaveAttribute("href", "/due-dates");
  });
});
