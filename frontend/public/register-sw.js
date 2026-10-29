// Registers the service worker. A file of its own rather than an inline
// <script> in index.html: the site's Content-Security-Policy is
// `script-src 'self' …` with no 'unsafe-inline', so the inline copy was
// blocked on every page load ("Executing inline script violates … script-src")
// and the service worker was never registered.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
