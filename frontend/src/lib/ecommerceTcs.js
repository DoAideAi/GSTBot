// TCS that an e-commerce operator collects from sellers (Section 52, CGST Act)
// and the income-tax TDS it deducts alongside (Section 194-O). Both come off a
// seller's payout, which is why the calculator shows them together.

// 0.5% from 10 July 2024 (Notification 15/2024–Central Tax); 1% before.
export const GST_TCS_RATE = 0.5;
// 0.1% from 1 October 2024 (Finance (No. 2) Act, 2024); 1% before.
export const TDS_194O_RATE = 0.1;

const round2 = (n) => Math.round(n * 100) / 100;

/**
 * TCS for one month.
 *
 * TCS is charged on the *net* value of taxable supplies — sales through the
 * operator less returns in the same month, excluding GST. When returns exceed
 * sales the month's TCS is nil; the excess is not refunded here.
 * `interstatePct` is the share of net sales going to other states, which
 * attracts IGST TCS; the rest is split evenly into CGST and SGST.
 * 194-O TDS is computed on gross sales.
 */
export function computeEcommerceTcs({ grossSales, returns = 0, interstatePct = 0 }) {
  const gross = Number(grossSales);
  const ret = Number(returns) || 0;
  const share = Math.min(Math.max(Number(interstatePct) || 0, 0), 100) / 100;
  if (!Number.isFinite(gross) || gross < 0 || !Number.isFinite(ret) || ret < 0) return null;

  const net = round2(gross - ret);
  const base = Math.max(net, 0);
  const tcs = round2((base * GST_TCS_RATE) / 100);
  const igst = round2(tcs * share);
  const cgst = round2((tcs - igst) / 2);
  const sgst = round2(tcs - igst - cgst);
  const tds194O = round2((gross * TDS_194O_RATE) / 100);

  return {
    gross,
    returns: ret,
    net,
    excessReturns: net < 0 ? -net : 0,
    tcs,
    igst,
    cgst,
    sgst,
    tds194O,
    totalWithheld: round2(tcs + tds194O),
  };
}
