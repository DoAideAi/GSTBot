import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { formatINR } from "../lib/gstCalc";
import { formatDay, rule37Reversal } from "../lib/itcTimeLimits";
import { todayInIndia } from "../lib/returnDueDates";

const PATH = "/itc-180-day-rule";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "180-Day ITC Reversal Calculator — Rule 37",
  url: `https://gst.doaide.com${PATH}`,
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "180-Day ITC Reversal Calculator" },
];

const ERRORS = {
  date: "Enter real dates.",
  amount: "Enter an invoice value above zero, and other amounts of zero or more.",
  "itc-exceeds-value": "The ITC cannot be more than the invoice value including tax.",
};

const FAQS = [
  {
    q: "What is the 180-day rule for ITC?",
    a: "Under section 16(2) and Rule 37, a buyer who has not paid the supplier within 180 days of the invoice date must reverse the credit on the unpaid part. Paying later brings it back.",
  },
  {
    q: "When must the ITC be reversed?",
    a: "In the GSTR-3B for the tax period after the one in which the 180 days end. If day 180 falls in July, the reversal goes in the August return, due on 20 September.",
  },
  {
    q: "Is interest payable on the reversal?",
    a: "Only if the credit was already used to pay tax. Interest at 18% a year under section 50 runs from the date it was used until it is reversed.",
  },
  {
    q: "Can the reversed ITC be claimed again?",
    a: "Yes. Once you pay the supplier, re-claim the credit in Table 4(A)(5) of GSTR-3B. The section 16(4) time limit does not apply to a re-claim under Rule 37(4).",
  },
  {
    q: "Which purchases are outside the 180-day rule?",
    a: "Supplies taxed under reverse charge, supplies made without consideration under Schedule I, and amounts added to value under section 15(2)(b) that the supplier pays on your behalf.",
  },
];

export default function Itc180DayRulePage() {
  usePageTitle("180-Day ITC Reversal Calculator — Rule 37 Unpaid Supplier Invoices");
  const [form, setForm] = useState({ invoiceDate: "", invoiceValue: "", itc: "", paidWithin: "", utilisedDate: "" });
  const today = useMemo(() => todayInIndia(), []);
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const ready = form.invoiceDate && form.invoiceValue !== "" && form.itc !== "";
  const result = useMemo(() => (ready ? rule37Reversal({ ...form, today }) : null), [ready, form, today]);

  return (
    <div className="tool-page">
      <SeoHead
        title="180-Day ITC Reversal Calculator — Rule 37 GST (Unpaid Suppliers)"
        description="Work out ITC to reverse under Rule 37 when a supplier is not paid within 180 days: the reversal, the GSTR-3B period, and 18% interest. Free, no login."
        path={PATH}
        jsonLd={[TOOL_SCHEMA, faqSchema(FAQS)]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">180-Day ITC Reversal Calculator</h1>
          <p className="tool-subtitle">
            Haven&apos;t paid a supplier within 180 days? See how much input tax credit to reverse,
            in which return, and what interest applies.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              Invoice date
              <input type="date" className="calc-input" value={form.invoiceDate} onChange={set("invoiceDate")} />
            </label>
            <label className="calc-label">
              Invoice value including GST (₹)
              <input type="number" className="calc-input" value={form.invoiceValue} onChange={set("invoiceValue")}
                placeholder="e.g. 118000" min="0" inputMode="decimal" />
            </label>
            <label className="calc-label">
              ITC claimed on the invoice (₹)
              <input type="number" className="calc-input" value={form.itc} onChange={set("itc")}
                placeholder="e.g. 18000" min="0" inputMode="decimal" />
            </label>
            <label className="calc-label">
              Amount paid to the supplier within 180 days (₹)
              <input type="number" className="calc-input" value={form.paidWithin} onChange={set("paidWithin")}
                placeholder="0" min="0" inputMode="decimal" />
            </label>
            <label className="calc-label">
              Date the ITC was used to pay tax (optional, for interest)
              <input type="date" className="calc-input" value={form.utilisedDate} onChange={set("utilisedDate")} />
            </label>

            {result?.error && (
              <p className="calc-error" role="alert">
                {ERRORS[result.error]}
              </p>
            )}

            {result && !result.error && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Pay the supplier by</span>
                  <strong>{formatDay(result.payBy)}</strong>
                </div>
                {result.fullyPaid ? (
                  <p>Paid in full within 180 days, so nothing needs to be reversed.</p>
                ) : (
                  <>
                    {result.daysToPay > 0 && (
                      <p>
                        {result.daysToPay} days left. Paying the balance before then avoids the
                        reversal entirely.
                      </p>
                    )}
                    <div className="calc-result-row">
                      <span>Unpaid amount</span>
                      <strong>{formatINR(result.unpaid)}</strong>
                    </div>
                    <div className="calc-result-row calc-total">
                      <span>ITC to reverse</span>
                      <strong>{formatINR(result.reversal)}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>Reverse in GSTR-3B for</span>
                      <strong>{result.reversalPeriod}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>That return is due</span>
                      <strong>{formatDay(result.reverseBy)}</strong>
                    </div>
                    {result.interest > 0 && (
                      <div className="calc-result-row">
                        <span>Interest at 18% ({result.interestDays} days)</span>
                        <strong>{formatINR(result.interest)}</strong>
                      </div>
                    )}
                    <p>
                      Show it in Table 4(B)(2). When you pay the supplier, re-claim it in Table
                      4(A)(5) — there is no time limit on the re-claim.
                    </p>
                    <p className="calc-note">Due dates assume monthly GSTR-3B. Quarterly filers reverse in the quarter&apos;s return.</p>
                  </>
                )}
                <div className="calc-result-actions">
                  <ShareButtons
                    path={PATH}
                    text="Checked my 180-day ITC reversal under Rule 37 — free on DoAide GST"
                    toolName="180-Day ITC Reversal Calculator"
                  />
                </div>
              </div>
            )}
          </div>

          <section className="tool-info">
            <h2>Keeping the 180-day rule from costing you</h2>
            <ol>
              <li>Age your payables by invoice date every month, and flag anything past 150 days.</li>
              <li>Part-payments reduce the reversal proportionately, so paying even some of the balance helps.</li>
              <li>If you reverse, record the reversal against the invoice so the re-claim is easy to trace.</li>
              <li>For credit that is blocked or never eligible, use the <Link to="/input-tax-credit">ITC eligibility checker</Link> instead. That credit is not re-claimable.</li>
            </ol>
          </section>

          <FaqSection faqs={FAQS} />

          <RelatedTools current={PATH} />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}

export { FAQS };
