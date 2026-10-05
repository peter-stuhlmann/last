"use client";

import { useEffect, useReducer } from "react";
import { initialLive, reduceLive, type LiveState } from "./events";
import type { EventMessage } from "./types";

const FIRST_RETRY_MS = 1000;
const MAX_RETRY_MS = 10_000;

/** Verbindet sich mit dem Ereignis-Strom des laufenden Tests (Server-Sent Events). */
export function useRunEvents(): LiveState {
  const [state, dispatch] = useReducer(reduceLive, initialLive);

  useEffect(() => {
    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let wait = FIRST_RETRY_MS;
    let stopped = false;

    function connect() {
      source = new EventSource("/api/events");
      source.onmessage = (event) => {
        wait = FIRST_RETRY_MS;
        try {
          dispatch(JSON.parse(event.data) as EventMessage);
        } catch {
          // Unlesbare Nachricht überspringen – die nächste kommt in einer Sekunde.
        }
      };
      source.onerror = () => {
        dispatch({ type: "offline" });
        // Bricht nur die Leitung ab, verbindet sich der Browser von selbst neu. Antwortet der
        // Server aber mit einem Fehler (z. B. 502, während das Backend neu startet), gibt er
        // endgültig auf – dann übernehmen wir, mit wachsendem Abstand zwischen den Versuchen.
        if (stopped || source?.readyState !== EventSource.CLOSED) return;
        timer = setTimeout(connect, wait);
        wait = Math.min(wait * 2, MAX_RETRY_MS);
      };
    }

    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      source?.close();
    };
  }, []);

  return state;
}
