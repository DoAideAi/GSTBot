import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ADVISOR_CUT_OFF,
  ADVISOR_HISTORY_SENT,
  ADVISOR_TURN_MAX_CHARS,
  ADVISOR_UNREACHABLE,
  advisorErrorMessage,
  advisorFailure,
  advisorHistory,
  streamAdvisor,
} from "./advisor";

describe("advisorHistory", () => {
  it("keeps only the recent turns, newest last", () => {
    const messages = Array.from({ length: 60 }, (_, i) => ({ role: "user", text: `t${i}` }));
    const sent = advisorHistory(messages);
    expect(sent).toHaveLength(ADVISOR_HISTORY_SENT);
    expect(sent[0].text).toBe(`t${60 - ADVISOR_HISTORY_SENT}`);
    expect(sent.at(-1).text).toBe("t59");
  });

  it("cuts a long reply to what the API accepts instead of failing the next question", () => {
    const [turn] = advisorHistory([{ role: "assistant", text: "x".repeat(9000) }]);
    expect(turn).toEqual({ role: "model", text: "x".repeat(ADVISOR_TURN_MAX_CHARS) });
  });

  it("maps every non-user role to the model's and tolerates a missing text", () => {
    expect(advisorHistory([{ role: "user", text: "q" }, { role: "assistant" }])).toEqual([
      { role: "user", text: "q" },
      { role: "model", text: "" },
    ]);
  });
});

describe("advisorFailure", () => {
  const res = (status, body) => ({
    status,
    json: () => (body instanceof Error ? Promise.reject(body) : Promise.resolve(body)),
  });

  it("shows the server's explanation when it gives one", async () => {
    await expect(
      advisorFailure(res(504, { detail: "The AI advisor took too long to answer. Ask again." })),
    ).resolves.toBe("The AI advisor took too long to answer. Ask again.");
  });

  it("explains a rate limit and falls back for anything without a readable detail", async () => {
    await expect(advisorFailure(res(429, {}))).resolves.toMatch(/wait a minute/);
    await expect(advisorFailure(res(422, { detail: [{ msg: "x" }] }))).resolves.toMatch(/could not answer/);
    await expect(advisorFailure(res(502, new SyntaxError("html")))).resolves.toMatch(/could not answer/);
  });
});


function sse(events, { close = true } = {}) {
  const encoder = new TextEncoder();
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
  // Split mid-event so the reader has to stitch chunks back together.
  const cut = Math.floor(text.length / 2);
  const pieces = [text.slice(0, cut), text.slice(cut)].filter(Boolean);
  return {
    ok: true,
    status: 200,
    // Pulled one piece per read, so a dropped connection fails the read after
    // the text has arrived (erroring in start() would discard what was queued).
    body: new ReadableStream({
      pull(controller) {
        const next = pieces.shift();
        if (next !== undefined) controller.enqueue(encoder.encode(next));
        else if (close) controller.close();
        else controller.error(new TypeError("network error"));
      },
    }),
  };
}

async function failure(promise) {
  try {
    await promise;
  } catch (err) {
    return advisorErrorMessage(err);
  }
  throw new Error("expected a failure");
}

describe("streamAdvisor", () => {
  afterEach(() => vi.restoreAllMocks());

  it("joins the chunks as they arrive, keeping their spacing", async () => {
    global.fetch = vi.fn(() => Promise.resolve(sse([{ t: "GST " }, { t: "is " }, { t: "18%." }, { done: true }])));
    const seen = [];
    const answer = await streamAdvisor("Rate?", [], (text) => seen.push(text));
    expect(answer).toBe("GST is 18%.");
    expect(seen.at(-1)).toBe("GST is 18%.");
    expect(global.fetch.mock.calls[0][0]).toBe("/api/v1/advisor/ask/stream");
  });

  it("shows the server's sentence for an error event", async () => {
    global.fetch = vi.fn(() => Promise.resolve(sse([{ error: "The AI advisor is overloaded right now." }])));
    expect(await failure(streamAdvisor("Hi", [], () => {}))).toBe("The AI advisor is overloaded right now.");
  });

  it("says the answer was cut off when the stream stops partway", async () => {
    global.fetch = vi.fn(() => Promise.resolve(sse([{ t: "GST on gold " }], { close: false })));
    const seen = [];
    expect(await failure(streamAdvisor("Gold?", [], (t) => seen.push(t)))).toBe(ADVISOR_CUT_OFF);
    expect(seen).toEqual(["GST on gold "]);
  });

  it("does not pass off a stream that ended without 'done' as a whole answer", async () => {
    global.fetch = vi.fn(() => Promise.resolve(sse([{ t: "Partial" }])));
    expect(await failure(streamAdvisor("Hi", [], () => {}))).toBe(ADVISOR_CUT_OFF);
  });

  it("calls the advisor unreachable when nothing came back at all", async () => {
    global.fetch = vi.fn(() => Promise.resolve(sse([])));
    expect(await failure(streamAdvisor("Hi", [], () => {}))).toBe(ADVISOR_UNREACHABLE);
  });

  it("replaces the browser's own error with a sentence", async () => {
    global.fetch = vi.fn(() => Promise.reject(new TypeError("Failed to fetch")));
    expect(await failure(streamAdvisor("Hi", [], () => {}))).toBe(ADVISOR_UNREACHABLE);
  });

  it("falls back to the one-shot answer when the browser cannot read a stream", async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, status: 200, body: null })
      .mockResolvedValueOnce({ ok: true, status: 200, json: () => Promise.resolve({ reply: "18%." }) });
    const seen = [];
    expect(await streamAdvisor("Rate?", [], (t) => seen.push(t))).toBe("18%.");
    expect(global.fetch.mock.calls[1][0]).toBe("/api/v1/advisor/ask");
    expect(seen).toEqual(["18%."]);
  });
});
