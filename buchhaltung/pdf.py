"""Erzeugt Rechnungen als PDF im Futura-Layout (reportlab).

Aufbau nach der bisherigen Word-Vorlage: Logo rechts oben, Zeile „An … Faktura_N° … Datum“,
Empfänger, „_RECHNUNG“, Auftraggeber-UID, Betreff (fett), Leistungszeitraum,
Positionen mit „netto EUR“, Summenblock, Zahlungstext, Fußzeile mit orangen Bezeichnungen.
"""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .geld import cent_zu_euro_text, datum_parsen, datum_text
from .logik import ar_steuersaetze

STATIC = Path(__file__).with_name("static")
ORANGE = colors.HexColor("#FAB535")
TEXT = colors.HexColor("#1a1a1a")
LEICHT, KRAEFTIG = "Jost-Light", "Jost-Medium"


def _schriften_registrieren():
    if LEICHT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(LEICHT, str(STATIC / "schrift" / "Jost-Light.ttf")))
        pdfmetrics.registerFont(TTFont(KRAEFTIG, str(STATIC / "schrift" / "Jost-Medium.ttf")))


def _absatz(text):
    """Zeilenumbrüche erhalten, HTML-Sonderzeichen maskieren."""
    return "<br/>".join(escape(z) for z in (text or "").splitlines())


def _betrag(cent):
    return cent_zu_euro_text(cent, mit_waehrung=False)


def _menge(m):
    return f"{m:g}".replace(".", ",")


def laufnummer(nummer):
    """'2026_100' → '100', '2026_007' → '7'."""
    teil = nummer.split("_", 1)[-1]
    return str(int(teil)) if teil.isdigit() else teil


def dateiname(rechnung):
    """Wie bisher: 100_Futura_RE_2026.pdf"""
    jahr = rechnung["nummer"].split("_", 1)[0]
    return f"{laufnummer(rechnung['nummer'])}_Futura_RE_{jahr}.pdf"


def logo_pfad(datenverzeichnis):
    """Eigenes Logo aus dem Datenordner, sonst das mitgelieferte Futura-Logo."""
    for endung in ("png", "jpg", "jpeg"):
        eigenes = Path(datenverzeichnis) / f"logo.{endung}"
        if eigenes.exists():
            return eigenes
    return STATIC / "logo.png"


def rechnung_pdf(rechnung, positionen, firma, logo=None):
    _schriften_registrieren()
    puffer = BytesIO()
    normal = ParagraphStyle("n", fontName=LEICHT, fontSize=11, leading=15, textColor=TEXT)
    fett = ParagraphStyle("f", parent=normal, fontName=KRAEFTIG)
    rechts = ParagraphStyle("r", parent=normal, alignment=TA_RIGHT)
    fett_rechts = ParagraphStyle("fr", parent=fett, alignment=TA_RIGHT)
    fuss = ParagraphStyle("fu", parent=normal, fontSize=7.5, leading=9.5, alignment=TA_CENTER)
    orange = ORANGE.hexval().replace("0x", "#")

    def o(text):
        return f'<font color="{orange}">{escape(text)}</font>'

    def fusszeile(canvas, doc):
        adresse = ", ".join(z.strip() for z in firma.get("firma_adresse", "").splitlines() if z.strip())
        zeile1 = o(firma.get("firma_name", "").upper()) + (f", {escape(adresse)}" if adresse else "")
        if firma.get("firma_zweigstelle"):
            zeile1 += f" {o('Zweigstelle:')} {escape(firma['firma_zweigstelle'])}"
        zeile2 = " ".join(f"{o(label)} {escape(firma[k])}" for k, label in
                          (("firma_firmenbuch", "FN:"), ("firma_wko", "WKO Mitgl.Nr.")) if firma.get(k))
        zeile3 = " ".join(f"{o(label)} {escape(firma[k])}" for k, label in
                          (("firma_uid", "UID:"), ("bank_iban", "IBAN:"), ("bank_bic", "BIC:")) if firma.get(k))
        if firma.get("bank_name"):
            zeile3 += f" {escape(firma['bank_name'])}"
        kontakt = " ".join(f"{o(label)} {escape(firma[k])}" for k, label in
                           (("firma_telefon", "Tel.:"), ("firma_email", "E-Mail:"), ("firma_web", "Web:")) if firma.get(k))
        text = "<br/>".join(z for z in (zeile1, zeile2, zeile3, kontakt) if z)
        absatz = Paragraph(text, fuss)
        _, hoehe = absatz.wrap(doc.width, 30 * mm)
        absatz.drawOn(canvas, doc.leftMargin, 12 * mm)
        if doc.page > 1:
            canvas.saveState()
            canvas.setFont(LEICHT, 8)
            canvas.drawRightString(A4[0] - doc.rightMargin, A4[1] - 12 * mm, f"Seite {doc.page}")
            canvas.restoreState()

    def logo_zeichnen(canvas, doc):
        if logo and Path(logo).exists():
            bild = ImageReader(str(logo))
            b, h = bild.getSize()
            breite = 37.5 * mm
            canvas.drawImage(bild, 147.5 * mm, A4[1] - 13 * mm - breite * h / b,
                             width=breite, height=breite * h / b, mask="auto")
        fusszeile(canvas, doc)

    doc = SimpleDocTemplate(
        puffer, pagesize=A4, leftMargin=23 * mm, rightMargin=24 * mm, topMargin=37.5 * mm, bottomMargin=30 * mm,
        title=f"Rechnung {rechnung['nummer']}", author=firma.get("firma_name", ""),
    )
    breite = doc.width - 12  # Rahmen hat 6 pt Innenabstand je Seite
    ohne_rand = [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                 ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                 ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]
    inhalt = []

    # „An“ – Rechnungsnummer – Datum
    inhalt.append(Table(
        [[Paragraph("An", normal), Paragraph(f"Faktura_N°{escape(laufnummer(rechnung['nummer']))}", normal),
          Paragraph(datum_text(rechnung["datum"]), rechts)]],
        colWidths=[breite - 59 * mm, 37 * mm, 22 * mm], style=ohne_rand,
    ))
    inhalt.append(Spacer(1, 5 * mm))
    inhalt.append(Paragraph(f"{escape(rechnung['kunde_name'])}<br/>{_absatz(rechnung['kunde_adresse'])}", normal))
    inhalt.append(Spacer(1, 13 * mm))

    ist_storno = bool(rechnung["storno_von_id"])
    inhalt.append(Paragraph("_STORNORECHNUNG" if ist_storno else "_RECHNUNG", fett))
    inhalt.append(Spacer(1, 10 * mm))
    if rechnung["kunde_uid"]:
        inhalt.append(Paragraph(f"Auftraggeber:&nbsp; {escape(rechnung['kunde_uid'])}", normal))
        inhalt.append(Spacer(1, 4 * mm))
    if ist_storno:
        inhalt.append(Paragraph(f"Storno zu Faktura_N°{escape(laufnummer(rechnung['storno_von_nummer'] or ''))}", normal))
        inhalt.append(Spacer(1, 3 * mm))
    betreff = rechnung["betreff"] or rechnung["projekt"]
    if betreff:
        inhalt.append(Paragraph(escape(betreff), fett))
        inhalt.append(Spacer(1, 3.5 * mm))
    if rechnung["leistungszeitraum"]:
        inhalt.append(Paragraph(f"Leistungszeitraum {escape(rechnung['leistungszeitraum'])}", normal))
        inhalt.append(Spacer(1, 3.5 * mm))
    if firma.get("rechnung_einleitung"):
        inhalt.append(Paragraph(_absatz(firma["rechnung_einleitung"]), normal))
        inhalt.append(Spacer(1, 3.5 * mm))

    # Positionen: Text links, „netto EUR“ + Betrag rechts
    # wie in der Vorlage: Beträge enden etwa 9 mm vor dem rechten Rand der Datumszeile
    spalten = [breite - 49 * mm, 23 * mm, 17 * mm]
    zeilen = []
    for p in positionen:
        text = _absatz(p["beschreibung"])
        if p["menge"] != 1 or p["einheit"]:
            text += (f'<br/><font size="9">{_menge(p["menge"])} {escape(p["einheit"])} à '
                     f'{_betrag(p["einzelpreis_cent"])} EUR</font>')
        if p["ust_satz"] == 0 and any(x["ust_satz"] for x in positionen):
            text += '<font size="9"> (ohne MwSt)</font>'
        zeilen.append([Paragraph(text, normal), Paragraph("netto EUR", normal),
                       Paragraph(_betrag(p["netto_cent"]), rechts)])
    zeilen.append([Spacer(1, 2 * mm), "", ""])
    zeilen.append([Paragraph("Total netto", normal), Paragraph("netto EUR", normal),
                   Paragraph(_betrag(rechnung["netto_cent"]), rechts)])
    for satz, (_, ust) in ar_steuersaetze(positionen).items():
        if satz:
            zeilen.append(["", Paragraph(f"{satz}% MwSt", normal), Paragraph(_betrag(ust), rechts)])
    zeilen.append([Paragraph("_Gesamt", fett), Paragraph("brutto EUR", fett),
                   Paragraph(_betrag(rechnung["brutto_cent"]), fett_rechts)])
    tabelle = Table(zeilen, colWidths=spalten, hAlign="LEFT")
    tabelle.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, -1), (-1, -1), 8),
    ]))
    inhalt.append(tabelle)
    inhalt.append(Spacer(1, 8 * mm))

    if rechnung["steuerhinweis"]:
        inhalt.append(Paragraph(_absatz(rechnung["steuerhinweis"]), normal))
        inhalt.append(Spacer(1, 3 * mm))
    if not ist_storno and rechnung["brutto_cent"] > 0 and firma.get("rechnung_zahlungstext"):
        faellig = datum_parsen(rechnung["faellig_am"]) if rechnung["faellig_am"] else None
        text = firma["rechnung_zahlungstext"].replace("{faellig}", faellig.strftime("%d.%m.%Y") if faellig else "")
        inhalt.append(Paragraph(_absatz(text), normal))
        inhalt.append(Spacer(1, 3 * mm))
    if firma.get("rechnung_fusstext"):
        inhalt.append(Paragraph(_absatz(firma["rechnung_fusstext"]), normal))

    doc.build(inhalt, onFirstPage=logo_zeichnen, onLaterPages=fusszeile)
    return puffer.getvalue()
