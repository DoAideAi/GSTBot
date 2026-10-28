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

/** Build a mock fetch Response whose body is an SSE stream. */
function mockStream(text) {
  const sse =
    `data: ${JSON.stringify({ t: text })}\n\n` +
    `data: ${JSON.stringify({ done: true })}\n\n`;
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(sse));
      controller.close();
    },
  });
  return { ok: true, body: stream };
}

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
    global.fetch = vi.fn().mockResolvedValue(
      mockStream("GST registration requires PAN and Aadhaar."),
    );
    renderAdvisor();
    const user = userEvent.setup();
    const input = screen.getByPlaceholderText("Ask a GST question...");
    await user.type(input, "How to register?");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(screen.getByText(/GST registration requires PAN/)).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith("/api/v1/advisor/ask/stream", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ message: "How to register?", history: [] }),
    }));
    expect(mockTrack).toHaveBeenCalledWith("advisor_ask", expect.any(Object));
  });

  it("shows the reply the API sends when the advisor is unavailable", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      mockStream("AI advisor is unavailable."),
    );
    renderAdvisor();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Ask a GST question..."), "test");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(screen.getByText(/AI advisor is unavailable/)).toBeInTheDocument());
  });

  it("explains a refused request instead of showing an empty reply", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 422, json: () => Promise.resolve({ detail: [] }) });
    renderAdvisor();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Ask a GST question..."), "test");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() => expect(screen.getByText(/could not answer just now/)).toBeInTheDocument());
  });

  it("sends the earlier turns as history with a follow-up", async () => {
    global.fetch = vi.fn().mockResolvedValue(mockStream("First answer."));
    renderAdvisor();
    const user = userEvent.setup();
    const input = screen.getByPlaceholderText("Ask a GST question...");
    await user.type(input, "First?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(screen.getByText("First answer.")).toBeInTheDocument());

    await user.type(input, "Second?");
    await user.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
    expect(JSON.parse(global.fetch.mock.calls[1][1].body)).toEqual({
      message: "Second?",
      history: [
        { role: "user", text: "First?" },
        { role: "model", text: "First answer." },
      ],
    });
  });

  it("handles fetch failure gracefully", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Network error"));
    renderAdvisor();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Ask a GST question..."), "test");
    await user.click(screen.getByRole("button", { name: "Ask" }));

    // The browser's own wording is replaced: it tells the visitor nothing.
    await waitFor(() =>
      expect(screen.getByText(/Could not reach the AI advisor/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/Network error/)).not.toBeInTheDocument();
  });

  it("clicking a suggested question sends it", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      mockStream("ITC is Input Tax Credit."),
    );
    renderAdvisor();
    const user = userEvent.setup();
    await user.click(screen.getByText("What is ITC?"));

    await waitFor(() => expect(screen.getByText(/ITC is Input Tax Credit/)).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith("/api/v1/advisor/ask/stream", expect.objectContaining({
      body: JSON.stringify({ message: "What is ITC?", history: [] }),
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
    resolvePromise(mockStream("Done"));
    await waitFor(() => expect(screen.getByPlaceholderText("Ask a GST question...")).not.toBeDisabled());
  });
});
