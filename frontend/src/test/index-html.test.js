import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path) => readFileSync(resolve(process.cwd(), path), "utf8");
const html = read("index.html");

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

  it("loads the service-worker cleanup from a file, and registers no worker", () => {
    // The worker cached signed-in API answers in the browser; it is retired.
    expect(html).toContain('<script src="/register-sw.js" defer></script>');
    const script = read("public/register-sw.js");
    expect(script).not.toContain(".register(");
    expect(script).toContain("registration.unregister()");
    const worker = read("public/sw.js");
    expect(worker).not.toContain('addEventListener("fetch"');
    expect(worker).toContain("self.registration.unregister()");
  });
});

describe("the analytics tag and the sign-in token", () => {
  // OAuth hands the session token to /auth/callback in the URL fragment, so it
  // never reaches a server log. Umami's tracker reports location.href with the
  // fragment unless told data-exclude-hash="true" (its `e.hash=""` runs only
  // then), and it sends a pageview on load and the URL with every track() — so
  // each Google, GitHub or Microsoft sign-in sent its 24-hour token to
  // analytics.doaide.com.
  const tag = html.match(/<script\b[^>]*analytics\.doaide\.com[^>]*>/)?.[0] ?? "";

  it("is present", () => {
    expect(tag).not.toBe("");
  });

  it("never reports the URL fragment", () => {
    expect(tag).toMatch(/\sdata-exclude-hash="true"/);
  });
});
