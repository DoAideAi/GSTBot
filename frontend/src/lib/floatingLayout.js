import { useEffect } from "react";

/**
 * The bottom-right corner is shared: the WhatsApp button, the Feedback pill
 * and the AI advisor stack up it, and two full-width bars (the free-tools
 * banner, and the sign-up bar on phones) can slide in along the bottom edge.
 *
 * The bars used to sit *under* the floats — the sign-up bar at z-index 999
 * covered the WhatsApp button entirely on a phone, and the WhatsApp button sat
 * on the tools banner's close button. Now a visible bar publishes its height as
 * `--bottom-bar-height` and the floats lift by it. Measured rather than
 * assumed, so a bar that wraps on a narrow screen, or one hidden by a media
 * query (height 0), lifts them by exactly what it occupies.
 */

const heights = new Map();

function publish(doc) {
  const tallest = Math.max(0, ...heights.values());
  doc.documentElement.style.setProperty("--bottom-bar-height", `${tallest}px`);
}

export function useBottomBar(ref, active, { doc = document } = {}) {
  useEffect(() => {
    const el = ref.current;
    if (!active || !el) return undefined;
    const key = {};
    const measure = () => {
      heights.set(key, el.getBoundingClientRect().height);
      publish(doc);
    };
    measure();
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(measure) : null;
    observer?.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", measure);
      heights.delete(key);
      publish(doc);
    };
  }, [ref, active, doc]);
}

/**
 * The feedback form and the advisor open into the same space above the
 * corner. Opening one closes the other rather than stacking two panels.
 */
const PANEL_EVENT = "gstbot:panel-open";

export function useExclusivePanel(name, open, close) {
  useEffect(() => {
    if (!open) return undefined;
    window.dispatchEvent(new CustomEvent(PANEL_EVENT, { detail: name }));
    const onOther = (e) => {
      if (e.detail !== name) close();
    };
    window.addEventListener(PANEL_EVENT, onOther);
    return () => window.removeEventListener(PANEL_EVENT, onOther);
  }, [name, open, close]);
}
