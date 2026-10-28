import { useCallback, useRef, useState } from "react";
import { advisorHistory } from "../lib/advisor";
import { track } from "../lib/track";

const SUGGESTED_QUESTIONS = [
  "What is the GST rate for IT services?",
  "How do I claim Input Tax Credit?",
  "When is the GSTR-3B due date?",
  "What is reverse charge mechanism?",
  "Do I need GST registration?",
  "What are blocked ITC credits under Section 17(5)?",
];

export default function GstAdvisor() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const bodyRef = useRef(null);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      if (bodyRef.current) {
        bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
      }
    });
  }, []);

  const sendMessage = useCallback(async (text, history) => {
    setError(null);
    setLoading(true);
    scrollToBottom();

    try {
      const res = await fetch("/api/v1/advisor/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: advisorHistory(history),
        }),
      });

      if (!res.ok) {
        const errBody = await res.text().catch(() => "");
        throw new Error(errBody || `API error ${res.status}`);
      }

      const data = await res.json();
      const reply = data?.reply ?? "Sorry, I could not generate a response.";
      setMessages((prev) => [...prev, { role: "assistant", text: reply }]);
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
      scrollToBottom();
    }
  }, [scrollToBottom]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg = { role: "user", text };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput("");
    track("advisor_send", { source: "input" });
    await sendMessage(text, messages);
  }, [input, loading, messages, sendMessage]);

  const handleSuggestionClick = useCallback((question) => {
    if (loading) return;
    const userMsg = { role: "user", text: question };
    setMessages((prev) => {
      const next = [...prev, userMsg];
      sendMessage(question, prev);
      return next;
    });
    track("advisor_send", { source: "suggestion", question });
  }, [loading, sendMessage]);

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <>
      {!open && (
        <button
          type="button"
          className="advisor-float"
          onClick={() => { setOpen(true); track("advisor_open"); }}
          aria-label="Open GST AI Advisor"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z" />
            <line x1="9" y1="21" x2="15" y2="21" />
            <line x1="10" y1="24" x2="14" y2="24" />
          </svg>
        </button>
      )}

      {open && (
        <div className="advisor-panel" role="dialog" aria-label="GST AI Advisor">
          <div className="advisor-header">
            <span className="advisor-title">
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true" style={{ marginRight: 6, verticalAlign: -2 }}>
                <path d="M12 2a7 7 0 0 1 7 7c0 2.38-1.19 4.47-3 5.74V17a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-2.26C6.19 13.47 5 11.38 5 9a7 7 0 0 1 7-7z" />
              </svg>
              GST AI Advisor
            </span>
            <button
              type="button"
              className="advisor-close"
              onClick={() => setOpen(false)}
              aria-label="Close advisor"
            >
              ×
            </button>
          </div>
          <div className="advisor-body" ref={bodyRef}>
            {messages.length === 0 && (
              <div className="advisor-welcome">
                <p className="advisor-welcome-title">Ask me anything about GST</p>
                <p className="advisor-welcome-hint">
                  Get instant answers on GST rates, ITC claims, filing deadlines, and compliance.
                </p>
                <div className="advisor-suggestions">
                  {SUGGESTED_QUESTIONS.map((q) => (
                    <button
                      key={q}
                      type="button"
                      className="advisor-suggestion"
                      onClick={() => handleSuggestionClick(q)}
                      disabled={loading}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`advisor-msg advisor-msg-${m.role}`}>
                <div className="advisor-msg-text">{m.text}</div>
              </div>
            ))}
            {loading && (
              <div className="advisor-msg advisor-msg-assistant">
                <div className="advisor-typing" aria-label="Thinking">
                  <span /><span /><span />
                </div>
              </div>
            )}
            {error && <div className="advisor-error">{error}</div>}
          </div>
          <div className="advisor-footer">
            <textarea
              className="advisor-input"
              placeholder="Ask a GST question..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
              maxLength={2000}
              disabled={loading}
            />
            <button
              type="button"
              className="advisor-send"
              onClick={handleSend}
              disabled={!input.trim() || loading}
              aria-label="Send message"
            >
              <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </>
  );
}

export { SUGGESTED_QUESTIONS };
