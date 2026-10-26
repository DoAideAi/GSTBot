import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FilingChecklistPage, { CHECKLISTS, itemsOf, loadChecked, saveChecked } from "./FilingChecklistPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));
vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: () => "https://wa.me/",
  twitterUrl: () => "https://twitter.com/",
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/api", () => ({
  api: { subscribe: vi.fn().mockResolvedValue({ subscribed: true, new: true, message: "Done" }) },
}));
vi.mock("../lib/track", () => ({ track: vi.fn() }));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/filing-checklist"]}>
      <FilingChecklistPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe("the checklist data", () => {
  it("keeps item ids unique across every return type", () => {
    const ids = Object.keys(CHECKLISTS).flatMap((rt) => itemsOf(rt).map((i) => i.id));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("gives every return type documents, checks and steps", () => {
    for (const { groups } of Object.values(CHECKLISTS)) {
      expect(groups.length).toBeGreaterThanOrEqual(3);
      for (const group of groups) {
        expect(group.items.length).toBeGreaterThan(0);
      }
    }
  });
});

describe("the stored progress", () => {
  it("round-trips through localStorage", () => {
    saveChecked({ gstr1: ["g1-sales"] });
    expect(loadChecked()).toEqual({ gstr1: ["g1-sales"] });
  });

  it("treats corrupted storage as a fresh start", () => {
    localStorage.setItem("gst_filing_checklist_v1", "{not json");
    expect(loadChecked()).toEqual({});
  });

  it("treats a stored non-object as a fresh start", () => {
    localStorage.setItem("gst_filing_checklist_v1", JSON.stringify(["g1-sales"]));
    expect(loadChecked()).toEqual({});
  });

  it("returns an unknown return type as an empty list of items", () => {
    expect(itemsOf("gstr99")).toEqual([]);
  });
});

describe("FilingChecklistPage", () => {
  it("opens on the GSTR-3B checklist with nothing done", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "GST Return Filing Checklist" })).toBeInTheDocument();
    expect(screen.getByText(`0 of ${itemsOf("gstr3b").length} done`)).toBeInTheDocument();
    expect(screen.getByText(/GSTR-2B statement downloaded/)).toBeInTheDocument();
  });

  it("advances the progress when an item is ticked, and persists it", () => {
    renderPage();
    fireEvent.click(screen.getByLabelText(/GSTR-2B statement downloaded/));
    expect(screen.getByText(`1 of ${itemsOf("gstr3b").length} done`)).toBeInTheDocument();
    expect(loadChecked().gstr3b).toEqual(["b3-2b"]);
  });

  it("unticks an item that is clicked twice", () => {
    renderPage();
    const box = screen.getByLabelText(/GSTR-2B statement downloaded/);
    fireEvent.click(box);
    fireEvent.click(box);
    expect(screen.getByText(`0 of ${itemsOf("gstr3b").length} done`)).toBeInTheDocument();
    expect(loadChecked().gstr3b).toEqual([]);
  });

  it("keeps each return type's progress separate", () => {
    renderPage();
    fireEvent.click(screen.getByLabelText(/GSTR-2B statement downloaded/));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "gstr1" } });
    expect(screen.getByText(`0 of ${itemsOf("gstr1").length} done`)).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "gstr3b" } });
    expect(screen.getByText(`1 of ${itemsOf("gstr3b").length} done`)).toBeInTheDocument();
  });

  it("restores saved progress on a fresh visit", () => {
    saveChecked({ gstr3b: ["b3-2b", "b3-sales"] });
    renderPage();
    expect(screen.getByText(`2 of ${itemsOf("gstr3b").length} done`)).toBeInTheDocument();
    expect(screen.getByLabelText(/GSTR-2B statement downloaded/)).toBeChecked();
  });

  it("resets only the visible checklist", () => {
    saveChecked({ gstr3b: ["b3-2b"], gstr1: ["g1-sales"] });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Reset This Checklist" }));
    expect(screen.getByText(`0 of ${itemsOf("gstr3b").length} done`)).toBeInTheDocument();
    expect(loadChecked().gstr1).toEqual(["g1-sales"]);
  });

  it("survives a browser that refuses storage", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    renderPage();
    fireEvent.click(screen.getByLabelText(/GSTR-2B statement downloaded/));
    expect(screen.getByText(`1 of ${itemsOf("gstr3b").length} done`)).toBeInTheDocument();
    setItem.mockRestore();
  });
});
