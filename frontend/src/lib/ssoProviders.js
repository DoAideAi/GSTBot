/**
 * The SSO providers this deployment has configured, from `/auth/providers`.
 *
 * The login form drew all three buttons unconditionally, so on a deployment
 * with no client ids every one of them led to a 501 page. Resolves to an
 * empty list on any failure: offering no shortcut is better than offering a
 * broken one.
 *
 * Its own module so tests that are not about SSO can stub it once in
 * `test/setup.js` rather than every fetch mock having to answer it.
 */
export async function fetchSsoProviders() {
  try {
    const res = await fetch("/api/v1/auth/providers");
    if (!res?.ok) return [];
    const body = await res.json();
    return Array.isArray(body?.providers) ? body.providers : [];
  } catch {
    return [];
  }
}
