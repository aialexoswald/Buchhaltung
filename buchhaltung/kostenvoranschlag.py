"""Kostenvoranschläge und anteilige Abrechnung (je Position 0–100 %)."""
from decimal import Decimal

from .geld import cent_zu_euro_text, datum_parsen, heute, runden
from .logik import FachFehler, ar_speichern


def kv_speichern(con, daten, positionen, kv_id=None):
    """Legt einen Kostenvoranschlag an oder ändert ihn. Gibt die ID zurück.

    Bestehende Positionen werden über ihre ID aktualisiert, damit die Verknüpfung zu
    bereits gestellten Rechnungen erhalten bleibt.
    """
    datum = datum_parsen(daten.get("datum"))
    if datum is None:
        raise FachFehler("Bitte ein Datum angeben.")
    if not positionen:
        raise FachFehler("Der Kostenvoranschlag braucht mindestens eine Position.")
    felder = (daten["kunde_id"], daten.get("bezeichnung", ""), datum.isoformat(), daten.get("notiz", ""))
    if kv_id is None:
        kv_id = con.execute(
            "INSERT INTO kostenvoranschlaege (kunde_id, bezeichnung, datum, notiz) VALUES (?, ?, ?, ?)", felder
        ).lastrowid
    else:
        con.execute("UPDATE kostenvoranschlaege SET kunde_id = ?, bezeichnung = ?, datum = ?, notiz = ? WHERE id = ?",
                    (*felder, kv_id))

    behalten = set()
    for i, p in enumerate(positionen, start=1):
        werte = (i, p.get("posnr", ""), p.get("beschreibung", ""), p["betrag_cent"], int(p.get("ust_satz", 20)))
        if p.get("id"):
            con.execute(
                "UPDATE kv_positionen SET reihenfolge = ?, posnr = ?, beschreibung = ?, betrag_cent = ?, ust_satz = ?"
                " WHERE id = ? AND kv_id = ?", (*werte, p["id"], kv_id))
            behalten.add(int(p["id"]))
        else:
            behalten.add(con.execute(
                "INSERT INTO kv_positionen (kv_id, reihenfolge, posnr, beschreibung, betrag_cent, ust_satz)"
                " VALUES (?, ?, ?, ?, ?, ?)", (kv_id, *werte)).lastrowid)
    for alt in con.execute("SELECT id FROM kv_positionen WHERE kv_id = ?", (kv_id,)).fetchall():
        if alt["id"] not in behalten:
            if _verrechnet(con, alt["id"]):
                raise FachFehler("Eine bereits (teilweise) verrechnete Position kann nicht gelöscht werden.")
            con.execute("DELETE FROM kv_positionen WHERE id = ?", (alt["id"],))
    return kv_id


def _verrechnet(con, position_id):
    z = con.execute("SELECT COALESCE(SUM(netto_cent), 0) AS s FROM ar_positionen WHERE kv_position_id = ?",
                    (position_id,)).fetchone()
    return z["s"]


def kv_laden(con, kv_id):
    """Kostenvoranschlag mit Positionen inkl. bereits verrechnetem Betrag und Prozentsatz."""
    kv = con.execute(
        """SELECT kv.*, k.name AS kunde_name FROM kostenvoranschlaege kv JOIN kunden k ON k.id = kv.kunde_id
           WHERE kv.id = ?""", (kv_id,)).fetchone()
    if kv is None:
        raise FachFehler("Kostenvoranschlag nicht gefunden.")
    positionen = []
    for p in con.execute(
        """SELECT p.*, COALESCE(SUM(a.netto_cent), 0) AS verrechnet_cent
           FROM kv_positionen p LEFT JOIN ar_positionen a ON a.kv_position_id = p.id
           WHERE p.kv_id = ? GROUP BY p.id ORDER BY p.reihenfolge""", (kv_id,)):
        p = dict(p)
        p["verrechnet_prozent"] = (float(Decimal(p["verrechnet_cent"]) * 100 / p["betrag_cent"])
                                   if p["betrag_cent"] else 0.0)
        p["rest_prozent"] = max(0.0, 100.0 - p["verrechnet_prozent"])
        positionen.append(p)
    return kv, positionen


def kv_rechnungen(con, kv_id):
    return con.execute(
        """SELECT DISTINCT ar.* FROM ausgangsrechnungen ar
           JOIN ar_positionen a ON a.rechnung_id = ar.id
           JOIN kv_positionen p ON p.id = a.kv_position_id
           WHERE p.kv_id = ? ORDER BY ar.datum, ar.nummer""", (kv_id,)).fetchall()


def kv_liste(con):
    return con.execute(
        """SELECT kv.*, k.name AS kunde_name,
                  (SELECT COALESCE(SUM(betrag_cent), 0) FROM kv_positionen WHERE kv_id = kv.id) AS summe_cent,
                  (SELECT COALESCE(SUM(a.netto_cent), 0) FROM ar_positionen a
                     JOIN kv_positionen p ON p.id = a.kv_position_id WHERE p.kv_id = kv.id) AS verrechnet_cent
           FROM kostenvoranschlaege kv JOIN kunden k ON k.id = kv.kunde_id
           ORDER BY kv.abgeschlossen, kv.datum DESC"""
    ).fetchall()


def _prozent_text(prozent):
    return f"{prozent:g}".replace(".", ",")


def rechnung_aus_kv(con, kv_id, prozente, daten):
    """Erstellt eine Ausgangsrechnung: je KV-Position `prozente[position_id]` Prozent.

    Positionen mit 0 % werden ausgelassen. Mehr als 100 % insgesamt sind nicht erlaubt.
    """
    kv, positionen = kv_laden(con, kv_id)
    rechnungspositionen = []
    for p in positionen:
        prozent = Decimal(str(prozente.get(p["id"], 0) or 0))
        if prozent == 0:
            continue
        if prozent < 0 or prozent > 100:
            raise FachFehler(f"Pos. {p['posnr']}: Prozentsatz muss zwischen 0 und 100 liegen.")
        if float(prozent) > p["rest_prozent"] + 0.001:
            raise FachFehler(
                f"Pos. {p['posnr']}: Es sind bereits {_prozent_text(round(p['verrechnet_prozent'], 2))} % verrechnet "
                f"– höchstens noch {_prozent_text(round(p['rest_prozent'], 2))} % möglich.")
        betrag = runden(Decimal(p["betrag_cent"]) * prozent / 100)
        text = " ".join(t for t in (f"Pos. {p['posnr']}" if p["posnr"] else "", p["beschreibung"]) if t)
        if prozent != 100:
            text += f"\n{_prozent_text(float(prozent))}% von EUR {cent_zu_euro_text(p['betrag_cent'], mit_waehrung=False)}"
        rechnungspositionen.append({
            "beschreibung": text, "menge": 1, "einheit": "", "einzelpreis_cent": betrag,
            "ust_satz": p["ust_satz"], "kv_position_id": p["id"],
        })
    if not rechnungspositionen:
        raise FachFehler("Bitte bei mindestens einer Position einen Prozentsatz über 0 eingeben.")
    return ar_speichern(con, {
        "datum": datum_parsen(daten.get("datum")) or heute(),
        "kunde_id": kv["kunde_id"],
        "betreff": daten.get("betreff") or kv["bezeichnung"],
        "projekt": daten.get("projekt", ""),
        "leistungszeitraum": daten.get("leistungszeitraum", ""),
    }, rechnungspositionen)
