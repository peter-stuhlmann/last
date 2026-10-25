"use client";

import { useEffect, useId, useRef, useState } from "react";

export type SelectOption = string | { value: string; label: string };

const valueOf = (o: SelectOption) => (typeof o === "string" ? o : o.value);
const labelOf = (o: SelectOption) => (typeof o === "string" ? o : o.label);

/** Auswahlliste im Look der App (statt des Betriebssystem-Menüs) – bedienbar per Maus und Tastatur. */
export function Select({
  id,
  value,
  options,
  onChange,
  label,
  mono = false,
}: {
  id: string;
  value: string;
  options: readonly SelectOption[];
  onChange: (value: string) => void;
  /** Name der Liste für Screenreader */
  label: string;
  /** Schreibmaschinenschrift, z. B. für HTTP-Methoden */
  mono?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const listId = useId();
  const values = options.map(valueOf);
  const current = options.find((o) => valueOf(o) === value);
  const font = mono ? "font-mono font-bold" : "font-medium";

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  function show() {
    setActive(Math.max(0, values.indexOf(value)));
    setOpen(true);
  }
  function pick(v: string) {
    onChange(v);
    setOpen(false);
  }
  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return show();
      setActive((a) => (a + (e.key === "ArrowDown" ? 1 : options.length - 1)) % options.length);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (open) pick(values[active]);
      else show();
    } else if (e.key === "Escape" && open) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
    } else if (e.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div ref={root} className="relative min-w-0">
      <button
        type="button"
        id={id}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={onKeyDown}
        className={`flex max-w-full items-center gap-2 rounded-lg border border-white/15 bg-white/[0.06] py-1.5 pl-3 pr-2 text-sm text-white transition-colors hover:border-cyan/50 hover:bg-white/10 ${font}`}
      >
        <span className="truncate">{current ? labelOf(current) : value}</span>
        <svg
          aria-hidden="true"
          viewBox="0 0 12 12"
          className={`size-3 shrink-0 text-cyan transition-transform ${open ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m2.5 4.5 3.5 3.5 3.5-3.5" />
        </svg>
      </button>
      {open && (
        <ul
          id={listId}
          role="listbox"
          aria-label={label}
          className={`absolute top-[calc(100%+8px)] z-30 min-w-28 max-w-[min(90vw,420px)] overflow-hidden rounded-xl border border-white/15 bg-[#0c0e18] p-1 shadow-[0_12px_40px_rgb(0_0_0/0.6),0_0_24px_rgb(124_92_255/0.25)] ${
            mono ? "left-0" : "right-0"
          }`}
        >
          {options.map((o, i) => {
            const v = valueOf(o);
            return (
              <li
                key={v}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={v === value}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(v)}
                className={`flex cursor-pointer items-center justify-between gap-4 rounded-lg px-3 py-1.5 text-sm ${font} ${
                  i === active ? "bg-violet/25 text-white" : "text-white/75"
                } ${v === value ? "text-cyan" : ""}`}
              >
                <span className={mono ? "" : "whitespace-nowrap"}>{labelOf(o)}</span>
                {v === value && <span aria-hidden="true">✓</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
