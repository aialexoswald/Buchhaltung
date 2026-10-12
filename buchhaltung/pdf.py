"""Erzeugt Rechnungen als PDF (reportlab)."""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .geld import cent_zu_euro_text, datum_text
from .logik import ar_steuersaetze

GRAU = colors.HexColor("#5b6470")
LINIE = colors.HexColor("#c9ced6")


def _absatz(text):
    """Zeilenumbrüche erhalten, HTML-Sonderzeichen maskieren."""
    return "<br/>".join(escape(z) for z in (text or "").splitlines())


def _menge(m):
    return f"{m:g}".replace(".", ",")


def rechnung_pdf(rechnung, positionen, firma):
    puffer = BytesIO()
    stile = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=stile["Normal"], fontName="Helvetica", fontSize=9.5, leading=13)
    klein = ParagraphStyle("k", parent=normal, fontSize=7.5, leading=10, textColor=GRAU)
    rechts = ParagraphStyle("r", parent=normal, alignment=TA_RIGHT)
    titel = ParagraphStyle("t", parent=normal, fontName="Helvetica-Bold", fontSize=16, leading=20)

    def fusszeile(canvas, doc):
        teile = [firma.get("firma_name", ""), firma.get("firma_adresse", "").replace("\n", ", ")]
        if firma.get("firma_uid"):
            teile.append(f"UID {firma['firma_uid']}")
        if firma.get("firma_firmenbuch"):
            teile.append(firma["firma_firmenbuch"])
        zeile2 = [x for x in (firma.get("bank_name"), firma.get("bank_iban") and f"IBAN {firma['bank_iban']}",
                              firma.get("bank_bic") and f"BIC {firma['bank_bic']}") if x]
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRAU)
        canvas.drawCentredString(A4[0] / 2, 14 * mm, " · ".join(t for t in teile if t))
        canvas.drawCentredString(A4[0] / 2, 10 * mm, " · ".join(zeile2))
        canvas.drawRightString(A4[0] - 20 * mm, 287 * mm, f"Seite {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        puffer, pagesize=A4, leftMargin=22 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=25 * mm,
        title=f"Rechnung {rechnung['nummer']}", author=firma.get("firma_name", ""),
    )
    inhalt = []
    # Der Rahmen hat 6 pt Innenabstand je Seite; Spaltenbreiten (in mm, Summe 168) darauf skalieren
    faktor = (doc.width - 12) / (168 * mm)

    def spalten(*werte):
        return [w * mm * faktor for w in werte]

    absender_kopf = Paragraph(
        f"<b>{escape(firma.get('firma_name', ''))}</b><br/>{_absatz(firma.get('firma_adresse', ''))}"
        + "".join(f"<br/>{escape(firma[k])}" for k in ("firma_telefon", "firma_email", "firma_web") if firma.get(k)),
        rechts,
    )
    inhalt.append(Table([[None, absender_kopf]], colWidths=spalten(100, 68),
                        style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    inhalt.append(Spacer(1, 6 * mm))

    absender_zeile = Paragraph(
        escape(" · ".join(x for x in (firma.get("firma_name", ""),
                                      firma.get("firma_adresse", "").replace("\n", ", ")) if x)), klein)
    empfaenger = Paragraph(f"{escape(rechnung['kunde_name'])}<br/>{_absatz(rechnung['kunde_adresse'])}", normal)
    daten = [
        ["Rechnungsnummer", rechnung["nummer"]],
        ["Rechnungsdatum", datum_text(rechnung["datum"])],
    ]
    if rechnung["leistungszeitraum"]:
        daten.append(["Leistungszeitraum", rechnung["leistungszeitraum"]])
    if rechnung["kunde_uid"]:
        daten.append(["Ihre UID", rechnung["kunde_uid"]])
    if rechnung["projekt"]:
        daten.append(["Projekt", rechnung["projekt"]])
    datenblock = Table(
        [[Paragraph(escape(a), klein), Paragraph(escape(b), normal)] for a, b in daten],
        colWidths=spalten(30, 42),
        style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
               ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)],
    )
    inhalt.append(Table(
        [[[absender_zeile, Spacer(1, 2 * mm), empfaenger], datenblock]],
        colWidths=spalten(96, 72),
        style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)],
    ))
    inhalt.append(Spacer(1, 14 * mm))

    ist_storno = bool(rechnung["storno_von_id"])
    inhalt.append(Paragraph("Stornorechnung" if ist_storno else "Rechnung", titel))
    inhalt.append(Spacer(1, 3 * mm))
    if ist_storno:
        inhalt.append(Paragraph(f"Storno zu Rechnung {escape(rechnung['storno_von_nummer'] or '')}.", normal))
    elif firma.get("rechnung_einleitung"):
        inhalt.append(Paragraph(_absatz(firma["rechnung_einleitung"]), normal))
    inhalt.append(Spacer(1, 5 * mm))

    kopf = ["Pos.", "Beschreibung", "Menge", "Einzelpreis", "USt", "Betrag"]
    zeilen = [kopf]
    for p in positionen:
        menge = _menge(p["menge"]) + (f" {p['einheit']}" if p["einheit"] else "")
        zeilen.append([
            str(p["pos"]), Paragraph(_absatz(p["beschreibung"]), normal), menge,
            cent_zu_euro_text(p["einzelpreis_cent"]), f"{p['ust_satz']} %", cent_zu_euro_text(p["netto_cent"]),
        ])
    tabelle = Table(zeilen, colWidths=spalten(11, 72, 20, 24, 13, 28), repeatRows=1)
    tabelle.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), GRAU),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINIE),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
    ]))
    inhalt.append(tabelle)
    inhalt.append(Spacer(1, 4 * mm))

    summen = [["Summe netto", cent_zu_euro_text(rechnung["netto_cent"])]]
    for satz, (netto, ust) in ar_steuersaetze(positionen).items():
        if satz:
            summen.append([f"zzgl. {satz} % USt von {cent_zu_euro_text(netto)}", cent_zu_euro_text(ust)])
    summen.append(["Gesamtbetrag", cent_zu_euro_text(rechnung["brutto_cent"])])
    summentabelle = Table(summen, colWidths=spalten(70, 28), hAlign="RIGHT")
    summentabelle.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 10.5),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
    ]))
    inhalt.append(summentabelle)
    inhalt.append(Spacer(1, 8 * mm))

    if rechnung["steuerhinweis"]:
        inhalt.append(Paragraph(_absatz(rechnung["steuerhinweis"]), normal))
        inhalt.append(Spacer(1, 3 * mm))
    if not ist_storno and rechnung["brutto_cent"] > 0:
        zahlung = f"Bitte überweisen Sie den Betrag bis {datum_text(rechnung['faellig_am'])} ohne Abzug"
        if firma.get("bank_iban"):
            zahlung += f" auf unser Konto IBAN {escape(firma['bank_iban'])}"
            if firma.get("bank_bic"):
                zahlung += f", BIC {escape(firma['bank_bic'])}"
        zahlung += f", unter Angabe der Rechnungsnummer {escape(rechnung['nummer'])}."
        inhalt.append(Paragraph(zahlung, normal))
        inhalt.append(Spacer(1, 3 * mm))
    if firma.get("rechnung_fusstext"):
        inhalt.append(Paragraph(_absatz(firma["rechnung_fusstext"]), normal))

    doc.build(inhalt, onFirstPage=fusszeile, onLaterPages=fusszeile)
    return puffer.getvalue()
