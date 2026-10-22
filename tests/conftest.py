"""Gemeinsame Fixtures: lokale HTML/JS ohne Netzwerk."""

from __future__ import annotations

from pathlib import Path

import pytest

from hochschulsport_cli.http_client import HttpClient

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STUTTGART = "https://anmeldung.hochschulsport.uni-stuttgart.de"


def _read_fixture(name: str) -> str:
    path = FIXTURES / name
    return path.read_bytes().decode("latin-1")


class FixtureHttpClient(HttpClient):
    """HTTP-Client, der nur Fixture-Dateien ausliefert."""

    def __init__(self) -> None:
        super().__init__(session=None)
        self.calls: list[str] = []

    def get_text(self, url: str, *, portal: str | None = None) -> str:
        self.calls.append(url)
        if "127.0.0.1:9" in url or "127.0.0.1:65530" in url:
            from hochschulsport_cli.errors import NetworkError

            raise NetworkError("connection refused", portal=portal, url=url)
        if url.endswith("/index.html"):
            return _read_fixture("index_stuttgart.html")
        if url.endswith("/kurssuche.js"):
            return Path(FIXTURES / "kurssuche_stuttgart.js").read_text(
                encoding="utf-8", errors="replace"
            )
        if "_Bogensport.html" in url:
            return _read_fixture("sport_bogensport_stuttgart.html")
        if "/angebote/" in url and ".html" in url:
            return "<html><body></body></html>"
        raise AssertionError(f"unexpected URL in test: {url}")


@pytest.fixture
def fixture_client() -> FixtureHttpClient:
    return FixtureHttpClient()
