"""SQLite-Zugriff."""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")

STANDARD_EINSTELLUNGEN = {
    "firma_name": "Futura GmbH",
    "firma_adresse": "Mariahilferstrasse 54/15\nA1070 Wien",
    "firma_zweigstelle": "Am Forst 21, 3011 Irenental",
    "firma_uid": "ATU67150012",
    "firma_firmenbuch": "378180y",
    "firma_wko": "0821830",
    "firma_email": "",
    "firma_telefon": "",
    "firma_web": "",
    "bank_name": "Raiffeisenbank Wienerwald",
    "bank_iban": "AT51 3266 7000 0007 5952",
    "bank_bic": "RLNWATWWPRB",
    "zahlungsziel_tage": "14",
    "rechnung_einleitung": "",
    "rechnung_zahlungstext": "Zahlbar prompt nach Rechnungserhalt.",
    "rechnung_fusstext": "",
}

# Frühere Standardtexte, die beim Update durch die neuen ersetzt werden (nur wenn unverändert)
ALTE_STANDARDS = {
    "rechnung_einleitung": {"Wir erlauben uns, für unsere Leistungen wie folgt in Rechnung zu stellen:"},
    "rechnung_fusstext": {"Vielen Dank für die gute Zusammenarbeit!"},
}


def verbinden(pfad):
    con = sqlite3.connect(pfad, detect_types=0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def initialisieren(con):
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    _migrieren(con)
    vorhanden = einstellungen(con)
    for schluessel, wert in STANDARD_EINSTELLUNGEN.items():
        if schluessel not in vorhanden:
            con.execute("INSERT INTO einstellungen (schluessel, wert) VALUES (?, ?)", (schluessel, wert))
        elif vorhanden[schluessel] in ALTE_STANDARDS.get(schluessel, ()) or (
            not vorhanden[schluessel] and wert and not vorhanden.get("_firmendaten_uebernommen")
        ):
            con.execute("UPDATE einstellungen SET wert = ? WHERE schluessel = ?", (wert, schluessel))
    # leere Firmendaten nur einmal vorbelegen – später absichtlich geleerte Felder bleiben leer
    con.execute("INSERT OR IGNORE INTO einstellungen (schluessel, wert) VALUES ('_firmendaten_uebernommen', '1')")
    con.commit()


def _migrieren(con):
    """Spalten nachrüsten, die in älteren Datenbanken fehlen."""
    spalten = {r["name"] for r in con.execute("PRAGMA table_info(ausgangsrechnungen)")}
    if "betreff" not in spalten:
        con.execute("ALTER TABLE ausgangsrechnungen ADD COLUMN betreff TEXT NOT NULL DEFAULT ''")
    spalten = {r["name"] for r in con.execute("PRAGMA table_info(ar_positionen)")}
    if "kv_position_id" not in spalten:
        con.execute("ALTER TABLE ar_positionen ADD COLUMN kv_position_id INTEGER "
                    "REFERENCES kv_positionen (id) ON DELETE SET NULL")


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
