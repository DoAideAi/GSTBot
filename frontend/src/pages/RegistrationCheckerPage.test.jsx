import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import RegistrationCheckerPage, { FAQS } from "./RegistrationCheckerPage";

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
    <MemoryRouter initialEntries={["/registration-checker"]}>
      <RegistrationCheckerPage />
    </MemoryRouter>,
  );
}

const row = (label) => screen.getByText(label).closest(".calc-result-row");

async function fill(user, { type, turnover, state }) {
  if (type) await user.selectOptions(screen.getByLabelText("Business type"), type);
  if (state) await user.selectOptions(screen.getByLabelText("State or UT of business"), state);
  if (turnover) await user.type(screen.getByLabelText(/Aggregate annual turnover/), turnover);
}

describe("RegistrationCheckerPage", () => {
  it("shows no verdict until turnover and state are given", async () => {
    const user = userEvent.setup();
    renderPage();
    expect(screen.getByRole("heading", { level: 1, name: "GST Registration Eligibility Checker" })).toBeInTheDocument();
    await fill(user, { turnover: "5000000" });
    expect(screen.queryByText("GST registration")).not.toBeInTheDocument();
  });

  it("requires a goods seller above ₹40 lakh to register, citing Notification 10/2019-CT", async () => {
    const user = userEvent.setup();
    renderPage();
    await fill(user, { turnover: "4500000", state: "Maharashtra" });
    expect(row("GST registration")).toHaveTextContent("Required");
    expect(row("Turnover limit for Maharashtra")).toHaveTextContent("40,00,000");
    expect(screen.getByText(/Section 22\(1\) with Notification 10\/2019-CT/)).toBeInTheDocument();
  });

  it("holds a Himachal Pradesh goods seller at ₹40 lakh, not ₹20 lakh", async () => {
    const user = userEvent.setup();
    renderPage();
    await fill(user, { turnover: "3000000", state: "Himachal Pradesh" });
    expect(row("GST registration")).toHaveTextContent("Not required");
    expect(row("Turnover limit for Himachal Pradesh")).toHaveTextContent("40,00,000");
  });

  it("applies ₹10 lakh to a service provider in Manipur", async () => {
    const user = userEvent.setup();
    renderPage();
    await fill(user, { type: "services", turnover: "1200000", state: "Manipur" });
    expect(row("GST registration")).toHaveTextContent("Required");
    expect(row("Turnover limit for Manipur")).toHaveTextContent("10,00,000");
  });

  it("requires an inter-state goods seller to register whatever the turnover, under Section 24(i)", async () => {
    const user = userEvent.setup();
    renderPage();
    await fill(user, { turnover: "100000", state: "Gujarat" });
    await user.click(screen.getByLabelText(/sell goods to buyers in other states/));
    expect(row("GST registration")).toHaveTextContent("Required");
    expect(screen.getByText("Section 24(i):")).toBeInTheDocument();
  });

  it("lets an intra-state marketplace goods seller stay unregistered below the limit", async () => {
    const user = userEvent.setup();
    renderPage();
    await fill(user, { turnover: "800000", state: "Karnataka" });
    await user.click(screen.getByLabelText(/e-commerce platforms/));
    expect(row("GST registration")).toHaveTextContent("Not required");
    expect(screen.getByText(/Notification 34\/2023-CT/)).toBeInTheDocument();
  });

  it("asks a casual taxable person nothing more and cites Section 24(ii)", async () => {
    const user = userEvent.setup();
    renderPage();
    await fill(user, { type: "casual" });
    expect(screen.queryByLabelText(/Aggregate annual turnover/)).not.toBeInTheDocument();
    expect(row("GST registration")).toHaveTextContent("Required");
    expect(screen.getByText("Section 24(ii):")).toBeInTheDocument();
  });

  it("flags a negative turnover instead of giving a verdict", async () => {
    const user = userEvent.setup();
    renderPage();
    await fill(user, { turnover: "-5", state: "Delhi" });
    expect(screen.getByRole("alert")).toHaveTextContent("zero or more");
    expect(screen.queryByText("GST registration")).not.toBeInTheDocument();
  });

  it("keeps every FAQ answer sentence under 220 characters and renders each one", () => {
    renderPage();
    for (const f of FAQS) {
      expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
      for (const s of f.a.split(/(?<=\.)\s/)) expect(s.length).toBeLessThanOrEqual(220);
    }
  });
});
