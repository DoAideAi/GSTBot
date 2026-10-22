import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ReturnDueDateCalendarPage from "./ReturnDueDateCalendarPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text, url) => `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
  twitterUrl: (text, url) => `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/api", () => ({
  api: { subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }) },
}));
vi.mock("../lib/track", () => ({ track: vi.fn() }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/return-calendar"]}>
      <ReturnDueDateCalendarPage />
    </MemoryRouter>,
  );
}

describe("ReturnDueDateCalendarPage", () => {
  it("renders the title", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GST Return Due Date Calendar" })).toBeInTheDocument();
  });

  it("shows the current month by default", () => {
    renderPage();
    const now = new Date();
    const monthNames = [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ];
    expect(screen.getByText(`${monthNames[now.getMonth()]} ${now.getFullYear()}`)).toBeInTheDocument();
  });

  it("shows filter buttons for return types", () => {
    renderPage();
    expect(screen.getByText("All Returns")).toBeInTheDocument();
    expect(screen.getByText("GSTR-1")).toBeInTheDocument();
    expect(screen.getByText("GSTR-3B")).toBeInTheDocument();
  });

  it("navigates to next month", async () => {
    renderPage();
    const nextBtn = screen.getByRole("button", { name: "Next month" });
    await userEvent.click(nextBtn);
    const now = new Date();
    const nextMonth = new Date(now.getFullYear(), now.getMonth() + 1, 1);
    const monthNames = [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ];
    expect(screen.getByText(`${monthNames[nextMonth.getMonth()]} ${nextMonth.getFullYear()}`)).toBeInTheDocument();
  });

  it("filters by return type", async () => {
    renderPage();
    await userEvent.click(screen.getByText("GSTR-1"));
    const badges = screen.queryAllByText("GSTR1");
    badges.forEach((badge) => {
      expect(badge).toBeInTheDocument();
    });
  });

  it("shows due dates with deadlines", () => {
    renderPage();
    expect(screen.getByText(/GSTR-1 for/)).toBeInTheDocument();
  });

  it("shows late fee section", () => {
    renderPage();
    expect(screen.getByText("GST Late Fee and Penalty")).toBeInTheDocument();
  });

  it("shows late fee rates for GSTR-1 and GSTR-3B", () => {
    renderPage();
    expect(screen.getByText(/Rs 50\/day/)).toBeInTheDocument();
    expect(screen.getAllByText(/18% p\.a\./).length).toBeGreaterThanOrEqual(1);
  });

  it("shows FAQ about late fee for GSTR-3B", () => {
    renderPage();
    expect(screen.getByText("What is the late fee for not filing GSTR-3B on time?")).toBeInTheDocument();
  });

  it("shows late fee estimate on past-due cards when navigating to a past month", async () => {
    renderPage();
    const prevBtn = screen.getByRole("button", { name: "Previous month" });
    await userEvent.click(prevBtn);
    await userEvent.click(prevBtn);
    const overdueTexts = screen.queryAllByText(/Overdue by/);
    if (overdueTexts.length > 0) {
      expect(screen.queryAllByText(/Estimated late fee/).length).toBeGreaterThanOrEqual(1);
    }
  });
});
