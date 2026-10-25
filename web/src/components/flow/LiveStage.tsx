"use client";

import { useEffect, useRef } from "react";
import type { LiveTarget } from "@/lib/types";

/** Meldungen des Backends zum Live-Vorführen (neben den Bildern). */
export type LiveMsg =
  | { t: "state"; url: string }
  | { t: "busy"; on: boolean }
  | { t: "notice"; text: string }
  | { t: "steps"; steps: string[]; thumb?: string | null }
  | { t: "fill"; target: LiveTarget; value: string; enter: boolean; thumb?: string | null };

type Input =
  | { t: "move"; x: number; y: number }
  | { t: "click"; x: number; y: number }
  | { t: "wheel"; x: number; y: number; dx: number; dy: number }
  | { t: "type"; text: string }
  | { t: "text"; text: string }
  | { t: "key"; key: string; mods?: string[] };

const MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta", "AltGraph", "CapsLock", "Dead", "Process"]);

/** Aufeinanderfolgende Bewegungen, Drehungen und Buchstaben zu einer Eingabe zusammenfassen – die Reihenfolge bleibt. */
function coalesce(events: Input[]): Input[] {
  const out: Input[] = [];
  for (const ev of events) {
    const last = out[out.length - 1];
    if (last && ev.t === "move" && last.t === "move") out[out.length - 1] = ev;
    else if (last && ev.t === "wheel" && last.t === "wheel") out[out.length - 1] = { ...ev, dx: last.dx + ev.dx, dy: last.dy + ev.dy };
    else if (last && ev.t === "type" && last.t === "type" && last.text.length + ev.text.length <= 4000)
      out[out.length - 1] = { t: "type", text: last.text + ev.text };
    else out.push(ev);
  }
  return out;
}

/**
 * Die Seite live: Bilder kommen als Strom vom Browser im Hintergrund, Maus und Tastatur gehen sofort zurück.
 * Man klickt und tippt direkt in die Seite, wie in einem normalen Browser – das Backend macht daraus die Schritte.
 */
export function LiveStage({
  session,
  size,
  measuring,
  disabled,
  onMessage,
  onClosed,
}: {
  session: string;
  size: { w: number; h: number };
  measuring: boolean;
  /** der Ablauf wurde geändert und muss erst neu abgespielt werden */
  disabled: boolean;
  onMessage: (msg: LiveMsg) => void;
  onClosed: (text: string) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const handlers = useRef({ onMessage, onClosed, measuring, disabled });
  useEffect(() => {
    handlers.current = { onMessage, onClosed, measuring, disabled };
  });
  const outbox = useRef<Input[]>([]);
  const inflight = useRef(false);

  // Der Strom: Bilder werden auf die Fläche gemalt (nur das neueste, wenn das Malen nicht mitkommt), Meldungen weitergereicht
  useEffect(() => {
    const es = new EventSource(`/api/flow/live/stream?session=${session}`);
    let drawing = false;
    let latest: string | null = null;
    const draw = async () => {
      if (drawing || latest === null) return;
      drawing = true;
      const b64 = latest;
      latest = null;
      try {
        const bin = atob(b64);
        const bytes = new Uint8Array(bin.length);
        for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        const bmp = await createImageBitmap(new Blob([bytes], { type: "image/jpeg" }));
        const c = canvas.current;
        if (c) {
          if (c.width !== bmp.width || c.height !== bmp.height) {
            c.width = bmp.width;
            c.height = bmp.height;
          }
          c.getContext("2d")?.drawImage(bmp, 0, 0);
        }
        bmp.close();
      } catch {
        // ein beschädigtes Bild überspringen – das nächste kommt gleich
      }
      drawing = false;
      void draw();
    };
    es.addEventListener("frame", (e) => {
      latest = (e as MessageEvent<string>).data;
      void draw();
    });
    es.addEventListener("msg", (e) => {
      try {
        handlers.current.onMessage(JSON.parse((e as MessageEvent<string>).data) as LiveMsg);
      } catch {
        // unlesbare Meldung ignorieren
      }
    });
    es.onerror = () => {
      // Bei Verbindungsabbruch verbindet sich der Browser selbst neu; ist die Sitzung weg, gibt der Server 410 und es bleibt zu
      if (es.readyState === EventSource.CLOSED)
        handlers.current.onClosed("Die Verbindung zum Browser ist abgebrochen – bitte „Neu abspielen“.");
    };
    return () => es.close();
  }, [session]);

  // Eingaben gehen einzeln nacheinander raus (damit ihre Reihenfolge stimmt); was sich währenddessen ansammelt, geht zusammengefasst mit
  function flush() {
    if (inflight.current || !outbox.current.length) return;
    inflight.current = true;
    const events = coalesce(outbox.current.splice(0, 200)).slice(0, 60);
    void fetch("/api/flow/live/input", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ session, measuring: handlers.current.measuring, events }),
    })
      .then((res) => {
        if (res.status === 410) handlers.current.onClosed("Der Browser wurde inzwischen geschlossen – bitte „Neu abspielen“.");
      })
      .catch(() => {})
      .finally(() => {
        inflight.current = false;
        flush();
      });
  }
  function send(ev: Input) {
    if (handlers.current.disabled) return;
    outbox.current.push(ev);
    flush();
  }

  function at(e: { clientX: number; clientY: number }) {
    const r = canvas.current?.getBoundingClientRect();
    if (!r || !r.width || !r.height) return null;
    const clamp = (v: number, max: number) => Math.round(Math.min(max, Math.max(0, v)));
    return { x: clamp(((e.clientX - r.left) / r.width) * size.w, size.w), y: clamp(((e.clientY - r.top) / r.height) * size.h, size.h) };
  }

  // Mausrad: eigener Listener (nicht passiv), sonst blättert das Fenster drumherum mit
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const p = at(e);
      if (!p) return;
      const unit = e.deltaMode === 1 ? 40 : e.deltaMode === 2 ? size.h : 1;
      send({ t: "wheel", ...p, dx: Math.round(e.deltaX * unit), dy: Math.round(e.deltaY * unit) });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- send/at lesen den aktuellen Zustand selbst
  }, [session, size.w, size.h]);

  function onKeyDown(e: React.KeyboardEvent<HTMLCanvasElement>) {
    // Alles geht an die Seite; Escape und Tab sollen nicht das Fenster darum schließen oder den Fokus mitnehmen
    e.stopPropagation();
    if (e.nativeEvent.isComposing || MODIFIERS.has(e.key)) return;
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key.toLowerCase() === "v") return; // Einfügen kommt als eigenes Ereignis (onPaste)
    if (ctrl && e.key.toLowerCase() === "c") return;
    e.preventDefault();
    if (e.key.length === 1 && !ctrl && !e.altKey) {
      send({ t: "type", text: e.key });
      return;
    }
    const mods = [e.ctrlKey && "Control", e.metaKey && "Meta", e.altKey && "Alt", e.shiftKey && e.key.length > 1 && "Shift"].filter(
      Boolean,
    ) as string[];
    send({ t: "key", key: e.key, ...(mods.length ? { mods } : {}) });
  }

  function onPaste(e: React.ClipboardEvent<HTMLCanvasElement>) {
    e.preventDefault();
    const text = e.clipboardData
      .getData("text")
      .replace(/[\r\n]+/g, " ")
      .slice(0, 4000);
    if (text) send({ t: "text", text });
  }

  return (
    <canvas
      ref={canvas}
      width={size.w}
      height={size.h}
      tabIndex={0}
      role="application"
      aria-label="Die Seite – Klicken und Tippen geht direkt hier"
      onMouseMove={(e) => {
        const p = at(e);
        if (p) send({ t: "move", ...p });
      }}
      onClick={(e) => {
        e.currentTarget.focus();
        const p = at(e);
        if (p) send({ t: "click", ...p });
      }}
      onContextMenu={(e) => e.preventDefault()}
      onKeyDown={onKeyDown}
      onPaste={onPaste}
      className="block w-full cursor-default select-none rounded-2xl bg-white outline-none focus-visible:ring-2 focus-visible:ring-cyan"
    />
  );
}
