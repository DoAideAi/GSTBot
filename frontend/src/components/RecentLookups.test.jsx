import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import RecentLookups from "./RecentLookups";

const mockRecentLookups = vi.fn();

vi.mock("../lib/api", () => ({
  api: {
    recentLookups: (...args) => mockRecentLookups(...args),
  },
}));

describe("RecentLookups", () => {
  it("renders nothing when API returns empty", async () => {
    mockRecentLookups.mockResolvedValue({ lookups: [] });
    const { container } = render(
      <MemoryRouter><RecentLookups /></MemoryRouter>,
    );
    await waitFor(() => expect(mockRecentLookups).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it("renders lookup items when API returns data", async () => {
    mockRecentLookups.mockResolvedValue({
      lookups: [
        { gstin: "27••••••••••1ZV", state_name: "Maharashtra", valid: true },
        { gstin: "29••••••••••1ZM", state_name: "Karnataka", valid: true },
      ],
    });
    render(
      <MemoryRouter><RecentLookups /></MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("Recently Verified Businesses")).toBeInTheDocument();
    });
    expect(screen.getByText("27••••••••••1ZV")).toBeInTheDocument();
    expect(screen.getByText("Maharashtra")).toBeInTheDocument();
    expect(screen.getByText("29••••••••••1ZM")).toBeInTheDocument();
  });

  it("does not link a masked GSTIN anywhere, since it has no page", async () => {
    mockRecentLookups.mockResolvedValue({
      lookups: [
        { gstin: "27••••••••••1ZV", state_name: "Maharashtra", valid: true },
        { gstin: "27••••••••••1ZV", state_name: "Maharashtra", valid: true },
      ],
    });
    render(
      <MemoryRouter><RecentLookups /></MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getAllByText("27••••••••••1ZV")).toHaveLength(2);
    });
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders nothing when API fails", async () => {
    mockRecentLookups.mockRejectedValue(new Error("fail"));
    const { container } = render(
      <MemoryRouter><RecentLookups /></MemoryRouter>,
    );
    await waitFor(() => expect(mockRecentLookups).toHaveBeenCalled());
    expect(container.firstChild).toBeNull();
  });

  it("shows Active badge for valid GSTINs", async () => {
    mockRecentLookups.mockResolvedValue({
      lookups: [
        { gstin: "27••••••••••1ZV", state_name: "Maharashtra", valid: true },
      ],
    });
    render(
      <MemoryRouter><RecentLookups /></MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByText("Active")).toBeInTheDocument();
    });
  });
});
