import { useCallback, useRef } from "react";
import { track } from "../lib/track";

/**
 * Did the visitor finish what they started with *tool*?
 *
 * Two events per visit at most: `tool_start` the first time they engage with
 * the tool, and `tool_complete` the first time it gives them what it exists to
 * give. Completion rate is then one count divided by the other, per tool, in
 * Umami — and a tool where many start and few finish is the one whose form is
 * in the way.
 *
 * Once each, because both questions are about the visit, not the keystroke:
 * someone who adjusts an amount ten times has started once, and someone who
 * downloads three invoices has still completed the tool.
 *
 * A completion counts only after a start. A shared link can arrive with its
 * inputs filled and the result already on screen; that visitor did nothing,
 * and counting them as a finish would inflate the rate with people who never
 * used the form. Where finishing is itself the engagement — a download button
 * pressed on the defaults — the caller calls `start()` first.
 */
export function useToolFunnel(tool) {
  const started = useRef(false);
  const completed = useRef(false);

  const start = useCallback(() => {
    if (started.current) return;
    started.current = true;
    track("tool_start", { tool });
  }, [tool]);

  const complete = useCallback(() => {
    if (completed.current || !started.current) return;
    completed.current = true;
    track("tool_complete", { tool });
  }, [tool]);

  return { start, complete };
}
