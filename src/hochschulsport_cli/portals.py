"""Bekannte Buchsys-Portale und Basis-URL-Normalisierung.

Alle Einträge sind am 2026-10-22 live von dieser Box aus verifiziert:
HTTP 200 auf ``<basis>/angebote/aktueller_zeitraum/index.html`` **und**
echte Kurstabelle (``table.bs_kurse``) **und** parsebares ``kurssuche.js``.

Hochschule Heilbronn (HHN, DHBW HN, TUM HN) nutzt das eigene
Hochschulsportportal https://portal.studi.hn (Hochschul-Login, **kein**
Buchsys). Am 2026-10-30 geprüft: ``/angebote/aktueller_zeitraum/`` antwortet
mit HTTP 302. Deshalb gibt es keinen Heilbronn-Eintrag; Default bleibt
Stuttgart (Baden-Württemberg).
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import UsageError

DEFAULT_PORTAL_ID = "stuttgart"

#: Hinweis für ``hsport portals``: Heilbronn ist kein Buchsys-Portal.
HEILBRONN_HINT = (
    "Heilbronn (HHN/DHBW/TUM): portal.studi.hn – kein Buchsys, nicht unterstützt"
)

#: Kürzel für ``--portal``, das zu ``https://www.buchsys.de/<slug>`` ergänzt wird.
BUCHSYS_HOST = "https://www.buchsys.de"


@dataclass(frozen=True)
class Portal:
    """Ein bekanntes Buchsys-Portal."""

    id: str
    name: str
    base_url: str
    #: ``True`` für Hochschulsportzentralen, ``False`` für Test-/Demosysteme.
    production: bool = True

    def url(self, path: str) -> str:
        """Absolute URL für ``path`` relativ zur Basis-URL."""
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"


#: Live verifizierte Portale. Reihenfolge = Ausgabe-Reihenfolge von ``portals``.
PORTALS: tuple[Portal, ...] = (
    Portal(
        id="stuttgart",
        name="Universität Stuttgart",
        base_url="https://anmeldung.hochschulsport.uni-stuttgart.de",
    ),
    Portal(
        id="hamburg",
        name="Universität Hamburg",
        base_url="https://buchung.hochschulsport-hamburg.de",
    ),
    Portal(
        id="bremen",
        name="Universität Bremen",
        base_url="https://www.buchsys.de/bremen",
    ),
    Portal(
        id="paderborn",
        name="Universität Paderborn",
        base_url="https://www.buchsys.de/paderborn",
    ),
    Portal(
        id="chemnitz",
        name="TU Chemnitz",
        base_url="https://www.buchsys.de/chemnitz",
    ),
    Portal(
        id="fu-berlin",
        name="Freie Universität Berlin",
        base_url="https://www.buchsys.de/fu-berlin",
    ),
    Portal(
        id="hsdemo",
        name="Hochschulsport der Test-Universität",
        base_url="https://www.buchsys.de/hsdemo",
        production=False,
    ),
)

PORTALS_BY_ID: dict[str, Portal] = {p.id: p for p in PORTALS}

#: Buchsys-Pfadpräfix für Sportseiten.
OFFERTS_PATH = "angebote/aktueller_zeitraum"
#: Buchsys-Pfadpräfix für die JSON-Suchdaten.
SEARCH_JS_PATH = f"{OFFERTS_PATH}/kurssuche.js"
#: Buchsys-Pfadpräfix für Detail- und Buchungsseiten.
CGI_PATH = "cgi"


def _normalize_base_url(raw: str) -> str:
    """Normalisiert eine vom Nutzer angegebene Basis-URL.

    Erlaubt sind vollständige URLs (``https://host/pfad``) sowie Kurzformen
    wie ``buchsys.de/bremen``, die zu ``https://www.buchsys.de/bremen``
    werden. Ungültige Eingaben erzeugen einen ``UsageError`` – nie einen
    Traceback.
    """
    value = (raw or "").strip()
    if not value:
        raise UsageError("Portal darf nicht leer sein.")
    if "://" not in value:
        value = f"https://{value}"
    scheme, _, rest = value.partition("://")
    if scheme not in ("http", "https"):
        raise UsageError(f"Ungültiges Portal-Schema: {scheme!r}. Erlaubt sind http und https.")
    if not rest or rest.startswith("/"):
        raise UsageError(f"Ungültige Portal-URL: {raw!r}")
    host, _, path = rest.partition("/")
    hostname = host.split(":")[0]
    if not hostname or "." not in hostname:
        raise UsageError(f"Ungültiger Portal-Host: {host!r}")
    base = f"{scheme}://{hostname}"
    path = path.strip("/")
    if path:
        base = f"{base}/{path}"
    # "buchsys.de/<slug>" -> "www.buchsys.de/<slug>" (Kurzform der Buchsys-Instanzen).
    if base in ("https://buchsys.de", "http://buchsys.de"):
        base = base.replace("://buchsys.de", "://www.buchsys.de")
    return base.rstrip("/")


def resolve_portal(raw: str | None) -> Portal:
    """Löst ``--portal``/``HS_PORTAL`` zu einem bekannten Portal auf.

    Bekannte IDs (``stuttgart`` …) werden direkt verwendet; unbekannte IDs und
    freie URLs werden als eigene Basis-URL aufgenommen (id = normalisierte
    URL), damit auch fremde Buchsys-Instanzen nutzbar sind.
    """
    value = (raw or "").strip()
    if not value:
        return PORTALS_BY_ID[DEFAULT_PORTAL_ID]
    if value in PORTALS_BY_ID:
        return PORTALS_BY_ID[value]
    base = _normalize_base_url(value)
    known = next((p for p in PORTALS if p.base_url.rstrip("/") == base), None)
    if known is not None:
        return known
    return Portal(id=base, name=base, base_url=base, production=False)
