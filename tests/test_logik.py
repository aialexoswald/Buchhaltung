import pytest

from buchhaltung.auswertung import offene_forderungen, uva
from buchhaltung.logik import (FachFehler, ar_laden, ar_loeschen, ar_speichern, ar_stornieren, er_berechnen,
                               er_speichern, fremdkosten_verrechnen, kunde_finden_oder_anlegen, kunden_zusammenfuehren,
                               naechste_nummer)


def rechnung(con, datum="2026-10-01", kunde="ETC", positionen=None):
    return ar_speichern(con, {"datum": datum, "kunde_id": kunde_finden_oder_anlegen(con, kunde)},
                        positionen or [{"beschreibung": "Beratung", "menge": 2, "einzelpreis_cent": 10000, "ust_satz": 20}])


def test_fortlaufende_nummern_je_jahr(con):
    a = rechnung(con)
    b = rechnung(con)
    c = rechnung(con, datum="2027-01-02")
    nummern = [ar_laden(con, i)[0]["nummer"] for i in (a, b, c)]
    assert nummern == ["2026_001", "2026_002", "2027_001"]
    assert naechste_nummer(con, 2026) == "2026_003"


def test_summen_und_gemischte_steuersaetze(con):
    rid = rechnung(con, positionen=[
        {"beschreibung": "Honorar", "menge": 1.5, "einzelpreis_cent": 10000, "ust_satz": 20},
        {"beschreibung": "Bahnticket", "menge": 1, "einzelpreis_cent": 4889, "ust_satz": 0},
    ])
    r, pos = ar_laden(con, rid)
    assert (r["netto_cent"], r["ust_cent"], r["brutto_cent"]) == (19889, 3000, 22889)
    assert [p["netto_cent"] for p in pos] == [15000, 4889]


def test_faelligkeit_aus_zahlungsziel(con):
    r, _ = ar_laden(con, rechnung(con, datum="2026-10-01"))
    assert r["faellig_am"] == "2026-10-15"


def test_kunde_gross_klein_und_leerzeichen(con):
    assert kunde_finden_oder_anlegen(con, "ETC ") == kunde_finden_oder_anlegen(con, "etc")


def test_storno(con):
    rid = rechnung(con)
    sid = ar_stornieren(con, rid, "2026-10-05")
    original, _ = ar_laden(con, rid)
    storno, _ = ar_laden(con, sid)
    assert original["storniert"] == 1
    assert storno["brutto_cent"] == -original["brutto_cent"]
    assert storno["storno_von_nummer"] == original["nummer"]
    assert offene_forderungen(con) == []
    with pytest.raises(FachFehler):
        ar_stornieren(con, rid)


def test_nur_letzte_rechnung_loeschbar(con):
    a, b = rechnung(con), rechnung(con)
    with pytest.raises(FachFehler):
        ar_loeschen(con, a)
    ar_loeschen(con, b)
    assert naechste_nummer(con, 2026) == "2026_002"


def test_er_berechnung():
    assert er_berechnen(12000, 20) == (10000, 2000)
    assert er_berechnen(11000, 10) == (10000, 1000)
    assert er_berechnen(5000, 0) == (5000, 0)
    assert er_berechnen(10000, 20, reverse_charge=True) == (10000, 2000)
    assert er_berechnen(11500, 20, vorsteuer_manuell_cent=1500) == (10000, 1500)


def test_er_laufende_nummer(con):
    a = er_speichern(con, {"datum": "2026-03-01", "lieferant": "A", "brutto_cent": 1200})
    b = er_speichern(con, {"datum": "2026-03-02", "lieferant": "B", "brutto_cent": 1200})
    enr = [con.execute("SELECT enr FROM eingangsrechnungen WHERE id = ?", (i,)).fetchone()[0] for i in (a, b)]
    assert enr == [1, 2]


def test_fremdkosten_weiterverrechnen(con):
    kunde = kunde_finden_oder_anlegen(con, "KAT")
    ids = [er_speichern(con, {"datum": "2026-09-01", "lieferant": "Druck.at", "text": "Flyer",
                              "brutto_cent": 12000, "weiter_kunde_id": kunde}) for _ in range(2)]
    ar_id = fremdkosten_verrechnen(con, ids, datum="2026-10-01", aufschlag_prozent=10)
    r, pos = ar_laden(con, ar_id)
    assert r["kunde_name"] == "KAT"
    assert [p["netto_cent"] for p in pos] == [11000, 11000]
    assert con.execute("SELECT COUNT(*) FROM eingangsrechnungen WHERE weiter_erledigt = 1 AND weiter_ar_id = ?",
                       (ar_id,)).fetchone()[0] == 2
    with pytest.raises(FachFehler):
        fremdkosten_verrechnen(con, ids)


def test_fremdkosten_nur_ein_kunde(con):
    a = er_speichern(con, {"datum": "2026-09-01", "brutto_cent": 100, "weiter_kunde_id": kunde_finden_oder_anlegen(con, "A")})
    b = er_speichern(con, {"datum": "2026-09-01", "brutto_cent": 100, "weiter_kunde_id": kunde_finden_oder_anlegen(con, "B")})
    with pytest.raises(FachFehler):
        fremdkosten_verrechnen(con, [a, b])


def test_uva(con):
    rechnung(con, datum="2026-07-10", positionen=[
        {"beschreibung": "x", "einzelpreis_cent": 100000, "ust_satz": 20},
        {"beschreibung": "Kurs", "einzelpreis_cent": 50000, "ust_satz": 0},
    ])
    rechnung(con, datum="2026-10-01")  # außerhalb
    er_speichern(con, {"datum": "2026-08-01", "brutto_cent": 24000, "ust_satz": 20})
    er_speichern(con, {"datum": "2026-08-02", "brutto_cent": 10000, "ust_satz": 20, "reverse_charge": True})
    d = uva(con, "2026-07-01", "2026-09-30")
    assert d["umsatz_gesamt"] == 150000
    assert d["steuerfrei"] == 50000
    assert d["ust"] == 20000
    assert d["vorsteuer"] == 4000
    assert (d["rc_bemessung"], d["rc_ust"]) == (10000, 2000)
    assert d["zahllast"] == 20000 + 2000 - 4000 - 2000


def test_kunden_zusammenfuehren(con):
    rechnung(con, kunde="APA")
    rechnung(con, kunde="APA-Comm GmbH")
    von = kunde_finden_oder_anlegen(con, "APA")
    nach = kunde_finden_oder_anlegen(con, "APA-Comm GmbH")
    kunden_zusammenfuehren(con, von, nach)
    assert con.execute("SELECT COUNT(*) FROM ausgangsrechnungen WHERE kunde_id = ?", (nach,)).fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM kunden").fetchone()[0] == 1
