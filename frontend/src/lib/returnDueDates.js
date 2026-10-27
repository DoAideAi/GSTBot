// GST return due dates by filer type and state, for /return-calendar.
//
// A port of backend/app/services/filing_dates.py `deadlines`, which drives the
// deadline alerts. The page needs the dates in its prerendered HTML, where no
// request runs, so it carries its own copy; returnDueDates.test.js reads the
// backend's CATEGORY_A_STATES and fails if the two lists drift.
//
// Dates are "YYYY-MM-DD" strings, not Date objects: a deadline is a day in
// India, and a Date built at local midnight shifts a day for anyone west of
// UTC. Notified extensions are not modelled — they are issued days before a
// deadline falls, and baking one in would make every later year wrong.

export const FILER_TYPES = [
  { key: "monthly", label: "Monthly filer" },
  { key: "quarterly", label: "Quarterly filer (QRMP, turnover up to ₹5 crore)" },
  { key: "composition", label: "Composition dealer" },
];

// QRMP GSTR-3B is staggered to spread portal load: these state codes file by
// the 22nd of the month after the quarter, the rest by the 24th
// (Notification 01/2021-CT, proviso to rule 61(5)).
export const CATEGORY_A_STATES = [
  "22", "23", "24", "25", "26", "27", "29", "30", "31", "32", "33", "34", "35", "36", "37",
];

const pad = (n) => String(n).padStart(2, "0");
const iso = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;

/** The month after `year`-`month`, as [year, month]. */
function following(year, month) {
  return month === 12 ? [year + 1, 1] : [year, month + 1];
}

function onFollowing(year, month, day) {
  const [y, m] = following(year, month);
  return iso(y, m, day);
}

/** The financial year a month falls in, as its starting calendar year. */
export function fyStart(year, month) {
  return month >= 4 ? year : year - 1;
}

const fyLabel = (start) => `FY ${start}-${pad((start + 1) % 100)}`;
const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const periodLabel = (y, m) => `${MONTH_NAMES[m - 1]} ${y}`;
const quarterLabel = (y, m) => {
  const start = fyStart(y, m);
  const q = { 6: 1, 9: 2, 12: 3, 3: 4 }[m];
  return `Q${q} ${fyLabel(start)} (${MONTH_NAMES[m - 3]}–${MONTH_NAMES[m - 1]})`;
};

/**
 * Deadlines arising from one tax period (`year`, `month` 1–12).
 * Without a state, a QRMP filer's GSTR-3B is listed for both categories:
 * picking one would be a confident wrong date for half the country.
 */
export function deadlinesForPeriod(year, month, filer, stateCode = "") {
  const fy = fyStart(year, month);
  const quarterEnd = month % 3 === 0;
  const found = [];

  if (filer === "composition") {
    if (quarterEnd) {
      found.push({ form: "CMP-08", covers: quarterLabel(year, month), due: onFollowing(year, month, 18), what: "Quarterly statement and tax payment" });
    }
    if (month === 3) {
      found.push({ form: "GSTR-4", covers: fyLabel(fy), due: iso(fy + 1, 4, 30), what: "Annual return for composition dealers" });
    }
    return found;
  }

  if (filer === "monthly") {
    found.push({ form: "GSTR-1", covers: periodLabel(year, month), due: onFollowing(year, month, 11), what: "Outward supplies (sales) statement" });
    found.push({ form: "GSTR-3B", covers: periodLabel(year, month), due: onFollowing(year, month, 20), what: "Summary return and tax payment" });
  } else if (quarterEnd) {
    found.push({ form: "GSTR-1", covers: quarterLabel(year, month), due: onFollowing(year, month, 13), what: "Quarterly outward supplies statement" });
    const categories = stateCode ? [CATEGORY_A_STATES.includes(stateCode)] : [true, false];
    for (const categoryA of categories) {
      found.push({
        form: stateCode ? "GSTR-3B" : `GSTR-3B (${categoryA ? "Category A" : "Category B"} states)`,
        covers: quarterLabel(year, month),
        due: onFollowing(year, month, categoryA ? 22 : 24),
        what: "Quarterly summary return and tax payment",
      });
    }
  } else {
    found.push({ form: "IFF", covers: periodLabel(year, month), due: onFollowing(year, month, 13), what: "B2B invoices for the month (optional)", optional: true });
    found.push({ form: "PMT-06", covers: periodLabel(year, month), due: onFollowing(year, month, 25), what: "Monthly tax payment challan" });
  }

  if (month === 3) {
    found.push({ form: "GSTR-9", covers: fyLabel(fy), due: iso(fy + 1, 12, 31), what: "Annual return (with GSTR-9C above ₹5 crore turnover)" });
  }
  return found;
}

/**
 * Every deadline whose due date lies in [from, to] (inclusive ISO dates).
 * GSTR-9 falls nine months after the March period it hangs off — the longest
 * lag of any return — so the scan starts ten months before `from`.
 */
export function deadlinesBetween(from, to, filer, stateCode = "") {
  let [y, m] = from.split("-").map(Number);
  m -= 10;
  while (m < 1) { m += 12; y -= 1; }
  const [endY, endM] = to.split("-").map(Number);
  const out = [];
  while (y < endY || (y === endY && m <= endM)) {
    for (const d of deadlinesForPeriod(y, m, filer, stateCode)) {
      if (d.due >= from && d.due <= to) out.push(d);
    }
    [y, m] = following(y, m);
  }
  return out.sort((a, b) => (a.due < b.due ? -1 : a.due > b.due ? 1 : 0));
}

/** Deadlines falling in calendar month `month` (1–12) of `year`. */
export function deadlinesInMonth(year, month, filer, stateCode = "") {
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return deadlinesBetween(iso(year, month, 1), iso(year, month, last), filer, stateCode);
}

/**
 * The next deadline(s) on or after `today` — all of them when several share
 * that date, so a monthly filer's two returns are not split arbitrarily.
 * Optional filings (IFF) do not count as the next deadline.
 */
export function nextDeadlines(today, filer, stateCode = "") {
  const [y, m] = today.split("-").map(Number);
  const horizon = new Date(Date.UTC(y, m + 12, 0)).toISOString().slice(0, 10);
  const upcoming = deadlinesBetween(today, horizon, filer, stateCode).filter((d) => !d.optional);
  if (upcoming.length === 0) return [];
  return upcoming.filter((d) => d.due === upcoming[0].due);
}

/** Whole days from `from` to `to`, both ISO dates. */
export function daysBetween(from, to) {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86400000);
}

/** Today's date in India, whatever the viewer's clock zone. */
export function todayInIndia(now = new Date()) {
  return new Date(now.getTime() + 330 * 60000).toISOString().slice(0, 10);
}
