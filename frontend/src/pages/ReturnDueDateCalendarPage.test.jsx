import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReturnDueDateCalendarPage, { FAQS } from "./ReturnDueDateCalendarPage";

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


const nextCard = () => screen.getByTestId("next-deadline");
const cards = () => [...document.querySelectorAll(".calendar-date-card")].map((c) => c.textContent);

// 28 October 2026, 11:30 IST. Only Date is faked, so userEvent's timers run.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-28T06:00:00Z"));
});
afterEach(() => vi.useRealTimers());

describe("ReturnDueDateCalendarPage", () => {
  it("opens on the current month for a monthly filer", () => {
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "GST Return Due Date Calendar" })).toBeInTheDocument();
    expect(screen.getByText("October 2026")).toBeInTheDocument();
    expect(cards()).toEqual([
      expect.stringContaining("GSTR-1"),
      expect.stringContaining("GSTR-3B"),
    ]);
    expect(cards()[1]).toContain("Overdue by 8 days");
  });

  it("highlights GSTR-1 on 11 November as a monthly filer's next deadline", () => {
    renderPage();
    expect(within(nextCard()).getByText("11 Nov 2026")).toBeInTheDocument();
    expect(nextCard()).toHaveTextContent("GSTR-1 — Oct 2026");
    expect(nextCard()).toHaveTextContent("14 days remaining");
  });

  it("marks the next deadline in the month view", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByLabelText("Next month"));
    expect(screen.getByText("November 2026")).toBeInTheDocument();
    expect(cards()[0]).toContain("Next up");
    expect(cards()[1]).not.toContain("Next up");
  });

  it("shows the 31 December GSTR-9 in the December view", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByLabelText("Next month"));
    await user.click(screen.getByLabelText("Next month"));
    expect(cards()[2]).toContain("GSTR-9");
    expect(cards()[2]).toContain("31 Dec 2026");
    expect(cards()[2]).toContain("FY 2025-26");
  });

  it("gives a QRMP filer PMT-06 as next, skipping the optional IFF", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("How you file"), "quarterly");
    await user.click(screen.getByLabelText("Next month"));
    expect(nextCard()).toHaveTextContent("PMT-06");
    expect(nextCard()).not.toHaveTextContent("IFF");
    expect(cards()[0]).toContain("optional");
  });

  it("moves a QRMP filer's quarterly GSTR-3B to the 22nd in Maharashtra and the 24th in Delhi", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("How you file"), "quarterly");
    expect(cards().filter((c) => c.includes("GSTR-3B"))).toHaveLength(2);

    await user.selectOptions(screen.getByLabelText(/State of registration/), "27");
    expect(cards().find((c) => c.includes("GSTR-3B"))).toContain("22 Oct 2026");
    await user.selectOptions(screen.getByLabelText(/State of registration/), "07");
    expect(cards().find((c) => c.includes("GSTR-3B"))).toContain("24 Oct 2026");
  });

  it("gives a composition dealer CMP-08 and says when a month has nothing due", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.selectOptions(screen.getByLabelText("How you file"), "composition");
    expect(cards()).toEqual([expect.stringContaining("CMP-08")]);
    expect(cards()[0]).toContain("18 Oct 2026");
    await user.click(screen.getByLabelText("Next month"));
    expect(screen.getByText("Nothing due in November 2026.")).toBeInTheDocument();
    expect(nextCard()).toHaveTextContent("CMP-08");
    expect(within(nextCard()).getByText("18 Jan 2027")).toBeInTheDocument();
  });

  it("keeps every FAQ answer sentence under 220 characters and renders each one", () => {
    renderPage();
    for (const f of FAQS) {
      expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
      for (const s of f.a.split(/(?<=\.)\s/)) expect(s.length).toBeLessThanOrEqual(220);
    }
  });
});
