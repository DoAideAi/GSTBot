// Gold as text on the light theme (P23 M13). The brand gold is 1.8:1 on the
// light grounds, and links, gold headings and badges all used it as their
// text colour, so a visitor whose device is in light mode — the default
// theme follows the system — read every link below WCAG AA. Text now uses
// the *-ink tokens, which the light theme darkens; the gold fills stay.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = (name) => readFileSync(join(here, name), "utf8");

function luminance(hex) {
  const channels = [0, 2, 4].map((i) => parseInt(hex.slice(1 + i, 3 + i), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The value *name* takes inside the `[data-theme="light"]` block of *source*. */
function lightValue(source, name) {
  const block = source.slice(source.indexOf('[data-theme="light"]'));
  const match = block.match(new RegExp(`${name}:\\s*(#[0-9A-Fa-f]{6})`));
  return match?.[1];
}

const LIGHT_GROUNDS = ["#FFFFFF", "#FAFAFA", "#F4F4F5"];

describe("gold text on the light theme", () => {
  it.each([
    ["index.css", "--brand-ink"],
    ["index.css", "--brand-ink-hover"],
    ["doaide-theme.css", "--doaide-gold-ink"],
    ["doaide-theme.css", "--doaide-gold-ink-hover"],
  ])("%s %s clears 4.5:1 on every light ground", (file, token) => {
    const value = lightValue(css(file), token);
    expect(value).toMatch(/^#/);
    for (const ground of LIGHT_GROUNDS) {
      expect(contrast(value, ground)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(["index.css", "doaide-theme.css"])("%s sets no text in the raw gold", (file) => {
    // background-color and border-color may use the gold; color may not.
    const raw = /(?<![-\w])color:\s*var\(--(brand|accent|brand-hover|doaide-gold|doaide-gold-light)\)/g;
    expect(css(file).match(raw)).toBeNull();
  });
});
