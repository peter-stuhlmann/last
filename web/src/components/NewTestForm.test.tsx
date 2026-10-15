import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectAccessible } from "@/test/setup";
import { NewTestForm, parseAccounts } from "./NewTestForm";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const defaults = {
  base_url: "http://host.docker.internal:8000/v1",
  levels: "1,2,4,8,16,32,64,128,256",
  level_seconds: 60,
  soak_minutes: 15,
  slo_ttft: 2,
  slo_user_tps: 10,
  target_users: 0,
  hw_price: 4000,
};
const quick = { levels: "1,4,16,32,64", level_seconds: 30, soak_minutes: 3 };

const fetchMock = vi.fn();

beforeEach(() => {
  push.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  localStorage.clear();
});
afterEach(() => vi.unstubAllGlobals());

function setup() {
  const user = userEvent.setup();
  const view = render(<NewTestForm defaults={defaults} quick={quick} />);
  return { user, ...view };
}

function sentBody(call = 0) {
  return JSON.parse(fetchMock.mock.calls[call][1].body);
}

describe("NewTestForm", () => {
  it("zeigt beschriftete Felder und ist barrierefrei", async () => {
    const { container } = setup();
    expect(screen.getByRole("textbox", { name: "Adresse des Servers" })).toHaveValue(defaults.base_url);
    expect(screen.getByRole("radio", { name: /Schnell/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Gründlich/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /HTTP-API/ })).toBeEnabled();
    expect(screen.getByRole("spinbutton", { name: /Nutzer im Team/ })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: /Warten höchstens/ })).toHaveValue(2);
    expect(screen.getByRole("spinbutton", { name: /Lesetempo mindestens/ })).toHaveValue(10);
    expect(screen.getByText("5 Stufen · bis 64 gleichzeitig")).toBeInTheDocument();
    expect(screen.getByText("9 Stufen · bis 256 gleichzeitig")).toBeInTheDocument();
    await expectAccessible(container);
  });

  it("startet mit dem Schnell-Profil und wechselt zur Live-Ansicht", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, run: "results_1" }));
    const { user } = setup();
    const url = screen.getByRole("textbox", { name: "Adresse des Servers" });
    await user.clear(url);
    await user.type(url, "http://spark.buero.lan:8000/v1");
    await user.type(screen.getByRole("spinbutton", { name: /Nutzer im Team/ }), "80");
    await user.click(screen.getByRole("button", { name: /Test starten/ }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/lauf"));
    expect(fetchMock.mock.calls[0][0]).toBe("/api/start");
    expect(sentBody()).toMatchObject({
      base_url: "http://spark.buero.lan:8000/v1",
      target_users: 80,
      slo_ttft: 2,
      slo_user_tps: 10,
      levels: "1,4,16,32,64",
      level_seconds: 30,
      soak_minutes: 3,
    });
  });

  it("schickt beim Profil „Gründlich“ die Standardwerte", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, run: "results_1" }));
    const { user } = setup();
    await user.click(screen.getByRole("radio", { name: /Gründlich/ }));
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(sentBody()).toMatchObject({ levels: "1,2,4,8,16,32,64,128,256", level_seconds: 60, soak_minutes: 15 });
  });

  it("lässt sich mit Enter im Adressfeld starten", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, run: "results_1" }));
    const { user } = setup();
    await user.type(screen.getByRole("textbox", { name: "Adresse des Servers" }), "{Enter}");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/lauf"));
  });

  it("meldet eine ungültige Adresse am Feld und fragt den Server nicht", async () => {
    const { user } = setup();
    const url = screen.getByRole("textbox", { name: "Adresse des Servers" });
    await user.clear(url);
    await user.type(url, "spark.buero.lan");
    await user.click(screen.getByRole("button", { name: /Test starten/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/http:\/\/ oder https:\/\//);
    expect(url).toHaveAttribute("aria-invalid", "true");
    expect(url).toHaveFocus();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("zeigt Fehler des Servers an", async () => {
    fetchMock.mockResolvedValue(Response.json({ error: "Es läuft bereits ein Test." }, { status: 409 }));
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Es läuft bereits ein Test.");
    expect(push).not.toHaveBeenCalled();
  });

  it("prüft die Verbindung und bietet die gefundenen Modelle an", async () => {
    fetchMock.mockResolvedValue(Response.json({ models: [{ id: "brain", max_len: 32768 }] }));
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Verbindung prüfen" }));
    const status = await screen.findByText(/erreichbar · brain/);
    expect(status.closest("[role=status]")).not.toBeNull();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/models");
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
  });

  it("speichert Einstellungen, aber niemals den API-Schlüssel", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, run: "results_1" }));
    const { user } = setup();
    await user.click(screen.getByText("Weitere Einstellungen"));
    const more = within(screen.getByRole("group", { name: "Weitere Einstellungen" }));
    await user.type(more.getByLabelText("API-Schlüssel"), "sk-geheim");
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    await waitFor(() => expect(push).toHaveBeenCalled());

    expect(sentBody().api_key).toBe("sk-geheim");
    const stored = JSON.stringify({ ...localStorage });
    expect(stored).toContain("host.docker.internal");
    expect(stored).not.toContain("sk-geheim");
  });
});

describe("NewTestForm für Websites", () => {
  const web = {
    defaults: { levels: "1,2,4,8,16,32,64,128,256", level_seconds: 60, soak_minutes: 15, slo_load: 3, think_time: 30, tests: "baseline,ramp,rate,spike,soak" },
    quick: { levels: "1,4,16,32,64", level_seconds: 30, soak_minutes: 3 },
  };

  function setupWeb() {
    const user = userEvent.setup();
    render(<NewTestForm defaults={defaults} quick={quick} web={web} />);
    return user;
  }

  it("stellt nach der Wahl „Website“ auf Besucher und Ladezeit um", async () => {
    const user = setupWeb();
    expect(screen.getByRole("radio", { name: /Website/ })).toBeEnabled();
    await user.click(screen.getByRole("radio", { name: /Website/ }));

    expect(screen.getByRole("textbox", { name: "Adresse der Website" })).toHaveValue("");
    expect(screen.getByRole("spinbutton", { name: /Besucher gleichzeitig/ })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: /Seite geladen nach höchstens/ })).toHaveValue(3);
    expect(screen.getByRole("spinbutton", { name: /Pause zwischen zwei Klicks/ })).toHaveValue(30);
    expect(screen.queryByRole("spinbutton", { name: /Lesetempo/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verbindung prüfen" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /eigene Website/ })).not.toBeChecked();
  });

  it("startet erst nach der Bestätigung und schickt die Website-Felder", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, run: "results_1" }));
    const user = setupWeb();
    await user.click(screen.getByRole("radio", { name: /Website/ }));
    await user.type(screen.getByRole("textbox", { name: "Adresse der Website" }), "https://shop.example/");
    await user.type(screen.getByRole("spinbutton", { name: /Besucher gleichzeitig/ }), "500");

    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/bestätig/i);
    expect(screen.getByRole("checkbox", { name: /eigene Website/ })).toHaveFocus();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("checkbox", { name: /eigene Website/ }));
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/lauf"));
    const body = sentBody();
    expect(body).toMatchObject({
      kind: "web",
      base_url: "https://shop.example",
      confirm_owner: true,
      include_assets: true,
      target_users: 500,
      slo_load: 3,
      think_time: 30,
      levels: "1,4,16,32,64",
      tests: "baseline,ramp,rate,spike,soak",
    });
    expect(body).not.toHaveProperty("api_key");
    expect(body).not.toHaveProperty("slo_ttft");
    expect(body).not.toHaveProperty("hw_price");
  });
});

describe("NewTestForm für HTTP-APIs", () => {
  const api = {
    defaults: { levels: "1,2,4,8,16,32,64,128,256", level_seconds: 60, soak_minutes: 15, slo_load: 0.5, tests: "baseline,ramp,rate,spike,soak" },
    quick: { levels: "1,4,16,32,64", level_seconds: 30, soak_minutes: 3 },
  };

  function setupApi() {
    const user = userEvent.setup();
    render(<NewTestForm defaults={defaults} quick={quick} api={api} />);
    return user;
  }

  it("bietet Methode, Status, Kopfzeilen und Body an", async () => {
    const user = setupApi();
    expect(screen.getByRole("radio", { name: /HTTP-API/ })).toBeEnabled();
    await user.click(screen.getByRole("radio", { name: /HTTP-API/ }));
    expect(screen.getByRole("textbox", { name: "Adresse der API" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Methode" })).toHaveValue("GET");
    expect(screen.getByRole("spinbutton", { name: /Anfragen pro Minute/ })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: /Antwort nach höchstens/ })).toHaveValue(0.5);
    expect(screen.getByRole("textbox", { name: /Erwarteter Status/ })).toHaveValue("2xx");
    expect(screen.queryByRole("textbox", { name: "Body" })).not.toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "Methode" }), "POST");
    expect(screen.getByRole("textbox", { name: "Body" })).toBeInTheDocument();
    expect(screen.getByText(/verändert der Test Daten/)).toBeInTheDocument();
  });

  it("schickt Kopfzeilen und Body mit, speichert sie aber nicht", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, run: "results_1" }));
    const user = setupApi();
    await user.click(screen.getByRole("radio", { name: /HTTP-API/ }));
    await user.type(screen.getByRole("textbox", { name: "Adresse der API" }), "https://api.example/v1/items");
    await user.selectOptions(screen.getByRole("combobox", { name: "Methode" }), "POST");
    await user.clear(screen.getByRole("textbox", { name: /Erwarteter Status/ }));
    await user.type(screen.getByRole("textbox", { name: /Erwarteter Status/ }), "201");
    await user.type(screen.getByRole("textbox", { name: "Kopfzeilen" }), "Authorization: Bearer geheim");
    await user.type(screen.getByRole("textbox", { name: "Body" }), '{{"name": "x"}');
    await user.click(screen.getByRole("checkbox", { name: /eigene API/ }));
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/lauf"));

    expect(sentBody()).toMatchObject({
      kind: "api", method: "POST", expect_status: "201", base_url: "https://api.example/v1/items",
      headers: [{ name: "Authorization", value: "Bearer geheim" }], body: '{"name": "x"}',
      confirm_owner: true, slo_load: 0.5, levels: "1,4,16,32,64", tests: "baseline,ramp,rate,spike,soak",
    });
    expect(JSON.stringify({ ...localStorage })).not.toContain("geheim");
    expect(JSON.stringify({ ...localStorage })).not.toContain('"name"');
  });

  it("meldet fehlerhafte Kopfzeilen vor dem Start", async () => {
    const user = setupApi();
    await user.click(screen.getByRole("radio", { name: /HTTP-API/ }));
    await user.type(screen.getByRole("textbox", { name: "Adresse der API" }), "https://api.example/v1/items");
    await user.type(screen.getByRole("textbox", { name: "Kopfzeilen" }), "ohne doppelpunkt");
    await user.click(screen.getByRole("checkbox", { name: /eigene API/ }));
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Name: Wert/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("NewTestForm für Abläufe", () => {
  const flow = {
    defaults: { levels: "1,2,4,8,16,32", level_seconds: 60, soak_minutes: 15, slo_load: 10, think_time: 60, tests: "baseline,ramp,rate,spike,soak" },
    quick: { levels: "1,2,4,8,16", level_seconds: 30, soak_minutes: 3 },
  };
  const steps = 'tippe in "E-Mail" {email}\ntippe in "Passwort" {passwort}\nklicke "Anmelden"\nmessen ab hier\nklicke "Senden"';

  function setupFlow() {
    const user = userEvent.setup();
    render(<NewTestForm defaults={defaults} quick={quick} flow={flow} />);
    return user;
  }

  it("bietet Schritte an und macht aus Platzhaltern Passwortfelder", async () => {
    const user = setupFlow();
    await user.click(screen.getByRole("radio", { name: /Ablauf/ }));
    await user.click(screen.getByRole("button", { name: "Als Text" }));
    expect(screen.getByRole("textbox", { name: "Adresse der Startseite" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: /Nutzer gleichzeitig/ })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: /Antwort fertig nach höchstens/ })).toHaveValue(10);
    expect(screen.getByRole("spinbutton", { name: /Pause zwischen zwei Durchläufen/ })).toHaveValue(60);
    const area = screen.getByRole("textbox", { name: "Die Schritte" });
    expect(screen.queryByLabelText(/Wert für/)).not.toBeInTheDocument();
    await user.type(area, steps.replaceAll("{", "{{"));
    expect(screen.getByLabelText("Wert für {email}")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Wert für {passwort}")).toHaveAttribute("type", "password");
  });

  it("schickt Schritte und Platzhalter-Werte, merkt sich aber keine Werte", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, run: "results_1" }));
    const user = setupFlow();
    await user.click(screen.getByRole("radio", { name: /Ablauf/ }));
    await user.click(screen.getByRole("button", { name: "Als Text" }));
    await user.type(screen.getByRole("textbox", { name: "Adresse der Startseite" }), "https://chat.example/login");
    await user.type(screen.getByRole("textbox", { name: "Die Schritte" }), steps.replaceAll("{", "{{"));
    await user.type(screen.getByLabelText("Wert für {email}"), "tester@example.de");
    await user.type(screen.getByLabelText("Wert für {passwort}"), "sehr-geheim");
    await user.click(screen.getByRole("checkbox", { name: /eigene Anwendung/ }));
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/lauf"));

    expect(sentBody()).toMatchObject({
      kind: "flow", base_url: "https://chat.example/login", steps: `öffne https://chat.example/login\n${steps}`,
      secrets: { email: "tester@example.de", passwort: "sehr-geheim" }, confirm_owner: true,
      slo_load: 10, think_time: 60, levels: "1,2,4,8,16", tests: "baseline,ramp,rate,spike,soak",
    });
    const stored = JSON.stringify({ ...localStorage });
    expect(stored).not.toContain("geheim");
    expect(stored).not.toContain("tester@");
    expect(stored).toContain("klicke");
  });

  it("verlangt Schritte und Platzhalter-Werte vor dem Start", async () => {
    const user = setupFlow();
    await user.click(screen.getByRole("radio", { name: /Ablauf/ }));
    await user.click(screen.getByRole("button", { name: "Als Text" }));
    await user.type(screen.getByRole("textbox", { name: "Adresse der Startseite" }), "https://chat.example/login");
    await user.click(screen.getByRole("checkbox", { name: /eigene Anwendung/ }));
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Schritt/);
    await user.type(screen.getByRole("textbox", { name: "Die Schritte" }), 'tippe in "Passwort" {{passwort}\nmessen ab hier\nklicke "Senden"');
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/passwort/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("Backend ohne Browser", () => {
  it("bietet Abläufe nur an, wenn das Backend-Image den Browser hat", async () => {
    render(<NewTestForm defaults={defaults} quick={quick} features={{ flow: false }} />);
    const radio = screen.getByRole("radio", { name: /Ablauf/ });
    expect(radio).toBeDisabled();
    expect(screen.getByText("braucht Browser-Image")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Website/ })).toBeEnabled();
  });
});

describe("Abläufe mit mehreren Konten", () => {
  const flow = {
    defaults: { levels: "1,2,4,8,16,32", level_seconds: 60, soak_minutes: 15, slo_load: 10, think_time: 60, tests: "baseline,ramp,rate,spike,soak" },
    quick: { levels: "1,2,4,8,16", level_seconds: 30, soak_minutes: 3 },
  };

  it("liest die Konten-Tabelle und prüft Kopfzeile und Spaltenzahl", () => {
    expect(parseAccounts("email, passwort\na@b.de, eins\nc@d.de; zwei", ["email", "passwort"])).toEqual([
      { email: "a@b.de", passwort: "eins" },
      { email: "c@d.de", passwort: "zwei" },
    ]);
    expect(parseAccounts("{passwort}\tmail\nx\ty", ["passwort"])).toEqual([{ passwort: "x", mail: "y" }]);
    expect(() => parseAccounts("email\na@b.de", ["email", "passwort"])).toThrow(/fehlt die Spalte „passwort“/);
    expect(() => parseAccounts("email, passwort\na@b.de", ["email", "passwort"])).toThrow(/Zeile 2 hat 1 statt 2/);
    expect(() => parseAccounts("email", ["email"])).toThrow(/je Zeile ein Konto/);
  });

  it("schickt accounts statt secrets, wenn mehrere Konten gewählt sind", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, run: "results_1" }));
    const user = userEvent.setup();
    render(<NewTestForm defaults={defaults} quick={quick} flow={flow} />);
    await user.click(screen.getByRole("radio", { name: /Ablauf/ }));
    await user.click(screen.getByRole("button", { name: "Als Text" }));
    await user.type(screen.getByRole("textbox", { name: "Adresse der Startseite" }), "https://chat.example/login");
    await user.type(screen.getByRole("textbox", { name: "Die Schritte" }), 'tippe in "Passwort" {{passwort}\nmessen ab hier\nklicke "Senden"');
    await user.click(screen.getByRole("checkbox", { name: /Mehrere Konten/ }));
    expect(screen.queryByLabelText("Wert für {passwort}")).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Konten" }), "passwort\ngeheim-eins\ngeheim-zwei");
    await user.click(screen.getByRole("checkbox", { name: /eigene Anwendung/ }));
    await user.click(screen.getByRole("button", { name: /Test starten/ }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/lauf"));
    const body = sentBody();
    expect(body.accounts).toEqual([{ passwort: "geheim-eins" }, { passwort: "geheim-zwei" }]);
    expect(body).not.toHaveProperty("secrets");
    expect(JSON.stringify({ ...localStorage })).not.toContain("geheim");
  });
});
