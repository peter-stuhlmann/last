import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { expectAccessible } from "@/test/setup";
import { NewTestForm } from "./NewTestForm";

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
    expect(screen.getByRole("radio", { name: /HTTP-API/ })).toBeDisabled();
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
