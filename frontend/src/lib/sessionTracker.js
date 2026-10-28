/**
 * What a visit looked like, so a feedback note can carry it without the visitor
 * having to explain: the pages they went through, how long they have been on
 * this one, how far they scrolled, where they clicked in frustration, whether a
 * form defeated them, whether the page threw.
 *
 * In memory only — nothing here is written to storage, and it is all gone when
 * the tab closes. It is sent nowhere on its own: `snapshot()` is read when, and
 * only when, the visitor submits feedback.
 *
 * Nothing the visitor typed or read is captured. A click is described by the
 * element's tag, id and first class; a page by its path, without the query.
 * The feedback widget's own clicks, typing and form are not counted, or
 * writing a long note would look like a struggle with the page it is about.
 */

// Rage clicks: three or more on one element, each within this long of the last.
const RAGE_WINDOW_MS = 800;
const RAGE_THRESHOLD = 3;
// A form worked on this long without being submitted counts as abandoned.
export const FORM_STALL_MS = 2 * 60 * 1000;
const MAX_PAGES = 50;
const MAX_TARGETS = 10;
const MAX_ERRORS = 5;
const MAX_TEXT = 300;

const WIDGET = "[data-feedback-widget]";

// First match wins, so the specific paths come before the prefixes they share.
const AREAS = [
  [/^\/(gstin-validator|gstin\/|lookup|registration-checker|gst-state-codes)/, "GSTIN Lookup"],
  [/^\/(hsn|hsn-sac-finder|gst-rates?|rate-comparison)/, "HSN & Rates"],
  [/^\/(reconcile|gstr2b-reconciliation|gstr3b-reconciliation|itc-reconciliation-dashboard|itc-mismatch)/, "Reconciliation"],
  [/^\/(itc|input-tax-credit|itc-)/, "Input Tax Credit"],
  [/^\/(filing|filing-checklist|gstr9|return-calendar|due-dates)/, "Returns & Filing"],
  [/^\/(invoices|upload|invoice-generator|e-invoice-generator|eway-bill)/, "Invoices"],
  [/^\/(pricing|usage|status)/, "Premium"],
  [/^\/(suppliers|alerts)/, "Suppliers & Alerts"],
  [/^\/admin\//, "Admin"],
  [/calculator|late-fee|penalty|refund|challan/, "Calculators"],
  [/^\/(guides|blog|resources|compare|best-gst-software)/, "Guides & Content"],
  [/^\/(login|auth)/, "Sign-in"],
  [/^\/(advisor)/, "AI Advisor"],
  [/^\/$/, "Home"],
];

export function featureArea(pathname) {
  for (const [pattern, label] of AREAS) if (pattern.test(pathname)) return label;
  return "Other";
}

function describe(el) {
  if (!el || !el.tagName) return "unknown";
  const tag = el.tagName.toLowerCase();
  const id = el.id ? `#${el.id}` : "";
  const cls =
    typeof el.className === "string" && el.className.trim()
      ? `.${el.className.trim().split(/\s+/)[0]}`
      : "";
  return `${tag}${id}${cls}`.slice(0, 120);
}

function inWidget(el) {
  return Boolean(el && typeof el.closest === "function" && el.closest(WIDGET));
}

function wasReload(win) {
  try {
    const [nav] = win.performance?.getEntriesByType?.("navigation") ?? [];
    if (nav) return nav.type === "reload";
    // The deprecated API, for browsers without Navigation Timing 2: 1 is TYPE_RELOAD.
    return win.performance?.navigation?.type === 1;
  } catch {
    return false;
  }
}

function freshPage(path, now) {
  return {
    path,
    startedAt: now,
    maxScrollPct: 0,
    clicks: 0,
    rageClicks: 0,
    rageTargets: [],
    lastClick: null,
    formStartedAt: null,
    errors: 0,
    errorMessages: [],
  };
}

let state = null;
let uninstall = null;

export function installSessionTracker(win = window, clock = () => Date.now()) {
  if (uninstall) return uninstall;
  const now = clock();
  state = {
    clock,
    sessionStartedAt: now,
    reloaded: wasReload(win),
    pages: [win.location.pathname],
    page: freshPage(win.location.pathname, now),
  };

  const onScroll = () => {
    const doc = win.document.documentElement;
    const scrollable = doc.scrollHeight - win.innerHeight;
    const pct = scrollable <= 0 ? 100 : Math.round((win.scrollY / scrollable) * 100);
    state.page.maxScrollPct = Math.max(state.page.maxScrollPct, Math.min(100, Math.max(0, pct)));
  };

  const onClick = (e) => {
    if (inWidget(e.target)) return;
    const page = state.page;
    page.clicks += 1;
    const target = describe(e.target);
    const at = state.clock();
    const last = page.lastClick;
    if (last && last.target === target && at - last.at <= RAGE_WINDOW_MS) {
      last.run += 1;
      last.at = at;
      // Counted once per burst, at the click that makes it one.
      if (last.run === RAGE_THRESHOLD) {
        page.rageClicks += 1;
        if (!page.rageTargets.includes(target) && page.rageTargets.length < MAX_TARGETS) {
          page.rageTargets.push(target);
        }
      }
    } else {
      page.lastClick = { target, at, run: 1 };
    }
  };

  const onFocusIn = (e) => {
    if (inWidget(e.target)) return;
    if (e.target?.closest?.("form") && state.page.formStartedAt === null) {
      state.page.formStartedAt = state.clock();
    }
  };

  const onSubmit = (e) => {
    if (inWidget(e.target)) return;
    state.page.formStartedAt = null;
  };

  const onError = (e) => {
    const message = e?.message || e?.reason?.message || String(e?.reason ?? "Unknown error");
    noteError(message);
  };

  win.addEventListener("scroll", onScroll, { passive: true });
  win.addEventListener("click", onClick, true);
  win.addEventListener("focusin", onFocusIn, true);
  win.addEventListener("submit", onSubmit, true);
  win.addEventListener("error", onError);
  win.addEventListener("unhandledrejection", onError);

  uninstall = () => {
    win.removeEventListener("scroll", onScroll);
    win.removeEventListener("click", onClick, true);
    win.removeEventListener("focusin", onFocusIn, true);
    win.removeEventListener("submit", onSubmit, true);
    win.removeEventListener("error", onError);
    win.removeEventListener("unhandledrejection", onError);
    uninstall = null;
    state = null;
  };
  return uninstall;
}

/** Also called by the error reporter for crashes the window never sees (render errors). */
export function noteError(message) {
  if (!state) return;
  const page = state.page;
  page.errors += 1;
  if (page.errorMessages.length < MAX_ERRORS) page.errorMessages.push(String(message).slice(0, MAX_TEXT));
}

export function routeChanged(pathname) {
  if (!state || state.page.path === pathname) return;
  state.page = freshPage(pathname, state.clock());
  if (state.pages[state.pages.length - 1] !== pathname) {
    state.pages.push(pathname);
    if (state.pages.length > MAX_PAGES) state.pages.shift();
  }
}

/** The visit so far, in the shape the feedback API stores as `metadata`. */
export function snapshot() {
  if (!state) return null;
  const now = state.clock();
  const page = state.page;
  const formTime = page.formStartedAt === null ? null : now - page.formStartedAt;
  const win = typeof window === "undefined" ? null : window;
  return {
    pages: state.pages.map((p) => p.slice(0, MAX_TEXT)),
    feature_area: featureArea(page.path),
    time_on_page_ms: now - page.startedAt,
    session_ms: now - state.sessionStartedAt,
    scroll_depth_pct: page.maxScrollPct,
    click_count: page.clicks,
    rage_clicks: page.rageClicks,
    rage_click_targets: [...page.rageTargets],
    form_abandoned: formTime !== null && formTime > FORM_STALL_MS,
    ...(formTime !== null ? { form_time_ms: formTime } : {}),
    js_errors: page.errors,
    js_error_messages: [...page.errorMessages],
    reloaded: state.reloaded,
    ...(win ? { viewport: `${win.innerWidth}x${win.innerHeight}` } : {}),
  };
}
