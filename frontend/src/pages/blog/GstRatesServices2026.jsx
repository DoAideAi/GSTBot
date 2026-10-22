import { useEffect } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../../hooks/usePageTitle";

export default function GstRatesServices2026() {
  usePageTitle("GST Rates for Services 2026 — Complete Rate List with SAC Codes");

  useEffect(() => {
    const meta = document.querySelector('meta[name="description"]');
    if (meta) meta.content = "Complete list of GST rates for services in India 2026. SAC codes and rates for IT, consulting, transport, healthcare, education, restaurants, real estate, and more.";

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
        headline: "GST Rates for Services 2026 — Complete Rate List with SAC Codes",
        description: "Complete list of GST rates for all services in India 2026 with SAC codes. Covers IT, consulting, transport, healthcare, education, restaurants, hotels, and professional services.",
        url: "https://gst.doaide.com/blog/gst-rates-services-2026",
        datePublished: "2026-10-08",
        dateModified: "2026-10-08",
        publisher: { "@type": "Organization", name: "DoAide" },
      },
      {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: [
          { "@type": "Question", name: "What is the GST rate for IT services?", acceptedAnswer: { "@type": "Answer", text: "IT services — software and web development, cloud computing, SaaS and IT consulting — attract 18% GST under SAC 998311-998316. Export of IT services to clients outside India is zero-rated with ITC." } },
          { "@type": "Question", name: "Are healthcare services exempt from GST?", acceptedAnswer: { "@type": "Answer", text: "Services by clinical establishments, authorized medical practitioners and paramedics are exempt, and so are health insurance premiums under GST 2.0. Cosmetic surgery (unless reconstructive) attracts 18% GST." } },
          { "@type": "Question", name: "What is the GST rate on restaurant food?", acceptedAnswer: { "@type": "Answer", text: "Standalone restaurants, cloud kitchens and food delivery apps charge 5% without ITC. Restaurants in hotels with room tariff above ₹7,500 charge 18% with ITC, and outdoor catering is 18% with ITC." } },
          { "@type": "Question", name: "Is GST applicable on rent?", acceptedAnswer: { "@type": "Answer", text: "Residential rent to an unregistered individual is exempt; a registered tenant pays 18% under reverse charge. Commercial rent attracts 18%. Hotel rooms: exempt up to ₹1,000/night, 5% to ₹7,500, 18% above." } },
          { "@type": "Question", name: "What is the GST on professional services like CA, lawyer, architect?", acceptedAnswer: { "@type": "Answer", text: "Chartered accountants, lawyers, architects, engineers and management consultants charge 18% GST. Services by an individual advocate to a business fall under reverse charge — the recipient pays the tax." } },
        ],
      },
    ]);
    return () => { if (script.parentNode) script.parentNode.removeChild(script); };
  }, []);

  return (
    <article className="blog-article">
      <h1>GST Rates for Services 2026 — Complete Rate List with SAC Codes</h1>
      <p className="blog-meta">Updated October 2026 · 14 min read</p>

      <section>
        <p>
          Services account for over 55% of India&apos;s GDP, and GST on services affects millions of
          businesses — from freelance consultants and restaurants to IT companies and hospitals.
          Unlike goods (classified by HSN codes), services are classified using SAC (Services Accounting
          Codes). This guide provides the complete GST rate list for services in 2026, organized by
          sector, with SAC codes and ITC eligibility details.
        </p>
        <p>
          Find the exact SAC code and rate for any service using our{" "}
          <Link to="/hsn-sac-finder">HSN/SAC Finder</Link>.
        </p>
      </section>

      <section>
        <h2>Understanding SAC Codes</h2>
        <p>
          SAC (Services Accounting Code) is a 6-digit code used to classify services under GST.
          All SAC codes start with &quot;99&quot;. The structure is:
        </p>
        <ul>
          <li><strong>First 2 digits (99):</strong> Identifies it as a service</li>
          <li><strong>Next 2 digits:</strong> Service group (e.g., 9983 = IT services)</li>
          <li><strong>Last 2 digits:</strong> Specific service type (e.g., 998311 = Management consulting)</li>
        </ul>
        <p>
          SAC codes must be mentioned on tax invoices for services. For businesses with turnover
          above ₹5 crore, the full 6-digit code is mandatory.
        </p>
      </section>

      <section>
        <h2>GST Rates for IT and Technology Services</h2>
        <ul>
          <li><strong>Software development (998314):</strong> 18%</li>
          <li><strong>Web development and hosting (998315):</strong> 18%</li>
          <li><strong>IT consulting (998311):</strong> 18%</li>
          <li><strong>Cloud computing / SaaS (998316):</strong> 18%</li>
          <li><strong>Data processing (998313):</strong> 18%</li>
          <li><strong>Hardware maintenance (998512):</strong> 18%</li>
          <li><strong>Cybersecurity services (998316):</strong> 18%</li>
          <li><strong>IT training and education (999293):</strong> 18%</li>
        </ul>
        <p>
          <strong>Export note:</strong> IT services exported to clients outside India qualify for zero-rating
          (0% GST with full ITC). The service must be provided to a recipient located outside India,
          and payment must be received in convertible foreign exchange.
        </p>
      </section>

      <section>
        <h2>GST Rates for Professional Services</h2>
        <ul>
          <li><strong>Management consulting (998311):</strong> 18%</li>
          <li><strong>CA / Auditing services (998221):</strong> 18%</li>
          <li><strong>Legal services by firms (998211):</strong> 18%</li>
          <li><strong>Legal services by individual advocate:</strong> 18% under Reverse Charge Mechanism (RCM) — the business client pays the GST</li>
          <li><strong>Architectural services (998321):</strong> 18%</li>
          <li><strong>Engineering services (998322):</strong> 18%</li>
          <li><strong>Scientific research (998311):</strong> 18%</li>
          <li><strong>Advertising services (998361):</strong> 18%</li>
          <li><strong>Market research (998362):</strong> 18%</li>
          <li><strong>HR and recruitment (998351):</strong> 18%</li>
          <li><strong>Event management (999592):</strong> 18%</li>
        </ul>
      </section>

      <section>
        <h2>GST Rates for Financial Services</h2>
        <ul>
          <li><strong>Banking services (997111):</strong> 18%</li>
          <li><strong>Insurance — life (997132):</strong> 18% on the premium component (not on the savings portion of endowment plans)</li>
          <li><strong>Insurance — health (997133):</strong> 18%</li>
          <li><strong>Insurance — motor (997134):</strong> 18%</li>
          <li><strong>Stock broking (997112):</strong> 18%</li>
          <li><strong>Mutual fund management (997113):</strong> 18%</li>
          <li><strong>Credit card services (997113):</strong> 18%</li>
          <li><strong>Payment gateway (997113):</strong> 18%</li>
          <li><strong>Foreign exchange (997113):</strong> 18% on the margin/commission</li>
        </ul>
        <p>
          Use our <Link to="/calculator">GST Calculator</Link> to compute GST on financial service charges.
        </p>
      </section>

      <section>
        <h2>GST Rates for Transport and Logistics</h2>
        <ul>
          <li><strong>Goods transport by road (GTA) (996511):</strong> 5% without ITC or 12% with ITC (at GTA&apos;s option)</li>
          <li><strong>Rail freight (996512):</strong> 5%</li>
          <li><strong>Air freight (996521):</strong> 18%</li>
          <li><strong>Sea freight — coastal (996522):</strong> 5%</li>
          <li><strong>Sea freight — international (996522):</strong> exempt (import), 18% (export, but zero-rated)</li>
          <li><strong>Courier and parcel (996812):</strong> 18%</li>
          <li><strong>Warehousing — agricultural (996721):</strong> exempt</li>
          <li><strong>Warehousing — other (996729):</strong> 18%</li>
          <li><strong>Bus transport (AC) (996411):</strong> 5%</li>
          <li><strong>Cab/taxi (radio taxi, app-based) (996413):</strong> 5% without ITC</li>
          <li><strong>Auto-rickshaw (app-based) (996413):</strong> 5%</li>
          <li><strong>Air travel — economy (996411):</strong> 5%</li>
          <li><strong>Air travel — business class (996411):</strong> 12%</li>
        </ul>
      </section>

      <section>
        <h2>GST Rates for Restaurant and Food Services</h2>
        <ul>
          <li><strong>Restaurant — non-AC, no alcohol (996331):</strong> 5% without ITC</li>
          <li><strong>Restaurant — AC, with/without alcohol (996331):</strong> 5% without ITC</li>
          <li><strong>Restaurant in hotel (room tariff ≤₹7,500/night) (996331):</strong> 5% without ITC</li>
          <li><strong>Restaurant in hotel (room tariff &gt;₹7,500/night) (996331):</strong> 18% with ITC</li>
          <li><strong>Outdoor catering (996333):</strong> 18% with ITC</li>
          <li><strong>Cloud kitchen / food delivery (996333):</strong> 5% without ITC (collected by delivery platform)</li>
          <li><strong>Indian Railways catering (996334):</strong> 5% without ITC</li>
          <li><strong>Canteen in educational/office (996334):</strong> 5% without ITC</li>
        </ul>
      </section>

      <section>
        <h2>GST Rates for Real Estate Services</h2>
        <ul>
          <li><strong>Under-construction flats — affordable (997211):</strong> 1% without ITC (value up to ₹45 lakh, carpet area ≤60 sqm metro / ≤90 sqm non-metro)</li>
          <li><strong>Under-construction flats — other (997211):</strong> 5% without ITC</li>
          <li><strong>Ready-to-move-in flats (with OC):</strong> exempt</li>
          <li><strong>Commercial property rent (997212):</strong> 18%</li>
          <li><strong>Residential rent (by registered person) (997212):</strong> 18% under RCM</li>
          <li><strong>Residential rent (to unregistered person) (997212):</strong> exempt</li>
          <li><strong>Hotel room (≤₹1,000/night) (997211):</strong> exempt</li>
          <li><strong>Hotel room (₹1,001–₹7,500/night) (997211):</strong> 12%</li>
          <li><strong>Hotel room (&gt;₹7,500/night) (997211):</strong> 18%</li>
          <li><strong>Real estate agent commission (997212):</strong> 18%</li>
        </ul>
      </section>

      <section>
        <h2>GST Rates for Construction Services</h2>
        <ul>
          <li><strong>General construction — commercial (995411):</strong> 18%</li>
          <li><strong>General construction — residential (affordable) (995411):</strong> 1% without ITC</li>
          <li><strong>General construction — residential (other) (995411):</strong> 5% without ITC</li>
          <li><strong>Works contract — government (995421):</strong> 12%</li>
          <li><strong>Works contract — private (995421):</strong> 18%</li>
          <li><strong>Pure labour contract (construction) (995421):</strong> 18%</li>
          <li><strong>Interior decoration (995461):</strong> 18%</li>
          <li><strong>Plumbing, electrical (995441):</strong> 18%</li>
        </ul>
      </section>

      <section>
        <h2>GST Rates for Healthcare Services</h2>
        <ul>
          <li><strong>Clinical establishment services (999311):</strong> exempt</li>
          <li><strong>Doctor / medical practitioner (999312):</strong> exempt</li>
          <li><strong>Paramedical services (999313):</strong> exempt</li>
          <li><strong>Ambulance services (999314):</strong> exempt</li>
          <li><strong>Hospital room (≤₹5,000/day) (999311):</strong> exempt</li>
          <li><strong>Hospital room (&gt;₹5,000/day) (999311):</strong> 5% without ITC</li>
          <li><strong>Cosmetic/plastic surgery (non-reconstructive) (999312):</strong> 18%</li>
          <li><strong>Diagnostic labs (999315):</strong> exempt</li>
          <li><strong>Telemedicine consultations (999312):</strong> exempt</li>
          <li><strong>Veterinary services (999319):</strong> exempt</li>
          <li><strong>Health insurance (997133):</strong> 18%</li>
        </ul>
      </section>

      <section>
        <h2>GST Rates for Education Services</h2>
        <ul>
          <li><strong>School education (999210):</strong> exempt</li>
          <li><strong>Higher education by recognized institution (999210):</strong> exempt</li>
          <li><strong>Coaching and tutoring (999293):</strong> 18%</li>
          <li><strong>Vocational training (approved by NSDC) (999292):</strong> exempt</li>
          <li><strong>Online courses / EdTech (999293):</strong> 18%</li>
          <li><strong>Foreign university degrees in India (999293):</strong> 18%</li>
          <li><strong>School transport (996411):</strong> exempt</li>
          <li><strong>Hostel (educational institution) (997212):</strong> exempt (up to ₹15,000/month per student)</li>
        </ul>
      </section>

      <section>
        <h2>GST Rates for Entertainment and Media</h2>
        <ul>
          <li><strong>Cinema tickets (≤₹100) (999611):</strong> 12%</li>
          <li><strong>Cinema tickets (&gt;₹100) (999611):</strong> 18%</li>
          <li><strong>OTT streaming (Netflix, Hotstar) (998432):</strong> 18%</li>
          <li><strong>Amusement parks (999611):</strong> 18%</li>
          <li><strong>Sporting events (999611):</strong> 28%</li>
          <li><strong>Casino, gambling (999611):</strong> 28% on full value of bets</li>
          <li><strong>Online gaming (real money) (999611):</strong> 28% on full value of bets</li>
          <li><strong>Gym / fitness (999594):</strong> 18%</li>
          <li><strong>Newspaper printing (998912):</strong> 5%</li>
        </ul>
      </section>

      <section>
        <h2>Exempt Services (0% GST)</h2>
        <p>These services are fully exempt from GST:</p>
        <ul>
          <li>Healthcare by hospitals and clinics</li>
          <li>Education by schools and recognized institutions</li>
          <li>Agricultural services (cultivation, harvesting, rearing)</li>
          <li>Public transport by non-AC buses, metro, local trains</li>
          <li>Religious pilgrimages (Haj, Kailash Mansarovar by government)</li>
          <li>Services by government and local authorities (most)</li>
          <li>Funeral, burial, cremation services</li>
          <li>Services by RBI, SEBI, IRDA</li>
          <li>Legal services by individual advocate to individual (non-business)</li>
          <li>Residential rent to unregistered persons</li>
        </ul>
      </section>

      <section>
        <h2>Reverse Charge Mechanism (RCM) on Services</h2>
        <p>
          For certain services, the recipient pays the GST instead of the supplier:
        </p>
        <ul>
          <li><strong>Legal services by individual advocate:</strong> Business recipient pays 18%</li>
          <li><strong>Security services (manpower supply):</strong> Registered recipient pays 18%</li>
          <li><strong>GTA services:</strong> If GTA doesn&apos;t charge GST, recipient pays 5% under RCM</li>
          <li><strong>Director&apos;s fees / sitting fees:</strong> Company pays 18% under RCM</li>
          <li><strong>Rent of residential property:</strong> Registered tenant pays 18% under RCM</li>
          <li><strong>Import of services:</strong> Indian recipient pays applicable GST under RCM</li>
        </ul>
        <p>
          Calculate RCM liability with our <Link to="/rcm-calculator">RCM Calculator</Link>.
        </p>
      </section>

      <section>
        <h2>Frequently Asked Questions</h2>

        <h3>What is the GST rate for IT services?</h3>
        <p>
          All IT services — software development, web hosting, cloud computing, SaaS, consulting — attract
          18% GST. Exports of IT services are zero-rated (0% with ITC) when the recipient is outside India
          and payment is in convertible foreign exchange.
        </p>

        <h3>Are healthcare services exempt from GST?</h3>
        <p>
          Clinical services by hospitals, doctors, and paramedics are exempt. However, cosmetic surgery
          (non-reconstructive), hospital rooms above ₹5,000/day, and health insurance attract GST. Diagnostic
          labs and telemedicine are exempt.
        </p>

        <h3>What is the GST rate on restaurant food?</h3>
        <p>
          Most restaurants charge 5% GST without ITC, regardless of whether they are AC or non-AC.
          The exception is restaurants in hotels with room tariff above ₹7,500/night (18% with ITC)
          and outdoor catering services (18% with ITC).
        </p>

        <h3>Is GST applicable on rent?</h3>
        <p>
          Residential rent to unregistered individuals is exempt. If the tenant is GST-registered, 18%
          applies under reverse charge. Commercial rent always attracts 18%. Hotel rooms vary by tariff:
          exempt (≤₹1,000), 12% (₹1,001–₹7,500), 18% (&gt;₹7,500).
        </p>

        <h3>What is the GST on professional services?</h3>
        <p>
          CA, architect, engineer, and consulting services attract 18%. Legal services by an individual
          advocate to a business attract 18% under reverse charge (the business pays). Legal services
          to individuals are exempt.
        </p>
      </section>

      <section>
        <h2>Free Tools for Service Providers</h2>
        <ul>
          <li><Link to="/hsn-sac-finder">HSN/SAC Finder</Link> — find SAC codes for any service</li>
          <li><Link to="/calculator">GST Calculator</Link> — calculate GST on service charges</li>
          <li><Link to="/rcm-calculator">RCM Calculator</Link> — compute reverse charge liability</li>
          <li><Link to="/invoice-generator">Invoice Generator</Link> — create service invoices with SAC codes</li>
          <li><Link to="/return-calendar">Return Calendar</Link> — track filing due dates</li>
        </ul>
        <p>
          <Link to="/">Start using DoAide GST free →</Link>
        </p>
      </section>
    </article>
  );
}
