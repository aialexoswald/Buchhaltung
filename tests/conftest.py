import pytest

from buchhaltung import create_app
from buchhaltung.db import initialisieren, verbinden


@pytest.fixture
def con(tmp_path):
    c = verbinden(str(tmp_path / "test.db"))
    initialisieren(c)
    yield c
    c.close()


@pytest.fixture
def app(tmp_path):
    return create_app({"DATENVERZEICHNIS": tmp_path, "TESTING": True, "SECRET_KEY": "test"})


@pytest.fixture
def client(app):
    c = app.test_client()
    c.get("/ausgang/neu")  # Formularseite legt das CSRF-Token in der Sitzung an
    with c.session_transaction() as s:
        c.token = s["csrf_token"]
    return c
