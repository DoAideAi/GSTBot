import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import GstAdvisor from "./GstAdvisor";

// The advisor from the keyboard and a screen reader. The launcher button is
// unmounted when the panel opens and the panel's close button when it closes,
// so focus fell to <body> both ways; Escape did nothing; and a streamed answer
// arrived in a region nothing announced.

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

async function openWithKeyboard(user) {
  render(<GstAdvisor />);
  screen.getByLabelText("Open GST AI Advisor").focus();
  await user.keyboard("{Enter}");
}

describe("GstAdvisor from the keyboard", () => {
  afterEach(() => vi.restoreAllMocks());

  it("puts focus in the question box when it opens", async () => {
    const user = userEvent.setup();
    await openWithKeyboard(user);
    expect(screen.getByRole("textbox", { name: "Your GST question" })).toHaveFocus();
  });

  it("closes on Escape and returns focus to the launcher", async () => {
    const user = userEvent.setup();
    await openWithKeyboard(user);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Open GST AI Advisor")).toHaveFocus();
  });

  it("returns focus to the launcher when closed with the close button", async () => {
    const user = userEvent.setup();
    await openWithKeyboard(user);
    screen.getByLabelText("Close advisor").focus();
    await user.keyboard("{Enter}");
    expect(screen.getByLabelText("Open GST AI Advisor")).toHaveFocus();
  });

  it("does not take focus on first render", () => {
    render(<GstAdvisor />);
    expect(document.body).toHaveFocus();
  });
});

describe("GstAdvisor for a screen reader", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reads the conversation out as it arrives", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockStream("GSTR-3B is due on the 20th."));
    const user = userEvent.setup();
    await openWithKeyboard(user);
    await user.keyboard("When is GSTR-3B due?{Enter}");

    const log = screen.getByRole("log");
    expect(log).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(log).toHaveTextContent("GSTR-3B is due on the 20th."));
  });

  it("announces a failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const user = userEvent.setup();
    await openWithKeyboard(user);
    await user.keyboard("Anything{Enter}");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("says it is thinking in a way a screen reader hears", async () => {
    let release;
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise((r) => { release = r; }));
    const user = userEvent.setup();
    await openWithKeyboard(user);
    await user.keyboard("Slow question{Enter}");
    expect(await screen.findByRole("status", { name: "Thinking" })).toBeInTheDocument();
    release(mockStream("done"));
  });
});
