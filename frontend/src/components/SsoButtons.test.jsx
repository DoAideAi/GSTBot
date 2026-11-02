import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../lib/api";
import SsoButtons from "./SsoButtons";

afterEach(() => vi.restoreAllMocks());

describe("sign-in provider availability", () => {
  it("offers only the providers the server configured", async () => {
    vi.spyOn(api, "authProviders").mockResolvedValue({ providers: ["google"] });
    render(<SsoButtons />);
    expect(await screen.findByRole("link", { name: "Continue with Google" })).toHaveAttribute("href", "/api/v1/auth/google");
    expect(screen.queryByRole("link", { name: /Microsoft/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /GitHub/ })).not.toBeInTheDocument();
  });

  it("enables Microsoft and GitHub when available without another frontend release", async () => {
    vi.spyOn(api, "authProviders").mockResolvedValue({ providers: ["microsoft", "github", "unrecognised"] });
    render(<SsoButtons />);
    expect(await screen.findByRole("link", { name: "Continue with Microsoft" })).toHaveAttribute("href", "/api/v1/auth/microsoft");
    expect(screen.getByRole("link", { name: "Continue with GitHub" })).toHaveAttribute("href", "/api/v1/auth/github");
    expect(screen.getAllByRole("link")).toHaveLength(2);
  });

  it.each([[], ["unknown"]])("does not show an empty divider with %j", async (providers) => {
    vi.spyOn(api, "authProviders").mockResolvedValue({ providers });
    const { container } = render(<SsoButtons />);
    await act(async () => {});
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps email sign-in available and retries a failed provider lookup", async () => {
    const user = userEvent.setup();
    const lookup = vi.spyOn(api, "authProviders").mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ providers: ["google"] });
    render(<SsoButtons />);
    expect(await screen.findByRole("status")).toHaveTextContent("You can use your email below");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("link", { name: "Continue with Google" })).toBeInTheDocument();
    expect(lookup).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("ignores a late response after leaving the page", async () => {
    let resolve;
    vi.spyOn(api, "authProviders").mockReturnValue(new Promise((done) => { resolve = done; }));
    const { unmount, container } = render(<SsoButtons />);
    unmount();
    await act(async () => resolve({ providers: ["microsoft"] }));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });
});
