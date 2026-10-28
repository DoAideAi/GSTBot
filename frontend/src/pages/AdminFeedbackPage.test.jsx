import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AdminFeedbackPage from "./AdminFeedbackPage";

function respond(status, body) {
  return Promise.resolve({
    ok: status < 400,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    text: () => Promise.resolve(JSON.stringify(body)),
  });
}

const ROWS = [
  {
    id: 2,
    category: "bug",
    message: "<b>not bold</b>",
    email: "a@example.com",
    page_url: "https://gst.doaide.com/hsn",
    user_agent: "UA",
    ip_address: "10.0.0.1",
    created_at: "2026-10-20T10:00:00Z",
  },
  {
    id: 1,
    category: "feature",
    message: "Add GSTR-9",
    email: null,
    page_url: null,
    user_agent: null,
    ip_address: null,
    created_at: "2026-10-01T10:00:00Z",
  },
];

function renderPage() {
  return render(
    <MemoryRouter>
      <AdminFeedbackPage />
    </MemoryRouter>,
  );
}

function lastUrl() {
  return global.fetch.mock.calls.at(-1)[0];
}

describe("AdminFeedbackPage", () => {
  beforeEach(() => {
    global.fetch = vi.fn(() => respond(200, { items: ROWS, total: 2 }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists feedback with its category, message and sender", async () => {
    renderPage();
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Bug Report");
    expect(rows[0]).toHaveTextContent("<b>not bold</b>"); // shown as text, never markup
    expect(within(rows[0]).getByRole("link", { name: "a@example.com" })).toHaveAttribute(
      "href",
      "mailto:a@example.com",
    );
    expect(rows[1]).toHaveTextContent("Feature Request");
    expect(rows[1]).toHaveTextContent("No email");
  });

  it("asks the server with the filters chosen, from the first page", async () => {
    renderPage();
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /category/i }), "bug");
    expect(lastUrl()).toContain("category=bug");
    expect(lastUrl()).toContain("offset=0");
  });

  it("says the inbox is for admins rather than showing it empty", async () => {
    global.fetch = vi.fn(() => respond(403, { detail: "Only site administrators can read this." }));
    renderPage();
    expect(await screen.findByText(/for site administrators/i)).toBeInTheDocument();
    expect(screen.queryByText(/no feedback matches/i)).not.toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    global.fetch = vi.fn(() => respond(200, { items: [], total: 0 }));
    renderPage();
    expect(await screen.findByText("No feedback matches these filters.")).toBeInTheDocument();
  });
});
