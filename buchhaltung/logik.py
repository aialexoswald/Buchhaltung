"""Fachlogik für Ausgangs- und Eingangsrechnungen (unabhängig von Flask)."""
from collections import defaultdict
from decimal import Decimal

from .db import einstellungen
from .geld import datum_parsen, heute, netto_von_brutto, plus_tage, runden, ust_von_netto


class FachFehler(ValueError):
    """Fehler, der dem Benutzer angezeigt werden kann."""


# --------------------------------------------------------------------------- Kunden

def kunde_finden_oder_anlegen(con, name):
    name = " ".join((name or "").split())
    if not name:
        raise FachFehler("Bitte einen Kunden angeben.")
    zeile = con.execute("SELECT id FROM kunden WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
    if zeile:
        return zeile["id"]
    return con.execute("INSERT INTO kunden (name) VALUES (?)", (name,)).lastrowid


def kunden_zusammenfuehren(con, von_id, nach_id):
    """Verschiebt alle Rechnungen von Kunde `von_id` zu `nach_id` und löscht `von_id`."""
    if von_id == nach_id:
        raise FachFehler("Ein Kunde kann nicht mit sich selbst zusammengeführt werden.")
    con.execute("UPDATE ausgangsrechnungen SET kunde_id = ? WHERE kunde_id = ?", (nach_id, von_id))
    con.execute("UPDATE eingangsrechnungen SET weiter_kunde_id = ? WHERE weiter_kunde_id = ?", (nach_id, von_id))
    con.execute("DELETE FROM kunden WHERE id = ?", (von_id,))


# ------------------------------------------------------------- Ausgangsrechnungen

def naechste_nummer(con, jahr):
    zeilen = con.execute(
        "SELECT nummer FROM ausgangsrechnungen WHERE nummer LIKE ? ESCAPE '\\'", (f"{jahr}\\_%",)
    ).fetchall()
    hoechste = 0
    for z in zeilen:
        teil = z["nummer"].split("_", 1)[1]
        if teil.isdigit():
            hoechste = max(hoechste, int(teil))
    return f"{jahr}_{hoechste + 1:03d}"


def positionen_berechnen(positionen):
    """Berechnet Netto je Position sowie Summen je Steuersatz.

    Liefert (positionen_mit_netto, {satz: netto}, netto, ust, brutto).
    Die USt wird je Steuersatz auf die Summe gerechnet (nicht je Position).
    """
    ergebnis = []
    je_satz = defaultdict(int)
    for p in positionen:
        menge = Decimal(str(p.get("menge", 1) or 0))
        netto = runden(menge * p["einzelpreis_cent"])
        satz = int(p.get("ust_satz", 20))
        ergebnis.append({**p, "menge": float(menge), "ust_satz": satz, "netto_cent": netto})
        je_satz[satz] += netto
    netto = sum(je_satz.values())
    ust = sum(ust_von_netto(n, s) for s, n in je_satz.items())
    return ergebnis, dict(je_satz), netto, ust, netto + ust


def _zahlungsziel(con, kunde_id):
    k = con.execute("SELECT zahlungsziel_tage FROM kunden WHERE id = ?", (kunde_id,)).fetchone()
    if k and k["zahlungsziel_tage"] is not None:
        return k["zahlungsziel_tage"]
    return int(einstellungen(con).get("zahlungsziel_tage") or 14)


def ar_speichern(con, daten, positionen, rechnung_id=None, nummer=None):
    """Legt eine Ausgangsrechnung an oder ändert sie. Gibt die ID zurück."""
    if not positionen:
        raise FachFehler("Die Rechnung braucht mindestens eine Position.")
    datum = datum_parsen(daten["datum"])
    if datum is None:
        raise FachFehler("Bitte ein Rechnungsdatum angeben.")
    kunde_id = daten["kunde_id"]
    faellig = daten.get("faellig_am") or plus_tage(datum.isoformat(), _zahlungsziel(con, kunde_id))
    pos, _, netto, ust, brutto = positionen_berechnen(positionen)

    felder = {
        "datum": datum.isoformat(),
        "kunde_id": kunde_id,
        "projekt": daten.get("projekt", ""),
        "betreff": daten.get("betreff", ""),
        "leistungszeitraum": daten.get("leistungszeitraum", ""),
        "steuerhinweis": daten.get("steuerhinweis", ""),
        "notiz": daten.get("notiz", ""),
        "faellig_am": datum_parsen(faellig).isoformat(),
        "netto_cent": netto,
        "ust_cent": ust,
        "brutto_cent": brutto,
    }
    for extra in ("bezahlt", "bezahlt_am", "importiert", "storno_von_id"):
        if extra in daten:
            felder[extra] = daten[extra]

    if rechnung_id is None:
        felder["nummer"] = nummer or naechste_nummer(con, datum.year)
        if con.execute("SELECT 1 FROM ausgangsrechnungen WHERE nummer = ?", (felder["nummer"],)).fetchone():
            raise FachFehler(f"Die Rechnungsnummer {felder['nummer']} ist bereits vergeben.")
        spalten = ", ".join(felder)
        rechnung_id = con.execute(
            f"INSERT INTO ausgangsrechnungen ({spalten}) VALUES ({', '.join('?' * len(felder))})",
            tuple(felder.values()),
        ).lastrowid
    else:
        zuweisung = ", ".join(f"{k} = ?" for k in felder)
        con.execute(
            f"UPDATE ausgangsrechnungen SET {zuweisung} WHERE id = ?", (*felder.values(), rechnung_id)
        )
        con.execute("DELETE FROM ar_positionen WHERE rechnung_id = ?", (rechnung_id,))

    for i, p in enumerate(pos, start=1):
        con.execute(
            """INSERT INTO ar_positionen
               (rechnung_id, pos, beschreibung, menge, einheit, einzelpreis_cent, ust_satz, netto_cent,
                kv_position_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rechnung_id, i, p.get("beschreibung", ""), p["menge"], p.get("einheit", ""),
             p["einzelpreis_cent"], p["ust_satz"], p["netto_cent"], p.get("kv_position_id")),
        )
    return rechnung_id


def ar_laden(con, rechnung_id):
    r = con.execute(
        """SELECT ar.*, k.name AS kunde_name, k.adresse AS kunde_adresse, k.uid AS kunde_uid,
                  s.nummer AS storno_von_nummer,
                  (SELECT nummer FROM ausgangsrechnungen x WHERE x.storno_von_id = ar.id) AS storno_nummer
           FROM ausgangsrechnungen ar
           JOIN kunden k ON k.id = ar.kunde_id
           LEFT JOIN ausgangsrechnungen s ON s.id = ar.storno_von_id
           WHERE ar.id = ?""",
        (rechnung_id,),
    ).fetchone()
    if r is None:
        raise FachFehler("Rechnung nicht gefunden.")
    pos = con.execute(
        "SELECT * FROM ar_positionen WHERE rechnung_id = ? ORDER BY pos", (rechnung_id,)
    ).fetchall()
    return r, pos


def ar_steuersaetze(positionen):
    """{satz: (netto, ust)} für die Rechnungsanzeige."""
    je_satz = defaultdict(int)
    for p in positionen:
        je_satz[p["ust_satz"]] += p["netto_cent"]
    return {s: (n, ust_von_netto(n, s)) for s, n in sorted(je_satz.items(), reverse=True)}


def ar_bezahlt_setzen(con, rechnung_id, bezahlt_am):
    """bezahlt_am=None markiert die Rechnung wieder als offen."""
    if bezahlt_am:
        con.execute(
            "UPDATE ausgangsrechnungen SET bezahlt = 1, bezahlt_am = ? WHERE id = ?",
            (datum_parsen(bezahlt_am).isoformat(), rechnung_id),
        )
    else:
        con.execute(
            "UPDATE ausgangsrechnungen SET bezahlt = 0, bezahlt_am = NULL WHERE id = ?", (rechnung_id,)
        )


def ar_stornieren(con, rechnung_id, datum=None):
    """Erstellt eine Stornorechnung mit negativen Beträgen. Gibt deren ID zurück."""
    r, pos = ar_laden(con, rechnung_id)
    if r["storniert"]:
        raise FachFehler(f"Rechnung {r['nummer']} ist bereits storniert.")
    if r["storno_von_id"]:
        raise FachFehler("Eine Stornorechnung kann nicht storniert werden.")
    datum = datum_parsen(datum) or heute()
    neue_id = ar_speichern(
        con,
        {
            "datum": datum,
            "kunde_id": r["kunde_id"],
            "projekt": r["projekt"],
            "betreff": r["betreff"],
            "leistungszeitraum": r["leistungszeitraum"],
            "steuerhinweis": r["steuerhinweis"],
            "notiz": f"Storno zu Rechnung {r['nummer']} vom {datum_parsen(r['datum']).strftime('%d.%m.%Y')}",
            "faellig_am": datum.isoformat(),
            "storno_von_id": r["id"],
            "bezahlt": 1,
            "bezahlt_am": datum.isoformat(),
        },
        [
            {
                "beschreibung": p["beschreibung"],
                "kv_position_id": p["kv_position_id"],
                "menge": -p["menge"],
                "einheit": p["einheit"],
                "einzelpreis_cent": p["einzelpreis_cent"],
                "ust_satz": p["ust_satz"],
            }
            for p in pos
        ],
    )
    con.execute("UPDATE ausgangsrechnungen SET storniert = 1 WHERE id = ?", (rechnung_id,))
    con.execute(
        "UPDATE eingangsrechnungen SET weiter_ar_id = NULL, weiter_erledigt = 0 WHERE weiter_ar_id = ?",
        (rechnung_id,),
    )
    return neue_id


def ar_loeschen(con, rechnung_id):
    """Nur die letzte Rechnung eines Jahres darf gelöscht werden (lückenlose Nummern)."""
    r, _ = ar_laden(con, rechnung_id)
    jahr = r["nummer"].split("_", 1)[0]
    if naechste_nummer(con, jahr) != _folgenummer(r["nummer"]):
        raise FachFehler(
            "Nur die zuletzt erstellte Rechnung darf gelöscht werden, damit die Nummern "
            "lückenlos bleiben. Bitte stattdessen stornieren."
        )
    if r["storno_von_id"]:
        con.execute("UPDATE ausgangsrechnungen SET storniert = 0 WHERE id = ?", (r["storno_von_id"],))
    con.execute(
        "UPDATE eingangsrechnungen SET weiter_ar_id = NULL, weiter_erledigt = 0 WHERE weiter_ar_id = ?",
        (rechnung_id,),
    )
    con.execute("DELETE FROM ausgangsrechnungen WHERE id = ?", (rechnung_id,))


def _folgenummer(nummer):
    jahr, teil = nummer.split("_", 1)
    return f"{jahr}_{int(teil) + 1:03d}" if teil.isdigit() else None


# -------------------------------------------------------------- Eingangsrechnungen

def er_berechnen(brutto_cent, ust_satz, reverse_charge=False, vorsteuer_manuell_cent=None):
    """Liefert (netto, vorsteuer).

    Reverse Charge: Die Rechnung enthält keine USt; Netto = Rechnungsbetrag,
    die Vorsteuer entspricht der selbst geschuldeten USt.
    """
    if reverse_charge:
        return brutto_cent, ust_von_netto(brutto_cent, ust_satz)
    if vorsteuer_manuell_cent is not None:
        return brutto_cent - vorsteuer_manuell_cent, vorsteuer_manuell_cent
    netto = netto_von_brutto(brutto_cent, ust_satz)
    return netto, brutto_cent - netto


def naechste_enr(con, jahr):
    z = con.execute("SELECT MAX(enr) AS m FROM eingangsrechnungen WHERE jahr = ?", (jahr,)).fetchone()
    return (z["m"] or 0) + 1


def er_speichern(con, daten, er_id=None):
    datum = datum_parsen(daten["datum"])
    if datum is None:
        raise FachFehler("Bitte ein Rechnungsdatum angeben.")
    if daten.get("brutto_cent") is None:
        raise FachFehler("Bitte einen Betrag angeben.")
    satz = int(daten.get("ust_satz", 20))
    rc = bool(daten.get("reverse_charge"))
    if rc and satz == 0:
        satz = 20
    netto, vst = er_berechnen(daten["brutto_cent"], satz, rc, daten.get("vorsteuer_manuell_cent"))
    felder = {
        "datum": datum.isoformat(),
        "jahr": datum.year,
        "lieferant": daten.get("lieferant", ""),
        "rechnungsnr_lieferant": daten.get("rechnungsnr_lieferant", ""),
        "text": daten.get("text", ""),
        "kostenart": daten.get("kostenart", ""),
        "brutto_cent": daten["brutto_cent"],
        "ust_satz": satz,
        "reverse_charge": int(rc),
        "vorsteuer_manuell_cent": None if rc else daten.get("vorsteuer_manuell_cent"),
        "netto_cent": netto,
        "vorsteuer_cent": vst,
        "bezahlt": int(bool(daten.get("bezahlt"))),
        "bezahlt_am": daten.get("bezahlt_am") or None,
        "weiter_kunde_id": daten.get("weiter_kunde_id"),
        "weiter_erledigt": int(bool(daten.get("weiter_erledigt"))) if daten.get("weiter_kunde_id") else 0,
        "notiz": daten.get("notiz", ""),
    }
    for extra in ("datum_geschaetzt", "importiert", "beleg_datei", "weiter_ar_id"):
        if extra in daten:
            felder[extra] = daten[extra]

    if er_id is None:
        felder["enr"] = daten.get("enr") or naechste_enr(con, datum.year)
        spalten = ", ".join(felder)
        return con.execute(
            f"INSERT INTO eingangsrechnungen ({spalten}) VALUES ({', '.join('?' * len(felder))})",
            tuple(felder.values()),
        ).lastrowid
    alt = con.execute("SELECT jahr FROM eingangsrechnungen WHERE id = ?", (er_id,)).fetchone()
    if alt and alt["jahr"] != datum.year:
        felder["enr"] = naechste_enr(con, datum.year)
    zuweisung = ", ".join(f"{k} = ?" for k in felder)
    con.execute(f"UPDATE eingangsrechnungen SET {zuweisung} WHERE id = ?", (*felder.values(), er_id))
    return er_id


def fremdkosten_verrechnen(con, er_ids, datum=None, aufschlag_prozent=0):
    """Erstellt aus offenen Fremdkosten (gleicher Kunde) eine neue Ausgangsrechnung."""
    if not er_ids:
        raise FachFehler("Bitte mindestens eine Eingangsrechnung auswählen.")
    marker = ", ".join("?" * len(er_ids))
    zeilen = con.execute(
        f"""SELECT * FROM eingangsrechnungen WHERE id IN ({marker})
            AND weiter_kunde_id IS NOT NULL AND weiter_erledigt = 0 ORDER BY datum""",
        tuple(er_ids),
    ).fetchall()
    if len(zeilen) != len(set(er_ids)):
        raise FachFehler("Einige der gewählten Belege sind nicht (mehr) offen zur Weiterverrechnung.")
    kunden = {z["weiter_kunde_id"] for z in zeilen}
    if len(kunden) != 1:
        raise FachFehler("Bitte nur Fremdkosten eines einzigen Kunden gemeinsam verrechnen.")
    faktor = Decimal(100 + aufschlag_prozent) / 100
    positionen = []
    for z in zeilen:
        text = " – ".join(t for t in (z["lieferant"], z["text"]) if t) or "Fremdkosten"
        positionen.append({
            "beschreibung": text,
            "menge": 1,
            "einheit": "pausch.",
            "einzelpreis_cent": runden(z["netto_cent"] * faktor),
            "ust_satz": 20,
        })
    ar_id = ar_speichern(
        con,
        {"datum": datum_parsen(datum) or heute(), "kunde_id": kunden.pop(), "projekt": "Weiterverrechnung Fremdkosten"},
        positionen,
    )
    con.execute(
        f"UPDATE eingangsrechnungen SET weiter_erledigt = 1, weiter_ar_id = ? WHERE id IN ({marker})",
        (ar_id, *er_ids),
    )
    return ar_id
