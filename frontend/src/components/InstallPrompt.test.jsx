import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import InstallPrompt from "./InstallPrompt";

function fireInstallable() {
  const event = new Event("beforeinstallprompt");
  event.prompt = vi.fn();
  event.userChoice = Promise.resolve({ outcome: "accepted" });
  fireEvent(window, event);
  return event;
}

describe("InstallPrompt", () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  it("stays hidden until the browser offers an install", () => {
    render(<InstallPrompt />);
    expect(screen.queryByText("Install DoAide GST")).not.toBeInTheDocument();
  });

  it("appears on beforeinstallprompt and installs on click", async () => {
    render(<InstallPrompt />);
    const event = fireInstallable();
    expect(screen.getByText("Install DoAide GST")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    expect(event.prompt).toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByText("Install DoAide GST")).not.toBeInTheDocument(),
    );
  });

  it("stays dismissed for the session once closed", () => {
    const { unmount } = render(<InstallPrompt />);
    fireInstallable();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Install DoAide GST")).not.toBeInTheDocument();

    // A later page view in the same session must not nag again.
    unmount();
    render(<InstallPrompt />);
    fireInstallable();
    expect(screen.queryByText("Install DoAide GST")).not.toBeInTheDocument();
  });
});
