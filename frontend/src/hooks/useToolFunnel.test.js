import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { track } from "../lib/track";
import { useToolFunnel } from "./useToolFunnel";

vi.mock("../lib/track", () => ({ track: vi.fn() }));

afterEach(() => track.mockClear());

describe("useToolFunnel", () => {
  it("records a start once, however much the visitor adjusts", () => {
    const { result } = renderHook(() => useToolFunnel("gst_calculator"));
    act(() => {
      result.current.start();
      result.current.start();
      result.current.start();
    });
    expect(track.mock.calls).toEqual([["tool_start", { tool: "gst_calculator" }]]);
  });

  it("records a completion once, however many results follow", () => {
    const { result } = renderHook(() => useToolFunnel("invoice_generator"));
    act(() => {
      result.current.start();
      result.current.complete();
      result.current.complete();
    });
    expect(track.mock.calls).toEqual([
      ["tool_start", { tool: "invoice_generator" }],
      ["tool_complete", { tool: "invoice_generator" }],
    ]);
  });

  it("does not count a result the visitor did nothing to produce", () => {
    // A shared link can arrive with its inputs filled and the result on screen.
    const { result } = renderHook(() => useToolFunnel("gst_calculator"));
    act(() => result.current.complete());
    expect(track).not.toHaveBeenCalled();
  });

  it("keeps the same functions across renders, so effects can depend on them", () => {
    const { result, rerender } = renderHook(() => useToolFunnel("hsn_finder"));
    const first = result.current;
    rerender();
    expect(result.current.start).toBe(first.start);
    expect(result.current.complete).toBe(first.complete);
  });
});
