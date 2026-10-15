import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LiveReply, LiveSnapshot } from "@/lib/types";
import { expectAccessible } from "@/test/setup";
import { FlowSteps } from "./FlowSteps";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

const SNAP: LiveSnapshot = {
  url: "https://chat.example/login",
  title: "Anmelden",
  viewport: { w: 1280, h: 800 },
  screenshot: "data:image/jpeg;base64,AAAA",
  elements: [
    { mark: "0", kind: "field", label: "E-Mail", box: { x: 10, y: 10, w: 200, h: 30 } },
    { mark: "1", kind: "button", label: "Anmelden", box: { x: 10, y: 60, w: 100, h: 30 } },
  ],
};

/** Wie im Formular: Text und Zugangsdaten liegen beim Eltern-Element. */
function Harness({ initial = "", baseUrl = "https://chat.example/login" }: { initial?: string; baseUrl?: string | null }) {
  const [text, setText] = useState(initial);
  const [secrets, setSecrets] = useState<Record<string, string>>({});
  return (
    <>
      <FlowSteps value={text} onChange={setText} baseUrl={baseUrl} secrets={secrets} onSecret={(k, v) => setSecrets((s) => ({ ...s, [k]: v }))} />
      <output data-testid="text">{text}</output>
      <output data-testid="secrets">{JSON.stringify(secrets)}</output>
    </>
  );
}

const text = () => screen.getByTestId("text").textContent;
const reply = (r: LiveReply, status = 200) => Response.json(r, { status });
const sent = (i: number) => JSON.parse(fetchMock.mock.calls[i][1].body);

describe("Grafischer Ablauf", () => {
  it("zeigt Vorbereitung und Messbereich als Bausteine", () => {
    render(<Harness initial={'tippe in "E-Mail" {email}\nklicke "Anmelden"\nmessen ab hier\nklicke "Löschen" bei "Bestellung 4711"'} />);
    const prep = screen.getByRole("region", { name: "1 · Vorbereitung" });
    expect(within(prep).getByText("Seite öffnen")).toBeInTheDocument();
    expect(within(prep).getByText(/Zugangsdaten \{email\}/)).toBeInTheDocument();
    const measured = screen.getByRole("region", { name: "2 · Das wird gemessen" });
    expect(within(measured).getByText("bei „Bestellung 4711“")).toBeInTheDocument();
  });

  it("verschiebt die Grenze der Messung und Bausteine, löscht und ändert Text", async () => {
    const user = userEvent.setup();
    render(<Harness initial={'tippe in "Nachricht" "Hallo"\nmessen ab hier\ndrücke Enter'} />);
    await user.click(screen.getByRole("button", { name: "früher" }));
    expect(text()).toBe('messen ab hier\ntippe in "Nachricht" "Hallo"\ndrücke Enter');
    await user.click(screen.getByRole("button", { name: "später" }));
    await user.click(screen.getByRole("button", { name: "Schritt 1 ändern" }));
    const input = screen.getByRole("textbox", { name: "Text für Schritt 1" });
    await user.clear(input);
    await user.type(input, "Was ist ein Lasttest?{Enter}");
    expect(text()).toBe('tippe in "Nachricht" "Was ist ein Lasttest?"\nmessen ab hier\ndrücke Enter');
    await user.click(screen.getByRole("button", { name: "Schritt 3 löschen" }));
    expect(text()).toBe('tippe in "Nachricht" "Was ist ein Lasttest?"\nmessen ab hier');
    expect(screen.getByText(/fehlt noch ein Schritt/)).toBeInTheDocument();
  });

  it("übernimmt Text aus dem Textmodus", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Als Text" }));
    await user.type(screen.getByRole("textbox", { name: "Die Schritte" }), 'klicke "Los"\nhüpfe');
    await user.click(screen.getByRole("button", { name: "Grafisch" }));
    expect(screen.getByText("Unbekannter Schritt")).toBeInTheDocument();
    expect(screen.getByText(/Schritt 2 versteht der Test nicht/)).toBeInTheDocument();
  });

  it("braucht zum Vorführen die Adresse der Startseite", async () => {
    const user = userEvent.setup();
    render(<Harness baseUrl={null} />);
    await user.click(screen.getByRole("button", { name: /Ablauf vorführen/ }));
    expect(screen.getByRole("alert")).toHaveTextContent("Adresse der Startseite");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("ist barrierefrei", async () => {
    const { container } = render(<Harness initial={'tippe in "E-Mail" {email}\nmessen ab hier\nwarte 2 s'} />);
    await expectAccessible(container);
  });
});

describe("Vorführen", () => {
  it("klickt, fragt bei Feldern nach dem Text und baut so den Ablauf", async () => {
    fetchMock
      .mockResolvedValueOnce(reply({ session: "a".repeat(32), snapshot: SNAP, steps_done: 1, error: null }))
      .mockResolvedValueOnce(
        reply({ need: "text", target: { kind: "fill", target: "E-Mail", label: "E-Mail", secret: "email" }, thumb: "data:image/jpeg;base64,BBBB" }),
      )
      .mockResolvedValueOnce(reply({ steps: ['tippe in "E-Mail" {email}'], snapshot: SNAP }))
      .mockResolvedValueOnce(reply({ steps: ['klicke "Anmelden"'], thumb: "data:image/jpeg;base64,CCCC", snapshot: SNAP }))
      .mockResolvedValueOnce(reply({ steps: ["drücke Enter", "warte bis die Seite ruhig ist (2 s)"], snapshot: SNAP }))
      .mockResolvedValue(reply({ ok: true } as LiveReply));
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Ablauf vorführen/ }));
    const dialog = screen.getByRole("dialog", { name: "Ablauf vorführen" });
    expect(sent(0)).toEqual({ steps: "öffne https://chat.example/login", secrets: {} });

    // Feld: Rückfrage, Zugangsdaten bleiben im Formular, im Ablauf steht nur der Platzhalter
    await user.click(await within(dialog).findByRole("button", { name: "Eingeben in „E-Mail“" }));
    expect(sent(1).action).toEqual({ type: "pick", mark: "0", measuring: false });
    const input = await within(dialog).findByLabelText("Was soll in „E-Mail“ hinein?");
    expect(input).toHaveAttribute("type", "password");
    await user.type(input, "tester@example.de");
    await user.click(within(dialog).getByRole("button", { name: "Eingeben" }));
    expect(sent(2)).toMatchObject({ action: { type: "fill", target: { target: "E-Mail" }, text: "{email}", enter: false }, secrets: { email: "tester@example.de" } });
    await waitFor(() => expect(text()).toBe('tippe in "E-Mail" {email}'));
    expect(screen.getByTestId("secrets").textContent).toContain("tester@example.de");

    // Knopf: sofort geklickt
    await user.click(await within(dialog).findByRole("button", { name: "Klicken auf „Anmelden“" }));
    await waitFor(() => expect(text()).toBe('tippe in "E-Mail" {email}\nklicke "Anmelden"'));

    // Ab hier messen, dann Enter – die Seite schreibt noch, Warten wird ergänzt
    await user.click(within(dialog).getByRole("button", { name: "⏱ Ab hier messen" }));
    await user.click(within(dialog).getByRole("button", { name: "↵ Enter drücken" }));
    expect(sent(4).action).toEqual({ type: "press", key: "Enter", measuring: true });
    await waitFor(() =>
      expect(text()).toBe('tippe in "E-Mail" {email}\nklicke "Anmelden"\nmessen ab hier\ndrücke Enter\nwarte bis die Seite ruhig ist (2 s)'),
    );
    expect(within(dialog).getByRole("status")).toHaveTextContent("Warten, bis die Seite fertig ist");
    await expectAccessible(dialog);

    await user.click(within(dialog).getByRole("button", { name: "Fertig" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(fetchMock.mock.calls.at(-1)?.[0]).toBe("/api/flow/live/stop"));
    expect(screen.getByRole("button", { name: /Weiter vorführen/ })).toHaveFocus();
  });

  it("zeigt, wo das Abspielen hängt, und macht dort weiter", async () => {
    fetchMock
      .mockResolvedValueOnce(reply({ session: "b".repeat(32), snapshot: SNAP, steps_done: 2, error: { index: 2, message: "„klicke „Weiter““ hat nicht geklappt." } }))
      .mockResolvedValue(reply({ ok: true } as LiveReply));
    const user = userEvent.setup();
    render(<Harness initial={'klicke "Anmelden"\nklicke "Weiter"\ndrücke Enter'} />);
    await user.click(screen.getByRole("button", { name: /Weiter vorführen/ }));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText(/^Schritt 2: „klicke „Weiter““ hat nicht geklappt/)).toBeInTheDocument();
    expect(within(dialog).getByText("Hier ist das Vorführen hängen geblieben.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Ab Schritt 2 neu vorführen" }));
    expect(text()).toBe('klicke "Anmelden"');
  });

  it("fragt vor dem Start nach fehlenden Zugangsdaten", async () => {
    fetchMock.mockResolvedValue(reply({ session: "c".repeat(32), snapshot: SNAP, steps_done: 2, error: null }));
    const user = userEvent.setup();
    render(<Harness initial={'tippe in "Passwort" {passwort}'} />);
    await user.click(screen.getByRole("button", { name: /Weiter vorführen/ }));
    expect(fetchMock).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Wert für {passwort}"), "geheim");
    await user.click(screen.getByRole("button", { name: "Starten" }));
    expect(sent(0).secrets).toEqual({ passwort: "geheim" });
  });

  it("meldet Fehler des Backends", async () => {
    fetchMock.mockResolvedValue(reply({ error: "Die Startseite lässt sich nicht öffnen: Zeitüberschreitung." }, 400));
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /Ablauf vorführen/ }));
    expect(await screen.findByText(/Startseite lässt sich nicht öffnen/)).toBeInTheDocument();
  });
});
