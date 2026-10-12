"""Auswertungen: UVA, Umsatz, offene Posten, Plausibilitätsprüfungen."""
from calendar import monthrange
from collections import defaultdict
from datetime import date

from .geld import MONATE, datum_parsen, heute, ust_von_netto


def zeitraum(jahr, art, nummer):
    """art = 'monat' | 'quartal' | 'jahr' → (von, bis, bezeichnung) als ISO-Daten."""
    if art == "monat":
        von_m = bis_m = nummer
        name = f"{MONATE[nummer - 1]} {jahr}"
    elif art == "quartal":
        von_m, bis_m = 3 * nummer - 2, 3 * nummer
        name = f"{nummer}. Quartal {jahr}"
    else:
        von_m, bis_m = 1, 12
        name = f"Jahr {jahr}"
    von = date(jahr, von_m, 1)
    bis = date(jahr, bis_m, monthrange(jahr, bis_m)[1])
    return von.isoformat(), bis.isoformat(), name


def uva(con, von, bis):
    """Umsatzsteuer-Voranmeldung (Sollbesteuerung, nach Rechnungsdatum)."""
    umsaetze = defaultdict(int)
    for z in con.execute(
        """SELECT p.ust_satz, SUM(p.netto_cent) AS netto
           FROM ar_positionen p JOIN ausgangsrechnungen ar ON ar.id = p.rechnung_id
           WHERE ar.datum BETWEEN ? AND ? GROUP BY p.ust_satz""",
        (von, bis),
    ):
        umsaetze[z["ust_satz"]] += z["netto"]

    zeilen_ust = []
    ust_summe = 0
    for satz in (20, 13, 10):
        bmg = umsaetze.get(satz, 0)
        ust = ust_von_netto(bmg, satz)
        ust_summe += ust
        zeilen_ust.append({"satz": satz, "bemessung": bmg, "ust": ust})
    steuerfrei = sum(n for s, n in umsaetze.items() if s not in (20, 13, 10))

    er = con.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN reverse_charge = 0 THEN vorsteuer_cent END), 0) AS vst,
             COALESCE(SUM(CASE WHEN reverse_charge = 1 THEN netto_cent END), 0) AS rc_bmg,
             COALESCE(SUM(CASE WHEN reverse_charge = 1 THEN vorsteuer_cent END), 0) AS rc_ust
           FROM eingangsrechnungen WHERE datum BETWEEN ? AND ?""",
        (von, bis),
    ).fetchone()

    ust_gesamt = ust_summe + er["rc_ust"]
    vst_gesamt = er["vst"] + er["rc_ust"]
    return {
        "umsaetze": zeilen_ust,
        "umsatz_gesamt": sum(umsaetze.values()),
        "steuerfrei": steuerfrei,
        "ust": ust_summe,
        "vorsteuer": er["vst"],
        "rc_bemessung": er["rc_bmg"],
        "rc_ust": er["rc_ust"],
        "ust_gesamt": ust_gesamt,
        "vorsteuer_gesamt": vst_gesamt,
        "zahllast": ust_gesamt - vst_gesamt,
    }


def verfuegbare_jahre(con):
    jahre = {
        int(z["j"])
        for z in con.execute(
            "SELECT DISTINCT substr(datum, 1, 4) AS j FROM ausgangsrechnungen "
            "UNION SELECT DISTINCT CAST(jahr AS TEXT) FROM eingangsrechnungen"
        )
    }
    jahre.add(heute().year)
    return sorted(jahre, reverse=True)


def umsatz_je_monat(con, jahre):
    """{jahr: [netto Jänner … Dezember]} – Stornos sind als negative Beträge enthalten."""
    ergebnis = {j: [0] * 12 for j in jahre}
    for z in con.execute(
        """SELECT CAST(substr(datum, 1, 4) AS INTEGER) AS j, CAST(substr(datum, 6, 2) AS INTEGER) AS m,
                  SUM(netto_cent) AS netto
           FROM ausgangsrechnungen GROUP BY j, m"""
    ):
        if z["j"] in ergebnis:
            ergebnis[z["j"]][z["m"] - 1] = z["netto"]
    return ergebnis


def kosten_je_monat(con, jahr):
    werte = [0] * 12
    for z in con.execute(
        """SELECT CAST(substr(datum, 6, 2) AS INTEGER) AS m, SUM(netto_cent) AS netto
           FROM eingangsrechnungen WHERE jahr = ? GROUP BY m""",
        (jahr,),
    ):
        werte[z["m"] - 1] = z["netto"]
    return werte


def umsatz_je_kunde(con, jahr):
    return con.execute(
        """SELECT k.id, k.name, COUNT(*) AS anzahl, SUM(ar.netto_cent) AS netto,
                  SUM(CASE WHEN ar.bezahlt = 0 AND ar.storniert = 0 AND ar.storno_von_id IS NULL
                           THEN ar.brutto_cent ELSE 0 END) AS offen
           FROM ausgangsrechnungen ar JOIN kunden k ON k.id = ar.kunde_id
           WHERE substr(ar.datum, 1, 4) = ?
           GROUP BY k.id ORDER BY netto DESC""",
        (str(jahr),),
    ).fetchall()


def umsatz_je_projekt(con, jahr):
    return con.execute(
        """SELECT ar.projekt, COUNT(*) AS anzahl, SUM(ar.netto_cent) AS netto
           FROM ausgangsrechnungen ar
           WHERE substr(ar.datum, 1, 4) = ? AND ar.projekt != ''
           GROUP BY ar.projekt ORDER BY netto DESC""",
        (str(jahr),),
    ).fetchall()


def fremdkosten_je_monat(con, jahr):
    """Fremdkosten (netto) je Monat: weiterverrechnet vs. intern (nicht verrechenbar)."""
    weiter, intern = [0] * 12, [0] * 12
    for z in con.execute(
        """SELECT CAST(substr(datum, 6, 2) AS INTEGER) AS m,
                  SUM(CASE WHEN weiter_kunde_id IS NOT NULL THEN netto_cent ELSE 0 END) AS weiter,
                  SUM(CASE WHEN weiter_kunde_id IS NULL THEN netto_cent ELSE 0 END) AS intern
           FROM eingangsrechnungen WHERE jahr = ? GROUP BY m""",
        (jahr,),
    ):
        weiter[z["m"] - 1] = z["weiter"]
        intern[z["m"] - 1] = z["intern"]
    return weiter, intern


# ------------------------------------------------------------------ offene Posten

def offene_forderungen(con, stichtag=None):
    stichtag = stichtag or heute()
    zeilen = con.execute(
        """SELECT ar.*, k.name AS kunde_name FROM ausgangsrechnungen ar
           JOIN kunden k ON k.id = ar.kunde_id
           WHERE ar.bezahlt = 0 AND ar.storniert = 0 AND ar.storno_von_id IS NULL
           ORDER BY ar.faellig_am, ar.nummer"""
    ).fetchall()
    ergebnis = []
    for z in zeilen:
        faellig = datum_parsen(z["faellig_am"] or z["datum"])
        ergebnis.append({**dict(z), "tage_ueberfaellig": (stichtag - faellig).days})
    return ergebnis


def offene_verbindlichkeiten(con):
    return con.execute(
        "SELECT * FROM eingangsrechnungen WHERE bezahlt = 0 ORDER BY datum"
    ).fetchall()


def offene_fremdkosten(con):
    return con.execute(
        """SELECT er.*, k.name AS kunde_name FROM eingangsrechnungen er
           JOIN kunden k ON k.id = er.weiter_kunde_id
           WHERE er.weiter_erledigt = 0 ORDER BY k.name, er.datum"""
    ).fetchall()


# ----------------------------------------------------------- Plausibilitätsprüfung

def hinweise(con):
    """Findet typische Erfassungsfehler: Liste von (text, (endpoint, url-parameter))."""
    liste = []
    for z in con.execute(
        "SELECT id, nummer, datum FROM ausgangsrechnungen WHERE substr(nummer, 1, 4) != substr(datum, 1, 4)"
    ):
        liste.append((f"Ausgangsrechnung {z['nummer']}: Rechnungsdatum {z['datum'][:4]} passt nicht zur Nummer.",
                      ("ausgang.detail", {"rechnung_id": z["id"]})))
    for z in con.execute(
        "SELECT id, nummer FROM ausgangsrechnungen WHERE netto_cent = 0 AND datum >= ?", (f"{heute().year - 1}-01-01",)
    ):
        liste.append((f"Ausgangsrechnung {z['nummer']}: Betrag ist 0.", ("ausgang.detail", {"rechnung_id": z["id"]})))
    ohne = con.execute(
        "SELECT id, jahr, enr FROM eingangsrechnungen WHERE lieferant = '' AND jahr >= ? ORDER BY datum",
        (heute().year - 1,),
    ).fetchall()
    if len(ohne) == 1:
        liste.append((f"Eingangsrechnung {ohne[0]['jahr']}/{ohne[0]['enr'] or '–'}: Lieferant fehlt.",
                      ("eingang.bearbeiten", {"er_id": ohne[0]["id"]})))
    elif ohne:
        liste.append((f"{len(ohne)} Eingangsrechnungen ohne Lieferant (z. B. ENR {ohne[0]['jahr']}/{ohne[0]['enr']}).",
                      ("eingang.bearbeiten", {"er_id": ohne[0]["id"]})))
    anzahl = con.execute(
        "SELECT COUNT(*) AS n FROM eingangsrechnungen WHERE datum_geschaetzt = 1 AND jahr >= ?",
        (heute().year,),
    ).fetchone()["n"]
    if anzahl:
        liste.append((f"{anzahl} Eingangsrechnungen aus dem Excel-Import haben nur ein geschätztes Datum "
                      "(Monat bekannt, Tag unbekannt).", ("eingang.liste", {"jahr": heute().year})))
    return liste
