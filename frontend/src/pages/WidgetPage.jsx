import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { calculate, formatINR, GST_SLABS, reverseCalculate } from "../lib/gstCalc";
import SeoHead from "../components/SeoHead";
import { usePageTitle } from "../hooks/usePageTitle";
import { track } from "../lib/track";

function parseWidgetParams(params) {
  const theme = params.get("theme");
  const rateParam = parseFloat(params.get("rate") || "");
  const widthParam = params.get("width");
  return {
    theme: theme === "light" || theme === "dark" ? theme : null,
    rate: Number.isFinite(rateParam) && rateParam >= 0 && rateParam <= 100 ? rateParam : 18,
    width: widthParam ? parseInt(widthParam, 10) || null : null,
  };
}

export { parseWidgetParams };

export default function WidgetPage() {
  usePageTitle("Embeddable GST Calculator Widget");
  const [params] = useSearchParams();
  const config = useMemo(() => parseWidgetParams(params), [params]);

  const [amount, setAmount] = useState("");
  const [rate, setRate] = useState(config.rate);
  const [interstate, setInterstate] = useState(false);
  const [mode, setMode] = useState("exclusive");

  useEffect(() => {
    if (config.theme) {
      document.documentElement.dataset.theme = config.theme;
      document.documentElement.style.colorScheme = config.theme;
    }
  }, [config.theme]);

  const parsed = parseFloat(amount);
  const valid = Number.isFinite(parsed) && parsed >= 0;

  const result = useMemo(
    () =>
      valid
        ? mode === "inclusive"
          ? reverseCalculate(parsed, rate, { interstate })
          : calculate(parsed, rate, { interstate })
        : null,
    [valid, mode, parsed, rate, interstate],
  );

  useEffect(() => {
    if (result) {
      track("widget_calculate", { amount: result.taxable, rate });
    }
  }, [result, rate]);

  const maxWidth = config.width ? `${config.width}px` : undefined;

  return (
    <div className="widget-page" style={maxWidth ? { maxWidth } : undefined}>
      <SeoHead
        title="Embeddable GST Calculator Widget — Free for Your Website"
        description="A free GST calculator you can embed on your website: add or remove GST at any slab, with CGST, SGST and IGST breakup. Light and dark themes."
        path="/widget"
      />
      <div className="widget-header">
        <strong>GST Calculator</strong>
      </div>

      <div className="widget-body">
        <div className="calc-mode-toggle" role="group" aria-label="Calculation mode">
          <button
            className={`calc-mode-btn${mode === "exclusive" ? " active" : ""}`}
            onClick={() => setMode("exclusive")}
          >
            Exclusive
          </button>
          <button
            className={`calc-mode-btn${mode === "inclusive" ? " active" : ""}`}
            onClick={() => setMode("inclusive")}
          >
            Inclusive
          </button>
        </div>

        <label className="calc-label">
          {mode === "inclusive" ? "Amount (incl. GST)" : "Taxable amount"}
          <input
            type="number"
            className="calc-input"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="Enter amount in ₹"
            min="0"
            step="0.01"
            inputMode="decimal"
          />
        </label>

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
          Interstate (IGST)
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
          </div>
        )}
      </div>

      <a
        className="widget-powered"
        href="https://gst.doaide.com?ref=widget"
        target="_blank"
        rel="noopener noreferrer"
      >
        Powered by <strong>DoAide GST</strong> — Try all our free tools
      </a>
    </div>
  );
}
