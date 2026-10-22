import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function GstRegistrationGuide2026() {
  usePageTitle("Complete Guide to GST Registration in India 2026");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Complete guide to GST registration in India 2026. Learn who needs GST registration, types of registration, documents required, step-by-step process, timelines, and common mistakes.";

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
        headline: "Complete Guide to GST Registration in India 2026",
        description: "Everything about GST registration in India 2026 — types, eligibility, documents, online process, timelines, and penalties for non-registration.",
        url: "https://gst.doaide.com/blog/gst-registration-complete-guide-2026",
        datePublished: "2026-10-08",
        dateModified: "2026-10-08",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "Is GST registration free?", acceptedAnswer: { "@type": "Answer", text: "Yes, GST registration on the official portal gst.gov.in is completely free. There is no government fee. Tax professionals may charge ₹1,000–₹5,000 for assistance." } },
          { "@type": "Question", name: "How many days does GST registration take?", acceptedAnswer: { "@type": "Answer", text: "If all documents are in order and Aadhaar authentication is completed, registration is typically granted within 3–7 working days. If a query is raised, it may take up to 30 days." } },
          { "@type": "Question", name: "Can I get GST registration without a shop?", acceptedAnswer: { "@type": "Answer", text: "Yes. You can register with a residential address as your principal place of business with valid address proof — an electricity bill, rent agreement or property tax receipt. Many freelancers register from home." } },
          { "@type": "Question", name: "What happens if I don't register for GST?", acceptedAnswer: { "@type": "Answer", text: "Operating without GST registration when required attracts a penalty of 10% of the tax due (minimum ₹10,000). In case of willful evasion, the penalty can be 100% of the tax due." } },
          { "@type": "Question", name: "Can I have multiple GST registrations?", acceptedAnswer: { "@type": "Answer", text: "Yes. You need a separate GSTIN for each state where you have a place of business. Within the same state, you can obtain additional registration for different business verticals." } },
          { "@type": "Question", name: "Is Aadhaar mandatory for GST registration?", acceptedAnswer: { "@type": "Answer", text: "Aadhaar authentication is mandatory for proprietorships, partnerships, and individual applicants. For companies and LLPs, DSC (Digital Signature Certificate) is required instead." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>Complete Guide to GST Registration in India 2026</h1>
      <p className="blog-meta">Updated October 2026 · 15 min read</p>

      <section>
        <p>
          The Goods and Services Tax (GST) is India&apos;s unified indirect tax system that replaced multiple
          taxes like VAT, service tax, and excise duty. GST registration is the first step for any business
          to become part of this system. This comprehensive guide covers everything you need to know about
          GST registration in 2026 — from eligibility criteria and types of registration to the complete
          online process, timelines, and post-registration compliance.
        </p>
        <p>
          Whether you&apos;re a startup founder, a freelancer, an e-commerce seller, or a manufacturer,
          understanding GST registration is essential. Use our{" "}
          <Link to="/turnover-limit">Turnover Limit Checker</Link> to quickly determine if registration
          is mandatory for your business.
        </p>
      </section>

      <section>
        <h2>What Is GST Registration?</h2>
        <p>
          GST registration is the process by which a business becomes a registered taxpayer under the
          Goods and Services Tax Act. Upon successful registration, you receive a unique 15-digit
          identification number called GSTIN (Goods and Services Tax Identification Number). This GSTIN
          must be displayed on all invoices, returns, and correspondence with the GST department.
        </p>
        <p>
          Registration is done entirely online through the GST portal at gst.gov.in. There is no
          physical documentation or office visit required. The process is paperless and can be completed
          from anywhere in India.
        </p>
      </section>

      <section>
        <h2>Who Must Register for GST in 2026?</h2>
        <p>
          GST registration is mandatory based on turnover thresholds and specific business activities.
          Here are the current rules:
        </p>

        <h3>Turnover-Based Registration</h3>
        <ul>
          <li><strong>Goods suppliers:</strong> Annual aggregate turnover exceeding ₹40 lakhs (₹20 lakhs for special category states — Manipur, Mizoram, Nagaland, Tripura, Meghalaya, Arunachal Pradesh, Sikkim, and Uttarakhand)</li>
          <li><strong>Service providers:</strong> Annual aggregate turnover exceeding ₹20 lakhs (₹10 lakhs for special category states)</li>
          <li><strong>Mixed suppliers:</strong> The lower threshold of ₹20 lakhs applies when you supply both goods and services</li>
        </ul>

        <h3>Mandatory Registration (Regardless of Turnover)</h3>
        <p>Certain businesses must register even if turnover is below the threshold:</p>
        <ul>
          <li><strong>Inter-state suppliers:</strong> Any business making taxable supply of goods or services to another state</li>
          <li><strong>E-commerce sellers:</strong> Sellers on Amazon, Flipkart, Meesho, and other marketplaces</li>
          <li><strong>E-commerce operators:</strong> Platforms that facilitate supply on behalf of sellers</li>
          <li><strong>Reverse charge mechanism (RCM):</strong> Persons required to pay tax under reverse charge</li>
          <li><strong>Casual taxable persons:</strong> Businesses that occasionally supply goods/services in a state where they have no fixed place of business</li>
          <li><strong>Non-resident taxable persons:</strong> Foreign businesses supplying to India</li>
          <li><strong>Input Service Distributors (ISD):</strong> Businesses distributing ITC to branches</li>
          <li><strong>Agents:</strong> Persons making supply on behalf of other taxable persons</li>
          <li><strong>TDS/TCS deductors:</strong> Government bodies and e-commerce operators deducting tax at source</li>
        </ul>
        <p>
          Not sure if registration is mandatory for you? Check with our{" "}
          <Link to="/registration-checker">Registration Checker</Link> tool.
        </p>
      </section>

      <section>
        <h2>Types of GST Registration</h2>

        <h3>1. Normal/Regular Registration</h3>
        <p>
          This is the standard registration for businesses exceeding the turnover threshold.
          Regular taxpayers can charge GST, claim Input Tax Credit (ITC), and must file monthly/quarterly
          returns (GSTR-1 and GSTR-3B). There is no validity period — registration remains active until
          cancelled or surrendered.
        </p>

        <h3>2. Composition Scheme Registration</h3>
        <p>
          A simplified scheme for small businesses with turnover up to ₹1.5 crore (₹75 lakhs for
          special category states). Under this scheme, you pay GST at a flat rate (1% for manufacturers,
          1% for traders, 6% for restaurants, 6% for service providers up to ₹50 lakhs). However,
          you cannot claim ITC or issue tax invoices. Compare both options using our{" "}
          <Link to="/scheme-comparison">Scheme Comparison</Link> tool.
        </p>

        <h3>3. Casual Taxable Person</h3>
        <p>
          For businesses that occasionally supply goods/services in a state where they have no fixed
          place of business (e.g., setting up a stall at an exhibition). Valid for 90 days, extendable
          by another 90 days. Requires advance tax deposit at the time of registration.
        </p>

        <h3>4. Non-Resident Taxable Person</h3>
        <p>
          For foreign businesses making taxable supplies in India without a permanent establishment.
          Valid for 90 days, extendable. Requires advance tax deposit and appointment of an authorized
          signatory in India.
        </p>

        <h3>5. Input Service Distributor (ISD)</h3>
        <p>
          For businesses with a head office that receives invoices for input services and distributes
          the ITC to various branches. The head office registers separately as an ISD.
        </p>

        <h3>6. UN Bodies and Embassies</h3>
        <p>
          Special registration for UN agencies, embassies, and consulates to claim refund of tax
          paid on purchases for official use.
        </p>
      </section>

      <section>
        <h2>Documents Required for GST Registration</h2>
        <p>The documents vary based on the type of business entity:</p>

        <h3>For Proprietorship</h3>
        <ul>
          <li>PAN card of the proprietor</li>
          <li>Aadhaar card of the proprietor</li>
          <li>Photograph (passport size)</li>
          <li>Address proof of business — electricity bill, rent agreement, or property tax receipt</li>
          <li>Bank account details — cancelled cheque or first page of passbook</li>
        </ul>

        <h3>For Partnership Firm / LLP</h3>
        <ul>
          <li>PAN card of the firm/LLP</li>
          <li>Partnership deed / LLP agreement</li>
          <li>PAN and Aadhaar of all partners</li>
          <li>Photographs of all partners</li>
          <li>Address proof of business premises</li>
          <li>Bank account details of the firm</li>
          <li>Certificate of Registration (for LLP)</li>
        </ul>

        <h3>For Private Limited / Public Limited Company</h3>
        <ul>
          <li>PAN card of the company</li>
          <li>Certificate of Incorporation</li>
          <li>MOA and AOA</li>
          <li>Board Resolution authorizing a signatory</li>
          <li>PAN and Aadhaar of all directors</li>
          <li>Photographs of directors</li>
          <li>Address proof of registered office</li>
          <li>Bank account details</li>
          <li>Digital Signature Certificate (DSC) of the authorized signatory</li>
        </ul>
      </section>

      <section>
        <h2>Step-by-Step GST Registration Process Online</h2>

        <h3>Step 1: Visit the GST Portal</h3>
        <p>
          Go to <strong>gst.gov.in</strong> and click on Services → Registration → New Registration.
          Select &quot;Taxpayer&quot; from the dropdown. Enter your state and district.
        </p>

        <h3>Step 2: Generate TRN</h3>
        <p>
          Enter your PAN, email address, and mobile number. OTPs will be sent to both. Verify the OTPs
          to generate a Temporary Reference Number (TRN). This TRN is valid for 15 days — save it securely.
        </p>

        <h3>Step 3: Log In and Fill Part B</h3>
        <p>
          Use your TRN to log in. The application form has the following tabs:
        </p>
        <ol>
          <li><strong>Business Details:</strong> Legal name (as on PAN), trade name, constitution type (proprietorship, partnership, company, etc.), district, and date of business commencement</li>
          <li><strong>Promoter/Partner Details:</strong> Full name, DIN (for directors), residential address, Aadhaar number, mobile number, email, and photograph</li>
          <li><strong>Authorized Signatory:</strong> Designate the person who will file returns and sign documents</li>
          <li><strong>Principal Place of Business:</strong> Full address with PIN code, nature of possession (owned, rented, leased), and proof documents</li>
          <li><strong>Additional Places of Business:</strong> Branches, warehouses, godowns if any</li>
          <li><strong>Goods and Services:</strong> Up to 5 HSN codes for goods and 5 SAC codes for services — use our <Link to="/hsn-sac-finder">HSN/SAC Finder</Link> to get the correct codes</li>
          <li><strong>Bank Account Details:</strong> Can be added within 45 days of registration</li>
          <li><strong>State-Specific Information:</strong> Professional tax number, state excise license, etc.</li>
        </ol>

        <h3>Step 4: Upload Documents</h3>
        <p>
          Upload scanned copies of all required documents. Each file must be in PDF or JPEG format
          and under 1 MB. Ensure documents are clear, recent (address proof within 2 months), and
          match the details in the application.
        </p>

        <h3>Step 5: Aadhaar Authentication</h3>
        <p>
          Proprietors, partners, and individuals must complete Aadhaar authentication. An OTP is sent
          to the mobile number linked to your Aadhaar. Biometric verification at GST Sewa Kendra
          may be required in some cases.
        </p>

        <h3>Step 6: Submit and Verify</h3>
        <p>
          Review all details carefully. Submit using:
        </p>
        <ul>
          <li><strong>EVC (Electronic Verification Code):</strong> OTP sent to Aadhaar-linked mobile. Available for proprietorships, partnerships, and HUFs</li>
          <li><strong>DSC (Digital Signature Certificate):</strong> Mandatory for companies and LLPs. Must be Class 2 or Class 3 DSC</li>
        </ul>
        <p>
          After submission, you receive an Application Reference Number (ARN) via email and SMS.
          Track your application status on the GST portal using this ARN.
        </p>

        <h3>Step 7: Receive GSTIN</h3>
        <p>
          If the application is complete and documents are satisfactory, the tax officer approves
          registration within 3–7 working days. Your GSTIN and registration certificate are generated
          automatically. Download the certificate from the GST portal. Verify your GSTIN anytime using
          our <Link to="/gstin-validator">GSTIN Validator</Link>.
        </p>
      </section>

      <section>
        <h2>Timeline and Processing</h2>
        <ul>
          <li><strong>Normal processing:</strong> 3–7 working days from submission date</li>
          <li><strong>With Aadhaar authentication:</strong> Often processed within 3 working days</li>
          <li><strong>If clarification needed:</strong> Officer issues a notice (SCN) → 7 days to respond → decision within 7 days of response. Total may take 21–30 days</li>
          <li><strong>Deemed approval:</strong> If no action taken within 21 days (for non-risky applicants), registration is deemed approved automatically</li>
          <li><strong>For companies/LLPs:</strong> May take 7–10 days due to DSC verification</li>
        </ul>
      </section>

      <section>
        <h2>Penalties for Not Registering</h2>
        <p>
          Failing to register when required can result in serious consequences:
        </p>
        <ul>
          <li><strong>Penalty:</strong> 10% of tax due or ₹10,000, whichever is higher, for genuine errors</li>
          <li><strong>Deliberate evasion:</strong> 100% of tax due (effectively double the tax amount)</li>
          <li><strong>No ITC claim:</strong> You cannot claim Input Tax Credit on purchases made before registration</li>
          <li><strong>Loss of business:</strong> B2B customers prefer registered vendors (they can claim ITC on your invoices)</li>
          <li><strong>E-commerce ban:</strong> Marketplaces will not allow unregistered sellers to list products</li>
        </ul>
        <p>
          Calculate potential penalties with our <Link to="/penalty-calculator">Penalty Calculator</Link>.
        </p>
      </section>

      <section>
        <h2>Post-Registration Compliance</h2>
        <p>After receiving your GSTIN, you must:</p>
        <ul>
          <li><strong>Display GSTIN:</strong> On your shop signboard, invoices, and website</li>
          <li><strong>Issue tax invoices:</strong> With GSTIN, HSN/SAC codes, and tax amount breakup</li>
          <li><strong>File GSTR-1:</strong> Monthly (by 11th) or quarterly (under QRMP) — details of outward supplies</li>
          <li><strong>File GSTR-3B:</strong> Monthly (by 20th) or quarterly — summary return with tax payment</li>
          <li><strong>File annual return:</strong> GSTR-9 by December 31st of the following year</li>
          <li><strong>Maintain records:</strong> Keep invoices, accounts, and stock records for 72 months</li>
          <li><strong>Generate E-Way Bills:</strong> For movement of goods worth over ₹50,000</li>
          <li><strong>E-invoicing:</strong> Mandatory for businesses with turnover above ₹5 crore</li>
        </ul>
        <p>
          Stay on top of due dates with our <Link to="/return-calendar">Return Calendar</Link> and track
          your filing status on the <Link to="/">Dashboard</Link>.
        </p>
      </section>

      <section>
        <h2>Voluntary GST Registration: When It Makes Sense</h2>
        <p>
          Even if your turnover is below the threshold, you may want to register voluntarily for these benefits:
        </p>
        <ul>
          <li><strong>Claim ITC:</strong> Recover GST paid on purchases, reducing your costs by 5–18%</li>
          <li><strong>Sell on marketplaces:</strong> Amazon, Flipkart, and Meesho require GSTIN for all sellers</li>
          <li><strong>Inter-state sales:</strong> Ship products to customers in other states</li>
          <li><strong>Credibility:</strong> Larger businesses and government entities prefer dealing with registered vendors</li>
          <li><strong>Government tenders:</strong> GSTIN is often a mandatory eligibility criterion</li>
          <li><strong>B2B growth:</strong> Corporate clients can claim ITC only if you are registered</li>
        </ul>
      </section>

      <section>
        <h2>Common Mistakes to Avoid</h2>
        <ul>
          <li><strong>PAN mismatch:</strong> The legal name must exactly match PAN records — verify your PAN details first</li>
          <li><strong>Incorrect address proof:</strong> Electricity bill must be in the business owner&apos;s or business entity&apos;s name. If in a landlord&apos;s name, attach an NOC (No Objection Certificate)</li>
          <li><strong>Expired documents:</strong> Address proof should be dated within the last 2 months</li>
          <li><strong>Wrong HSN codes:</strong> Incorrect HSN/SAC classification can lead to rejection — use our <Link to="/hsn-sac-finder">HSN/SAC Finder</Link> for accuracy</li>
          <li><strong>Aadhaar not linked to mobile:</strong> EVC requires the mobile number linked to your Aadhaar. Update at the nearest enrolment centre before applying</li>
          <li><strong>Blurry uploads:</strong> Scan documents at 200+ DPI in colour. Black-and-white scans may be rejected</li>
          <li><strong>Delayed bank details:</strong> While you have 45 days to add bank details, doing it later requires a separate amendment process</li>
        </ul>
      </section>

      <section>
        <h2>GST Registration for Specific Business Types</h2>

        <h3>Freelancers and Consultants</h3>
        <p>
          If your annual service income exceeds ₹20 lakhs, registration is mandatory. Register as a
          proprietorship with your residential address. Use SAC code 998311 (management consulting) or
          998314 (IT services) based on your work.
        </p>

        <h3>E-Commerce Sellers</h3>
        <p>
          Registration is mandatory regardless of turnover if you sell through Amazon, Flipkart, or
          any e-commerce platform. The marketplace deducts 1% TCS on your sales and deposits it with
          the government. You can claim this TCS credit while filing returns.
        </p>

        <h3>Restaurants and Food Businesses</h3>
        <p>
          Restaurants with turnover up to ₹1.5 crore can opt for the Composition Scheme at a flat 5% GST
          rate. Above ₹1.5 crore, the regular 5% rate (without ITC) applies. Swiggy and Zomato
          collect and deposit GST on restaurant services delivered through their platforms.
        </p>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>

        <h3>Is GST registration free?</h3>
        <p>
          Yes, registration on the official GST portal is completely free. There are no government fees.
          If you engage a CA or tax professional, they typically charge ₹1,000–₹5,000 depending on the
          complexity and business type.
        </p>

        <h3>How many days does GST registration take?</h3>
        <p>
          With Aadhaar authentication and complete documents, registration is usually granted within
          3–7 working days. If a query is raised by the officer, it may take up to 30 days. The deemed
          approval rule ensures registration within 21 days for non-risky applicants.
        </p>

        <h3>Can I get GST registration without a shop?</h3>
        <p>
          Yes. You can use your residential address as the principal place of business. Provide valid
          address proof like an electricity bill, rent agreement, or property tax receipt. Many
          freelancers, consultants, and home-based businesses register this way.
        </p>

        <h3>What happens if I don&apos;t register for GST?</h3>
        <p>
          Operating without registration when required attracts a penalty of 10% of the tax due
          (minimum ₹10,000). For deliberate evasion, the penalty can be 100% of the tax due. You also
          lose the ability to claim ITC and sell on e-commerce platforms.
        </p>

        <h3>Can I have multiple GST registrations?</h3>
        <p>
          You need a separate GSTIN for each state where you have a place of business. Within a
          single state, you can also obtain additional registrations for different business verticals
          under section 25(2).
        </p>

        <h3>Is Aadhaar mandatory for GST registration?</h3>
        <p>
          Aadhaar authentication is mandatory for proprietors, individual partners, and karta of HUF.
          Companies and LLPs use DSC instead. Without Aadhaar authentication, the application goes through
          physical verification, which takes longer.
        </p>
      </section>

      <section>
        <h2>Free Tools for GST Registration</h2>
        <p>Use these DoAide GST tools to make registration and compliance easier:</p>
        <ul>
          <li><Link to="/turnover-limit">Turnover Limit Checker</Link> — check if registration is mandatory</li>
          <li><Link to="/registration-checker">Registration Status Checker</Link> — verify registration status</li>
          <li><Link to="/gstin-validator">GSTIN Validator</Link> — validate any GSTIN format</li>
          <li><Link to="/hsn-sac-finder">HSN/SAC Finder</Link> — find the right codes for your products/services</li>
          <li><Link to="/scheme-comparison">Scheme Comparison</Link> — compare Regular vs Composition scheme</li>
          <li><Link to="/calculator">GST Calculator</Link> — calculate GST on your products</li>
        </ul>
        <p>
          <Link to="/">Start using DoAide GST free →</Link>
        </p>
      </section>
    </article>
  );
}
