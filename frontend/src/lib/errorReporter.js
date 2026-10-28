import { noteError } from "./sessionTracker";

/**
 * Uncaught errors, reported to the server on their own — separate from
 * feedback, which only carries a count of them.
 *
 * Each distinct (page, message) is sent once per page load: the server counts
 * repeats too, but a render loop throwing on every frame should not become a
 * request per frame. Reporting never throws and never reports itself.
 */

const ENDPOINT = "/api/v1/feedback/error";
const MAX_STACK = 10_000;
const MAX_MESSAGE = 2000;

let sent = new Set();
let uninstall = null;
let reporting = false;

function pageUrl(win) {
  return `${win.location.origin}${win.location.pathname}`;
}

export function reportError(error, { win = window, fetchImpl } = {}) {
  if (reporting) return;
  const message = String(error?.message || error || "").trim().slice(0, MAX_MESSAGE);
  // "Script error." is a cross-origin script the browser will not describe:
  // there is nothing in it to act on.
  if (!message || message === "Script error.") return;
  const page = pageUrl(win);
  const key = `${page}\n${message}`;
  if (sent.has(key)) return;
  sent.add(key);

  const stack = typeof error?.stack === "string" ? error.stack.slice(0, MAX_STACK) : null;
  const send = fetchImpl ?? win.fetch?.bind(win);
  if (!send) return;
  reporting = true;
  try {
    send(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page, message, stack }),
      // Survives the tab closing straight after the error.
      keepalive: true,
    }).catch(() => {});
  } catch {
    // A report that cannot be sent is dropped; it must not become an error itself.
  } finally {
    reporting = false;
  }
}

export function installErrorReporter(win = window) {
  if (uninstall) return uninstall;
  const onError = (e) => reportError(e?.error ?? { message: e?.message }, { win });
  const onRejection = (e) => reportError(e?.reason ?? { message: "Unhandled promise rejection" }, { win });
  win.addEventListener("error", onError);
  win.addEventListener("unhandledrejection", onRejection);
  uninstall = () => {
    win.removeEventListener("error", onError);
    win.removeEventListener("unhandledrejection", onRejection);
    sent = new Set();
    uninstall = null;
  };
  return uninstall;
}

/** For the React error boundary: a render crash never reaches window.onerror in production. */
export function reportRenderError(error) {
  noteError(error?.message || String(error));
  reportError(error);
}
