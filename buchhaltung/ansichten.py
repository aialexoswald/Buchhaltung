"""Web-Oberfläche (Flask-Routen)."""
import sqlite3
import tempfile
import threading
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

from flask import (Blueprint, Response, current_app, flash, redirect, render_template, request,
                   send_file, session, url_for)

from . import auswertung as aw
from .db import einstellungen, get_db
from .export import jahr_exportieren
from .geld import MONATE, UST_SAETZE, datum_parsen, euro_zu_cent, heute
from .importer import importieren
from .logik import (FachFehler, ar_bezahlt_setzen, ar_laden, ar_loeschen, ar_speichern, ar_steuersaetze,
                    ar_stornieren, er_speichern, fremdkosten_verrechnen, kunde_finden_oder_anlegen,
                    kunden_zusammenfuehren)
from .pdf import rechnung_pdf

STEUERHINWEISE = [
    "",
    "Reverse Charge – die Steuerschuld geht auf den Leistungsempfänger über.",
    "Steuerfreie Leistung gemäß § 6 Abs. 1 Z 11 UStG.",
    "Nicht steuerbare Leistung (Leistungsort im Ausland).",
]

uebersicht = Blueprint("uebersicht", __name__)
ausgang = Blueprint("ausgang", __name__, url_prefix="/ausgang")
eingang = Blueprint("eingang", __name__, url_prefix="/eingang")
kunden = Blueprint("kunden", __name__, url_prefix="/kunden")
berichte = Blueprint("berichte", __name__, url_prefix="/auswertung")
verwaltung = Blueprint("verwaltung", __name__)


def registrieren(app):
    for bp in (uebersicht, ausgang, eingang, kunden, berichte, verwaltung):
        app.register_blueprint(bp)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            if request.form.get("passwort") == current_app.config["PASSWORT"]:
                session["angemeldet"] = True
                ziel = request.args.get("weiter", "/")
                return redirect(ziel if ziel.startswith("/") and not ziel.startswith("//") else "/")
            flash("Falsches Passwort.", "fehler")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("uebersicht.start"))

    @app.route("/lebenszeichen")
    def lebenszeichen():
        return Response("buchhaltung", mimetype="text/plain")

    @app.route("/beenden", methods=["POST"])
    def beenden():
        funktion = current_app.config.get("BEENDEN")
        if funktion:
            threading.Timer(0.3, funktion).start()
        return render_template("beendet.html")

    @app.errorhandler(FachFehler)
    def fachfehler(e):
        get_db().rollback()
        flash(str(e), "fehler")
        return redirect(request.referrer or url_for("uebersicht.start"))


def _jahr():
    try:
        return int(request.args.get("jahr", heute().year))
    except ValueError:
        return heute().year


def _kundennamen(con):
    return [r["name"] for r in con.execute("SELECT name FROM kunden ORDER BY name COLLATE NOCASE")]


# ---------------------------------------------------------------- Übersicht

@uebersicht.route("/")
def start():
    con = get_db()
    jahr = heute().year
    monat = heute().month
    umsatz = aw.umsatz_je_monat(con, [jahr, jahr - 1])
    bisher = sum(umsatz[jahr][:monat])
    vorjahr_bisher = sum(umsatz[jahr - 1][:monat])
    forderungen = aw.offene_forderungen(con)
    ueberfaellig = [f for f in forderungen if f["tage_ueberfaellig"] > 0]
    verbindlichkeiten = aw.offene_verbindlichkeiten(con)
    fremd = aw.offene_fremdkosten(con)
    # UVA des Vormonats (fällig am 15. des zweitfolgenden Monats)
    vm_jahr, vm = (jahr, monat - 1) if monat > 1 else (jahr - 1, 12)
    von, bis, uva_name = aw.zeitraum(vm_jahr, "monat", vm)
    return render_template(
        "start.html",
        jahr=jahr,
        bisher=bisher,
        vorjahr_bisher=vorjahr_bisher,
        monat_name=MONATE[monat - 1],
        forderungen=forderungen,
        forderungen_summe=sum(f["brutto_cent"] for f in forderungen),
        ueberfaellig=ueberfaellig,
        ueberfaellig_summe=sum(f["brutto_cent"] for f in ueberfaellig),
        verbindlichkeiten_summe=sum(v["brutto_cent"] for v in verbindlichkeiten),
        verbindlichkeiten_anzahl=len(verbindlichkeiten),
        fremd_summe=sum(f["netto_cent"] for f in fremd),
        fremd_anzahl=len(fremd),
        uva=aw.uva(con, von, bis),
        uva_name=uva_name,
        diagramm=_diagramm(umsatz, jahr),
        hinweise=aw.hinweise(con),
        letzte=con.execute(
            """SELECT ar.*, k.name AS kunde_name FROM ausgangsrechnungen ar JOIN kunden k ON k.id = ar.kunde_id
               ORDER BY ar.datum DESC, ar.nummer DESC LIMIT 6"""
        ).fetchall(),
    )


def _diagramm(umsatz, jahr):
    """Daten für das Säulendiagramm Monatsumsatz (aktuelles Jahr vs. Vorjahr)."""
    serien = [(jahr, umsatz.get(jahr, [0] * 12)), (jahr - 1, umsatz.get(jahr - 1, [0] * 12))]
    hoechster = max([max(w) for _, w in serien] + [1])
    # „schöne“ Obergrenze für die Achse
    schritt = 10 ** (len(str(int(hoechster // 100))) - 1) * 100
    for faktor in (1, 2, 2.5, 5, 10):
        if hoechster <= schritt * faktor * 4:
            schritt = int(schritt * faktor)
            break
    oben = schritt * 4
    return {"serien": serien, "oben": oben, "linien": [oben * i // 4 for i in range(5)], "monate": MONATE}


# --------------------------------------------------------- Ausgangsrechnungen

@ausgang.route("/")
def liste():
    con = get_db()
    jahr = _jahr()
    status = request.args.get("status", "")
    suche = request.args.get("q", "").strip()
    sql = """SELECT ar.*, k.name AS kunde_name FROM ausgangsrechnungen ar JOIN kunden k ON k.id = ar.kunde_id
             WHERE substr(ar.datum, 1, 4) = ?"""
    werte = [str(jahr)]
    if status == "offen":
        sql += " AND ar.bezahlt = 0 AND ar.storniert = 0 AND ar.storno_von_id IS NULL"
    elif status == "bezahlt":
        sql += " AND ar.bezahlt = 1"
    if suche:
        sql += " AND (k.name LIKE ? OR ar.nummer LIKE ? OR ar.projekt LIKE ? OR ar.notiz LIKE ?)"
        werte += [f"%{suche}%"] * 4
    zeilen = con.execute(sql + " ORDER BY ar.nummer DESC", werte).fetchall()
    return render_template(
        "ausgang_liste.html", zeilen=zeilen, jahr=jahr, jahre=aw.verfuegbare_jahre(con), status=status,
        suche=suche, summe_netto=sum(z["netto_cent"] for z in zeilen), summe_brutto=sum(z["brutto_cent"] for z in zeilen),
    )


def _ar_formular_lesen(con):
    f = request.form
    positionen = []
    for beschreibung, menge, einheit, preis, satz in zip(
        f.getlist("pos_beschreibung"), f.getlist("pos_menge"), f.getlist("pos_einheit"),
        f.getlist("pos_preis"), f.getlist("pos_ust"),
    ):
        if not beschreibung.strip() and not preis.strip():
            continue
        try:
            menge_wert = float((menge or "1").replace(",", "."))
        except ValueError:
            raise FachFehler(f"Ungültige Menge: {menge}") from None
        cent = euro_zu_cent(preis)
        if cent is None:
            raise FachFehler(f"Bitte einen Preis für „{beschreibung}“ angeben.")
        positionen.append({"beschreibung": beschreibung.strip(), "menge": menge_wert, "einheit": einheit.strip(),
                           "einzelpreis_cent": cent, "ust_satz": int(satz)})
    try:
        daten = {
            "datum": datum_parsen(f.get("datum")),
            "kunde_id": kunde_finden_oder_anlegen(con, f.get("kunde")),
            "projekt": f.get("projekt", "").strip(),
            "leistungszeitraum": f.get("leistungszeitraum", "").strip(),
            "steuerhinweis": f.get("steuerhinweis", "").strip(),
            "notiz": f.get("notiz", "").strip(),
            "faellig_am": datum_parsen(f.get("faellig_am")),
        }
    except ValueError as e:
        raise FachFehler(str(e)) from None
    return daten, positionen


@ausgang.route("/neu", methods=["GET", "POST"])
def neu():
    con = get_db()
    if request.method == "POST":
        daten, positionen = _ar_formular_lesen(con)
        rid = ar_speichern(con, daten, positionen)
        con.commit()
        flash("Rechnung angelegt.", "ok")
        return redirect(url_for("ausgang.detail", rechnung_id=rid))
    vorlage, pos = None, []
    if request.args.get("kopie"):
        vorlage, pos = ar_laden(con, int(request.args["kopie"]))
    return render_template(
        "ausgang_formular.html", r=vorlage, positionen=pos, kopie=bool(vorlage), heute=heute().isoformat(),
        kunden=_kundennamen(con), projekte=_projekte(con), steuerhinweise=STEUERHINWEISE, saetze=UST_SAETZE,
    )


def _projekte(con):
    return [r["projekt"] for r in con.execute(
        "SELECT projekt FROM ausgangsrechnungen WHERE projekt != '' GROUP BY projekt ORDER BY MAX(datum) DESC LIMIT 60")]


@ausgang.route("/<int:rechnung_id>/bearbeiten", methods=["GET", "POST"])
def bearbeiten(rechnung_id):
    con = get_db()
    r, pos = ar_laden(con, rechnung_id)
    if request.method == "POST":
        daten, positionen = _ar_formular_lesen(con)
        ar_speichern(con, daten, positionen, rechnung_id=rechnung_id)
        con.commit()
        flash("Rechnung gespeichert.", "ok")
        return redirect(url_for("ausgang.detail", rechnung_id=rechnung_id))
    return render_template(
        "ausgang_formular.html", r=r, positionen=pos, kopie=False, heute=heute().isoformat(),
        kunden=_kundennamen(con), projekte=_projekte(con), steuerhinweise=STEUERHINWEISE, saetze=UST_SAETZE,
    )


@ausgang.route("/<int:rechnung_id>")
def detail(rechnung_id):
    con = get_db()
    r, pos = ar_laden(con, rechnung_id)
    fremd = con.execute("SELECT * FROM eingangsrechnungen WHERE weiter_ar_id = ?", (rechnung_id,)).fetchall()
    return render_template("ausgang_detail.html", r=r, positionen=pos, saetze=ar_steuersaetze(pos),
                           fremd=fremd, heute=heute().isoformat())


@ausgang.route("/<int:rechnung_id>/pdf")
def pdf(rechnung_id):
    con = get_db()
    r, pos = ar_laden(con, rechnung_id)
    inhalt = rechnung_pdf(r, pos, einstellungen(con))
    return Response(inhalt, mimetype="application/pdf", headers={
        "Content-Disposition": f'inline; filename="Rechnung_{r["nummer"]}.pdf"'})


@ausgang.route("/<int:rechnung_id>/bezahlt", methods=["POST"])
def bezahlt(rechnung_id):
    con = get_db()
    ar_bezahlt_setzen(con, rechnung_id, request.form.get("bezahlt_am") or None)
    con.commit()
    return redirect(request.form.get("zurueck") or url_for("ausgang.detail", rechnung_id=rechnung_id))


@ausgang.route("/<int:rechnung_id>/stornieren", methods=["POST"])
def stornieren(rechnung_id):
    con = get_db()
    neue = ar_stornieren(con, rechnung_id, request.form.get("datum") or None)
    con.commit()
    flash("Stornorechnung erstellt.", "ok")
    return redirect(url_for("ausgang.detail", rechnung_id=neue))


@ausgang.route("/<int:rechnung_id>/loeschen", methods=["POST"])
def loeschen(rechnung_id):
    con = get_db()
    ar_loeschen(con, rechnung_id)
    con.commit()
    flash("Rechnung gelöscht.", "ok")
    return redirect(url_for("ausgang.liste"))


# --------------------------------------------------------- Eingangsrechnungen

@eingang.route("/")
def liste():
    con = get_db()
    jahr = _jahr()
    filter_ = request.args.get("filter", "")
    suche = request.args.get("q", "").strip()
    sql = """SELECT er.*, k.name AS kunde_name, ar.nummer AS ar_nummer FROM eingangsrechnungen er
             LEFT JOIN kunden k ON k.id = er.weiter_kunde_id
             LEFT JOIN ausgangsrechnungen ar ON ar.id = er.weiter_ar_id
             WHERE er.jahr = ?"""
    werte = [jahr]
    if filter_ == "unbezahlt":
        sql += " AND er.bezahlt = 0"
    elif filter_ == "weiterverrechnen":
        sql += " AND er.weiter_kunde_id IS NOT NULL AND er.weiter_erledigt = 0"
    elif filter_ == "intern":
        sql += " AND er.weiter_kunde_id IS NULL"
    if suche:
        sql += " AND (er.lieferant LIKE ? OR er.text LIKE ? OR k.name LIKE ? OR er.notiz LIKE ?)"
        werte += [f"%{suche}%"] * 4
    zeilen = con.execute(sql + " ORDER BY er.datum DESC, er.enr DESC", werte).fetchall()
    return render_template(
        "eingang_liste.html", zeilen=zeilen, jahr=jahr, jahre=aw.verfuegbare_jahre(con), filter=filter_, suche=suche,
        summe_brutto=sum(z["brutto_cent"] for z in zeilen), summe_netto=sum(z["netto_cent"] for z in zeilen),
        summe_vst=sum(z["vorsteuer_cent"] for z in zeilen),
    )


def _er_formular(con, er=None):
    f = request.form
    weiter = f.get("weiter_an", "").strip()
    try:
        daten = {
            "datum": datum_parsen(f.get("datum")),
            "lieferant": f.get("lieferant", "").strip(),
            "rechnungsnr_lieferant": f.get("rechnungsnr_lieferant", "").strip(),
            "text": f.get("text", "").strip(),
            "kostenart": f.get("kostenart", "").strip(),
            "brutto_cent": euro_zu_cent(f.get("brutto")),
            "ust_satz": int(f.get("ust_satz", 20)),
            "reverse_charge": f.get("reverse_charge") == "1",
            "vorsteuer_manuell_cent": euro_zu_cent(f.get("vorsteuer_manuell")),
            "bezahlt": f.get("bezahlt") == "1",
            "bezahlt_am": (datum_parsen(f.get("bezahlt_am")) or (heute() if f.get("bezahlt") == "1" else None)),
            "weiter_kunde_id": kunde_finden_oder_anlegen(con, weiter) if weiter else None,
            "weiter_erledigt": f.get("weiter_erledigt") == "1",
            "notiz": f.get("notiz", "").strip(),
        }
    except ValueError as e:
        raise FachFehler(str(e)) from None
    if daten["bezahlt_am"]:
        daten["bezahlt_am"] = daten["bezahlt_am"].isoformat()
    if er is not None and er["datum_geschaetzt"]:
        daten["datum_geschaetzt"] = int(daten["datum"].isoformat() == er["datum"])
    datei = request.files.get("beleg")
    if datei and datei.filename:
        endung = Path(datei.filename).suffix.lower()
        if endung not in (".pdf", ".png", ".jpg", ".jpeg"):
            raise FachFehler("Belege bitte als PDF, PNG oder JPG hochladen.")
        name = f"{daten['datum'].year}/{uuid.uuid4().hex}{endung}"
        ziel = Path(current_app.config["BELEGE"]) / name
        ziel.parent.mkdir(parents=True, exist_ok=True)
        datei.save(ziel)
        daten["beleg_datei"] = name
    return daten


def _er_vorlagen(con):
    return {
        "lieferanten": [r["lieferant"] for r in con.execute(
            "SELECT lieferant FROM eingangsrechnungen WHERE lieferant != '' GROUP BY lieferant ORDER BY COUNT(*) DESC LIMIT 300")],
        "kostenarten": [r["kostenart"] for r in con.execute(
            "SELECT kostenart FROM eingangsrechnungen WHERE kostenart != '' GROUP BY kostenart ORDER BY kostenart")],
        "kunden": _kundennamen(con),
        "saetze": UST_SAETZE,
    }


@eingang.route("/neu", methods=["GET", "POST"])
def neu():
    con = get_db()
    if request.method == "POST":
        er_speichern(con, _er_formular(con))
        con.commit()
        flash("Eingangsrechnung erfasst.", "ok")
        if request.form.get("weiter_erfassen"):
            return redirect(url_for("eingang.neu"))
        return redirect(url_for("eingang.liste", jahr=datum_parsen(request.form.get("datum")).year))
    return render_template("eingang_formular.html", er=None, heute=heute().isoformat(), **_er_vorlagen(con))


@eingang.route("/<int:er_id>", methods=["GET", "POST"])
def bearbeiten(er_id):
    con = get_db()
    er = con.execute(
        """SELECT er.*, k.name AS kunde_name, ar.nummer AS ar_nummer FROM eingangsrechnungen er
           LEFT JOIN kunden k ON k.id = er.weiter_kunde_id
           LEFT JOIN ausgangsrechnungen ar ON ar.id = er.weiter_ar_id WHERE er.id = ?""", (er_id,)
    ).fetchone()
    if er is None:
        raise FachFehler("Eingangsrechnung nicht gefunden.")
    if request.method == "POST":
        er_speichern(con, _er_formular(con, er), er_id=er_id)
        con.commit()
        flash("Eingangsrechnung gespeichert.", "ok")
        return redirect(url_for("eingang.liste", jahr=datum_parsen(request.form.get("datum")).year))
    return render_template("eingang_formular.html", er=er, heute=heute().isoformat(), **_er_vorlagen(con))


@eingang.route("/<int:er_id>/beleg")
def beleg(er_id):
    er = get_db().execute("SELECT beleg_datei FROM eingangsrechnungen WHERE id = ?", (er_id,)).fetchone()
    if not er or not er["beleg_datei"]:
        raise FachFehler("Kein Beleg vorhanden.")
    basis = Path(current_app.config["BELEGE"]).resolve()
    pfad = (basis / er["beleg_datei"]).resolve()
    if basis not in pfad.parents:
        raise FachFehler("Ungültiger Belegpfad.")
    return send_file(pfad)


@eingang.route("/<int:er_id>/bezahlt", methods=["POST"])
def bezahlt(er_id):
    con = get_db()
    if request.form.get("bezahlt") == "1":
        con.execute("UPDATE eingangsrechnungen SET bezahlt = 1, bezahlt_am = ? WHERE id = ?",
                    (heute().isoformat(), er_id))
    else:
        con.execute("UPDATE eingangsrechnungen SET bezahlt = 0, bezahlt_am = NULL WHERE id = ?", (er_id,))
    con.commit()
    return redirect(request.form.get("zurueck") or url_for("eingang.liste"))


@eingang.route("/<int:er_id>/loeschen", methods=["POST"])
def loeschen(er_id):
    con = get_db()
    con.execute("DELETE FROM eingangsrechnungen WHERE id = ?", (er_id,))
    con.commit()
    flash("Eingangsrechnung gelöscht.", "ok")
    return redirect(url_for("eingang.liste"))


@eingang.route("/fremdkosten", methods=["GET", "POST"])
def fremdkosten():
    con = get_db()
    if request.method == "POST":
        ids = [int(i) for i in request.form.getlist("er_id")]
        if request.form.get("aktion") == "erledigt":
            if ids:
                con.execute(f"UPDATE eingangsrechnungen SET weiter_erledigt = 1 WHERE id IN ({', '.join('?' * len(ids))})", ids)
                con.commit()
                flash(f"{len(ids)} Beleg(e) als weiterverrechnet markiert.", "ok")
            return redirect(url_for("eingang.fremdkosten"))
        try:
            aufschlag = int(request.form.get("aufschlag") or 0)
        except ValueError:
            raise FachFehler("Aufschlag bitte als ganze Zahl in Prozent angeben.") from None
        ar_id = fremdkosten_verrechnen(con, ids, aufschlag_prozent=aufschlag)
        con.commit()
        flash("Ausgangsrechnung aus Fremdkosten erstellt – bitte prüfen und ergänzen.", "ok")
        return redirect(url_for("ausgang.bearbeiten", rechnung_id=ar_id))
    gruppen = {}
    for z in aw.offene_fremdkosten(con):
        gruppen.setdefault((z["weiter_kunde_id"], z["kunde_name"]), []).append(z)
    return render_template("fremdkosten.html", gruppen=gruppen)


# ------------------------------------------------------------------- Kunden

@kunden.route("/")
def liste():
    con = get_db()
    zeilen = con.execute(
        """SELECT k.*, COUNT(ar.id) AS anzahl, COALESCE(SUM(ar.netto_cent), 0) AS netto, MAX(ar.datum) AS zuletzt,
                  COALESCE(SUM(CASE WHEN ar.bezahlt = 0 AND ar.storniert = 0 AND ar.storno_von_id IS NULL
                                    THEN ar.brutto_cent END), 0) AS offen
           FROM kunden k LEFT JOIN ausgangsrechnungen ar ON ar.kunde_id = k.id
           GROUP BY k.id ORDER BY zuletzt IS NULL, zuletzt DESC"""
    ).fetchall()
    return render_template("kunden_liste.html", zeilen=zeilen)


@kunden.route("/<int:kunde_id>", methods=["GET", "POST"])
def bearbeiten(kunde_id):
    con = get_db()
    if request.method == "POST":
        f = request.form
        ziel = f.get("zahlungsziel_tage", "").strip()
        name = " ".join(f.get("name", "").split())
        if not name:
            raise FachFehler("Der Name darf nicht leer sein.")
        andere = con.execute("SELECT id FROM kunden WHERE name = ? COLLATE NOCASE AND id != ?", (name, kunde_id)).fetchone()
        if andere:
            raise FachFehler("Es gibt bereits einen Kunden mit diesem Namen – bitte „Zusammenführen“ verwenden.")
        con.execute(
            "UPDATE kunden SET name = ?, adresse = ?, uid = ?, email = ?, zahlungsziel_tage = ?, notiz = ? WHERE id = ?",
            (name, f.get("adresse", "").strip(), f.get("uid", "").strip(), f.get("email", "").strip(),
             int(ziel) if ziel.isdigit() else None, f.get("notiz", "").strip(), kunde_id),
        )
        con.commit()
        flash("Kunde gespeichert.", "ok")
        return redirect(url_for("kunden.bearbeiten", kunde_id=kunde_id))
    k = con.execute("SELECT * FROM kunden WHERE id = ?", (kunde_id,)).fetchone()
    if k is None:
        raise FachFehler("Kunde nicht gefunden.")
    rechnungen = con.execute(
        "SELECT * FROM ausgangsrechnungen WHERE kunde_id = ? ORDER BY datum DESC, nummer DESC", (kunde_id,)
    ).fetchall()
    andere = con.execute("SELECT id, name FROM kunden WHERE id != ? ORDER BY name COLLATE NOCASE", (kunde_id,)).fetchall()
    return render_template("kunde.html", k=k, rechnungen=rechnungen, andere=andere)


@kunden.route("/<int:kunde_id>/zusammenfuehren", methods=["POST"])
def zusammenfuehren(kunde_id):
    con = get_db()
    nach = int(request.form["nach_id"])
    kunden_zusammenfuehren(con, kunde_id, nach)
    con.commit()
    flash("Kunden zusammengeführt.", "ok")
    return redirect(url_for("kunden.bearbeiten", kunde_id=nach))


# --------------------------------------------------------------- Auswertungen

@berichte.route("/offene-posten")
def offene_posten():
    con = get_db()
    forderungen = aw.offene_forderungen(con)
    verbindlichkeiten = aw.offene_verbindlichkeiten(con)
    return render_template(
        "offene_posten.html", forderungen=forderungen, verbindlichkeiten=verbindlichkeiten,
        summe_f=sum(f["brutto_cent"] for f in forderungen), summe_v=sum(v["brutto_cent"] for v in verbindlichkeiten),
        heute=heute().isoformat(),
    )


@berichte.route("/uva")
def uva():
    con = get_db()
    jahr = _jahr()
    art = request.args.get("art", "monat")
    if art not in ("monat", "quartal", "jahr"):
        art = "monat"
    # Standard: der zuletzt abgeschlossene Monat bzw. das zuletzt abgeschlossene Quartal
    standard = max(1, heute().month - 1) if art == "monat" else max(1, (heute().month - 1) // 3)
    try:
        nr = int(request.args.get("nr", standard))
    except ValueError:
        nr = standard
    nr = max(1, min(nr, 12 if art == "monat" else 4))
    von, bis, name = aw.zeitraum(jahr, art, nr)
    # Übersicht aller Perioden des Jahres
    perioden = []
    for i in range(1, (12 if art == "monat" else 4 if art == "quartal" else 1) + 1):
        v, b, n = aw.zeitraum(jahr, art, i)
        perioden.append((i, n, aw.uva(con, v, b)))
    return render_template("uva.html", jahr=jahr, art=art, nr=nr, name=name, daten=aw.uva(con, von, bis),
                           perioden=perioden, jahre=aw.verfuegbare_jahre(con), von=von, bis=bis)


@berichte.route("/umsatz")
def umsatz():
    con = get_db()
    jahr = _jahr()
    jahre = [j for j in sorted(aw.verfuegbare_jahre(con)) if j <= jahr][-5:]
    je_monat = aw.umsatz_je_monat(con, jahre)
    weiter, intern = aw.fremdkosten_je_monat(con, jahr)
    return render_template(
        "umsatz.html", jahr=jahr, jahre=jahre, alle_jahre=aw.verfuegbare_jahre(con), je_monat=je_monat,
        kosten=aw.kosten_je_monat(con, jahr), weiter=weiter, intern=intern, monate=MONATE,
        kunden=aw.umsatz_je_kunde(con, jahr), projekte=aw.umsatz_je_projekt(con, jahr),
        diagramm=_diagramm(je_monat, jahr),
    )


@berichte.route("/export/<int:jahr>.xlsx")
def export(jahr):
    inhalt = jahr_exportieren(get_db(), jahr)
    return Response(inhalt, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="Buchhaltung_{jahr}.xlsx"'})


# ------------------------------------------------------- Einstellungen / Import

@verwaltung.route("/einstellungen", methods=["GET", "POST"])
def einstellungen_seite():
    con = get_db()
    werte = einstellungen(con)
    if request.method == "POST":
        for schluessel in werte:
            if schluessel in request.form:
                con.execute("UPDATE einstellungen SET wert = ? WHERE schluessel = ?",
                            (request.form[schluessel].strip(), schluessel))
        con.commit()
        flash("Einstellungen gespeichert.", "ok")
        return redirect(url_for("verwaltung.einstellungen_seite"))
    return render_template("einstellungen.html", w=werte)


@verwaltung.route("/datensicherung")
def datensicherung():
    """ZIP mit konsistenter Kopie der Datenbank und allen Belegen."""
    puffer = BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        kopie = Path(tmp) / "buchhaltung.db"
        ziel = sqlite3.connect(kopie)
        get_db().backup(ziel)
        ziel.close()
        with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(kopie, "buchhaltung.db")
            belege = Path(current_app.config["BELEGE"])
            for datei in sorted(belege.rglob("*")):
                if datei.is_file():
                    zf.write(datei, f"belege/{datei.relative_to(belege).as_posix()}")
    name = f"Buchhaltung-Sicherung-{heute().isoformat()}.zip"
    return Response(puffer.getvalue(), mimetype="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@verwaltung.route("/import", methods=["GET", "POST"])
def import_seite():
    con = get_db()
    bericht = None
    if request.method == "POST":
        datei = request.files.get("datei")
        if not datei or not datei.filename.lower().endswith(".xlsx"):
            raise FachFehler("Bitte eine .xlsx-Datei auswählen.")
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "import.xlsx"
            datei.save(pfad)
            bericht = importieren(con, pfad)
    leer = con.execute("SELECT COUNT(*) AS n FROM ausgangsrechnungen").fetchone()["n"] == 0
    return render_template("import.html", bericht=bericht, leer=leer)
