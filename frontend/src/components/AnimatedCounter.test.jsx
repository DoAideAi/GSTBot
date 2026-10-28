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
});
