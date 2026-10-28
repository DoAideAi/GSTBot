import { afterEach, describe, expect, it, vi } from "vitest";
import {
  STALE_CHUNK_RELOAD_KEY,
  STALE_CHUNK_RELOAD_WINDOW_MS,
  installStaleChunkReload,
  reloadOnceForStaleChunk,
} from "./staleChunk";

function memoryStorage(initial = {}) {
  const data = { ...initial };
  return {
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => {
      data[key] = String(value);
    },
    data,
  };
}

describe("reloadOnceForStaleChunk", () => {
  it("reloads the first time a chunk is missing, and records when", () => {
    const storage = memoryStorage();
    const reload = vi.fn();

    expect(reloadOnceForStaleChunk({ storage, reload, now: 50_000 })).toBe(true);

    expect(reload).toHaveBeenCalledTimes(1);
    expect(storage.data[STALE_CHUNK_RELOAD_KEY]).toBe("50000");
  });

  it("does not reload again when the reload it just did failed the same way", () => {
    const storage = memoryStorage({ [STALE_CHUNK_RELOAD_KEY]: "50000" });
    const reload = vi.fn();

    const now = 50_000 + STALE_CHUNK_RELOAD_WINDOW_MS - 1;
    expect(reloadOnceForStaleChunk({ storage, reload, now })).toBe(false);

    expect(reload).not.toHaveBeenCalled();
  });

  it("reloads for a later deploy once the window has passed", () => {
    const storage = memoryStorage({ [STALE_CHUNK_RELOAD_KEY]: "50000" });
    const reload = vi.fn();

    const now = 50_000 + STALE_CHUNK_RELOAD_WINDOW_MS;
    expect(reloadOnceForStaleChunk({ storage, reload, now })).toBe(true);

    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("does not reload when it cannot write down that it did, so it cannot loop", () => {
    const storage = {
      getItem: () => null,
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
    };
    const reload = vi.fn();

    expect(reloadOnceForStaleChunk({ storage, reload })).toBe(false);

    expect(reload).not.toHaveBeenCalled();
  });
});

describe("installStaleChunkReload", () => {
  let uninstall;

  afterEach(() => {
    uninstall?.();
    window.sessionStorage.clear();
  });

  function fakeWindow(sessionStorage) {
    const target = new EventTarget();
    const reload = vi.fn();
    return {
      addEventListener: target.addEventListener.bind(target),
      removeEventListener: target.removeEventListener.bind(target),
      dispatchEvent: target.dispatchEvent.bind(target),
      get sessionStorage() {
        if (sessionStorage instanceof Error) throw sessionStorage;
        return sessionStorage;
      },
      location: { reload },
      reload,
    };
  }

  it("reloads the page when Vite reports a dynamic import that failed", () => {
    const win = fakeWindow(memoryStorage());
    uninstall = installStaleChunkReload(win);

    win.dispatchEvent(new Event("vite:preloadError"));

    expect(win.reload).toHaveBeenCalledTimes(1);
  });

  it("stops listening once uninstalled", () => {
    const win = fakeWindow(memoryStorage());
    installStaleChunkReload(win)();

    win.dispatchEvent(new Event("vite:preloadError"));

    expect(win.reload).not.toHaveBeenCalled();
  });

  it("leaves the error to the boundary when sessionStorage is blocked", () => {
    const win = fakeWindow(new Error("SecurityError"));
    uninstall = installStaleChunkReload(win);

    win.dispatchEvent(new Event("vite:preloadError"));

    expect(win.reload).not.toHaveBeenCalled();
  });

  it("listens on the real window by default", () => {
    const add = vi.spyOn(window, "addEventListener");

    uninstall = installStaleChunkReload();

    expect(add).toHaveBeenCalledWith("vite:preloadError", expect.any(Function));
    add.mockRestore();
  });
});
