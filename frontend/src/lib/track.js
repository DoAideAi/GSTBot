// Product analytics (Umami), and the one place that decides what may reach it.
//
// Umami is a third-party store, so an event carries what the product needs to
// learn — which tools are used, how far a funnel gets — and never what a
// business typed into one. The advisor already sent a question's length rather
// than its words; the calculators sent the taxable value, the ITC page the GST
// and net credit, the scheme comparison the turnover, and the HSN search
// whatever was typed into the box (a GSTIN, an email). Enforced here rather
// than at each call site, so a new event cannot forget it.

// Keys whose numbers are a business's own figures. Sent as a band — enough to
// see whether the calculator is used for a chai stall or a distributor — and
// never as the figure.
const MONEY_KEY = /amount|turnover|value|total|gst|itc|tax|income|revenue|price/i;

// Identifiers that are personal or identify a business outright.
const GSTIN = /\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b/i;
const PAN = /\b[A-Z]{5}\d{4}[A-Z]\b/i;
const EMAIL = /[^\s@]+@[^\s@]+\.[^\s@]+/;
const PHONE = /(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b/;

const MAX_TEXT = 40;

/** A rupee figure as a band in lakh and crore, the way it would be said. */
export function amountBand(value) {
  const n = Math.abs(Number(value));
  if (!Number.isFinite(n)) return "unknown";
  if (n < 10_000) return "<10K";
  if (n < 1_00_000) return "10K-1L";
  if (n < 10_00_000) return "1L-10L";
  if (n < 1_00_00_000) return "10L-1Cr";
  return "1Cr+";
}

function cleanValue(key, value) {
  if (typeof value === "number" && MONEY_KEY.test(key) && key !== "rate") {
    return amountBand(value);
  }
  if (typeof value === "string") {
    if (GSTIN.test(value) || PAN.test(value) || EMAIL.test(value) || PHONE.test(value)) {
      return "[redacted]";
    }
    return value.slice(0, MAX_TEXT);
  }
  return value;
}

/** *data* as it may leave the browser: banded money, no identifiers. */
export function analyticsSafe(data) {
  if (!data || typeof data !== "object") return data;
  return Object.fromEntries(
    Object.entries(data).map(([key, value]) => [key, cleanValue(key, value)]),
  );
}

export function track(event, data) {
  if (typeof window !== "undefined" && typeof window.umami !== "undefined") {
    window.umami.track(event, analyticsSafe(data));
  }
}
