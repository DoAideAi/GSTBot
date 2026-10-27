// E-way bill rules (Rule 138, CGST Rules), shared by /eway-bill and
// /eway-bill-generator so the two pages cannot disagree about a consignment.

// Rule 138(1) applies to a consignment value *exceeding* ₹50,000, so exactly
// ₹50,000 needs no bill. The value is taxable value plus tax, without exempt
// goods — the same figure the generator totals.
export const THRESHOLD = 50000;

export function ewayBillRequired(consignmentValue) {
  return consignmentValue > THRESHOLD;
}

// Rule 138(10), as amended from 1 January 2021: 200 km a day for normal cargo
// (it was 100 before), and 20 km a day for over-dimensional cargo, which the
// amendment left alone. "Or part thereof" — 201 km is two days.
export const KM_PER_DAY = { normal: 200, odc: 20 };

export function validityDays(distanceKm, overDimensional = false) {
  if (!(distanceKm > 0)) return null;
  return Math.ceil(distanceKm / (overDimensional ? KM_PER_DAY.odc : KM_PER_DAY.normal));
}

/**
 * The last calendar day the bill is valid, as an ISO date. The explanation to
 * Rule 138(10) ends each day at midnight of the day after generation, so a
 * one-day bill made at 10am on the 5th runs to the end of the 6th, not 10am
 * on the 6th. Plain date arithmetic in UTC keeps the viewer's zone out of it.
 */
export function validUntil(generatedOn, days) {
  if (!generatedOn || !days) return null;
  const [y, m, d] = generatedOn.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

// Ordinary registrations (MH12AB1234, DL1CAA1234) and the Bharat series
// (22BH1234AB). Advisory only: temporary and defence numbers exist too, and
// the portal is the authority, so a mismatch warns rather than blocks.
export function looksLikeVehicleNumber(value) {
  const v = value.replace(/[\s-]/g, "").toUpperCase();
  return /^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{4}$/.test(v) || /^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$/.test(v);
}
