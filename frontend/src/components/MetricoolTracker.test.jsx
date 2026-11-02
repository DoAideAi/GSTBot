import { StrictMode } from "react";
import { act, render, waitFor } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MetricoolTracker from "./MetricoolTracker";
import { metricoolPageUrl } from "../lib/metricool";

const auth = vi.hoisted(() => ({ user: null, loading: false }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => auth }));
vi.mock("../lib/metricool", () => ({ metricoolPageUrl: vi.fn() }));
let navigate;
const images = [];

function Page() {
  navigate = useNavigate();
  return <MetricoolTracker />;
}
function tree(url = "/") {
  return <StrictMode><MemoryRouter initialEntries={[url]}><Page /></MemoryRouter></StrictMode>;
}

beforeEach(() => {
  auth.user = null;
  auth.loading = false;
  images.length = 0;
  metricoolPageUrl.mockReset().mockResolvedValue("https://tracker.metricool.com/c3po.jpg?test");
  vi.stubGlobal("Image", class { constructor() { images.push(this); } });
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("Metricool navigation tracking", () => {
  it("counts initial navigation once, ignores query/hash changes, and counts the next page", async () => {
    render(tree("/calculator?amount=12345#secret"));
    await waitFor(() => expect(images).toHaveLength(1));
    expect(metricoolPageUrl).toHaveBeenLastCalledWith("/calculator", expect.any(Object));
    expect(images[0].referrerPolicy).toBe("no-referrer");
    expect(images[0].src).toContain("tracker.metricool.com");
    await act(async () => navigate("/calculator?amount=54321#other"));
    expect(images).toHaveLength(1);
    await act(async () => navigate("/pricing"));
    await waitFor(() => expect(images).toHaveLength(2));
  });

  it.each([{ user: null, loading: true }, { user: { id: 1 }, loading: false }])("skips unresolved and signed-in sessions: %j", async (state) => {
    Object.assign(auth, state);
    render(tree());
    await act(async () => {});
    expect(metricoolPageUrl).not.toHaveBeenCalled();
    expect(images).toHaveLength(0);
  });

  it("does not send build-time prerender visits", () => {
    vi.stubEnv("SSR", true);
    render(tree());
    expect(metricoolPageUrl).not.toHaveBeenCalled();
  });

  it("cancels a pending public page view when the visitor signs in", async () => {
    let resolve;
    metricoolPageUrl.mockImplementation(() => new Promise((done) => { resolve = done; }));
    const { rerender } = render(tree());
    auth.user = { id: 1 };
    rerender(tree());
    await act(async () => resolve("https://tracker.metricool.com/c3po.jpg"));
    expect(images).toHaveLength(0);
  });

  it.each(["excluded", "blocked"])("does not send a request when tracking is %s", async (outcome) => {
    if (outcome === "excluded") metricoolPageUrl.mockResolvedValue(null);
    else metricoolPageUrl.mockRejectedValue(new Error("blocked"));
    render(tree());
    await act(async () => {});
    expect(images).toHaveLength(0);
  });
});
