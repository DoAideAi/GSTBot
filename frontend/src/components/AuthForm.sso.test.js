import { describe, expect, it } from "vitest";
import { ssoErrorMessage } from "./AuthForm";

describe("ssoErrorMessage", () => {
  it("names the provider that failed", () => {
    expect(ssoErrorMessage("github_auth_failed")).toMatch(/^Signing in with GitHub did not complete/);
    expect(ssoErrorMessage("microsoft_auth_failed")).toMatch(/Microsoft could not be reached/);
  });

  it("explains each refusal the callbacks send", () => {
    expect(ssoErrorMessage("no_email")).toMatch(/did not share an email/);
    expect(ssoErrorMessage("account_deactivated")).toMatch(/sign in with your email and password/);
  });

  it("is empty without a code and generic for an unknown one", () => {
    expect(ssoErrorMessage(null)).toBe("");
    expect(ssoErrorMessage("<script>")).toMatch(/^Single sign-on did not complete/);
  });
});
