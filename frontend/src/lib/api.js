import { track } from "./track";

// API client for the DoAide GST backend.
// Stores the JWT in localStorage and attaches it as a Bearer token.

const BASE = "/api/v1";
const TOKEN_KEY = "gstbot_token";
const ACTIVE_BUSINESS_KEY = "gstbot_active_business_id";

/**
 * Where a key goes when the browser will not store it.
 *
 * Touching `localStorage` is not a safe operation. A browser configured to
 * block all site data, a sandboxed iframe, and a full quota each throw a
 * `SecurityError` or `QuotaExceededError` on access rather than answering null
 * — and this module was reading it bare. `AuthProvider` calls `getToken()`
 * synchronously in an effect, so the throw landed in the outer ErrorBoundary:
 * the whole app became the crash screen, on every reload, with no way through
 * it. A compliance app that cannot be signed into by someone whose IT has
 * locked the browser down is worse than one whose session ends with the tab.
 *
 * So this degrades the way the backend degrades when Redis is gone — falls back
 * in-process, never fails the operation. The cost is precisely stated: the
 * session lives for the life of the tab and does not survive a reload. Signing
 * in, switching business, and every request in between still work.
 *
 * Guarded per call rather than probed once at import, because the two failures
 * are not the same shape: blocked site data throws on the first read forever,
 * while a quota fills up mid-session and throws on a write while reads keep
 * working.
 */
const fallbackStore = new Map();

function readStored(key) {
  // The fallback wins wherever it holds the key. It only ever holds one
  // because a write was refused, which makes whatever `localStorage` still
  // answers for that key strictly older — a stale token that could not be
  // overwritten must not beat the one this session actually signed in with.
  if (fallbackStore.has(key)) return fallbackStore.get(key);
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
    // Cleared on success so the two cannot diverge if storage comes back —
    // a quota freed by another tab, say.
    fallbackStore.delete(key);
  } catch {
    // `null` is stored rather than deleted: it has to shadow the value still
    // sitting in a `localStorage` that would not let us remove it, or signing
    // out would leave the old token readable on the next call.
    fallbackStore.set(key, value);
  }
}

export function getToken() {
  return readStored(TOKEN_KEY);
}

export function setToken(token) {
  writeStored(TOKEN_KEY, token || null);
}

/**
 * Which business a request acts for, beyond the caller's own tenant.
 *
 * Most logins never set this — every request acts for the caller's own
 * business by default, exactly as it always has. It only exists for a login
 * that has linked another GSTIN registration with `api.linkBusiness` and
 * wants a request to act for that one instead; see `X-Business-Id` on
 * `app.core.deps.get_current_business` in the backend.
 */
export function getActiveBusinessId() {
  return readStored(ACTIVE_BUSINESS_KEY);
}

export function setActiveBusinessId(id) {
  writeStored(ACTIVE_BUSINESS_KEY, id ? String(id) : null);
}

// Told when a credential this client actually sent comes back refused.
//
// Dropping the dead token is only half of what has to happen, and on its own it
// left the app in a state it could not get out of. The session lives in React
// (`useAuth`), the token lives in localStorage, and clearing one without the
// other means `user` is still set: every page goes on rendering, every request
// now goes out with no Authorization header at all, and each one comes back
// "Your session has expired. Please sign in again." — advice the user cannot take,
// because `/login` redirects to `/` for as long as `user` is truthy. A token
// expiring mid-session was therefore a dead end, escapable only by clearing
// site data. The 24-hour expiry means every user meets it.
const unauthorizedListeners = new Set();

/** Subscribe to "the token was refused". Returns an unsubscribe function. */
export function onUnauthorized(listener) {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

/**
 * A rejected token is a dead token: drop it and say so.
 *
 * Only called when the request actually carried one. A 401 from the login form
 * is a wrong password, not an expired session, and announcing it as one would
 * make the sign-in page fight its own error handling.
 */
function tokenRejected() {
  setToken(null);
  for (const listener of unauthorizedListeners) {
    try {
      listener();
    } catch {
      // A subscriber that throws must not become the error the caller sees:
      // the request has its own outcome to report and this is a side channel.
    }
  }
}

async function request(
  path,
  { method = "GET", body, form, auth = true, signal, carriesOtherCredentials = false } = {},
) {
  const headers = {};
  const token = getToken();
  if (auth && token) headers["Authorization"] = `Bearer ${token}`;
  // Sent only once a business has actually been switched to — see
  // `getActiveBusinessId`. An anonymous or single-business request never
  // carries this header, so the backend sees exactly what it always has.
  const activeBusinessId = auth ? getActiveBusinessId() : null;
  if (activeBusinessId) headers["X-Business-Id"] = activeBusinessId;

  let payload;
  if (form) {
    payload = form; // URLSearchParams or FormData — the browser sets the type.
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const res = await send(`${BASE}${path}`, { method, headers, body: payload, signal });

  // A rejected token is a dead token; drop it, and end the session with it, so
  // the app falls back to login rather than retrying with a credential the
  // server has already refused.
  //
  // Unless the request carried a *second* credential, in which case the 401 is
  // about that one. `POST /businesses/mine/link` submits another account's
  // email and password to prove the caller also holds it, and answers 401 when
  // they do not match — so mistyping the other registration's password was
  // read here as the caller's own token being refused, and signed them out of
  // the account they were signed into. The rule "a 401 means our bearer token
  // is dead" only holds while the bearer token is the only credential in the
  // request; this says when it is not. The same reasoning as `auth: false` on
  // login, which is why that one never had the problem.
  if (res.status === 401 && auth && token && !carriesOtherCredentials) tokenRejected();

  if (res.status === 204) return null;

  const text = await res.text();
  const { data, readable } = readBody(text);

  if (!res.ok) {
    const err = refusal(
      readable ? errorMessage(data, statusMessage(res)) : statusMessage(res),
      res,
      readable ? data : null,
    );
    // The top of the free-to-paid funnel: someone reached for a paid feature.
    // Counted here, once, because every gated route refuses the same way, so
    // no screen has to remember to report it. The route rather than the URL —
    // ids and query strings identify a business's rows, not a feature.
    // The 402 too: the monthly upload allowance running out is the commonest
    // way the free plan stops being enough, and it was missing from the
    // funnel because it is a different status from the feature gate.
    if (err.code === "paid_plan_required" || res.status === 402) {
      track("paywall_hit", { feature: featurePath(path) });
    }
    throw err;
  }
  if (!readable) throw new Error(unreadableMessage(res));
  return data;
}

/** `/reconciliation/12/report.pdf?x=1` -> `/reconciliation/:id/report.pdf`. */
/**
 * The plan just changed (a payment verified, or a cancellation). Anything
 * showing the plan listens for this: the header's premium badge was fetched
 * once per business and went on saying "free" after a payment until a reload.
 */
export const SUBSCRIPTION_CHANGED = "gst:subscription-changed";

export function announceSubscriptionChange() {
  window.dispatchEvent(new Event(SUBSCRIPTION_CHANGED));
}

export function featurePath(path) {
  return path.split("?")[0].replace(/\/\d+(?=\/|$)/g, "/:id");
}

/**
 * An error carrying the status that caused it.
 *
 * Some refusals are a normal state of the product rather than a problem: a
 * period with no GSTR-2B imported answers 404, and that is the empty screen
 * inviting an import, not a failure to report. Every other refusal — a 500, a
 * 503, an edge that never reached the API — has to be told to the user.
 *
 * Without the status those two are the same rejection, and a caller wanting to
 * pass over the first quietly has no way to do it except by passing over all of
 * them, which turns a backend outage into a page that says there is nothing
 * here yet.
 */
function refusal(message, res, data = null) {
  const err = new Error(message);
  err.status = res.status;
  // `error.code` is what the API's catalog says to branch on; the message is
  // prose. Null when the body was not the API's own (an edge error page).
  err.code = data?.error?.code ?? null;
  return err;
}

/**
 * Parse a response body, reporting failure rather than throwing.
 *
 * Not every response comes from the application. A 502 from Caddy, a captive
 * portal, or a corporate middlebox all answer with HTML, and `JSON.parse` on
 * that throws a SyntaxError whose message is `Unexpected token '<'` — which is
 * what the user then reads in the error banner, on the one occasion they most
 * need to be told the server is unreachable.
 *
 * `readable` distinguishes "the body was empty" (legitimate: a 201 with no
 * content) from "the body was not JSON" (the server is not who we think).
 */
function readBody(text) {
  if (!text) return { data: null, readable: true };
  try {
    return { data: JSON.parse(text), readable: true };
  } catch {
    return { data: null, readable: false };
  }
}

/**
 * The number, and only the number, as the reference a message quotes.
 *
 * `res.statusText` is deliberately not part of this, and used to be. Three
 * things are wrong with putting it in front of a user:
 *
 * It is not ours. The reason phrase is written by whichever hop answered, and
 * on a bad day that is not the API — a proxy, a captive portal, a middlebox
 * sending back whatever it likes. Rendering it into the banner puts a
 * stranger's prose in the product's voice.
 *
 * It is the wording the sentence exists to replace. "The server is having
 * trouble (500 Internal Server Error)" reintroduces the phrase in the same
 * breath as the plain-English version of it — and the backend refuses that
 * exact string in `tests/test_error_prose.py`, so the API would never say it
 * while its own client did.
 *
 * And it is not there in production anyway. HTTP/2 and HTTP/3 dropped the
 * reason phrase from the wire format, so `statusText` is `""` against the
 * server this deploys behind and non-empty on a developer's HTTP/1.1 mock —
 * which made the message a user reports one nobody could reproduce.
 *
 * The number survives all three: it is the thing support asks for, and it is
 * always there, which is why it and not `statusText` is what a caller falls
 * back to when a body carries no `detail`.
 */
function statusCode(res) {
  return `${res.status}`;
}

/** A last-resort description of a response, which is never the empty string. */
function statusMessage(res) {
  const code = statusCode(res);
  if (res.status >= 500) {
    return `The server is having trouble (${code}). Please try again in a moment.`;
  }
  if (res.status === 429) {
    return `Too many requests (${code}). Please wait a moment and try again.`;
  }
  if (res.status === 401) {
    return `Your session has expired (${code}). Please sign in again.`;
  }
  // Not the same sentence as a 401, though it used to be. Every 403 this API
  // issues is about *authorisation*, not authentication — a business you are
  // not a member of, a business that has been deactivated, an account that
  // has. The caller is signed in, and `request` deliberately does not drop
  // their token on a 403, so "please sign in again" sent them to a login page
  // that redirected straight back and changed nothing about why they were
  // refused. A cross-tenant read answers 404 rather than 403 precisely so
  // this response never means "that record is someone else's".
  if (res.status === 403) {
    return (
      `You do not have access to this (${code}). If you have just been given ` +
      `access, sign out and back in.`
    );
  }
  // A body-less 413 is the proxy's, not the API's — the API's own carries a
  // detail naming MAX_UPLOAD_MB. Either way the user picked a file, so say
  // what to do about it rather than reporting the number.
  if (res.status === 413) {
    return `That file is too large to upload (${code}). Try a smaller one.`;
  }
  if (res.status === 404) {
    return `That is not here (${code}). It may have been deleted.`;
  }
  // Whatever else could not be read: a 400, 409 or 422 whose body an edge or
  // proxy replaced. Not a dead end — the two things worth trying are named.
  return `That could not be completed (${code}). Check what you entered and try again, or reload the page.`;
}

/**
 * The browser's own words for "the request never arrived", replaced.
 *
 * `fetch` rejects rather than resolving when the request does not complete: no
 * network, DNS failure, the API down, a proxy closing the connection, TLS
 * refused. What it rejects *with* is a `TypeError` whose message is the
 * browser's — `Failed to fetch` in Chrome, `Load failed` in Safari,
 * `NetworkError when attempting to fetch resource` in Firefox — and every one
 * of those went straight into an error banner unchanged.
 *
 * That is the most common failure the product has and the least informative
 * thing it says. "Load failed" above an invoice list reads as the invoices
 * being unloadable, and the one action that would fix it — check the
 * connection, wait for the API to come back — is the one the sentence does not
 * suggest. An `AbortError` is passed through untouched: the app cancels its
 * own superseded requests, and `isAbortError` is what tells those apart.
 */
async function send(input, init) {
  try {
    return await fetch(input, init);
  } catch (err) {
    if (isAbortError(err)) throw err;
    const offline = typeof navigator !== "undefined" && navigator.onLine === false;
    const failure = new Error(
      offline
        ? "You appear to be offline. Reconnect and try again."
        : "Could not reach the server. Check your connection, or try again in a moment.",
    );
    // No `status`: nothing answered. Callers that pass over a 404 quietly —
    // a period with no GSTR-2B imported — must not also pass over this.
    failure.cause = err;
    throw failure;
  }
}

/** A 2xx whose body was not JSON: the request worked, the answer did not. */
function unreadableMessage(res) {
  return `The server sent a response this app could not read (${statusCode(res)}).`;
}

/**
 * Whether a rejection is this app cancelling its own request.
 *
 * A superseded search is aborted rather than left to land, so its rejection is
 * an expected part of the flow and not something to put in an error banner —
 * "signal is aborted without reason" in front of a user who simply kept typing
 * would be worse than the stale rows the abort exists to prevent. `fetch`
 * rejects with a `DOMException` named `AbortError`; the name is the only part
 * of it specified, so it is the only part matched on.
 */
export function isAbortError(err) {
  return err?.name === "AbortError";
}

/**
 * Flatten whatever FastAPI put in `detail` into one readable line.
 *
 * A `detail` that is present but says nothing counts as absent. `??` alone
 * only catches `null` and `undefined`, so `{"detail": ""}`, `{"detail": []}`
 * and `{"detail": {"message": ""}}` each came through as themselves and the
 * caller raised an error with an empty message — which renders as an error
 * banner with nothing written in it, the exact failure `fallback` exists to
 * prevent and the one that looks least like a bug and most like the app having
 * frozen. None of the three is hypothetical: a proxy rewriting the API's
 * envelope produces the first, a field list filtered to nothing produces the
 * second, and the third is our own conflict shape with an unset field.
 */
export function errorMessage(data, fallback = "Request failed") {
  const detail = data?.detail ?? fallback;
  // Checked on the way out rather than on the way in, so that one guard covers
  // every shape `detail` arrives in. A blank string, an empty list, and a
  // structured conflict whose `message` is "" each flatten to nothing by a
  // different route, and each of the three is a body a proxy or a filter can
  // produce.
  return flatten(detail).trim() || fallback;
}

function flatten(detail) {
  if (typeof detail === "string") return detail;
  // Validation errors arrive as a list of {loc, msg} objects.
  if (Array.isArray(detail)) {
    return detail.map((d) => (d.msg == null ? JSON.stringify(d) : fieldMessage(d))).join(", ");
  }
  // Our own structured conflicts, e.g. the duplicate-upload response.
  if (detail && typeof detail === "object") {
    return detail.message ?? JSON.stringify(detail);
  }
  return String(detail);
}

/**
 * One validation entry as a sentence that says which field it is about.
 *
 * Pydantic's own messages do not: a register form missing both fields read
 * "Field required, Field required", and a short password "String should have
 * at least 8 characters" with nothing to say which input to fix. The field is
 * the last named part of `loc`; a message that already names it — our own
 * "GSTIN check digit does not match" — is left as it is.
 */
function fieldMessage({ loc, msg }) {
  const name = Array.isArray(loc) ? [...loc].reverse().find((part) => typeof part === "string") : null;
  if (!name || ["body", "query", "path", "header"].includes(name)) return msg;
  const label = name
    .split("_")
    .map((word) => (FIELD_ACRONYMS.has(word) ? word.toUpperCase() : word))
    .join(" ");
  if (msg.toLowerCase().includes(label.toLowerCase())) return msg;
  return `${label.charAt(0).toUpperCase()}${label.slice(1)}: ${msg}`;
}

const FIELD_ACRONYMS = new Set(["gst", "gstin", "hsn", "sac", "pan", "arn", "itc", "otp"]);

export const api = {
  // ---- Auth ----
  async login(email, password) {
    // The token endpoint is OAuth2 password flow, so it takes form fields and
    // calls the email "username".
    const form = new URLSearchParams({ username: email, password });
    const data = await request("/auth/login", { method: "POST", form, auth: false });
    setToken(data.access_token);
    return data;
  },

  async register(payload) {
    // Registration returns a usable session, so there is no second login step.
    const data = await request("/auth/register", {
      method: "POST",
      body: payload,
      auth: false,
    });
    setToken(data.access_token);
    return data;
  },

  logout() {
    setToken(null);
    // A stale "acting as" business must not survive into the next session on
    // this browser — the next sign-in may be a different login entirely.
    setActiveBusinessId(null);
  },

  me: () => request("/auth/me"),

  // ---- Meta (public) ----
  validateGstin: (gstin) =>
    request(`/meta/gstin/${encodeURIComponent(gstin)}`, { auth: false }),
  // Paid plans only; a free business gets a 403 the page turns into an offer.
  validateGstinBulk: (gstins) =>
    request("/meta/gstin/bulk", { method: "POST", body: { gstins } }),
  states: () => request("/meta/states", { auth: false }),
  /**
   * Every dependency with its latency. Read by the status page.
   *
   * Answers 503 when the database is unreachable, so this is one of the few
   * calls whose *failure* is the result worth showing rather than an error to
   * report — see `StatusPage`, which keeps the two probes' outcomes apart.
   */
  health: ({ signal } = {}) => request("/health", { auth: false, signal }),

  reminderSubscribe: (email) =>
    request("/meta/reminder-subscribe", { method: "POST", body: { email }, auth: false }),
  subscribe: (email, source = "landing") =>
    request("/subscribers", { method: "POST", body: { email, source }, auth: false }),
  recentLookups: () =>
    request("/meta/recent-lookups", { auth: false }),
  stats: () =>
    request("/meta/stats", { auth: false }),

  feedback: (payload) =>
    request("/feedback", { method: "POST", body: payload }),
  // Admin-only on the server (ADMIN_EMAILS); anyone else gets a 403.
  listFeedback: (params = {}, { signal } = {}) =>
    request(`/feedback${query(params)}`, { signal }),
  deleteFeedback: (id) => request(`/feedback/${id}`, { method: "DELETE" }),
  listClientErrors: (params = {}, { signal } = {}) =>
    request(`/feedback/errors${query(params)}`, { signal }),
  deleteClientError: (id) => request(`/feedback/errors/${id}`, { method: "DELETE" }),

  // ---- Invoices ----
  uploadInvoice(file, invoiceType = "purchase") {
    const form = new FormData();
    form.append("file", file);
    form.append("invoice_type", invoiceType);
    return request("/invoices/upload", { method: "POST", form });
  },

  /**
   * Upload a batch of invoices in one request.
   *
   * Never rejects for one bad file among many — the response's `items` carry
   * one outcome per file, `accepted`/`rejected` unmatched or otherwise, so a
   * caller shows a per-file result rather than an all-or-nothing error.
   */
  bulkUploadInvoices(files, invoiceType = "purchase") {
    const form = new FormData();
    for (const file of files) form.append("files", file);
    form.append("invoice_type", invoiceType);
    return request("/invoices/bulk", { method: "POST", form });
  },

  listInvoices(params = {}, { signal } = {}) {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""),
    );
    const suffix = query.toString();
    return request(`/invoices${suffix ? `?${suffix}` : ""}`, { signal });
  },

  getInvoice: (id, { signal } = {}) => request(`/invoices/${id}`, { signal }),
  updateInvoice: (id, changes) =>
    request(`/invoices/${id}`, { method: "PATCH", body: changes }),
  reparseInvoice: (id) => request(`/invoices/${id}/reparse`, { method: "POST" }),
  deleteInvoice: (id) => request(`/invoices/${id}`, { method: "DELETE" }),

  // ---- Dashboard ----
  dashboard: (period, { signal } = {}) =>
    request(`/dashboard${period ? `?period=${encodeURIComponent(period)}` : ""}`, {
      signal,
    }),

  // ---- GSTR-2B and reconciliation ----
  importGstr2b(file, period) {
    const form = new FormData();
    form.append("file", file);
    // Omitted rather than sent empty: the server reads the period out of the
    // file when the caller does not name one, and "" is not a period.
    if (period) form.append("period", period);
    return request("/reconciliation/gstr2b/import", { method: "POST", form });
  },

  // An { items } envelope like every other list. Unwrapped here so the page
  // keeps its array; the signal is passed through (it was accepted and dropped).
  importedPeriods: ({ signal } = {}) =>
    request("/reconciliation/gstr2b/periods", { signal }).then((data) => data?.items ?? []),
  getImported2b: (period, { signal } = {}) =>
    request(`/reconciliation/gstr2b/${encodeURIComponent(period)}`, { signal }),

  reconcile: (period, tolerance) =>
    request("/reconciliation/run", {
      method: "POST",
      body: tolerance === undefined ? { period } : { period, tolerance },
    }),

  /**
   * Past runs for a period, newest first — counts only, no report.
   *
   * Abortable, like every other read the period picker drives. Runs accumulate
   * rather than overwrite: a period is reconciled again each time a supplier
   * files late and the 2B is regenerated, so this is the list of what was known
   * and when.
   */
  listReconciliations: (params = {}, { signal } = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""),
    );
    const suffix = query.toString();
    return request(`/reconciliation${suffix ? `?${suffix}` : ""}`, { signal });
  },

  /** One past run with its full per-invoice report. */
  getReconciliation: (id, { signal } = {}) => request(`/reconciliation/${id}`, { signal }),
  latestReconciliation: (period, { signal } = {}) =>
    request(`/reconciliation/latest?period=${encodeURIComponent(period)}`, { signal }),

  // ---- ITC ----
  itc: (period, params = {}, { signal } = {}) =>
    request(`/itc${query({ period, ...params })}`, { signal }),

  rule37: (asOf) => request(`/itc/rule37${query({ as_of: asOf })}`),

  /**
   * Unclaimed credit by financial year, against its s.16(4) deadline.
   *
   * The one reversal in this product that is permanent. Rules 37, 42 and 43 all
   * defer credit — pay the supplier, or the proportion changes, and it comes
   * back. Section 16(4) extinguishes it: after the 30th of November following
   * the financial year, credit on that invoice is gone and no later filing
   * recovers it. So this is the figure with a date on it that cannot be missed,
   * and it is not part of the period summary — a lapsing year is answered for
   * the whole register, not for whichever month is on screen.
   */
  lapsingCredit: (asOf, { signal } = {}) =>
    request(`/itc/lapsing${query({ as_of: asOf })}`, { signal }),

  setOff: (payload) => request("/itc/set-off", { method: "POST", body: payload }),

  // ---- Filing ----
  /**
   * What would stop a period being filed, for one direction of invoice.
   *
   * The sales side arrives with the return already — `gstr1` and `gstr3b`
   * carry the same report — so this is asked for the purchase side, which no
   * return is built from and nothing else validates. A supplier GSTIN that
   * does not checksum is not a filing problem, it is a credit that will never
   * match in GSTR-2B, and until the reconciliation screen said so the only
   * evidence of it was a row that kept coming back "missing in 2B".
   *
   * Abortable: the period picker drives it.
   */
  validateFiling: (period, invoiceType, { signal } = {}) =>
    request(`/filing/validate${query({ period, invoice_type: invoiceType })}`, { signal }),

  gstr1: (period, { signal } = {}) => request(`/filing/gstr1${query({ period })}`, { signal }),
  gstr3b: (period, { signal } = {}) => request(`/filing/gstr3b${query({ period })}`, { signal }),

  /** Recent periods, with each return's due date and whether it was filed. */
  filingStatus: ({ signal } = {}) => request("/filing/status", { signal }),

  /**
   * Record that a return was filed on the portal.
   *
   * Nothing in this product can observe a submission — the portal is where a
   * return is actually filed — so the deadline alerting has only this to go on.
   * A filing nobody records is a business that keeps being told it is late.
   *
   * Idempotent per period and return type: sending the same period again
   * corrects the ARN or the date rather than filing twice. Omitting the ARN
   * leaves a stored one alone, so it can be supplied later.
   */
  recordFiled: (returnType, payload) =>
    request(`/filing/${returnType}/filed`, { method: "POST", body: payload }),

  /**
   * Late fee (s.47) and interest (s.50) owed on a period's return.
   *
   * A running projection while the return is unfiled — it grows by the day —
   * and the amount actually run up once `recordFiled` has been called for it.
   * `params` may carry `is_nil` or `previous_year_turnover` to refine the
   * estimate; both are optional.
   *
   * Abortable, like every other read a picker drives. It was not, for as long
   * as nothing called it: two controls choose what this asks about, and the
   * answers do not come back in the order they were sent — so a stale reply
   * would land as the amount owed on a month the user has already left, which
   * is a number they might go and pay.
   */
  lateFee: (returnType, period, params = {}, { signal } = {}) =>
    request(`/filing/${returnType}/late-fee${query({ period, ...params })}`, { signal }),

  /**
   * The URL of an export.
   *
   * It said "used as an href, not fetched", and that stopped being true when
   * the export endpoints started needing the bearer token: `downloadExport`
   * below is now the only caller, and it fetches this. Kept separate from it
   * so the query-building lives in one place.
   */
  exportUrl: (returnType, extension, period) =>
    `${BASE}/filing/export/${returnType}.${extension}${query({ period })}`,

  /**
   * Fetch an export as a Blob.
   *
   * The export endpoints need the bearer token, which a plain `<a href>`
   * cannot carry — so the file is fetched with the header and handed to the
   * browser as an object URL rather than linked to directly.
   */
  downloadExport(returnType, extension, period) {
    return fetchFile(api.exportUrl(returnType, extension, period));
  },

  // ---- Paid reconciliation report ----
  //
  // Bought per run. `purchaseReport` answers `already_purchased` instead of an
  // order when this business has paid for the run before, and the report is
  // then downloaded again rather than charged for twice.
  purchaseReport: (runId) =>
    request("/reconciliation/report/purchase", { method: "POST", body: { run_id: runId } }),
  verifyReportPayment: (payload) =>
    request("/reconciliation/report/verify", { method: "POST", body: payload }),
  downloadReport: (runId) => fetchFile(`${BASE}/reconciliation/${runId}/report.pdf`),

  /** Everything held about the business on screen, as one JSON file. Owner only. */
  exportAccount: () => fetchFile(`${BASE}/businesses/mine/export`),

  // ---- Alerts ----
  //
  // The daily sweep in the backend raises these, the dashboard counts them, and
  // until now there was no client method for any of the three endpoints — so an
  // alert could be raised and counted but never read, and never closed.
  //
  // Never closed is the part that mattered. The sweep's central rule is that a
  // dismissal is respected and the alert is not raised again tomorrow, and that
  // rule could not fire, because no caller could produce a dismissal. A business
  // that filed on the portal without recording it here got the same "GSTR-3B is
  // overdue" every morning with nothing on any screen able to stop it.

  /** Alerts, open by default. `scope` is `open`, `closed` or `all`. */
  listAlerts: (params = {}, { signal } = {}) =>
    request(`/alerts${query(params)}`, { signal }),

  /** Seen, not handled — the alert stays open and stays in the badge. */
  markAlertRead: (id) => request(`/alerts/${id}/read`, { method: "POST" }),

  /** Close it: "I know". The sweep will not raise it again unless it worsens. */
  dismissAlert: (id) => request(`/alerts/${id}/dismiss`, { method: "POST" }),

  // ---- Suppliers ----
  listSuppliers: (params = {}, { signal } = {}) =>
    request(`/suppliers${query(params)}`, { signal }),
  getSupplier: (id, period) => request(`/suppliers/${id}${query({ period })}`),
  rescoreSuppliers: (period) =>
    request(`/suppliers/rescore${query({ period })}`, { method: "POST" }),

  // ---- Businesses (multi-GSTIN) ----
  //
  // A DoAide GST sign-up is one GSTIN, so a company with several registrations —
  // or an accountant with several clients — ends up with one login per
  // business. These are what let one of those logins reach the others: link
  // a second account by proving you also hold its password, then switch
  // which business a request acts for with `setActiveBusinessId`.

  /** The caller's own business, plus every business they have linked. */
  myBusinesses: ({ signal } = {}) => request("/businesses/mine", { signal }),

  /**
   * Links another account's business here, proven by that account's password.
   *
   * `carriesOtherCredentials` because the 401 this can answer is about the
   * email and password in the body, not about the caller's own session — see
   * `request`. Without it, a typo in the other registration's password ended
   * the session it was typed into.
   */
  linkBusiness: (email, password) =>
    request("/businesses/mine/link", {
      method: "POST",
      body: { email, password },
      carriesOtherCredentials: true,
    }),

  /** Revokes access gained through `linkBusiness`. Never removes your own tenant. */
  unlinkBusiness: (id) => request(`/businesses/mine/${id}`, { method: "DELETE" }),

  // ---- Subscriptions & Payments ----
  pricing: () => request("/subscriptions/pricing", { auth: false }),
  currentSubscription: () => request("/subscriptions/current"),
  createOrder: (tier, billing = "monthly") =>
    request("/subscriptions/create-order", { method: "POST", body: { tier, billing } }),
  verifyPayment: (payload) =>
    request("/subscriptions/verify-payment", { method: "POST", body: payload }),
  cancelSubscription: () =>
    request("/subscriptions/cancel", { method: "POST" }),
  usage: (period) =>
    request(`/subscriptions/usage${period ? `?period=${encodeURIComponent(period)}` : ""}`),

  // ---- Referrals (CA referral program) ----
  trackReferral: (referral_code) =>
    request("/referrals/track", { method: "POST", body: { referral_code }, auth: false }),
  referralLeaderboard: () =>
    request("/referrals/leaderboard", { auth: false }),
  myReferralCode: () => request("/referrals/my-code"),
  myReferralStats: () => request("/referrals/my-stats"),

  // ---- Background jobs (operational, not tenant data) ----
  /**
   * Worker reachability, broker queue depth, and scheduled-job heartbeats.
   *
   * Holds the server thread for up to a second waiting on a Celery broadcast
   * ping, which is why the status page runs it alongside `health` rather than
   * after it, and why it takes a signal — a user who navigates away should not
   * leave a request of that cost in flight.
   */
  jobHealth: ({ signal } = {}) => request("/health/jobs", { auth: false, signal }),
};

/** Build a `?a=1&b=2` suffix, dropping empty values. Returns "" when empty. */
function query(params = {}) {
  const search = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""),
  );
  const suffix = search.toString();
  return suffix ? `?${suffix}` : "";
}

/**
 * Fetch an authenticated download as `{blob, filename}`.
 *
 * A plain `<a href>` cannot carry the bearer token or the active business, so
 * files are fetched with both headers and handed to the browser as a Blob.
 */
async function fetchFile(url) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const activeBusinessId = getActiveBusinessId();
  if (activeBusinessId) headers["X-Business-Id"] = activeBusinessId;

  const res = await send(url, { headers });
  if (res.status === 401 && token) tokenRejected();
  if (!res.ok) {
    // Same two hazards as `request`: an HTML error page from the edge must
    // not surface as a JSON parse error, and `statusText` is empty over
    // HTTP/2 so it cannot be the fallback on its own.
    const { data, readable } = readBody(await res.text());
    throw refusal(
      readable ? errorMessage(data, statusMessage(res)) : statusMessage(res),
      res,
      readable ? data : null,
    );
  }
  return {
    blob: await res.blob(),
    filename: filenameFrom(res.headers.get("Content-Disposition")),
  };
}

/** Pull the filename out of a Content-Disposition header. */
export function filenameFrom(header, fallback = "doaide-gst-export") {
  const match = /filename="?([^"]+)"?/.exec(header ?? "");
  return match ? match[1] : fallback;
}
