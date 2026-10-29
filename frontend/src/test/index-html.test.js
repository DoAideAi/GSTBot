import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");

describe("index.html under the site's CSP", () => {
  // deploy/caddy-gstbot.conf sends `script-src 'self' …` with no
  // 'unsafe-inline'. An inline service-worker registration was blocked on
  // every page load and showed in the console as a CSP violation.
  it("has no inline script the browser would execute", () => {
    const inline = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)].filter(
      ([, attrs, body]) => !/\bsrc=/.test(attrs) && !/application\/ld\+json/.test(attrs) && body.trim(),
    );
    expect(inline.map(([tag]) => tag.slice(0, 80))).toEqual([]);
  });

  it("still registers the service worker, from a file", () => {
    expect(html).toContain('<script src="/register-sw.js" defer></script>');
    const script = readFileSync(resolve(process.cwd(), "public/register-sw.js"), "utf8");
    expect(script).toContain('navigator.serviceWorker.register("/sw.js")');
  });
});
