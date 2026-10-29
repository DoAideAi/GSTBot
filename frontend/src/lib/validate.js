// Client-side validation.
//
// Every rule here exists on the server too, and the server stays the authority
// — these functions only move the "no" forward in time. A 15 MB scan that is
// going to be refused should be refused before it is read off disk and pushed
// over a phone connection, and a negative CGST should be caught while the
// cursor is still in the field rather than after a round trip.
//
// Two consequences of "the server is still the authority", both deliberate:
//
//   * Nothing here is a security control. The API re-checks all of it.
//   * When a rule is expensive to keep in sync, it is not duplicated at all.
//     The GSTIN checksum is the example: it lives on the server, and the
//     browser only checks the shape. See `gstinShapeError` below.

/**
 * Mirrors MAX_UPLOAD_MB, whose server default is 15.
 *
 * A deployment can raise its own limit, which would make this too strict. That
 * failure is the safe direction — the file is refused with a clear message
 * rather than accepted and then 413'd — and the callers still handle the
 * server's 413, so a raised limit degrades to "the old behaviour" rather than
 * to a broken upload.
 */
import { rupees } from "./format";
import { STATE_CODES } from "./stateCodes";

export const MAX_UPLOAD_MB = 15;

/** Kept in step with ALLOWED_EXTENSIONS in app/routers/invoices.py. */
export const INVOICE_EXTENSIONS = [
  ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic",
  ".txt", ".csv", ".xlsx", ".xlsm", ".xls",
];

/** Kept in step with ALLOWED_EXTENSIONS in app/routers/reconciliation.py. */
export const GSTR2B_EXTENSIONS = [".json", ".csv", ".txt"];

/** GST itself started on 1 July 2017; an invoice cannot predate it. */
const GST_EPOCH = "2017-07-01";

// Max lengths from InvoiceUpdate in app/schemas/invoice.py.
const MAX_INVOICE_NUMBER = 64;
// What Rule 46(b) of the CGST Rules actually allows in an invoice serial:
// letters, digits, hyphen and slash, up to sixteen characters. The column
// takes 64 and the API accepts them, which is why these are warnings rather
// than errors — but the portal refuses the whole return over one line, so a
// reviewer should hear about it while the paper is still in their hand rather
// than from a validation report a month later.
const RULE_46_CHAR = /[A-Za-z0-9/-]/;
const PORTAL_INVOICE_NUMBER = 16;
const MAX_COUNTERPARTY_NAME = 255;
const MAX_HSN = 8;

function extensionOf(name) {
  const dot = String(name ?? "").lastIndexOf(".");
  return dot === -1 ? "" : String(name).slice(dot).toLowerCase();
}

/** Human list: ".pdf, .jpg and .png" rather than a bare array. */
function readableList(items) {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/**
 * Why a file cannot be uploaded, or "" when it can.
 *
 * Returns a sentence rather than a code: every caller renders it directly, and
 * an error the user cannot act on is not worth showing. "That file is 41.2 MB"
 * tells them to re-export; "INVALID_SIZE" does not.
 */
export function fileError(file, { extensions, maxMb = MAX_UPLOAD_MB } = {}) {
  if (!file) return "No file selected.";

  const allowed = extensions ?? INVOICE_EXTENSIONS;
  const ext = extensionOf(file.name);
  if (!allowed.includes(ext)) {
    // The extension is named explicitly because the common case is a file the
    // user believes is fine — a .doc invoice, a .zip of scans.
    const got = ext || "no extension";
    return `${file.name} is ${got}, which cannot be read. Use ${readableList(allowed)}.`;
  }

  // Zero bytes reaches the parser as an empty document and comes back as "no
  // fields found", which reads like the extraction failed rather than like the
  // file is empty. Usually a half-finished download or a sync placeholder.
  if (file.size === 0) {
    return `${file.name} is empty (0 bytes). It may still be downloading.`;
  }

  const maxBytes = maxMb * 1024 * 1024;
  if (file.size > maxBytes) {
    const mb = (file.size / (1024 * 1024)).toFixed(1);
    return `${file.name} is ${mb} MB, over the ${maxMb} MB limit. Re-export it at a lower resolution or split it.`;
  }

  return "";
}

/** Partition a FileList into the ones worth sending and one error per reject. */
export function partitionFiles(files, options) {
  const accepted = [];
  const rejected = [];
  for (const file of Array.from(files ?? [])) {
    const error = fileError(file, options);
    if (error) rejected.push({ file, error });
    else accepted.push(file);
  }
  return { accepted, rejected };
}

const ASSIGNED_STATE_CODES = new Set(STATE_CODES.map((s) => s.code));

/**
 * Why a GSTIN is malformed, or "" when it is plausibly well-formed.
 *
 * No checksum. The check digit is base-36 weighted mod-36 arithmetic, and a
 * second implementation of it in another language is a standing invitation for
 * the two to disagree; the one that matters is the one the server enforces. So
 * this catches the errors that need no arithmetic (wrong length, a letter where
 * a digit belongs, an unassigned state code) and lets the server return the
 * definitive answer for anything shaped right.
 *
 * The state code is checked against lib/stateCodes, which stateCodes.test.js
 * pins to the server's list. Only 00 was refused, and the invoice generator —
 * which never asks the server — printed a GSTIN in "state 45" under a green
 * "✓ Valid format".
 *
 * `` is returned for an empty string: emptiness is the caller's business, and
 * on the invoice form clearing the field is a legitimate edit.
 */
export function gstinShapeError(value) {
  const cleaned = normalizeGstin(value);
  if (!cleaned) return "";

  if (cleaned.length !== 15) {
    return `A GSTIN is 15 characters; this one is ${cleaned.length}.`;
  }
  // 2 digits state, 5 letters + 4 digits + 1 letter PAN, 1 alphanumeric entity
  // code, "Z", 1 alphanumeric check digit.
  if (!/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$/.test(cleaned)) {
    return "That does not look like a GSTIN. The format is 27AAPFU0939F1ZV.";
  }
  const state = cleaned.slice(0, 2);
  // 00 is the usual result of a leading digit being eaten, so it gets a hint.
  if (state === "00") {
    return "A GSTIN starts with its state code, and 00 is not one. Check for a missing first digit.";
  }
  if (!ASSIGNED_STATE_CODES.has(state)) {
    return `A GSTIN starts with its state code, and ${state} is not one. Check the first two digits.`;
  }
  return "";
}

/** Strip the spaces and hyphens people paste in, and upper-case. */
export function normalizeGstin(value) {
  // The same rule as app/services/gstin.normalize, so a pasted GSTIN is one
  // GSTIN on both sides: full-width forms folded, then whitespace, every dash,
  // the minus sign and invisible format characters (a zero-width space, a
  // CSV's byte-order mark, a PDF's soft hyphen) removed. Only spaces and the
  // ASCII hyphen were, and the rest made a valid GSTIN "16 characters".
  return String(value ?? "")
    .normalize("NFKC")
    .replace(/[\s\p{Cf}\p{Pd}\u2212]/gu, "")
    .toUpperCase();
}

/**
 * Why an amount is unacceptable, or "".
 *
 * Mirrors `Decimal | None = Field(ge=0)`: blank is allowed (it clears the
 * field), negative is not. The paise check is ours — the column is
 * Numeric(14, 2), so a third decimal is silently rounded on the way in, and a
 * total the user did not type is worse than a rejected edit.
 */
export function amountError(value, label = "Amount") {
  const raw = String(value ?? "").trim();
  if (raw === "") return "";

  if (!/^-?\d*\.?\d*$/.test(raw) || raw === "." || raw === "-") {
    return `${label} must be a number.`;
  }
  const num = Number(raw);
  if (!Number.isFinite(num)) return `${label} must be a number.`;
  if (num < 0) return `${label} cannot be negative.`;

  const decimals = raw.split(".")[1];
  if (decimals && decimals.length > 2) {
    return `${label} cannot be finer than paise (two decimal places).`;
  }
  // Numeric(14, 2) — twelve digits before the point. A number this large is a
  // mistyped amount, not a real invoice.
  if (num >= 1e12) return `${label} is too large; it looks like a mistyped amount. Check the digits.`;
  return "";
}

/**
 * Why an invoice date is unacceptable, or "".
 *
 * Future dates are refused rather than warned about: an invoice dated next
 * month lands in a period that cannot be filed yet, and the reconciliation
 * then reports it as missing from the 2B every month until someone notices.
 */
export function invoiceDateError(value, { today = new Date() } = {}) {
  const raw = String(value ?? "").trim();
  if (raw === "") return "";

  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return "Use the date picker, or type YYYY-MM-DD.";

  // Compared as strings against ISO dates. Parsing to Date would drag the
  // browser's timezone in, which near midnight can shift the day and refuse a
  // date typed today as being in the future.
  const [y, m, d] = raw.split("-").map(Number);
  const probe = new Date(Date.UTC(y, m - 1, d));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== m - 1 || probe.getUTCDate() !== d) {
    return "That date does not exist.";
  }

  const todayIso = new Date(
    Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()),
  )
    .toISOString()
    .slice(0, 10);

  if (raw > todayIso) return "An invoice cannot be dated in the future.";
  if (raw < GST_EPOCH) return "GST started on 1 July 2017; that date is before it.";
  return "";
}

/** Why an HSN/SAC code is unacceptable, or "". */
export function hsnError(value) {
  const raw = String(value ?? "").trim();
  if (raw === "") return "";
  if (!/^\d+$/.test(raw)) return "HSN/SAC codes are digits only.";
  // 4, 6 and 8 are the real lengths; 2 is allowed as a chapter heading, which
  // the portal accepts on small-turnover returns.
  if (raw.length > MAX_HSN) return `HSN/SAC codes are at most ${MAX_HSN} digits.`;
  if (raw.length < 2) return "An HSN/SAC code is at least 2 digits.";
  return "";
}

/**
 * Why a place of supply is unacceptable, or "".
 *
 * Checked against the same list as `gstinShapeError`, lib/stateCodes, which a
 * test pins to the server's `STATE_CODES` so the two cannot drift apart when the
 * Council reorganises a state or union territory. A single digit is padded
 * rather than refused — `7` for Delhi is what a person types and `07` is what
 * the portal wants, which is exactly what the server's own validator does with
 * it.
 */
export function placeOfSupplyError(value) {
  const raw = normalizePlaceOfSupply(value);
  if (raw === "") return "";
  if (!/^\d{2}$/.test(raw)) {
    return "A place of supply is the two-digit state code, e.g. 27 for Maharashtra.";
  }
  if (!ASSIGNED_STATE_CODES.has(raw)) return `${raw} is not a state code.`;
  return "";
}

/** A place of supply as the server wants it: two digits, zero-padded. */
export function normalizePlaceOfSupply(value) {
  const raw = String(value ?? "").trim();
  return /^\d$/.test(raw) ? `0${raw}` : raw;
}

/**
 * The rates GST actually levies.
 *
 * Mirrors VALID_TAX_RATES in app/services/invoice_parser.py. Unlike the state
 * codes this is worth carrying, because it is only ever used to *warn*: the API
 * accepts any rate from 0 to 100, and it is `/filing/validate` that calls a
 * non-slab rate an error. Being a slab out of date here therefore costs a
 * missing hint, never a refused edit.
 */
// GST 2.0's 40% slab (from 22 September 2025) was missing here, so a 40%
// invoice was flagged "not a GST rate" — a nudge to change a right rate to a
// wrong one. 12 and 28 stay: invoices dated before the reform still carry
// them. validate.test.js now fails if this list and the backend's drift.
export const GST_RATES = [0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28, 40];

/** Why a tax rate is unacceptable, or "". Mirrors `Field(ge=0, le=100)`. */
export function taxRateError(value) {
  const raw = String(value ?? "").trim();
  if (raw === "") return "";
  // The minus is admitted by the shape check so that the next line can say
  // "cannot be negative" rather than "must be a number", which is the same
  // trade `amountError` makes: the reason a field is refused is the whole
  // value of refusing it.
  if (!/^-?\d*\.?\d*$/.test(raw) || raw === "." || raw === "-") {
    return "Tax rate must be a number.";
  }
  const num = Number(raw);
  if (!Number.isFinite(num)) return "Tax rate must be a number.";
  if (num < 0) return "Tax rate cannot be negative.";
  if (num > 100) return "Tax rate is a percentage, so it cannot be over 100.";
  return "";
}

/**
 * Why a payment date is unacceptable, or "".
 *
 * Blank is legitimate and load-bearing: clearing it means "not paid after all",
 * which is what puts an invoice back on Rule 37's 180-day clock.
 *
 * Both refusals mirror the server, and both are about that clock rather than
 * tidiness. A payment date in the future takes an invoice off the reversal list
 * it belongs on, and one before the invoice was issued is a mistyped year doing
 * the same thing — an under-reported reversal in GSTR-3B is over-claimed
 * credit, with interest running on it.
 */
export function paidAtError(value, { invoiceDate, today = new Date() } = {}) {
  const raw = String(value ?? "").trim();
  if (raw === "") return "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(raw)) return "Use the date picker, or type YYYY-MM-DD.";

  const [y, m, d] = raw.split("-").map(Number);
  const probe = new Date(Date.UTC(y, m - 1, d));
  if (probe.getUTCFullYear() !== y || probe.getUTCMonth() !== m - 1 || probe.getUTCDate() !== d) {
    return "That date does not exist.";
  }

  const todayIso = new Date(
    Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()),
  )
    .toISOString()
    .slice(0, 10);
  if (raw > todayIso) return "A payment cannot be dated in the future.";

  const issued = String(invoiceDate ?? "").trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(issued) && raw < issued) {
    return `The invoice is dated ${issued}; it cannot have been paid before it was issued.`;
  }
  return "";
}

/**
 * Why an ARN is unacceptable, or "".
 *
 * Mirrors ARN_PATTERN in app/services/filing.py, including its deliberate
 * looseness. The portal issues a 15-character reference, but the two ways to be
 * wrong here are not symmetric: too strict locks a business out of recording a
 * filing that genuinely happened, and the deadline alert for that period then
 * never clears — so the product goes on nagging them about a return they have
 * already filed. Only something plainly not an ARN is refused.
 *
 * The empty string is acceptable: the acknowledgement is often not to hand at
 * the moment someone marks a return done, and it can be supplied later.
 */
export function arnError(value) {
  const raw = String(value ?? "").replace(/\s+/g, "").toUpperCase();
  if (raw === "") return "";
  if (!/^[0-9A-Z]+$/.test(raw)) return "An ARN is letters and digits only.";
  if (raw.length < 10 || raw.length > 32) {
    return "That does not look like an ARN. The portal's acknowledgement shows a 15-character reference.";
  }
  return "";
}

/** An ARN as the server wants it: no spaces, upper case. "" when blank. */
export function normalizeArn(value) {
  return String(value ?? "").replace(/\s+/g, "").toUpperCase();
}

function lengthError(value, max, label) {
  const raw = String(value ?? "");
  if (raw.length > max) return `${label} is limited to ${max} characters.`;
  return "";
}

/**
 * Validate the whole invoice edit form.
 *
 * Returns `{ errors, warnings }`. Errors are keyed by field and block the save.
 * Warnings are cross-field observations that do *not* block it — the server
 * would accept the values, and there are real invoices that trip every one of
 * these heuristics. Refusing to save because a total looks off would leave the
 * user with no way to record what the paper actually says.
 */
export function invoiceDraftErrors(draft, options = {}) {
  const errors = {};
  const set = (field, message) => {
    if (message && !errors[field]) errors[field] = message;
  };

  set("counterparty_gstin", gstinShapeError(draft.counterparty_gstin));
  set(
    "counterparty_name",
    lengthError(draft.counterparty_name, MAX_COUNTERPARTY_NAME, "Counterparty name"),
  );
  set("invoice_number", lengthError(draft.invoice_number, MAX_INVOICE_NUMBER, "Invoice number"));
  set("invoice_date", invoiceDateError(draft.invoice_date, options));
  set("hsn_code", hsnError(draft.hsn_code));
  set("place_of_supply", placeOfSupplyError(draft.place_of_supply));
  set("tax_rate", taxRateError(draft.tax_rate));
  // Checked against the invoice date as this form will leave it, not as the
  // row holds it now: correcting a misread year is the commonest reason anyone
  // touches that field, and the server compares the pair the PATCH lands.
  set(
    "paid_at",
    paidAtError(draft.paid_at, { ...options, invoiceDate: draft.invoice_date }),
  );

  for (const [field, label] of [
    ["taxable_value", "Taxable value"],
    ["cgst", "CGST"],
    ["sgst", "SGST"],
    ["igst", "IGST"],
    ["cess", "Cess"],
    ["total_value", "Total value"],
  ]) {
    set(field, amountError(draft[field], label));
  }

  return { errors, warnings: invoiceDraftWarnings(draft, errors, options) };
}

/**
 * Cross-field observations that are suspicious but legal.
 *
 * Skipped for any field that already has a hard error, so a half-typed amount
 * does not also produce "the total does not add up".
 */
function invoiceDraftWarnings(draft, errors, options = {}) {
  const warnings = [];

  // The identity first, because it is the one field on this form that can
  // make the portal reject a return that is otherwise perfect.
  const number = String(draft.invoice_number ?? "").trim();
  if (number.length > PORTAL_INVOICE_NUMBER) {
    warnings.push(
      `The portal allows ${PORTAL_INVOICE_NUMBER} characters in an invoice number; this is ${number.length}.`,
    );
  }
  // Sales only. On a purchase this serial is the supplier's, copied off their
  // document — it is what GSTR-2B carries too, so it reconciles exactly as
  // well as a compliant one, and it is not a number the buyer has any
  // authority to change. Matches `validate_invoice` in app/services/filing.py,
  // which raises the error on the same side.
  if (options.invoiceType === "sales" && number) {
    const offending = [...new Set([...number].filter((c) => !RULE_46_CHAR.test(c)))];
    if (offending.length > 0) {
      warnings.push(
        `Invoice numbers may contain letters, digits, '-' and '/' only (Rule 46(b)). ` +
          `This one has ${offending.map((c) => `'${c}'`).join(", ")}.`,
      );
    }
  }

  const num = (field) => {
    if (errors[field]) return null;
    const raw = String(draft[field] ?? "").trim();
    if (raw === "") return null;
    const value = Number(raw);
    // The `: null` never fires: every field this is called for is run through
    // `amountError` above, which rejects anything non-finite — so a raw that
    // would land here has already put a message in `errors` and returned at
    // the first line. Kept so the arithmetic below cannot inherit an Infinity
    // if that pairing is ever broken; a warning computed on one reads as a
    // confident claim about the invoice rather than as a bug.
    return Number.isFinite(value) ? value : null;
  };

  const taxable = num("taxable_value");
  const cgst = num("cgst");
  const sgst = num("sgst");
  const igst = num("igst");
  const cess = num("cess");
  const total = num("total_value");

  // IGST is interstate, CGST+SGST is intrastate. One supply is one or the
  // other, so both being non-zero usually means a misread column — but a
  // credit note adjusting a supply booked the other way can look like this.
  if (igst && (cgst || sgst)) {
    warnings.push(
      "This has both IGST and CGST/SGST. A supply is either interstate or intrastate, not both.",
    );
  }

  // The two halves of an intrastate supply are equal by construction.
  if (cgst != null && sgst != null && cgst !== sgst) {
    warnings.push("CGST and SGST are normally equal. Check both were read correctly.");
  }

  // Rounding on the invoice is real and legal, so this needs a tolerance
  // rather than an equality. A rupee covers the usual line-level rounding.
  //
  // Skipped outright when any contributing field is in error. Treating an
  // unparseable CGST as zero would compute a total that disagrees with the
  // one on screen and report *that* as the problem, on top of the real
  // message — pointing the user at the wrong field.
  const contributors = ["taxable_value", "cgst", "sgst", "igst", "cess", "total_value"];
  const anyContributorInvalid = contributors.some((field) => errors[field]);

  if (taxable != null && total != null && !anyContributorInvalid) {
    const computed = taxable + (cgst ?? 0) + (sgst ?? 0) + (igst ?? 0) + (cess ?? 0);
    if (Math.abs(computed - total) > 1) {
      warnings.push(
        `Taxable plus tax comes to ${rupees(computed)}, but the total says ${rupees(total)}.`,
      );
    }
  }

  // A rate outside the slabs saves — the API takes anything from 0 to 100 —
  // and `/filing/validate` then calls it an error the portal will reject. Said
  // here it is a hint while the paper is still in the reviewer's hand; left to
  // the filing screen it is a line in a report a month later.
  const rate = num("tax_rate");
  if (rate != null && !GST_RATES.includes(rate)) {
    warnings.push(
      `${rate}% is not a GST rate. The slabs are ${GST_RATES.join(", ")} — the portal rejects anything else.`,
    );
  }

  return warnings;
}

/**
 * The loosest shape that is still an address: something, an @, a dotted host.
 *
 * Deliberately a subset of what the server enforces — it validates with
 * pydantic's `EmailStr`, which is stricter — so this can only ever refuse
 * addresses the server would refuse too. Anything cleverer is how a legitimate
 * address gets rejected by a regex, and the server remains the authority.
 */
const EMAIL_SHAPE = /^\S+@\S+\.\S+$/;

/**
 * Why a registration form cannot be submitted, or "" — keyed by field.
 *
 * The password rule matches the server's minimum.
 *
 * Email is checked here rather than left to the input's own `type="email"`,
 * because the form sets `noValidate` — which turns that check off along with
 * the required-field bubbles it was disabled for. The sign-in path noticed and
 * checks the field itself; this one did not, so registering with the email box
 * empty was a round trip that came back as a generic 400 with nothing pointing
 * at the field that caused it. On the one form a new user has to get through,
 * that is the difference between a corrected typo and an abandoned signup.
 */
export function registrationErrors(form) {
  const errors = {};
  const cleaned = normalizeGstin(form.gstin);
  if (cleaned) {
    const gstin = gstinShapeError(cleaned);
    if (gstin) errors.gstin = gstin;
  }

  const email = String(form.email ?? "").trim();
  if (!email) errors.email = "Enter your email.";
  else if (!EMAIL_SHAPE.test(email)) errors.email = "That does not look like an email address.";

  if (form.gstin && form.gstin.trim() && !String(form.legal_name ?? "").trim()) {
    errors.legal_name = "Legal name is required when registering with a GSTIN.";
  }
  if (String(form.password ?? "").length < 8) {
    errors.password = "Use at least 8 characters.";
  }
  return errors;
}
