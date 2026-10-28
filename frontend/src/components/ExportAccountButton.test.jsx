import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import ExportAccountButton from "./ExportAccountButton";

const api = vi.hoisted(() => ({ exportAccount: vi.fn() }));
vi.mock("../lib/api", () => ({ api }));

function renderAs(role) {
  return render(
    <StubAuth role={role}>
      <ExportAccountButton />
    </StubAuth>,
  );
}

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:export");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => vi.clearAllMocks());

describe("ExportAccountButton", () => {
  it("downloads the account under the server's filename", async () => {
    const blob = new Blob(["{}"]);
    api.exportAccount.mockResolvedValue({ blob, filename: "doaide-gst-export.json" });
    renderAs("owner");

    await userEvent.click(screen.getByRole("button", { name: "Export data" }));

    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledWith(blob));
    expect(URL.revokeObjectURL).toHaveBeenCalled();
  });

  it.each(["accountant", "viewer"])("is not offered to an %s, whom the API refuses", (role) => {
    renderAs(role);
    expect(screen.queryByRole("button", { name: "Export data" })).toBeNull();
  });

  it("says why when the export fails", async () => {
    api.exportAccount.mockRejectedValue(new Error("Too many requests"));
    renderAs("owner");

    await userEvent.click(screen.getByRole("button", { name: "Export data" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Export failed: Too many requests");
    expect(screen.getByRole("button", { name: "Export data" })).not.toBeDisabled();
  });
});
