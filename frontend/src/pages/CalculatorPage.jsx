import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import DeadlineBanner from "../components/DeadlineBanner";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import RelatedTools from "../components/RelatedTools";
import SavedCalculations, { getSavedCalcs, SaveCalcButton } from "../components/SavedCalculations";
import SavePrompt, { getCalcCount, incrementCalcCount } from "../components/SavePrompt";
import SeoHead from "../components/SeoHead";
import PrintButton from "../components/PrintButton";
import ShareButtons from "../components/ShareButtons";
import ShareSavings from "../components/ShareSavings";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { calcUrl, calculate, formatINR, GST_SLABS, parseCalcParams, reverseCalculate } from "../lib/gstCalc";
import { track } from "../lib/track";

/** How long a result must stand before it counts as a calculation. */
export const CALC_SETTLE_MS = 800;

export default function CalculatorPage() {
  usePageTitle("Free GST Calculator — Calculate CGST, SGST, IGST Instantly");
  const location = useLocation();
  const navigate = useNavigate();

  const initial = parseCalcParams(location.search);
  const [amount, setAmount] = useState(initial.amount != null ? String(initial.amount) : "");
  const [rate, setRate] = useState(initial.rate != null ? initial.rate : 18);
  const [interstate, setInterstate] = useState(initial.interstate);
  const [mode, setMode] = useState("exclusive");
  const [calcCount, setCalcCount] = useState(getCalcCount);
  const [promptDismissed, setPromptDismissed] = useState(false);
  const [savedCalcs, setSavedCalcs] = useState(getSavedCalcs);

  const parsed = parseFloat(amount);
  const valid = Number.isFinite(parsed) && parsed >= 0;
  const negative = Number.isFinite(parsed) && parsed < 0;

  const result = useMemo(
    () =>
      valid
        ? mode === "inclusive"
          ? reverseCalculate(parsed, rate, { interstate })
          : calculate(parsed, rate, { interstate })
        : null,
    [valid, mode, parsed, rate, interstate],
  );

  // The address bar carries the *taxable* value, because that is what
  // `?amount=` means when the page loads. In inclusive mode the field holds
  // the total, and writing that out meant a reload (or a copied link) showed
  // a different breakdown from the one on screen.
  const taxable = result ? result.taxable : null;
  useEffect(() => {
    if (taxable != null) {
      const url = calcUrl(taxable, rate, interstate);
      if (location.search !== url.replace("/calculator", "")) {
        navigate(url, { replace: true });
      }
    }
  }, [taxable, rate, interstate, navigate, location.search]);

  // Counted once the result has settled, not per keystroke. Typing "100"
  // used to be three calculations — enough to raise the sign-up prompt
  // before the visitor had finished entering their first amount — and sent
  // an analytics event for every digit.
  useEffect(() => {
    if (!result) return undefined;
    const timer = setTimeout(() => {
      track("gst_calculate", { amount: result.taxable, rate });
      setCalcCount(incrementCalcCount());
    }, CALC_SETTLE_MS);
    return () => clearTimeout(timer);
  }, [result, rate]);

  return (
    <div className="tool-page">
      <SeoHead
        title="Free GST Calculator Online - Calculate CGST, SGST, IGST"
        description="Calculate GST instantly for any amount. Get CGST, SGST, IGST breakdown with inclusive/exclusive modes. Example: 18% GST on ₹10,000 = ₹1,800 tax, ₹11,800 total."
        path="/calculator"
        jsonLd={[
          {
            "@context": "https://schema.org",
            "@type": "WebApplication",
            name: "Free GST Calculator",
            url: "https://gst.doaide.com/calculator",
            applicationCategory: "FinanceApplication",
            operatingSystem: "Any",
            offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
          },
          {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            mainEntity: [
              { "@type": "Question", name: "How do I calculate GST on a product?", acceptedAnswer: { "@type": "Answer", text: "Multiply the taxable amount by the GST rate and divide by 100. Example: 18% GST on ₹10,000 = ₹1,800, total ₹11,800. For intrastate sales, split equally into CGST and SGST (₹900 each)." } },
              { "@type": "Question", name: "What is the difference between GST exclusive and inclusive?", acceptedAnswer: { "@type": "Answer", text: "GST exclusive: price excludes GST, you add it on top. GST inclusive: GST is already in the price, you extract it. Formula: Taxable amount = Total / (1 + GST rate/100)." } },
              { "@type": "Question", name: "When is IGST charged instead of CGST+SGST?", acceptedAnswer: { "@type": "Answer", text: "IGST is charged on interstate supplies (supplier and buyer in different states). CGST+SGST is charged on intrastate supplies (same state). The total GST amount is the same — only the split differs." } },
              { "@type": "Question", name: "What are the GST rate slabs in India?", acceptedAnswer: { "@type": "Answer", text: "Under GST 2.0, India has 3 slabs plus Nil: 0% (essentials, insurance), 5% (necessities), 18% (most goods and services), and 40% (tobacco, luxury). The old 12% and 28% slabs are abolished." } },
            ],
          },
          {
            "@context": "https://schema.org",
            "@type": "HowTo",
            name: "How to calculate GST on any amount",
            description: "Get the CGST, SGST or IGST breakdown for any amount and rate, inclusive or exclusive of tax.",
            step: [
              { "@type": "HowToStep", name: "Pick the mode", text: "Choose GST Exclusive to add tax on top of a base price, or GST Inclusive to extract the tax already inside a total." },
              { "@type": "HowToStep", name: "Enter the amount", text: "Type the price in rupees." },
              { "@type": "HowToStep", name: "Pick the GST rate", text: "Select the slab — 0%, 5%, 18% or 40% under GST 2.0." },
              { "@type": "HowToStep", name: "Read the breakdown", text: "The calculator shows taxable value, CGST+SGST (same state) or IGST (inter-state), and the final total." },
            ],
          },
        ]}
      />
      <ToolsNav />
      <DeadlineBanner />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST Calculator</h1>
          <p className="tool-subtitle">
            Calculate GST tax breakdown instantly. No sign-up required.
          </p>

          <div className="calc-card">
            <div className="calc-mode-toggle" role="group" aria-label="Calculation mode">
              <button
                type="button"
                className={`calc-mode-btn${mode === "exclusive" ? " active" : ""}`}
                aria-pressed={mode === "exclusive"}
                onClick={() => setMode("exclusive")}
              >
                GST Exclusive
              </button>
              <button
                type="button"
                className={`calc-mode-btn${mode === "inclusive" ? " active" : ""}`}
                aria-pressed={mode === "inclusive"}
                onClick={() => setMode("inclusive")}
              >
                GST Inclusive
              </button>
            </div>

            <label className="calc-label">
              {mode === "inclusive" ? "Total amount (including GST)" : "Taxable amount (excluding GST)"}
              <input
                type="number"
                className="calc-input"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                placeholder="Enter amount in ₹"
                min="0"
                step="0.01"
                inputMode="decimal"
                autoFocus
                aria-invalid={negative}
                aria-describedby={negative ? "calc-amount-error" : undefined}
              />
            </label>
            {negative && (
              <p id="calc-amount-error" className="field-error" role="alert">
                Enter an amount of zero or more.
              </p>
            )}

            <label className="calc-label">
              GST Rate (%)
              <select
                className="calc-select"
                value={rate}
                onChange={(e) => setRate(Number(e.target.value))}
              >
                {GST_SLABS.map((r) => (
                  <option key={r} value={r}>
                    {r}%
                  </option>
                ))}
              </select>
            </label>

            <label className="calc-checkbox-label">
              <input
                type="checkbox"
                checked={interstate}
                onChange={(e) => setInterstate(e.target.checked)}
              />
              Interstate supply (IGST instead of CGST + SGST)
            </label>

            {result && (
              <div className="calc-result" aria-live="polite">
                <div className="calc-result-row">
                  <span>Taxable Value</span>
                  <strong>{formatINR(result.taxable)}</strong>
                </div>
                {result.interstate ? (
                  <div className="calc-result-row">
                    <span>IGST ({rate}%)</span>
                    <strong>{formatINR(result.igst)}</strong>
                  </div>
                ) : (
                  <>
                    <div className="calc-result-row">
                      <span>CGST ({rate / 2}%)</span>
                      <strong>{formatINR(result.cgst)}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>SGST ({rate / 2}%)</span>
                      <strong>{formatINR(result.sgst)}</strong>
                    </div>
                  </>
                )}
                <div className="calc-result-row calc-total">
                  <span>Total</span>
                  <strong>{formatINR(result.total)}</strong>
                </div>

                <div className="calc-result-actions">
                  <ShareButtons
                    path={calcUrl(result.taxable, rate, interstate)}
                    text={result.interstate
                      ? `✅ GST calculated: ${formatINR(result.taxable)} | IGST: ${formatINR(result.igst)} | Total: ${formatINR(result.total)} | Calculate yours free →`
                      : `✅ GST calculated: ${formatINR(result.taxable)} | CGST: ${formatINR(result.cgst)} SGST: ${formatINR(result.sgst)} | Total: ${formatINR(result.total)} | Calculate yours free →`
                    }
                  />
                  <SaveCalcButton result={result} rate={rate} onSaved={setSavedCalcs} />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          {result && <ShareSavings toolName="GST Calculator" savedAmount={500} />}

          {!promptDismissed && (
            <SavePrompt
              calcCount={calcCount}
              onDismiss={() => setPromptDismissed(true)}
            />
          )}

          <SavedCalculations calcs={savedCalcs} onUpdate={setSavedCalcs} />

          {result && (
            <EmailCapture
              source="calculator"
              heading="Get notified about GST rate changes"
              subtext="Stay updated when GST rates change — free email alerts."
              buttonLabel="Notify Me"
              compact
            />
          )}

          <section className="tool-info">
            <h2>How GST Calculation Works</h2>
            <p>
              GST in India is levied at the point of sale. For intrastate sales (within the same
              state), the tax is split equally between CGST (Central GST) and SGST (State GST).
              For interstate sales, IGST (Integrated GST) applies as a single tax.
            </p>
            <h3>GST 2.0 Rate Slabs in India (Effective 2026)</h3>
            <ul>
              <li><strong>0% (Nil)</strong> — Essentials: milk, fresh vegetables, grains, books, insurance (health &amp; life)</li>
              <li><strong>5%</strong> — Common necessities: sugar, tea, cooking oil, transport, cancer drugs</li>
              <li><strong>18%</strong> — Most goods and services: electronics, furniture, IT services, cement, processed food</li>
              <li><strong>40%</strong> — Tobacco, aerated drinks, vehicles above ₹20L, bikes above 350cc, premium goods</li>
            </ul>
            <p><em>The old 12% and 28% slabs have been abolished under GST 2.0. Items previously at 12% moved to 5% or 18%; items at 28% moved to 18% or 40%.</em></p>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>How do I calculate GST on a product?</h3>
            <p>
              Multiply the taxable amount by the GST rate and divide by 100. For example,
              18% GST on ₹10,000 = ₹1,800 tax, total ₹11,800. For intrastate sales, the
              tax splits equally into CGST and SGST (₹900 each).
            </p>

            <h3>What is the difference between GST exclusive and inclusive?</h3>
            <p>
              Exclusive means GST is added on top of the price. Inclusive means GST is
              already included — you extract it. Formula: Taxable = Total ÷ (1 + rate/100).
            </p>

            <h3>When is IGST charged instead of CGST+SGST?</h3>
            <p>
              IGST applies to interstate supplies (different states). CGST+SGST applies to
              intrastate supplies (same state). The total GST amount is identical.
            </p>

            <h3>What are the GST rate slabs in India?</h3>
            <p>
              Under GST 2.0: 0% (essentials, insurance), 5% (necessities), 18% (most goods
              and services), and 40% (tobacco, aerated drinks, luxury vehicles). The old 12%
              and 28% slabs have been abolished.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/calculator" />
          <CrossProductLinks page="calculator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
