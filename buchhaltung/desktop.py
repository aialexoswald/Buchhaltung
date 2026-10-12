"""Start als Desktop-Programm (Mac-App): Server im Hintergrund, Oberfläche im Standardbrowser.

Wird die App ein zweites Mal geöffnet, während sie schon läuft, öffnet sich nur der
Browser erneut. Beendet wird sie über „Beenden“ in der Seitenleiste.
"""
import logging
import os
import socket
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

STANDARD_PORT = 8765
KENNUNG = b"buchhaltung"


def datenverzeichnis():
    if os.environ.get("BUCHHALTUNG_DATEN"):
        return Path(os.environ["BUCHHALTUNG_DATEN"])
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Buchhaltung"
    return Path.home() / "Buchhaltung-Daten"


def _laeuft_bereits(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/lebenszeichen", timeout=1) as antwort:
            return antwort.read() == KENNUNG
    except OSError:
        return False


def _port_frei(port):
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _meldung(text):
    """Fehlermeldung als Mac-Dialog anzeigen (ohne Terminal sieht man sonst nichts)."""
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", "on run argv", "-e",
                        'display alert "Buchhaltung" message (item 1 of argv) as critical',
                        "-e", "end run", text], check=False)
    else:
        print(text, file=sys.stderr)


def main():
    daten = datenverzeichnis()
    daten.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=daten / "buchhaltung.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    browser = not os.environ.get("BUCHHALTUNG_KEIN_BROWSER")
    port = int(os.environ.get("BUCHHALTUNG_PORT", STANDARD_PORT))

    if _laeuft_bereits(port):
        if browser:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return
    if not _port_frei(port):
        port = _freier_port()

    try:
        from werkzeug.serving import make_server

        from . import create_app

        os.environ["BUCHHALTUNG_DATEN"] = str(daten)
        app = create_app({"DESKTOP": True})
        server = make_server("127.0.0.1", port, app, threaded=True)
    except Exception as fehler:  # noqa: BLE001 – jede Startpanne dem Benutzer zeigen
        logging.exception("Start fehlgeschlagen")
        _meldung(f"Die Buchhaltung konnte nicht gestartet werden: {fehler}")
        sys.exit(1)

    def beenden():
        logging.info("Beendet über die Oberfläche")
        threading.Thread(target=server.shutdown, daemon=True).start()

    app.config["BEENDEN"] = beenden
    url = f"http://127.0.0.1:{port}/"
    logging.info("Gestartet auf %s, Daten in %s", url, daten)
    if browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
