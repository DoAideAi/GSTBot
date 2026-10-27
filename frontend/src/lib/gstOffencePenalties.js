// Penalties for GST offences under Sections 122, 123 and 125 of the CGST Act.
//
// Every figure in those sections is levied *per Act*: the SGST/UTGST Act
// carries an identical section, so an intra-state case pays it twice — once
// on the CGST half of the tax and once on the SGST half. The ₹10,000 floor in
// s.122(1) is therefore ₹20,000 combined, and s.125's ₹25,000 ceiling is
// ₹50,000. Inter-state cases fall under the IGST Act, which takes the CGST
// penalty provisions over through its s.20, so they pay each figure once.
// Quoting the CGST figure alone, as most calculators do, halves the floor.

export const MIN_PENALTY_122 = 10000;
export const MAX_PENALTY_125 = 25000;
export const PER_DAY_123 = 100;
export const MAX_PENALTY_123 = 5000;

// `input` is what the amount field asks for; `rule` is how it becomes a penalty.
export const VIOLATIONS = [
  {
    key: "evasion",
    label: "Tax evasion or short payment of tax",
    section: "Section 122(1)",
    input: "tax",
    rule: "greaterOf",
    what: "Tax evaded, short-paid, or input tax credit wrongly availed or passed on.",
  },
  {
    key: "fake_invoice",
    label: "Fake invoice — issued without any supply",
    section: "Section 122(1)(ii)",
    input: "tax",
    rule: "greaterOf",
    what: "Invoice or bill issued without supplying goods or services, letting the buyer claim credit.",
  },
  {
    key: "no_invoice",
    label: "Supply without an invoice, or a false invoice",
    section: "Section 122(1)(i)",
    input: "tax",
    rule: "greaterOf",
    what: "Goods or services supplied with no invoice, or with one that misstates the supply.",
  },
  {
    key: "not_registered",
    label: "Not registering despite being liable",
    section: "Section 122(1)(xi)",
    input: "tax",
    rule: "greaterOf",
    what: "Trading above the registration threshold, or in a compulsory category, without a GSTIN.",
  },
  {
    key: "refund",
    label: "Refund obtained fraudulently",
    section: "Section 122(1)(viii)",
    input: "refund",
    rule: "greaterOf",
    what: "A refund of tax obtained by fraud or misstatement.",
  },
  {
    key: "invoice_error",
    label: "Wrong invoice details (no tax lost)",
    section: "Section 125",
    input: null,
    rule: "general",
    what: "Missing or wrong particulars on an invoice — HSN, address, signature — with the tax itself correct.",
  },
  {
    key: "info_return",
    label: "Information return not furnished",
    section: "Section 123",
    input: "days",
    rule: "perDay",
    what: "A person required to furnish an information return under Section 150 who misses the deadline.",
  },
  {
    key: "not_filed",
    label: "GST return not filed",
    section: "Section 47",
    input: null,
    rule: "lateFee",
    what: "A GSTR-1, GSTR-3B, GSTR-4 or GSTR-9 filed late or not at all.",
  },
  {
    key: "general",
    label: "Any other contravention (no specific penalty)",
    section: "Section 125",
    input: null,
    rule: "general",
    what: "Any breach of the Act or rules for which no penalty is separately provided.",
  },
];

const round2 = (n) => Math.round(n * 100) / 100;

/**
 * Penalty for one violation.
 *
 * `amount` is the tax (CGST+SGST combined, or IGST) or refund involved, or the
 * days of delay for s.123 — whichever the violation's `input` asks for.
 * Returns null when that input is missing or invalid. `upTo` marks a ceiling
 * the officer may levy anything below, rather than a fixed amount.
 */
export function computeOffencePenalty({ violation, amount, interState = false }) {
  const v = VIOLATIONS.find((x) => x.key === violation);
  if (!v) return null;
  if (v.rule === "lateFee") return { violation: v, lateFee: true };

  let n = 0;
  if (v.input) {
    if (amount === "" || amount === null || amount === undefined) return null;
    n = Number(amount);
    if (!Number.isFinite(n) || n < 0) return null;
  }

  const acts = interState
    ? [{ act: "IGST Act", share: 1 }]
    : [{ act: "CGST Act", share: 0.5 }, { act: "SGST/UTGST Act", share: 0.5 }];

  const perAct = acts.map(({ act, share }) => {
    let penalty;
    if (v.rule === "greaterOf") penalty = Math.max(round2(n * share), MIN_PENALTY_122);
    else if (v.rule === "perDay") penalty = Math.min(Math.floor(n) * PER_DAY_123, MAX_PENALTY_123);
    else penalty = MAX_PENALTY_125;
    return { act, penalty };
  });

  const total = round2(perAct.reduce((s, a) => s + a.penalty, 0));
  return {
    violation: v,
    perAct,
    total,
    upTo: v.rule === "general",
    // True when the ₹10,000 floor, not the amount, set the penalty in some Act.
    floorApplied: v.rule === "greaterOf" && n * acts[0].share < MIN_PENALTY_122,
  };
}
