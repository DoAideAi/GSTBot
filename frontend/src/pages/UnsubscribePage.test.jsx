import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import UnsubscribePage from "./UnsubscribePage";

// The reminder's unsubscribe link opened the API itself, which showed a person
// a raw JSON object. It opens this page now — which acts only on a click,
// because mail scanners follow every link in a message.

const TOKEN = "a".repeat(64);

function land(query = `?email=a%40example.com&token=${TOKEN}`) {
  render(
    <MemoryRouter initialEntries={[`/unsubscribe${query}`]}>
      <UnsubscribePage />
    </MemoryRouter>,
  );
}

function respond(body) {
  return Promise.resolve({ ok: true, status: 200, statusText: "", text: async () => JSON.stringify(body) });
}

describe("UnsubscribePage", () => {
  afterEach(() => vi.restoreAllMocks());

  it("does nothing until the button is pressed", () => {
    global.fetch = vi.fn();
    land();
    expect(screen.getByText("a@example.com")).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("unsubscribes the address in the link on a click", async () => {
    global.fetch = vi.fn(() => respond({ unsubscribed: true, message: "You've been unsubscribed." }));
    land();

    await userEvent.click(screen.getByRole("button", { name: "Unsubscribe" }));

    expect(await screen.findByRole("status")).toHaveTextContent("You've been unsubscribed.");
    const [url, init] = global.fetch.mock.calls[0];
    expect(init.method).toBe("POST");
    const u = new URL(url, "http://x");
    expect(u.pathname).toBe("/api/v1/subscribers/unsubscribe");
    expect(u.searchParams.get("email")).toBe("a@example.com");
    expect(u.searchParams.get("token")).toBe(TOKEN);
  });

  it("says so when the link was not one we sent", async () => {
    global.fetch = vi.fn(() => respond({ unsubscribed: false, error: "Invalid or expired link." }));
    land();

    await userEvent.click(screen.getByRole("button", { name: "Unsubscribe" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid or expired link.");
  });

  it("explains a link with nothing in it", () => {
    global.fetch = vi.fn();
    land("");
    expect(screen.getByRole("alert")).toHaveTextContent("link");
    expect(screen.queryByRole("button", { name: "Unsubscribe" })).not.toBeInTheDocument();
  });
});
