// Removes the service worker this site used to register, and registers none.
//
// The old one cached signed-in API responses in the browser and broke
// third-party scripts (see public/sw.js, now a self-removing stub). A plain
// file rather than an inline <script>, because the site's CSP has no
// 'unsafe-inline' — the inline version was blocked on every page load.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker
    .getRegistrations()
    .then((registrations) => registrations.forEach((registration) => registration.unregister()))
    .catch(() => {});
}
if ("caches" in window) {
  caches
    .keys()
    .then((keys) => keys.forEach((key) => caches.delete(key)))
    .catch(() => {});
}
