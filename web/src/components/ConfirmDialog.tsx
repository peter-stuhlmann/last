"use client";

import { useEffect, useRef, type ReactNode } from "react";

/**
 * Rückfrage vor etwas, das sich nicht rückgängig machen lässt. Zwei Schaltflächen, Fokus bleibt
 * im Dialog, Escape schließt. Der Aufrufer behält den Fokus auf dem Auslöser (focus() nach close).
 */
export function ConfirmDialog({
  id,
  title,
  text,
  confirmLabel,
  cancelLabel = "Abbrechen",
  onConfirm,
  onClose,
}: {
  id: string;
  title: string;
  text: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    cancel.current?.focus();
  }, []);
  return (
    <div className="fixed inset-0 z-40 grid place-items-center bg-black/70 p-4" onClick={onClose}>
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-titel`}
        aria-describedby={`${id}-text`}
        className="card w-full max-w-md bg-ink-2 p-6"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          if (e.key === "Tab") {
            e.preventDefault();
            const buttons = e.currentTarget.querySelectorAll("button");
            (document.activeElement === buttons[0] ? buttons[1] : buttons[0]).focus();
          }
        }}
      >
        <h2 id={`${id}-titel`} className="font-display text-xl font-bold">
          {title}
        </h2>
        <p id={`${id}-text`} className="mt-2 text-sm text-white/75">
          {text}
        </p>
        <div className="mt-6 flex flex-wrap justify-end gap-2">
          <button ref={cancel} type="button" className="btn btn-ghost" onClick={onClose}>
            {cancelLabel}
          </button>
          <button type="button" className="btn btn-danger" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
