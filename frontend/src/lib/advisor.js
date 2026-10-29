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

/**
 * *text* cut to the per-turn cap without splitting a surrogate pair. A cut
 * through an emoji left half of one, which the API refuses as invalid text —
 * and since the history is resent with every question, every later question
 * in that conversation was a 422.
 */
function capTurn(text) {
  if (text.length <= ADVISOR_TURN_MAX_CHARS) return text;
  const end = ADVISOR_TURN_MAX_CHARS;
  const code = text.charCodeAt(end - 1);
  return text.slice(0, code >= 0xd800 && code <= 0xdbff ? end - 1 : end);
}

/**
 * The wire form of *messages*: the recent turns, in roles the API knows.
 * A bubble marked `error` is this app telling the user something went wrong,
 * not something the model said, so it is not sent back as the model's turn.
 */
export function advisorHistory(messages) {
  return messages
    .filter((m) => !m.error)
    .slice(-ADVISOR_HISTORY_SENT)
    .map((m) => ({
      role: m.role === "user" ? "user" : "model",
      text: capTurn(String(m.text ?? "")),
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

/**
 * A failure whose message is written for the visitor — the server's own
 * sentence, or one of ours. Anything else that is thrown (the browser's
 * "Failed to fetch", a parse error) is shown as `ADVISOR_UNREACHABLE` instead,
 * because its wording tells the visitor nothing.
 */
export class AdvisorError extends Error {}

/** Shown when the stream stopped after part of the answer had arrived. */
export const ADVISOR_CUT_OFF = "The answer was cut off. Ask again for the rest.";

/** The sentence to show for anything `streamAdvisor` throws. */
export function advisorErrorMessage(err) {
  return err instanceof AdvisorError ? err.message : ADVISOR_UNREACHABLE;
}

async function post(path, message, messages) {
  try {
    return await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: advisorHistory(messages) }),
    });
  } catch {
    throw new AdvisorError(ADVISOR_UNREACHABLE);
  }
}

/** The whole answer in one response — for a browser that cannot read a stream. */
async function askOnce(message, messages, onChunk) {
  const res = await post("/api/v1/advisor/ask", message, messages);
  if (!res.ok) throw new AdvisorError(await advisorFailure(res));
  const reply = (await res.json().catch(() => null))?.reply;
  if (!reply) throw new AdvisorError("The advisor sent back an empty answer. Ask again.");
  onChunk(reply);
  return reply;
}

/**
 * Stream an advisor answer as it is written, via server-sent events.
 *
 * `onChunk` is called with the answer so far each time more arrives, so the
 * first words show in about a second instead of after the whole reply.
 *
 * A stream only counts as finished when the server says `done`. One that just
 * stops — a dropped connection, a proxy timing out — throws: with nothing
 * received it is unreachable, and with part of an answer received it says the
 * answer was cut off, leaving the part on screen rather than passing it off as
 * the whole thing.
 *
 * @param {string} message  The user's question.
 * @param {Array}  messages The conversation so far (before this question).
 * @param {(cumulative: string) => void} onChunk Called with the growing text.
 * @returns {Promise<string>} The complete answer.
 */
export async function streamAdvisor(message, messages, onChunk) {
  const res = await post("/api/v1/advisor/ask/stream", message, messages);
  if (!res.ok) throw new AdvisorError(await advisorFailure(res));
  if (typeof res.body?.getReader !== "function") return askOnce(message, messages, onChunk);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let full = "";
  let buf = "";

  try {
    for (;;) {
      let chunk;
      try {
        chunk = await reader.read();
      } catch {
        break; // the connection dropped mid-answer; handled below
      }
      if (chunk.done) break;

      buf += decoder.decode(chunk.value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        let evt;
        try {
          evt = JSON.parse(line.slice(6));
        } catch {
          continue;
        }
        if (evt.error) throw new AdvisorError(evt.error);
        if (evt.done) return full;
        if (typeof evt.t === "string" && evt.t) {
          full += evt.t;
          onChunk(full);
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  throw new AdvisorError(full ? ADVISOR_CUT_OFF : ADVISOR_UNREACHABLE);
}
