import { useState } from "react";
import { Link } from "react-router-dom";
import { usePageTitle } from "../hooks/usePageTitle";
import DoAideFooter from "../components/DoAideFooter";
import SeoHead from "../components/SeoHead";

const COMMANDS = [
  {
    title: "GST Rate Lookup",
    icon: "💰",
    description: "Check GST rate for any product or service",
    examples: ["laptop", "GST rate for mobile phone", "restaurant"],
    response: "Returns the applicable GST rate, HSN/SAC code, and CGST/SGST/IGST split.",
  },
  {
    title: "GSTIN Verification",
    icon: "🔍",
    description: "Validate any 15-digit GSTIN number",
    examples: ["27AAPFU0939F1ZV", "Verify 29AADCT1234Q1ZV"],
    response: "Checks the format, check digit, and shows state, PAN, and entity details.",
  },
  {
    title: "HSN/SAC Code Finder",
    icon: "📋",
    description: "Look up HSN or SAC codes for products and services",
    examples: ["HSN code for cotton fabric", "SAC code for consulting"],
    response: "Returns matching HSN/SAC codes with descriptions and GST rates.",
  },
  {
    title: "GST Calculator",
    icon: "💱",
    description: "Calculate GST on any amount at any rate",
    examples: ["Calculate 50000 at 18%", "25000 @ 12% GST"],
    response: "Shows taxable amount, CGST, SGST, IGST, and total with tax.",
  },
];

// Set at build time once the bot has a real number. This used to be the
// placeholder +919999999999, so "Start Chatting" opened a chat with a stranger
// (or nobody). Without a number the page says the bot is coming and sends the
// reader to the same lookups on the web instead of to a dead end.
const WHATSAPP_NUMBER = (import.meta.env.VITE_WHATSAPP_NUMBER || "").trim();
const WHATSAPP_LINK = WHATSAPP_NUMBER
  ? `https://wa.me/${WHATSAPP_NUMBER.replace(/\D/g, "")}?text=hi`
  : "";

function QRPlaceholder() {
  return (
    <div
      style={{
        width: 200,
        height: 200,
        border: "2px dashed var(--border-color, #d1d5db)",
        borderRadius: 12,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
        gap: 8,
        color: "var(--text-muted, #6b7280)",
        fontSize: 13,
        textAlign: "center",
        padding: 16,
      }}
    >
      <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="4" height="4" rx="0.5" />
        <line x1="21" y1="14" x2="21" y2="21" />
        <line x1="14" y1="21" x2="21" y2="21" />
      </svg>
      <span>Scan QR code<br />to start chatting</span>
    </div>
  );
}

export default function WhatsAppPage() {
  usePageTitle("WhatsApp Bot — GSTIndia by DoAide");
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(WHATSAPP_NUMBER).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }).catch(() => {});
  }

  return (
    <>
      <SeoHead
        title="WhatsApp GST Bot — Instant GST Rates, GSTIN Verification & Calculator"
        description="Get instant GST rates, verify GSTIN numbers, find HSN/SAC codes, and calculate GST — all on WhatsApp. Free GST bot by DoAide."
        path="/whatsapp"
      />
      <div className="landing-page" style={{ minHeight: "100vh" }}>
        <nav className="landing-nav">
          <Link to="/" className="landing-logo">
            <span className="landing-logo-icon" aria-hidden="true">
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
                <rect x="5" y="6" width="22" height="17" rx="5" fill="#F0B429" />
                <ellipse cx="11" cy="13" rx="2.5" ry="3" fill="#0A0A0B" />
                <ellipse cx="21" cy="13" rx="2.5" ry="3" fill="#0A0A0B" />
                <path d="M12 19Q16 22 20 19" stroke="#0A0A0B" strokeWidth="1.2" fill="none" strokeLinecap="round" />
              </svg>
            </span>
            GSTIndia
          </Link>
          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <Link to="/calculator" className="landing-nav-link">Calculator</Link>
            <Link to="/lookup" className="landing-nav-link">GSTIN Lookup</Link>
            <Link to="/hsn" className="landing-nav-link">HSN Finder</Link>
          </div>
        </nav>

        <section style={{ padding: "48px 20px", maxWidth: 900, margin: "0 auto", textAlign: "center" }}>
          <div style={{ display: "inline-flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
            <span style={{ fontSize: 48, lineHeight: 1 }}>
              <svg viewBox="0 0 24 24" width="48" height="48" fill="#25D366" aria-hidden="true">
                <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z" />
              </svg>
            </span>
            <h1 style={{ fontSize: 32, fontWeight: 700, margin: 0 }}>
              GSTIndia on WhatsApp
            </h1>
          </div>

          <p style={{ fontSize: 18, color: "var(--text-muted, #6b7280)", maxWidth: 600, margin: "0 auto 32px", lineHeight: 1.6 }}>
            Get instant GST rates, verify GSTIN numbers, find HSN/SAC codes, and calculate GST
            — all from WhatsApp. No app to install, no sign-up needed.
          </p>

          {WHATSAPP_NUMBER ? (
            <>
              <div style={{ display: "flex", gap: 16, justifyContent: "center", flexWrap: "wrap", marginBottom: 48 }}>
                <a
                  href={WHATSAPP_LINK}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn btn-primary"
                  style={{
                    background: "#25D366",
                    color: "#fff",
                    padding: "14px 28px",
                    borderRadius: 8,
                    fontWeight: 600,
                    fontSize: 16,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    textDecoration: "none",
                    border: "none",
                  }}
                >
                  <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor" aria-hidden="true">
                    <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z" />
                  </svg>
                  Start Chatting
                </a>
                <button
                  onClick={handleCopy}
                  className="btn"
                  style={{
                    padding: "14px 28px",
                    borderRadius: 8,
                    fontWeight: 600,
                    fontSize: 16,
                    cursor: "pointer",
                    border: "1px solid var(--border-color, #d1d5db)",
                    background: "var(--bg-surface, #fff)",
                    color: "var(--text-primary, #111)",
                  }}
                >
                  {copied ? "Copied!" : "Copy Number"}
                </button>
              </div>

              <QRPlaceholder />
            </>
          ) : (
            <div className="card" role="status" style={{ maxWidth: 560, margin: "0 auto 48px", padding: 24 }}>
              <p style={{ fontWeight: 600, fontSize: 18, margin: "0 0 8px" }}>
                The WhatsApp bot is launching soon.
              </p>
              <p style={{ color: "var(--text-muted, #6b7280)", margin: "0 0 16px" }}>
                Every lookup below already works on the web — free, with no sign-up.
              </p>
              <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
                <Link to="/calculator" className="btn btn-primary">GST Calculator</Link>
                <Link to="/lookup" className="btn">Verify a GSTIN</Link>
                <Link to="/hsn" className="btn">Find an HSN code</Link>
              </div>
            </div>
          )}
        </section>

        <section style={{ padding: "48px 20px", maxWidth: 900, margin: "0 auto" }}>
          <h2 style={{ fontSize: 24, fontWeight: 700, textAlign: "center", marginBottom: 32 }}>
            What You Can Do
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 24 }}>
            {COMMANDS.map((cmd) => (
              <div
                key={cmd.title}
                style={{
                  border: "1px solid var(--border-color, #e5e7eb)",
                  borderRadius: 12,
                  padding: 24,
                  background: "var(--bg-surface, #fff)",
                }}
              >
                <h3 style={{ fontSize: 18, fontWeight: 600, margin: "0 0 8px", display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 24 }}>{cmd.icon}</span>
                  {cmd.title}
                </h3>
                <p style={{ color: "var(--text-muted, #6b7280)", margin: "0 0 12px", fontSize: 14 }}>
                  {cmd.description}
                </p>
                <div style={{ marginBottom: 12 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted, #6b7280)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                    Try sending:
                  </span>
                  {cmd.examples.map((ex) => (
                    <div
                      key={ex}
                      style={{
                        background: "var(--bg-muted, #f3f4f6)",
                        borderRadius: 8,
                        padding: "6px 12px",
                        marginTop: 6,
                        fontSize: 14,
                        fontFamily: "monospace",
                      }}
                    >
                      {ex}
                    </div>
                  ))}
                </div>
                <p style={{ fontSize: 13, color: "var(--text-muted, #9ca3af)", margin: 0, fontStyle: "italic" }}>
                  {cmd.response}
                </p>
              </div>
            ))}
          </div>
        </section>

        <section style={{ padding: "48px 20px", maxWidth: 700, margin: "0 auto", textAlign: "center" }}>
          <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 16 }}>
            How It Works
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 24, textAlign: "left" }}>
            {[
              { step: "1", title: "Save our number", desc: WHATSAPP_NUMBER
                ? `Save ${WHATSAPP_NUMBER} to your contacts, or tap "Start Chatting" above.`
                : "Our number will be published here at launch." },
              { step: "2", title: "Send a message", desc: "Type your GST query — a product name, GSTIN, HSN code request, or calculation." },
              { step: "3", title: "Get instant answers", desc: "Receive formatted results with GST rates, verification details, or calculations within seconds." },
            ].map((item) => (
              <div key={item.step} style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: "50%",
                    background: "#25D366",
                    color: "#fff",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontWeight: 700,
                    fontSize: 16,
                    flexShrink: 0,
                  }}
                >
                  {item.step}
                </div>
                <div>
                  <h3 style={{ margin: "0 0 4px", fontSize: 16, fontWeight: 600 }}>{item.title}</h3>
                  <p style={{ margin: 0, color: "var(--text-muted, #6b7280)", fontSize: 14 }}>{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section style={{ padding: "32px 20px 48px", maxWidth: 700, margin: "0 auto", textAlign: "center" }}>
          <p style={{ color: "var(--text-muted, #6b7280)", fontSize: 14 }}>
            Also available on the web:&ensp;
            <Link to="/calculator">GST Calculator</Link>&ensp;|&ensp;
            <Link to="/lookup">GSTIN Lookup</Link>&ensp;|&ensp;
            <Link to="/hsn-sac-finder">HSN/SAC Finder</Link>&ensp;|&ensp;
            <Link to="/due-dates">Due Dates</Link>
          </p>
        </section>

        <DoAideFooter />
      </div>
    </>
  );
}
