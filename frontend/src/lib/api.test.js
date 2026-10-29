import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  api,
  errorMessage,
  featurePath,
  getActiveBusinessId,
  getToken,
  isAbortError,
  onUnauthorized,
  setActiveBusinessId,
  setToken,
} from "./api";

function jsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    text: async () => (body === null ? "" : JSON.stringify(body)),
  };
}

describe("errorMessage", () => {
  it("passes a plain string detail through", () => {
    expect(errorMessage({ detail: "Email already registered" })).toBe(
      "Email already registered",
    );
  });

  it("flattens a FastAPI validation error list", () => {
    const detail = [
      { loc: ["body", "gstin"], msg: "GSTIN check digit does not match" },
      { loc: ["body", "password"], msg: "too short" },
    ];
    expect(errorMessage({ detail })).toBe("GSTIN check digit does not match, Password: too short");
  });

  it("says which field a generic validation message is about", () => {
    const detail = [
      { loc: ["body", "email"], msg: "Field required" },
      { loc: ["body", "invoice_date"], msg: "Input should be a valid date" },
      { loc: ["body", "items", 0, "hsn_code"], msg: "Field required" },
      { loc: ["body", 29], msg: "JSON decode error" },
    ];
    expect(errorMessage({ detail })).toBe(
      "Email: Field required, Invoice date: Input should be a valid date, " +
        "HSN code: Field required, JSON decode error",
    );
  });

  it("reads the message out of a structured conflict", () => {
    // The duplicate-upload response is {message, invoice_id}.
    expect(errorMessage({ detail: { message: "Already uploaded as 7", invoice_id: 7 } })).toBe(
      "Already uploaded as 7",
    );
  });

  it("falls back when there is no detail", () => {
    expect(errorMessage(null, "Request failed")).toBe("Request failed");
  });

  it("stringifies a detail that is neither text, list nor object", () => {
    // Nothing we send looks like this, but an upstream proxy erroring with
    // `{"detail": 502}` should still read as something rather than crash the
    // banner that renders it.
    expect(errorMessage({ detail: 502 })).toBe("502");
  });

  it("falls back to JSON for a structured detail with no message", () => {
    expect(errorMessage({ detail: { code: "rate_limited" } })).toBe('{"code":"rate_limited"}');
  });

  // A `detail` that is there and says nothing. Three shapes, three routes to
  // the same outcome — an error raised with an empty message, which renders as
  // a banner with nothing written in it. That is the failure that looks least
  // like a failure: not "the server refused", but the app appearing to have
  // stopped mid-thought.
  it.each([
    ["an empty string, from a proxy that rewrote the envelope", ""],
    ["a string of nothing but space", "   "],
    ["a field list filtered down to nothing", []],
    ["a structured conflict whose message was never set", { message: "" }],
    ["a structured conflict whose message is blank", { message: " ", invoice_id: 7 }],
  ])("falls back rather than saying nothing when the detail is %s", (unused, detail) => {
    expect(errorMessage({ detail }, "The server is having trouble (503).")).toBe(
      "The server is having trouble (503).",
    );
  });

  it("falls back to JSON for a validation entry with no msg", () => {
    // Not FastAPI's own shape — a gateway that rewrote the list, or a
    // middleware error serialized into it. Rendering `undefined` in the banner
    // would tell the user nothing about which field was refused; the raw entry
    // at least still names it.
    expect(errorMessage({ detail: [{ loc: ["body", "gstin"], type: "value_error" }] })).toBe(
      '{"loc":["body","gstin"],"type":"value_error"}',
    );
  });
});

describe("isAbortError", () => {
  it("recognises what a browser rejects an aborted fetch with", () => {
    // Constructed rather than taken from a real `fetch`: this suite runs on
    // jsdom, whose `AbortController` is from a different realm than the fetch
    // implementation under it, so an abort here fails with a TypeError about
    // the signal instead of ever reaching the abort path. A browser rejects
    // with a DOMException named "AbortError", and the name is the only part of
    // it the specification pins down — so the name is what is matched on, and
    // what is asserted here.
    expect(isAbortError(new DOMException("The operation was aborted.", "AbortError"))).toBe(
      true,
    );
    // Some runtimes reject with a plain Error carrying the same name.
    const plain = new Error("The operation was aborted.");
    plain.name = "AbortError";
    expect(isAbortError(plain)).toBe(true);
  });

  it("does not swallow an ordinary failure", () => {
    // The banner exists for these. Treating one as a cancelled request would
    // leave a genuinely broken page looking merely busy.
    expect(isAbortError(new Error("Database unreachable"))).toBe(false);
    expect(isAbortError(null)).toBe(false);
    expect(isAbortError(undefined)).toBe(false);
  });
});

describe("api", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("imported GSTR-2B periods", () => {
    it("unwraps the items envelope and passes the abort signal through", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse({ items: ["2026-05", "2026-04"] }));
      const controller = new AbortController();

      await expect(api.importedPeriods({ signal: controller.signal })).resolves.toEqual([
        "2026-05",
        "2026-04",
      ]);
      expect(global.fetch.mock.calls[0][1].signal).toBe(controller.signal);
    });
  });

  describe("the status a refusal carries", () => {
    // Some refusals are a normal state of the product — a period with nothing
    // imported answers 404 — and some are a failure. A caller that wants to
    // pass over the first quietly needs to be able to tell them apart.
    it("puts the status on the error it throws", async () => {
      global.fetch.mockResolvedValueOnce(
        jsonResponse({ detail: "Nothing imported for that period" }, { status: 404 }),
      );

      const err = await api.getImported2b("2026-04").catch((e) => e);
      expect(err.status).toBe(404);
      expect(err.message).toBe("Nothing imported for that period");
    });

    it("carries the status of a failure just the same", async () => {
      global.fetch.mockResolvedValueOnce(
        jsonResponse({ detail: "Database unreachable" }, { status: 500 }),
      );

      const err = await api.getImported2b("2026-04").catch((e) => e);
      expect(err.status).toBe(500);
    });

    it("carries a status even when the body was not readable", async () => {
      // An HTML error page from the edge. The message falls back, the status
      // does not — it is the only thing the caller can still branch on.
      global.fetch.mockResolvedValueOnce({
        ok: false,
        status: 502,
        statusText: "",
        text: async () => "<html><body>502 Bad Gateway</body></html>",
      });

      const err = await api.latestReconciliation("2026-04").catch((e) => e);
      expect(err.status).toBe(502);
      expect(err.message).toContain("502");
    });

    it("carries the status on a refused export too", async () => {
      global.fetch.mockResolvedValueOnce(
        jsonResponse({ detail: "No invoices for that period" }, { status: 404 }),
      );

      const err = await api.downloadExport("gstr1", "csv", "2026-04").catch((e) => e);
      expect(err.status).toBe(404);
    });
  });

  describe("cancellation", () => {
    // The two list endpoints are the ones a search box refetches per keystroke,
    // so they are the two that have to be cancellable. Without the signal
    // reaching `fetch` the page can abort nothing, and a superseded response
    // still lands on the table it no longer describes.
    it("passes a signal through to fetch on the invoice list", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));
      const controller = new AbortController();

      await api.listInvoices({ search: "north" }, { signal: controller.signal });

      const [, options] = global.fetch.mock.calls[0];
      expect(options.signal).toBe(controller.signal);
    });

    it("passes a signal through to fetch on the supplier list", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));
      const controller = new AbortController();

      await api.listSuppliers({ search: "north" }, { signal: controller.signal });

      const [, options] = global.fetch.mock.calls[0];
      expect(options.signal).toBe(controller.signal);
    });

    it("passes a signal through to fetch on the late fee", async () => {
      // Two controls on the filing page choose which return this asks about,
      // and the answer is an amount of money owed. A superseded response that
      // lands anyway puts the wrong month's figure under the wrong month's
      // heading — and unlike a stale table, that is a number someone may pay.
      global.fetch.mockResolvedValueOnce(jsonResponse({ days_late: 0 }));
      const controller = new AbortController();

      await api.lateFee("gstr3b", "2026-04", {}, { signal: controller.signal });

      const [url, options] = global.fetch.mock.calls[0];
      expect(String(url)).toContain("/filing/gstr3b/late-fee?period=2026-04");
      expect(options.signal).toBe(controller.signal);
    });

    it("still asks for the late fee when the caller wants no cancellation", async () => {
      // The refining parameters stay optional and stay out of the query when
      // they are not given: an omitted turnover means "use the highest cap", and
      // an empty one would be a different question.
      global.fetch.mockResolvedValueOnce(jsonResponse({ days_late: 0 }));

      await api.lateFee("gstr1", "2026-04");

      const [url, options] = global.fetch.mock.calls[0];
      expect(String(url)).toBe("/api/v1/filing/gstr1/late-fee?period=2026-04");
      expect(options.signal).toBeUndefined();
    });

    it("asks for the lapsing credit of the whole register, not a period", async () => {
      // s.16(4) governs a financial year. Omitting `as_of` asks about today,
      // and an empty one would be a different question — so it stays out of the
      // query string rather than going in blank.
      global.fetch.mockResolvedValueOnce(jsonResponse({ years: [] }));
      const controller = new AbortController();

      await api.lapsingCredit(undefined, { signal: controller.signal });

      const [url, options] = global.fetch.mock.calls[0];
      expect(String(url)).toBe("/api/v1/itc/lapsing");
      expect(options.signal).toBe(controller.signal);
    });

    it("measures the lapsing deadline against a date when given one", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse({ years: [] }));

      await api.lapsingCredit("2026-11-01");

      const [url] = global.fetch.mock.calls[0];
      expect(String(url)).toBe("/api/v1/itc/lapsing?as_of=2026-11-01");
    });

    it("asks the Rule 37 pool about today when given no date", async () => {
      // Same shape as `lapsingCredit`, for the same reason: the 180-day clock
      // is measured against a date, and an empty `as_of` is a different
      // question from an absent one — so it must not reach the query string.
      global.fetch.mockResolvedValueOnce(jsonResponse({ items: [] }));

      await api.rule37(undefined);

      const [url] = global.fetch.mock.calls[0];
      expect(String(url)).toBe("/api/v1/itc/rule37");
    });

    it("measures the Rule 37 clock against a date when given one", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse({ items: [] }));

      await api.rule37("2026-09-30");

      const [url] = global.fetch.mock.calls[0];
      expect(String(url)).toBe("/api/v1/itc/rule37?as_of=2026-09-30");
    });

    it("posts a set-off rather than asking for one", async () => {
      // The one ITC call that writes. A GET would be answered by the read
      // route and quietly return a summary instead of applying anything, so
      // the method is asserted here and not only the path.
      global.fetch.mockResolvedValueOnce(jsonResponse({ set_off: {} }));
      const payload = { period: "2026-04", igst: "81000.00" };

      await api.setOff(payload);

      const [url, options] = global.fetch.mock.calls[0];
      expect(String(url)).toBe("/api/v1/itc/set-off");
      expect(options.method).toBe("POST");
      expect(JSON.parse(options.body)).toEqual(payload);
    });

    it("still works for a caller that does not want to cancel", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

      await api.listSuppliers({ search: "north" });

      const [, options] = global.fetch.mock.calls[0];
      expect(options.signal).toBeUndefined();
    });
  });

  it("stores the token on login and sends it afterwards", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ access_token: "tok-1" }));
    await api.login("owner@example.com", "supersecret123");
    expect(getToken()).toBe("tok-1");

    global.fetch.mockResolvedValueOnce(jsonResponse({ email: "owner@example.com" }));
    await api.me();

    const [, options] = global.fetch.mock.calls[1];
    expect(options.headers.Authorization).toBe("Bearer tok-1");
  });

  it("sends login as form fields with the email as username", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ access_token: "tok-1" }));
    await api.login("owner@example.com", "pw");

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/auth/login");
    // OAuth2 password flow: form-encoded, and the field is called "username".
    expect(options.body).toBeInstanceOf(URLSearchParams);
    expect(options.body.get("username")).toBe("owner@example.com");
    expect(options.headers["Content-Type"]).toBeUndefined();
  });

  it("drops a token the server has rejected", async () => {
    setToken("stale-token");
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Could not validate credentials" }, { status: 401 }),
    );

    await expect(api.me()).rejects.toThrow("Could not validate credentials");
    // Retrying with a credential the server already refused is pointless, and
    // it keeps the UI from ever falling back to the login screen.
    expect(getToken()).toBeNull();
  });

  it("announces a rejected token so the session can end with it", async () => {
    // Dropping the token is only half of it. The session lives in React and
    // outlived the credential: `user` stayed set, so the app kept rendering,
    // every later request went out unauthenticated, and `/login` bounced back
    // to `/`. The one screen that could fix it was unreachable.
    setToken("stale-token");
    const told = vi.fn();
    const unsubscribe = onUnauthorized(told);

    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Could not validate credentials" }, { status: 401 }),
    );
    await expect(api.me()).rejects.toThrow();

    expect(told).toHaveBeenCalledTimes(1);
    unsubscribe();
  });

  it("stops announcing once a subscriber has unsubscribed", async () => {
    setToken("stale-token");
    const told = vi.fn();
    onUnauthorized(told)();

    global.fetch.mockResolvedValueOnce(jsonResponse({ detail: "no" }, { status: 401 }));
    await expect(api.me()).rejects.toThrow();

    expect(told).not.toHaveBeenCalled();
  });

  it("says nothing about a 401 from a request that carried no token", async () => {
    // A wrong password on the sign-in form is not an expired session, and
    // announcing it as one would have the login page fight its own error
    // handling.
    setToken(null);
    const told = vi.fn();
    const unsubscribe = onUnauthorized(told);

    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Incorrect email or password" }, { status: 401 }),
    );
    await expect(api.login("a@b.com", "wrong")).rejects.toThrow();

    expect(told).not.toHaveBeenCalled();
    unsubscribe();
  });

  it("keeps the session when the 401 is about a credential in the body", async () => {
    // Linking another GSTIN submits *that* account's email and password to
    // prove the caller also holds it, and the endpoint answers 401 when they do
    // not match. Read as the caller's own token being refused, a typo in the
    // other registration's password signed the user out of the account they
    // were signed into — and the token is still perfectly good.
    setToken("good-token");
    const told = vi.fn();
    const unsubscribe = onUnauthorized(told);

    global.fetch.mockResolvedValueOnce(
      jsonResponse(
        { detail: "That email and password do not match an active account." },
        { status: 401 },
      ),
    );
    await expect(api.linkBusiness("other@acme.in", "wrong")).rejects.toThrow(
      /do not match an active account/,
    );

    expect(told).not.toHaveBeenCalled();
    expect(getToken()).toBe("good-token");
    unsubscribe();
  });

  it("does not let a throwing subscriber become the caller's error", async () => {
    setToken("stale-token");
    const unsubscribe = onUnauthorized(() => {
      throw new Error("subscriber exploded");
    });

    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Could not validate credentials" }, { status: 401 }),
    );
    await expect(api.me()).rejects.toThrow("Could not validate credentials");
    unsubscribe();
  });

  it("registers and keeps the returned session", async () => {
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ access_token: "tok-2", user: {}, business: {} }),
    );
    await api.register({ email: "a@b.com", password: "supersecret123", gstin: "27AAPFU0939F1ZV" });
    expect(getToken()).toBe("tok-2");
  });

  it("clears the token on logout", () => {
    setToken("tok-3");
    api.logout();
    expect(getToken()).toBeNull();
  });

  it("tells the server, so the token stops working there too", async () => {
    // Logout used to be the browser forgetting its copy: a token copied
    // before sign-out kept working for the rest of its day.
    setToken("tok-out");
    global.fetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
    api.logout();
    expect(getToken()).toBeNull(); // forgotten at once, whatever the server says
    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/auth/logout");
    expect(init.method).toBe("POST");
    // The request carries the token being signed out, not the cleared one.
    expect(init.headers.Authorization).toBe("Bearer tok-out");
  });

  it("still signs out locally when the server cannot be reached", async () => {
    setToken("tok-offline");
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    expect(() => api.logout()).not.toThrow();
    expect(getToken()).toBeNull();
    await new Promise((r) => setTimeout(r, 0)); // no unhandled rejection
  });

  describe("changing the password", () => {
    // The endpoint existed with nothing in the app calling it, so a password
    // that leaked could not be rotated by the person it belongs to.
    it("posts both passwords and keeps the session on the token it returns", async () => {
      setToken("tok-before");
      global.fetch.mockResolvedValueOnce(jsonResponse({ access_token: "tok-after" }));
      await api.changePassword("old-secret-1", "new-secret-2");
      const [url, init] = global.fetch.mock.calls[0];
      expect(url).toBe("/api/v1/auth/change-password");
      expect(init.method).toBe("POST");
      expect(init.headers.Authorization).toBe("Bearer tok-before");
      expect(JSON.parse(init.body)).toEqual({
        current_password: "old-secret-1",
        new_password: "new-secret-2",
      });
      // The change ends every token issued before it, this one included:
      // keeping the old token would sign the user out on their next click.
      expect(getToken()).toBe("tok-after");
    });

    it("leaves the session alone when the change is refused", async () => {
      setToken("tok-before");
      global.fetch.mockResolvedValueOnce(
        jsonResponse({ detail: "The current password is not correct." }, { status: 400 }),
      );
      await expect(api.changePassword("wrong", "new-secret-2")).rejects.toThrow(
        "The current password is not correct.",
      );
      expect(getToken()).toBe("tok-before");
    });
  });

  it("does not call the server when there is no session to end", () => {
    setToken(null);
    api.logout();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("posts an upload as multipart with the invoice type", async () => {
    setToken("tok-1");
    global.fetch.mockResolvedValueOnce(jsonResponse({ invoice: { id: 1 }, queued: false }));

    const file = new File(["invoice text"], "inv.txt", { type: "text/plain" });
    await api.uploadInvoice(file, "purchase");

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/invoices/upload");
    expect(options.body).toBeInstanceOf(FormData);
    expect(options.body.get("invoice_type")).toBe("purchase");
    // The browser must set the multipart boundary itself.
    expect(options.headers["Content-Type"]).toBeUndefined();
  });

  it("posts every file of a batch under the one field name the route reads", async () => {
    setToken("tok-1");
    global.fetch.mockResolvedValueOnce(jsonResponse({ items: [] }));

    const files = [
      new File(["one"], "a.txt", { type: "text/plain" }),
      new File(["two"], "b.txt", { type: "text/plain" }),
    ];
    await api.bulkUploadInvoices(files, "sales");

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/invoices/bulk");
    // `files: list[UploadFile] = File(...)` on the route is a *repeated* field,
    // not one field holding a list. Appending under any other name — "file",
    // the "files[]" some clients send — is a 422 naming a field the browser
    // never sent, and nothing on the page would say which. Pinned by name and
    // by count because getAll is what distinguishes the two mistakes: the
    // wrong name gives an empty list, one append gives a short one.
    expect(options.body.getAll("files").map((f) => f.name)).toEqual(["a.txt", "b.txt"]);
    expect(options.body.get("invoice_type")).toBe("sales");
    expect(options.headers["Content-Type"]).toBeUndefined();
  });

  it("defaults a batch to purchase, the type that claims credit", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ items: [] }));
    await api.bulkUploadInvoices([new File(["one"], "a.txt")]);

    // Matches the route's own default. A batch booked as sales by accident
    // claims input credit on the business's own output tax — see the comment
    // on the type toggle in UploadPage for why that direction is the costly one.
    expect(global.fetch.mock.calls[0][1].body.get("invoice_type")).toBe("purchase");
  });

  it("omits empty filters from the invoice query", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));
    await api.listInvoices({ invoice_type: "purchase", status: "", search: undefined, limit: 25 });

    const [url] = global.fetch.mock.calls[0];
    expect(url).toContain("invoice_type=purchase");
    expect(url).toContain("limit=25");
    expect(url).not.toContain("status=");
    expect(url).not.toContain("search=");
  });

  it("builds a bare invoice URL when there are no filters", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));
    await api.listInvoices();
    expect(global.fetch.mock.calls[0][0]).toBe("/api/v1/invoices");
  });

  it("handles a 204 with no body", async () => {
    global.fetch.mockResolvedValueOnce({ ok: true, status: 204, text: async () => "" });
    await expect(api.deleteInvoice(1)).resolves.toBeNull();
  });

  it("passes the period to the dashboard", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ period: "2026-04" }));
    await api.dashboard("2026-04");
    expect(global.fetch.mock.calls[0][0]).toBe("/api/v1/dashboard?period=2026-04");
  });

  it("sends a GSTR-2B as multipart with the period", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 1, period: "2026-04" }));
    const file = new File(["{}"], "gstr2b.json", { type: "application/json" });
    await api.importGstr2b(file, "2026-04");

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/reconciliation/gstr2b/import");
    expect(options.method).toBe("POST");
    expect(options.body.get("file").name).toBe("gstr2b.json");
    expect(options.body.get("period")).toBe("2026-04");
    // The browser sets the multipart boundary; setting it by hand breaks it.
    expect(options.headers["Content-Type"]).toBeUndefined();
  });

  it("omits the period rather than sending an empty one", async () => {
    // The server reads the period out of the file when none is given, and ""
    // is not a period it can parse.
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 1, period: "2026-04" }));
    await api.importGstr2b(new File(["{}"], "gstr2b.json"));

    expect(global.fetch.mock.calls[0][1].body.has("period")).toBe(false);
  });

  it("posts a reconciliation run", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 7 }));
    await api.reconcile("2026-04");

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/reconciliation/run");
    expect(JSON.parse(options.body)).toEqual({ period: "2026-04" });
  });

  it("sends a tolerance only when one was chosen", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 7 }));
    await api.reconcile("2026-04", "0");

    expect(JSON.parse(global.fetch.mock.calls[0][1].body)).toEqual({
      period: "2026-04",
      tolerance: "0",
    });
  });

  it("escapes the period in a GSTR-2B lookup", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 1 }));
    await api.getImported2b("2026-04");
    expect(global.fetch.mock.calls[0][0]).toBe("/api/v1/reconciliation/gstr2b/2026-04");
  });

  it("fetches the latest run for a period", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 7 }));
    await api.latestReconciliation("2026-04");
    expect(global.fetch.mock.calls[0][0]).toBe(
      "/api/v1/reconciliation/latest?period=2026-04",
    );
  });

  it("builds a bare reconciliation URL when there are no filters", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));
    await api.listReconciliations();
    expect(global.fetch.mock.calls[0][0]).toBe("/api/v1/reconciliation");
  });

  it("drops the filters that carry no value rather than sending them empty", async () => {
    // `?period=` is not the same request as no period at all — the first asks
    // the server to match the empty string. The filter runs over null and
    // undefined too, because a page holds an unset control as either.
    global.fetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

    await api.listReconciliations({
      period: "2026-04",
      status: "",
      limit: null,
      offset: undefined,
    });

    expect(global.fetch.mock.calls[0][0]).toBe("/api/v1/reconciliation?period=2026-04");
  });

  it("asks for the public usage stats without a token", async () => {
    setToken("a-token-that-must-not-leak");
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ businesses: 3, invoices: 7, gstin_lookups: 42 }),
    );

    const stats = await api.stats();

    expect(stats).toEqual({ businesses: 3, invoices: 7, gstin_lookups: 42 });
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/meta/stats");
    expect(init.headers.Authorization).toBeUndefined();
  });

  // What the user reads when the answer did not come from the application.
  // Both of these are invisible to a test that mocks an HTTP/1.1-shaped
  // response, and both are what production actually serves.
  describe("a response the application did not write", () => {
    it("explains a 502 whose body is an HTML page from the edge", async () => {
      // `JSON.parse` on this throws `Unexpected token '<'`, and that string is
      // what would otherwise land in the error banner.
      global.fetch.mockResolvedValueOnce({
        ok: false,
        status: 502,
        statusText: "",
        text: async () => "<html><head><title>502</title></head></html>",
      });

      await expect(api.me()).rejects.toThrow(
        "The server is having trouble (502). Please try again in a moment.",
      );
    });

    it("never raises an empty message when the body carries no detail", async () => {
      // HTTP/2 dropped the reason phrase, so `statusText` is "" in production.
      global.fetch.mockResolvedValueOnce(jsonResponse({ error: "nope" }, { status: 500 }));

      await expect(api.me()).rejects.toThrow("The server is having trouble (500)");
    });

    it("leaves the answering hop's reason phrase out of the sentence", async () => {
      // The phrase belongs to whoever answered, and on a 503 that is usually
      // not the API. It is also the wording the sentence in front of it was
      // written to replace, so quoting both says the same thing twice, once
      // in the voice of a stranger.
      global.fetch.mockResolvedValueOnce({
        ...jsonResponse(null, { status: 503 }),
        statusText: "Service Unavailable",
      });

      await expect(api.me()).rejects.toThrow(
        "The server is having trouble (503). Please try again in a moment.",
      );
    });

    it("says the same thing whether or not the wire format carried a phrase", async () => {
      // The one that would otherwise go unnoticed. HTTP/1.1 is what a
      // developer mocks and what a local proxy speaks; HTTP/2 is what
      // production serves. A message that differed between them is a bug
      // report nobody can reproduce from the screenshot.
      const withPhrase = {
        ...jsonResponse(null, { status: 502 }),
        statusText: "Bad Gateway",
      };
      const withoutPhrase = jsonResponse(null, { status: 502 });

      global.fetch.mockResolvedValueOnce(withPhrase);
      const overHttp1 = await api.me().catch((err) => err.message);
      global.fetch.mockResolvedValueOnce(withoutPhrase);
      const overHttp2 = await api.me().catch((err) => err.message);

      expect(overHttp1).toBe(overHttp2);
    });

    it("still prefers the server's own detail over the generic message", async () => {
      global.fetch.mockResolvedValueOnce(
        jsonResponse({ detail: "This business has been deactivated. Contact support to reactivate it." }, { status: 403 }),
      );

      await expect(api.me()).rejects.toThrow("This business has been deactivated. Contact support to reactivate it.");
    });

    it("names a rate limit as one", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse({}, { status: 429 }));

      await expect(api.me()).rejects.toThrow("Too many requests (429)");
    });

    it("leaves the reason phrase out of the unreadable-2xx message too", async () => {
      // The path where a phrase most reliably shows up, and the one where it
      // is least ours: a captive portal answering 200 with an HTML sign-in
      // page is by definition the hop that is not the API.
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: "OK",
        text: async () => "<html>Sign in to the network</html>",
      });

      await expect(api.me()).rejects.toThrow(
        "The server sent a response this app could not read (200).",
      );
    });

    it("reports a 2xx whose body is not JSON rather than throwing a parse error", async () => {
      // A truncated response, or a proxy that replaced the body on the way
      // back. The request succeeded; the answer is unusable, and saying so is
      // more use than `Unexpected end of JSON input`.
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        statusText: "",
        text: async () => "{partial",
      });

      await expect(api.me()).rejects.toThrow(
        "The server sent a response this app could not read (200).",
      );
    });

    it("treats an empty body on a 2xx as no content rather than unreadable", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse(null));

      await expect(api.me()).resolves.toBeNull();
    });

    it("does not tell a signed-in user to sign in again when they are refused", async () => {
      // A 403 here is authorisation, never authentication: a business the
      // caller is not a member of, or one that has been deactivated. `request`
      // deliberately keeps their token — only a 401 drops it — so the old
      // advice sent them to a login page that redirected straight back.
      setToken("t");
      global.fetch.mockResolvedValueOnce(jsonResponse(null, { status: 403 }));

      const error = await api.me().catch((err) => err);
      expect(error.message).toContain("You do not have access to this (403)");
      expect(error.message).not.toContain("not signed in");
      // Still signed in, which is the whole reason the sentence changed.
      expect(getToken()).toBe("t");
    });

    it("names an expired session on a 401", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse(null, { status: 401 }));

      await expect(api.me()).rejects.toThrow("Your session has expired (401)");
    });

    it("names a body-less 413 as the file being too big", async () => {
      // The API's own 413 carries a detail naming MAX_UPLOAD_MB. This one is
      // the proxy's, which answers before the request reaches the app at all
      // — and "Request failed (413)" is no help to someone holding a scan.
      global.fetch.mockResolvedValueOnce(jsonResponse(null, { status: 413 }));

      await expect(api.me()).rejects.toThrow("That file is too large to upload (413)");
    });
  });

  describe("a request that never reached the server", () => {
    it("replaces the browser's word for a network failure", async () => {
      // What `fetch` rejects with is the browser's: `Failed to fetch` in
      // Chrome, `Load failed` in Safari, `NetworkError when attempting to
      // fetch resource` in Firefox. All three went into the error banner
      // unchanged, and none of them says the request never arrived.
      global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

      const error = await api.me().catch((err) => err);
      expect(error.message).toBe(
        "Could not reach the server. Check your connection, or try again in a moment.",
      );
      // No status, because nothing answered. A caller that passes over a 404
      // quietly — a period with no GSTR-2B yet — must not pass over this too.
      expect(error.status).toBeUndefined();
    });

    it("says so plainly when the browser knows it is offline", async () => {
      // `onLine` lives on the prototype, so there is no own descriptor to save
      // and restore — deleting the shadowing property is what puts it back.
      // Getting that wrong leaves every later test in this file offline, which
      // is how it first showed up.
      Object.defineProperty(navigator, "onLine", { value: false, configurable: true });
      global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

      try {
        await expect(api.me()).rejects.toThrow("You appear to be offline");
      } finally {
        delete navigator.onLine;
      }
      expect(navigator.onLine).toBe(true);
    });

    it("keeps the original rejection as the cause", async () => {
      // The user gets the readable sentence; a console or an error reporter
      // still gets what actually happened.
      const underlying = new TypeError("Load failed");
      global.fetch.mockRejectedValueOnce(underlying);

      const error = await api.me().catch((err) => err);
      expect(error.cause).toBe(underlying);
    });

    it("lets an abort through untouched", async () => {
      // The app cancels its own superseded requests, and a banner reading
      // "Could not reach the server" every time a user keeps typing would be
      // worse than the stale rows the abort exists to prevent.
      const aborted = new DOMException("aborted", "AbortError");
      global.fetch.mockRejectedValueOnce(aborted);

      const error = await api.me().catch((err) => err);
      expect(isAbortError(error)).toBe(true);
    });

    it("reports a download that never reached the server the same way", async () => {
      // `downloadExport` carries its own copy of this path, and had its own
      // copy of the problem.
      global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

      await expect(api.downloadExport("gstr1", "json", "2026-04")).rejects.toThrow(
        "Could not reach the server",
      );
    });
  });

  // downloadExport does not go through `request` — it needs the raw response
  // to get at the blob and the Content-Disposition — so it carries its own
  // copy of the auth and error handling, and that copy needs its own tests.
  describe("the paid reconciliation report", () => {
    it("asks for an order for one run", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse({ run_id: 7, already_purchased: true }));

      await api.purchaseReport(7);

      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/api/v1/reconciliation/report/purchase");
      expect(options.method).toBe("POST");
      expect(JSON.parse(options.body)).toEqual({ run_id: 7 });
    });

    it("hands Checkout's response to the backend to verify", async () => {
      global.fetch.mockResolvedValueOnce(jsonResponse({ run_id: 7, purchased: true }));
      const payload = {
        run_id: 7,
        razorpay_order_id: "order_rpt",
        razorpay_payment_id: "pay_rpt",
        razorpay_signature: "sig",
      };

      await api.verifyReportPayment(payload);

      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/api/v1/reconciliation/report/verify");
      expect(JSON.parse(options.body)).toEqual(payload);
    });

    it("downloads the run's PDF with the bearer token", async () => {
      setToken("tok-1");
      global.fetch.mockResolvedValueOnce({
        ok: true,
        status: 200,
        blob: async () => new Blob(["%PDF"]),
        headers: { get: () => 'attachment; filename="reconciliation-run7.pdf"' },
      });

      const { filename } = await api.downloadReport(7);

      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/api/v1/reconciliation/7/report.pdf");
      expect(options.headers.Authorization).toBe("Bearer tok-1");
      expect(filename).toBe("reconciliation-run7.pdf");
    });
  });

  it("downloads the whole account with the bearer token", async () => {
    setToken("tok-1");
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      blob: async () => new Blob(["{}"]),
      headers: { get: () => 'attachment; filename="doaide-gst-export-x.json"' },
    });

    const { filename } = await api.exportAccount();

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/businesses/mine/export");
    expect(options.headers.Authorization).toBe("Bearer tok-1");
    expect(filename).toBe("doaide-gst-export-x.json");
  });

  describe("downloadExport", () => {
    function fileResponse(body, { status = 200, disposition = null } = {}) {
      return {
        ok: status >= 200 && status < 300,
        status,
        statusText: "",
        text: async () => (body === null ? "" : JSON.stringify(body)),
        blob: async () => new Blob(["csv,data"]),
        headers: { get: () => disposition },
      };
    }

    it("sends the bearer token a plain link could not carry", async () => {
      setToken("tok-1");
      global.fetch.mockResolvedValueOnce(fileResponse(null));

      await api.downloadExport("gstr1", "csv", "2026-04");

      const [url, options] = global.fetch.mock.calls[0];
      expect(url).toBe("/api/v1/filing/export/gstr1.csv?period=2026-04");
      expect(options.headers.Authorization).toBe("Bearer tok-1");
    });

    it("reads the filename out of the Content-Disposition", async () => {
      global.fetch.mockResolvedValueOnce(
        fileResponse(null, { disposition: 'attachment; filename="gstr1-2026-04.csv"' }),
      );

      const { filename } = await api.downloadExport("gstr1", "csv", "2026-04");

      expect(filename).toBe("gstr1-2026-04.csv");
    });

    it("names the file itself when the server did not", async () => {
      global.fetch.mockResolvedValueOnce(fileResponse(null));

      const { filename } = await api.downloadExport("gstr1", "csv", "2026-04");

      expect(filename).toBe("doaide-gst-export");
    });

    it("raises the server's reason when the export is refused", async () => {
      // A period with no invoices is a 400 with a detail worth showing —
      // saving that JSON to disk as "doaide-gst-export.csv" would be worse than
      // any error message.
      global.fetch.mockResolvedValueOnce(
        fileResponse({ detail: "Nothing to export for 2026-04" }, { status: 400 }),
      );

      await expect(api.downloadExport("gstr1", "csv", "2026-04")).rejects.toThrow(
        "Nothing to export for 2026-04",
      );
    });

    it("does not fall back to the status text when the error body is empty", async () => {
      global.fetch.mockResolvedValueOnce({
        ...fileResponse(null, { status: 502 }),
        statusText: "Bad Gateway",
      });

      await expect(api.downloadExport("gstr1", "csv", "2026-04")).rejects.toThrow(
        "The server is having trouble (502). Please try again in a moment.",
      );
    });

    it("still says something when the error body is empty over HTTP/2", async () => {
      // The reason phrase does not exist in HTTP/2 or HTTP/3, so `statusText`
      // is "" against the server this actually deploys behind — which is why
      // the status number, not the phrase, is what a message falls back to.
      // Falling back to `statusText` renders an error banner with nothing in
      // it exactly where production is.
      global.fetch.mockResolvedValueOnce(fileResponse(null, { status: 502 }));

      await expect(api.downloadExport("gstr1", "csv", "2026-04")).rejects.toThrow(
        "The server is having trouble (502)",
      );
    });

    it("does not surface a JSON parse error when the edge returns HTML", async () => {
      global.fetch.mockResolvedValueOnce({
        ...fileResponse(null, { status: 502 }),
        text: async () => "<html><body>502 Bad Gateway</body></html>",
      });

      await expect(api.downloadExport("gstr1", "csv", "2026-04")).rejects.toThrow(
        "The server is having trouble (502)",
      );
    });

    it("drops a token the export endpoint rejected", async () => {
      setToken("stale");
      global.fetch.mockResolvedValueOnce(fileResponse({ detail: "Not authenticated" }, { status: 401 }));

      await expect(api.downloadExport("gstr1", "csv", "2026-04")).rejects.toThrow();

      // Same rule as `request`: a refused credential is not retried.
      expect(getToken()).toBeNull();
    });
  });
});

describe("filing records", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("asks for the recent filing standings", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ as_of: "2026-05-06", items: [] }));

    await api.filingStatus();

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/filing/status",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("posts a filing record against the return type in the path", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 1 }, { status: 201 }));

    await api.recordFiled("gstr3b", { period: "2026-04", arn: "AA270426000000X" });

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/filing/gstr3b/filed");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({
      period: "2026-04",
      arn: "AA270426000000X",
    });
  });

  it("sends a record with no ARN when the caller omits it", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 1 }, { status: 201 }));

    await api.recordFiled("gstr1", { period: "2026-04" });

    expect(JSON.parse(global.fetch.mock.calls[0][1].body)).toEqual({ period: "2026-04" });
  });

  it("surfaces the server's reason for refusing a record", async () => {
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "A filing date of 2027-01-01 is in the future." }, { status: 422 }),
    );

    await expect(api.recordFiled("gstr1", { period: "2026-04" })).rejects.toThrow(
      "A filing date of 2027-01-01 is in the future.",
    );
  });
});

// `X-Business-Id` is the whole of the multi-GSTIN feature on this side of the
// wire: the backend resolves the tenant from it in `get_current_business`, and
// honours it only against a live membership. Which requests carry it, and
// which must not, is therefore a tenancy question rather than a plumbing one.
describe("acting for a linked business", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stores the id as a string, and reads back nothing when cleared", () => {
    setActiveBusinessId(7);
    expect(getActiveBusinessId()).toBe("7");
    setActiveBusinessId(null);
    expect(getActiveBusinessId()).toBeNull();
  });

  it("names the business on an authenticated request once one is switched to", async () => {
    setToken("tok-123");
    setActiveBusinessId(7);
    global.fetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

    await api.listInvoices();

    expect(global.fetch.mock.calls[0][1].headers["X-Business-Id"]).toBe("7");
  });

  it("sends nothing extra for a login that never switched", async () => {
    // The default is the caller's own tenant, and the backend must see exactly
    // the request shape it saw before this feature existed.
    setToken("tok-123");
    global.fetch.mockResolvedValueOnce(jsonResponse({ items: [], total: 0 }));

    await api.listInvoices();

    expect(global.fetch.mock.calls[0][1].headers).not.toHaveProperty("X-Business-Id");
  });

  it("never names a business on an unauthenticated request", async () => {
    // A stale id in localStorage must not ride along on the public lookups. It
    // identifies nobody without a token, and `auth: false` is the statement
    // that this request carries no identity at all.
    setActiveBusinessId(7);
    global.fetch.mockResolvedValueOnce(jsonResponse({ valid: true }));

    await api.validateGstin("27AAPFU0939F1ZV");

    expect(global.fetch.mock.calls[0][1].headers).not.toHaveProperty("X-Business-Id");
  });

  it("carries it on an export, which fetches outside `request`", async () => {
    // downloadExport builds its own headers, so it can and did drift from the
    // rule above — an export would then have come from the wrong business,
    // which is the one place that mistake produces a file to file with.
    setToken("tok-123");
    setActiveBusinessId(7);
    global.fetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "",
      text: async () => "",
      blob: async () => new Blob(["csv,data"]),
      headers: { get: () => null },
    });

    await api.downloadExport("gstr1", "csv", "2026-04");

    expect(global.fetch.mock.calls[0][1].headers["X-Business-Id"]).toBe("7");
  });

  it("forgets the business on logout, since the next sign-in may be another login", async () => {
    setToken("tok-123");
    setActiveBusinessId(7);

    api.logout();

    expect(getToken()).toBeNull();
    expect(getActiveBusinessId()).toBeNull();
  });
});

describe("alerts", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("asks for open alerts when a scope is given", async () => {
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ items: [], total: 0, open_total: 0, limit: 50, offset: 0 }),
    );

    await api.listAlerts({ scope: "open" });

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/alerts?scope=open",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("sends no query at all when nothing is filtered", async () => {
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ items: [], total: 0, open_total: 0, limit: 50, offset: 0 }),
    );

    await api.listAlerts();

    expect(global.fetch.mock.calls[0][0]).toBe("/api/v1/alerts");
  });

  it("posts a dismissal against the alert's own id", async () => {
    // The whole reason this method exists: the daily sweep will not raise an
    // alert it has already been told about, and until there was a client for
    // this endpoint no caller could ever tell it.
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 4, status: "dismissed" }));

    await api.dismissAlert(4);

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe("/api/v1/alerts/4/dismiss");
    expect(options.method).toBe("POST");
  });

  it("posts a read against the alert's own id", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse({ id: 4, status: "read" }));

    await api.markAlertRead(4);

    expect(global.fetch.mock.calls[0][0]).toBe("/api/v1/alerts/4/read");
    expect(global.fetch.mock.calls[0][1].method).toBe("POST");
  });

  it("carries the bearer token, since alerts are tenant-scoped", async () => {
    setToken("tok-123");
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ items: [], total: 0, open_total: 0, limit: 50, offset: 0 }),
    );

    await api.listAlerts();

    expect(global.fetch.mock.calls[0][1].headers.Authorization).toBe("Bearer tok-123");
  });

  it("surfaces the server's reason for refusing", async () => {
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Alert not found" }, { status: 404 }),
    );

    await expect(api.dismissAlert(999)).rejects.toThrow("Alert not found");
  });
});

describe("a browser that will not store anything", () => {
  // Blocked site data, a sandboxed iframe and a full quota all throw on
  // `localStorage` access instead of answering null. This module read it bare,
  // and `AuthProvider` calls `getToken()` inside an effect — so the throw
  // reached the outer ErrorBoundary and the whole app became the crash screen,
  // on every reload, with no way past it.

  /**
   * Run *body* with a `localStorage` that throws on every operation.
   *
   * Restored in a `finally`, and the session keys are cleared through a write
   * that succeeds, because the in-memory fallback is sticky until one does —
   * leaving an entry behind would shadow real storage for every later test in
   * this file.
   */
  async function withBlockedStorage(body) {
    const real = globalThis.localStorage;
    const refuse = () => {
      throw new DOMException("The operation is insecure.", "SecurityError");
    };
    Object.defineProperty(globalThis, "localStorage", {
      value: { getItem: refuse, setItem: refuse, removeItem: refuse, clear: refuse },
      configurable: true,
      writable: true,
    });
    try {
      return await body();
    } finally {
      Object.defineProperty(globalThis, "localStorage", {
        value: real,
        configurable: true,
        writable: true,
      });
      setToken(null);
      setActiveBusinessId(null);
      localStorage.clear();
    }
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("answers no token rather than throwing", async () => {
    await withBlockedStorage(() => {
      expect(getToken()).toBeNull();
      expect(getActiveBusinessId()).toBeNull();
    });
  });

  it("still signs in, for the life of the tab", async () => {
    // What is lost is precisely stated: the session does not survive a reload.
    // Signing in, and every authenticated request after it, still work — which
    // is the difference between a degraded app and an unusable one.
    await withBlockedStorage(async () => {
      global.fetch = vi.fn().mockResolvedValue(
        jsonResponse({ access_token: "tok-blocked", token_type: "bearer" }),
      );
      await api.login("owner@example.com", "supersecret123");
      expect(getToken()).toBe("tok-blocked");

      global.fetch = vi.fn().mockResolvedValue(jsonResponse({ items: [], total: 0 }));
      await api.listInvoices();

      expect(global.fetch.mock.calls[0][1].headers.Authorization).toBe("Bearer tok-blocked");
    });
  });

  it("does not let a token it could not delete come back", async () => {
    // The sign-out path. `removeItem` throws too, so the value written before
    // storage went blind is still sitting there — and returning it would put a
    // signed-out browser back into a session.
    setToken("tok-from-a-working-browser");
    await withBlockedStorage(() => {
      setToken(null);
      expect(getToken()).toBeNull();
    });
  });

  it("switches business in memory, which is what X-Business-Id needs", async () => {
    await withBlockedStorage(async () => {
      setActiveBusinessId(9);
      expect(getActiveBusinessId()).toBe("9");

      global.fetch = vi.fn().mockResolvedValue(jsonResponse({ id: 1 }));
      await api.me();

      expect(global.fetch.mock.calls[0][1].headers["X-Business-Id"]).toBe("9");
    });
  });

  it("goes back to real storage once a write succeeds", async () => {
    // A quota freed by another tab. The fallback has to stop shadowing, or the
    // session silently stops persisting for the rest of the browser's life.
    await withBlockedStorage(() => setToken("tok-in-memory"));

    setToken("tok-stored");
    expect(localStorage.getItem("gstbot_token")).toBe("tok-stored");
    expect(getToken()).toBe("tok-stored");
  });
});

describe("a refusal the API gave its own code", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
    window.umami = { track: vi.fn() };
  });

  afterEach(() => {
    delete window.umami;
  });

  const paywall = {
    detail: "This feature requires a paid subscription. Visit /pricing to upgrade.",
    error: { code: "paid_plan_required", status: 403, message: "..." },
  };

  it("carries error.code, which is what the catalog says to branch on", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse(paywall, { status: 403 }));
    const err = await api.itc("2026-04").catch((e) => e);
    expect(err.status).toBe(403);
    expect(err.code).toBe("paid_plan_required");
  });

  it("counts a paywall hit against the feature, not the business's rows", async () => {
    global.fetch.mockResolvedValueOnce(jsonResponse(paywall, { status: 403 }));
    await api.itc("2026-04").catch(() => {});
    expect(window.umami.track).toHaveBeenCalledWith("paywall_hit", { feature: "/itc" });
  });

  it("counts running out of the monthly uploads as a paywall hit too", async () => {
    // P24 M18: the commonest way the free plan stops being enough is a 402,
    // not the 403 feature gate, and it was missing from the funnel.
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Plan 'free' allows 50 invoices per month." }, { status: 402 }),
    );
    await api.itc("2026-04").catch(() => {});
    expect(window.umami.track).toHaveBeenCalledWith("paywall_hit", { feature: "/itc" });
  });

  it("does not count a role refusal as a paywall hit", async () => {
    global.fetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Viewers cannot write", error: { code: "forbidden" } }, { status: 403 }),
    );
    const err = await api.rescoreSuppliers().catch((e) => e);
    expect(err.code).toBe("forbidden");
    expect(window.umami.track).not.toHaveBeenCalled();
  });

  it("has no code when the body was not the API's own", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 502,
      statusText: "",
      text: async () => "<html>Bad Gateway</html>",
    });
    const err = await api.me().catch((e) => e);
    expect(err.code).toBeNull();
  });
});

describe("a refusal whose body could not be read", () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  it("still says what to try, whatever the status", async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      statusText: "",
      text: async () => "<html>Conflict</html>",
    });
    const err = await api.me().catch((e) => e);
    expect(err.message).toBe(
      "That could not be completed (409). Check what you entered and try again, or reload the page.",
    );
  });
});

describe("featurePath", () => {
  it.each([
    ["/itc?period=2026-04", "/itc"],
    ["/reconciliation/12/report.pdf", "/reconciliation/:id/report.pdf"],
    ["/invoices/7", "/invoices/:id"],
    ["/filing/gstr1", "/filing/gstr1"],
  ])("%s -> %s", (path, feature) => {
    expect(featurePath(path)).toBe(feature);
  });
});

describe("the business a session acts for does not outlive the session", () => {
  // Only an explicit sign-out cleared it. A token that expired, and every way
  // a session starts — password, registration, a reset — left the previous
  // session's "acting for" business in place, so the next login on that
  // browser began pointed at it: a 403 for someone with no access to it, or a
  // silent start in another person's client for someone with access.
  function ok(body) {
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }

  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn();
  });

  afterEach(() => vi.restoreAllMocks());

  it("is forgotten when the token is refused", async () => {
    setToken("expired");
    setActiveBusinessId(7);
    global.fetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Token has expired" }), { status: 401 }),
    );
    await expect(api.dashboard()).rejects.toThrow();
    expect(getActiveBusinessId()).toBeNull();
  });

  it.each([
    ["signing in", () => api.login("a@b.com", "supersecret123")],
    ["registering", () => api.register({ email: "a@b.com", password: "supersecret123" })],
    ["resetting a password", () => api.resetPassword("reset-tok", "a-fresh-passphrase")],
  ])("is not carried into a new session started by %s", async (_, start) => {
    setActiveBusinessId(7);
    global.fetch.mockResolvedValueOnce(ok({ access_token: "new", token_type: "bearer" }));
    await start();
    global.fetch.mockResolvedValueOnce(ok({ id: 1 }));
    await api.me();
    expect(global.fetch.mock.calls.at(-1)[1].headers["X-Business-Id"]).toBeUndefined();
  });

  it("is kept when a password change continues the same session", async () => {
    setToken("tok");
    setActiveBusinessId(7);
    global.fetch.mockResolvedValueOnce(ok({ access_token: "rotated", token_type: "bearer" }));
    await api.changePassword("old-secret-1", "new-secret-2");
    expect(getActiveBusinessId()).toBe("7");
  });
});
