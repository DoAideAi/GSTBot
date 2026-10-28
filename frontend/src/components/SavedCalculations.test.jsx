import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SavedCalculations, { getSavedCalcs, removeCalc, saveCalc, SaveCalcButton } from "./SavedCalculations";

vi.mock("../lib/share", () => ({
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text) => `https://wa.me/?text=${encodeURIComponent(text)}`,
  twitterUrl: () => "https://twitter.com/intent/tweet",
  copyToClipboard: vi.fn().mockResolvedValue(true),
}));
vi.mock("../lib/track", () => ({ track: vi.fn() }));

describe("getSavedCalcs", () => {
  beforeEach(() => localStorage.clear());

  it("returns empty array when nothing saved", () => {
    expect(getSavedCalcs()).toEqual([]);
  });

  it("returns saved calculations", () => {
    localStorage.setItem("gstbot_saved_calcs", JSON.stringify([{ id: 1, taxable: 1000 }]));
    expect(getSavedCalcs()).toEqual([{ id: 1, taxable: 1000 }]);
  });

  it("handles corrupt localStorage gracefully", () => {
    localStorage.setItem("gstbot_saved_calcs", "not json");
    expect(getSavedCalcs()).toEqual([]);
  });
});

describe("saveCalc", () => {
  beforeEach(() => localStorage.clear());

  it("saves a calculation and returns updated list", () => {
    const result = saveCalc({ taxable: 1000, total: 1180, rate: 18 });
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ taxable: 1000, total: 1180, rate: 18 });
    expect(result[0].id).toBeDefined();
    expect(result[0].savedAt).toBeDefined();
  });

  it("prepends new calculations", () => {
    saveCalc({ taxable: 1000, rate: 18 });
    const result = saveCalc({ taxable: 2000, rate: 5 });
    expect(result).toHaveLength(2);
    expect(result[0].taxable).toBe(2000);
  });

  it("caps at 20 entries", () => {
    for (let i = 0; i < 25; i++) {
      saveCalc({ taxable: i * 100, rate: 18 });
    }
    expect(getSavedCalcs()).toHaveLength(20);
  });
});

describe("removeCalc", () => {
  beforeEach(() => localStorage.clear());

  it("removes a calculation by id", () => {
    const saved = saveCalc({ taxable: 1000, rate: 18 });
    const result = removeCalc(saved[0].id);
    expect(result).toHaveLength(0);
  });
});

describe("SaveCalcButton", () => {
  beforeEach(() => localStorage.clear());

  it("renders nothing when no result", () => {
    const { container } = render(<SaveCalcButton result={null} rate={18} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders save button when result exists", () => {
    render(
      <SaveCalcButton
        result={{ taxable: 1000, total: 1180, cgst: 90, sgst: 90, igst: 0, interstate: false }}
        rate={18}
      />,
    );
    expect(screen.getByLabelText("Save this calculation")).toBeInTheDocument();
  });

  it("saves on click and shows confirmation", async () => {
    const user = userEvent.setup();
    const onSaved = vi.fn();
    render(
      <SaveCalcButton
        result={{ taxable: 1000, total: 1180, cgst: 90, sgst: 90, igst: 0, interstate: false }}
        rate={18}
        onSaved={onSaved}
      />,
    );
    await user.click(screen.getByLabelText("Save this calculation"));
    expect(screen.getByLabelText("Saved!")).toBeInTheDocument();
    expect(onSaved).toHaveBeenCalled();
  });
});

describe("SavedCalculations", () => {
  it("renders nothing when empty", () => {
    const { container } = render(
      <MemoryRouter><SavedCalculations calcs={[]} onUpdate={() => {}} /></MemoryRouter>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders saved calculations list", () => {
    const calcs = [
      { id: 1, taxable: 1000, total: 1180, rate: 18, interstate: false, cgst: 90, sgst: 90, igst: 0 },
      { id: 2, taxable: 5000, total: 5250, rate: 5, interstate: true, cgst: 0, sgst: 0, igst: 250 },
    ];
    render(
      <MemoryRouter><SavedCalculations calcs={calcs} onUpdate={() => {}} /></MemoryRouter>,
    );
    expect(screen.getByText("Your Saved Calculations")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("IGST")).toBeInTheDocument();
    expect(screen.getByText("CGST+SGST")).toBeInTheDocument();
  });

  it("has WhatsApp share links", () => {
    const calcs = [
      { id: 1, taxable: 1000, total: 1180, rate: 18, interstate: false, cgst: 90, sgst: 90, igst: 0 },
    ];
    render(
      <MemoryRouter><SavedCalculations calcs={calcs} onUpdate={() => {}} /></MemoryRouter>,
    );
    const whatsappLinks = screen.getAllByLabelText("Share on WhatsApp");
    expect(whatsappLinks).toHaveLength(1);
    expect(whatsappLinks[0].href).toContain("wa.me");
  });

  it("calls onUpdate when removing a calculation", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    const calcs = [
      { id: 1, taxable: 1000, total: 1180, rate: 18, interstate: false, cgst: 90, sgst: 90, igst: 0 },
    ];
    render(
      <MemoryRouter><SavedCalculations calcs={calcs} onUpdate={onUpdate} /></MemoryRouter>,
    );
    await user.click(screen.getByLabelText("Remove saved calculation"));
    expect(onUpdate).toHaveBeenCalled();
  });
});
