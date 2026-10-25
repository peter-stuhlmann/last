import { describe, expect, it } from "vitest";
import { approxUsers, clock, eur, hostLabel, nf, perMinute, runLabel, secs, signedPct, splitSecs } from "./format";

describe("nf", () => {
  it("formatiert deutsch mit fester Nachkommazahl", () => {
    expect(nf(1.38)).toBe("1,4");
    expect(nf(2150, 0)).toBe("2.150");
    expect(nf(0.41, 2)).toBe("0,41");
  });
  it("zeigt einen Strich für fehlende Werte", () => {
    expect(nf(null)).toBe("–");
    expect(nf(undefined)).toBe("–");
    expect(nf(Number.NaN)).toBe("–");
  });
});

describe("secs / splitSecs", () => {
  it("wählt die Genauigkeit nach Größe", () => {
    expect(secs(0.321)).toBe("0,32 s");
    expect(secs(1.38)).toBe("1,4 s");
    expect(secs(12.4)).toBe("12 s");
    expect(secs(null)).toBe("–");
  });
  it("trennt Zahl und Einheit", () => {
    expect(splitSecs(0.321)).toEqual({ value: "0,32", unit: "s" });
  });
});

describe("eur / signedPct / perMinute", () => {
  it("formatiert Beträge", () => {
    expect(eur(2150)).toBe("2.150 €");
    expect(eur(0.41, 2)).toBe("0,41 €");
  });
  it("setzt ein Vorzeichen mit typografischem Minus", () => {
    expect(signedPct(-2)).toBe("−2 %");
    expect(signedPct(38)).toBe("+38 %");
    expect(signedPct(0)).toBe("±0 %");
    expect(signedPct(null)).toBe("–");
  });
  it("rechnet Fragen pro Sekunde in pro Minute um", () => {
    expect(perMinute(2)).toBe("120");
    expect(perMinute(0.05)).toBe("3,0");
  });
});

describe("approxUsers", () => {
  it("rundet wie der Bericht", () => {
    expect(approxUsers(142)).toBe(140);
    expect(approxUsers(1234)).toBe(1200);
    expect(approxUsers(47)).toBe(45);
    expect(approxUsers(12.4)).toBe(12);
    expect(approxUsers(null)).toBeNull();
    expect(approxUsers(0)).toBeNull();
  });
});

describe("clock", () => {
  it("zeigt Minuten:Sekunden", () => {
    expect(clock(21)).toBe("0:21");
    expect(clock(892)).toBe("14:52");
    expect(clock(-3)).toBe("0:00");
    expect(clock(null)).toBe("–");
  });
});

describe("hostLabel / runLabel", () => {
  it("kürzt die Adresse auf den Rechnernamen", () => {
    expect(hostLabel("https://ailaitie.p.tnurl.de/v1")).toBe("ailaitie.p.tnurl.de");
    expect(hostLabel("http://spark.buero.lan:8000/v1")).toBe("spark.buero.lan:8000");
    expect(hostLabel("kaputt")).toBe("kaputt");
    expect(hostLabel(undefined)).toBe("–");
  });
  it("macht aus dem Ordnernamen ein lesbares Datum", () => {
    expect(runLabel("results_20261004_234100")).toBe("04.10.2026, 23:41");
    expect(runLabel("results_x")).toBe("results_x");
  });
});
