import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import GstAdvisor from "./GstAdvisor";

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
  return render(<GstAdvisor />);
}

describe("GstAdvisor", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the floating button initially", () => {
    renderAdvisor();
    expect(screen.getByLabelText("Open GST AI Advisor")).toBeInTheDocument();
  });

  it("opens the chat panel when the button is clicked", async () => {
    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    expect(screen.getByRole("dialog", { name: "GST AI Advisor" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask a GST question...")).toBeInTheDocument();
  });

  it("names the question box for a screen reader, not only with a placeholder", async () => {
    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    expect(screen.getByRole("textbox", { name: "Your GST question" })).toBeInTheDocument();
  });

  it("shows the welcome message when no messages exist", async () => {
    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    expect(screen.getByText("Ask me anything about GST")).toBeInTheDocument();
  });

  it("closes the panel when the close button is clicked", async () => {
    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Close advisor"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Open GST AI Advisor")).toBeInTheDocument();
  });

  it("sends a message and displays the reply", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(mockStream("The GST rate for IT services is 18%.")),
    );

    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    await userEvent.type(
      screen.getByPlaceholderText("Ask a GST question..."),
      "What is the GST rate for IT services?",
    );
    await userEvent.click(screen.getByLabelText("Send message"));

    expect(screen.getByText("What is the GST rate for IT services?")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("The GST rate for IT services is 18%.")).toBeInTheDocument();
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/advisor/ask/stream",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("shows an error when the API call fails", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: false,
        status: 503,
        json: () =>
          Promise.resolve({
            detail: "The AI advisor is overloaded right now. Wait a minute and ask again.",
            correlation_id: "abc123",
          }),
      }),
    );

    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    await userEvent.type(
      screen.getByPlaceholderText("Ask a GST question..."),
      "test",
    );
    await userEvent.click(screen.getByLabelText("Send message"));

    await waitFor(() => {
      // The server's explanation, not its raw JSON body.
      expect(screen.getByText(/overloaded right now/)).toBeInTheDocument();
      expect(screen.queryByText(/correlation_id/)).not.toBeInTheDocument();
    });
  });

  it("disables send when input is empty", async () => {
    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    expect(screen.getByLabelText("Send message")).toBeDisabled();
  });

  it("sends on Enter key", async () => {
    global.fetch = vi.fn(() => Promise.resolve(mockStream("Reply")));

    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    const textarea = screen.getByPlaceholderText("Ask a GST question...");
    await userEvent.type(textarea, "hello{enter}");

    await waitFor(() => {
      expect(screen.getByText("Reply")).toBeInTheDocument();
    });
  });

  it("clears the welcome message after the first user message", async () => {
    global.fetch = vi.fn(() => Promise.resolve(mockStream("Hi!")));

    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    expect(screen.getByText("Ask me anything about GST")).toBeInTheDocument();

    await userEvent.type(
      screen.getByPlaceholderText("Ask a GST question..."),
      "hello",
    );
    await userEvent.click(screen.getByLabelText("Send message"));

    expect(screen.queryByText("Ask me anything about GST")).not.toBeInTheDocument();
  });

  it("shows suggested question chips in the welcome state", async () => {
    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));

    expect(screen.getByText("What is the GST rate for IT services?")).toBeInTheDocument();
    expect(screen.getByText("How do I claim Input Tax Credit?")).toBeInTheDocument();
    expect(screen.getByText("When is the GSTR-3B due date?")).toBeInTheDocument();
    expect(screen.getByText("What is reverse charge mechanism?")).toBeInTheDocument();
    expect(screen.getByText("Do I need GST registration?")).toBeInTheDocument();
    expect(screen.getByText("What are blocked ITC credits under Section 17(5)?")).toBeInTheDocument();
  });

  it("sends a message when a suggested question is clicked", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve(mockStream("The GSTR-3B is due on the 20th of each month.")),
    );

    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    await userEvent.click(screen.getByText("When is the GSTR-3B due date?"));

    expect(screen.getByText("When is the GSTR-3B due date?")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("The GSTR-3B is due on the 20th of each month.")).toBeInTheDocument();
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/advisor/ask/stream",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("keeps asking after a reply too long for the API to take back as history", async () => {
    const long = "x".repeat(5000);
    global.fetch = vi.fn(() => Promise.resolve(mockStream(long)));
    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    const input = screen.getByPlaceholderText("Ask a GST question...");
    await userEvent.type(input, "first");
    await userEvent.click(screen.getByLabelText("Send message"));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByLabelText("Send message")).toBeDefined());

    await userEvent.type(input, "second");
    await userEvent.click(screen.getByLabelText("Send message"));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));

    const { history } = JSON.parse(global.fetch.mock.calls[1][1].body);
    expect(history).toEqual([
      { role: "user", text: "first" },
      { role: "model", text: "x".repeat(4000) },
    ]);
  });

  it("hides suggested questions after the first message is sent", async () => {
    global.fetch = vi.fn(() => Promise.resolve(mockStream("Sure!")));

    renderAdvisor();
    await userEvent.click(screen.getByLabelText("Open GST AI Advisor"));
    expect(screen.getByText("How do I claim Input Tax Credit?")).toBeInTheDocument();

    await userEvent.click(screen.getByText("How do I claim Input Tax Credit?"));

    expect(screen.queryByText("Do I need GST registration?")).not.toBeInTheDocument();
  });
});

describe("GstAdvisor when it unmounts mid-answer", () => {
  afterEach(() => vi.restoreAllMocks());

  function endlessAnswer() {
    let signal;
    global.fetch = vi.fn((url, init) => {
      signal = init.signal;
      return Promise.resolve({
        ok: true,
        body: new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode(`data: ${JSON.stringify({ t: "Part of it" })}\n\n`),
            );
          },
        }),
      });
    });
    return () => signal;
  }

  it("stops the answer it was streaming", async () => {
    const signal = endlessAnswer();
    const { unmount } = renderAdvisor();
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Open GST AI Advisor"));
    await user.type(screen.getByPlaceholderText("Ask a GST question..."), "Rate?{Enter}");
    await waitFor(() => expect(screen.getByText(/Part of it/)).toBeInTheDocument());

    unmount();

    expect(signal()?.aborted).toBe(true);
  });

  it("keeps the answer coming when the panel is only closed", async () => {
    const signal = endlessAnswer();
    renderAdvisor();
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Open GST AI Advisor"));
    await user.type(screen.getByPlaceholderText("Ask a GST question..."), "Rate?{Enter}");
    await waitFor(() => expect(screen.getByText(/Part of it/)).toBeInTheDocument());

    await user.keyboard("{Escape}");

    expect(signal()?.aborted).toBe(false);
  });
});
