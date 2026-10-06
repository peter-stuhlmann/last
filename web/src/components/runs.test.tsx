import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RunInfo } from "@/lib/types";
import { notesSchema } from "@/lib/validation";
import { expectAccessible } from "@/test/setup";
import { RunNotes } from "./RunNotes";
import { RunsList } from "./RunsList";
import { Trend } from "./Trend";

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, refresh }) }));

const fetchMock = vi.fn();
beforeEach(() => {
  push.mockReset();
  refresh.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function run(name: string, over: Partial<RunInfo> = {}): RunInfo {
  return {
    name, kind: "web", model: null, base_url: "https://shop.example/", started: null, tests: ["baseline", "ramp"], report: true, pdf: true,
    title: null, tags: [], note: "", pinned: false, users: 400, target_users: 500, status: "warn", alone: 0.8, ...over,
  };
}

describe("notesSchema", () => {
  it("nimmt Titel, Tags, Notiz und Pin an und bereinigt Tags", () => {
    const r = notesSchema.safeParse({ title: " Vor dem Cache ", tags: ["Shop", "shop", "prod-nah"], note: "x", pinned: true });
    expect(r.success).toBe(true);
    expect(r.data).toEqual({ title: "Vor dem Cache", tags: ["shop", "prod-nah"], note: "x", pinned: true });
  });
  it("lehnt zu lange oder unsaubere Werte ab", () => {
    expect(notesSchema.safeParse({ title: "x".repeat(81) }).success).toBe(false);
    expect(notesSchema.safeParse({ title: "zwei\nzeilen" }).success).toBe(false);
    expect(notesSchema.safeParse({ tags: ["mit leerzeichen"] }).success).toBe(false);
    expect(notesSchema.safeParse({ tags: Array.from({ length: 11 }, (_, i) => `t${i}`) }).success).toBe(false);
    expect(notesSchema.safeParse({ note: "n".repeat(2001) }).success).toBe(false);
  });
});

describe("RunNotes", () => {
  it("bearbeitet Titel und Notiz, meldet „Gespeichert“ und schickt nur geprüfte Felder", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true }));
    const user = userEvent.setup();
    const { container } = render(<RunNotes name="results_20261005_100000" initial={{ title: null, tags: ["shop"], note: "", pinned: false }} />);
    expect(screen.getByRole("heading", { level: 2, name: "Lauf vom 05.10.2026, 10:00" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Titel und Notiz bearbeiten" }));
    await user.type(screen.getByLabelText("Titel"), "Vor dem Cache");
    await user.type(screen.getByLabelText("Notiz"), "Redis noch aus.");
    await user.click(screen.getByRole("button", { name: "Speichern" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Gespeichert"));
    expect(fetchMock).toHaveBeenCalledWith("/api/runs/results_20261005_100000/notes", expect.objectContaining({ method: "PUT" }));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ title: "Vor dem Cache", tags: ["shop"], note: "Redis noch aus.", pinned: false });
    expect(screen.getByRole("heading", { level: 2, name: "Vor dem Cache" })).toBeInTheDocument();
    expect(refresh).toHaveBeenCalled();
    await expectAccessible(container);
  });

  it("fügt Tags mit Enter hinzu, entfernt sie und pinnt", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true }));
    const user = userEvent.setup();
    render(<RunNotes name="results_20261005_100000" initial={{ title: "T", tags: [], note: "", pinned: false }} allTags={["shop"]} />);
    await user.type(screen.getByLabelText("Tag hinzufügen"), "Prod-Nah{Enter}");
    await waitFor(() => expect(screen.getByText("#prod-nah")).toBeInTheDocument());
    expect(JSON.parse(fetchMock.mock.calls[0][1].body).tags).toEqual(["prod-nah"]);
    await user.type(screen.getByLabelText("Tag hinzufügen"), "nicht erlaubt{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(/Tag/);
    await user.click(screen.getByRole("button", { name: "Tag prod-nah entfernen" }));
    await waitFor(() => expect(screen.queryByText("#prod-nah")).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /Anpinnen/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Angepinnt/ })).toHaveAttribute("aria-pressed", "true"));
  });

  it("löscht erst nach Rückfrage und führt dann zur Liste", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, trash_days: 7 }));
    const user = userEvent.setup();
    render(<RunNotes name="results_20261005_100000" initial={null} />);
    await user.click(screen.getByRole("button", { name: "Lauf löschen" }));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent(/Papierkorb/);
    await user.click(within(dialog).getByRole("button", { name: "Abbrechen" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Lauf löschen" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "In den Papierkorb" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/laeufe?geloescht=results_20261005_100000"));
    expect(fetchMock).toHaveBeenCalledWith("/api/runs/results_20261005_100000", expect.objectContaining({ method: "DELETE" }));
  });

  it("zeigt Fehler des Backends an", async () => {
    fetchMock.mockResolvedValue(Response.json({ error: "Dieser Lauf läuft gerade – erst abbrechen, dann löschen." }, { status: 409 }));
    const user = userEvent.setup();
    render(<RunNotes name="results_20261005_100000" initial={null} />);
    await user.click(screen.getByRole("button", { name: "Lauf löschen" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "In den Papierkorb" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/läuft gerade/);
    expect(push).not.toHaveBeenCalled();
  });
});

describe("RunsList mit Titeln, Tags, Suche und Löschen", () => {
  const runs = [
    run("results_20261005_100000", { title: "Vor dem Cache", tags: ["shop", "cache"] }),
    run("results_20261004_234100", { kind: "llm", model: "brain", base_url: "http://spark:8000/v1", pinned: true }),
    run("results_20261001_080000"),
  ];

  it("zeigt Titel statt Datum, angepinnte zuerst und filtert über Suche, Tag und Art", async () => {
    const user = userEvent.setup();
    const { container } = render(<RunsList runs={runs} />);
    // Nur die Titel-Links der Zeilen (die Download-Links tragen das Datum ebenfalls im Namen)
    const links = () =>
      screen
        .getAllByRole("link")
        .filter((l) => l.getAttribute("href")?.startsWith("/laeufe/"))
        .map((l) => l.textContent);
    expect(links()[0]).toContain("04.10.2026, 23:41");           // angepinnt
    expect(screen.getByRole("link", { name: /Vor dem Cache/ })).toHaveAttribute("href", "/laeufe/results_20261005_100000");
    await user.type(screen.getByRole("searchbox", { name: "Läufe durchsuchen" }), "cache");
    expect(links()).toEqual(["Vor dem Cache"]);
    await user.clear(screen.getByRole("searchbox", { name: "Läufe durchsuchen" }));
    await user.click(screen.getByRole("button", { name: "Nach Tag shop filtern" }));
    expect(screen.getByRole("searchbox", { name: "Läufe durchsuchen" })).toHaveValue("#shop");
    expect(links()).toEqual(["Vor dem Cache"]);
    await user.clear(screen.getByRole("searchbox", { name: "Läufe durchsuchen" }));
    await user.click(screen.getByRole("button", { name: "KI-Server" }));
    expect(links()).toHaveLength(1);
    await user.type(screen.getByRole("searchbox", { name: "Läufe durchsuchen" }), "gibtsnicht");
    expect(screen.getByText("Kein Lauf passt zur Suche.")).toBeInTheDocument();
    await expectAccessible(container);
  });

  it("löscht nach Rückfrage und meldet den Papierkorb", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, trash_days: 7 }));
    const user = userEvent.setup();
    render(<RunsList runs={runs} />);
    await user.click(screen.getByRole("button", { name: "Lauf vom 01.10.2026, 08:00 löschen" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "In den Papierkorb" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/01\.10\.2026, 08:00 liegt im Papierkorb/));
    expect(fetchMock).toHaveBeenCalledWith("/api/runs/results_20261001_080000", expect.objectContaining({ method: "DELETE" }));
    expect(refresh).toHaveBeenCalled();
  });

  it("zeigt den Hinweis, wenn man nach dem Löschen hierher kommt", () => {
    render(<RunsList runs={runs} deleted="results_20260930_120000" />);
    expect(screen.getByRole("status")).toHaveTextContent(/30\.09\.2026, 12:00 liegt im Papierkorb/);
  });
});

describe("Trend", () => {
  it("zeichnet den Verlauf gleicher Läufe und erklärt ihn in einem Satz", async () => {
    const runs = [
      run("results_20260901_100000", { users: 410, alone: 0.9, status: "bad" }),
      run("results_20260915_100000", { users: 520, alone: 0.7, title: "Cache an" }),
      run("results_20261001_100000", { users: 770, alone: 0.6, status: "good" }),
      run("results_20261002_100000", { kind: "api", base_url: "https://api.example/v1/items", users: 1500, alone: 0.05 }),
    ];
    const { container } = render(<Trend runs={runs} />);
    expect(screen.getByRole("heading", { name: "Verlauf" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Verlauf der Kapazität in Besucher über 3 Läufe/ })).toBeInTheDocument();
    expect(screen.getByText(/von 410 auf 770 Besucher gestiegen/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cache an" })).toHaveAttribute("href", "/laeufe/results_20260915_100000");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();     // nur eine Gruppe mit ≥ 2 Läufen
    await expectAccessible(container);
  });

  it("verschwindet, solange es nichts zu vergleichen gibt", () => {
    const { container } = render(<Trend runs={[run("results_20261001_100000")]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
