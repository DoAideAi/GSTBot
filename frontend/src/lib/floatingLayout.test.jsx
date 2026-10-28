import { act, cleanup, render } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { useBottomBar, useExclusivePanel } from "./floatingLayout";

function Bar({ height, active = true }) {
  const ref = useRef(null);
  useBottomBar(ref, active);
  return <div ref={ref} data-height={height} />;
}

const barHeight = () => document.documentElement.style.getPropertyValue("--bottom-bar-height");

// jsdom lays nothing out, so each bar reports the height it was given.
const realRect = Element.prototype.getBoundingClientRect;
function fakeHeights() {
  Element.prototype.getBoundingClientRect = function rect() {
    return { height: Number(this.dataset?.height ?? 0) };
  };
}

afterEach(() => {
  // Unmount first: an unmounting bar republishes the height this then clears.
  cleanup();
  Element.prototype.getBoundingClientRect = realRect;
  document.documentElement.style.removeProperty("--bottom-bar-height");
});

describe("useBottomBar", () => {
  it("lifts the corner by a visible bar's height, and drops it when the bar goes", () => {
    fakeHeights();
    const { unmount } = render(<Bar height={58} />);
    expect(barHeight()).toBe("58px");
    unmount();
    expect(barHeight()).toBe("0px");
  });

  it("uses the taller of two bars, and the other when one goes", () => {
    fakeHeights();
    const { rerender } = render(
      <>
        <Bar height={58} />
        <Bar height={104} />
      </>,
    );
    expect(barHeight()).toBe("104px");
    rerender(
      <>
        <Bar height={58} />
        <Bar height={104} active={false} />
      </>,
    );
    expect(barHeight()).toBe("58px");
  });

  it("does not lift anything for a bar that is not showing", () => {
    fakeHeights();
    render(<Bar height={58} active={false} />);
    expect(barHeight()).toBe("");
  });
});

function Panel({ name, label }) {
  const [open, setOpen] = useState(false);
  const close = () => setOpen(false);
  useExclusivePanel(name, open, close);
  return (
    <button type="button" aria-pressed={open} onClick={() => setOpen(true)}>
      {label}
    </button>
  );
}

describe("useExclusivePanel", () => {
  it("closes one corner panel when the other opens", () => {
    const { getByText } = render(
      <>
        <Panel name="feedback" label="feedback" />
        <Panel name="advisor" label="advisor" />
      </>,
    );
    act(() => getByText("feedback").click());
    expect(getByText("feedback")).toHaveAttribute("aria-pressed", "true");
    act(() => getByText("advisor").click());
    expect(getByText("advisor")).toHaveAttribute("aria-pressed", "true");
    expect(getByText("feedback")).toHaveAttribute("aria-pressed", "false");
  });
});
