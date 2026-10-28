import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/*
 * WCAG AA for the text colours the stylesheets define, read from the CSS
 * itself so a token edited back below 4.5:1 fails here rather than in front of
 * a reader.
 *
 * Several were under it: white on the gold every primary button uses was 1.9:1
 * in the light theme, the muted greys and the translucent inks that carry the
 * sign-in labels were 2.8–4.4:1, and the light theme's success and warning
 * greens and ambers were about 3:1.
 */

const here = dirname(fileURLToPath(import.meta.url));
const css = ["index.css", "doaide-theme.css"]
  .map((name) => readFileSync(join(here, name), "utf8"))
  .join("\n");

/** The custom properties declared in the first block opening with `selector {`. */
function block(selector) {
  const start = css.indexOf(`${selector} {`);
  if (start === -1) throw new Error(`no ${selector} block`);
  const body = css.slice(start, css.indexOf("}", start));
  const vars = {};
  for (const [, name, value] of body.matchAll(/--([\w-]+):\s*([^;]+);/g)) vars[name] = value.trim();
  return vars;
}

function parse(color) {
  const hex = color.match(/^#([0-9a-f]{6})$/i);
  if (hex) {
    const n = parseInt(hex[1], 16);
    return { rgb: [(n >> 16) & 255, (n >> 8) & 255, n & 255], alpha: 1 };
  }
  const rgba = color.match(/^rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)$/);
  if (rgba) return { rgb: rgba.slice(1, 4).map(Number), alpha: Number(rgba[4]) };
  throw new Error(`unparsed colour ${color}`);
}

function luminance([r, g, b]) {
  const lin = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/** Contrast of `fg` (composited over `bg` if translucent) against `bg`. */
function contrast(fg, bg) {
  const ground = parse(bg).rgb;
  const { rgb, alpha } = parse(fg);
  const shown = rgb.map((c, i) => alpha * c + (1 - alpha) * ground[i]);
  const [hi, lo] = [luminance(shown), luminance(ground)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}

const AA = 4.5;

describe("text colours meet WCAG AA", () => {
  const app = { dark: block(":root"), light: block('[data-theme="light"]') };
  const brand = app.dark.brand;

  describe.each(["dark", "light"])("the app's %s theme", (theme) => {
    const v = { ...app.dark, ...app[theme] };
    const grounds = [v.canvas, v.surface];

    it.each(["ink", "ink-soft", "ink-muted", "ink-faint", "good", "warn", "bad"])(
      "--%s on every ground",
      (token) => {
        for (const ground of grounds) expect(contrast(v[token], ground)).toBeGreaterThanOrEqual(AA);
      },
    );

    it("--brand-text on the gold", () => {
      expect(contrast(v["brand-text"], brand)).toBeGreaterThanOrEqual(AA);
    });
  });

  describe("the shared DoAide theme", () => {
    const start = css.indexOf("--doaide-bg:");
    const darkTheme = (() => {
      const body = css.slice(start, css.indexOf("}", start));
      const vars = {};
      for (const [, name, value] of body.matchAll(/--doaide-([\w-]+):\s*([^;]+);/g)) vars[name] = value.trim();
      return vars;
    })();
    const lightStart = css.lastIndexOf('[data-theme="light"] {');
    const lightTheme = Object.fromEntries(
      [...css
        .slice(lightStart, css.indexOf("}", lightStart))
        .matchAll(/--doaide-([\w-]+):\s*([^;]+);/g)].map(([, n, value]) => [n, value.trim()]),
    );

    it.each([
      ["dark", darkTheme],
      ["light", { ...darkTheme, ...lightTheme }],
    ])("%s: text tokens on bg and surface, and the ink on gold", (_, t) => {
      const tokens = ["text", "text-secondary", "text-muted", "success", "error", "warning", "info"];
      for (const ground of [t.bg, t.surface, t["bg-alt"]]) {
        for (const token of tokens) {
          expect(contrast(t[token], ground), `--doaide-${token} on ${ground}`).toBeGreaterThanOrEqual(AA);
        }
      }
      expect(contrast(t["text-on-gold"], t.gold)).toBeGreaterThanOrEqual(AA);
    });
  });
});
