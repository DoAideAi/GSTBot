// Does a business have to register for GST? Section 22 (turnover) and
// Section 24 (compulsory, whatever the turnover), with the notifications that
// carve exceptions out of each.
//
// The state lists are narrower than the folk version, which calls every
// north-eastern and hill state "special category" and halves its limits:
//
// - ₹10 lakh (instead of ₹20 lakh) applies only in Manipur, Mizoram, Nagaland
//   and Tripura. Explanation (iv) to s.22 has excluded J&K, Arunachal Pradesh,
//   Assam, Himachal Pradesh, Meghalaya, Sikkim and Uttarakhand since 1 Feb 2019.
// - ₹40 lakh for goods (Notification 10/2019-CT) is withheld in the ten states
//   that did not opt in, which fall back to their s.22 limit — a list that
//   includes Telangana and Puducherry and leaves out Assam, J&K and Himachal.

import { STATE_CODES } from "./stateCodes";

export const LAKH = 100000;

export const TEN_LAKH_STATES = ["Manipur", "Mizoram", "Nagaland", "Tripura"];

export const NO_40_LAKH_STATES = [
  "Arunachal Pradesh", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
  "Puducherry", "Sikkim", "Telangana", "Tripura", "Uttarakhand",
];

// Registrable places only: the retired codes and the two non-state codes are
// GSTIN prefixes, not somewhere a business is located.
export const STATES = STATE_CODES
  .filter((s) => /^(State|Union territory)$/.test(s.kind))
  .map((s) => s.name)
  .sort();

export const BUSINESS_TYPES = [
  { key: "goods", label: "Goods seller" },
  { key: "services", label: "Service provider" },
  { key: "both", label: "Goods and services" },
  { key: "casual", label: "Casual taxable person (trade fairs, exhibitions)" },
  { key: "nonresident", label: "Non-resident taxable person (no place of business in India)" },
  { key: "isd", label: "Input service distributor" },
];

const COMPULSORY = {
  casual: { section: "Section 24(ii)", text: "A casual taxable person must register before making any taxable supply, whatever the turnover, at least five days before starting business." },
  nonresident: { section: "Section 24(v)", text: "A non-resident taxable person must register before making any taxable supply, whatever the turnover." },
  isd: { section: "Section 24(viii)", text: "An input service distributor must take a separate registration to distribute credit, whatever the turnover." },
};

/** The s.22 limit for this business, with the provision it comes from. */
export function thresholdFor(type, state) {
  const base = TEN_LAKH_STATES.includes(state) ? 10 * LAKH : 20 * LAKH;
  if (type === "goods" && !NO_40_LAKH_STATES.includes(state)) {
    return { limit: 40 * LAKH, section: "Section 22(1) with Notification 10/2019-CT" };
  }
  return { limit: base, section: "Section 22(1)" };
}

/**
 * @returns null until a valid turnover and a state are given (or for the
 *   compulsory types, which need neither); otherwise
 *   { required, reasons: [{section, text}], threshold, notes: [string] }.
 */
export function checkRegistration({ type, turnover, state, interState = false, ecommerce = false }) {
  if (COMPULSORY[type]) {
    return { required: true, reasons: [COMPULSORY[type]], threshold: null, notes: [] };
  }
  if (!BUSINESS_TYPES.some((b) => b.key === type) || !state) return null;
  if (turnover === "" || turnover === null || turnover === undefined) return null;
  const amount = Number(turnover);
  if (!Number.isFinite(amount) || amount < 0) return null;

  const sellsGoods = type === "goods" || type === "both";
  const threshold = thresholdFor(type, state);
  const reasons = [];
  const notes = [];

  if (sellsGoods && interState) {
    reasons.push({
      section: ecommerce ? "Section 24(i) and 24(ix)" : "Section 24(i)",
      text: "Selling goods to buyers in another state requires registration from the first sale, whatever the turnover.",
    });
  }
  // s.22 says "exceeds", so turnover exactly at the limit does not trigger it.
  if (amount > threshold.limit) {
    reasons.push({
      section: threshold.section,
      text: `Aggregate turnover is above the ₹${threshold.limit / LAKH} lakh limit for ${state}. Register within 30 days of crossing it.`,
    });
  }

  if (reasons.length === 0) {
    if (!sellsGoods && interState) {
      notes.push("Inter-state services do not by themselves require registration below the limit (Notification 10/2017-Integrated Tax).");
    }
    if (ecommerce && sellsGoods) {
      notes.push("Selling goods within your own state through a marketplace is allowed without registration below the limit since 1 October 2023 (Notification 34/2023-CT). You need a PAN and an enrolment number from the GST portal.");
    } else if (ecommerce) {
      notes.push("Services sold through a marketplace do not require registration below the limit (Notification 65/2017-CT).");
    }
  }
  if (type === "goods" && threshold.limit === 40 * LAKH) {
    notes.push("The ₹40 lakh limit does not apply to ice cream, pan masala or tobacco; those suppliers use ₹20 lakh.");
  }

  return { required: reasons.length > 0, reasons, threshold, notes };
}
