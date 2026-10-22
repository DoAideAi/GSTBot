import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

// The number is read at module load, so each case imports a fresh copy of the
// page after setting (or clearing) the build-time variable.
async function renderWith(number) {
  vi.resetModules();
  vi.stubEnv("VITE_WHATSAPP_NUMBER", number);
  const { default: WhatsAppPage } = await import("./WhatsAppPage");
  return render(
    <MemoryRouter>
      <WhatsAppPage />
    </MemoryRouter>,
  );
}

describe("WhatsAppPage", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.useRealTimers();
  });

  describe("before the bot has a number", () => {
    it("says the bot is coming instead of linking to a placeholder chat", async () => {
      await renderWith("");
      expect(screen.getByRole("status")).toHaveTextContent(/launching soon/i);
      expect(screen.queryByText("Start Chatting")).not.toBeInTheDocument();
      expect(document.querySelector('a[href*="wa.me"]')).toBeNull();
    });

    it("sends the reader to the same lookups on the web", async () => {
      await renderWith("");
      const status = screen.getByRole("status");
      const hrefs = [...status.querySelectorAll("a")].map((a) => a.getAttribute("href"));
      expect(hrefs).toEqual(["/calculator", "/lookup", "/hsn"]);
    });

    it("does not tell the reader to save a number that does not exist", async () => {
      await renderWith("");
      expect(screen.getByText(/published here at launch/i)).toBeInTheDocument();
      expect(document.body.textContent).not.toMatch(/9999999999/);
    });

    it("keeps operator configuration off the public page", async () => {
      await renderWith("");
      expect(document.body.textContent).not.toMatch(/WHATSAPP_TWILIO_AUTH_TOKEN/);
    });
  });

  describe("once a number is configured", () => {
    it("links the chat button to that number with only its digits", async () => {
      await renderWith("+91 98765 43210");
      const link = screen.getByText("Start Chatting").closest("a");
      expect(link).toHaveAttribute("href", "https://wa.me/919876543210?text=hi");
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
      expect(screen.getByText(/Save \+91 98765 43210 to your contacts/)).toBeInTheDocument();
    });

    it("copies the number and confirms it briefly", async () => {
      const writeText = vi.fn().mockResolvedValue();
      Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
      await renderWith("+919876543210");
      vi.useFakeTimers({ shouldAdvanceTime: true });

      await userEvent.click(screen.getByText("Copy Number"));
      expect(writeText).toHaveBeenCalledWith("+919876543210");
      expect(await screen.findByText("Copied!")).toBeInTheDocument();

      await act(() => vi.advanceTimersByTimeAsync(2000));
      expect(screen.getByText("Copy Number")).toBeInTheDocument();
    });

    it("stays quiet when the clipboard refuses", async () => {
      const writeText = vi.fn().mockRejectedValue(new Error("denied"));
      Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
      await renderWith("+919876543210");

      await userEvent.click(screen.getByText("Copy Number"));
      expect(screen.getByText("Copy Number")).toBeInTheDocument();
    });
  });
});
