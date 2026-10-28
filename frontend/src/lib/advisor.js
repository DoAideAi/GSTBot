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

/** What the user can do when the advisor could not be reached at all. */
export const ADVISOR_UNREACHABLE =
  "Could not reach the AI advisor. Check your connection and ask again.";

/**
 * The sentence to show for a failed `POST /advisor/ask`.
 *
 * The server answers a failure with a status and `{ detail }` saying what
 * happened and what to do — not set up, overloaded, too slow, refused. The
 * widget used to print the raw response body (a JSON blob) and the page a
 * fixed "Something went wrong", so either way the explanation was lost.
 */
export async function advisorFailure(res) {
  const body = await res.json().catch(() => null);
  if (typeof body?.detail === "string" && body.detail.trim()) return body.detail;
  if (res.status === 429) return "You're asking quickly — wait a minute and ask again.";
  return "The AI advisor could not answer just now. Ask again in a minute.";
}
