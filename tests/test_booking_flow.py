"""Buchungsablauf: kurs_waehlen -> daten -> verbindlich (gemockter HTTP-Client)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hochschulsport_cli import prompts
from hochschulsport_cli.booking import BookingCredentials, submit_booking
from hochschulsport_cli.cli import main
from hochschulsport_cli.errors import ParseError, UsageError
from hochschulsport_cli.models import STATUS_BOOKABLE, Course, Price
from hochschulsport_cli.portals import Portal

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "ux"
PORTAL = Portal(id="test", name="Testportal", base_url="http://127.0.0.1:8765")


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FlowClient:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = list(responses or [])
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, str]]] = []

    def get_text(self, url: str, *, portal: str | None = None) -> str:
        self.get_calls.append(url)
        return _fixture("volleyball.html")

    def post_form(
        self, url: str, data: dict[str, str], *, portal: str | None = None
    ) -> str:
        self.post_calls.append((url, dict(data)))
        if not self.responses:
            raise AssertionError("unerwarteter POST ohne vorbereitete Antwort")
        return self.responses.pop(0)


def _credentials(**overrides) -> BookingCredentials:
    values = {
        "login_user": "max@example.org",
        "login_password": "geheim",
        "status_group": "Studierende",
        "first_name": "Max",
        "last_name": "Beispiel",
        "email": "max@example.org",
    }
    values.update(overrides)
    return BookingCredentials(**values)


def _course() -> Course:
    return Course(
        course_nr="32304",
        title="Volleyball LS3 hohes Spielniveau / Advanced",
        sport="Volleyball",
        day="Mi",
        time="19:30-21:30",
        location="Sporthalle Allmandring",
        prices=[Price("Studierende", 45.0)],
        booking_status=STATUS_BOOKABLE,
    )


def _submit(client: FlowClient, credentials: BookingCredentials | None = None):
    return submit_booking(
        PORTAL,
        client,
        sport_name="Volleyball",
        course_nr="32304",
        booking_status=STATUS_BOOKABLE,
        credentials=credentials or _credentials(),
    )


def test_alle_drei_posts_in_reihenfolge_und_mit_feldern():
    client = FlowClient(
        [
            _fixture("step1_formular.html"),
            _fixture("step2_uebersicht.html"),
            _fixture("step3_bestaetigt.html"),
        ]
    )

    result = _submit(client)

    assert result["submitted"] is True
    assert result["confirmed"] is True
    assert result["steps"] == ["kurs_waehlen", "daten", "verbindlich"]
    assert len(client.post_calls) == 3
    assert [url for url, _ in client.post_calls] == [
        "http://127.0.0.1:8765/cgi/anmeldung.fcgi"
    ] * 3

    first = client.post_calls[0][1]
    assert any(name.startswith("BS_Kursid_") for name in first)
    assert first["BS_Code"] == "DUMMY"

    second = client.post_calls[1][1]
    assert second["statusorig"] == "1"
    assert second["vorname"] == "Max"
    assert second["name"] == "Beispiel"
    assert second["email"] == "max@example.org"
    assert second["tnbed"] == "1"
    assert second["BS_Code"] == "DUMMY"
    assert second["BS_Kursid_31584"] == "32304"

    third = client.post_calls[2][1]
    assert third["fid"] == "DUMMY-FID"
    assert third["BS_Verbindlich"] == "verbindlich buchen"


def test_fehlendes_pflichtfeld_sendet_kein_daten_post():
    client = FlowClient([_fixture("step1_formular.html")])

    with pytest.raises(UsageError) as exc:
        _submit(client, _credentials(email=None))

    assert "email" in exc.value.message
    assert "hsport login" in exc.value.message
    assert len(client.post_calls) == 1
    assert exc.value.extra["confirmed"] is False
    assert exc.value.extra["step"] == "daten"


def test_unbekannte_antwort_nach_verbindlich_ist_fehler():
    client = FlowClient(
        [
            _fixture("step1_formular.html"),
            _fixture("step2_uebersicht.html"),
            "<html><body>Unbekannte Seite ohne Bestätigung</body></html>",
        ]
    )

    with pytest.raises(ParseError) as exc:
        _submit(client)

    assert "bestätigt" not in exc.value.message
    assert exc.value.extra["confirmed"] is False
    assert exc.value.extra["step"] == "verbindlich"
    assert exc.value.extra["steps"] == ["kurs_waehlen", "daten", "verbindlich"]
    assert len(client.post_calls) == 3


def test_cli_antwort_n_sendet_keinen_formularschritt(monkeypatch, capsys):
    client = FlowClient()
    monkeypatch.setattr("hochschulsport_cli.cli.HttpClient", lambda *a, **k: client)
    monkeypatch.setattr(
        "hochschulsport_cli.cli.load_courses_for_sport",
        lambda portal, http, name: [_course()],
    )
    monkeypatch.setattr(prompts, "is_tty", lambda: True)
    monkeypatch.setattr(prompts, "confirm", lambda question, *, default=False: False)
    monkeypatch.setenv("HS_LOGIN_USER", "max@example.org")
    monkeypatch.setenv("HS_LOGIN_PASSWORD", "geheim")
    monkeypatch.setenv("HS_STATUSGRUPPE", "Studierende")
    monkeypatch.setenv("HSPORT_FIRSTNAME", "Max")
    monkeypatch.setenv("HSPORT_LASTNAME", "Beispiel")
    monkeypatch.setenv("HS_BOOKING_EMAIL", "max@example.org")

    assert main(["book", "volleyball"]) == 0
    out = capsys.readouterr().out
    assert "Abgebrochen, nichts gebucht." in out
    assert client.post_calls == []
    assert client.get_calls == []


def test_cli_json_erfolg_mit_bestaetigung(monkeypatch, capsys):
    client = FlowClient(
        [
            _fixture("step1_formular.html"),
            _fixture("step2_uebersicht.html"),
            _fixture("step3_bestaetigt.html"),
        ]
    )
    monkeypatch.setattr("hochschulsport_cli.cli.HttpClient", lambda *a, **k: client)
    monkeypatch.setattr(
        "hochschulsport_cli.cli.load_courses_for_sport",
        lambda portal, http, name: [_course()],
    )
    monkeypatch.setattr(prompts, "is_tty", lambda: False)
    for key, value in {
        "HS_LOGIN_USER": "max@example.org",
        "HS_LOGIN_PASSWORD": "geheim",
        "HS_STATUSGRUPPE": "Studierende",
        "HSPORT_FIRSTNAME": "Max",
        "HSPORT_LASTNAME": "Beispiel",
        "HS_BOOKING_EMAIL": "max@example.org",
    }.items():
        monkeypatch.setenv(key, value)

    assert main(["book", "volleyball", "--confirm", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["submitted"] is True
    assert payload["confirmed"] is True
    assert payload["steps"] == ["kurs_waehlen", "daten", "verbindlich"]
    assert payload["buchungsnummer"] is None


def test_cli_json_fehler_nennt_schritt_und_confirmed_false(monkeypatch, capsys):
    client = FlowClient([_fixture("step1_formular.html")])
    monkeypatch.setattr("hochschulsport_cli.cli.HttpClient", lambda *a, **k: client)
    monkeypatch.setattr(
        "hochschulsport_cli.cli.load_courses_for_sport",
        lambda portal, http, name: [_course()],
    )
    monkeypatch.setattr(prompts, "is_tty", lambda: False)
    for key, value in {
        "HS_LOGIN_USER": "max",
        "HS_LOGIN_PASSWORD": "geheim",
        "HS_STATUSGRUPPE": "Studierende",
        "HSPORT_FIRSTNAME": "Max",
        "HSPORT_LASTNAME": "Beispiel",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("HS_BOOKING_EMAIL", raising=False)
    monkeypatch.delenv("HSPORT_EMAIL", raising=False)

    assert main(["book", "volleyball", "--confirm", "--json"]) == 1
    captured = capsys.readouterr()
    data = json.loads(captured.err)
    assert data["error"]["kind"] == "usage"
    assert data["confirmed"] is False
    assert data["submitted"] is False
    assert data["steps"] == ["kurs_waehlen"]
    assert data["step"] == "daten"
    assert "email" in data["error"]["message"]
    assert len(client.post_calls) == 1
