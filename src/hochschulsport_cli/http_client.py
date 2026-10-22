"""HTTP-Zugriff auf Buchsys-Portale.

Reihenfolge ist strikt: **erst den HTTP-Status prüfen, dann parsen**
(``agent-learnings/rules/AGENTS.md``). HTTP >= 500 oder ein Verbindungsfehler
ist ein Netzwerkfehler (Exit 3) und niemals ein Parsefehler (Exit 4).
"""

from __future__ import annotations

import time
from typing import Any

import requests

from .errors import NetworkError, ParseError

DEFAULT_TIMEOUT = 20.0
USER_AGENT = "hochschulsport-cli/0.1 (+https://github.com/smlfg/hochschulsport-cli)"
RETRY_STATUSES = (502, 503, 504)


class HttpClient:
    """Minimaler HTTP-Client mit Status-vor-Parse-Semantik."""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        session: requests.Session | None = None,
        retries: int = 2,
        backoff: float = 0.7,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def get_text(self, url: str, *, portal: str | None = None) -> str:
        """GET mit Status-Prüfung. Gibt den Response-Body als Text zurück."""
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
                raise NetworkError(
                    f"Portal nicht erreichbar: {exc}", portal=portal, url=url
                ) from exc
            if response.status_code >= 500 and attempt < self.retries:
                time.sleep(self.backoff * (attempt + 1))
                continue
            self._check_status(response, portal=portal, url=url)
            return response.text
        raise NetworkError(
            f"Portal nicht erreichbar: {last_error}", portal=portal, url=url
        )

    def get_json_like(self, url: str, *, portal: str | None = None) -> str:
        """GET für JSON-artige Antworten (``kurssuche.js``)."""
        return self.get_text(url, portal=portal)

    def post_form(
        self,
        url: str,
        data: dict[str, str],
        *,
        portal: str | None = None,
    ) -> str:
        """POST mit Formular-Daten. Nur für den bestätigten Buchungsabschluss."""
        try:
            response = self.session.post(url, data=data, timeout=self.timeout)
        except requests.RequestException as exc:
            raise NetworkError(
                f"Portal nicht erreichbar: {exc}", portal=portal, url=url
            ) from exc
        self._check_status(response, portal=portal, url=url)
        return response.text

    @staticmethod
    def _check_status(response: Any, *, portal: str | None, url: str) -> None:
        status = response.status_code
        if status >= 500:
            raise NetworkError(
                f"Portal antwortet mit HTTP {status}.",
                portal=portal,
                url=url,
            )
        if status == 404:
            raise ParseError(
                "Seite nicht gefunden (HTTP 404).",
                portal=portal,
                url=url,
            )
        if status in (401, 403):
            from .errors import AuthError

            raise AuthError(
                f"Zugriff verweigert (HTTP {status}).",
                portal=portal,
                url=url,
            )
        if status >= 400:
            raise NetworkError(
                f"Portal antwortet mit HTTP {status}.",
                portal=portal,
                url=url,
            )
