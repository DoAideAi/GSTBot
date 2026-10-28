import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StubAuth } from "../test/auth";
import ReportPurchaseButton from "./ReportPurchaseButton";

const api = vi.hoisted(() => ({
  purchaseReport: vi.fn(),
  verifyReportPayment: vi.fn(),
  downloadReport: vi.fn(),
}));
const razorpay = vi.hoisted(() => ({ loadRazorpay: vi.fn(), payWithRazorpay: vi.fn() }));

vi.mock("../lib/api", () => ({ api }));
vi.mock("../lib/razorpay", () => razorpay);
vi.mock("../lib/track", () => ({ track: vi.fn() }));

const ORDER = {
  run_id: 7,
  already_purchased: false,
  order_id: "order_rpt",
  amount: 9900,
  currency: "INR",
  razorpay_key_id: "rzp_test_publishable",
};
const PAYMENT = {
  razorpay_order_id: "order_rpt",
  razorpay_payment_id: "pay_rpt",
  razorpay_signature: "sig",
};
const FILE = { blob: new Blob(["%PDF"]), filename: "reconciliation-2026-04-run7.pdf" };

function renderButton({ user } = {}) {
  return render(
    <StubAuth user={user}>
      <ReportPurchaseButton runId={7} />
    </StubAuth>,
  );
}

// The action, not the error banner's "Dismiss", which appears beside it.
const button = () => screen.getByRole("button", { name: (name) => name !== "Dismiss" });

beforeEach(() => {
  api.purchaseReport.mockResolvedValue(ORDER);
  api.verifyReportPayment.mockResolvedValue({ run_id: 7, purchased: true });
  api.downloadReport.mockResolvedValue(FILE);
  razorpay.loadRazorpay.mockResolvedValue(true);
  razorpay.payWithRazorpay.mockResolvedValue(PAYMENT);
  URL.createObjectURL = vi.fn(() => "blob:report");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ReportPurchaseButton", () => {
  it("offers the report at its price before it is bought", () => {
    renderButton();
    expect(button()).toHaveTextContent("Download PDF Report — ₹99");
  });

  it("pays, verifies that payment, then downloads the file", async () => {
    renderButton();
    await userEvent.click(button());

    await waitFor(() => expect(api.downloadReport).toHaveBeenCalledWith(7));
    expect(razorpay.payWithRazorpay).toHaveBeenCalledWith(
      expect.objectContaining({ key: "rzp_test_publishable", order_id: "order_rpt", amount: 9900 }),
    );
    expect(api.verifyReportPayment).toHaveBeenCalledWith({ run_id: 7, ...PAYMENT });
    expect(URL.createObjectURL).toHaveBeenCalledWith(FILE.blob);
    expect(button()).toHaveTextContent("Download PDF report");
    expect(button()).not.toHaveTextContent("₹99");
  });

  it("prefills checkout with the signed-in user", async () => {
    renderButton({ user: { email: "asha@example.com", full_name: "Asha Rao" } });
    await userEvent.click(button());

    await waitFor(() => expect(razorpay.payWithRazorpay).toHaveBeenCalled());
    expect(razorpay.payWithRazorpay.mock.calls[0][0].prefill).toEqual({
      email: "asha@example.com",
      name: "Asha Rao",
    });
  });

  it("leaves the email blank in checkout when the session has none", async () => {
    renderButton({ user: { email: null } });
    await userEvent.click(button());

    await waitFor(() => expect(razorpay.payWithRazorpay).toHaveBeenCalled());
    expect(razorpay.payWithRazorpay.mock.calls[0][0].prefill.email).toBe("");
  });

  it("starts one purchase for a double click, not two", async () => {
    renderButton();
    const target = button();
    fireEvent.click(target);
    fireEvent.click(target);

    await waitFor(() => expect(api.downloadReport).toHaveBeenCalled());
    expect(api.purchaseReport).toHaveBeenCalledTimes(1);
    expect(razorpay.payWithRazorpay).toHaveBeenCalledTimes(1);
  });

  it("downloads a report already paid for without opening checkout", async () => {
    api.purchaseReport.mockResolvedValue({ run_id: 7, already_purchased: true });
    renderButton();
    await userEvent.click(button());

    await waitFor(() => expect(api.downloadReport).toHaveBeenCalledWith(7));
    expect(razorpay.payWithRazorpay).not.toHaveBeenCalled();
    expect(api.verifyReportPayment).not.toHaveBeenCalled();
  });

  it("does nothing more, and says nothing, when checkout is closed without paying", async () => {
    razorpay.payWithRazorpay.mockResolvedValue(null);
    renderButton();
    await userEvent.click(button());

    await waitFor(() => expect(button()).not.toBeDisabled());
    expect(api.verifyReportPayment).not.toHaveBeenCalled();
    expect(api.downloadReport).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(button()).toHaveTextContent("₹99");
  });

  it("retries a payment whose verification failed rather than charging again", async () => {
    api.verifyReportPayment
      .mockRejectedValueOnce(new Error("Could not confirm the payment"))
      .mockResolvedValueOnce({ run_id: 7, purchased: true });
    renderButton();

    await userEvent.click(button());
    expect(await screen.findByText(/Could not confirm the payment/)).toBeInTheDocument();
    expect(button()).toHaveTextContent("Retry confirming payment");

    await userEvent.click(button());
    await waitFor(() => expect(api.downloadReport).toHaveBeenCalled());
    expect(api.purchaseReport).toHaveBeenCalledTimes(1);
    expect(razorpay.payWithRazorpay).toHaveBeenCalledTimes(1);
    expect(api.verifyReportPayment).toHaveBeenLastCalledWith({ run_id: 7, ...PAYMENT });
  });

  it("says the payment is safe when the download fails, and downloads again for free", async () => {
    api.downloadReport.mockRejectedValueOnce(new Error("Network error"));
    renderButton();

    await userEvent.click(button());
    expect(
      await screen.findByText(/payment went through.*you will not be charged again/),
    ).toBeInTheDocument();
    expect(button()).toHaveTextContent("Download PDF report");

    await userEvent.click(button());
    await waitFor(() => expect(api.downloadReport).toHaveBeenCalledTimes(2));
    expect(api.purchaseReport).toHaveBeenCalledTimes(1);
  });

  it("lets the error be dismissed", async () => {
    razorpay.loadRazorpay.mockResolvedValue(false);
    renderButton();
    await userEvent.click(button());
    await screen.findByText(/Could not load the payment window/);

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByText(/Could not load the payment window/)).toBeNull();
  });

  it("explains when the payment window cannot be loaded", async () => {
    razorpay.loadRazorpay.mockResolvedValue(false);
    renderButton();
    await userEvent.click(button());

    expect(await screen.findByText(/Could not load the payment window/)).toBeInTheDocument();
    expect(razorpay.payWithRazorpay).not.toHaveBeenCalled();
  });

  it("shows the refusal when an order cannot be created", async () => {
    api.purchaseReport.mockRejectedValue(new Error("Payment processing is not configured."));
    renderButton();
    await userEvent.click(button());

    expect(await screen.findByText("Payment processing is not configured.")).toBeInTheDocument();
  });
});
