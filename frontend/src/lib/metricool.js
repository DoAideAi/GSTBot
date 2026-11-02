import sitemap from "../../public/sitemap.xml?raw";

const SITE = "https://gst.doaide.com";
const HASH = "36195e51b9aa7f88d328d9d285bb8be";
const PUBLIC_PATHS = new Set([...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)]
  .map((match) => new URL(match[1]).pathname));

// Metricool's be.js sends an image request to c3po.jpg, with the entire current
// URL and referrer. Reproduce that small JavaScript beacon with public URLs
// only: the app's OAuth fragments and reset links contain credentials, and
// calculator queries and GSTIN paths can contain a business's own data.
// https://tracker.metricool.com/resources/be.js
export async function metricoolPageUrl(pathname, { origin, referrer, width, height }) {
  if (origin !== SITE) return null;
  const path = pathname.replace(/\/+$/, "") || "/";
  if (!PUBLIC_PATHS.has(path)) {
    if (!/^\/(?:hsn|gst-rate)\/[a-z0-9-]+$/.test(path)) return null;
    // These pages already load this data chunk. Keep it out of the landing
    // page's first load, and refuse invented product/HSN paths.
    const { programmaticRoutes } = await import("./hsnData");
    if (!programmaticRoutes().includes(path)) return null;
  }
  const params = new URLSearchParams({ hash: HASH, u: SITE + path, bw: width, bh: height });
  try {
    const source = new URL(referrer);
    if (["https:", "http:"].includes(source.protocol) && source.origin !== SITE) {
      params.set("ref", source.origin + "/");
    }
  } catch { /* No valid referrer: treat this as a direct visit. */ }
  return "https://tracker.metricool.com/c3po.jpg?" + params;
}
