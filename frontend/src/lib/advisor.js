/**
 * The conversation history `POST /api/v1/advisor/ask` is sent with a question.
 *
 * The backend forwards only the last dozen turns to the model and refuses a
 * request with more than fifty, or with any turn over 4,000 characters. The
 * chat widget sent the whole conversation as it stood, so it hit the first
 * limit at the 26th exchange — and the second one sooner, the moment a long
 * reply came back, since replies run to 1,024 tokens. Either way every later
 * question was a 422, after each request had grown larger than the last.
 */

/** Earlier messages sent with a question — the number the backend forwards. */
export const ADVISOR_HISTORY_SENT = 12;

/** Per-message cap, the backend's `HistoryMessage.text` limit. */
export const ADVISOR_TURN_MAX_CHARS = 4000;

/** The wire form of *messages*: the recent turns, in roles the API knows. */
export function advisorHistory(messages) {
  return messages.slice(-ADVISOR_HISTORY_SENT).map((m) => ({
    role: m.role === "user" ? "user" : "model",
    text: String(m.text ?? "").slice(0, ADVISOR_TURN_MAX_CHARS),
  }));
}
