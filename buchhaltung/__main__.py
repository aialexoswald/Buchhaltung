"""Start: `python -m buchhaltung` (Web-App) oder `python -m buchhaltung import DATEI.xlsx`."""
import argparse
import webbrowser

from . import create_app
from .db import verbinden
from .importer import importieren


def main():
    parser = argparse.ArgumentParser(prog="buchhaltung")
    unter = parser.add_subparsers(dest="befehl")
    start = unter.add_parser("start", help="Web-App starten (Standard)")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=5000)
    start.add_argument("--kein-browser", action="store_true")
    imp = unter.add_parser("import", help="Bisherige Excel-Datei übernehmen")
    imp.add_argument("datei")
    imp.add_argument("--offen-wert", type=int, default=1,
                     help="Wert in der Spalte 'bezahlt', der eine OFFENE Rechnung bedeutet (Standard: 1)")
    args = parser.parse_args()

    app = create_app()
    if args.befehl == "import":
        con = verbinden(app.config["DATENBANK"])
        print(importieren(con, args.datei, offen_wert=args.offen_wert))
        con.close()
        return

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 5000)
    if not getattr(args, "kein_browser", False):
        webbrowser.open(f"http://{host}:{port}/")
    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
