import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SocialProofBar from "./SocialProofBar";
import { getUsageStats } from "../lib/usageStats";

vi.mock("../lib/usageStats", async () => {
  const actual = await vi.importActual("../lib/usageStats");
  return { ...actual, getUsageStats: vi.fn() };
});

function renderAt(pathname) {
  return render(
    <MemoryRouter initialEntries={[pathname]}>
      <SocialProofBar />
    </MemoryRouter>,
  );
}

describe("SocialProofBar", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the real aggregate figures on a tool page", async () => {
    getUsageStats.mockResolvedValue({ businesses: 150, invoices: 2500, gstin_lookups: 12000 });
    renderAt("/calculator");

    expect(await screen.findByText("12,000")).toBeInTheDocument();
    expect(screen.getByText(/GSTIN lookups served/)).toBeInTheDocument();
    expect(screen.getByText("2,500")).toBeInTheDocument();
    expect(screen.getByText(/invoices processed/)).toBeInTheDocument();
  });

  it("drops a figure below the floor rather than showing a weak one", async () => {
    getUsageStats.mockResolvedValue({ businesses: 150, invoices: 3, gstin_lookups: 12000 });
    renderAt("/calculator");

    expect(await screen.findByText("12,000")).toBeInTheDocument();
    expect(screen.queryByText(/invoices processed/)).not.toBeInTheDocument();
  });

  it("renders nothing while every figure is below the floor", async () => {
    getUsageStats.mockResolvedValue({ businesses: 1, invoices: 2, gstin_lookups: 3 });
    const { container } = renderAt("/calculator");

    await waitFor(() => expect(getUsageStats).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the stats are unavailable", async () => {
    getUsageStats.mockResolvedValue(null);
    const { container } = renderAt("/calculator");

    await waitFor(() => expect(getUsageStats).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("stays off pages that are not tools and never fetches for them", () => {
    const { container } = renderAt("/blog");

    expect(container).toBeEmptyDOMElement();
    expect(getUsageStats).not.toHaveBeenCalled();
  });
});
