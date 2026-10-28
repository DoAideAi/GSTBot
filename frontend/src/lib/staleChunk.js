/**
 * Recovers a tab that outlived a deploy.
 *
 * Every page is a lazy chunk with a content hash in its name, and a deploy
 * replaces those files. A tab opened before the deploy still holds the old
 * index, so the first screen it opens that it has not loaded yet asks for a file
 * that is gone. React.lazy caches that rejection, which means the boundary's
 * "Try again" re-throws the same error forever and only a reload gets the user
 * anywhere. The fallback offers one, but nothing on it says that a reload is
 * the answer rather than one guess among two.
 *
 * So the reload is done for them, once. Vite announces a failed dynamic import
 * as `vite:preloadError` on window, which is the one place that sees it before
 * React does.
 *
 * Once, and only with somewhere to write that down. A chunk that is missing for
 * a reason a reload does not fix — a broken deploy, a network that is down —
 * would otherwise reload the page in a loop the user cannot stop. The stamp in
 * sessionStorage is what tells a second failure from a first; a browser that
 * refuses storage gets no reload and lands on the boundary's fallback as before.
 */

export const STALE_CHUNK_RELOAD_KEY = "gstindia:stale-chunk-reload-at";

// Long enough that a reload which fetched the new index and failed again counts
// as the same failure; short enough that the next deploy, hours later, still
// gets its one reload.
export const STALE_CHUNK_RELOAD_WINDOW_MS = 10_000;

export function reloadOnceForStaleChunk({ storage, reload, now = Date.now() }) {
  try {
    const last = Number(storage.getItem(STALE_CHUNK_RELOAD_KEY));
    if (last && now - last < STALE_CHUNK_RELOAD_WINDOW_MS) return false;
    storage.setItem(STALE_CHUNK_RELOAD_KEY, String(now));
  } catch {
    return false;
  }
  reload();
  return true;
}

export function installStaleChunkReload(win = window) {
  const onPreloadError = () => {
    let storage;
    try {
      storage = win.sessionStorage;
    } catch {
      return;
    }
    reloadOnceForStaleChunk({ storage, reload: () => win.location.reload() });
  };
  win.addEventListener("vite:preloadError", onPreloadError);
  return () => win.removeEventListener("vite:preloadError", onPreloadError);
}
