import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SocialProof from "./SocialProof";

describe("SocialProof", () => {
  it("shows a usage count for the named tool", () => {
    render(<SocialProof toolName="GST Calculator" />);
    expect(screen.getByText(/people used GST Calculator today/)).toBeInTheDocument();
  });

  it("falls back to a generic tool name", () => {
    render(<SocialProof />);
    expect(screen.getByText(/people used this tool today/)).toBeInTheDocument();
    expect(screen.getByText(/No login required/)).toBeInTheDocument();
  });
});
