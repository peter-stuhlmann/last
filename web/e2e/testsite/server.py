# -*- coding: utf-8 -*-
"""
Winzige Test-Anwendung für die Durchlauf-Tests (nur Python-Standardbibliothek).

Liefert die statischen Dateien in diesem Ordner (Website- und API-Test) und dazu eine kleine
Anwendung mit Anmeldung und KI-Chat-Attrappe für den Ablauf-Test:

  GET  /login                          Anmeldeseite
  POST /login                          JSON {email, pw} → Cookie sid
  GET  /chat                           Chatseite (nur mit Cookie)
  POST /api/conversations              → {"data": {"id": …}} (nur mit Cookie)
  POST /api/conversations/<id>/messages → text/event-stream mit ein paar Wörtern
"""
import json
import os
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
USERS = {("tester@example.de", "sehr-geheim-42"): "sitzung-abcdefgh",
         ("zweite@example.de", "auch-geheim-43"): "sitzung-zweitesk"}

LOGIN_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Anmelden</title></head><body>
<h1>Anmelden</h1>
<form id="f"><label>E-Mail <input name="email" type="email"></label>
<label>Passwort <input name="pw" type="password"></label>
<button type="submit">Anmelden</button></form>
<script>
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch('/login', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({email: f.email.value, pw: f.pw.value})});
  if (r.ok) location.href = '/chat'; else document.body.insertAdjacentHTML('beforeend', '<p>Falsch</p>');
};
</script></body></html>"""

CHAT_PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Chat</title></head><body>
<h1>Willkommen, Tester</h1>
<label>Nachricht <input id="msg"></label> <button id="send">Senden</button>
<div class="antwort"></div>
<script>
async function send() {
  const out = document.querySelector('.antwort'); out.textContent = '';
  const c = await (await fetch('/api/conversations', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: '{}'})).json();
  const r = await fetch('/api/conversations/' + c.data.id + '/messages', {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: document.getElementById('msg').value})});
  const reader = r.body.getReader(); const dec = new TextDecoder();
  for (;;) { const {done, value} = await reader.read(); if (done) break;
    for (const line of dec.decode(value).split('\\n')) if (line.startsWith('data: ') && !line.includes('[DONE]'))
      out.textContent += line.slice(6) + ' '; }
}
document.getElementById('send').onclick = send;
document.getElementById('msg').addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
</script></body></html>"""

known = set()
lock = threading.Lock()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, *a):  # ruhig bleiben
        pass

    def _json(self, obj, status=200, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text):
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _logged_in(self):
        raw = self.headers.get("Cookie") or ""
        return any(part.strip() in {f"sid={sid}" for sid in USERS.values()} for part in raw.split(";"))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/login":
            return self._html(LOGIN_PAGE)
        if path == "/chat":
            return self._html(CHAT_PAGE) if self._logged_in() else self._json({"error": "kein Zugriff"}, 401)
        return super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/login":
            data = self._body()
            sid = USERS.get((data.get("email"), data.get("pw")))
            if not sid:
                return self._json({"error": "falsch"}, 401)
            return self._json({"ok": True}, cookie=f"sid={sid}; Path=/; HttpOnly")
        if not self._logged_in():
            return self._json({"error": "kein Zugriff"}, 401)
        if path == "/api/conversations":
            cid = str(uuid.uuid4())
            with lock:
                known.add(cid)
            return self._json({"data": {"id": cid}}, 201)
        if path.startswith("/api/conversations/") and path.endswith("/messages"):
            cid = path.split("/")[3]
            with lock:
                ok = cid in known
            if not ok:
                return self._json({"error": "unbekannt"}, 404)
            self._body()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            time.sleep(0.1)
            for word in ("Ein", "Lasttest", "prüft", "die", "Belastbarkeit."):
                self.wfile.write(f"data: {word}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.02)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self.send_error(HTTPStatus.NOT_FOUND)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
