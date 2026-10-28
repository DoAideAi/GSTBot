import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ErrorBanner from "./ErrorBanner";

describe("ErrorBanner", () => {
  it("renders nothing at all when there is no message", () => {
    // Not an empty banner: every page mounts this unconditionally and passes
    // whatever its error state holds, so the no-error case is the common one
    // and it must not leave an announced-but-empty alert in the tree.
    const { container } = render(<ErrorBanner message="" />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("announces the message as an alert", () => {
    render(<ErrorBanner message="GSTIN check digit does not match" />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "GSTIN check digit does not match",
    );
  });

  it("offers no dismiss button when the caller cannot clear the error", () => {
    // A button that does nothing is worse than no button: it says the error
    // is dismissible and then leaves it on screen.
    render(<ErrorBanner message="Upload failed" />);
    expect(screen.queryByRole("button", { name: "Dismiss" })).not.toBeInTheDocument();
  });

  it("calls back when the dismiss button is clicked", async () => {
    // Every page wires this to `() => setError("")`. The handler had no test
    // clicking it anywhere in the suite, so a banner that could be shown but
    // never cleared would have shipped green.
    const onDismiss = vi.fn();
    render(<ErrorBanner message="Upload failed" onDismiss={onDismiss} />);

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("does not submit the form it may be sitting inside", async () => {
    // The banner renders inside the filing and upload forms. A button with no
    // explicit type defaults to submit, which would make dismissing an error
    // re-fire the request that produced it.
    const onSubmit = vi.fn((event) => event.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <ErrorBanner message="Upload failed" onDismiss={() => {}} />
      </form>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("offers the plans when the refusal is the paid tier's", () => {
    render(
      <ErrorBanner message="This feature requires a paid subscription. Visit /pricing to upgrade." />,
    );
    expect(screen.getByRole("link", { name: "See plans" })).toHaveAttribute("href", "/pricing");
  });

  it("offers no plans for any other refusal", () => {
    render(<ErrorBanner message="You do not have access to this (403)." />);
    expect(screen.queryByRole("link", { name: "See plans" })).not.toBeInTheDocument();
  });
});
