import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";
import SeoHead from "../../components/SeoHead";

export default function EwayBillGuide() {
  usePageTitle("E-Way Bill Under GST: Rules, Generation Process & Validity");

  return (
    <article className="blog-article">
      <SeoHead title="E-Way Bill Under GST: Rules, Generation & Validity" description="E-way bill guide — when required (₹50,000+ goods movement), how to generate on portal, validity periods, exemptions, and penalties for non-compliance." path="/blog/eway-bill-gst-rules-guide" />
      <h1>E-Way Bill Under GST: Rules, Generation Process, and Validity</h1>
      <p className="blog-meta">Updated October 2026 · 10 min read</p>

      <section>
        <h2>What is an E-Way Bill?</h2>
        <p>
          An E-Way Bill (Electronic Way Bill) is a document required for the movement of goods
          worth more than ₹50,000 under the GST regime. It is generated on the E-Way Bill portal
          (ewaybillgst.gov.in) and serves as proof that the goods being transported are
          GST-compliant. The system was introduced to replace the multiple waybill systems that
          existed under the state VAT regime, providing a unified national framework for goods
          movement tracking.
        </p>
      </section>

      <section>
        <h2>When is an E-Way Bill Required?</h2>
        <p>
          An E-Way Bill must be generated when goods with a consignment value exceeding ₹50,000
          are moved:
        </p>
        <ul>
          <li>In relation to a supply (sale, transfer, barter, exchange)</li>
          <li>For reasons other than supply (job work, semi-knocked-down/completely-knocked-down movement, sales returns)</li>
          <li>Due to inward supply from an unregistered person</li>
        </ul>
        <p>
          The consignment value includes the value of goods, CGST, SGST/UTGST, IGST, and cess
          charged in the invoice. It does not include the value of exempt goods in a mixed
          consignment — only the taxable portion is considered.
        </p>
        <p>
          Some states have reduced the threshold below ₹50,000 for intra-state movement. Check
          your state&apos;s notification for the applicable limit.
        </p>
      </section>

      <section>
        <h2>Who Should Generate an E-Way Bill?</h2>
        <ul>
          <li><strong>Registered person:</strong> the consignor (supplier) or consignee (recipient) when movement is caused by them</li>
          <li><strong>Transporter:</strong> if neither the consignor nor consignee generates it, the transporter must do so before movement begins</li>
          <li><strong>Unregistered person:</strong> when an unregistered person makes a supply to a registered person, the recipient must generate the E-Way Bill</li>
        </ul>
      </section>

      <section>
        <h2>How to Generate an E-Way Bill</h2>
        <p>
          The E-Way Bill has two parts:
        </p>
        <h3>Part A — Supply Details</h3>
        <ul>
          <li>GSTIN of supplier and recipient</li>
          <li>Place of dispatch and delivery (PIN codes)</li>
          <li>Document type (invoice, bill of supply, delivery challan) and number</li>
          <li>Value of goods and HSN code</li>
          <li>Reason for transport (supply, export, job work, etc.)</li>
        </ul>
        <h3>Part B — Vehicle Details</h3>
        <ul>
          <li>Vehicle number (for road transport)</li>
          <li>Transport document number (for rail, air, or ship)</li>
          <li>Transporter ID (if assigned to a transporter)</li>
        </ul>
        <p>
          Part A can be filled in advance. The E-Way Bill becomes valid only when Part B is
          completed with vehicle details. If goods are transferred between vehicles mid-route,
          Part B must be updated with the new vehicle number.
        </p>
      </section>

      <section>
        <h2>Validity of E-Way Bills</h2>
        <p>
          Validity depends on the distance the goods must travel, calculated from the PIN code of
          dispatch to the PIN code of delivery:
        </p>
        <table className="blog-table">
          <thead>
            <tr>
              <th>Distance</th>
              <th>Validity (Regular)</th>
              <th>Validity (Over-Dimensional Cargo)</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Up to 200 km</td>
              <td>1 day</td>
              <td>1 day</td>
            </tr>
            <tr>
              <td>200 to 400 km</td>
              <td>3 days</td>
              <td>3 days</td>
            </tr>
            <tr>
              <td>400 to 600 km</td>
              <td>4 days</td>
              <td>6 days</td>
            </tr>
            <tr>
              <td>600 to 800 km</td>
              <td>5 days</td>
              <td>8 days</td>
            </tr>
            <tr>
              <td>800 to 1000 km</td>
              <td>6 days</td>
              <td>10 days</td>
            </tr>
            <tr>
              <td>Every additional 200 km</td>
              <td>+1 day</td>
              <td>+2 days</td>
            </tr>
          </tbody>
        </table>
        <p>
          Validity starts from the time Part B is completed. If the goods cannot be delivered
          within the validity period due to exceptional circumstances (natural calamity, vehicle
          breakdown, transhipment delay), the validity can be extended through the portal before
          or within 8 hours of expiry.
        </p>
      </section>

      <section>
        <h2>Intra-State vs Inter-State E-Way Bills</h2>
        <p>
          E-Way Bills are required for both intra-state and inter-state movement of goods above
          the threshold. Key differences:
        </p>
        <ul>
          <li><strong>Inter-state:</strong> mandatory for all movements above ₹50,000 across all states</li>
          <li><strong>Intra-state:</strong> mandatory above ₹50,000, but some states have lower thresholds or additional exemptions</li>
          <li><strong>Consolidated E-Way Bill:</strong> a transporter carrying goods from multiple consignors or consignees can generate one consolidated bill (Form GST EWB-02) covering all individual E-Way Bills for that vehicle</li>
        </ul>
      </section>

      <section>
        <h2>When an E-Way Bill is NOT Required</h2>
        <p>
          E-Way Bills are exempted in the following cases, regardless of value:
        </p>
        <ul className="blog-checklist">
          <li>Goods transported by non-motorised conveyance (hand cart, bullock cart)</li>
          <li>Goods moved from port, airport, or land customs station to an inland container depot or container freight station for customs clearance</li>
          <li>Goods transported under customs supervision or customs seal</li>
          <li>Transit cargo moving to or from Nepal or Bhutan</li>
          <li>Defence Ministry goods moved under Ministry of Defence or its authorised consignee</li>
          <li>Empty cargo containers being moved</li>
          <li>Goods specified as exempt from E-Way Bill requirements (listed in Annexure to Rule 138)</li>
          <li>Goods moved within a distance of 20 km from the place of business of the consignor to a weighbridge and back (with a delivery challan)</li>
        </ul>
      </section>

      <section>
        <h2>Penalties for Non-Compliance</h2>
        <table className="blog-table">
          <thead>
            <tr>
              <th>Violation</th>
              <th>Penalty</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Moving goods without an E-Way Bill</td>
              <td>₹10,000 or tax sought to be evaded, whichever is higher</td>
            </tr>
            <tr>
              <td>Moving goods with an expired E-Way Bill</td>
              <td>₹10,000 or tax sought to be evaded, whichever is higher</td>
            </tr>
            <tr>
              <td>Vehicle detention for inspection</td>
              <td>Vehicle and goods may be detained/seized; release on payment of applicable tax and penalty (200% of tax for owner, or 50% of value for non-owner)</td>
            </tr>
            <tr>
              <td>Repeated offences</td>
              <td>Confiscation of goods and vehicle; redemption on payment of market value of confiscated goods</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Common E-Way Bill Mistakes and How to Avoid Them</h2>
        <ul className="blog-checklist">
          <li>Entering wrong PIN codes — the system calculates distance from these; wrong PINs mean wrong validity</li>
          <li>Not updating Part B when changing vehicles mid-transit — each vehicle change needs an update</li>
          <li>Generating the E-Way Bill after goods have already started moving — it must be generated before</li>
          <li>Not generating an E-Way Bill for goods returned or rejected — returns also need an E-Way Bill if above ₹50,000</li>
          <li>Forgetting to extend validity before expiry — extension must be done before or within 8 hours of expiry</li>
          <li>Not cancelling unused E-Way Bills within 24 hours — uncancelled bills can trigger tax demands if inspected</li>
          <li>Using the wrong document type — match the document type (invoice, delivery challan, bill of supply) to the actual transaction</li>
        </ul>
      </section>

      <section>
        <h2>Recent Changes and Updates</h2>
        <ul>
          <li><strong>Multi-vehicle tracking:</strong> Part B can now be updated multiple times for multi-modal transport (road → rail → road)</li>
          <li><strong>Auto-calculation of distance:</strong> the portal now auto-calculates distance based on PIN codes, with a tolerance of 10% for route deviations</li>
          <li><strong>E-Way Bill and E-Invoice integration:</strong> for businesses generating e-invoices, Part A of the E-Way Bill is auto-populated from the IRN, reducing duplicate data entry</li>
          <li><strong>Blocking of E-Way Bills:</strong> taxpayers who have not filed GSTR-3B for two consecutive months are blocked from generating E-Way Bills</li>
        </ul>
        <p>
          Use our <Link to="/eway-bill">E-Way Bill tools</Link> to verify requirements and track
          goods movement for your business.
        </p>
      </section>

      <section className="blog-cta">
        <h2>Manage GST Compliance End to End</h2>
        <p>
          DoAide GST helps you track invoices, reconcile ITC, and stay on top of filing deadlines
          — so you can focus on running your business.{" "}
          <Link to="/">Get started with DoAide GST</Link> — it is free for basic use.
        </p>
      </section>
    </article>
  );
}
