import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BusinessCounter from "./BusinessCounter";
import { getUsageStats } from "../lib/usageStats";

vi.mock("../lib/usageStats", async () => {
  const actual = await vi.importActual("../lib/usageStats");
  return { ...actual, getUsageStats: vi.fn() };
});

describe("BusinessCounter", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the real business count once it clears the floor", async () => {
    getUsageStats.mockResolvedValue({ businesses: 1234, invoices: 0, gstin_lookups: 0 });
    render(<BusinessCounter />);

    expect(await screen.findByText("1,234+")).toBeInTheDocument();
    expect(screen.getByText(/Indian businesses/)).toBeInTheDocument();
  });

  it("stays non-numeric while the count is below the floor", async () => {
    getUsageStats.mockResolvedValue({ businesses: 12, invoices: 0, gstin_lookups: 0 });
    render(<BusinessCounter />);

    await waitFor(() => expect(getUsageStats).toHaveBeenCalled());
    expect(screen.getByText("Built for Indian businesses")).toBeInTheDocument();
    expect(screen.queryByText(/\+/)).not.toBeInTheDocument();
  });

  it("stays non-numeric when the stats are unavailable", async () => {
    getUsageStats.mockResolvedValue(null);
    render(<BusinessCounter />);

    await waitFor(() => expect(getUsageStats).toHaveBeenCalled());
    expect(screen.getByText("Built for Indian businesses")).toBeInTheDocument();
  });

  it("renders the free badge and the status role", async () => {
    getUsageStats.mockResolvedValue(null);
    render(<BusinessCounter />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText(/Free/)).toBeInTheDocument();
    await waitFor(() => expect(getUsageStats).toHaveBeenCalled());
  });
});
