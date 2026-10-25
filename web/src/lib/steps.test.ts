import { describe, expect, it } from "vitest";
import { formatSteps, freePlaceholder, parseLine, parseSteps, secretName, sentence, stepProblems, withStart } from "./steps";

const EXAMPLE = `tippe in "E-Mail" {email}
tippe in "Passwort" {passwort}
klicke "Anmelden"
warte auf Text "Willkommen"
messen ab hier
tippe in "Nachricht" "Was ist ein Lasttest?"
drücke Enter
warte auf erste Antwort in ".antwort"
warte bis ".antwort" fertig ist (2 s ruhig)`;

describe("Schritt-Sprache", () => {
  it("liest alle Arten wie das Backend", () => {
    expect(parseSteps(EXAMPLE).map((s) => s.kind)).toEqual([
      "fill",
      "fill",
      "click",
      "wait_text",
      "measure",
      "fill",
      "press",
      "wait_first",
      "wait_done",
    ]);
    expect(parseLine('tippe in "Nachricht" "Was ist ein Lasttest?"')).toEqual({
      kind: "fill",
      target: "Nachricht",
      text: "Was ist ein Lasttest?",
    });
    expect(parseLine("drücke esc")).toEqual({ kind: "press", key: "Escape" });
    expect(parseLine("warte 2,5 s")).toEqual({ kind: "wait_s", seconds: 2.5 });
    expect(parseLine('warte bis ".a" fertig ist')).toEqual({ kind: "wait_done", target: ".a", quiet: 3 });
    expect(parseLine("── messen ab hier ──")).toEqual({ kind: "measure" });
    expect(parseLine("öffne https://x.test/chat")).toEqual({ kind: "open", url: "https://x.test/chat" });
  });

  it("schreibt denselben Text zurück", () => {
    expect(formatSteps(parseSteps(EXAMPLE))).toBe(EXAMPLE);
  });

  it("behält unbekannte Zeilen und Kommentare wörtlich", () => {
    const steps = parseSteps('# Anmeldung\nhüpfe dreimal\n\nklicke "Los"');
    expect(steps).toEqual([
      { kind: "raw", line: "# Anmeldung" },
      { kind: "raw", line: "hüpfe dreimal" },
      { kind: "click", target: "Los" },
    ]);
    expect(formatSteps(steps)).toBe('# Anmeldung\nhüpfe dreimal\nklicke "Los"');
  });

  it("lässt beim Tippen Leerzeichen stehen und nimmt Anführungszeichen aus dem Ziel", () => {
    expect(formatSteps([{ kind: "click", target: 'Neue "Nachricht ' }])).toBe('klicke "Neue Nachricht "');
    expect(formatSteps([{ kind: "fill", target: "Feld", text: "" }])).toBe('tippe in "Feld" ""');
    expect(parseLine('tippe in "Feld" ""')).toEqual({ kind: "fill", target: "Feld", text: "" });
  });

  it("versteht mehrfache Ziele und die ruhige Seite wie das Backend", () => {
    const text = [
      'klicke "Löschen" bei "Bestellung 4711"',
      'klicke "Löschen" (Nr. 3)',
      'tippe in "Menge" bei "Zeile 2" (Nr. 2) "3"',
      "warte bis die Seite ruhig ist (2,5 s)",
    ].join("\n");
    const steps = parseSteps(text);
    expect(steps[0]).toEqual({ kind: "click", target: "Löschen", near: "Bestellung 4711" });
    expect(steps[1]).toEqual({ kind: "click", target: "Löschen", nth: 3 });
    expect(steps[2]).toEqual({ kind: "fill", target: "Menge", near: "Zeile 2", nth: 2, text: "3" });
    expect(steps[3]).toEqual({ kind: "wait_quiet", quiet: 2.5 });
    expect(formatSteps(steps)).toBe(text);
    expect(parseLine("warte bis die Seite ruhig ist")).toEqual({ kind: "wait_quiet", quiet: 2 });
  });

  it("beschreibt Schritte in Alltagssprache", () => {
    expect(sentence(parseLine('klicke "Löschen" bei "Bestellung 4711"'))).toEqual({
      title: "Klicken",
      what: "Löschen",
      detail: "bei „Bestellung 4711“",
    });
    expect(sentence(parseLine('klicke "Löschen" (Nr. 2)')).detail).toBe("der 2. auf der Seite");
    expect(sentence(parseLine('tippe in "E-Mail" {email}')).detail).toBe("Zugangsdaten {email}");
    expect(sentence(parseLine('tippe in "Nachricht" "Hallo"')).detail).toBe("„Hallo“");
    expect(sentence(parseLine("drücke Enter")).what).toBe("Enter ↵");
    expect(sentence(parseLine("warte bis die Seite ruhig ist")).title).toMatch(/fertig/);
    expect(sentence(parseLine("hüpfe")).title).toBe("Unbekannter Schritt");
  });

  it("findet freie Namen für Zugangsdaten", () => {
    expect(secretName("{passwort}")).toBe("passwort");
    expect(secretName("Hallo {name}")).toBeNull();
    expect(freePlaceholder("passwort", [])).toBe("passwort");
    expect(freePlaceholder("passwort", ["passwort", "passwort2"])).toBe("passwort3");
    expect(freePlaceholder("E-Mail Adresse", [])).toBe("EMailAdresse");
    expect(freePlaceholder("123", [])).toBe("wert");
  });

  it("nennt, was noch fehlt", () => {
    expect(stepProblems(parseSteps(EXAMPLE))).toEqual([]);
    expect(stepProblems(parseSteps('klicke "Los"')).join()).toMatch(/Ab hier messen/);
    expect(stepProblems(parseSteps('klicke "Los"\nmessen ab hier')).join()).toMatch(/fehlt noch ein Schritt/);
    expect(stepProblems(parseSteps('hüpfe\nmessen\nklicke "x"')).join()).toMatch(/Schritt 1 versteht/);
    expect(stepProblems([{ kind: "click", target: "" }, { kind: "measure" }, { kind: "press", key: "Enter" }]).join()).toMatch(
      /Schritt 1 fehlt das Ziel/,
    );
  });

  it("setzt die Startseite davor, außer der Ablauf beginnt selbst mit öffne", () => {
    expect(withStart('klicke "x"', "https://a.test")).toBe('öffne https://a.test\nklicke "x"');
    expect(withStart("", "https://a.test")).toBe("öffne https://a.test");
    expect(withStart('öffne https://b.test\nklicke "x"', "https://a.test")).toBe('öffne https://b.test\nklicke "x"');
  });
});
