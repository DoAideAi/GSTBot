import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FeedbackWidget from "./FeedbackWidget";

function respond(status, body = {}) {
  return Promise.resolve({
    ok: status < 400,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

function renderWidget(route = "/gst-calculator") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <FeedbackWidget />
    </MemoryRouter>,
  );
}

async function openForm() {
  await userEvent.click(screen.getByRole("button", { name: "Feedback" }));
  return screen.getByRole("dialog", { name: "Send feedback" });
}

function sentBody() {
  const [, init] = global.fetch.mock.calls.at(-1);
  return JSON.parse(init.body);
}

describe("FeedbackWidget", () => {
  beforeEach(() => {
    global.fetch = vi.fn(() => respond(201, { id: 1 }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("is a labelled button, always there, that opens the form", async () => {
    renderWidget();
    const button = screen.getByRole("button", { name: "Feedback" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await openForm();
    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it("offers the four categories and defaults to general feedback", async () => {
    renderWidget();
    await openForm();
    const select = screen.getByRole("combobox", { name: "Category" });
    expect([...select.options].map((o) => o.textContent)).toEqual([
      "Bug Report",
      "Feature Request",
      "General Feedback",
      "Other",
    ]);
    expect(select).toHaveValue("general");
  });

  it("will not submit until there is something to say", async () => {
    renderWidget();
    await openForm();
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox", { name: /your feedback/i }), "   ");
    expect(submit).toBeDisabled();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("sends the category, message, email and the page without its query", async () => {
    window.history.replaceState(null, "", "/gst-calculator?token=secret#frag");
    renderWidget();
    await openForm();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Category" }), "bug");
    await userEvent.type(screen.getByRole("textbox", { name: /your feedback/i }), "  Rate is wrong  ");
    await userEvent.type(screen.getByRole("textbox", { name: /email/i }), "me@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));

    await screen.findByText("Thanks — we read every message.");
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/feedback",
      expect.objectContaining({ method: "POST" }),
    );
    expect(sentBody()).toEqual({
      category: "bug",
      message: "Rate is wrong",
      email: "me@example.com",
      page_url: `${window.location.origin}/gst-calculator`,
    });
    window.history.replaceState(null, "", "/");
  });

  it("sends no email when the box is left empty", async () => {
    renderWidget();
    await openForm();
    await userEvent.type(screen.getByRole("textbox", { name: /your feedback/i }), "Nice");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByRole("status");
    expect(sentBody().email).toBeNull();
  });

  it("says so when sending fails, and keeps what was typed", async () => {
    global.fetch = vi.fn(() =>
      respond(429, { detail: "Too many requests. Please wait a moment and try again." }),
    );
    renderWidget();
    await openForm();
    const box = screen.getByRole("textbox", { name: /your feedback/i });
    await userEvent.type(box, "Keep me");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/too many requests/i);
    expect(box).toHaveValue("Keep me");
    expect(screen.queryByText("Thanks — we read every message.")).not.toBeInTheDocument();
  });

  it("closes on Escape and on the close button, returning focus to the button", async () => {
    renderWidget();
    await openForm();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Feedback" })).toHaveFocus();

    await openForm();
    await userEvent.click(screen.getByRole("button", { name: "Close feedback" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("starts a fresh form after a sent one is closed", async () => {
    renderWidget();
    await openForm();
    await userEvent.type(screen.getByRole("textbox", { name: /your feedback/i }), "First");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await userEvent.click(await screen.findByRole("button", { name: "Close" }));
    await openForm();
    expect(screen.getByRole("textbox", { name: /your feedback/i })).toHaveValue("");
  });
});
