import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import SeoHead from "../components/SeoHead";
import { usePageTitle } from "../hooks/usePageTitle";
import { announceSubscriptionChange, api } from "../lib/api";
import { track } from "../lib/track";

/** How close to the end of a paid period the renewal is called out. */
const RENEWAL_WARNING_MS = 7 * 24 * 60 * 60 * 1000;

const TIER_ORDER = ["free", "pro", "enterprise"];
const TIER_LABELS = { free: "Free Tools", pro: "SMB", enterprise: "CA" };
const HIGHLIGHT_TIER = "pro";

function loadRazorpayScript() {
  return new Promise((resolve) => {
    if (document.getElementById("razorpay-script")) {
      resolve(true);
      return;
    }
    const script = document.createElement("script");
    script.id = "razorpay-script";
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve(true);
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

function formatPrice(paise) {
  if (!paise) return "Free forever";
  const rupees = paise / 100;
  return `₹${rupees.toLocaleString("en-IN")}`;
}

export default function PricingPage() {
  usePageTitle("Pricing — DoAide GST");
  const { user } = useAuth();
  const [pricing, setPricing] = useState(null);
  const [currentSub, setCurrentSub] = useState(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [billing, setBilling] = useState("monthly");

  const fetchData = useCallback(async () => {
    try {
      const p = await api.pricing();
      setPricing(p);
      if (user) {
        const sub = await api.currentSubscription();
        setCurrentSub(sub);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    track("pricing_view");
  }, []);

  async function handleSubscribe(tier) {
    if (tier === "free") return;
    setError(null);
    setSuccess(null);
    setPaying(true);
    // The upgrade funnel, one event per step: chose a plan, saw checkout, and
    // then exactly one of paid, walked away, or failed — with the stage it
    // failed at, because a gateway that will not load and a payment that will
    // not verify are different problems to go and fix.
    const step = { tier, billing };
    track("upgrade_click", step);
    let stage = "gateway";

    try {
      const scriptLoaded = await loadRazorpayScript();
      if (!scriptLoaded) {
        track("upgrade_failed", { ...step, stage });
        setError("Could not load payment gateway. Please try again.");
        setPaying(false);
        return;
      }

      stage = "order";
      const order = await api.createOrder(tier, billing);
      const periodLabel = billing === "annual" ? "Annual" : "Monthly";

      const options = {
        key: order.razorpay_key_id,
        amount: order.amount,
        currency: order.currency,
        name: "DoAide GST",
        description: `${TIER_LABELS[tier]} Plan — ${periodLabel}`,
        order_id: order.order_id,
        handler: async function (response) {
          try {
            await api.verifyPayment({
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
              tier,
            });
            track("subscribe_success", step);
            setSuccess(`Subscribed to ${TIER_LABELS[tier]} plan!`);
            const sub = await api.currentSubscription();
            setCurrentSub(sub);
            announceSubscriptionChange();
          } catch (err) {
            // Paid but not activated: the step a support ticket follows.
            track("upgrade_failed", { ...step, stage: "verify" });
            setError(err.message);
          } finally {
            setPaying(false);
          }
        },
        modal: {
          ondismiss: function () {
            track("checkout_dismissed", step);
            setPaying(false);
          },
        },
        prefill: {
          email: user?.email || "",
          name: user?.full_name || "",
        },
        theme: { color: "#F0B429" },
      };

      const rzp = new window.Razorpay(options);
      rzp.open();
      track("checkout_open", step);
    } catch (err) {
      track("upgrade_failed", { ...step, stage });
      setError(err.message);
      setPaying(false);
    }
  }

  const [cancelling, setCancelling] = useState(false);
  async function handleCancel() {
    if (cancelling) return;
    if (!window.confirm("Cancel your paid plan and move to Free? Paid features stop straight away.")) return;
    setError(null);
    setSuccess(null);
    setCancelling(true);
    try {
      await api.cancelSubscription();
      setSuccess("Subscription cancelled. You are now on the Free plan.");
      const sub = await api.currentSubscription();
      setCurrentSub(sub);
      announceSubscriptionChange();
    } catch (err) {
      setError(err.message);
    } finally {
      setCancelling(false);
    }
  }

  if (loading) {
    return (
      <div className="pricing-page">
        <p className="pricing-loading">Loading pricing...</p>
      </div>
    );
  }

  // An expired or cancelled row keeps its tier; the plan the business is on
  // is free until it pays again, and the page has to offer that.
  const currentTier = currentSub?.status === "active" ? currentSub.tier : "free";
  // Plans are one-time orders, not auto-renewing mandates: when the period
  // ends the business drops to Free with nothing charged and, until now,
  // nothing said. The date is shown, and renewing early extends from it.
  const paidUntil =
    currentTier !== "free" && currentSub?.current_period_end
      ? new Date(currentSub.current_period_end)
      : null;
  const endsSoon = paidUntil && paidUntil.getTime() - Date.now() <= RENEWAL_WARNING_MS;

  return (
    <div className="pricing-page">
      <SeoHead
        title="Pricing — DoAide GST"
        description="Free GST calculator, GSTIN lookup, and HSN search forever. Upgrade from ₹499/month for filing assistance, bulk validation, and GSTR-2B reconciliation."
        path="/pricing"
      />
      <div className="pricing-header">
        <h1>Simple, transparent pricing</h1>
        <p>Calculator, GSTIN lookup, and HSN search are free forever — no login required.</p>
        <p>Upgrade for bulk validation, reconciliation, and ITC optimization.</p>
      </div>

      <div className="pricing-toggle" role="radiogroup" aria-label="Billing period">
        <button
          className={`pricing-toggle-btn${billing === "monthly" ? " pricing-toggle-active" : ""}`}
          onClick={() => setBilling("monthly")}
          aria-checked={billing === "monthly"}
          role="radio"
        >
          Monthly
        </button>
        <button
          className={`pricing-toggle-btn${billing === "annual" ? " pricing-toggle-active" : ""}`}
          onClick={() => setBilling("annual")}
          aria-checked={billing === "annual"}
          role="radio"
        >
          Annual
          <span className="pricing-save-badge">Save 17%</span>
        </button>
      </div>

      {error && <div className="pricing-error" role="alert">{error}</div>}
      {success && (
        <div className="pricing-success" role="status">
          <span>{success}</span>
          {/* "/", where the dashboard is: /dashboard is no route, and this
              button sent a customer who had just paid to the 404 page. */}
          <Link to="/" className="btn btn-primary">Go to dashboard</Link>
        </div>
      )}

      <div className="pricing-grid">
        {pricing &&
          TIER_ORDER.map((tierKey) => {
            const tier = pricing.tiers[tierKey];
            if (!tier) return null;
            const isCurrent = currentTier === tierKey;
            const isHighlight = tierKey === HIGHLIGHT_TIER;
            const price = billing === "annual" && tier.price_annual
              ? tier.price_annual
              : tier.price_monthly;
            const perMonth = billing === "annual" && tier.price_annual
              ? Math.round(tier.price_annual / 1200) * 100
              : tier.price_monthly;

            return (
              <div
                key={tierKey}
                className={`pricing-card${isHighlight ? " pricing-card-highlight" : ""}${isCurrent ? " pricing-card-current" : ""}`}
              >
                {isHighlight && (
                  <div className="pricing-badge">Most Popular</div>
                )}
                <h2>{tier.name}</h2>
                <div className="pricing-price">
                  {price === 0 ? (
                    "Free forever"
                  ) : (
                    <>
                      <span className="pricing-amount">{formatPrice(perMonth)}</span>
                      <span className="pricing-period">/month</span>
                      {billing === "annual" && (
                        <div className="pricing-billed">
                          Billed {formatPrice(price)}/year
                        </div>
                      )}
                    </>
                  )}
                </div>
                <ul className="pricing-features">
                  {tier.features.map((f, i) => (
                    <li key={i}>{f}</li>
                  ))}
                </ul>
                <div className="pricing-action">
                  {isCurrent ? (
                    <>
                      <button className="btn btn-ghost" disabled>
                        Current plan
                      </button>
                      {tierKey !== "free" && paidUntil && (
                        <p className={endsSoon ? "pricing-period pricing-period-soon" : "pricing-period"}>
                          Paid until{" "}
                          {paidUntil.toLocaleDateString("en-IN", { dateStyle: "medium" })}.{" "}
                          {endsSoon
                            ? "It does not renew on its own — extend it to keep your paid features."
                            : "It does not renew on its own."}
                        </p>
                      )}
                      {tierKey !== "free" && paidUntil && (
                        <button
                          className={endsSoon ? "btn btn-primary" : "btn btn-ghost"}
                          disabled={paying}
                          onClick={() => handleSubscribe(tierKey)}
                        >
                          {paying
                            ? "Processing..."
                            : `Extend by a ${billing === "annual" ? "year" : "month"}`}
                        </button>
                      )}
                      {tierKey !== "free" && (
                        <button
                          className="btn btn-danger-ghost"
                          onClick={handleCancel}
                          disabled={cancelling}
                        >
                          {cancelling ? "Cancelling…" : "Cancel"}
                        </button>
                      )}
                    </>
                  ) : tierKey === "free" ? (
                    currentTier !== "free" ? (
                      <button className="btn btn-ghost" onClick={handleCancel} disabled={cancelling}>
                        {cancelling ? "Cancelling…" : "Downgrade"}
                      </button>
                    ) : null
                  ) : (
                    user ? (
                      <button
                        className="btn btn-primary"
                        disabled={paying}
                        onClick={() => handleSubscribe(tierKey)}
                      >
                        {paying ? "Processing..." : "Subscribe"}
                      </button>
                    ) : (
                      <Link className="btn btn-primary" to="/login">
                        Sign in to subscribe
                      </Link>
                    )
                  )}
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
}
