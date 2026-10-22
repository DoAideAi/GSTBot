import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function GstImsGuide() {
  usePageTitle("GST Invoice Management System (IMS) Explained: Accept, Reject, Pending");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "How the GST Invoice Management System (IMS) works — accepting, rejecting and keeping invoices pending, how actions change your GSTR-2B and ITC, credit note handling, and a month-end IMS workflow.";

    let script = document.getElementById("blog-ld-json");
    if (!script) {
      script = document.createElement("script");
      script.id = "blog-ld-json";
      script.type = "application/ld+json";
      document.head.appendChild(script);
    }
    script.textContent = JSON.stringify([
      {
        "@context": "https://schema.org",
        "@type": "Article",
        headline: "GST Invoice Management System (IMS) Explained: Accept, Reject, Pending",
        description: "How IMS on the GST portal works, how accept/reject/pending actions change GSTR-2B and ITC, credit note rules, and a practical month-end workflow.",
        url: "https://gst.doaide.com/blog/gst-invoice-management-system-ims-guide",
        datePublished: "2026-10-22",
        dateModified: "2026-10-22",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "What is the Invoice Management System (IMS) in GST?", acceptedAnswer: { "@type": "Answer", text: "IMS is a facility on the GST portal where invoices your suppliers report in GSTR-1, IFF or amendments appear for you to accept, reject or keep pending before they flow into GSTR-2B and set your input tax credit." } },
          { "@type": "Question", name: "Is taking action on IMS mandatory?", acceptedAnswer: { "@type": "Answer", text: "No action is compulsory for invoices — records left untouched are treated as deemed accepted and flow into GSTR-2B. But active review protects you: rejecting wrong invoices keeps ineligible ITC out of your returns." } },
          { "@type": "Question", name: "What happens when I reject an invoice in IMS?", acceptedAnswer: { "@type": "Answer", text: "A rejected record is excluded from your GSTR-2B, so its ITC does not appear in your GSTR-3B auto-population. The supplier sees the rejection and must correct the document through an amendment if it was genuine." } },
          { "@type": "Question", name: "Can I keep an invoice pending in IMS?", acceptedAnswer: { "@type": "Answer", text: "Yes. Pending invoices stay in IMS without flowing into GSTR-2B until you act, subject to the ITC time limit under Section 16(4). Credit notes can stay pending only for one tax period under current rules." } },
          { "@type": "Question", name: "When is GSTR-2B generated under IMS?", acceptedAnswer: { "@type": "Answer", text: "GSTR-2B is generated on the 14th of the month for monthly filers. If you take further IMS actions after that, you must recompute GSTR-2B on the portal before filing GSTR-3B." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>GST Invoice Management System (IMS) Explained: Accept, Reject, Pending</h1>
      <p className="blog-meta">Updated October 2026 · 8 min read</p>

      <section>
        <p>
          The Invoice Management System (IMS) is the biggest change to how input tax credit
          works since GSTR-2B itself. Instead of your GSTR-2B being a passive snapshot of
          whatever suppliers uploaded, IMS puts every supplier invoice in front of you first —
          to <strong>accept</strong>, <strong>reject</strong>, or keep <strong>pending</strong> —
          and only the accepted (or untouched) records flow into GSTR-2B and your{" "}
          <Link to="/itc-calculator">ITC</Link>.
        </p>
        <p>
          If you claim ITC, IMS is now part of your monthly routine. This guide explains what
          each action does, how credit notes behave differently, and a month-end workflow that
          keeps your <Link to="/gstr2b-reconciliation">GSTR-2B reconciliation</Link> clean.
        </p>
      </section>

      <section>
        <h2>What IMS Is and Where It Sits</h2>
        <p>
          IMS lives on the GST portal under <em>Services → Returns → Invoice Management System</em>.
          From the moment a supplier saves a document in GSTR-1, IFF, or an amendment, it appears
          in your IMS inbox. Your actions decide its fate:
        </p>
        <ul>
          <li><strong>Accept</strong> — the record flows into your next GSTR-2B and its ITC auto-populates GSTR-3B</li>
          <li><strong>Reject</strong> — the record is excluded from GSTR-2B; the supplier is notified and must amend if it was genuine</li>
          <li><strong>Pending</strong> — the record waits in IMS, out of GSTR-2B, until you decide (useful when goods have not yet arrived or the invoice is under dispute)</li>
          <li><strong>No action</strong> — treated as <em>deemed accepted</em> when GSTR-2B is generated</li>
        </ul>
      </section>

      <section>
        <h2>How Each Action Affects Your ITC</h2>
        <table>
          <thead>
            <tr>
              <th>IMS action</th>
              <th>GSTR-2B</th>
              <th>ITC effect</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Accept / no action</td>
              <td>Included</td>
              <td>ITC auto-populates GSTR-3B Table 4</td>
            </tr>
            <tr>
              <td>Reject</td>
              <td>Excluded</td>
              <td>No ITC; supplier must amend to restore it</td>
            </tr>
            <tr>
              <td>Pending</td>
              <td>Excluded for now</td>
              <td>ITC deferred to the period you accept it — watch the Section 16(4) time limit</td>
            </tr>
          </tbody>
        </table>
        <p>
          Remember that IMS controls only <em>availability</em> in GSTR-2B. The usual conditions
          for claiming ITC still apply — possession of invoice, receipt of goods or services,
          supplier payment within 180 days, and the Section 16(4) deadline. Check eligibility
          with our <Link to="/input-tax-credit">ITC eligibility tool</Link>.
        </p>
      </section>

      <section>
        <h2>Credit Notes Are Special</h2>
        <p>
          A supplier&apos;s credit note <em>reduces</em> your ITC, so IMS treats it more strictly:
        </p>
        <ul>
          <li>Accepting a credit note reverses the corresponding ITC in your next GSTR-2B</li>
          <li>Rejecting a credit note increases the <em>supplier&apos;s</em> liability in their next GSTR-3B — reject only when the credit note is genuinely wrong</li>
          <li>Keeping a credit note pending is allowed only for a limited window (one tax period), unlike invoices which can stay pending until the ITC time limit</li>
        </ul>
        <p>
          Rejecting credit notes casually strains supplier relationships and creates mismatches
          that surface in <Link to="/blog/gstr-1-vs-gstr-3b-mismatch-how-to-fix">GSTR-1 vs
          GSTR-3B reconciliations</Link> on their side. Communicate before you reject.
        </p>
      </section>

      <section>
        <h2>A Practical Month-End IMS Workflow</h2>
        <ol>
          <li><strong>Days 1–11:</strong> suppliers file GSTR-1; records accumulate in your IMS inbox</li>
          <li><strong>Days 12–13:</strong> review IMS against your purchase register — accept matches, mark disputed or undelivered supplies pending, reject documents that are not yours</li>
          <li><strong>Day 14:</strong> GSTR-2B is generated from your IMS state</li>
          <li><strong>Before filing GSTR-3B:</strong> if you changed any IMS action after the 14th, <em>recompute</em> GSTR-2B on the portal — filing with a stale 2B is a common and avoidable mismatch</li>
          <li><strong>After filing:</strong> follow up with suppliers on rejected and pending records so the ITC lands next month</li>
        </ol>
      </section>

      <section>
        <h2>Common IMS Mistakes</h2>
        <ul>
          <li>Treating &quot;deemed accepted&quot; as safe — fake or erroneous invoices left untouched become your ITC problem in an audit</li>
          <li>Rejecting an invoice to &quot;fix&quot; a value difference — reject is for wrong documents; value disputes are better kept pending while the supplier amends</li>
          <li>Forgetting to recompute GSTR-2B after late IMS actions, so GSTR-3B auto-population doesn&apos;t match IMS</li>
          <li>Leaving genuine invoices pending past the Section 16(4) deadline and losing the credit permanently</li>
        </ul>
      </section>

      <section>
        <h2>FAQs</h2>
        <h3>Is IMS mandatory for every taxpayer?</h3>
        <p>IMS is available to all regular taxpayers. Taking action is not compulsory — untouched invoices are deemed accepted — but active review is the whole point: it is your chance to keep bad ITC out before it reaches GSTR-3B.</p>
        <h3>Does IMS replace GSTR-2B reconciliation?</h3>
        <p>No. IMS is where you act; reconciliation against your purchase register tells you which action to take. Run the comparison first, then accept or reject.</p>
        <h3>What about QRMP taxpayers?</h3>
        <p>IMS works for quarterly filers too — records flow into the quarterly GSTR-2B, and IFF-reported invoices appear in IMS in the month they are saved.</p>
      </section>

      <section>
        <h2>Related Tools and Guides</h2>
        <ul>
          <li><Link to="/gstr2b-reconciliation">GSTR-2B Reconciliation</Link> — match your purchase register before acting in IMS</li>
          <li><Link to="/itc-calculator">ITC Calculator</Link> — compute eligible credit</li>
          <li><Link to="/input-tax-credit">ITC Eligibility Checker</Link> — Section 16/17 conditions</li>
          <li><Link to="/blog/itc-rules-2026-what-every-business-must-know">ITC Rules 2026</Link> — the full credit rulebook</li>
          <li><Link to="/blog/gstr-3b-common-mistakes-how-to-avoid">GSTR-3B Common Mistakes</Link> — where IMS errors show up</li>
        </ul>
      </section>
    </article>
  );
}
