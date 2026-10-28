import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FeedbackWidget from "./FeedbackWidget";

function renderWidget(route = "/calculator") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <FeedbackWidget />
    </MemoryRouter>,
  );
}

describe("FeedbackWidget", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve("{}") }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the floating button on a fresh page", () => {
    renderWidget();
    expect(screen.getByLabelText("Send feedback")).toBeInTheDocument();
  });

  it("opens the modal when the button is clicked", async () => {
    renderWidget();
    await userEvent.click(screen.getByLabelText("Send feedback"));
    expect(screen.getByRole("dialog", { name: "Send feedback" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Tell us what you think...")).toBeInTheDocument();
  });

  it("closes the modal when the close button is clicked", async () => {
    renderWidget();
    await userEvent.click(screen.getByLabelText("Send feedback"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Close feedback"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("submits feedback and shows a thank-you message", async () => {
    renderWidget();
    await userEvent.click(screen.getByLabelText("Send feedback"));
    await userEvent.click(screen.getByLabelText("4 stars"));
    await userEvent.type(
      screen.getByPlaceholderText("Tell us what you think..."),
      "Great tool!",
    );
    await userEvent.click(screen.getByText("Submit"));

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/feedback",
      expect.objectContaining({ method: "POST" }),
    );
    const body = JSON.parse(global.fetch.mock.calls[0][1].body);
    expect(body.page).toBe("/calculator");
    expect(body.rating).toBe(4);
    expect(body.comment).toBe("Great tool!");

    expect(screen.getByText("Thanks for your feedback!")).toBeInTheDocument();
  });

  it("hides the button on pages the user already submitted feedback for", () => {
    localStorage.setItem(
      "gstbot_feedback_pages",
      JSON.stringify(["/calculator"]),
    );
    renderWidget("/calculator");
    expect(screen.queryByLabelText("Send feedback")).not.toBeInTheDocument();
  });

  it("disables submit until a rating is selected", async () => {
    renderWidget();
    await userEvent.click(screen.getByLabelText("Send feedback"));
    const submitBtn = screen.getByText("Submit");
    expect(submitBtn).toBeDisabled();
    await userEvent.click(screen.getByLabelText("3 stars"));
    expect(submitBtn).not.toBeDisabled();
  });

  it("marks the page in localStorage after submission", async () => {
    renderWidget("/lookup");
    await userEvent.click(screen.getByLabelText("Send feedback"));
    await userEvent.click(screen.getByLabelText("5 stars"));
    await userEvent.click(screen.getByText("Submit"));

    const stored = JSON.parse(localStorage.getItem("gstbot_feedback_pages"));
    expect(stored).toContain("/lookup");
  });
});
