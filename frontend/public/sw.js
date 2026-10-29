// Retired. This file only exists to remove itself.
//
// The previous worker cached every /api GET — signed-in answers included,
// /auth/me and a business's invoices among them — in Cache Storage, served
// them back offline, and routed cross-origin scripts (Umami) through a
// cache-first handler that failed them. It never ran until a863c71 moved its
// registration out of the inline script the CSP had always blocked; the
// first browsers to register it get this instead, which deletes every cache
// it made and unregisters, so the next load is served by the network alone.
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((key) => caches.delete(key)));
      await self.registration.unregister();
    })(),
  );
});
