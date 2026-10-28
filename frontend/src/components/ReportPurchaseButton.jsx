import { useRef, useState } from "react";
import ErrorBanner from "./ErrorBanner";
import { useAuth } from "../hooks/useAuth";
import { api } from "../lib/api";
import { loadRazorpay, payWithRazorpay } from "../lib/razorpay";
import { track } from "../lib/track";

/** Save a fetched blob to the user's disk under the server's filename. */
function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

const BUSY_LABELS = {
  paying: "Opening payment…",
  verifying: "Confirming payment…",
  downloading: "Preparing PDF…",
};

/**
 * Buy, then download, the PDF report of one reconciliation run.
 *
 * One button for both because the backend decides which this is: a run the
 * business has already paid for comes back as `already_purchased` and goes
 * straight to the download, so the same click never charges twice.
 */
export default function ReportPurchaseButton({ runId }) {
  const { user } = useAuth();
  const [busy, setBusy] = useState(null);
  const [purchased, setPurchased] = useState(false);
  // A payment Checkout reported but the backend has not yet accepted. Kept so
  // that pressing the button again after a failed verification retries *this*
  // payment instead of opening a new order and charging a second time.
  const [unverified, setUnverified] = useState(null);
  const [error, setError] = useState("");
  // Set synchronously, unlike `busy`: a double click delivers both events to
  // handlers closed over the same render, so a state check lets the second
  // through and opens a second order.
  const inFlight = useRef(false);

  async function download() {
    setBusy("downloading");
    try {
      const { blob, filename } = await api.downloadReport(runId);
      saveBlob(blob, filename);
      track("report_download", { run_id: runId });
    } catch (err) {
      // Said in terms of the money, because that is what the reader is
      // worried about the moment a paid download fails.
      setError(
        `Your payment went through, but the PDF did not download (${err.message}). ` +
          "Press the button again — you will not be charged again.",
      );
    }
  }

  async function handleClick() {
    if (inFlight.current) return;
    inFlight.current = true;
    setError("");
    setBusy("paying");
    try {
      if (!purchased) {
        let payment = unverified;
        if (!payment) {
          const order = await api.purchaseReport(runId);
          if (!order.already_purchased) {
            if (!(await loadRazorpay())) {
              setError("Could not load the payment window. Check your connection and try again.");
              return;
            }
            track("report_checkout_open", { run_id: runId });
            payment = await payWithRazorpay({
              key: order.razorpay_key_id,
              amount: order.amount,
              currency: order.currency,
              order_id: order.order_id,
              name: "DoAide GST",
              description: "GSTR-2B reconciliation report (PDF)",
              prefill: { email: user?.email || "", name: user?.full_name || "" },
              theme: { color: "#F0B429" },
            });
            if (!payment) return;
            setUnverified(payment);
          }
        }
        if (payment) {
          setBusy("verifying");
          await api.verifyReportPayment({ run_id: runId, ...payment });
          setUnverified(null);
          track("report_purchase", { run_id: runId });
        }
        setPurchased(true);
      }
      await download();
    } catch (err) {
      setError(err.message);
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  }

  return (
    <div className="report-purchase">
      <ErrorBanner message={error} onDismiss={() => setError("")} />
      <button
        type="button"
        className="btn btn-primary"
        onClick={handleClick}
        disabled={Boolean(busy)}
        aria-busy={Boolean(busy)}
      >
        {busy
          ? BUSY_LABELS[busy]
          : purchased
            ? "Download PDF report"
            : unverified
              ? "Retry confirming payment"
              : "Download PDF Report — ₹99"}
      </button>
      {!purchased && !busy && !unverified && (
        <p className="small muted">
          Matched and unmatched invoices with the ITC impact, for this run. Pay once;
          download it again any time.
        </p>
      )}
    </div>
  );
}
