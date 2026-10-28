import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/*
 * The PNGs served from public/. The two PWA icons were saved at 16 bits per
 * channel — 157 KB and 28 KB for images a screen draws at 8 — and re-saving
 * them at 8 bits was pixel-identical at a quarter of the size.
 */
const PUBLIC = join(dirname(fileURLToPath(import.meta.url)), "..", "public");
const pngs = readdirSync(PUBLIC).filter((name) => name.endsWith(".png"));

/** IHDR's bit-depth byte: 8-byte signature, 4 length, 4 type, 4 width, 4 height. */
const bitDepth = (name) => readFileSync(join(PUBLIC, name))[24];

describe("public PNGs", () => {
  it("found the icons", () => {
    expect(pngs).toEqual(expect.arrayContaining(["icon-192.png", "icon-512.png"]));
  });

  it.each(pngs)("%s is 8 bits per channel", (name) => {
    expect(bitDepth(name)).toBeLessThanOrEqual(8);
  });

  it.each(pngs)("%s is under 100 KB", (name) => {
    expect(statSync(join(PUBLIC, name)).size).toBeLessThan(100 * 1024);
  });
});
