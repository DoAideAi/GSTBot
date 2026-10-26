// Rule 42, CGST Rules: how much of the input tax credit on inputs and input
// services shared between taxable and exempt (or non-business) use has to be
// reversed. The letters follow the rule so a reader can check each line
// against the text:
//
//   T  total ITC for the period      T1 exclusively non-business
//   T2 exclusively exempt supplies   T3 blocked under section 17(5)
//   C1 = T − (T1 + T2 + T3)          credited to the electronic credit ledger
//   T4 exclusively taxable supplies (zero-rated included)
//   C2 = C1 − T4                     common credit
//   D1 = (E ÷ F) × C2                attributable to exempt supplies
//   D2 = 5% × C2                     attributable to non-business use, only
//                                    when common inputs are also used that way
//   C3 = C2 − (D1 + D2)              common credit that stays
//
// Capital goods are Rule 43, a different formula over a 60-month life, and are
// deliberately not handled here.

export const NON_BUSINESS_SHARE = 5;

const round2 = (n) => Math.round(n * 100) / 100;

function amount(v) {
  if (v === "" || v === undefined || v === null) return 0;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/**
 * Returns `{ error }` for input the rule cannot be applied to, else the
 * full working. `error` is a code, not prose, so the page owns the wording.
 */
export function computeRule42({
  total,
  nonBusiness = 0,
  exemptOnly = 0,
  blocked = 0,
  taxableOnly = 0,
  exemptTurnover = 0,
  totalTurnover,
  commonUsedForNonBusiness = false,
}) {
  const T = amount(total);
  const T1 = amount(nonBusiness);
  const T2 = amount(exemptOnly);
  const T3 = amount(blocked);
  const T4 = amount(taxableOnly);
  const E = amount(exemptTurnover);
  const F = amount(totalTurnover);
  if ([T, T1, T2, T3, T4, E, F].some((v) => v === null)) return { error: "negative" };
  if (T1 + T2 + T3 + T4 > T) return { error: "parts-exceed-total" };
  // The rule takes E/F from the last period that had turnover when this one
  // had none; the page cannot know that period, so it asks for it instead.
  if (F === 0) return { error: "no-turnover" };
  if (E > F) return { error: "exempt-exceeds-total" };

  const C1 = round2(T - (T1 + T2 + T3));
  const C2 = round2(C1 - T4);
  const exemptRatio = E / F;
  const D1 = round2(exemptRatio * C2);
  const D2 = commonUsedForNonBusiness ? round2((C2 * NON_BUSINESS_SHARE) / 100) : 0;
  const C3 = round2(C2 - D1 - D2);

  return {
    C1,
    C2,
    D1,
    D2,
    C3,
    exemptRatio,
    reversal: round2(D1 + D2),
    // What the period's return finally keeps: exclusively-taxable credit plus
    // what is left of the common pool.
    eligible: round2(T4 + C3),
    notCredited: round2(T1 + T2 + T3),
  };
}
