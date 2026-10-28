import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { api } from "../lib/api";

const STORAGE_KEY = "gstbot_feedback_pages";

function getSubmittedPages() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function markPageSubmitted(page) {
  try {
    const pages = getSubmittedPages();
    if (!pages.includes(page)) {
      pages.push(page);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(pages));
    }
  } catch {
    // Storage unavailable — widget will show again next visit.
  }
}

export default function FeedbackWidget() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [hidden, setHidden] = useState(false);

  const page = location.pathname;

  useEffect(() => {
    setHidden(getSubmittedPages().includes(page));
    setOpen(false);
    setRating(0);
    setHover(0);
    setComment("");
    setSubmitted(false);
  }, [page]);

  const handleSubmit = useCallback(async () => {
    if (rating === 0) return;
    try {
      await api.feedback({ page, rating, comment });
    } catch {
      // Best-effort — don't block the UI on a failed submission.
    }
    markPageSubmitted(page);
    setSubmitted(true);
    setTimeout(() => {
      setOpen(false);
      setHidden(true);
      setSubmitted(false);
    }, 1800);
  }, [page, rating, comment]);

  if (hidden) return null;

  return (
    <>
      {!open && (
        <button
          type="button"
          className="feedback-float"
          onClick={() => setOpen(true)}
          aria-label="Send feedback"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z" />
            <path d="M12 10c.55 0 1-.45 1-1s-.45-1-1-1-1 .45-1 1 .45 1 1 1zm-4 0c.55 0 1-.45 1-1s-.45-1-1-1-1 .45-1 1 .45 1 1 1zm8 0c.55 0 1-.45 1-1s-.45-1-1-1-1 .45-1 1 .45 1 1 1z" />
          </svg>
        </button>
      )}

      {open && (
        <div className="feedback-modal" role="dialog" aria-label="Send feedback">
          <div className="feedback-modal-inner">
            {submitted ? (
              <p className="feedback-thanks">Thanks for your feedback!</p>
            ) : (
              <>
                <div className="feedback-header">
                  <span className="feedback-title">Send feedback</span>
                  <button
                    type="button"
                    className="feedback-close"
                    onClick={() => setOpen(false)}
                    aria-label="Close feedback"
                  >
                    ×
                  </button>
                </div>
                <div className="feedback-stars" role="radiogroup" aria-label="Rating">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <button
                      key={star}
                      type="button"
                      className={
                        "feedback-star" +
                        (star <= (hover || rating) ? " is-active" : "")
                      }
                      onClick={() => setRating(star)}
                      onMouseEnter={() => setHover(star)}
                      onMouseLeave={() => setHover(0)}
                      aria-label={`${star} star${star > 1 ? "s" : ""}`}
                      role="radio"
                      aria-checked={star === rating}
                    >
                      ★
                    </button>
                  ))}
                </div>
                <textarea
                  className="feedback-comment"
                  placeholder="Tell us what you think..."
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  maxLength={2000}
                  rows={3}
                />
                <button
                  type="button"
                  className="feedback-submit"
                  disabled={rating === 0}
                  onClick={handleSubmit}
                >
                  Submit
                </button>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
