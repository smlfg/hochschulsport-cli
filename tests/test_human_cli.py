"""Menschliche Bedienung: login/logout/whoami/config und interaktives Buchen."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from hochschulsport_cli import config as config_mod
from hochschulsport_cli import prompts
from hochschulsport_cli.booking import load_booking_credentials
from hochschulsport_cli.cli import main
from hochschulsport_cli.models import STATUS_BOOKABLE, STATUS_WAITLIST, Course, Price
from hochschulsport_cli.portals import resolve_portal

from tests.conftest import FixtureHttpClient

TEST_SECRET = "hsport-test-passwort-9d2f"


@pytest.fixture
def xdg_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for key in list(os.environ):
        if key.startswith("HS_") or key.startswith("HSPORT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config_mod, "_keyring_usable", lambda: False)
    return tmp_path


def _login(monkeypatch) -> None:
    monkeypatch.setattr(prompts, "is_tty", lambda: True)
    answers = {
        "E-Mail/Login": "max@example.org",
        "Vorname": "Max",
        "Nachname": "Mustermann",
        "Auswahl": "1",
    }

    def fake_ask(question: str, *, default: str | None = None) -> str:
        for needle, value in answers.items():
            if needle in question:
                return value
        return default or ""

    monkeypatch.setattr(prompts, "ask", fake_ask)
    monkeypatch.setattr(prompts, "ask_secret", lambda question: TEST_SECRET)
    assert main(["login", "--json"]) == 0


def _course(course_nr: str, *, status: str = STATUS_BOOKABLE) -> Course:
    return Course(
        course_nr=course_nr,
        title=f"Testkurs {course_nr}",
        sport="Bogensport",
        day="Sa",
        time="12:00-15:00",
        location="Sporthalle Test",
        period="12.10.-11.04.",
        prices=[Price("Studierende", 30.0), Price("Externe", 60.0)],
        booking_status=status,
    )


def _fixture_client(monkeypatch) -> FixtureHttpClient:
    client = FixtureHttpClient()
    monkeypatch.setattr(
        "hochschulsport_cli.cli.HttpClient", lambda *args, **kwargs: client
    )
    return client


def test_login_speichert_datei_mit_0600(xdg_config, monkeypatch, capsys):
    _login(monkeypatch)
    path = xdg_config / "hochschulsport-cli" / "config.json"
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = data["portals"]["stuttgart"]
    assert entry["login_user"] == "max@example.org"
    assert entry["first_name"] == "Max"
    assert entry["last_name"] == "Mustermann"
    assert entry["status_group"] == "Studierende"
    assert entry["password_store"] == "file"
    assert entry["login_password"] == TEST_SECRET
    assert TEST_SECRET not in capsys.readouterr().out


def test_whoami_zeigt_passwort_nur_als_status(xdg_config, monkeypatch, capsys):
    _login(monkeypatch)
    capsys.readouterr()
    assert main(["whoami", "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["portal"] == "stuttgart"
    assert data["login_user"] == "max@example.org"
    assert data["name"] == "Max Mustermann"
    assert data["status_group"] == "Studierende"
    assert data["password"] == "gespeichert (Datei)"
    assert data["sources"]["login_user"] == "config"
    assert TEST_SECRET not in captured.out
    assert TEST_SECRET not in captured.err

    assert main(["whoami"]) == 0
    text = capsys.readouterr().out
    assert "Passwort: gespeichert (Datei)" in text
    assert TEST_SECRET not in text


def test_logout_loescht_gespeicherte_daten(xdg_config, monkeypatch, capsys):
    _login(monkeypatch)
    capsys.readouterr()
    assert main(["logout", "--json"]) == 0
    capsys.readouterr()
    assert config_mod.load()["portals"].get("stuttgart") is None
    assert main(["whoami", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["password"] == "fehlt"
    assert data["login_user"] is None


def test_config_portal_setzt_default(xdg_config, capsys):
    assert main(["config", "portal", "hamburg", "--json"]) == 0
    assert config_mod.load()["default_portal"] == "hamburg"
    capsys.readouterr()
    assert main(["whoami", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["portal"] == "hamburg"


def test_config_portal_unbekannt_ist_usage_fehler(xdg_config, capsys):
    assert main(["config", "portal", "gibtsnicht", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    data = json.loads(captured.err)
    assert data["error"]["kind"] == "usage"
    assert "Unbekanntes Portal 'gibtsnicht'" in data["error"]["message"]
    assert "hsport portals" in data["error"]["message"]
    assert "Buchsys-URL" in data["error"]["message"]


def test_portals_text_zeigt_default_hinweis(xdg_config, monkeypatch, capsys):
    _fixture_client(monkeypatch)
    assert main(["portals"]) == 0
    out = capsys.readouterr().out
    assert "Default ändern: hsport config portal stuttgart" in out
    assert "(aktuell: stuttgart, Quelle: Standard)" in out
    assert (
        "Heilbronn (HHN/DHBW/TUM): portal.studi.hn – kein Buchsys, "
        "nicht unterstützt"
    ) in out


def test_portals_quelle_config(xdg_config, monkeypatch, capsys):
    assert main(["config", "portal", "hamburg", "--json"]) == 0
    capsys.readouterr()
    _fixture_client(monkeypatch)
    assert main(["portals"]) == 0
    out = capsys.readouterr().out
    assert "(aktuell: hamburg, Quelle: config)" in out


def test_book_ein_buchbarer_treffer_zeigt_hinweis(
    xdg_config, monkeypatch, capsys
):
    courses = [
        _course("50100"),
        _course("50102", status=STATUS_WAITLIST),
        _course("50103", status="ausgebucht"),
    ]
    monkeypatch.setattr(
        "hochschulsport_cli.cli.load_courses_for_sport",
        lambda portal, client, name: courses,
    )
    _fixture_client(monkeypatch)
    monkeypatch.setattr(prompts, "is_tty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    assert main(["book", "volleyball"]) == 0
    out = capsys.readouterr().out
    notice = (
        "1 buchbarer Kurs für „volleyball“ gefunden "
        "(weitere 2 nur Warteliste/ausgebucht)."
    )
    assert notice in out
    assert out.index(notice) < out.index("Kurs: 50100")


def test_env_ueberschreibt_config(xdg_config, monkeypatch, capsys):
    _login(monkeypatch)
    monkeypatch.setenv("HS_LOGIN_USER", "env@example.org")
    monkeypatch.setenv("HS_STATUSGRUPPE", "Externe")
    capsys.readouterr()
    assert main(["whoami", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["login_user"] == "env@example.org"
    assert data["status_group"] == "Externe"
    assert data["sources"]["login_user"] == "env"
    assert data["sources"]["status_group"] == "env"

    credentials = load_booking_credentials("stuttgart")
    assert credentials.login_user == "env@example.org"
    assert credentials.status_group == "Externe"
    assert credentials.login_password == TEST_SECRET


def test_login_ohne_tty_klarer_fehler(xdg_config, monkeypatch, capsys):
    monkeypatch.setattr(prompts, "is_tty", lambda: False)
    assert main(["login", "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    data = json.loads(captured.err)
    assert data["error"]["kind"] == "usage"
    assert "braucht ein Terminal" in data["error"]["message"]
    assert "HS_LOGIN_USER" in data["error"]["message"]


def test_book_per_name_auswahl_nein_ohne_post(
    xdg_config, monkeypatch, capsys
):
    _login(monkeypatch)
    courses = [_course("50100"), _course("50102")]
    monkeypatch.setattr(
        "hochschulsport_cli.cli.load_courses_for_sport",
        lambda portal, client, name: courses,
    )
    client = _fixture_client(monkeypatch)
    monkeypatch.setattr(prompts, "is_tty", lambda: True)
    asked: list[str] = []

    def fake_ask(question: str, *, default: str | None = None) -> str:
        asked.append(question)
        if "Nummer wählen" in question:
            return "1"
        return default or ""

    monkeypatch.setattr(prompts, "ask", fake_ask)
    monkeypatch.setattr(
        prompts, "confirm", lambda question, *, default=False: False
    )

    assert main(["book", "bogensport"]) == 0
    captured = capsys.readouterr()
    assert client.post_calls == []
    assert "Abgebrochen, nichts gebucht." in captured.out
    assert any("Nummer wählen" in question for question in asked)
    assert "[1] 50100 Testkurs 50100" in captured.out
    assert "30,00 € (Studierende)" in captured.out


def test_book_name_nicht_tty_mehrere_treffer_usage(
    xdg_config, monkeypatch, capsys
):
    courses = [_course("50100"), _course("50102")]
    monkeypatch.setattr(
        "hochschulsport_cli.cli.load_courses_for_sport",
        lambda portal, client, name: courses,
    )
    _fixture_client(monkeypatch)
    monkeypatch.setattr(prompts, "is_tty", lambda: False)

    assert main(["book", "bogensport"]) == 1
    captured = capsys.readouterr()
    assert "[1] 50100" in captured.out
    assert "Kursnummer" in captured.err


def test_book_ohne_buchbare_kurse_hinweis_watch(
    xdg_config, monkeypatch, capsys
):
    courses = [_course("50102", status=STATUS_WAITLIST)]
    monkeypatch.setattr(
        "hochschulsport_cli.cli.load_courses_for_sport",
        lambda portal, client, name: courses,
    )
    _fixture_client(monkeypatch)
    monkeypatch.setattr(prompts, "is_tty", lambda: False)

    assert main(["book", "bogensport"]) == 1
    captured = capsys.readouterr()
    assert "50102" in captured.out
    assert "warteliste" in captured.out
    assert "hsport watch" in captured.err


def test_book_confirm_ohne_login_kein_request(xdg_config, monkeypatch, capsys):
    client = _fixture_client(monkeypatch)
    monkeypatch.setattr(prompts, "is_tty", lambda: False)

    assert main(["book", "50100", "--confirm", "--json"]) == 1
    captured = capsys.readouterr()
    assert client.calls == []
    assert client.post_calls == []
    assert captured.out == ""
    data = json.loads(captured.err)
    assert data["error"]["kind"] == "usage"
    assert "hsport login" in data["error"]["message"]


def test_book_ohne_confirm_nicht_tty_ist_dry_run(
    xdg_config, monkeypatch, capsys
):
    client = _fixture_client(monkeypatch)
    monkeypatch.setattr(prompts, "is_tty", lambda: False)

    assert main(["book", "50100", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["dry_run"] is True
    assert data["submitted"] is False
    assert data["course_nr"] == "50100"
    assert client.post_calls == []


def test_help_zeigt_neue_beispiele(capsys):
    assert main(["--help"]) == 0
    root_help = capsys.readouterr().out
    for command in ("login", "logout", "whoami", "config", "book"):
        assert command in root_help
    assert "hsport login" in root_help
    assert "hsport book volleyball" in root_help

    assert main(["book", "--help"]) == 0
    book_help = capsys.readouterr().out
    assert "--confirm" in book_help
    assert "--yes" in book_help
    assert "hsport book volleyball" in book_help


def test_keyring_wird_nur_mit_backend_genutzt(xdg_config, monkeypatch):
    monkeypatch.setattr(config_mod, "_keyring_usable", lambda: True)
    monkeypatch.setattr(config_mod, "_keyring_set", lambda portal_id, password: True)
    monkeypatch.setattr(config_mod, "_keyring_get", lambda portal_id: TEST_SECRET)

    entry = config_mod.save_portal(
        "stuttgart",
        {
            "login_user": "max@example.org",
            "login_password": TEST_SECRET,
            "status_group": "Studierende",
            "first_name": "Max",
            "last_name": "Mustermann",
        },
    )
    assert entry["password_store"] == "keyring"
    assert "login_password" not in entry
    loaded = config_mod.load_portal("stuttgart")
    assert loaded["login_password"] == TEST_SECRET
