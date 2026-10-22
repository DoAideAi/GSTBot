import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import AdvisorPage from "./AdvisorPage";

const mockTrack = vi.fn();
vi.mock("../lib/track", () => ({ track: (...args) => mockTrack(...args) }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: null }) }));

// jsdom has no layout, so the chat's auto-scroll target needs a stand-in.
window.HTMLElement.prototype.scrollIntoView = vi.fn();

function renderAdvisor() {
  return render(
    <MemoryRouter initialEntries={["/advisor"]}>
      <AdvisorPage />
    </MemoryRouter>,
  );
}

describe("AdvisorPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    global.fetch?.mockRestore?.();
  });

  it("renders the header and suggested questions", () => {
    renderAdvisor();
    expect(screen.getByText("GST AI Advisor")).toBeInTheDocument();
    expect(screen.getByText("How to register for GST?")).toBeInTheDocument();
    expect(screen.getByText("What is ITC?")).toBeInTheDocument();
  });

  it("sends a question and displays the answer", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ answer: "GST registration requires PAN and Aadhaar.", error: null }),
    });
    renderAdvisor();
    const user = userEvent.setup();
    const input = screen.getByPlaceholderText("Ask a GST question...");
    await user.type(input, "How to register?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(screen.getByText(/GST registration requires PAN/)).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith("/api/v1/advisor/ask", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ question: "How to register?" }),
    }));
    expect(mockTrack).toHaveBeenCalledWith("advisor_ask", expect.any(Object));
  });

  it("displays an error message when the API returns an error", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ answer: "", error: "AI advisor is unavailable." }),
    });
    renderAdvisor();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Ask a GST question..."), "test");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(screen.getByText(/AI advisor is unavailable/)).toBeInTheDocument());
  });

  it("handles fetch failure gracefully", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Network error"));
    renderAdvisor();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Ask a GST question..."), "test");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(screen.getByText(/Something went wrong/)).toBeInTheDocument());
  });

  it("clicking a suggested question sends it", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ answer: "ITC is Input Tax Credit.", error: null }),
    });
    renderAdvisor();
    const user = userEvent.setup();
    await user.click(screen.getByText("What is ITC?"));

    await waitFor(() => expect(screen.getByText(/ITC is Input Tax Credit/)).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith("/api/v1/advisor/ask", expect.objectContaining({
      body: JSON.stringify({ question: "What is ITC?" }),
    }));
  });

  it("disables input while loading", async () => {
    let resolvePromise;
    global.fetch = vi.fn().mockReturnValue(
      new Promise((resolve) => { resolvePromise = resolve; }),
    );
    renderAdvisor();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Ask a GST question..."), "test");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    expect(screen.getByPlaceholderText("Ask a GST question...")).toBeDisabled();
    resolvePromise({
      ok: true,
      json: () => Promise.resolve({ answer: "Done", error: null }),
    });
    await waitFor(() => expect(screen.getByPlaceholderText("Ask a GST question...")).not.toBeDisabled());
  });
});
