// A page's visible FAQ and its FAQPage structured data from one list. Google
// only honours FAQ markup whose questions are on the page, so building both
// from the same array keeps them from drifting apart.

/** FAQPage JSON-LD for a list of { q, a } pairs. */
export function faqSchema(faqs) {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };
}

export default function FaqSection({ faqs, children }) {
  return (
    <section className="tool-info">
      <h2>Frequently Asked Questions</h2>
      {faqs.map((f) => (
        <div key={f.q}>
          <h3>{f.q}</h3>
          <p>{f.a}</p>
        </div>
      ))}
      {children}
    </section>
  );
}
