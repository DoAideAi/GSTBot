import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import SeoHead from "../components/SeoHead";
import ToolsNav from "../components/ToolsNav";
import PilotStatus, { pilotDate } from "../components/PilotStatus";
import { usePageTitle } from "../hooks/usePageTitle";
import { announceSubscriptionChange, api } from "../lib/api";
import { track } from "../lib/track";
import { rememberReturnTo } from "../lib/returnTo";

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

/**
 * What the cancel prompt says. Cancelling ends the plan at once and the API
 * gives nothing back for the rest of the period, so a plan paid up to a date
 * says which date, and that those days go with it. The prompt only said
 * "paid features stop straight away", so cancelling three days into an
 * annual plan lost a year of it without saying so.
 */
export function cancelConfirmation(sub, now = new Date()) {
  const end = sub?.current_period_end ? new Date(sub.current_period_end) : null;
  if (!end || Number.isNaN(end.getTime()) || end <= now) {
    return "Cancel your paid plan and move to Free? Paid features stop straight away.";
  }
  const date = end.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  });
  return (
    `Your plan is paid up to ${date}. Cancelling moves you to Free now: paid ` +
    "features stop straight away and the remaining days are not refunded. Cancel anyway?"
  );
}

export default function PricingPage() {
  usePageTitle("Pricing — DoAide GST");
  const { user } = useAuth();
  const [search] = useSearchParams();
  const requestedTier = ["pro", "enterprise"].includes(search.get("pilot")) ? search.get("pilot") : null;
  const [pricing, setPricing] = useState(null);
  const [currentSub, setCurrentSub] = useState(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [billing, setBilling] = useState("monthly");
  const [pilotState, setPilotState] = useState(null);
  const [startingPilot, setStartingPilot] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const p = await api.pricing();
      setPricing(p);
      if (user) {
        const sub = await api.currentSubscription();
        setCurrentSub(sub);
        if (p.pilot) setPilotState(await api.pilotStatus());
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

  async function startPilot(tier) {
    if (startingPilot) return;
    setStartingPilot(true);
    setError(null);
    try {
      setPilotState(await api.startPilot(tier));
      track("pilot_started", { tier });
      await fetchData();
      announceSubscriptionChange();
      setSuccess("Your 60-day free pilot has started. No payment details are needed.");
    } catch (err) {
      setError(err.message);
    } finally {
      setStartingPilot(false);
    }
  }

  async function coverBusiness(id) {
    setStartingPilot(true);
    setError(null);
    try {
      setPilotState(await api.coverPilotBusiness(id));
      announceSubscriptionChange();
    } catch (err) {
      setError(err.message);
    } finally {
      setStartingPilot(false);
    }
  }

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
            track("subscribe_success", step, {
              value: order.amount / 100,
              transaction_id: order.order_id,
            });
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
        theme: { color: "#0f766e" },
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
    if (!window.confirm(cancelConfirmation(currentSub))) return;
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
  const isPilot = currentSub?.source === "pilot";
  const pilotActive = isPilot && currentSub?.status === "active";
  const offer = pricing?.pilot;
  // Plans are one-time orders, not auto-renewing mandates: when the period
  // ends the business drops to Free with nothing charged and, until now,
  // nothing said. The date is shown, and renewing early extends from it.
  const paidUntil =
    currentTier !== "free" && currentSub?.current_period_end
      ? new Date(currentSub.current_period_end)
      : null;
  const endsSoon = paidUntil && paidUntil.getTime() - Date.now() <= RENEWAL_WARNING_MS;

  return (
    <>
      {!user && <ToolsNav />}
    <div className="pricing-page">
      <SeoHead
        title="Pricing — DoAide GST"
        description="Try DoAide GST free for 60 days. No payment details required. Limited SMB and CA pilot places; regular plans from ₹499/month afterward."
        path="/pricing"
      />
      {user && <p><Link to="/">Return to dashboard</Link></p>}
      <div className="pricing-header">
        <h1>Simple, transparent pricing</h1>
        <p>Calculator, GSTIN lookup, and HSN search are free forever — no login required.</p>
        <p>Upgrade for bulk validation, reconciliation, and ITC optimization.</p>
        {offer && <div className="pilot-offer">
          <h2>Try DoAide GST free for {offer.days} days</h2>
          <p>No payment details required. No automatic charge. One pilot per account and business.</p>
          <p>Founding cohort: {offer.capacity.pro} SMBs and {offer.capacity.enterprise} CA firms. Includes {offer.monthly_invoice_limit} invoice uploads per registration per calendar month, reconciliation and report downloads.</p>
          <p>AI advisor: {offer.advisor_allowance || "100/day"} per network, subject to shared availability. Invoice re-reading: {offer.reparse_allowance || "100/day"} per login.</p>
          <p><a href="https://doaide.com/demo/">Request onboarding help for your firm</a>.</p>
        </div>}
      </div>

      <PilotStatus state={pilotState} busy={startingPilot} onCover={coverBusiness} />
      {offer && user && !pilotState?.is_home && pilotState && <p className="pricing-loading">Switch to your own business to start or manage a pilot.</p>}

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
            const isHighlight = tierKey === (requestedTier || HIGHLIGHT_TIER);
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
                  <div className="pricing-badge">{requestedTier ? "Your selected pilot" : "Most Popular"}</div>
                )}
                <h2>{tier.name}</h2>
                {offer && tierKey !== "free" && <div className="pilot-card-offer">
                  <strong>Free for {offer.days} days</strong>
                  <p>{offer.business_limits[tierKey]} {tierKey === "pro" ? "registration" : "registrations, including your own"} · {offer.remaining[tierKey]} pilot places available</p>
                  <span>Regular price after the pilot:</span>
                </div>}
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
                        {pilotActive ? "Pilot active" : "Current plan"}
                      </button>
                      {tierKey !== "free" && paidUntil && (
                        <p className={endsSoon ? "pricing-period pricing-period-soon" : "pricing-period"}>
                          {pilotActive ? "Free until " : "Paid until "}
                          {pilotDate(currentSub.current_period_end)}.{" "}
                          {pilotActive ? "Choose a paid upgrade after it ends. No automatic charge." : endsSoon
                            ? "It does not renew on its own — extend it to keep your paid features."
                            : "It does not renew on its own."}
                        </p>
                      )}
                      {tierKey !== "free" && paidUntil && !isPilot && (
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
                      {tierKey !== "free" && !isPilot && (
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
                    currentTier !== "free" && !isPilot ? (
                      <button className="btn btn-ghost" onClick={handleCancel} disabled={cancelling}>
                        {cancelling ? "Cancelling…" : "Downgrade"}
                      </button>
                    ) : null
                  ) : (
                    offer && (!user || pilotState?.can_start) && offer.remaining[tierKey] > 0 ? (
                      user ? <button className="btn btn-primary" disabled={startingPilot} onClick={() => startPilot(tierKey)}>{startingPilot ? "Starting…" : `Start ${tier.name} free pilot`}</button>
                        : <Link className="btn btn-primary" to="/login?mode=register" onClick={() => rememberReturnTo(`/pricing?pilot=${tierKey}`)}>Start {tier.name} free pilot</Link>
                    ) : pilotActive ? (
                      <p>Paid upgrades open after your pilot ends.</p>
                    ) : offer && !pricing.razorpay_key_id ? (
                      <a className="btn btn-ghost" href="https://doaide.com/demo/">{offer.remaining[tierKey] === 0 ? "Ask about the next pilot" : "Contact us about a paid plan"}</a>
                    ) : user ? (
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
    </>
  );
}
