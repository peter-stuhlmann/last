"""Das Python-Backend als eigenständiges Programm für die Desktop-App – ohne Docker, ohne installiertes Python.

Ergebnis (im Ordner desktop/build):
  backend/last-backend[.exe]   das Backend mit allen Paketen (PyInstaller, Ordner-Variante: startet schneller)
  browsers/                    Chromium für Abläufe (Playwright, nur die Headless-Variante)

Läuft auf macOS, Windows und Linux – jeweils für das eigene System (PyInstaller kann nicht über Kreuz bauen).
Aufruf mit Python 3.12 aus dem Projektordner:   python desktop/scripts/build_backend.py
"""
import os
import shutil
import subprocess
import sys
import venv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = os.path.join(ROOT, "desktop", "build")
VENV = os.path.join(BUILD, "venv")
WIN = sys.platform == "win32"

# Was das Backend zur Laufzeit lädt – auch, was nur in Funktionen importiert wird
MODULES = ["stresstest_web", "llm_stresstest", "web_stresstest", "flow_stresstest", "flow_recorder", "flow_live",
           "report_web", "report_pptx", "report_pdf", "report_compare"]
DATA = ["VERSION", "stresstest_ui.html", "LIESMICH.md"]


def run(*cmd, **kw):
    print("→", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def main():
    if sys.version_info[:2] != (3, 12):
        sys.exit(f"Bitte mit Python 3.12 bauen (wie im Docker-Image), nicht {sys.version.split()[0]}.")
    os.makedirs(BUILD, exist_ok=True)
    if not os.path.isdir(VENV):
        venv.create(VENV, with_pip=True)
    py = os.path.join(VENV, "Scripts" if WIN else "bin", "python.exe" if WIN else "python")
    run(py, "-m", "pip", "install", "--quiet", "--upgrade", "pip")
    run(py, "-m", "pip", "install", "--quiet", "-r", "requirements-browser.txt", "pyinstaller==6.16.0")

    # Chromium für Abläufe – nur die Headless-Variante, die Playwright im unsichtbaren Betrieb nimmt
    browsers = os.path.join(BUILD, "browsers")
    run(py, "-m", "playwright", "install", "--only-shell", "chromium",
        env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": browsers})

    for old in ("backend", "pyinstaller"):
        shutil.rmtree(os.path.join(BUILD, old), ignore_errors=True)
    args = [py, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--name", "last-backend",
            "--distpath", os.path.join(BUILD, "backend-dist"), "--workpath", os.path.join(BUILD, "pyinstaller"),
            "--specpath", os.path.join(BUILD, "pyinstaller"), "--collect-all", "playwright"]
    for m in MODULES:
        args += ["--hidden-import", m]
    for d in DATA:
        args += ["--add-data", f"{os.path.join(ROOT, d)}{os.pathsep}."]
    run(*args, os.path.join(ROOT, "stresstest_web.py"))
    shutil.move(os.path.join(BUILD, "backend-dist", "last-backend"), os.path.join(BUILD, "backend"))
    shutil.rmtree(os.path.join(BUILD, "backend-dist"), ignore_errors=True)
    print(f"\nFertig: {os.path.join(BUILD, 'backend')}  ·  Chromium: {browsers}")


if __name__ == "__main__":
    main()
