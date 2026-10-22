import { Link } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";

const STORAGE_KEY = "gstbot_calc_count";

export function getCalcCount() {
  try {
    return parseInt(localStorage.getItem(STORAGE_KEY) || "0", 10) || 0;
  } catch {
    return 0;
  }
}

export function incrementCalcCount() {
  try {
    const count = getCalcCount() + 1;
    localStorage.setItem(STORAGE_KEY, String(count));
    return count;
  } catch {
    return 0;
  }
}

export default function SavePrompt({ calcCount, onDismiss }) {
  const { user } = useAuth();

  if (user || calcCount < 3) return null;

  return (
    <div className="save-prompt" role="status">
      <p>
        <strong>Save your calculations</strong> — Sign up for free to keep your
        calculation history and access it anytime.
      </p>
      <div className="save-prompt-actions">
        <Link to="/login" className="btn btn-primary btn-sm">
          Sign up free
        </Link>
        <button className="btn btn-ghost btn-sm" onClick={onDismiss}>
          Not now
        </button>
      </div>
    </div>
  );
}
