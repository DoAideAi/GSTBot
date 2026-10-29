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
