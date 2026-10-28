// Razorpay Checkout, loaded on demand and wrapped in a promise.
//
// Only the publishable key id ever reaches the browser — it arrives with each
// order from the backend. The key secret, which signs and verifies payments,
// stays on the server.

const SCRIPT_ID = "razorpay-script";
const SCRIPT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

/** Resolves true once Checkout is available, false if the script failed. */
export function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve(true);
  return new Promise((resolve) => {
    // A tag without `window.Razorpay` is either still loading or one that
    // failed, and a failed tag never fires again — waiting on it would hang
    // the button. A fresh tag settles either way.
    document.getElementById(SCRIPT_ID)?.remove();
    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.src = SCRIPT_SRC;
    script.onload = () => resolve(Boolean(window.Razorpay));
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

/**
 * Open Checkout and settle when the customer is done with it.
 *
 * Resolves with Razorpay's `{razorpay_order_id, razorpay_payment_id,
 * razorpay_signature}` on success, and with null when the window is closed
 * without paying — closing it is a choice, not an error to show.
 */
export function payWithRazorpay(options) {
  return new Promise((resolve) => {
    const checkout = new window.Razorpay({
      ...options,
      handler: (response) => resolve(response),
      modal: { ondismiss: () => resolve(null) },
    });
    checkout.open();
  });
}
