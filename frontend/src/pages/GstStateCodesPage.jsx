import { useState } from "react";
import { Link } from "react-router-dom";
import Breadcrumb from "../components/Breadcrumb";
import DoAideFooter from "../components/DoAideFooter";
import FaqSection, { faqSchema } from "../components/FaqSection";
import RelatedTools from "../components/RelatedTools";
import SeoHead from "../components/SeoHead";
import TableScroll from "../components/TableScroll";
import ToolsNav from "../components/ToolsNav";
import { usePageTitle } from "../hooks/usePageTitle";
import { STATE_CODES, stateForGstin } from "../lib/stateCodes";

const BREADCRUMBS = [
  { name: "Home", url: "https://gst.doaide.com" },
  { name: "GST State Code List" },
];

const FAQS = [
  {
    q: "What is the GST state code?",
    a: "The two digits at the start of every GSTIN, identifying the state or union territory of registration: 27 for Maharashtra, 29 for Karnataka, 07 for Delhi. Invoices and e-way bills use it for place of supply.",
  },
  {
    q: "Why does Andhra Pradesh have two GST state codes?",
    a: "Code 28 was Andhra Pradesh's code before the state was divided in 2014. Andhra Pradesh now uses code 37, and Telangana uses 36.",
  },
  {
    q: "What is the state code for Dadra and Nagar Haveli and Daman and Diu?",
    a: "26. The two union territories were merged in January 2020, and code 26 covers the merged territory. Code 25, the old Daman and Diu code, appears only on older registrations.",
  },
  {
    q: "When is UTGST charged instead of SGST?",
    a: "In union territories without a legislature (Chandigarh, Ladakh, Lakshadweep, Andaman and Nicobar, and Dadra and Nagar Haveli and Daman and Diu). Delhi, Puducherry and Jammu and Kashmir levy SGST.",
  },
  {
    q: "What do state codes 97 and 99 mean?",
    a: "97 is Other Territory, for areas outside every state, such as offshore installations. 99 is Centre Jurisdiction, for registrations made with the Centre, such as foreign online service providers.",
  },
];

export default function GstStateCodesPage() {
  usePageTitle("GST State Code List 2026 — All States & UTs");
  const [gstin, setGstin] = useState("");
  const found = stateForGstin(gstin);

  return (
    <div className="tool-page">
      <SeoHead
        title="GST State Code List 2026 — All States & Union Territories"
        description="Complete GST state code list: the first two digits of a GSTIN for every state and union territory, with SGST or UTGST. Find the state of any GSTIN instantly."
        path="/gst-state-codes"
        jsonLd={faqSchema(FAQS)}
        breadcrumbs={BREADCRUMBS}
      />
      <ToolsNav />
      <main className="tool-main">
        <div className="tool-container">
          <Breadcrumb />
          <h1 className="tool-title">GST State Code List</h1>
          <p className="tool-subtitle">
            The first two digits of every GSTIN identify the state or union territory of
            registration. Paste a GSTIN to see its state, or browse the full list.
          </p>

          <div className="calc-card">
            <label className="calc-label">
              GSTIN or state code
              <input
                className="calc-input"
                value={gstin}
                onChange={(e) => setGstin(e.target.value.toUpperCase())}
                placeholder="e.g. 27AAPFU0939F1ZV or 29"
                maxLength={15}
                autoComplete="off"
                spellCheck={false}
              />
            </label>
            {gstin.trim().length >= 2 && (
              <p aria-live="polite">
                {found ? (
                  <>
                    <strong>{found.code}</strong> — {found.name} ({found.kind})
                    {found.tax && <>. Intra-state supplies carry CGST + {found.tax}.</>}
                  </>
                ) : (
                  "That does not start with a valid GST state code."
                )}
              </p>
            )}
            <p className="rate-label">
              To check the whole number, including its check digit, use the{" "}
              <Link to="/gstin-validator">GSTIN validator</Link>.
            </p>
          </div>

          <section className="tool-info">
            <h2>State codes for all states and union territories</h2>
            <TableScroll label="GST state code table">
              <table className="hsn-table">
                <thead>
                  <tr>
                    <th scope="col">Code</th>
                    <th scope="col">State / UT</th>
                    <th scope="col">Type</th>
                    <th scope="col">Intra-state tax</th>
                  </tr>
                </thead>
                <tbody>
                  {STATE_CODES.map((s) => (
                    <tr key={s.code}>
                      <td className="hsn-code">{s.code}</td>
                      <td>{s.name}</td>
                      <td>{s.kind}</td>
                      <td>{s.tax ? `CGST + ${s.tax}` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
            <p>
              A supply between two different state codes is inter-state and carries IGST. Not
              sure which applies? Use the <Link to="/place-of-supply">place of supply tool</Link>.
            </p>
          </section>

          <FaqSection faqs={FAQS} />

          <RelatedTools current="/gst-state-codes" />
        </div>
      </main>
      <DoAideFooter />
    </div>
  );
}

export { FAQS };
