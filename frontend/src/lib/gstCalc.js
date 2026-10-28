const GST_SLABS = [0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 18, 40];

export { GST_SLABS };

/**
 * A rupee amount as whole paise, rounded half-up the way the decimal it was
 * typed as reads — not the way its nearest binary double does. `1.005 * 100`
 * is 100.49999…, so `Math.round` took ₹1.005 down to ₹1.00 where the backend's
 * Decimal (and the portal) take it up to ₹1.01. Shifting the decimal point in
 * the string form keeps the digits the user typed.
 */
function toPaise(amount) {
  const text = String(amount);
  const shifted = text.includes("e") ? amount * 100 : Number(`${text}e2`);
  return Math.round(shifted);
}

const rupees = (paise) => paise / 100;

function split(taxablePaise, headPaise, rate, interstate) {
  const cgst = interstate ? 0 : headPaise;
  const igst = interstate ? headPaise : 0;
  return {
    taxable: rupees(taxablePaise),
    cgst: rupees(cgst),
    sgst: rupees(cgst),
    igst: rupees(igst),
    cess: 0,
    total: rupees(taxablePaise + 2 * cgst + igst),
    rate,
    interstate,
  };
}

/**
 * Tax added on top of a taxable value, by the rules the backend's
 * `gst_calculator.on_taxable` follows.
 *
 * CGST and SGST are each computed at half the rate and rounded on their own,
 * never by halving a rounded total: that left an odd paisa on one head
 * (₹0.09 of tax split ₹0.05 / ₹0.04), and the portal refuses a CGST that
 * differs from its SGST.
 */
export function calculate(amount, rate, { interstate = false } = {}) {
  if (!Number.isFinite(amount) || amount < 0) return null;
  if (!Number.isFinite(rate) || rate < 0 || rate > 100) return null;

  const taxable = toPaise(amount);
  const basisPoints = Math.round(rate * 100);
  // Integer paise × integer basis points: the only rounding is the one below.
  const head = interstate
    ? Math.round((taxable * basisPoints) / 10000)
    : Math.round((taxable * basisPoints) / 20000);
  return split(taxable, head, rate, interstate);
}

/**
 * Tax backed out of a price that already includes it, as
 * `gst_calculator.from_inclusive` does: the heads first, and the taxable value
 * is whatever is left, so taxable + tax is always the amount typed. Rounding
 * the taxable value first and taxing it again landed a paisa either side of it.
 */
export function reverseCalculate(totalWithTax, rate, { interstate = false } = {}) {
  if (!Number.isFinite(totalWithTax) || totalWithTax < 0) return null;
  if (!Number.isFinite(rate) || rate < 0 || rate > 100) return null;

  const gross = toPaise(totalWithTax);
  const basisPoints = Math.round(rate * 100);
  if (interstate) {
    const igst = Math.round((gross * basisPoints) / (10000 + basisPoints));
    return split(gross - igst, igst, rate, true);
  }
  const head = Math.round((gross * basisPoints) / (2 * (10000 + basisPoints)));
  return split(gross - 2 * head, head, rate, false);
}

export function formatINR(value) {
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function calcUrl(amount, rate, interstate) {
  const params = new URLSearchParams();
  if (amount) params.set("amount", String(amount));
  if (rate !== undefined) params.set("rate", String(rate));
  if (interstate) params.set("type", "igst");
  const suffix = params.toString();
  return `/calculator${suffix ? `?${suffix}` : ""}`;
}

export function parseCalcParams(search) {
  const params = new URLSearchParams(search);
  const amount = parseFloat(params.get("amount") || "");
  const rate = parseFloat(params.get("rate") || "");
  const interstate = params.get("type") === "igst";
  return {
    amount: Number.isFinite(amount) && amount >= 0 ? amount : null,
    rate: Number.isFinite(rate) && rate >= 0 && rate <= 100 ? rate : null,
    interstate,
  };
}
