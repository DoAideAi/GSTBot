/**
 * A stored visit (`feedback.metadata`) read back as a sentence an admin can
 * scan — "Was on GSTIN Lookup for 3m 12s, scrolled 80%, 5 rage clicks, 1 JS
 * error" — plus the struggle signals as separate flags for the eye to catch.
 */

export function duration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return null;
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

export function summarize(meta) {
  if (!meta || typeof meta !== "object") return { sentence: "", flags: [] };

  const parts = [];
  const time = duration(meta.time_on_page_ms);
  if (meta.feature_area && time) parts.push(`Was on ${meta.feature_area} for ${time}`);
  else if (meta.feature_area) parts.push(`Was on ${meta.feature_area}`);
  else if (time) parts.push(`Was on the page for ${time}`);
  if (Number.isFinite(meta.scroll_depth_pct)) parts.push(`scrolled ${meta.scroll_depth_pct}%`);
  if (Number.isFinite(meta.click_count)) parts.push(plural(meta.click_count, "click"));
  if (meta.rage_clicks > 0) parts.push(plural(meta.rage_clicks, "rage click"));
  if (meta.js_errors > 0) parts.push(plural(meta.js_errors, "JS error"));
  if (Array.isArray(meta.pages) && meta.pages.length > 1) {
    parts.push(`${plural(meta.pages.length, "page")} this session`);
  }

  const flags = [];
  if (meta.rage_clicks > 0) {
    const where = meta.rage_click_targets?.length ? ` on ${meta.rage_click_targets.join(", ")}` : "";
    flags.push({ kind: "rage", label: `Rage clicks${where}` });
  }
  if (meta.form_abandoned) {
    const spent = duration(meta.form_time_ms);
    flags.push({ kind: "form", label: `Stuck on a form${spent ? ` for ${spent}` : ""} without submitting` });
  }
  if (meta.js_errors > 0) {
    const first = meta.js_error_messages?.[0];
    flags.push({ kind: "error", label: first ? `JS error: ${first}` : "JS errors on the page" });
  }
  if (meta.reloaded) flags.push({ kind: "reload", label: "Reloaded the page" });

  const sentence = parts.length ? `${parts.join(", ")}.` : "";
  return { sentence, flags };
}
