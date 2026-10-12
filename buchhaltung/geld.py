"""Hilfsfunktionen für Geldbeträge (in Cent) und Datumswerte."""
import re
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

UST_SAETZE = (20, 13, 10, 0)

MONATE = (
    "Jänner", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def runden(wert):
    """Kaufmännisch auf ganze Cent runden (Decimal → int)."""
    return int(Decimal(wert).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def euro_zu_cent(wert):
    """Wandelt 1234.5 / '1.234,50' / '1234,5' / '-12' in Cent um. Leer → None."""
    if wert is None:
        return None
    if isinstance(wert, (int, float)):
        return runden(Decimal(str(wert)) * 100)
    text = str(wert).strip().replace("€", "").replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        # deutsches Format: Punkte sind Tausendertrennzeichen
        text = text.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        return runden(Decimal(text) * 100)
    except InvalidOperation:
        raise ValueError(f"Ungültiger Betrag: {wert!r}") from None


def cent_zu_euro_text(cent, mit_waehrung=True):
    """12345 → '123,45 €' (österreichische Schreibweise)."""
    if cent is None:
        return ""
    negativ = cent < 0
    euro, rest = divmod(abs(int(cent)), 100)
    text = f"{euro:,}".replace(",", ".") + f",{rest:02d}"
    if negativ:
        text = "-" + text
    return text + (" €" if mit_waehrung else "")


def cent_zu_eingabe(cent):
    """Wert für Formularfelder: 12345 → '123,45'."""
    if cent is None:
        return ""
    return cent_zu_euro_text(cent, mit_waehrung=False).replace(".", "")


def ust_von_netto(netto_cent, satz):
    return runden(Decimal(netto_cent) * satz / 100)


def netto_von_brutto(brutto_cent, satz):
    return runden(Decimal(brutto_cent) * 100 / (100 + satz))


def datum_parsen(wert):
    """Akzeptiert date/datetime, 'JJJJ-MM-TT' und 'TT.MM.JJJJ'. Leer → None."""
    if wert is None or wert == "":
        return None
    if isinstance(wert, datetime):
        return wert.date()
    if isinstance(wert, date):
        return wert
    text = str(wert).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Ungültiges Datum: {wert!r}")


def datum_text(iso):
    """'2026-10-12' → '12.10.2026'."""
    if not iso:
        return ""
    d = datum_parsen(iso)
    return d.strftime("%d.%m.%Y")


def plus_tage(iso, tage):
    return (datum_parsen(iso) + timedelta(days=tage)).isoformat()


def heute():
    return date.today()
