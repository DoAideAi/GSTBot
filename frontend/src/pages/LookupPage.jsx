import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DeadlineBanner from "../components/DeadlineBanner";
import DoAideFooter from "../components/DoAideFooter";
import RecentLookups from "../components/RecentLookups";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { api } from "../lib/api";
import { track } from "../lib/track";
import { normalizeGstin } from "../lib/validate";

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "Free GSTIN Lookup & Verification",
  url: "https://gst.doaide.com/lookup",
  applicationCategory: "FinanceApplication",
  operatingSystem: "Any",
  offers: { "@type": "Offer", price: "0", priceCurrency: "INR" },
};

const FAQ_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "FAQPage",
  mainEntity: [
    {
      "@type": "Question",
      name: "What is a GSTIN?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "A GSTIN is a unique 15-character identifier for every GST-registered business in India. It encodes the state code, PAN of the entity, entity number within that state, and a check digit.",
      },
    },
    {
      "@type": "Question",
      name: "How do I verify a GSTIN?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Enter the 15-digit GSTIN above to validate its format (state code, PAN structure, check digit) and see the registration state, PAN, and validity. You can also verify on the GST portal.",
      },
    },
    {
      "@type": "Question",
      name: "Why should I verify a GSTIN before transacting?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "A wrong GSTIN on a purchase invoice is the top reason ITC goes unclaimed — it shows as missing in GSTR-2B and the credit never arrives. Verifying before you transact catches typos early.",
      },
    },
    {
      "@type": "Question",
      name: "What does each part of a GSTIN mean?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Digits 1-2 are the state code, digits 3-12 are the PAN, digit 13 is the entity number for that PAN in that state, digit 14 is always Z (reserved), and digit 15 is the check digit computed from the first 14 characters.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GSTIN Lookup" },
];

export default function LookupPage() {
  usePageTitle("Free GSTIN Lookup — Verify Any GST Number Instantly");
  const navigate = useNavigate();
  const location = useLocation();
  const params = useParams();

  const initialGstin = params.gstin || new URLSearchParams(location.search).get("q") || "";
  const [input, setInput] = useState(initialGstin);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const abortRef = useRef(null);

  const lookup = useCallback(
    async (gstin, { fromForm = false } = {}) => {
      const cleaned = normalizeGstin(gstin);
      if (!cleaned || cleaned.length < 2) {
        setResult(null);
        // Pressing Verify on an empty box used to do nothing at all.
        setError(fromForm ? "Enter a 15-character GSTIN, e.g. 27AAPFU0939F1ZV." : "");
        return;
      }

      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setLoading(true);
      setError("");
      // The last answer is about a different number: leaving "Valid GSTIN"
      // up while this one is checked — or next to its error — reads as this
      // number's verdict.
      setResult(null);
      try {
        const data = await api.validateGstin(cleaned);
        if (controller.signal.aborted) return;
        setResult(data);
        // Never the GSTIN itself: characters 3-12 are a PAN — for a
        // proprietorship the owner's personal one — and Umami is a third-party
        // store. The state and the verdict are what the usage question needs.
        track("gstin_lookup", { state: cleaned.slice(0, 2), valid: Boolean(data.valid) });
        if (data.valid) {
          navigate(`/gstin/${cleaned}`, { replace: true });
        }
      } catch (err) {
        if (err?.name !== "AbortError") {
          // An HTTP refusal carries its own sentence (a rate limit says to
          // wait); "could not reach the server" was only ever true of the
          // request that never got an answer.
          setError(
            err?.status ? err.message : "Could not reach the server. Try again.",
          );
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [navigate],
  );

  useEffect(() => {
    if (initialGstin) lookup(initialGstin);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = (e) => {
    e.preventDefault();
    lookup(input, { fromForm: true });
  };

  return (
    <div className="tool-page">
      <SeoHead
        title="Free GSTIN Lookup & Verification — Check Any GST Number"
        description="Verify any GSTIN instantly. Check registration status, state code, PAN, business name, and filing compliance. Free GSTIN verification tool — no login required."
        path="/lookup"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <DeadlineBanner />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GSTIN Lookup</h1>
          <p className="tool-subtitle">
            Verify any GST number instantly. Check validity, state, and PAN details.
          </p>

          <div className="calc-card">
            <form onSubmit={handleSubmit} className="lookup-form" aria-busy={loading}>
              <label className="calc-label">
                Enter GSTIN
                <input
                  type="text"
                  className="calc-input"
                  value={input}
                  onChange={(e) => setInput(e.target.value.toUpperCase())}
                  placeholder="e.g. 27AAPFU0939F1ZV"
                  maxLength={20}
                  autoFocus
                  spellCheck={false}
                  autoComplete="off"
                />
              </label>
              <button type="submit" className="btn btn-primary lookup-btn" disabled={loading}>
                {loading ? "Checking…" : "Verify GSTIN"}
              </button>
            </form>

            {error && <p className="lookup-error" role="alert">{error}</p>}

            {/* Always in the tree: a live region that appears together with
                its content is not announced, so the first verdict was silent
                to a screen reader. */}
            <div className={result ? "lookup-result" : undefined} aria-live="polite">
              {result && (result.valid ? (
                  <>
                    <div className="lookup-badge lookup-valid">Valid GSTIN</div>
                    <dl className="lookup-details">
                      <dt>GSTIN</dt>
                      <dd className="lookup-gstin-value">{result.gstin}</dd>
                      <dt>State</dt>
                      <dd>{result.state_name} ({result.state_code})</dd>
                      <dt>PAN</dt>
                      <dd>{result.pan}</dd>
                    </dl>
                    <ShareButtons
                      path={`/gstin/${result.gstin}`}
                      text={`GSTIN ${result.gstin} is valid — registered in ${result.state_name}. Verified on DoAide GST`}
                    />
                  </>
                ) : (
                  <div className="lookup-badge lookup-invalid">Invalid GSTIN</div>
                ))}
              {result?.error && <p className="lookup-reason">{result.error}</p>}
            </div>
          </div>

          <p className="bulk-gstin-pointer muted">
            Checking a whole supplier list? <Link to="/bulk-gstin">Validate up to 100 GSTINs at once</Link>{" "}
            on a paid plan.
          </p>

          <RecentLookups />

          <section className="tool-info">
            <h2>What Is a GSTIN?</h2>
            <p>
              A GSTIN (Goods and Services Tax Identification Number) is a unique 15-character
              identifier assigned to every business registered under GST in India. It encodes
              the state, PAN of the entity, and a check digit.
            </p>
            <h3>GSTIN Format</h3>
            <ul>
              <li><strong>Digits 1–2:</strong> State code (e.g. 27 = Maharashtra)</li>
              <li><strong>Digits 3–12:</strong> PAN of the registered entity</li>
              <li><strong>Digit 13:</strong> Entity number for that PAN in that state</li>
              <li><strong>Digit 14:</strong> Always Z (reserved)</li>
              <li><strong>Digit 15:</strong> Check digit</li>
            </ul>
            <h3>Why Verify a GSTIN?</h3>
            <p>
              A wrong GSTIN on a purchase invoice is the most common reason ITC goes unclaimed.
              The invoice shows up as &ldquo;missing at supplier&rsquo;s end&rdquo; in GSTR-2B, and the credit
              you paid for never arrives. Verifying at the point of entry catches typos before
              they cost money.
            </p>
          </section>

          <InlineCTA variant="save" />
          <RelatedTools current="/lookup" />
          <CrossProductLinks page="lookup" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
    </div>
  );
}
