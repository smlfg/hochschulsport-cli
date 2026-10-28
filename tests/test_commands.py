"""CLI-Befehle mit Fixture-HTTP (kein Netzwerk)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hochschulsport_cli import api
from hochschulsport_cli.cli import main
from hochschulsport_cli.errors import NetworkError, UsageError
from hochschulsport_cli.portals import Portal, resolve_portal

ROOT = Path(__file__).resolve().parents[1]


class TestPortals:
    def test_portals_json_structure(self, fixture_client):
        payload = api.cmd_portals(fixture_client)
        assert payload["count"] == 7
        assert payload["default"] == "stuttgart"
        ids = {p["id"] for p in payload["portals"]}
        assert ids == {
            "stuttgart",
            "hamburg",
            "bremen",
            "paderborn",
            "chemnitz",
            "fu-berlin",
            "hsdemo",
        }
        stuttgart = next(p for p in payload["portals"] if p["id"] == "stuttgart")
        assert stuttgart["reachable"] is True
        assert stuttgart["sports"] == 168
        assert stuttgart["courses"] == 404


class TestSports:
    def test_sports_count(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_sports(portal, fixture_client)
        assert payload["count"] == 168

    def test_sports_query_bogen(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_sports(portal, fixture_client, query="bogen")
        assert payload["count"] == 1
        assert payload["sports"][0]["name"] == "Bogensport"

    def test_sports_query_special_chars_course_counts(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_sports(portal, fixture_client, query="yoga")
        counts = {s["name"]: s["course_count"] for s in payload["sports"]}
        assert counts["Acro Yoga & Bodenakrobatik"] == 1
        assert counts["Yoga - Breathe & Flow"] == 1
        assert counts["Yoga für alle"] == 1


class TestCourses:
    def test_courses_bogensport(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(portal, fixture_client, sport="Bogensport")
        assert payload["count"] == 3
        nrs = {c["course_nr"] for c in payload["courses"]}
        assert nrs == {"50100", "50101", "50102"}

    def test_courses_sport_filter_yoga(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(portal, fixture_client, sport_filter="yoga")
        assert payload["count"] >= 1
        for course in payload["courses"]:
            assert "yoga" in course["sport"].casefold()

    def test_courses_sport_filter_yoga_period_and_detail_url(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(portal, fixture_client, sport_filter="yoga")
        assert payload["count"] >= 1
        for course in payload["courses"]:
            assert "<" not in (course["period"] or "")
            assert ">" not in (course["period"] or "")
            assert course["detail_url"]
            assert course["detail_url"].startswith(
                portal.base_url + "/cgi/webpage.cgi?kursinfo="
            )
        by_nr = {c["course_nr"]: c for c in payload["courses"]}
        assert by_nr["13601"]["period"] == "12.10.-11.04."
        assert by_nr["13601"]["booking_status"] == "warteliste"

    def test_courses_sport_filter_status_from_sport_page(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(portal, fixture_client, sport_filter="Bogensport")
        by_nr = {c["course_nr"]: c for c in payload["courses"]}
        assert by_nr["50102"]["booking_status"] == "warteliste"

    def test_courses_query_and_sport_filter(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(
            portal, fixture_client, query="Training", sport_filter="yoga"
        )
        assert payload["count"] >= 1
        for course in payload["courses"]:
            assert "yoga" in course["sport"].casefold()
            blob = f"{course['title']} {course['sport']}".casefold()
            assert "training" in blob

    def test_courses_query_schwimmen(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(portal, fixture_client, query="Schwimmen")
        assert payload["count"] >= 1
        for course in payload["courses"]:
            blob = f"{course['title']} {course['sport']}".casefold()
            assert "schwimmen" in blob

    def test_courses_day_mi(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(portal, fixture_client, query="a", day="Mi")
        assert payload["count"] >= 1
        assert all(c["day"] == "Mi" for c in payload["courses"])

    def test_courses_free_only_bogensport(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(
            portal, fixture_client, sport="Bogensport", free_only=True
        )
        assert all(c["booking_status"] == "buchbar" for c in payload["courses"])
        assert payload["count"] == 1

    def test_unknown_sport_usage(self, fixture_client):
        portal = resolve_portal("stuttgart")
        with pytest.raises(UsageError) as exc:
            api.cmd_courses(portal, fixture_client, sport="NichtExistiert")
        assert "hsport sports --query" in exc.value.message
        assert "--sport" in exc.value.message

    def test_courses_sport_case_insensitive_exact(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(portal, fixture_client, sport="bogensport")
        assert payload["count"] == 3
        assert all(c["sport"] == "Bogensport" for c in payload["courses"])

    def test_courses_sport_nonexact_resolves_without_404(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(portal, fixture_client, sport="yoga")
        assert payload["count"] == 12
        assert all(c["detail_url"] for c in payload["courses"])

    def test_unknown_sport_json_cli_exit_usage(self, monkeypatch, capsys):
        import hochschulsport_cli.cli as cli_mod

        from tests.conftest import FixtureHttpClient

        monkeypatch.setattr(
            cli_mod, "HttpClient", lambda *args, **kwargs: FixtureHttpClient()
        )
        code = main(["courses", "NichtExistiert", "--json"])
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert "Traceback" not in captured.err
        data = json.loads(captured.err)
        assert data["error"]["kind"] == "usage"
        assert data["error"]["code"] == 1
        assert "hsport sports --query" in data["error"]["message"]
        assert "--sport" in data["error"]["message"]

    def test_invalid_day(self, fixture_client):
        portal = resolve_portal("stuttgart")
        with pytest.raises(UsageError):
            api.cmd_courses(portal, fixture_client, query="yoga", day="xyz")

    def test_empty_query_result(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_courses(portal, fixture_client, query="zzzznoop")
        assert payload["count"] == 0


class TestCliExitCodes:
    @pytest.mark.parametrize("argv", [["--version"], ["--version", "--json"]])
    def test_version_exit_zero(self, argv, capsys):
        code = main(argv)
        captured = capsys.readouterr()
        assert code == 0
        assert "hsport" in captured.out

    @pytest.mark.parametrize("argv", [["--help"], ["--help", "--json"]])
    def test_help_exit_zero(self, argv, capsys):
        code = main(argv)
        captured = capsys.readouterr()
        assert code == 0
        assert "usage" in captured.out.lower()

    @pytest.mark.parametrize(
        "argv",
        [
            ["does-not-exist"],
            ["does-not-exist", "--json"],
            [],
            ["--json"],
            ["courses", "Bogensport", "--day"],
            ["courses", "Bogensport", "--day", "--json"],
        ],
    )
    def test_argparse_errors_exit_usage(self, argv, capsys):
        code = main(argv)
        captured = capsys.readouterr()
        assert code == 1
        if "--json" in argv:
            assert captured.out == ""
            assert "Traceback" not in captured.err
            data = json.loads(captured.err)
            assert data["error"]["kind"] == "usage"
            assert data["error"]["code"] == 1


class TestCliErrors:
    def test_invalid_portal_usage(self):
        with pytest.raises(UsageError):
            resolve_portal("://bad")

    def test_network_error_exit(self, fixture_client):
        portal = Portal(id="x", name="x", base_url="http://127.0.0.1:9")
        with pytest.raises(NetworkError) as exc:
            api._load_index_html(portal, fixture_client)
        assert exc.value.exit_code == 3

    def test_courses_day_json_cli(self, capsys):
        code = main(["courses", "--day", "xyz", "--json"])
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        data = json.loads(captured.err)
        assert data["error"]["kind"] == "usage"
        assert data["error"]["code"] == 1

    def test_invalid_portal_json_no_traceback(self, capsys):
        code = main(["--portal", "nichtexistiert", "courses", "--query", "yoga", "--json"])
        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert "Traceback" not in captured.err
        data = json.loads(captured.err)
        assert data["error"]["kind"] == "usage"
        assert data["error"]["code"] == 1
        assert "Portal" in data["error"]["message"] or "Host" in data["error"]["message"]


def test_no_network_subprocess():
    """Sandbox: Subprozess darf kein DNS nach außen."""
    env = {
        **dict(__import__("os").environ),
        "PYTHONPATH": str(ROOT / "tests" / "harness"),
        "ACCEPTANCE_SANDBOX": "1",
    }
    proc = subprocess.run(
        [sys.executable, "-c", "import socket; socket.getaddrinfo('example.com', 443)"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
