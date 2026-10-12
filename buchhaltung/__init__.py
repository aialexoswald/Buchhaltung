"""Buchhaltung – Verwaltung von Ausgangs- und Eingangsrechnungen."""
import os
import secrets
from pathlib import Path

from flask import Flask, abort, redirect, request, session, url_for

from . import db
from .geld import cent_zu_eingabe, cent_zu_euro_text, datum_text, heute


def create_app(konfiguration=None):
    app = Flask(__name__)
    daten = Path(os.environ.get("BUCHHALTUNG_DATEN", Path.cwd() / "data"))
    app.config.update(
        DATENVERZEICHNIS=daten,
        DATENBANK=str(daten / "buchhaltung.db"),
        BELEGE=daten / "belege",
        PASSWORT=os.environ.get("BUCHHALTUNG_PASSWORT", ""),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    )
    if konfiguration:
        app.config.update(konfiguration)
        if "DATENVERZEICHNIS" in konfiguration:
            basis = Path(konfiguration["DATENVERZEICHNIS"])
            app.config["DATENBANK"] = konfiguration.get("DATENBANK", str(basis / "buchhaltung.db"))
            app.config["BELEGE"] = konfiguration.get("BELEGE", basis / "belege")
    Path(app.config["DATENVERZEICHNIS"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["BELEGE"]).mkdir(parents=True, exist_ok=True)
    app.secret_key = app.config.get("SECRET_KEY") or _geheimschluessel(Path(app.config["DATENVERZEICHNIS"]))

    con = db.verbinden(app.config["DATENBANK"])
    db.initialisieren(con)
    con.close()
    app.teardown_appcontext(db.schliessen)

    app.jinja_env.filters["euro"] = cent_zu_euro_text
    app.jinja_env.filters["eingabe"] = cent_zu_eingabe
    app.jinja_env.filters["datum"] = datum_text
    app.jinja_env.globals["csrf_token"] = _csrf_token
    app.jinja_env.globals["heute_iso"] = lambda: heute().isoformat()

    @app.before_request
    def schutz():
        if request.endpoint in ("static", "login"):
            return None
        if app.config["PASSWORT"] and not session.get("angemeldet"):
            return redirect(url_for("login", weiter=request.path))
        if request.method == "POST" and request.form.get("csrf_token") != session.get("csrf_token"):
            abort(400, "Formular abgelaufen – bitte Seite neu laden.")
        return None

    from .ansichten import registrieren
    registrieren(app)
    return app


def _csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(24)
    return session["csrf_token"]


def _geheimschluessel(verzeichnis):
    if os.environ.get("BUCHHALTUNG_SECRET"):
        return os.environ["BUCHHALTUNG_SECRET"]
    datei = verzeichnis / ".secret_key"
    if not datei.exists():
        datei.write_text(secrets.token_hex(32))
    return datei.read_text().strip()
