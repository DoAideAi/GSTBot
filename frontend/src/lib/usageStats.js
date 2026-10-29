// One fetch of /meta/stats per page load, shared by every component that
// shows social proof. The numbers are real aggregates from the backend — the
// fabricated "N people used this today" counters these replaced are exactly
// what a visitor who checks twice stops trusting.
import { api } from "./api";

// Below this a real figure reads as an admission rather than proof, so the
// components fall back to non-numeric copy ("Free • No login required")
// instead of showing it. The floor never rounds a number up: a stat is either
// shown as it is or not shown.
export const STAT_FLOOR = 100;

let inflight = null;

export function getUsageStats() {
  if (!inflight) {
    // A failed fetch resolves to null rather than rejecting: no caller has a
    // better plan for a missing stat than quietly not rendering it.
    //
    // And the failure is not kept. Only a success is shared for the rest of
    // the page load. This is a single-page app, so a cached null meant one
    // unreachable moment (a visitor landing during a deploy's restart) hid the
    // figures on every page until a full reload. The next component to ask
    // asks the server again.
    const pending = api.stats().then(
      (stats) => (stats && typeof stats === "object" ? stats : null),
      () => null,
    );
    inflight = pending;
    pending.then((stats) => {
      if (stats === null && inflight === pending) inflight = null;
    });
  }
  return inflight;
}

/** A display string for a stat, or null when it should not be shown. */
export function formatStat(value) {
  return Number.isFinite(value) && value >= STAT_FLOOR
    ? value.toLocaleString("en-IN")
    : null;
}
