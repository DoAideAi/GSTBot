// `onRetry` is for a failure that left nothing on screen: dismissing the
// banner alone leaves an empty page, so the way forward has to be offered.
// The paid-tier refusal (`require_paid_tier`) names /pricing in prose. A free
// user meets it on the ITC screen or pressing Import/Run on Reconcile, and a
// path they would have to retype is not a way forward — so it becomes a link.
// A plain anchor because the banner is also rendered outside the router.
const PAID_TIER_REFUSAL = /requires a paid subscription|monthly allowance ran out|upgrade the plan/i;

export default function ErrorBanner({ message, onDismiss, onRetry }) {
  if (!message) return null;
  return (
    <div className="banner banner-error" role="alert">
      <span>{message}</span>
      {PAID_TIER_REFUSAL.test(message) && (
        <a className="btn btn-ghost" href="/pricing">
          See plans
        </a>
      )}
      {onRetry && (
        <button type="button" className="btn btn-ghost" onClick={onRetry}>
          Try again
        </button>
      )}
      {onDismiss && (
        <button type="button" className="banner-close" onClick={onDismiss} aria-label="Dismiss">
          ×
        </button>
      )}
    </div>
  );
}
