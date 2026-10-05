import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { initialLive, normalizeSummary, type LiveState } from "@/lib/events";
import { apiSummary, finishedSummary, webSummary } from "@/test/fixtures";
import { expectAccessible } from "@/test/setup";
import { LiveView } from "./live/LiveView";
import { ResultView } from "./result/ResultView";
import { RunsList } from "./RunsList";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));

function runningState(): LiveState {
  const s = finishedSummary();
  return {
    ...initialLive,
    connected: true,
    run: "results_20261004_234100",
    state: "running",
    summary: {
      ...s,
      meta: { started: "2026-10-04T23:41:00", current_test: "ramp" },
      ramp: { steps: s.ramp!.steps.slice(0, 4), break: null, saturated: null },
      rate: undefined, context: undefined, spike: undefined, soak: undefined, control: undefined,
    },
    samples: [
      { t: 20, phase: "baseline" },
      { t: 72, phase: "ramp_c1" },
      { t: 190, phase: "ramp_c32", kv: 72, waiting: 3 },
    ],
    logs: ["[23:39:12] ━━ 2/6 Immer mehr gleichzeitig ━━", "[23:40:49]     32 gleichzeitig: 30s messen …"],
  };
}

describe("LiveView", () => {
  it("zeigt Stufe, Urteil in Worten, Ablauf und Protokoll", async () => {
    const { container } = render(<LiveView live={runningState()} onStop={vi.fn()} />);

    expect(screen.getByRole("heading", { level: 1, name: "Der Server hält mit." })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Stufe 4 / 5: 32 gleichzeitig" })).toBeInTheDocument();

    const steps = within(screen.getByRole("list", { name: "Ablauf des Tests" })).getAllByRole("listitem");
    expect(steps).toHaveLength(8);
    expect(steps[2]).toHaveAttribute("aria-current", "step");
    expect(steps[2]).toHaveTextContent("Stufe 4 von 5 · 32 gleichzeitig");
    expect(steps[1]).toHaveTextContent("erledigt");

    expect(screen.getByText("Reicht für etwa")).toBeInTheDocument();
    expect(screen.getByText("140")).toBeInTheDocument();
    expect(screen.getByRole("log", { name: "Protokoll" })).toHaveTextContent("32 gleichzeitig: 30s messen");
    expect(screen.getByRole("progressbar", { name: "Gesamtfortschritt" })).toBeInTheDocument();
    await expectAccessible(container);
  });

  it("bietet die Lastkurve auch als Tabelle an", () => {
    render(<LiveView live={runningState()} onStop={vi.fn()} />);
    const table = screen.getByRole("table", { name: /Gesamtleistung und Wartezeit je Stufe/ });
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    expect(within(table).getByRole("cell", { name: "612 tok/s" })).toBeInTheDocument();
  });

  it("bricht erst nach Rückfrage ab", async () => {
    const onStop = vi.fn();
    const user = userEvent.setup();
    render(<LiveView live={runningState()} onStop={onStop} />);
    await user.click(screen.getByRole("button", { name: "Abbrechen" }));
    expect(onStop).not.toHaveBeenCalled();
    const dialog = screen.getByRole("alertdialog", { name: "Test wirklich abbrechen?" });
    await user.click(within(dialog).getByRole("button", { name: "Ja, abbrechen" }));
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("erklärt, wenn kein Test läuft, und meldet Fehler", () => {
    const { rerender } = render(<LiveView live={{ ...initialLive, connected: true }} onStop={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Gerade läuft kein Test." })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Neuen Test starten/ })).toHaveAttribute("href", "/");

    rerender(
      <LiveView
        live={{ ...runningState(), state: "error", error: "Server nicht erreichbar" }}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Server nicht erreichbar");
  });

  it("verlinkt nach dem Ende auf das Ergebnis", () => {
    render(<LiveView live={{ ...runningState(), state: "done" }} onStop={vi.fn()} />);
    expect(screen.getByRole("link", { name: /Ergebnis ansehen/ })).toHaveAttribute(
      "href",
      "/laeufe/results_20261004_234100",
    );
    expect(screen.queryByRole("button", { name: "Abbrechen" })).not.toBeInTheDocument();
  });
});

describe("ResultView", () => {
  it("zeigt Urteil, Kennzahlen, Ampel und Kosten", async () => {
    const { container } = render(
      <ResultView name="results_20261004_234100" summary={finishedSummary()} report pdf />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Grünes Licht." })).toBeInTheDocument();
    expect(screen.getByText("Der Server ist für unseren Einsatz geeignet.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /PowerPoint herunterladen/ })).toHaveAttribute(
      "href",
      "/api/runs/results_20261004_234100/report.pptx",
    );
    expect(screen.getByRole("link", { name: /PDF/ })).toHaveAttribute(
      "href",
      "/api/runs/results_20261004_234100/report.pdf",
    );

    const ampel = within(screen.getByRole("list", { name: "Alle Ergebnisse auf einen Blick" })).getAllByRole("listitem");
    expect(ampel).toHaveLength(7);
    // Die Farbe allein reicht nicht: der Status steht auch als Text da.
    expect(ampel[0]).toHaveTextContent("Grün");
    expect(ampel[3]).toHaveTextContent("Gelb");
    expect(ampel[3]).toHaveTextContent("8,4 s bis zum 1. Wort");

    expect(screen.getByText("≈ 2.150 €")).toBeInTheDocument();
    expect(screen.getByText(/Preise sind Platzhalter/)).toBeInTheDocument();
    await expectAccessible(container);
  });

  it("blendet fehlende Berichte aus und nennt die Gründe bei Rot", () => {
    const s = finishedSummary();
    s.verdict = { status: "bad", headline: "Der Server reicht in dieser Form nicht aus.", reasons: [["bad", "Reicht nur für 20 Nutzer."]] };
    render(<ResultView name="results_1" summary={s} report={false} pdf={false} />);
    expect(screen.getByRole("heading", { level: 1, name: "Rotes Licht." })).toBeInTheDocument();
    expect(screen.getByText("Reicht nur für 20 Nutzer.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /PowerPoint/ })).not.toBeInTheDocument();
  });
});

describe("RunsList", () => {
  const runs = ["results_20261004_234100", "results_20261003_101500", "results_20261001_080000"].map((name) => ({
    name, model: "brain", base_url: "http://spark.buero.lan:8000/v1", started: null, tests: ["baseline", "ramp"], report: true, pdf: true,
  }));

  it("aktiviert den Vergleich erst ab zwei gewählten Läufen", async () => {
    const user = userEvent.setup();
    const { container } = render(<RunsList runs={runs} />);
    const compare = () => screen.getByRole("link", { name: /vergleichen/i });

    expect(compare()).toHaveAttribute("aria-disabled", "true");
    const boxes = screen.getAllByRole("checkbox");
    await user.click(boxes[0]);
    expect(compare()).toHaveAttribute("aria-disabled", "true");
    await user.click(boxes[2]);
    expect(compare()).not.toHaveAttribute("aria-disabled");
    expect(compare()).toHaveAttribute(
      "href",
      "/api/compare?runs=results_20261004_234100%2Cresults_20261001_080000",
    );
    expect(screen.getByRole("link", { name: /04\.10\.2026, 23:41/ })).toHaveAttribute(
      "href",
      "/laeufe/results_20261004_234100",
    );
    await expectAccessible(container);
  });

  it("zeigt einen freundlichen Leerzustand", () => {
    render(<RunsList runs={[]} />);
    expect(screen.getByText(/Noch keine Läufe/)).toBeInTheDocument();
  });
});

describe("LiveView direkt nach dem Start", () => {
  it("zeigt den Vorab-Check, auch wenn noch keine Messwerte da sind", () => {
    const early = normalizeSummary({ config: finishedSummary().config, meta: {} } as never)!;
    render(<LiveView live={{ ...initialLive, connected: true, state: "running", run: "results_1", summary: early }} onStop={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1, name: "Messung läuft …" })).toBeInTheDocument();
    const steps = within(screen.getByRole("list", { name: "Ablauf des Tests" })).getAllByRole("listitem");
    expect(steps[0]).toHaveAttribute("aria-current", "step");
  });
});

describe("Website-Läufe in den Ansichten", () => {
  it("zeigt das Ergebnis mit Besuchern und ohne Kostenvergleich", async () => {
    const { container } = render(<ResultView name="results_1" summary={webSummary()} report={false} pdf={false} />);
    expect(screen.getByRole("heading", { level: 1, name: "Grünes Licht." })).toBeInTheDocument();
    expect(screen.getByText(/für 500 Besucher geplant/)).toBeInTheDocument();
    expect(screen.getByText(/Besucher gleichzeitig/)).toBeInTheDocument();
    expect(screen.queryByText("Lohnt sich der eigene Server?")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Was wurde gemessen?" })).toBeInTheDocument();
    expect(screen.getByText(/12 Dateien/)).toBeInTheDocument();
    expect(screen.queryByText(/tok\/s/)).not.toBeInTheDocument();
    await expectAccessible(container);
  });

  it("zeigt live die Website-Begriffe", () => {
    const s = webSummary();
    render(
      <LiveView
        live={{ ...initialLive, connected: true, state: "running", run: "results_1", summary: { ...s, meta: { current_test: "ramp" } }, samples: [{ t: 90, phase: "ramp_c64" }] }}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Es wird eng." })).toBeInTheDocument();
    expect(screen.getAllByText("Seiten pro Sekunde").length).toBeGreaterThan(0);
    expect(screen.getByText("Besucher gleichzeitig auf der Website")).toBeInTheDocument();
    expect(screen.queryByText(/tok\/s/)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Server" })).not.toBeInTheDocument();
  });

  it("kennzeichnet die Art jedes Laufs", () => {
    render(
      <RunsList
        runs={[
          { name: "results_20261005_100000", kind: "web", model: null, base_url: "https://shop.example/", started: null, tests: ["baseline", "ramp"], report: false, pdf: false },
          { name: "results_20261004_234100", kind: "llm", model: "brain", base_url: "http://spark:8000/v1", started: null, tests: ["ramp"], report: true, pdf: true },
        ]}
      />,
    );
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes[0]).toBeEnabled();
    expect(boxes[1]).toBeEnabled();
    expect(screen.getByText("Website")).toBeInTheDocument();
  });

  it("lässt nur Läufe gleicher Art miteinander vergleichen", async () => {
    const user = userEvent.setup();
    const run = (name: string, kind: "web" | "llm") => ({
      name, kind, model: null, base_url: "https://shop.example/", started: null, tests: ["ramp"], report: true, pdf: true,
    });
    render(
      <RunsList
        runs={[run("results_20261006_090000", "web"), run("results_20261005_100000", "web"), run("results_20261004_234100", "llm")]}
      />,
    );
    const boxes = screen.getAllByRole("checkbox");
    await user.click(boxes[0]);
    // Ein Website-Lauf ist gewählt: der KI-Server-Lauf passt nicht dazu
    expect(boxes[2]).toBeDisabled();
    expect(boxes[2]).toHaveAccessibleName(/passt nicht zur Auswahl/);
    expect(boxes[1]).toBeEnabled();
    await user.click(boxes[1]);
    expect(screen.getByRole("link", { name: /vergleichen/i })).toHaveAttribute(
      "href",
      "/api/compare?runs=results_20261006_090000%2Cresults_20261005_100000",
    );
    // Auswahl aufheben gibt alle wieder frei
    await user.click(boxes[0]);
    await user.click(boxes[1]);
    expect(boxes[2]).toBeEnabled();
  });

  it("bietet PowerPoint, PDF und Vergleich auch für Website-Läufe an", () => {
    render(<ResultView name="results_20261005_100000" summary={webSummary()} report pdf />);
    expect(screen.getByRole("link", { name: /PowerPoint herunterladen/ })).toHaveAttribute(
      "href",
      "/api/runs/results_20261005_100000/report.pptx",
    );
    expect(screen.getByRole("link", { name: /PDF/ })).toHaveAttribute("href", "/api/runs/results_20261005_100000/report.pdf");
    expect(screen.getByRole("link", { name: /Vergleichen/ })).toHaveAttribute("href", "/laeufe");
    expect(screen.queryByText(/noch nicht/)).not.toBeInTheDocument();
    expect(screen.getByText(/zusammen rund 469 kB/)).toBeInTheDocument();
  });
});

describe("LiveView bei unterbrochener Verbindung", () => {
  it("sagt, dass neu verbunden wird und der Test weiterläuft", () => {
    render(<LiveView live={{ ...initialLive, connected: true, offline: true, state: "running", run: "results_1", summary: webSummary() }} onStop={vi.fn()} />);
    expect(screen.getByRole("status", { name: "Verbindung" })).toHaveTextContent(/Verbindung unterbrochen.*läuft weiter/);
  });

  it("zeigt den Hinweis sonst nicht", () => {
    render(<LiveView live={{ ...initialLive, connected: true, state: "running", run: "results_1", summary: webSummary() }} onStop={vi.fn()} />);
    expect(screen.queryByRole("status", { name: "Verbindung" })).not.toBeInTheDocument();
  });
});

describe("HTTP-API-Läufe in den Ansichten", () => {
  it("zeigt das Ergebnis mit Anfragen pro Minute und der getesteten Anfrage", async () => {
    const { container } = render(<ResultView name="results_1" summary={apiSummary()} report pdf />);
    expect(screen.getByRole("heading", { level: 1, name: "Grünes Licht." })).toBeInTheDocument();
    expect(screen.getByText(/für 1.000 Anfragen\/min geplant/)).toBeInTheDocument();
    expect(screen.getAllByText(/Anfragen pro Minute/).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Was wurde gemessen?" })).toBeInTheDocument();
    expect(screen.getByText(/POST \/v1\/items/)).toBeInTheDocument();
    expect(screen.getByText(/Status 201/)).toBeInTheDocument();
    expect(screen.getByText(/verändert/)).toBeInTheDocument();
    expect(screen.queryByText(/Besucher/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Dateien/)).not.toBeInTheDocument();
    await expectAccessible(container);
  });

  it("zeigt live die API-Begriffe", () => {
    render(
      <LiveView
        live={{ ...initialLive, connected: true, state: "running", run: "results_1", summary: { ...apiSummary(), meta: { current_test: "ramp" } }, samples: [{ t: 90, phase: "ramp_c64" }] }}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Es wird eng." })).toBeInTheDocument();
    expect(screen.getByText("Anfragen pro Minute, die flüssig durchgehen")).toBeInTheDocument();
    expect(screen.queryByText(/Besucher/)).not.toBeInTheDocument();
  });

  it("kennzeichnet API-Läufe in der Liste", () => {
    render(<RunsList runs={[{ name: "results_20261006_090000", kind: "api", model: null, base_url: "https://api.example/v1/items", started: null, tests: ["ramp"], report: true, pdf: true }]} />);
    expect(screen.getByText("HTTP-API")).toBeInTheDocument();
  });
});
