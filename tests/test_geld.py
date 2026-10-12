import pytest

from buchhaltung.geld import cent_zu_euro_text, euro_zu_cent, netto_von_brutto, ust_von_netto


@pytest.mark.parametrize("eingabe, cent", [
    ("1.234,56", 123456), ("1234,5", 123450), ("1234.56", 123456), ("1.234", 123400),
    ("-12", -1200), ("12 €", 1200), (99.995, 10000), (1042.5, 104250), ("", None), (None, None),
])
def test_euro_zu_cent(eingabe, cent):
    assert euro_zu_cent(eingabe) == cent


def test_ungueltiger_betrag():
    with pytest.raises(ValueError):
        euro_zu_cent("abc")


def test_formatierung():
    assert cent_zu_euro_text(123456789) == "1.234.567,89 €"
    assert cent_zu_euro_text(-5) == "-0,05 €"


def test_steuer():
    assert ust_von_netto(104250, 20) == 20850
    assert netto_von_brutto(12000, 20) == 10000
    assert netto_von_brutto(11000, 10) == 10000
