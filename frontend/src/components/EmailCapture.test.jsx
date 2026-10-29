import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import EmailCapture from "./EmailCapture";

const mockSubscribe = vi.fn();
vi.mock("../lib/api", () => ({
  api: { subscribe: (...args) => mockSubscribe(...args) },
}));

const mockTrack = vi.fn();
vi.mock("../lib/track", () => ({ track: (...args) => mockTrack(...args) }));

function renderCapture(props = {}) {
  return render(<EmailCapture source="calculator" {...props} />);
}

describe("EmailCapture", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders heading and subtext by default", () => {
    renderCapture({ heading: "Get reminders", subtext: "Never miss a deadline." });
    expect(screen.getByText("Get reminders")).toBeInTheDocument();
    expect(screen.getByText("Never miss a deadline.")).toBeInTheDocument();
  });

  it("hides heading and subtext in compact mode", () => {
    renderCapture({ compact: true, heading: "Get reminders", subtext: "Sub" });
    expect(screen.queryByText("Get reminders")).not.toBeInTheDocument();
    expect(screen.queryByText("Sub")).not.toBeInTheDocument();
  });

  it("submits email and shows success", async () => {
    mockSubscribe.mockResolvedValue({ subscribed: true, new: true, message: "Subscribed!" });
    renderCapture();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("your@email.com"), "test@example.com");
    await user.click(screen.getByRole("button", { name: /subscribe/i }));
    await waitFor(() => expect(screen.getByText("Subscribed!")).toBeInTheDocument());
    expect(mockSubscribe).toHaveBeenCalledWith("test@example.com", "calculator");
    expect(mockTrack).toHaveBeenCalledWith("email_subscribe", { source: "calculator" });
  });

  it("shows error on failure", async () => {
    mockSubscribe.mockRejectedValue(new Error("Network error"));
    renderCapture();
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("your@email.com"), "fail@example.com");
    await user.click(screen.getByRole("button", { name: /subscribe/i }));
    await waitFor(() => expect(screen.getByText("Network error")).toBeInTheDocument());
  });

  it("uses custom button label", () => {
    renderCapture({ buttonLabel: "Notify Me" });
    expect(screen.getByRole("button", { name: "Notify Me" })).toBeInTheDocument();
  });

  it("passes source to api.subscribe", async () => {
    mockSubscribe.mockResolvedValue({ subscribed: true, new: true, message: "Done" });
    renderCapture({ source: "filing-dates" });
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("your@email.com"), "fd@example.com");
    await user.click(screen.getByRole("button", { name: /subscribe/i }));
    await waitFor(() => expect(mockSubscribe).toHaveBeenCalledWith("fd@example.com", "filing-dates"));
  });

  it("names the email field on the full form and the compact one", () => {
    const { unmount } = render(<EmailCapture source="test" heading="Get reminders" />);
    expect(screen.getByRole("textbox", { name: "Email address" })).toBeInTheDocument();
    unmount();
    render(<EmailCapture source="test" compact />);
    expect(screen.getByRole("textbox", { name: "Email address" })).toBeInTheDocument();
  });
});
