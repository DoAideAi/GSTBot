import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import { InlineCTA, StickyMobileCTA } from "../components/ConversionCTA";
import CrossProductLinks from "../components/CrossProductLinks";
import DoAideFooter from "../components/DoAideFooter";
import EmailCapture from "../components/EmailCapture";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import PrintButton from "../components/PrintButton";
import ShareButtons from "../components/ShareButtons";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import WhatsAppFloat from "../components/WhatsAppFloat";
import { track } from "../lib/track";

const ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";

const ENTITY_TYPES = {
  A: "Association of Persons (AOP)",
  B: "Body of Individuals (BOI)",
  C: "Company",
  F: "Partnership Firm / LLP",
  G: "Government Agency",
  H: "Hindu Undivided Family (HUF)",
  J: "Artificial Juridical Person",
  L: "Local Authority",
  P: "Individual / Proprietorship",
  T: "Trust (AOP)",
};

const STATE_CODES = {
  "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
  "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
  "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
  "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
  "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam",
  "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
  "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
  "25": "Daman & Diu", "26": "Dadra & Nagar Haveli", "27": "Maharashtra",
  "28": "Andhra Pradesh (old)", "29": "Karnataka", "30": "Goa",
  "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
  "34": "Puducherry", "35": "Andaman & Nicobar", "36": "Telangana",
  "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory",
  "99": "Centre",
};

function computeCheckDigit(gstin14) {
  let sum = 0;
  for (let i = 0; i < 14; i++) {
    const charVal = ALPHABET.indexOf(gstin14[i]);
    const weight = i % 2 === 0 ? 1 : 2;
    const product = charVal * weight;
    sum += Math.floor(product / 36) + (product % 36);
  }
  return ALPHABET[(36 - (sum % 36)) % 36];
}

function validateGstin(raw) {
  const gstin = raw.trim().toUpperCase();
  if (!gstin) return null;

  const errors = [];

  if (gstin.length !== 15) {
    errors.push(`GSTIN must be exactly 15 characters (entered ${gstin.length})`);
    return { gstin, valid: false, errors, breakdown: null };
  }

  if (!/^[0-9A-Z]+$/.test(gstin)) {
    errors.push("GSTIN must contain only digits and uppercase letters");
  }

  const stateCode = gstin.slice(0, 2);
  const pan = gstin.slice(2, 12);
  const entityCode = gstin[12];
  const reservedZ = gstin[13];
  const checkDigit = gstin[14];

  const stateName = STATE_CODES[stateCode];
  if (!stateName) errors.push(`Invalid state code "${stateCode}" — must be 01-38, 97, or 99`);
  if (!/^[A-Z]{5}[0-9]{4}[A-Z]$/.test(pan)) errors.push(`Invalid PAN format "${pan}"`);
  if (!/^[1-9A-Z]$/.test(entityCode)) errors.push(`Entity code must be 1-9 or A-Z, got "${entityCode}"`);
  if (reservedZ !== "Z") errors.push(`Position 14 must be "Z", got "${reservedZ}"`);

  const expectedCheck = computeCheckDigit(gstin.slice(0, 14));
  const checkValid = checkDigit === expectedCheck;
  if (!checkValid && errors.length === 0) {
    errors.push(`Invalid check digit — expected "${expectedCheck}", got "${checkDigit}"`);
  }

  const panEntityChar = pan.length >= 4 ? pan[3] : "";
  const entityType = ENTITY_TYPES[panEntityChar] || "Unknown";

  return {
    gstin,
    valid: errors.length === 0 && checkValid,
    errors,
    breakdown: {
      stateCode,
      stateName: stateName || "Unknown",
      pan,
      entityCode,
      entityType,
      reservedZ,
      checkDigit,
      expectedCheck,
      checkValid,
    },
  };
}

const TOOL_SCHEMA = {
  "@context": "https://schema.org",
  "@type": "WebApplication",
  name: "GSTIN Validator",
  url: "https://gst.doaide.com/gstin-validator",
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
      name: "What is the format of a GSTIN number?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "A GSTIN is a 15-character code. Positions 1-2 are the state code, 3-12 are the PAN, 13 is the entity number, 14 is always Z, and 15 is a check digit.",
      },
    },
    {
      "@type": "Question",
      name: "How is the GSTIN check digit calculated?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Each of the first 14 characters is assigned a numeric value and multiplied by alternating weights. The results are summed and the remainder after dividing by 36 gives the check digit.",
      },
    },
    {
      "@type": "Question",
      name: "Why is GSTIN validation important?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "A wrong GSTIN on a purchase invoice is the top reason for ITC mismatch. Even one transposed character makes the invoice show as missing. Validating at entry time catches this before filing.",
      },
    },
    {
      "@type": "Question",
      name: "What does each part of the GSTIN mean?",
      acceptedAnswer: {
        "@type": "Answer",
        text: "Positions 1-2 identify the state. 3-12 are the PAN. Position 13 is the entity number for that PAN in that state. 14 is always Z. 15 is the check digit.",
      },
    },
  ],
};

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GSTIN Validator" },
];

export default function GstinValidatorPage() {
  usePageTitle("Free GSTIN Validator — Verify GST Number Format Online");
  const [input, setInput] = useState("");

  const result = useMemo(() => validateGstin(input), [input]);

  const handleChange = (e) => {
    setInput(e.target.value);
    const v = e.target.value.trim();
    if (v.length === 15) track("gstin_validate", { gstin: v.toUpperCase() });
  };

  return (
    <div className="tool-page">
      <SeoHead
        title="Free GSTIN Validator — Verify GST Number Format Online"
        description="Validate any GSTIN number instantly. Check state code, PAN, entity code, and verify the check digit. Catch typos before they cause GSTR-2B mismatches. Free, no sign-up."
        path="/gstin-validator"
        jsonLd={[TOOL_SCHEMA, FAQ_SCHEMA]}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GSTIN Validator</h1>
          <p className="tool-subtitle">
            Validate the format of any GSTIN number — check state code, PAN, and verify the check digit. No sign-up required.
          </p>

          <div className="how-it-works">
            <h2 className="how-it-works-title">How It Works</h2>
            <div className="how-it-works-steps">
              <div className="how-it-works-step">
                <div className="how-it-works-num">1</div>
                <h3>Enter GSTIN</h3>
                <p>Type or paste any 15-character GSTIN number</p>
              </div>
              <div className="how-it-works-step">
                <div className="how-it-works-num">2</div>
                <h3>Instant Validation</h3>
                <p>Format, state code, PAN, and check digit are verified</p>
              </div>
              <div className="how-it-works-step">
                <div className="how-it-works-num">3</div>
                <h3>See Breakdown</h3>
                <p>Get a detailed breakdown of each part of the GSTIN</p>
              </div>
            </div>
          </div>

          <div className="calc-card">
            <label className="calc-label">
              GSTIN Number
              <input
                type="text"
                className="calc-input"
                value={input}
                onChange={handleChange}
                placeholder="e.g. 27AAPFU0939F1ZV"
                maxLength={15}
                spellCheck={false}
                autoComplete="off"
                autoFocus
                style={{ textTransform: "uppercase", fontFamily: "var(--mono)" }}
              />
            </label>

            {result && result.gstin && (
              <div className="calc-result" aria-live="polite">
                <div className={`calc-result-row ${result.valid ? "calc-valid" : "calc-invalid"}`}>
                  <span>Status</span>
                  <strong>{result.valid ? "Valid GSTIN" : "Invalid GSTIN"}</strong>
                </div>

                {result.breakdown && (
                  <>
                    <div className="calc-result-row">
                      <span>State Code</span>
                      <strong>{result.breakdown.stateCode} — {result.breakdown.stateName}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>PAN</span>
                      <strong>{result.breakdown.pan}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>Entity Type</span>
                      <strong>{result.breakdown.entityType}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>Entity Number</span>
                      <strong>{result.breakdown.entityCode}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>Reserved Character</span>
                      <strong>{result.breakdown.reservedZ}{result.breakdown.reservedZ === "Z" ? "" : " (should be Z)"}</strong>
                    </div>
                    <div className="calc-result-row">
                      <span>Check Digit</span>
                      <strong>
                        {result.breakdown.checkDigit}
                        {result.breakdown.checkValid
                          ? " (valid)"
                          : ` (invalid — expected ${result.breakdown.expectedCheck})`}
                      </strong>
                    </div>
                  </>
                )}

                {result.errors.length > 0 && (
                  <ul className="calc-errors">
                    {result.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                )}

                <div className="calc-result-actions">
                  <ShareButtons
                    path="/gstin-validator"
                    text={`GSTIN ${result.gstin} is ${result.valid ? "valid" : "invalid"} — verified free on DoAide GST`}
                  />
                  <PrintButton label="Print Result" />
                </div>
              </div>
            )}
          </div>

          <EmailCapture
            source="gstin-validator"
            heading="Get notified about GST updates"
            subtext="Stay updated when GST rules change — free email alerts."
            buttonLabel="Notify Me"
            compact
          />

          <section className="tool-info">
            <h2>How GSTIN Validation Works</h2>
            <p>
              Every GSTIN is a 15-character alphanumeric code with a built-in error-detection
              check digit. A single transposed character in a supplier&apos;s GSTIN on a purchase
              invoice is the most common cause of the invoice &ldquo;missing&rdquo; in GSTR-2B —
              and the ITC on it goes unclaimed until the supplier corrects their return.
            </p>
            <h3>GSTIN Structure</h3>
            <ul>
              <li><strong>Positions 1-2:</strong> State/UT code (01 Jammu &amp; Kashmir to 37 Andhra Pradesh, plus 97 Other Territory and 99 Centre)</li>
              <li><strong>Positions 3-12:</strong> PAN of the registered entity — 5 letters, 4 digits, 1 letter</li>
              <li><strong>Position 13:</strong> Entity/registration number for that PAN in that state (1-9, then A-Z for 10th+ registrations)</li>
              <li><strong>Position 14:</strong> Always &ldquo;Z&rdquo; — reserved by the GST design for future use</li>
              <li><strong>Position 15:</strong> Check digit — base-36 weighted mod-36, catches single-character errors and most transpositions</li>
            </ul>
          </section>

          <section className="tool-info">
            <h2>Frequently Asked Questions</h2>

            <h3>What is the format of a GSTIN number?</h3>
            <p>
              A GSTIN is 15 characters: state code (2 digits), PAN (10 characters), entity
              number (1 character, 1-9 or A-Z), reserved &ldquo;Z&rdquo;, and a check digit.
              Example: 27AAPFU0939F1ZV — where 27 is Maharashtra, AAPFU0939F is the PAN,
              1 is the first registration, Z is reserved, and V is the check digit.
            </p>

            <h3>How is the GSTIN check digit calculated?</h3>
            <p>
              Each of the first 14 characters is converted to a base-36 value (0-9 → 0-9,
              A-Z → 10-35), multiplied by weight 1 or 2 alternately. If the product exceeds
              36, its quotient and remainder are summed. The check digit is (36 - total % 36) % 36.
            </p>

            <h3>Why is GSTIN validation important?</h3>
            <p>
              A wrong GSTIN on an invoice causes it to be &ldquo;missing&rdquo; in GSTR-2B
              reconciliation. The ITC on that invoice goes unclaimed until the supplier
              corrects their filing — which they may never do. Catching the typo at entry
              avoids months of follow-up.
            </p>

            <h3>What does each part of the GSTIN mean?</h3>
            <p>
              The state code identifies where the registration is held. The PAN links to the
              entity&apos;s income tax identity. The entity number allows multiple registrations
              per PAN per state (e.g. for different branches). The check digit catches data
              entry errors.
            </p>
          </section>

          <InlineCTA variant="save" />
          <p className="bulk-gstin-pointer muted">
            Checking a whole supplier list? <Link to="/bulk-gstin">Validate up to 100 GSTINs at once</Link>{" "}
            on a paid plan.
          </p>
          <RelatedTools current="/gstin-validator" />
          <CrossProductLinks page="gstin-validator" />
        </div>
      </main>
      <DoAideFooter />
      <StickyMobileCTA />
      <WhatsAppFloat path="/gstin-validator" text="Free GSTIN Validator — validate any GST number format instantly" />
    </div>
  );
}
