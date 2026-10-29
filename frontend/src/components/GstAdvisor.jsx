import { useCallback, useEffect, useRef, useState } from "react";
import { useExclusivePanel } from "../lib/floatingLayout";
import { advisorErrorMessage, streamAdvisor } from "../lib/advisor";
import { isAbortError } from "../lib/api";
import { formatMarkdown } from "../lib/format";
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
  const closePanel = useCallback(() => setOpen(false), []);
  useExclusivePanel("advisor", open, closePanel);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);
  const launcherRef = useRef(null);
  const wasOpen = useRef(false);

  // Focus follows the panel. The launcher is unmounted when the panel opens
  // and the close button when it closes, so focus fell to <body> both ways and
  // a keyboard user had to tab the whole page to find either one. Escape
  // closes it, as it does the feedback form beside it. Nothing moves on the
  // first render: the launcher is on every page and must not steal focus.
  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
      const onKeyDown = (e) => {
        if (e.key === "Escape") setOpen(false);
      };
      document.addEventListener("keydown", onKeyDown);
      wasOpen.current = true;
      return () => document.removeEventListener("keydown", onKeyDown);
    }
    if (wasOpen.current) launcherRef.current?.focus();
    wasOpen.current = false;
    return undefined;
  }, [open]);

  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      if (bodyRef.current) {
        bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
      }
    });
  }, []);

  // Stopped if the panel unmounts mid-answer, for the reason AdvisorPage
  // gives. Closing the panel only hides it, so that keeps its answer coming.
  const inFlight = useRef(null);
  useEffect(() => () => inFlight.current?.abort(), []);

  const sendMessage = useCallback(async (text, history) => {
    setError(null);
    setLoading(true);
    scrollToBottom();

    const controller = new AbortController();
    inFlight.current = controller;
    try {
      let added = false;
      await streamAdvisor(text, history, (partial) => {
        if (!added) {
          setMessages((prev) => [...prev, { role: "assistant", text: partial }]);
          added = true;
        } else {
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = { role: "assistant", text: partial };
            return next;
          });
        }
        scrollToBottom();
      }, { signal: controller.signal });
    } catch (err) {
      if (isAbortError(err)) return;
      setError(advisorErrorMessage(err));
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
        scrollToBottom();
      }
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
          ref={launcherRef}
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
          {/* A log: each answer is read out as it streams in, which a screen
              reader user otherwise only learnt of by going looking. */}
          <div
            className="advisor-body"
            ref={bodyRef}
            role="log"
            aria-live="polite"
            aria-label="Conversation"
          >
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
                {m.role === "assistant" ? (
                  <div className="advisor-msg-text" dangerouslySetInnerHTML={{ __html: formatMarkdown(m.text) }} />
                ) : (
                  <div className="advisor-msg-text">{m.text}</div>
                )}
              </div>
            ))}
            {loading && (messages.length === 0 || messages[messages.length - 1].role !== "assistant") && (
              <div className="advisor-msg advisor-msg-assistant">
                <div className="advisor-typing" role="status" aria-label="Thinking">
                  <span /><span /><span />
                </div>
              </div>
            )}
            {error && <div className="advisor-error" role="alert">{error}</div>}
          </div>
          <div className="advisor-footer">
            <textarea
              ref={inputRef}
              className="advisor-input"
              aria-label="Your GST question"
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
