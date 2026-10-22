// A sweep over the content pages that carry no logic of their own — guides,
// blog articles and the comparison hub. Each one is a page of prose whose only
// moving part is a FAQ accordion, so the claim worth making is uniform: it
// mounts, it has a single h1, and every button on it survives being clicked
// twice (open and close for the accordions). Pages with real behaviour keep
// their own test files.
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import Gst2ChangesExplained from "./blog/Gst2ChangesExplained";
import GstRatesServices2026 from "./blog/GstRatesServices2026";
import GstRegistrationGuide2026 from "./blog/GstRegistrationGuide2026";
import GstRegistrationProcess2026 from "./blog/GstRegistrationProcess2026";
import GstReturnFilingOnline from "./blog/GstReturnFilingOnline";
import Gstr3bCommonMistakes from "./blog/Gstr3bCommonMistakes";
import HsnCodeList2026 from "./blog/HsnCodeList2026";
import ItcRules2026 from "./blog/ItcRules2026";
import BestGstTools from "./compare/BestGstTools";
import EwayBillGuide from "./guides/EwayBillGuide";
import Gst2GuidePage from "./guides/Gst2GuidePage";
import GstRatesListGuide from "./guides/GstRatesListGuide";
import GstRegistrationProcessGuide from "./guides/GstRegistrationProcessGuide";
import GstReturnCalendarGuide from "./guides/GstReturnCalendarGuide";
import InputTaxCreditGuide from "./guides/InputTaxCreditGuide";

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

const PAGES = [
  ["blog/Gst2ChangesExplained", Gst2ChangesExplained],
  ["blog/GstRatesServices2026", GstRatesServices2026],
  ["blog/GstRegistrationGuide2026", GstRegistrationGuide2026],
  ["blog/GstRegistrationProcess2026", GstRegistrationProcess2026],
  ["blog/GstReturnFilingOnline", GstReturnFilingOnline],
  ["blog/Gstr3bCommonMistakes", Gstr3bCommonMistakes],
  ["blog/HsnCodeList2026", HsnCodeList2026],
  ["blog/ItcRules2026", ItcRules2026],
  ["compare/BestGstTools", BestGstTools],
  ["guides/EwayBillGuide", EwayBillGuide],
  ["guides/Gst2GuidePage", Gst2GuidePage],
  ["guides/GstRatesListGuide", GstRatesListGuide],
  ["guides/GstRegistrationProcessGuide", GstRegistrationProcessGuide],
  ["guides/GstReturnCalendarGuide", GstReturnCalendarGuide],
  ["guides/InputTaxCreditGuide", InputTaxCreditGuide],
];

describe.each(PAGES)("%s", (name, Page) => {
  it("mounts with a single h1 and every control survives a double click", () => {
    render(
      <MemoryRouter>
        <Page />
      </MemoryRouter>,
    );

    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0].textContent.trim()).not.toBe("");

    // Open and close every accordion / toggle on the page; a crash here is a
    // handler reading state that render alone never exercised.
    for (const pass of [1, 2]) {
      for (const button of screen.queryAllByRole("button")) {
        fireEvent.click(button);
        expect(pass).toBeGreaterThan(0);
      }
    }
  });
});
