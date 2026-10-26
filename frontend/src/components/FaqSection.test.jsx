import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FaqSection, { faqSchema } from "./FaqSection";

const FAQS = [
  { q: "What is GST?", a: "A tax on supply." },
  { q: "Who pays it?", a: "The final consumer." },
];

describe("faqSchema", () => {
  it("maps each pair to a Question with an accepted Answer", () => {
    const schema = faqSchema(FAQS);
    expect(schema["@type"]).toBe("FAQPage");
    expect(schema.mainEntity).toEqual([
      { "@type": "Question", name: "What is GST?", acceptedAnswer: { "@type": "Answer", text: "A tax on supply." } },
      { "@type": "Question", name: "Who pays it?", acceptedAnswer: { "@type": "Answer", text: "The final consumer." } },
    ]);
  });
});

describe("FaqSection", () => {
  it("renders every question and answer, then any extra content", () => {
    render(<FaqSection faqs={FAQS}><p>More reading</p></FaqSection>);
    expect(screen.getByRole("heading", { name: "Frequently Asked Questions" })).toBeInTheDocument();
    for (const f of FAQS) {
      expect(screen.getByRole("heading", { name: f.q })).toBeInTheDocument();
      expect(screen.getByText(f.a)).toBeInTheDocument();
    }
    expect(screen.getByText("More reading")).toBeInTheDocument();
  });
});
