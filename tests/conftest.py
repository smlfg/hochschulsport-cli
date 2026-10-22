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

    def __init__(self, *, broken_js: bool = False, http_503: bool = False) -> None:
        super().__init__(session=None)
        self.calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, str]]] = []
        self.broken_js = broken_js
        self.http_503 = http_503

    def get_text(self, url: str, *, portal: str | None = None) -> str:
        self.calls.append(url)
        if self.http_503:
            from hochschulsport_cli.errors import NetworkError

            raise NetworkError("HTTP 503", portal=portal, url=url)
        if "127.0.0.1:9" in url or "127.0.0.1:65530" in url:
            from hochschulsport_cli.errors import NetworkError

            raise NetworkError("connection refused", portal=portal, url=url)
        if url.endswith("/index.html"):
            return _read_fixture("index_stuttgart.html")
        if url.endswith("/kurssuche.js"):
            if self.broken_js:
                return "const data={not valid"
            return Path(FIXTURES / "kurssuche_stuttgart.js").read_text(
                encoding="utf-8", errors="replace"
            )
        if "kursinfo=76DC9CFAE3" in url:
            return _read_fixture("course_13600_stuttgart.html")
        if "kursinfo=" in url:
            return _read_fixture("course_50100_stuttgart.html")
        if "_Bogensport.html" in url:
            return _read_fixture("sport_bogensport_stuttgart.html")
        if "_Aerobic.html" in url:
            return _read_fixture("sport_aerobic_hsdemo.html")
        if "/angebote/" in url and ".html" in url:
            return "<html><body></body></html>"
        raise AssertionError(f"unexpected URL in test: {url}")

    def get_json_like(self, url: str, *, portal: str | None = None) -> str:
        return self.get_text(url, portal=portal)

    def post_form(
        self,
        url: str,
        data: dict[str, str],
        *,
        portal: str | None = None,
    ) -> str:
        self.post_calls.append((url, dict(data)))
        return "<html>login required</html>"


@pytest.fixture
def fixture_client() -> FixtureHttpClient:
    return FixtureHttpClient()
