"""Fehlerklassen und Exit-Codes.

Jede Fehlerklasse hat genau einen Exit-Code. „Unbekannt" ist nie „Erfolg".
Siehe ``agent-learnings/rules/AGENTS.md``.

Exit-Codes
----------
0  Erfolg
1  Usage / Validierung      -> ``usage``
2  Auth                      -> ``auth``
3  Netzwerk / HTTP           -> ``network``
4  Parse                     -> ``parse``
5  Forbidden / nicht unterstützt -> ``forbidden``
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_AUTH = 2
EXIT_NETWORK = 3
EXIT_PARSE = 4
EXIT_FORBIDDEN = 5


class CliError(Exception):
    """Basisfehler mit Exit-Code und ``kind`` für das JSON-Fehlerobjekt."""

    exit_code = EXIT_USAGE
    kind = "usage"

    def __init__(
        self,
        message: str,
        *,
        portal: str | None = None,
        url: str | None = None,
        course_nr: str | None = None,
        exit_code: int | None = None,
        kind: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.portal = portal
        self.url = url
        self.course_nr = course_nr
        self.extra = dict(extra or {})
        if exit_code is not None:
            self.exit_code = exit_code
        if kind is not None:
            self.kind = kind

    def to_dict(self) -> dict[str, object]:
        """JSON-Fehlerobjekt: ``{"error": {"code": …, "kind": …, "message": …}}``."""
        error: dict[str, object] = {
            "code": self.exit_code,
            "kind": self.kind,
            "message": self.message,
        }
        if self.portal is not None:
            error["portal"] = self.portal
        if self.url is not None:
            error["url"] = self.url
        if self.course_nr is not None:
            error["course_nr"] = self.course_nr
        payload: dict[str, object] = {"error": error}
        payload.update(self.extra)
        return payload


class UsageError(CliError):
    """Ungültige Eingabe, unbekannter Kurs, fehlende Pflichtwerte."""

    exit_code = EXIT_USAGE
    kind = "usage"


class AuthError(CliError):
    """Login fehlt, ist abgelaufen oder die Credentials sind falsch."""

    exit_code = EXIT_AUTH
    kind = "auth"


class NetworkError(CliError):
    """DNS-Fehler, Timeout, HTTP >= 500 oder sonstige Verbindungsprobleme."""

    exit_code = EXIT_NETWORK
    kind = "network"


class ParseError(CliError):
    """Antwort ist unlesbar oder hat ein unerwartetes Format."""

    exit_code = EXIT_PARSE
    kind = "parse"


class ForbiddenError(CliError):
    """Die Aktion ist auf diesem Portal/Kurs nicht möglich."""

    exit_code = EXIT_FORBIDDEN
    kind = "forbidden"
