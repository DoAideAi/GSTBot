/**
 * The page a sign-in returns to.
 *
 * A deep link opened while signed out — an emailed /invoices/42, a bookmark, a
 * session that expired mid-task — was sent home, and after signing in, by
 * password or through Google, GitHub or Microsoft, the user landed on the
 * dashboard with the page they asked for lost. `Protected` remembers it here;
 * both sign-in paths take it back.
 *
 * In this tab's sessionStorage, not in the OAuth round trip: a return address
 * the provider hands back to the server is the classic open redirect, and this
 * never leaves the browser. It survives the trip to the provider because that
 * is the same tab coming back to the same origin.
 *
 * Only a path on this site is ever returned. "//host" and "/\host" are
 * protocol-relative to a browser, and the auth pages themselves would loop.
 */
const KEY = "gstbot_return_to";
const SAME_SITE_PATH = /^\/(?![/\\])/;
const NOT_A_DESTINATION = /^\/(login|auth\/|forgot-password|reset-password)/;

function usable(target) {
  return (
    typeof target === "string" &&
    SAME_SITE_PATH.test(target) &&
    !NOT_A_DESTINATION.test(target)
  );
}

export function rememberReturnTo(target) {
  try {
    if (usable(target)) sessionStorage.setItem(KEY, target);
    else sessionStorage.removeItem(KEY);
  } catch {
    // Storage refused: the sign-in still works, it just returns home.
  }
}

/** The remembered page, or "/" — and forgets it, so it is used once. */
export function takeReturnTo() {
  let target = null;
  try {
    target = sessionStorage.getItem(KEY);
    sessionStorage.removeItem(KEY);
  } catch {
    return "/";
  }
  return usable(target) ? target : "/";
}
