import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import FilingPage from "./FilingPage";
import ITCPage from "./ITCPage";
import ReconcilePage from "./ReconcilePage";

describe("action links keep the selected filing period", () => {
  beforeEach(() => { vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false, status: 503, statusText: "Unavailable",
    text: async () => JSON.stringify({ detail: "Fixture unavailable" }),
  })); });
  afterEach(() => vi.unstubAllGlobals());
  it.each([["filing", FilingPage], ["ITC", ITCPage], ["reconciliation", ReconcilePage]])(
    "%s accepts an older linked period in its picker and requests",
    async (_name, Page) => {
      render(<MemoryRouter initialEntries={["/?period=2020-04"]}><StubAuth><Page /></StubAuth></MemoryRouter>);
      const picker = await screen.findByLabelText("Period");
      expect(picker).toHaveValue("2020-04");
      await waitFor(() => expect(fetch).toHaveBeenCalled());
      expect(fetch.mock.calls.some(([url]) => url.includes("2020-04"))).toBe(true);
    },
  );
});
