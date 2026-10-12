-- Alle Geldbeträge werden als ganze Cent (INTEGER) gespeichert,
-- damit keine Rundungsfehler wie in Excel entstehen.

CREATE TABLE IF NOT EXISTS einstellungen (
    schluessel TEXT PRIMARY KEY,
    wert       TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS kunden (
    id               INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    adresse          TEXT NOT NULL DEFAULT '',
    uid              TEXT NOT NULL DEFAULT '',
    email            TEXT NOT NULL DEFAULT '',
    zahlungsziel_tage INTEGER,
    notiz            TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS kunden_name ON kunden (name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS ausgangsrechnungen (
    id             INTEGER PRIMARY KEY,
    nummer         TEXT NOT NULL UNIQUE,
    datum          TEXT NOT NULL,           -- ISO-Datum JJJJ-MM-TT
    kunde_id       INTEGER NOT NULL REFERENCES kunden (id),
    projekt        TEXT NOT NULL DEFAULT '',
    betreff        TEXT NOT NULL DEFAULT '',
    leistungszeitraum TEXT NOT NULL DEFAULT '',
    steuerhinweis  TEXT NOT NULL DEFAULT '',
    notiz          TEXT NOT NULL DEFAULT '',
    faellig_am     TEXT,
    bezahlt_am     TEXT,
    bezahlt        INTEGER NOT NULL DEFAULT 0,
    storno_von_id  INTEGER REFERENCES ausgangsrechnungen (id),
    storniert      INTEGER NOT NULL DEFAULT 0,
    importiert     INTEGER NOT NULL DEFAULT 0,
    netto_cent     INTEGER NOT NULL DEFAULT 0,
    ust_cent       INTEGER NOT NULL DEFAULT 0,
    brutto_cent    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ar_datum ON ausgangsrechnungen (datum);
CREATE INDEX IF NOT EXISTS ar_kunde ON ausgangsrechnungen (kunde_id);

CREATE TABLE IF NOT EXISTS ar_positionen (
    id              INTEGER PRIMARY KEY,
    rechnung_id     INTEGER NOT NULL REFERENCES ausgangsrechnungen (id) ON DELETE CASCADE,
    pos             INTEGER NOT NULL,
    beschreibung    TEXT NOT NULL DEFAULT '',
    menge           REAL NOT NULL DEFAULT 1,
    einheit         TEXT NOT NULL DEFAULT '',
    einzelpreis_cent INTEGER NOT NULL DEFAULT 0,
    ust_satz        INTEGER NOT NULL DEFAULT 20,
    netto_cent      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS eingangsrechnungen (
    id              INTEGER PRIMARY KEY,
    jahr            INTEGER NOT NULL,
    enr             INTEGER,                -- laufende Nummer im Jahr
    datum           TEXT NOT NULL,
    datum_geschaetzt INTEGER NOT NULL DEFAULT 0,
    lieferant       TEXT NOT NULL DEFAULT '',
    rechnungsnr_lieferant TEXT NOT NULL DEFAULT '',
    text            TEXT NOT NULL DEFAULT '',
    kostenart       TEXT NOT NULL DEFAULT '',
    brutto_cent     INTEGER NOT NULL DEFAULT 0,
    ust_satz        INTEGER NOT NULL DEFAULT 20,
    reverse_charge  INTEGER NOT NULL DEFAULT 0,
    vorsteuer_manuell_cent INTEGER,
    netto_cent      INTEGER NOT NULL DEFAULT 0,
    vorsteuer_cent  INTEGER NOT NULL DEFAULT 0,
    bezahlt         INTEGER NOT NULL DEFAULT 0,
    bezahlt_am      TEXT,
    weiter_kunde_id INTEGER REFERENCES kunden (id),
    weiter_erledigt INTEGER NOT NULL DEFAULT 0,
    weiter_ar_id    INTEGER REFERENCES ausgangsrechnungen (id) ON DELETE SET NULL,
    beleg_datei     TEXT,
    notiz           TEXT NOT NULL DEFAULT '',
    importiert      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS er_datum ON eingangsrechnungen (datum);
CREATE INDEX IF NOT EXISTS er_weiter ON eingangsrechnungen (weiter_kunde_id, weiter_erledigt);
