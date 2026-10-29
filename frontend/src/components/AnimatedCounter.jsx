import { useEffect, useRef, useState } from "react";

const format = (n) => {
  if (n >= 1000) return `${Math.round(n / 1000).toLocaleString("en-IN")}k`;
  return n.toLocaleString("en-IN");
};

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Animates a number from 0 to `end` when the element scrolls into view.
 * Uses requestAnimationFrame for smooth animation with an ease-out curve.
 *
 * The count is for the eye only. What a screen reader reads is the real
 * figure, in a visually hidden span beside it: the animated text is "0" until
 * the element scrolls into view, a screen reader's virtual cursor need not
 * scroll, and the trust strip was read out as "0+ Businesses on DoAide GST".
 * Every frame also rewrote the text under the cursor. A visitor who has asked
 * for reduced motion gets the figure at once.
 */
export default function AnimatedCounter({ end, duration = 1500, prefix = "", suffix = "" }) {
  const [display, setDisplay] = useState(() => (prefersReducedMotion() ? format(end) : "0"));
  const ref = useRef(null);
  const started = useRef(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Gracefully degrade when IntersectionObserver is unavailable (SSR, old
    // browsers, tests), and skip the motion for anyone who asked for less.
    if (prefersReducedMotion() || typeof IntersectionObserver === "undefined") {
      setDisplay(format(end));
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started.current) {
          started.current = true;
          const t0 = performance.now();
          const step = (now) => {
            const progress = Math.min((now - t0) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            setDisplay(format(Math.round(eased * end)));
            if (progress < 1) requestAnimationFrame(step);
          };
          requestAnimationFrame(step);
        }
      },
      { threshold: 0.3 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [end, duration]);

  return (
    <span ref={ref} className="animated-counter">
      <span aria-hidden="true">
        {prefix}{display}{suffix}
      </span>
      <span className="sr-only">
        {prefix}{format(end)}{suffix}
      </span>
    </span>
  );
}
