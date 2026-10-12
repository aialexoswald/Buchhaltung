"""SQLite-Zugriff."""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")

STANDARD_EINSTELLUNGEN = {
    "firma_name": "Futura GmbH",
    "firma_adresse": "",
    "firma_uid": "",
    "firma_firmenbuch": "",
    "firma_email": "",
    "firma_telefon": "",
    "firma_web": "",
    "bank_name": "",
    "bank_iban": "",
    "bank_bic": "",
    "zahlungsziel_tage": "14",
    "rechnung_einleitung": "Wir erlauben uns, für unsere Leistungen wie folgt in Rechnung zu stellen:",
    "rechnung_fusstext": "Vielen Dank für die gute Zusammenarbeit!",
}


def verbinden(pfad):
    con = sqlite3.connect(pfad, detect_types=0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def initialisieren(con):
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    for schluessel, wert in STANDARD_EINSTELLUNGEN.items():
        con.execute(
            "INSERT OR IGNORE INTO einstellungen (schluessel, wert) VALUES (?, ?)",
            (schluessel, wert),
        )
    con.commit()


def get_db():
    if "db" not in g:
        g.db = verbinden(current_app.config["DATENBANK"])
    return g.db


def schliessen(_exc=None):
    con = g.pop("db", None)
    if con is not None:
        con.close()


def einstellungen(con):
    return {r["schluessel"]: r["wert"] for r in con.execute("SELECT * FROM einstellungen")}
