"""Datenmodell für Kurse, Sportarten und Buchungsstatus."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Buchungsstatus eines Kurses.
STATUS_BOOKABLE = "buchbar"
STATUS_FULL = "ausgebucht"
STATUS_WAITLIST = "warteliste"
STATUS_NOT_BOOKABLE = "noch_nicht_buchbar"

ALL_STATUSES = (
    STATUS_BOOKABLE,
    STATUS_FULL,
    STATUS_WAITLIST,
    STATUS_NOT_BOOKABLE,
)

#: CSS-Klasse -> Buchungsstatus. Reihenfolge = Priorität (erster Treffer gewinnt).
#: Live am 2026-10-22 beobachtete Klassen; die restlichen Klassen stammen aus
#: ``buchsys/lib/global/angebote.css`` (identisch auf allen Portalen).
STATUS_BY_CLASS: dict[str, str] = {
    "bs_btn_buchen": STATUS_BOOKABLE,
    "bs_btn_ausgebucht": STATUS_FULL,
    "bs_btn_warteliste": STATUS_WAITLIST,
    "bs_btn_vormerkliste": STATUS_WAITLIST,
    "bs_btn_abgelaufen": STATUS_NOT_BOOKABLE,
    "bs_btn_gesperrt": STATUS_NOT_BOOKABLE,
    "bs_btn_keine_buchung": STATUS_NOT_BOOKABLE,
    "bs_btn_ohne_anmeldung": STATUS_NOT_BOOKABLE,
    "bs_btn_nur_buero": STATUS_NOT_BOOKABLE,
    "bs_btn_storniert": STATUS_NOT_BOOKABLE,
    "bs_btn_siehe_text": STATUS_NOT_BOOKABLE,
    "bs_btn_infoservice": STATUS_NOT_BOOKABLE,
    "bs_btn_semesterkarte": STATUS_NOT_BOOKABLE,
    "bs_btn_platz_buchen": STATUS_NOT_BOOKABLE,
    "bs_btn_karte_kaufen": STATUS_NOT_BOOKABLE,
    "bs_btn_autostart": STATUS_NOT_BOOKABLE,
    "bs_btn_jump": STATUS_NOT_BOOKABLE,
}

#: Wochentage in Buchsys-Schreibweise.
DAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

#: Deutsche und englische Wochentagsnamen -> Buchsys-Kürzel.
DAY_ALIASES: dict[str, str] = {
    "mo": "Mo", "montag": "Mo", "mo.": "Mo", "mon": "Mo",
    "di": "Di", "dienstag": "Di", "di.": "Di", "die": "Di",
    "mi": "Mi", "mittwoch": "Mi", "mi.": "Mi", "mit": "Mi",
    "do": "Do", "donnerstag": "Do", "do.": "Do", "don": "Do",
    "fr": "Fr", "freitag": "Fr", "fr.": "Fr", "fre": "Fr",
    "sa": "Sa", "samstag": "Sa", "sa.": "Sa", "sam": "Sa",
    "so": "So", "sonntag": "So", "so.": "So", "son": "So",
}


@dataclass
class Price:
    """Preis für eine Statusgruppe (z. B. Studierende / Beschäftigte / Externe)."""

    group: str
    price_eur: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"group": self.group, "price_eur": self.price_eur}


@dataclass
class Session:
    """Ein einzelner Termin eines Kurses."""

    day: str | None = None
    date: str | None = None
    time: str | None = None
    location: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "date": self.date,
            "time": self.time,
            "location": self.location,
        }


@dataclass
class Course:
    """Ein Kurs aus einer Buchsys-Kurstabelle oder aus ``kurssuche.js``."""

    course_nr: str
    title: str = ""
    sport: str = ""
    day: str | None = None
    time: str | None = None
    location: str | None = None
    instructor: str | None = None
    period: str | None = None
    prices: list[Price] = field(default_factory=list)
    booking_status: str = STATUS_NOT_BOOKABLE
    detail_url: str | None = None
    sessions: list[Session] = field(default_factory=list)
    locations: list[dict[str, Any]] = field(default_factory=list)
    category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_nr": self.course_nr,
            "title": self.title,
            "sport": self.sport,
            "day": self.day,
            "time": self.time,
            "location": self.location,
            "instructor": self.instructor,
            "period": self.period,
            "prices": [p.to_dict() for p in self.prices],
            "booking_status": self.booking_status,
            "detail_url": self.detail_url,
        }


@dataclass
class Sport:
    """Eine Sportart eines Portals."""

    name: str
    slug: str
    course_count: int = 0
    category: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "slug": self.slug,
            "course_count": self.course_count,
            "category": self.category,
        }
