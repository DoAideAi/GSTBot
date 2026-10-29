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
    metadata: {
      feature_area: "GSTIN Lookup",
      time_on_page_ms: 192000,
      scroll_depth_pct: 80,
      click_count: 9,
      rage_clicks: 5,
      js_errors: 1,
      js_error_messages: ["TypeError: x"],
      pages: ["/", "/gstin-validator"],
    },
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
    metadata: null,
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

  it("reads the visit back as what the visitor went through", async () => {
    renderPage();
    const table = await screen.findByRole("table");
    const [first, second] = within(table).getAllByRole("row").slice(1);
    expect(first).toHaveTextContent(
      "Was on GSTIN Lookup for 3m 12s, scrolled 80%, 9 clicks, 5 rage clicks, 1 JS error, 2 pages this session.",
    );
    const flags = within(first).getByRole("list", { name: "Struggle signals" });
    expect(within(flags).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Rage clicks",
      "JS error: TypeError: x",
    ]);
    expect(first).toHaveTextContent("Path: / → /gstin-validator");
    expect(within(second).queryByRole("list", { name: "Struggle signals" })).toBeNull();
  });

  it("deletes a piece of feedback once confirmed, and keeps it when not", async () => {
    vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderPage();
    const table = await screen.findByRole("table");
    const firstDelete = within(table).getAllByRole("button", { name: "Delete" })[0];

    await userEvent.click(firstDelete);
    expect(global.fetch).toHaveBeenCalledTimes(1);

    global.fetch.mockImplementationOnce(() => Promise.resolve({ ok: true, status: 204, text: () => Promise.resolve("") }));
    await userEvent.click(firstDelete);
    const calls = global.fetch.mock.calls;
    const del = calls.findIndex(([, init]) => init?.method === "DELETE");
    expect(calls[del][0]).toBe("/api/v1/feedback/2");
    // The page is then asked for again rather than patched locally.
    await vi.waitFor(() => expect(calls.length).toBeGreaterThan(del + 1));
    expect(calls.at(-1)[0]).toBe("/api/v1/feedback?limit=50&offset=0");
  });

  it("shows the browser error log, and clears an error marked fixed", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderPage();
    await screen.findByRole("table");
    let cleared = false;
    global.fetch = vi.fn((url, init) =>
      init?.method === "DELETE"
        ? ((cleared = true),
          Promise.resolve({ ok: true, status: 204, text: () => Promise.resolve("") }))
        : respond(200, cleared ? { items: [], total: 0 } : {
            items: [
              {
                id: 7,
                page: "https://gst.doaide.com/hsn",
                message: "TypeError: x is undefined",
                stack: "at f (a.js:1)",
                user_agent: "UA",
                occurrences: 12,
                first_seen_at: "2026-10-01T10:00:00Z",
                last_seen_at: "2026-10-20T10:00:00Z",
              },
            ],
            total: 1,
          }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Browser errors" }));

    const table = await screen.findByRole("table", {});
    expect(within(table).getByText("TypeError: x is undefined")).toBeInTheDocument();
    expect(within(table).getByText("12")).toBeInTheDocument();
    expect(global.fetch.mock.calls[0][0]).toContain("/api/v1/feedback/errors");

    await userEvent.click(within(table).getByRole("button", { name: "Mark fixed" }));
    const del = global.fetch.mock.calls.find(([, init]) => init?.method === "DELETE");
    expect(del[0]).toBe("/api/v1/feedback/errors/7");
    expect(await screen.findByText("No browser errors have been reported.")).toBeInTheDocument();
  });
});

describe("AdminFeedbackPage paging after a delete", () => {
  // A delete took the row off the screen and asked the server nothing more.
  // The server's next page then started as many rows further on as had been
  // deleted, so those rows appeared on neither page; and deleting the last row
  // on the last page left "No feedback matches these filters." with the pager
  // gone, though the count said there was more.
  function server(rows) {
    const store = [...rows];
    global.fetch = vi.fn((url, init) => {
      const u = new URL(url, "http://x");
      if (init?.method === "DELETE") {
        const id = Number(u.pathname.split("/").at(-1));
        store.splice(store.findIndex((r) => r.id === id), 1);
        return Promise.resolve({ ok: true, status: 204, text: () => Promise.resolve("") });
      }
      const limit = Number(u.searchParams.get("limit") ?? 50);
      const offset = Number(u.searchParams.get("offset") ?? 0);
      return respond(200, { items: store.slice(offset, offset + limit), total: store.length });
    });
  }

  const feedback = (n) =>
    Array.from({ length: n }, (_, i) => ({
      id: n - i,
      category: "general",
      message: `Message ${n - i}`,
      email: null,
      page_url: null,
      user_agent: null,
      ip_address: null,
      metadata: null,
      created_at: "2026-10-20T10:00:00Z",
    }));

  afterEach(() => vi.restoreAllMocks());

  it("brings the next row up instead of skipping it", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    server(feedback(51));
    renderPage();
    const table = await screen.findByRole("table");
    expect(within(table).queryByText("Message 1")).not.toBeInTheDocument();

    await userEvent.click(within(table).getAllByRole("button", { name: "Delete" })[0]);

    expect(await screen.findByText("Message 1")).toBeInTheDocument();
    expect(screen.getByText("1–50 of 50")).toBeInTheDocument();
  });

  it("steps back a page when it deletes the last row of the last one", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    server(feedback(51));
    renderPage();
    await screen.findByRole("table");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("51–51 of 51")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("1–50 of 50")).toBeInTheDocument();
    expect(screen.queryByText("No feedback matches these filters.")).not.toBeInTheDocument();
  });

  it("pages the browser error log instead of stopping at the first fifty", async () => {
    const errors = Array.from({ length: 55 }, (_, i) => ({
      id: 55 - i,
      page: "/hsn",
      message: `Error ${55 - i}`,
      stack: null,
      user_agent: null,
      occurrences: 1,
      first_seen_at: "2026-10-01T10:00:00Z",
      last_seen_at: "2026-10-20T10:00:00Z",
    }));
    server(feedback(1));
    renderPage();
    await screen.findByRole("table");
    server(errors);
    await userEvent.click(screen.getByRole("button", { name: "Browser errors" }));
    await screen.findByText("Error 55");

    await userEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Error 1")).toBeInTheDocument();
    expect(screen.getByText("51–55 of 55")).toBeInTheDocument();
  });
});
