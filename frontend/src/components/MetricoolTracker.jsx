import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { metricoolPageUrl } from "../lib/metricool";

export default function MetricoolTracker() {
  const { pathname } = useLocation();
  const { user, loading } = useAuth();

  useEffect(() => {
    if (import.meta.env.SSR || loading || user) return undefined;
    let active = true;
    metricoolPageUrl(pathname, {
      origin: window.location.origin,
      referrer: document.referrer,
      width: window.innerWidth,
      height: window.innerHeight,
    }).then((url) => {
      if (active && url) {
        const beacon = new Image();
        beacon.referrerPolicy = "no-referrer";
        beacon.src = url;
      }
    }).catch(() => { /* A blocked tracker must never interrupt the page. */ });
    // Also avoids duplicate visits from StrictMode and stale asynchronous
    // lookups when someone navigates or signs in before the page is ready.
    return () => { active = false; };
  }, [pathname, loading, user]);

  return null;
}
