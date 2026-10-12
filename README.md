# Buchhaltung

Anwendung zur Verwaltung von Eingangs- und Ausgangsrechnungen – Ersatz für die bisherige
Excel-Datei `AR_ER_Futura_JJJJ.xlsx`. Läuft lokal im Browser, die Daten liegen in einer
einzigen Datei (`data/buchhaltung.db`) auf Ihrem Rechner.

## Funktionen

- **Ausgangsrechnungen** mit fortlaufender Nummer (`2026_114`, …), Positionen, gemischten
  Steuersätzen (20 / 13 / 10 / 0 %), Steuerhinweisen (Reverse Charge, steuerfrei) und
  **PDF-Rechnung** nach § 11 UStG. Storno erzeugt eine Stornorechnung mit eigener Nummer.
- **Eingangsrechnungen** mit laufender Nummer je Jahr, automatischer Vorsteuer-Berechnung,
  Reverse Charge, Beleg-Upload (PDF/Bild) und Zahlungsstatus.
- **Fremdkosten weiterverrechnen**: Eingangsrechnungen einem Kunden zuordnen; offene
  Fremdkosten mit einem Klick (optional mit Aufschlag) in eine Ausgangsrechnung übernehmen.
- **Offene Posten**: offene und überfällige Forderungen, unbezahlte Eingangsrechnungen.
- **UVA-Hilfe** je Monat / Quartal / Jahr (USt, Vorsteuer, Reverse Charge, Zahllast).
- **Auswertungen**: Monatsumsatz im Vergleich zu den Vorjahren (ersetzt die bisherigen
  händischen Monatssummen), Umsatz je Kunde und Projekt, Honorar vs. Fremdkosten.
- **Excel-Import** der bisherigen Datei (alle Jahre) und **Excel-Export** je Jahr für die
  Steuerberatung.
- **Plausibilitätsprüfung** auf der Übersicht (falsche Jahreszahlen, fehlende Beträge,
  fehlende Lieferanten, …).

## Installation & Start

Voraussetzung: [Python 3.10 oder neuer](https://www.python.org/downloads/).

**Windows:** Doppelklick auf `start.bat`
**macOS / Linux:** `./start.sh` im Terminal

Beim ersten Start werden die benötigten Pakete installiert, danach öffnet sich der Browser
mit <http://127.0.0.1:5000>.

Manuell:

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip ...
.venv/bin/python -m buchhaltung                 # startet die Web-App
```

## Bisherige Excel-Datei übernehmen

Im Menü **Excel-Import** die Datei hochladen – oder im Terminal:

```bash
.venv/bin/python -m buchhaltung import AR_ER_Futura_2026.xlsx
```

Der Import ist wiederholbar (vorhandene Rechnungsnummern werden übersprungen). Dabei gilt:

- **Spalte „bezahlt“ (AR):** In der bisherigen Datei steht `1` bei den jüngsten, noch
  offenen Rechnungen. Der Import wertet daher `1` = *offen* und `0` = *bezahlt*. Falls das
  umgekehrt gemeint war: `--offen-wert 0` bzw. die Auswahl im Import-Formular.
- **Steuersatz:** wird aus Netto/Brutto erkannt. Enthält das Brutto zusätzlich Spesen ohne
  USt (z. B. Bahn/Hotel), entsteht eine eigene Position „Barauslagen (ohne USt)“.
- **Datum der Eingangsrechnungen:** In den ER-Blättern ist die Datumsspalte oft nicht
  gepflegt. Der Monat wird dann aus dem Monatsblock abgeleitet und das Datum als
  „geschätzt“ markiert.
- **Weiterverrechnung:** Spalte „weiter-verrechnen an“ ≠ Futura wird dem Kunden zugeordnet,
  „verrechnet = ja“ gilt als erledigt, „intern“ als nicht weiterzuverrechnen.
- **Überwiesen:** Nur Einträge mit „nein“ oder „???“ gelten als unbezahlt.

Nach dem Import unter **Kunden** doppelte Schreibweisen (z. B. „APA“ / „APA-Comm GmbH“)
mit *Zusammenführen* bereinigen und unter **Einstellungen** Adresse, UID und Bankdaten für
die Rechnungs-PDFs eintragen.

## Datensicherung

Alle Daten liegen im Ordner `data/` (Datenbank + Belege). Diesen Ordner regelmäßig sichern,
z. B. in OneDrive/SharePoint kopieren. **Er gehört nicht ins Git-Repository** (ist in
`.gitignore` ausgeschlossen).

## Optionen

| Umgebungsvariable        | Bedeutung                                                       |
|--------------------------|-----------------------------------------------------------------|
| `BUCHHALTUNG_DATEN`      | Speicherort für Datenbank und Belege (Standard: `./data`)       |
| `BUCHHALTUNG_PASSWORT`   | Passwortschutz aktivieren (empfohlen, wenn auf einem Server)    |

Start im Netzwerk (z. B. auf einem Büro-Rechner): `python -m buchhaltung start --host 0.0.0.0`
– dann unbedingt `BUCHHALTUNG_PASSWORT` setzen.

## Entwicklung

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Aufbau: `buchhaltung/logik.py` (Rechnungslogik), `auswertung.py` (UVA, offene Posten,
Umsatz), `importer.py` (Excel-Import), `pdf.py` (Rechnungs-PDF), `ansichten.py` (Web-Routen),
`templates/` (Oberfläche). Beträge werden durchgehend in ganzen Cent gespeichert.

> Die UVA-Ansicht ist eine Hilfsrechnung zur Kontrolle und ersetzt nicht die Abstimmung mit
> der Steuerberatung.
