// Display formatting. Everything money-shaped arrives from the API as a
// string so that no rupee value passes through a JavaScript float on its way
// to the screen.

/** Format a rupee amount in the Indian grouping (₹1,23,456.00). */
export function rupees(value, { decimals = 2 } = {}) {
  const number = Number(value ?? 0);
  if (!Number.isFinite(number)) return "₹0.00";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(number);
}

/** Compact rupees for tiles: ₹1.2L, ₹3.4Cr. */
export function rupeesShort(value) {
  const number = Number(value ?? 0);
  if (!Number.isFinite(number)) return "₹0";
  const abs = Math.abs(number);
  // Lakh and crore rather than K/M: this is what an Indian business reads.
  if (abs >= 1e7) return `₹${(number / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `₹${(number / 1e5).toFixed(2)}L`;
  if (abs >= 1e3) return `₹${(number / 1e3).toFixed(1)}K`;
  return `₹${number.toFixed(0)}`;
}

/** "2026-04" -> "April 2026". */
export function periodLabel(period) {
  if (!period || !/^\d{4}-\d{2}$/.test(period)) return period ?? "";
  const [year, month] = period.split("-");
  const date = new Date(Number(year), Number(month) - 1, 1);
  return date.toLocaleDateString("en-IN", { month: "long", year: "numeric" });
}

// `new Date("2026-04-15")` is defined to parse as UTC midnight, so every
// browser west of Greenwich renders the day before. A GST date is a calendar
// date, not an instant, so parse the date-only form into local components and
// leave full timestamps to the engine.
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

function toLocalDate(value) {
  if (value instanceof Date) return value;
  const match = DATE_ONLY.exec(String(value));
  if (match) {
    return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  }
  return new Date(value);
}

/** "2026-04-15" -> "15 Apr 2026". */
export function dateLabel(value) {
  if (!value) return "—";
  const date = toLocalDate(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/** The current filing period as YYYY-MM. */
export function currentPeriod(now = new Date()) {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

/** The previous filing period as YYYY-MM. */
export function previousPeriod(now = new Date()) {
  const date = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

/** Days until a due date; negative once it has passed. */
export function daysUntil(dueDate, now = new Date()) {
  if (!dueDate) return null;
  const due = toLocalDate(dueDate);
  if (Number.isNaN(due.getTime())) return null;
  const midnight = (d) => Date.UTC(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.round((midnight(due) - midnight(now)) / 86400000);
}

const STATUS_LABELS = {
  uploaded: "Uploaded",
  processing: "Processing",
  parsed: "Parsed",
  failed: "Failed",
  matched: "Matched",
  mismatched: "Mismatched",
  missing_in_2b: "Missing in 2B",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] ?? status ?? "";
}

/** Semantic tone for a status chip: good / warn / bad / neutral. */
export function statusTone(status) {
  if (status === "matched" || status === "parsed") return "good";
  if (status === "mismatched" || status === "missing_in_2b") return "warn";
  if (status === "failed") return "bad";
  return "neutral";
}

/** Escape HTML then apply minimal markdown (bold, italic, code, newline). */
export function formatMarkdown(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br />");
}
