"""Kursnr → Sportseite → Detailseite auflösen."""

from __future__ import annotations

from typing import Any

from .errors import UsageError
from .http_client import HttpClient
from .models import Course
from .parser import (
    clean,
    courses_from_search_data,
    parse_course_detail,
    parse_course_rows,
    parse_search_data,
    parse_sport_description,
    sport_filename,
)
from .portals import OFFERTS_PATH, Portal, SEARCH_JS_PATH


def _course_numbers(data: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for raw in data.get("kurse") or []:
        if isinstance(raw, list) and len(raw) > 1:
            out.append(str(raw[1]))
    return out


def suggest_course_numbers(data: dict[str, Any], course_nr: str, limit: int = 5) -> list[str]:
    """Ähnliche Kursnummern für Fehlermeldungen."""
    needle = course_nr.casefold()
    candidates = _course_numbers(data)
    scored: list[tuple[int, str]] = []
    for candidate in candidates:
        cand = candidate.casefold()
        if needle in cand or cand in needle:
            scored.append((0, candidate))
        elif cand.startswith(needle[:3]) or needle.startswith(cand[:3]):
            scored.append((1, candidate))
    scored.sort(key=lambda item: (item[0], item[1]))
    seen: set[str] = set()
    result: list[str] = []
    for _, nr in scored:
        if nr in seen:
            continue
        seen.add(nr)
        result.append(nr)
        if len(result) >= limit:
            break
    return result


def find_course_in_index(data: dict[str, Any], course_nr: str) -> dict[str, Any] | None:
    for raw in data.get("kurse") or []:
        if isinstance(raw, list) and len(raw) > 1 and str(raw[1]) == course_nr:
            return raw
    return None


def load_search_data(portal: Portal, client: HttpClient) -> dict[str, Any]:
    url = portal.url(SEARCH_JS_PATH)
    text = client.get_json_like(url, portal=portal.id)
    return parse_search_data(text)


def resolve_course_row(
    portal: Portal, client: HttpClient, sport_name: str, course_nr: str
) -> Course:
    slug = sport_filename(sport_name)
    url = portal.url(f"{OFFERTS_PATH}/{slug}")
    html = client.get_text(url, portal=portal.id)
    rows = parse_course_rows(html, portal.base_url, sport_name=sport_name)
    for row in rows:
        if row.course_nr == course_nr:
            row.sport_description = parse_sport_description(html)
            return row
    raise UsageError(
        f"Kurs {course_nr!r} nicht auf der Sportseite {sport_name!r} gefunden.",
        portal=portal.id,
        course_nr=course_nr,
    )


def resolve_course(
    portal: Portal, client: HttpClient, course_nr: str
) -> Course:
    data = load_search_data(portal, client)
    raw = find_course_in_index(data, course_nr)
    if raw is None:
        hints = suggest_course_numbers(data, course_nr)
        message = f"Unbekannte Kursnummer: {course_nr!r}."
        if hints:
            message += " Ähnliche Nummern: " + ", ".join(hints) + "."
        raise UsageError(message, portal=portal.id, course_nr=course_nr)

    sport_name = clean(raw[2])
    row = resolve_course_row(portal, client, sport_name, course_nr)

    if not row.detail_url:
        raise UsageError(
            f"Keine Detail-URL für Kurs {course_nr!r} gefunden.",
            portal=portal.id,
            course_nr=course_nr,
        )

    detail_html = client.get_text(row.detail_url, portal=portal.id)
    detail = parse_course_detail(detail_html, portal.base_url, detail_url=row.detail_url)
    if detail is None:
        raise UsageError(
            f"Kursdetail für {course_nr!r} konnte nicht gelesen werden.",
            portal=portal.id,
            course_nr=course_nr,
        )

    detail.booking_status = row.booking_status
    detail.sport = sport_name
    detail.sport_description = row.sport_description
    if not detail.prices and row.prices:
        detail.prices = row.prices
    if not detail.instructor and row.instructor:
        detail.instructor = row.instructor
    if not detail.period and row.period:
        detail.period = row.period
    if not detail.sessions and row.sessions:
        detail.sessions = row.sessions
    return detail


def course_from_index_only(data: dict[str, Any], base_url: str, course_nr: str) -> Course | None:
    """Schneller Zugriff nur aus ``kurssuche.js`` (ohne Sportseite)."""
    for course in courses_from_search_data(data, base_url):
        if course.course_nr == course_nr:
            return course
    return None
