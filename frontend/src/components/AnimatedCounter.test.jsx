import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import AnimatedCounter from "./AnimatedCounter";

describe("AnimatedCounter", () => {
  let mockObserve;
  let mockDisconnect;

  beforeEach(() => {
    mockObserve = vi.fn();
    mockDisconnect = vi.fn();
    window.IntersectionObserver = vi.fn(function () {
      this.observe = mockObserve;
      this.disconnect = mockDisconnect;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders with initial zero value", () => {
    render(<AnimatedCounter end={5000} />);

    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("renders with prefix and suffix", () => {
    render(<AnimatedCounter end={100} prefix="$" suffix="+" />);

    // Initial state shows 0 with prefix/suffix
    expect(screen.getByText("$0+")).toBeInTheDocument();
  });

  it("creates an IntersectionObserver", () => {
    render(<AnimatedCounter end={1000} />);

    expect(window.IntersectionObserver).toHaveBeenCalledTimes(1);
    expect(mockObserve).toHaveBeenCalledTimes(1);
  });

  it("disconnects observer on unmount", () => {
    const { unmount } = render(<AnimatedCounter end={1000} />);

    unmount();
    expect(mockDisconnect).toHaveBeenCalledTimes(1);
  });

  it("has the animated-counter class", () => {
    const { container } = render(<AnimatedCounter end={500} />);

    expect(container.querySelector(".animated-counter")).toBeTruthy();
  });

  describe("for someone who is not watching it count", () => {
    // P37 M17: the text a screen reader read was whatever the animation had
    // reached, which is "0" until the figure scrolls into view. A screen reader's
    // virtual cursor need not scroll, so the trust strip could be read as
    // "0+ Businesses on DoAide GST". Every frame also swapped the text under it,
    // and a visitor who asked the OS for reduced motion still got the count.

    afterEach(() => {
      delete window.matchMedia;
    });

    it("gives assistive technology the real figure before any animation runs", () => {
      const { container } = render(<AnimatedCounter end={5000} suffix="+" />);

      expect(screen.getByText("5k+")).toBeInTheDocument();
      const ticking = container.querySelector("[aria-hidden='true']");
      expect(ticking).toHaveTextContent("0+");
    });

    it("shows the figure at once when reduced motion is asked for", () => {
      window.matchMedia = vi.fn((query) => ({
        matches: query.includes("prefers-reduced-motion: reduce"),
        media: query,
      }));
      const { container } = render(<AnimatedCounter end={250} suffix="+" />);

      expect(container.querySelector("[aria-hidden='true']")).toHaveTextContent("250+");
      expect(window.IntersectionObserver).not.toHaveBeenCalled();
    });
  });
});
