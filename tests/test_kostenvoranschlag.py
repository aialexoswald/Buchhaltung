import re

import pytest

from buchhaltung.kostenvoranschlag import kv_laden, kv_speichern, rechnung_aus_kv
from buchhaltung.logik import FachFehler, ar_laden, ar_loeschen, ar_speichern, ar_stornieren, kunde_finden_oder_anlegen


@pytest.fixture
def kv(con):
    kunde = kunde_finden_oder_anlegen(con, "Medizinische Universität Wien")
    return kv_speichern(con, {"kunde_id": kunde, "bezeichnung": "Kommunikationsstrategie", "datum": "2026-07-01"}, [
        {"posnr": "1.4", "beschreibung": "Redaktionsplan Social Media", "betrag_cent": 150000},
        {"posnr": "1.5", "beschreibung": "Interviews Key-Researcher", "betrag_cent": 100000},
        {"posnr": "2.4", "beschreibung": "Ausschreibung Webseite", "betrag_cent": 350000},
    ])


def ids(con, kv_id):
    return [p["id"] for p in kv_laden(con, kv_id)[1]]


def test_teilabrechnung(con, kv):
    a, b, c = ids(con, kv)
    rid = rechnung_aus_kv(con, kv, {a: 100, b: 0, c: 50}, {"datum": "2026-10-09"})
    r, pos = ar_laden(con, rid)
    assert [p["netto_cent"] for p in pos] == [150000, 175000]   # Pos. 1.5 mit 0 % fehlt
    assert r["netto_cent"] == 325000 and r["betreff"] == "Kommunikationsstrategie"
    assert pos[1]["beschreibung"] == "Pos. 2.4 Ausschreibung Webseite\n50% von EUR 3.500,00"
    _, kvpos = kv_laden(con, kv)
    assert [round(p["verrechnet_prozent"]) for p in kvpos] == [100, 0, 50]
    assert [round(p["rest_prozent"]) for p in kvpos] == [0, 100, 50]


def test_mehr_als_100_prozent_nicht_moeglich(con, kv):
    _, _, c = ids(con, kv)
    rechnung_aus_kv(con, kv, {c: 60}, {})
    with pytest.raises(FachFehler, match="höchstens noch 40"):
        rechnung_aus_kv(con, kv, {c: 50}, {})
    rechnung_aus_kv(con, kv, {c: 40}, {})
    assert kv_laden(con, kv)[1][2]["rest_prozent"] == pytest.approx(0)


def test_nichts_ausgewaehlt(con, kv):
    with pytest.raises(FachFehler):
        rechnung_aus_kv(con, kv, {}, {})


def test_storno_und_loeschen_geben_frei(con, kv):
    a, _, _ = ids(con, kv)
    rid = rechnung_aus_kv(con, kv, {a: 100}, {})
    ar_stornieren(con, rid)
    assert kv_laden(con, kv)[1][0]["rest_prozent"] == pytest.approx(100)
    rid2 = rechnung_aus_kv(con, kv, {a: 30}, {})
    ar_loeschen(con, rid2)
    assert kv_laden(con, kv)[1][0]["rest_prozent"] == pytest.approx(100)


def test_bearbeiten_behaelt_verknuepfung(con, kv):
    a, _, _ = ids(con, kv)
    rid = rechnung_aus_kv(con, kv, {a: 50}, {})
    r, pos = ar_laden(con, rid)
    ar_speichern(con, {"datum": r["datum"], "kunde_id": r["kunde_id"]},
                 [{**dict(p)} for p in pos] + [{"beschreibung": "Zusatz", "einzelpreis_cent": 1000}], rechnung_id=rid)
    assert kv_laden(con, kv)[1][0]["verrechnet_prozent"] == pytest.approx(50)


def test_verrechnete_position_nicht_loeschbar(con, kv):
    a, b, c = ids(con, kv)
    rechnung_aus_kv(con, kv, {a: 10}, {})
    kv_daten = {"kunde_id": 1, "datum": "2026-07-01"}
    with pytest.raises(FachFehler):
        kv_speichern(con, kv_daten, [{"id": b, "betrag_cent": 1}, {"id": c, "betrag_cent": 1}], kv_id=kv)
    kv_speichern(con, kv_daten, [{"id": a, "posnr": "1.4", "beschreibung": "neu", "betrag_cent": 150000}], kv_id=kv)
    assert len(kv_laden(con, kv)[1]) == 1


def post(client, url, **daten):
    return client.post(url, data={"csrf_token": client.token, **daten})


def test_web_ablauf(client):
    antwort = post(client, "/kostenvoranschlaege/neu", kunde="KAT", datum="2026-06-01", bezeichnung="CTS26",
                   pos_id=["", ""], pos_nr=["1", "2"], pos_beschreibung=["Konzept", "Umsetzung"],
                   pos_betrag=["10.000", "12.625"], pos_ust=["20", "20"])
    url = antwort.headers["Location"]
    seite = client.get(url).get_data(as_text=True)
    assert "22.625,00 €" in seite
    felder = re.findall(r'name="(prozent_\d+)"', seite)
    antwort = post(client, url, datum="2026-10-12", betreff="CTS26 1. Teil", **{felder[0]: "100", felder[1]: "50"})
    rechnung = client.get(antwort.headers["Location"]).get_data(as_text=True)
    assert "2026_001" in rechnung and "16.312,50 €" in rechnung
    # Bearbeitungsformular trägt die Verknüpfung weiter
    rid = re.search(r"/ausgang/(\d+)", antwort.headers["Location"]).group(1)
    formular = client.get(f"/ausgang/{rid}/bearbeiten").get_data(as_text=True)
    assert len(re.findall(r'name="pos_kv" value="\d+"', formular)) == 2
    seite = client.get(url).get_data(as_text=True)
    assert "erledigt" in seite and "teilweise" not in seite  # Pos. 1 erledigt
    assert "teilweise verrechnet" in client.get("/kostenvoranschlaege/").get_data(as_text=True)
    pdf = client.get(f"/ausgang/{rid}/pdf")
    assert pdf.data.startswith(b"%PDF")
