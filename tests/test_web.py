import re

import pytest

from buchhaltung import create_app


def post(client, url, **daten):
    return client.post(url, data={"csrf_token": client.token, **daten}, follow_redirects=False)


def neue_rechnung(client, kunde="Neukunde GmbH"):
    return post(client, "/ausgang/neu", kunde=kunde, datum="2026-10-12", projekt="Logo",
                pos_beschreibung=["Konzept", "Reinzeichnung"], pos_menge=["2", "1,5"], pos_einheit=["Std.", "Std."],
                pos_preis=["120,00", "1.000"], pos_ust=["20", "20"])


def test_alle_seiten_leer(client):
    for url in ["/", "/ausgang/", "/ausgang/neu", "/eingang/", "/eingang/neu", "/eingang/fremdkosten", "/kunden/",
                "/auswertung/offene-posten", "/auswertung/uva", "/auswertung/uva?art=quartal&nr=3",
                "/auswertung/uva?art=jahr", "/auswertung/umsatz", "/einstellungen", "/import"]:
        assert client.get(url).status_code == 200, url


def test_rechnung_anlegen_pdf_bezahlen(client):
    antwort = neue_rechnung(client)
    assert antwort.status_code == 302
    url = antwort.headers["Location"]
    seite = client.get(url).get_data(as_text=True)
    assert "2026_001" in seite and "1.740,00 €" in seite  # (240 + 1500) netto
    rid = re.search(r"/ausgang/(\d+)", url).group(1)
    pdf = client.get(f"/ausgang/{rid}/pdf")
    assert pdf.mimetype == "application/pdf" and pdf.data.startswith(b"%PDF")
    post(client, f"/ausgang/{rid}/bezahlt", bezahlt_am="2026-10-20")
    assert "bezahlt am 20.10.2026" in client.get(url).get_data(as_text=True).lower()


def test_csrf_pflicht(client):
    antwort = client.post("/ausgang/neu", data={"kunde": "X", "datum": "2026-01-01"})
    assert antwort.status_code == 400


def test_fehlermeldung_statt_absturz(client):
    antwort = post(client, "/ausgang/neu", kunde="X", datum="2026-10-12", pos_beschreibung=[""], pos_menge=["1"],
                   pos_einheit=[""], pos_preis=[""], pos_ust=["20"])
    assert antwort.status_code == 302
    folge = client.get(antwort.headers["Location"]).get_data(as_text=True)
    assert "mindestens eine Position" in folge


def test_eingangsrechnung_und_weiterverrechnung(client):
    antwort = post(client, "/eingang/neu", datum="2026-09-15", lieferant="Druck.at", text="Plakate", brutto="240,00",
                   ust_satz="20", weiter_an="Gemeinde Tullnerbach")
    assert antwort.status_code == 302
    seite = client.get("/eingang/fremdkosten").get_data(as_text=True)
    assert "Gemeinde Tullnerbach" in seite and "200,00 €" in seite
    er_id = re.search(r'name="er_id" value="(\d+)"', seite).group(1)
    antwort = post(client, "/eingang/fremdkosten", er_id=er_id, aktion="rechnung", aufschlag="0")
    assert "/ausgang/" in antwort.headers["Location"]
    assert "Alle zugeordneten Fremdkosten sind weiterverrechnet" in client.get("/eingang/fremdkosten").get_data(as_text=True)


def test_export(client):
    neue_rechnung(client)
    antwort = client.get("/auswertung/export/2026.xlsx")
    assert antwort.status_code == 200 and antwort.data[:2] == b"PK"


def test_passwortschutz(tmp_path):
    app = create_app({"DATENVERZEICHNIS": tmp_path, "PASSWORT": "geheim", "SECRET_KEY": "x", "TESTING": True})
    c = app.test_client()
    assert c.get("/").status_code == 302
    c.post("/login", data={"passwort": "falsch"})
    assert c.get("/").status_code == 302
    c.post("/login", data={"passwort": "geheim"})
    assert c.get("/").status_code == 200


@pytest.mark.parametrize("ziel", ["//boese.example", "https://boese.example"])
def test_login_keine_offene_weiterleitung(tmp_path, ziel):
    app = create_app({"DATENVERZEICHNIS": tmp_path, "PASSWORT": "geheim", "SECRET_KEY": "x"})
    antwort = app.test_client().post(f"/login?weiter={ziel}", data={"passwort": "geheim"})
    assert antwort.headers["Location"] == "/"
