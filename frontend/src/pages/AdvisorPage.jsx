import { useEffect, useRef, useState } from "react";
import SeoHead from "../components/SeoHead";
import { advisorErrorMessage, streamAdvisor } from "../lib/advisor";
import { formatMarkdown } from "../lib/format";
import { track } from "../lib/track";
import { usePageTitle } from "../hooks/usePageTitle";
import { useToolFunnel } from "../hooks/useToolFunnel";

const SUGGESTED_QUESTIONS = [
  "How to register for GST?",
  "What is ITC?",
  "GSTR-3B filing process",
  "GST on e-commerce",
  "Composition scheme eligibility",
];

function TypingIndicator() {
  return (
    <div className="advisor-typing" aria-label="Thinking">
      <span /><span /><span />
    </div>
  );
}

function MessageBubble({ role, text }) {
  return (
    <div className={`advisor-bubble advisor-bubble--${role}`}>
      {role === "assistant" && (
        <div className="advisor-avatar" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
            <path d="M12 2a2 2 0 012 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 017 7h1a1 1 0 110 2h-1.07A7.001 7.001 0 0113 22h-2a7.001 7.001 0 01-6.93-6H3a1 1 0 110-2h1a7 7 0 017-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 012-2zm0 7a5 5 0 00-5 5 5 5 0 005 5h0a5 5 0 005-5 5 5 0 00-5-5zm-2 4a1.5 1.5 0 110 3 1.5 1.5 0 010-3zm4 0a1.5 1.5 0 110 3 1.5 1.5 0 010-3z" />
          </svg>
        </div>
      )}
      <div
        className="advisor-text"
        dangerouslySetInnerHTML={{ __html: formatMarkdown(text) }}
      />
    </div>
  );
}


export default function AdvisorPage() {
  usePageTitle("Free GST AI Advisor");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const chatEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // Started by a question, finished by an answer: a failed or empty reply
  // leaves the visit unfinished, which is the case worth seeing.
  const { start: startTool, complete: completeTool } = useToolFunnel("advisor");

  const ask = async (question) => {
    const trimmed = question.trim();
    if (!trimmed || loading) return;

    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setInput("");
    setLoading(true);
    // The length, not the words: a GST question is typed by the user and
    // routinely carries a name, a GSTIN or an amount, none of which belongs
    // in a third-party analytics store.
    track("advisor_ask", { chars: trimmed.length });
    startTool();

    try {
      let added = false;
      await streamAdvisor(trimmed, messages, (partial) => {
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
      });
      if (added) completeTool();
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: advisorErrorMessage(err), error: true },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    ask(input);
  };

  return (
    <>
      <SeoHead
        title="Free GST AI Advisor - Ask Any GST Question | DoAide GST"
        description="Ask our free AI-powered GST advisor any question about GST registration, filing, rates, compliance, ITC claims, and regulations. Get instant, expert answers."
        path="/advisor"
      />

      <div className="advisor-page">
        <header className="advisor-header">
          <h1>
            <svg viewBox="0 0 24 24" fill="currentColor" width="24" height="24" className="advisor-sparkle" aria-hidden="true">
              <path d="M12 1l2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z" />
            </svg>
            GST AI Advisor
          </h1>
          <p>Ask any GST question and get instant expert answers — powered by AI.</p>
        </header>

        <div className="advisor-chat" role="log" aria-label="Advisor conversation">
          {messages.length === 0 && !loading && (
            <div className="advisor-welcome">
              <p>Hi! I can help you with GST questions. Try one of these:</p>
              <div className="advisor-chips">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    type="button"
                    className="advisor-chip"
                    onClick={() => ask(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <MessageBubble key={i} role={msg.role} text={msg.text} />
          ))}

          {loading && (messages.length === 0 || messages[messages.length - 1].role !== "assistant") && <TypingIndicator />}
          <div ref={chatEndRef} />
        </div>

        {messages.length > 0 && !loading && (
          <div className="advisor-chips advisor-chips--bottom">
            {SUGGESTED_QUESTIONS.filter(
              (q) => !messages.some((m) => m.role === "user" && m.text === q),
            ).slice(0, 3).map((q) => (
              <button
                key={q}
                type="button"
                className="advisor-chip"
                onClick={() => ask(q)}
              >
                {q}
              </button>
            ))}
          </div>
        )}

        <form className="advisor-input" onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a GST question..."
            disabled={loading}
            maxLength={2000}
            aria-label="Your question"
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!input.trim() || loading}
          >
            Ask
          </button>
        </form>
      </div>

      <style>{`
        .advisor-page {
          max-width: 740px;
          margin: 0 auto;
          padding: 24px 16px 100px;
          display: flex;
          flex-direction: column;
          min-height: 80vh;
        }
        .advisor-header {
          text-align: center;
          margin-bottom: 24px;
        }
        .advisor-header h1 {
          font-size: 1.5rem;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          margin: 0 0 8px;
        }
        .advisor-sparkle { color: var(--brand, #2563eb); }
        .advisor-header p {
          color: var(--text-secondary, #666);
          margin: 0;
          font-size: 0.95rem;
        }
        .advisor-chat {
          flex: 1;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 12px;
          padding: 8px 0;
        }
        .advisor-welcome {
          text-align: center;
          padding: 32px 0;
          color: var(--text-secondary, #666);
        }
        .advisor-welcome p { margin: 0 0 16px; }
        .advisor-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
          justify-content: center;
        }
        .advisor-chips--bottom {
          padding: 8px 0;
          justify-content: center;
        }
        .advisor-chip {
          background: var(--surface-raised, #f3f4f6);
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 20px;
          padding: 6px 14px;
          font-size: 0.85rem;
          cursor: pointer;
          color: var(--text, #111);
          transition: background 0.15s;
        }
        .advisor-chip:hover {
          background: var(--brand, #2563eb);
          color: #fff;
          border-color: var(--brand, #2563eb);
        }
        .advisor-bubble {
          display: flex;
          gap: 8px;
          max-width: 85%;
          animation: advisor-fade 0.2s ease;
        }
        @keyframes advisor-fade {
          from { opacity: 0; transform: translateY(6px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .advisor-bubble--user {
          align-self: flex-end;
          flex-direction: row-reverse;
        }
        .advisor-bubble--assistant { align-self: flex-start; }
        .advisor-avatar {
          width: 28px;
          height: 28px;
          border-radius: 50%;
          background: var(--brand, #2563eb);
          color: #fff;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          margin-top: 2px;
        }
        .advisor-text {
          padding: 10px 14px;
          border-radius: 14px;
          font-size: 0.93rem;
          line-height: 1.55;
        }
        .advisor-text code {
          background: var(--surface-raised, #f3f4f6);
          padding: 1px 5px;
          border-radius: 4px;
          font-size: 0.88em;
        }
        .advisor-bubble--user .advisor-text {
          background: var(--brand, #2563eb);
          color: #fff;
          border-bottom-right-radius: 4px;
        }
        .advisor-bubble--assistant .advisor-text {
          background: var(--surface-raised, #f3f4f6);
          color: var(--text, #111);
          border-bottom-left-radius: 4px;
        }
        .advisor-typing {
          display: flex;
          gap: 5px;
          padding: 12px 16px;
          align-self: flex-start;
        }
        .advisor-typing span {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--text-secondary, #999);
          animation: advisor-dot 1.2s infinite;
        }
        .advisor-typing span:nth-child(2) { animation-delay: 0.2s; }
        .advisor-typing span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes advisor-dot {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
          30% { transform: translateY(-6px); opacity: 1; }
        }
        .advisor-input {
          position: fixed;
          bottom: 0;
          left: 0;
          right: 0;
          background: var(--surface, #fff);
          border-top: 1px solid var(--border, #e5e7eb);
          padding: 12px 16px;
          display: flex;
          gap: 8px;
          max-width: 740px;
          margin: 0 auto;
          z-index: 10;
        }
        .advisor-input input {
          flex: 1;
          border: 1px solid var(--border, #ddd);
          border-radius: 8px;
          padding: 10px 14px;
          font-size: 0.95rem;
          background: var(--surface, #fff);
          color: var(--text, #111);
        }
        .advisor-input button { flex-shrink: 0; }
        @media (max-width: 600px) {
          .advisor-bubble { max-width: 92%; }
          .advisor-header h1 { font-size: 1.25rem; }
        }
      `}</style>
    </>
  );
}
