// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET as compare } from "./compare/route";
import { GET as events } from "./events/route";
import { POST as models } from "./models/route";
import { GET as download } from "./runs/[name]/[file]/route";
import { POST as start } from "./start/route";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function post(url: string, body: unknown) {
  return new Request(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

describe("POST /api/start", () => {
  it("leitet nur geprüfte Felder an das Backend weiter", async () => {
    fetchMock.mockResolvedValue(Response.json({ ok: true, run: "results_20261004_234100" }));
    const res = await start(
      post("http://localhost/api/start", {
        base_url: "http://spark.buero.lan:8000/v1/",
        api_key: "sk-geheim",
        target_users: "80",
        out: "/etc",
      }),
    );
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: true, run: "results_20261004_234100" });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://127.0.0.1:8090/api/start");
    const sent = JSON.parse(init.body);
    expect(sent).toEqual({ base_url: "http://spark.buero.lan:8000/v1", api_key: "sk-geheim", target_users: 80 });
  });

  it("lehnt ungültige Eingaben ab, ohne das Backend zu fragen", async () => {
    const res = await start(post("http://localhost/api/start", { base_url: "file:///etc/passwd" }));
    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/http/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("lehnt kaputtes JSON und übergroße Anfragen ab", async () => {
    expect((await start(post("http://localhost/api/start", "{kaputt"))).status).toBe(400);
    const big = await start(post("http://localhost/api/start", { base_url: "http://x/v1", model: "x".repeat(120_000) }));
    expect(big.status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("gibt Backend-Fehler verständlich weiter", async () => {
    fetchMock.mockResolvedValue(Response.json({ error: "Es läuft bereits ein Test." }, { status: 409 }));
    const res = await start(post("http://localhost/api/start", { base_url: "http://x/v1" }));
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ error: "Es läuft bereits ein Test." });
  });

  it("meldet ein nicht erreichbares Backend ohne interne Details", async () => {
    fetchMock.mockRejectedValue(new Error("connect ECONNREFUSED 10.0.0.5:8090"));
    const res = await start(post("http://localhost/api/start", { base_url: "http://x/v1" }));
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain("10.0.0.5");
  });
});

describe("GET /api/events", () => {
  const enc = new TextEncoder();

  async function readAll(res: Response): Promise<string> {
    const reader = res.body!.getReader();
    let text = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return text;
      text += new TextDecoder().decode(value);
    }
  }

  it("reicht den Strom des Backends durch", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        new ReadableStream({
          start(c) {
            c.enqueue(enc.encode("data: 1\n\n"));
            c.close();
          },
        }),
      ),
    );
    const res = await events(new Request("http://localhost/api/events"));
    expect(res.headers.get("content-type")).toContain("text/event-stream");
    expect(await readAll(res)).toBe("data: 1\n\n");
  });

  it("endet sauber, wenn das Backend die Verbindung mittendrin verliert", async () => {
    let n = 0;
    fetchMock.mockResolvedValue(
      new Response(
        new ReadableStream({
          pull(c) {
            if (n++ === 0) c.enqueue(enc.encode("data: 1\n\n"));
            else c.error(new TypeError("terminated"));
          },
        }),
      ),
    );
    const res = await events(new Request("http://localhost/api/events"));
    // Kein Fehler nach außen: der Strom endet einfach, der Browser verbindet sich neu
    await expect(readAll(res)).resolves.toBe("data: 1\n\n");
  });

  it("meldet ein nicht erreichbares Backend als 502", async () => {
    fetchMock.mockRejectedValue(new Error("ECONNREFUSED"));
    expect((await events(new Request("http://localhost/api/events"))).status).toBe(502);
  });
});

describe("POST /api/models", () => {
  it("fragt den Modellserver direkt – der Schlüssel steht nie in der Adresse", async () => {
    fetchMock.mockResolvedValue(
      Response.json({ data: [{ id: "brain", max_model_len: 32768, owned_by: "intern" }, { id: 7 }] }),
    );
    const res = await models(
      post("http://localhost/api/models", { base_url: "http://spark:8000/v1", api_key: "sk-geheim" }),
    );
    expect(await res.json()).toEqual({ models: [{ id: "brain", max_len: 32768 }] });

    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://spark:8000/v1/models");
    expect(String(url)).not.toContain("sk-geheim");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer sk-geheim");
    expect(init.redirect).toBe("error");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("lehnt unzulässige Adressen ab", async () => {
    const res = await models(post("http://localhost/api/models", { base_url: "file:///etc/passwd" }));
    expect(res.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("meldet nicht erreichbare Server ohne interne Details", async () => {
    fetchMock.mockRejectedValue(new Error("getaddrinfo ENOTFOUND intern.db.lan"));
    const res = await models(post("http://localhost/api/models", { base_url: "http://spark:8000/v1" }));
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain("intern.db.lan");
  });

  it("verwirft übergroße Antworten", async () => {
    fetchMock.mockResolvedValue(new Response("x".repeat(3_000_000)));
    const res = await models(post("http://localhost/api/models", { base_url: "http://spark:8000/v1" }));
    expect(res.status).toBe(502);
  });
});

describe("GET /api/runs/[name]/[file]", () => {
  const ctx = (name: string, file: string) => ({ params: Promise.resolve({ name, file }) });

  it("reicht erlaubte Dateien durch", async () => {
    fetchMock.mockResolvedValue(
      new Response("PDF", {
        headers: {
          "content-type": "application/pdf",
          "content-disposition": 'attachment; filename="LLM-Haertetest_x.pdf"',
        },
      }),
    );
    const res = await download(new Request("http://localhost/x"), ctx("results_20261004_234100", "report.pdf"));
    expect(res.status).toBe(200);
    expect(res.headers.get("content-disposition")).toContain("attachment");
    expect(res.headers.get("x-content-type-options")).toBe("nosniff");
    expect(String(fetchMock.mock.calls[0][0])).toBe(
      "http://127.0.0.1:8090/api/runs/results_20261004_234100/report.pdf",
    );
  });

  it("blockt Pfadtricks und unbekannte Dateien", async () => {
    expect((await download(new Request("http://localhost/x"), ctx("..%2F..%2Fetc", "report.pdf"))).status).toBe(404);
    expect((await download(new Request("http://localhost/x"), ctx("results_1", "passwd"))).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("GET /api/compare", () => {
  it("verlangt mindestens zwei gültige Läufe", async () => {
    expect((await compare(new Request("http://localhost/api/compare?runs=results_1"))).status).toBe(400);
    expect((await compare(new Request("http://localhost/api/compare?runs=results_1,../x"))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("gibt die Begründung des Backends weiter, wenn die Läufe nicht zusammenpassen", async () => {
    fetchMock.mockResolvedValue(Response.json({ error: "Bitte nur Läufe gleicher Art vergleichen." }, { status: 400 }));
    const res = await compare(new Request("http://localhost/api/compare?runs=results_1,results_2"));
    expect(res.status).toBe(400);
    expect(await res.json()).toEqual({ error: "Bitte nur Läufe gleicher Art vergleichen." });
  });

  it("verrät bei internen Fehlern keine Details", async () => {
    fetchMock.mockResolvedValue(Response.json({ error: "Traceback /app/report_web.py" }, { status: 500 }));
    const res = await compare(new Request("http://localhost/api/compare?runs=results_1,results_2"));
    expect(res.status).toBe(502);
    expect(JSON.stringify(await res.json())).not.toContain("Traceback");
  });

  it("leitet gültige Namen weiter", async () => {
    fetchMock.mockResolvedValue(new Response("PPTX"));
    const res = await compare(new Request("http://localhost/api/compare?runs=results_1,results_2"));
    expect(res.status).toBe(200);
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://127.0.0.1:8090/api/compare?runs=results_1%2Cresults_2");
  });
});
