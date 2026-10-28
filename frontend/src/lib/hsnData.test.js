import { describe, expect, it } from "vitest";
import {
  HSN_DATA,
  allProducts,
  byCategory,
  categories,
  findProductRate,
  getByCode,
  productSlug,
  programmaticRoutes,
  searchHSN,
} from "./hsnData";

describe("HSN_DATA", () => {
  it("is a non-empty array of objects with expected shape", () => {
    expect(HSN_DATA.length).toBeGreaterThan(100);
    for (const item of HSN_DATA) {
      expect(item).toHaveProperty("code");
      expect(item).toHaveProperty("desc");
      expect(item).toHaveProperty("rate");
      expect(item).toHaveProperty("category");
    }
  });
});

describe("searchHSN", () => {
  it("returns empty array for empty query", () => {
    expect(searchHSN("")).toEqual([]);
    expect(searchHSN("  ")).toEqual([]);
    expect(searchHSN(null)).toEqual([]);
  });

  it("searches by code prefix", () => {
    const results = searchHSN("84");
    expect(results.length).toBeGreaterThan(0);
    for (const r of results) {
      expect(r.code).toMatch(/^84/);
    }
  });

  it("searches by keyword", () => {
    const results = searchHSN("cement");
    expect(results.length).toBeGreaterThan(0);
    expect(results.some((r) => r.desc.toLowerCase().includes("cement"))).toBe(true);
  });

  it("matches multi-word queries", () => {
    const results = searchHSN("iron steel");
    expect(results.length).toBeGreaterThan(0);
  });

  it("respects limit", () => {
    const results = searchHSN("0", { limit: 3 });
    expect(results.length).toBeLessThanOrEqual(3);
  });

  it("returns empty for no matches", () => {
    expect(searchHSN("xyznonexistent")).toEqual([]);
  });
});

describe("getByCode", () => {
  it("returns the matching item", () => {
    const item = getByCode("8471");
    expect(item).not.toBeNull();
    expect(item.desc).toContain("Computers");
  });

  it("returns null for unknown code", () => {
    expect(getByCode("0000")).toBeNull();
  });
});

describe("categories", () => {
  it("returns a sorted unique list", () => {
    const cats = categories();
    expect(cats.length).toBeGreaterThan(5);
    const sorted = [...cats].sort();
    expect(cats).toEqual(sorted);
    expect(new Set(cats).size).toBe(cats.length);
  });
});

describe("byCategory", () => {
  it("returns items in the specified category", () => {
    const items = byCategory("Food");
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.category).toBe("Food");
    }
  });

  it("returns empty array for non-existent category", () => {
    expect(byCategory("NonExistent")).toEqual([]);
  });
});

describe("findProductRate", () => {
  it("finds an exact match", () => {
    const r = findProductRate("laptop");
    expect(r).not.toBeNull();
    expect(r.product).toBe("laptop");
    expect(r.hsn).toBe("8471");
    expect(r.rate).toBe(18);
  });

  it("finds a partial match", () => {
    const r = findProductRate("gold jewellery ring");
    expect(r).not.toBeNull();
    expect(r.hsn).toBe("7113");
  });

  it("returns null for unknown product", () => {
    expect(findProductRate("xyznonexistent")).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(findProductRate("")).toBeNull();
    expect(findProductRate(null)).toBeNull();
  });

  it("normalises dashes to spaces", () => {
    const r = findProductRate("mobile-phone");
    expect(r).not.toBeNull();
    expect(r.hsn).toBe("8517");
  });
});

describe("allProducts", () => {
  it("returns a non-empty array", () => {
    const products = allProducts();
    expect(products.length).toBeGreaterThan(50);
    for (const p of products) {
      expect(p).toHaveProperty("product");
      expect(p).toHaveProperty("hsn");
      expect(p).toHaveProperty("rate");
    }
  });
});

describe("productSlug", () => {
  it("lowercases and hyphenates spaces", () => {
    expect(productSlug("Mobile Phone")).toBe("mobile-phone");
  });

  it("round-trips through findProductRate for every listed product", () => {
    for (const p of allProducts()) {
      expect(findProductRate(productSlug(p.product))).toBe(p);
    }
  });

  it("still matches a name typed with spaces", () => {
    expect(findProductRate("Mobile Phone").product).toBe("mobile phone");
  });

  it("keeps a hyphen that belongs to the name", () => {
    expect(findProductRate("t-shirts").product).toBe("t-shirts");
  });
});

describe("programmaticRoutes", () => {
  const routes = programmaticRoutes();

  it("has one page per HSN code and per product slug, without duplicates", () => {
    expect(new Set(routes).size).toBe(routes.length);
    expect(routes).toContain("/hsn/8471");
    expect(routes).toContain("/gst-rate/mobile-phone");
    expect(routes.filter((r) => r.startsWith("/hsn/")).length).toBe(new Set(HSN_DATA.map((h) => h.code)).size);
  });

  it("only lists rate pages that resolve to a listing", () => {
    for (const r of routes.filter((x) => x.startsWith("/gst-rate/"))) {
      expect(findProductRate(r.slice("/gst-rate/".length))).not.toBeNull();
    }
  });
});

describe("GST 2.0 rates (Notification 9/2025, from 22 Sep 2025)", () => {
  // The table was built on the 2017 schedule and its 12%/28% rows were folded
  // into 18% wholesale, so goods the reform cut to 5% or nil were quoted at 18%.
  const cut = { "1704": 5, "1806": 5, "1904": 5, "1905": 5, "2105": 5, "2106": 5,
    "2201": 5, "3305": 5, "3306": 5, "3401": 5, "6601": 5, "7323": 5, "9615": 5,
    "4820": 0, "9609": 0 };
  it.each(Object.entries(cut))("heading %s is at %s%%", (code, rate) => {
    expect(HSN_DATA.find((h) => h.code === code).rate).toBe(rate);
  });
  it.each([["shampoo", 5], ["biscuits", 5], ["namkeen", 5], ["notebook", 0], ["bread", 0],
    ["suv", 40], ["petrol", 0], ["diesel", 0], ["natural gas", 0]])(
    "%s resolves to %s%%", (product, rate) => {
      expect(findProductRate(product).rate).toBe(rate);
    });
});
