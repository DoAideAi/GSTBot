import { describe, expect, it } from "vitest";
import { ADVISOR_HISTORY_SENT, ADVISOR_TURN_MAX_CHARS, advisorFailure, advisorHistory } from "./advisor";

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
