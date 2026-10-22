"""Tests für course, watch und book (Fixtures, kein Netz)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from hochschulsport_cli import api
from hochschulsport_cli.cli import main
from hochschulsport_cli.errors import NetworkError, ParseError, UsageError
from hochschulsport_cli.portals import resolve_portal
from hochschulsport_cli.watch_state import EXIT_WATCH_CHANGED, load_watch_state

from tests.harness.leak_check import find_secret_in_text

ROOT = Path(__file__).resolve().parents[1]
TEST_SECRET = "hsport-pytest-secret-7f3a9c"


class TestCourse:
    def test_course_50100_json(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_course(portal, fixture_client, course_nr="50100")
        assert payload["course_nr"] == "50100"
        assert payload["title"] == "Bogensport für Fortgeschrittene"
        assert payload["detail_url"] and "kursinfo=" in payload["detail_url"]
        assert payload["sessions"]
        assert payload["locations"]
        assert payload.get("sport_description")

    def test_course_unknown_usage(self, fixture_client):
        portal = resolve_portal("stuttgart")
        with pytest.raises(UsageError) as exc:
            api.cmd_course(portal, fixture_client, course_nr="99999")
        assert exc.value.exit_code == 1
        assert "99999" in exc.value.message

    def test_course_unknown_json_cli(self, fixture_client, capsys):
        code = main(["course", "99999", "--json"])
        out = capsys.readouterr().out
        assert code == 1
        data = json.loads(out)
        assert data["error"]["kind"] == "usage"
        assert "99999" in data["error"]["message"]


class TestWatch:
    def test_watch_baseline_and_change(self, fixture_client, tmp_path):
        portal = resolve_portal("stuttgart")
        state_file = tmp_path / "watch.json"
        payload, code = api.cmd_watch(
            portal,
            fixture_client,
            course_nr="50100",
            state_file=state_file,
        )
        assert code == 0
        assert payload["changed"] is False
        assert payload["booking_status"] == "buchbar"
        assert state_file.exists()
        assert stat.S_IMODE(state_file.stat().st_mode) == 0o600
        stored = load_watch_state(state_file)
        assert "stuttgart:50100" in stored
        assert stored["stuttgart:50100"]["course_nr"] == "50100"
        assert "password" not in json.dumps(stored).casefold()

        stored["stuttgart:50100"]["booking_status"] = "ausgebucht"
        state_file.write_text(json.dumps(stored), encoding="utf-8")
        payload2, code2 = api.cmd_watch(
            portal,
            fixture_client,
            course_nr="50100",
            state_file=state_file,
        )
        assert payload2["changed"] is True
        assert payload2["previous_status"] == "ausgebucht"
        assert code2 == EXIT_WATCH_CHANGED

    def test_watch_corrupt_state(self, fixture_client, tmp_path):
        portal = resolve_portal("stuttgart")
        state_file = tmp_path / "watch.json"
        state_file.write_text("{not-json", encoding="utf-8")
        with pytest.raises(UsageError):
            api.cmd_watch(
                portal,
                fixture_client,
                course_nr="50100",
                state_file=state_file,
            )


class TestBook:
    def test_book_dry_run_no_post(self, fixture_client):
        portal = resolve_portal("stuttgart")
        payload = api.cmd_book(portal, fixture_client, course_nr="50100", confirm=False)
        assert payload["dry_run"] is True
        assert payload["submitted"] is False
        assert fixture_client.post_calls == []
        form = payload["form"]
        names = {f["name"] for f in form["fields"]}
        assert "BS_Code" in names
        assert any(n.startswith("BS_Kursid_") for n in names)

    def test_book_confirm_missing_env_no_http(self, fixture_client):
        portal = resolve_portal("stuttgart")
        env = {k: v for k, v in os.environ.items() if not k.startswith("HS_") and not k.startswith("HSPORT_")}
        # validate credentials before any HTTP in cmd_book
        with pytest.MonkeyPatch.context() as mp:
            for key in (
                "HS_LOGIN_USER",
                "HS_LOGIN_PASSWORD",
                "HS_STATUSGRUPPE",
                "HSPORT_FIRSTNAME",
                "HSPORT_LASTNAME",
            ):
                mp.delenv(key, raising=False)
            with pytest.raises(UsageError):
                api.cmd_book(portal, fixture_client, course_nr="50100", confirm=True)
        assert fixture_client.calls == []
        assert fixture_client.post_calls == []

    def test_book_confirm_missing_env_cli(self, capsys):
        for key in list(os.environ):
            if key.startswith("HS_") or key.startswith("HSPORT_"):
                os.environ.pop(key, None)
        code = main(["book", "50100", "--confirm", "--json"])
        out = capsys.readouterr()
        assert code == 1
        data = json.loads(out.out)
        assert data["error"]["kind"] == "usage"
        assert TEST_SECRET not in out.out
        assert TEST_SECRET not in out.err


class TestErrors:
    def test_network_503(self):
        portal = resolve_portal("stuttgart")
        client = __import__("tests.conftest", fromlist=["FixtureHttpClient"]).FixtureHttpClient(
            http_503=True
        )
        with pytest.raises(NetworkError) as exc:
            api.cmd_course(portal, client, course_nr="50100")
        assert exc.value.exit_code == 3

    def test_parse_broken_js(self):
        portal = resolve_portal("stuttgart")
        from tests.conftest import FixtureHttpClient

        client = FixtureHttpClient(broken_js=True)
        with pytest.raises(ParseError) as exc:
            api.cmd_course(portal, client, course_nr="50100")
        assert exc.value.exit_code == 4


def test_leak_check_harness_importable():
    secret = "never-embed-this-secret-value"
    assert not find_secret_in_text(secret, "hochschulsport-cli tests")
