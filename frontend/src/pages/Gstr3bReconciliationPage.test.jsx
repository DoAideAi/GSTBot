import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import Gstr3bReconciliationPage, { reconcileGstr3b } from "./Gstr3bReconciliationPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text) => `https://wa.me/?text=${encodeURIComponent(text)}`,
  twitterUrl: () => "https://twitter.com/",
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/api", () => ({
  api: { subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }) },
}));
vi.mock("../lib/track", () => ({ track: vi.fn() }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/gstr3b-reconciliation"]}>
      <Gstr3bReconciliationPage />
    </MemoryRouter>,
  );
}

describe("reconcileGstr3b", () => {
  it("answers nothing until at least one pair is complete", () => {
    expect(reconcileGstr3b({ g1Tax: NaN, b3Tax: NaN, itc2b: NaN, itcClaimed: NaN })).toBeNull();
    expect(reconcileGstr3b({ g1Tax: 100, b3Tax: NaN, itc2b: NaN, itcClaimed: 50 })).toBeNull();
  });

  it("flags a 3B liability short of GSTR-1 as a shortfall", () => {
    const r = reconcileGstr3b({ g1Tax: 118000, b3Tax: 100000, itc2b: NaN, itcClaimed: NaN });
    expect(r.liability).toEqual({ diff: -18000, status: "shortfall" });
    expect(r.itc).toBeNull();
  });

  it("flags a 3B liability above GSTR-1 as an excess", () => {
    const r = reconcileGstr3b({ g1Tax: 100000, b3Tax: 100500, itc2b: NaN, itcClaimed: NaN });
    expect(r.liability).toEqual({ diff: 500, status: "excess" });
  });

  it("treats a sub-rupee liability gap as matched", () => {
    const r = reconcileGstr3b({ g1Tax: 100000.4, b3Tax: 100000, itc2b: NaN, itcClaimed: NaN });
    expect(r.liability.status).toBe("matched");
    expect(r.liability.diff).toBe(-0.4);
  });

  it("flags ITC claimed beyond GSTR-2B as an excess", () => {
    const r = reconcileGstr3b({ g1Tax: NaN, b3Tax: NaN, itc2b: 45000, itcClaimed: 52000 });
    expect(r.itc).toEqual({ diff: 7000, status: "excess" });
    expect(r.liability).toBeNull();
  });

  it("flags ITC claimed below GSTR-2B as unclaimed credit", () => {
    const r = reconcileGstr3b({ g1Tax: NaN, b3Tax: NaN, itc2b: 45000, itcClaimed: 40000 });
    expect(r.itc).toEqual({ diff: -5000, status: "unclaimed" });
  });

  it("treats a sub-rupee ITC gap as matched", () => {
    const r = reconcileGstr3b({ g1Tax: NaN, b3Tax: NaN, itc2b: 45000.9, itcClaimed: 45000 });
    expect(r.itc.status).toBe("matched");
  });

  it("reconciles both pairs at once", () => {
    const r = reconcileGstr3b({ g1Tax: 118000, b3Tax: 118000, itc2b: 45000, itcClaimed: 45000 });
    expect(r.liability.status).toBe("matched");
    expect(r.itc.status).toBe("matched");
  });
});

describe("Gstr3bReconciliationPage", () => {
  it("renders the title and no verdict before any figures", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GSTR-3B Reconciliation Helper" })).toBeInTheDocument();
    expect(screen.queryByText(/Liability difference/)).not.toBeInTheDocument();
  });

  it("warns about DRC-01B when 3B is short of GSTR-1", () => {
    renderPage();
    const [g1, b3] = screen.getAllByPlaceholderText("e.g. 118000");
    fireEvent.change(g1, { target: { value: "118000" } });
    fireEvent.change(b3, { target: { value: "100000" } });
    expect(screen.getByText(/DRC-01B risk/)).toBeInTheDocument();
    expect(screen.getByText("-₹18,000.00")).toBeInTheDocument();
  });

  it("warns about DRC-01C when ITC is claimed beyond GSTR-2B", () => {
    renderPage();
    const [i2b, i3b] = screen.getAllByPlaceholderText("e.g. 45000");
    fireEvent.change(i2b, { target: { value: "45000" } });
    fireEvent.change(i3b, { target: { value: "52000" } });
    expect(screen.getByText(/DRC-01C risk/)).toBeInTheDocument();
    expect(screen.getByText("₹7,000.00")).toBeInTheDocument();
  });

  it("reports a clean reconciliation when both pairs agree", () => {
    renderPage();
    const [g1, b3] = screen.getAllByPlaceholderText("e.g. 118000");
    const [i2b, i3b] = screen.getAllByPlaceholderText("e.g. 45000");
    fireEvent.change(g1, { target: { value: "118000" } });
    fireEvent.change(b3, { target: { value: "118000" } });
    fireEvent.change(i2b, { target: { value: "45000" } });
    fireEvent.change(i3b, { target: { value: "45000" } });
    expect(screen.getByText(/Liability matches GSTR-1/)).toBeInTheDocument();
    expect(screen.getByText(/ITC claim matches GSTR-2B/)).toBeInTheDocument();
  });

  it("points out unclaimed credit without calling it a risk", () => {
    renderPage();
    const [i2b, i3b] = screen.getAllByPlaceholderText("e.g. 45000");
    fireEvent.change(i2b, { target: { value: "45000" } });
    fireEvent.change(i3b, { target: { value: "40000" } });
    expect(screen.getByText(/ITC left unclaimed/)).toBeInTheDocument();
    expect(screen.queryByText(/DRC-01C risk/)).not.toBeInTheDocument();
  });
});
