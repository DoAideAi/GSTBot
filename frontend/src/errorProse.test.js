/**
 * What the app says when it refuses, held to the standard a person reads it at.
 *
 * `backend/tests/test_error_prose.py` does this for the API, and its opening
 * argument applies here unchanged: every other test owns the *shape* of a
 * failure — that a banner appears, that a field is marked, that the token is
 * dropped — and none of them says anything about the sentence, which is the
 * whole of what the user gets. A refusal can put the right element on screen
 * and still be useless. "Unexpected token '<'", "Load failed", "Cannot read
 * properties of null (reading 'total')" would each satisfy every assertion in
 * this suite about the element they appear in.
 *
 * The frontend's messages come from two places, and only one of them can be
 * read out of the source:
 *
 *   * the sentences somebody wrote — in `validate.js`, in a page's own
 *     refusal, in a fallback. Swept out of the files themselves rather than
 *     out of the screens somebody remembered to test.
 *   * the sentences `lib/api.js` *builds*, which exist only as a status code
 *     and a template until a response arrives. Those are gone and got: every
 *     status the client can meet is driven through it and the message it
 *     produces is read off the error it throws.
 *
 * The rules are the backend's, for the reason that file gives — a test cannot
 * tell whether a sentence is kind, but it can tell that the sentence names a
 * type, quotes an identifier, or is four hundred characters of a stack frame,
 * and those are how this goes wrong in practice. They are restated rather than
 * imported because the two suites do not share a runtime, and a frontend list
 * needs frontend words: a browser refusal fails by saying `fetch`, `JSON` or
 * `localStorage`, never by saying `psycopg`.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import * as espree from "espree";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, errorMessage, setToken } from "./lib/api";

const SRC = path.dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// What counts as jargon
// ---------------------------------------------------------------------------

// Words that mean something to whoever wrote the line and nothing to a business
// owner reading it at 11pm on the 20th. Matched case-insensitively on word
// boundaries, so "the JSON" fails and "reasons" does not.
const JARGON = [
  "traceback", "stack trace", "stacktrace", "exception", "assertion",
  "null", "undefined", "nan", "unhandled", "panic",
  // The browser's own vocabulary. Every one of these has been the whole of an
  // error banner at some point in this app's history: `fetch` rejects with
  // "Failed to fetch", `JSON.parse` with "Unexpected token '<'", a blocked
  // `localStorage` with "SecurityError".
  "fetch", "json", "xhr", "cors", "localstorage", "sessionstorage", "cookie",
  "networkerror", "syntaxerror", "typeerror", "referenceerror", "securityerror",
  "quotaexceedederror", "aborterror", "domexception", "promise", "async",
  "react", "render", "component", "props", "hook", "dom", "http", "https",
  "url", "uri", "token", "bearer", "cache", "bundle", "regex", "utf-8",
  "mimetype", "timeout", "internal server error", "bad request",
  "unprocessable entity",
];

// A JavaScript identifier that has escaped into prose: two lowercase words
// joined by an underscore. `total_value`, `invoice_type`, `business_id`.
const IDENTIFIER = /\b[a-z][a-z0-9]*_[a-z0-9_]+\b/;

// The shapes a value leaves behind when an object is interpolated into a
// message that meant to interpolate one of its fields.
const OBJECT_MARKERS = ["[object ", "function ", "=> ", "{\"", "[{", "undefined"];

// Long enough for two sentences and a thing to do about it. Past this the
// message is a log line that took a wrong turn.
const MAX_LENGTH = 220;

// An FAQ answer is reference prose the reader asked for, not a message
// interrupting them: the turnover limits by state, the parts of an e-way bill.
// Eight of them ran to 230-260 characters and failed the message cap, which
// was never written for them. They keep every other rule here; the length
// bar is only raised to what a short paragraph needs.
const MAX_ANSWER_LENGTH = 400;

/** The whole standard, in one place, so both sweeps hold to the same one. */
function assertReadsAsProse(message, where, { maxLength = MAX_LENGTH } = {}) {
  expect(message.trim(), `${where}: empty message`).not.toBe("");
  expect(message.length, `${where}: ${message.length} characters — ${message}`).toBeLessThanOrEqual(
    maxLength,
  );

  const lowered = message.toLowerCase();
  for (const word of JARGON) {
    const jargon = new RegExp(`(?<![a-z])${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![a-z])`);
    expect(jargon.test(lowered), `${where}: says "${word}" — ${message}`).toBe(false);
  }

  const identifier = IDENTIFIER.exec(message);
  expect(identifier, `${where}: names "${identifier?.[0]}" — ${message}`).toBeNull();

  for (const marker of OBJECT_MARKERS) {
    expect(message.includes(marker), `${where}: carries "${marker}" — ${message}`).toBe(false);
  }

  // A sentence, not a label. The first character is the one place a message
  // written as a log line gives itself away, and `{}` leads several of these
  // because the thing being refused — a filename, a period — is what the
  // reader is looking for.
  const first = message.replace(/^["'₹]+/, "")[0];
  expect(
    first === first.toUpperCase() || first === "{",
    `${where}: does not start a sentence — ${message}`,
  ).toBe(true);
}

// ---------------------------------------------------------------------------
// Reading the sentences out of the source
// ---------------------------------------------------------------------------

function sourceFiles(dir) {
  const found = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    // `src/test/` is the fixtures and the fake backend — not shipped, and its
    // canned refusals are copies of the server's wording rather than wording
    // this app owns.
    if (entry.isDirectory() && entry.name !== "test") found.push(...sourceFiles(full));
    else if (/\.jsx?$/.test(entry.name) && !/\.test\.jsx?$/.test(entry.name)) found.push(full);
  }
  return found.sort();
}

/**
 * Every string a node can evaluate to, with interpolations as `{}`.
 *
 * A template's substitutions are runtime data — a filename, a period, a rupee
 * figure — and are not what is under test; the words around them are. So they
 * collapse to a placeholder rather than making the message unreadable. A
 * ternary yields both of its branches, because both are sentences somebody
 * wrote and either can be the one on screen.
 *
 * A `+` chain or a ternary yields nothing unless *every* part of it is a
 * string this can read. Half of one is not a sentence — the second line of
 * `"You do not have access to this. If you have just been given " + "access,
 * sign out and back in."` starts lowercase and would be reported as a message
 * that does not begin with a capital. Yielding nothing sends the walk into the
 * operands instead, where each is judged on its own and a fragment that is
 * plainly not a whole sentence falls out of the sweep rather than into it.
 */
function literals(node) {
  if (!node) return [];
  if (node.type === "Literal" && typeof node.value === "string") return [node.value];
  if (node.type === "TemplateLiteral") {
    return [node.quasis.map((quasi) => quasi.value.cooked).join("{}")];
  }
  if (node.type === "BinaryExpression" && node.operator === "+") {
    const left = literals(node.left);
    const right = literals(node.right);
    return left.length === 1 && right.length === 1 ? [left[0] + right[0]] : [];
  }
  if (node.type === "ConditionalExpression") {
    const consequent = literals(node.consequent);
    const alternate = literals(node.alternate);
    return consequent.length && alternate.length ? [...consequent, ...alternate] : [];
  }
  return [];
}

/**
 * Walk the tree, reading each node the moment it can be read as a string.
 *
 * A node that yields a string is not descended into: its operands and quasis
 * are the parts of that string, and collecting them again would report the
 * halves of a joined sentence as sentences in their own right.
 */
function walk(node, visit, context = null) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node)) {
    for (const child of node) walk(child, visit, context);
    return;
  }
  if (typeof node.type === "string") {
    const texts = literals(node);
    if (texts.length > 0) {
      for (const text of texts) visit(node, text, context === "answer");
      return;
    }
  }
  // Carries which property a value sits under, for the one distinction this
  // walk makes: an FAQ answer — `a:` in a page's FAQ list, or `text:` inside a
  // schema.org `acceptedAnswer` — is reference prose rather than a message.
  if (node.type === "Property") {
    const key = node.key?.name ?? node.key?.value;
    const next =
      key === "acceptedAnswer"
        ? "acceptedAnswer"
        : key === "a" || (key === "text" && context === "acceptedAnswer")
          ? "answer"
          : null;
    walk(node.value, visit, next);
    return;
  }
  for (const key of Object.keys(node)) walk(node[key], visit, context);
}

/**
 * Every sentence in the shipped source, as `[where, message]`.
 *
 * "Sentence" is the definition this sweep turns on, and it is deliberately
 * about shape rather than about intent: two words and a full stop. Nothing
 * else in these files looks like that. A class list (`"banner banner-error"`),
 * a field label (`"Counterparty name"`), a page title, an ARIA name — none of
 * them ends in a stop, so the rule separates the strings written for a reader
 * from the strings written for the machine without needing a list of which is
 * which.
 *
 * It also sweeps wider than errors, and that is intended. A jargon bar that
 * applied only to refusals would let the empty state next to one say anything
 * it liked.
 */
function sentences() {
  const found = [];
  for (const file of sourceFiles(SRC)) {
    const tree = espree.parse(fs.readFileSync(file, "utf8"), {
      ecmaVersion: "latest",
      sourceType: "module",
      ecmaFeatures: { jsx: true },
      loc: true,
    });
    walk(tree, (node, text, answer) => {
      if (!/[a-z]{2}\s+\S/i.test(text)) return;
      if (!/[.!?]$/.test(text.trim())) return;
      found.push([`${path.basename(file)}:${node.loc.start.line}`, text, answer]);
    });
  }
  return found;
}

const SENTENCES = sentences();

// The backend file carries a list of exceptions whose message a user never
// reads, because there the distinction is invisible in the source: whether
// `str(exc)` becomes a `detail` depends on some router elsewhere. Here the
// same distinction falls out of the rule above and needs no list. The messages
// written for a developer are invariant violations — "useAuth must be used
// within AuthProvider" — and they are phrases, not sentences, so the sweep
// does not pick them up. What they *are* is thrown during render, which means
// the error boundary catches them; and the boundary now introduces whatever it
// caught as a reference to quote rather than as an explanation, which is the
// one place in this app where a programmer's words are the right words.

describe("every sentence the app can put on screen", () => {
  it("found the sentences", () => {
    // A parametrised sweep over an empty list passes every case it has. If a
    // change to how the source is read stops it finding anything, that is a
    // green suite testing nothing at all.
    expect(SENTENCES.length).toBeGreaterThanOrEqual(40);
  });

  it("is reading the real wording", () => {
    // The other half of the same guard: one message that is definitely there,
    // pinned, so a parser that silently returns fragments fails here rather
    // than passing a sweep of nothing.
    const messages = SENTENCES.map(([, message]) => message);
    expect(messages).toContain("That does not look like a GSTIN. The format is 27AAPFU0939F1ZV.");
    expect(messages.some((message) => message.includes("monthly allowance"))).toBe(true);
  });

  it("tells an FAQ answer from a message", () => {
    // Both shapes are read as answers, and a message is not.
    const answers = SENTENCES.filter(([, , answer]) => answer);
    expect(answers.some(([where]) => where.startsWith("RegistrationCheckerPage.jsx"))).toBe(true);
    expect(answers.some(([where]) => where.startsWith("CompositionSchemePage.jsx"))).toBe(true);
    const gstinMessage = SENTENCES.find(([, m]) => m.startsWith("That does not look like a GSTIN."));
    expect(gstinMessage[2]).toBe(false);
  });

  it.each(SENTENCES)("%s reads as prose", (where, message, answer) => {
    assertReadsAsProse(message, where, answer ? { maxLength: MAX_ANSWER_LENGTH } : undefined);
  });
});

// ---------------------------------------------------------------------------
// And the same standard, applied to what the client actually throws
// ---------------------------------------------------------------------------

/** A response shaped as production serves them: HTTP/2, so no reason phrase. */
function response(status, { body = "", ok = status >= 200 && status < 300 } = {}) {
  return {
    ok,
    status,
    statusText: "",
    text: async () => body,
    headers: { get: () => null },
  };
}

/** The message `api` rejects with, or "" when it resolved. */
async function messageFrom(call) {
  return call.then(
    () => "",
    (err) => err.message,
  );
}

describe("what the API client says about a response", () => {
  beforeEach(() => {
    setToken(null);
    global.fetch = vi.fn();
  });

  // Every refusal the client can meet, not the handful with a branch written
  // for them. `statusMessage` answers for a range and a default as well as for
  // named codes, so a sweep of 400 and 500 would leave the sentence a 418 or a
  // 599 produces — the ones nobody pictured — unread by anything.
  const REFUSALS = Array.from({ length: 200 }, (unused, offset) => 400 + offset);

  it.each(REFUSALS)("words a %i with no body of its own", async (status) => {
    // No `detail`: what is under test is the sentence *this app* falls back
    // to. A body carrying the server's own wording is the backend's to answer
    // for, and `test_error_prose.py` holds it to this same bar.
    global.fetch.mockResolvedValueOnce(response(status, { body: "{}" }));

    const message = await messageFrom(api.me());
    assertReadsAsProse(message, `GET /auth/me answered ${status}`);
    // The number is the reference support asks for, and the only part of the
    // response the sentence quotes.
    expect(message).toContain(`${status}`);
  });

  it("says the connection failed rather than repeating the browser", async () => {
    // "Failed to fetch" in Chrome, "Load failed" in Safari, "NetworkError when
    // attempting to fetch resource" in Firefox. The most common failure this
    // product has, and the least informative thing any of them says.
    global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    assertReadsAsProse(await messageFrom(api.me()), "a request that never arrived");
  });

  it("says so plainly when the browser knows it is offline", async () => {
    const online = Object.getOwnPropertyDescriptor(Navigator.prototype, "onLine");
    Object.defineProperty(navigator, "onLine", { configurable: true, value: false });
    try {
      global.fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
      assertReadsAsProse(await messageFrom(api.me()), "a request made offline");
    } finally {
      if (online) Object.defineProperty(Navigator.prototype, "onLine", online);
      else delete navigator.onLine;
    }
  });

  it("explains an answer that did not come from the application", async () => {
    // A 502 page from the edge, a captive portal, a middlebox. `JSON.parse`
    // throws `Unexpected token '<'` on every one of them, and that string is
    // what used to reach the banner on the one occasion the user most needs
    // to be told the server is unreachable.
    global.fetch.mockResolvedValueOnce(
      response(502, { body: "<html><head><title>502 Bad Gateway</title></head></html>" }),
    );

    assertReadsAsProse(await messageFrom(api.me()), "an HTML error page from the edge");
  });

  it("explains a success whose body it could not read", async () => {
    global.fetch.mockResolvedValueOnce(response(200, { body: "{partial" }));

    assertReadsAsProse(await messageFrom(api.me()), "a 2xx that was not JSON");
  });

  it("never renders an empty banner when a refusal carries no detail at all", async () => {
    // The failure this replaced: `statusText` is "" over HTTP/2, which is what
    // production serves, so falling back to it put an error banner on screen
    // with nothing written in it.
    for (const body of ["", "{}", '{"detail": null}', '{"detail": ""}']) {
      global.fetch.mockResolvedValueOnce(response(503, { body }));
      const message = await messageFrom(api.me());
      expect(message.trim(), `503 with body ${JSON.stringify(body)}`).not.toBe("");
    }
  });

  it("keeps the server's own sentence when there is one", async () => {
    // The client words a refusal only when the API did not. Overriding a
    // detail the backend wrote would throw away the one message with the
    // context to say *why* — which period, which role, which invoice.
    global.fetch.mockResolvedValueOnce(
      response(403, {
        body: JSON.stringify({
          detail:
            "Your role on this business is viewer, which cannot make changes. " +
            "Ask an owner or an accountant.",
        }),
      }),
    );

    const message = await messageFrom(api.me());
    expect(message).toBe(
      "Your role on this business is viewer, which cannot make changes. " +
        "Ask an owner or an accountant.",
    );
    assertReadsAsProse(message, "a 403 the API worded itself");
  });

  it("flattens a field-by-field refusal into one readable line", async () => {
    // A 422's detail is a list, and the banner is one line. Joining them with
    // the raw objects is how `[object Object]` reaches a user.
    const message = errorMessage({
      detail: [
        // As the API sends them: it strips pydantic's "Value error, " prefix,
        // which used to reach the banner verbatim.
        { loc: ["body", "gstin"], msg: "A GSTIN is 15 characters." },
        { loc: ["body", "password"], msg: "Use at least 8 characters." },
      ],
    });

    assertReadsAsProse(message, "a 422 from the register form");
  });
});
