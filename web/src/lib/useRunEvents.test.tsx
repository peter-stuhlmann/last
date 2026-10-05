import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRunEvents } from "./useRunEvents";

/** Nachbau von EventSource, bei dem der Test Nachrichten und Abbrüche auslöst. */
class FakeSource {
  static CLOSED = 2;
  static all: FakeSource[] = [];
  readyState = 1;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeSource.all.push(this);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  /** Der Server hat mit einem Fehler geantwortet: Der Browser gibt endgültig auf. */
  fail() {
    this.readyState = 2;
    this.onerror?.();
  }
  /** Kurzer Aussetzer: Der Browser verbindet sich von selbst neu. */
  hiccup() {
    this.readyState = 0;
    this.onerror?.();
  }
}

const state = JSON.stringify({ type: "state", state: "running", error: null, run: "results_1", report: false, pdf: false, summary: null });

beforeEach(() => {
  FakeSource.all = [];
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeSource);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useRunEvents", () => {
  it("verbindet sich und übernimmt Nachrichten", () => {
    const { result } = renderHook(() => useRunEvents());
    expect(FakeSource.all).toHaveLength(1);
    expect(FakeSource.all[0].url).toBe("/api/events");
    act(() => FakeSource.all[0].onmessage?.({ data: state }));
    expect(result.current.state).toBe("running");
    expect(result.current.offline).toBe(false);
  });

  it("baut die Verbindung selbst neu auf, wenn der Browser aufgegeben hat", () => {
    const { result } = renderHook(() => useRunEvents());
    act(() => FakeSource.all[0].onmessage?.({ data: state }));
    act(() => FakeSource.all[0].fail());
    expect(result.current.offline).toBe(true);
    // Der letzte bekannte Stand bleibt sichtbar
    expect(result.current.state).toBe("running");

    act(() => vi.advanceTimersByTime(1000));
    expect(FakeSource.all).toHaveLength(2);
    act(() => FakeSource.all[1].onmessage?.({ data: state }));
    expect(result.current.offline).toBe(false);
  });

  it("wartet bei wiederholtem Scheitern länger, aber nie länger als zehn Sekunden", () => {
    renderHook(() => useRunEvents());
    const waits = [1000, 2000, 4000, 8000, 10000, 10000];
    waits.forEach((ms, i) => {
      act(() => FakeSource.all[i].fail());
      act(() => vi.advanceTimersByTime(ms - 1));
      expect(FakeSource.all).toHaveLength(i + 1);
      act(() => vi.advanceTimersByTime(1));
      expect(FakeSource.all).toHaveLength(i + 2);
    });
  });

  it("mischt sich nicht ein, solange der Browser selbst neu verbindet", () => {
    const { result } = renderHook(() => useRunEvents());
    act(() => FakeSource.all[0].hiccup());
    expect(result.current.offline).toBe(true);
    act(() => vi.advanceTimersByTime(30_000));
    expect(FakeSource.all).toHaveLength(1);
  });

  it("räumt beim Verlassen der Seite auf", () => {
    const { unmount } = renderHook(() => useRunEvents());
    act(() => FakeSource.all[0].fail());
    unmount();
    act(() => vi.advanceTimersByTime(60_000));
    expect(FakeSource.all).toHaveLength(1);
    expect(FakeSource.all[0].closed).toBe(true);
  });
});
