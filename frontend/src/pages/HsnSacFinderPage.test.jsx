import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import HsnSacFinderPage from "./HsnSacFinderPage";

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
    <MemoryRouter initialEntries={["/hsn-sac-finder"]}>
      <HsnSacFinderPage />
    </MemoryRouter>,
  );
}

describe("HsnSacFinderPage", () => {
  it("renders the title", () => {
    renderPage();
    expect(screen.getByRole("heading", { name: "HSN/SAC Code Finder" })).toBeInTheDocument();
  });

  it("shows category browse buttons initially", () => {
    renderPage();
    const buttons = screen.getAllByRole("button");
    const categoryButtons = buttons.filter((b) => b.classList.contains("hsn-category-btn"));
    expect(categoryButtons.length).toBeGreaterThan(5);
  });

  it("searches by product name", async () => {
    renderPage();
    const input = screen.getByPlaceholderText(/laptop, cement/);
    await userEvent.type(input, "cement");
    expect(screen.getByText("2523")).toBeInTheDocument();
    expect(screen.getAllByText("18%").length).toBeGreaterThanOrEqual(1);
  });

  it("searches by code number", async () => {
    renderPage();
    const input = screen.getByPlaceholderText(/laptop, cement/);
    await userEvent.type(input, "8517");
    expect(screen.getByText(/Telephone sets including smartphones/)).toBeInTheDocument();
  });

  it("shows results when browsing by category", async () => {
    renderPage();
    const buttons = screen.getAllByRole("button");
    const beveragesBtn = buttons.find((b) => b.classList.contains("hsn-category-btn") && b.textContent.includes("Beverages"));
    await userEvent.click(beveragesBtn);
    expect(screen.getByText("2201")).toBeInTheDocument();
  });

  it("shows no results message for bad search", async () => {
    renderPage();
    const input = screen.getByPlaceholderText(/laptop, cement/);
    await userEvent.type(input, "xyznonexistent");
    expect(screen.getByText(/No results found\. Try a different/)).toBeInTheDocument();
    // Announced too — this message used to sit outside the live region.
    expect(screen.getByRole("status")).toHaveTextContent("No results found");
  });

  it("shows type column distinguishing HSN and SAC", async () => {
    renderPage();
    const input = screen.getByPlaceholderText(/laptop, cement/);
    await userEvent.type(input, "construction services");
    expect(screen.getByText("SAC")).toBeInTheDocument();
  });
});
