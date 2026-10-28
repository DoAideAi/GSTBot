import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import HsnFinderPage from "./HsnFinderPage";

vi.mock("../hooks/usePageTitle", () => ({ usePageTitle: () => {} }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));

const mockCopyToClipboard = vi.fn();
vi.mock("../lib/share", () => ({
  copyToClipboard: (...args) => mockCopyToClipboard(...args),
  fullUrl: (p) => `http://localhost${p}`,
  whatsappUrl: (text, url) => `https://wa.me/?text=${encodeURIComponent(`${text} ${url}`)}`,
  twitterUrl: (text, url) => `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${encodeURIComponent(url)}`,
}));

const mockTrack = vi.fn();
vi.mock("../lib/track", () => ({ track: (...args) => mockTrack(...args) }));

function renderHsn() {
  return render(
    <MemoryRouter initialEntries={["/hsn"]}>
      <HsnFinderPage />
    </MemoryRouter>,
  );
}

describe("HsnFinderPage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the HSN finder title and search input", () => {
    renderHsn();

    expect(screen.getByText("HSN / SAC Code Finder")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/laptop/)).toBeInTheDocument();
  });

  it("shows category cards when search is empty", () => {
    renderHsn();

    expect(screen.getByText("Browse by Category")).toBeInTheDocument();
    expect(screen.getByText("Food")).toBeInTheDocument();
    expect(screen.getByText("Electronics")).toBeInTheDocument();
  });

  it("shows results when searching by keyword", async () => {
    renderHsn();

    await userEvent.type(screen.getByPlaceholderText(/laptop/), "cement");

    expect(screen.getAllByText(/cement/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("2523")).toBeInTheDocument();
    expect(screen.getAllByText("18%").length).toBeGreaterThanOrEqual(1);
  });

  it("shows no-matching message for unknown search", async () => {
    renderHsn();

    await userEvent.type(screen.getByPlaceholderText(/laptop/), "xyznonexistent");

    expect(screen.getByText(/No matching HSN\/SAC codes/)).toBeInTheDocument();
  });

  it("hides categories when a query is active", async () => {
    renderHsn();

    await userEvent.type(screen.getByPlaceholderText(/laptop/), "rice");

    expect(screen.queryByText("Browse by Category")).not.toBeInTheDocument();
  });

  it("shows a copy button per result row", async () => {
    renderHsn();

    await userEvent.type(screen.getByPlaceholderText(/laptop/), "cement");

    const copyButtons = screen.getAllByText("Copy");
    expect(copyButtons.length).toBeGreaterThan(0);
  });

  it("copy button shows Copied! on click", async () => {
    mockCopyToClipboard.mockResolvedValue(true);
    renderHsn();

    await userEvent.type(screen.getByPlaceholderText(/laptop/), "cement");
    const copyBtn = screen.getAllByText("Copy")[0];
    await userEvent.click(copyBtn);

    expect(screen.getByText("Copied!")).toBeInTheDocument();
  });

  it("clicking a category populates the search", async () => {
    renderHsn();

    await userEvent.click(screen.getByText("Food"));

    expect(screen.getByPlaceholderText(/laptop/)).toHaveValue("Food");
  });

  it("renders the info section", () => {
    renderHsn();

    expect(screen.getByText("What Are HSN and SAC Codes?")).toBeInTheDocument();
  });

  it("fires hsn_search tracking event when searching", async () => {
    renderHsn();

    mockTrack.mockClear();
    await userEvent.type(screen.getByPlaceholderText(/laptop/), "cement");

    // Once, for the settled query — not once per keystroke.
    await waitFor(() => expect(mockTrack).toHaveBeenCalledWith("hsn_search", { query: "cement" }), { timeout: 2000 });
    expect(mockTrack.mock.calls.filter(([name]) => name === "hsn_search")).toHaveLength(1);
  });

  it("announces how many codes matched, in one short status line", async () => {
    renderHsn();
    await userEvent.type(screen.getByPlaceholderText(/laptop/), "xyznonexistent");
    expect(screen.getByRole("status")).toHaveTextContent("No results found");
  });
});
