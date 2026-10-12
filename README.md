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

## Installation auf dem Mac (empfohlen)

1. **Herunterladen** – passend zu Ihrem Mac (Apple-Menü  → „Über diesen Mac“ zeigt den Chip):
   - Apple-Chip (M1, M2, M3, M4 …):
     [Buchhaltung-Mac-AppleSilicon.zip](https://github.com/aialexoswald/Buchhaltung/releases/latest/download/Buchhaltung-Mac-AppleSilicon.zip)
   - Intel-Prozessor:
     [Buchhaltung-Mac-Intel.zip](https://github.com/aialexoswald/Buchhaltung/releases/latest/download/Buchhaltung-Mac-Intel.zip)
2. Die ZIP-Datei im Ordner „Downloads“ doppelklicken und **„Buchhaltung“ in den Ordner
   „Programme“ ziehen**.
3. **Erster Start (nur einmal nötig):** Die App ist nicht bei Apple registriert, daher
   blockiert macOS sie beim ersten Mal.
   - „Buchhaltung“ doppelklicken → Meldung mit **„Fertig“** schließen.
   - **Systemeinstellungen → Datenschutz & Sicherheit** öffnen, ganz nach unten scrollen und
     bei „Buchhaltung wurde blockiert“ auf **„Dennoch öffnen“** klicken, mit Passwort bestätigen.
   - (Auf älteren macOS-Versionen genügt: Rechtsklick auf die App → **Öffnen** → **Öffnen**.)
4. Ab dann: **Doppelklick auf „Buchhaltung“** – der Browser öffnet sich mit der Anwendung.
   Ist der Browser-Tab geschlossen, öffnet ein weiterer Doppelklick ihn wieder.
   Zum Beenden links unten auf **„Beenden“** klicken.

Die Daten liegen auf dem Mac unter `~/Library/Application Support/Buchhaltung`
(nicht in OneDrive, damit die Datenbank nicht beim Synchronisieren beschädigt wird).
Sicherung: **Einstellungen → Datensicherung herunterladen** und die ZIP-Datei in OneDrive ablegen.

Neue Versionen werden bei jeder Änderung automatisch gebaut; zum Aktualisieren einfach erneut
herunterladen und die App in „Programme“ ersetzen – die Daten bleiben erhalten.

## Start ohne App (für Entwicklung, Windows, Linux)

Voraussetzung: [Python 3.10 oder neuer](https://www.python.org/downloads/).
Windows: `start.bat` doppelklicken · macOS/Linux: `sh start.sh`. Danach öffnet sich
<http://127.0.0.1:8765>. Die Daten liegen dabei im Unterordner `data/`.

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

**Einstellungen → Datensicherung herunterladen** erzeugt eine ZIP-Datei mit Datenbank und
Belegen. Die Daten gehören **nicht ins Git-Repository** (`data/` ist in `.gitignore`
ausgeschlossen).

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

Mac-App bauen: `pyinstaller --noconfirm packaging/Buchhaltung.spec` (auf einem Mac). Das
übernimmt der GitHub-Workflow `.github/workflows/mac-app.yml` automatisch und veröffentlicht
das Ergebnis als Release.

Aufbau: `buchhaltung/logik.py` (Rechnungslogik), `auswertung.py` (UVA, offene Posten,
Umsatz), `importer.py` (Excel-Import), `pdf.py` (Rechnungs-PDF), `ansichten.py` (Web-Routen),
`templates/` (Oberfläche). Beträge werden durchgehend in ganzen Cent gespeichert.

> Die UVA-Ansicht ist eine Hilfsrechnung zur Kontrolle und ersetzt nicht die Abstimmung mit
> der Steuerberatung.
