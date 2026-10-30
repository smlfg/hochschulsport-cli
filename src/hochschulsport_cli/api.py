"""Live-Zugriff auf Buchsys-Portale (Sportarten, Kurse, Portal-Checks)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import CliError, EXIT_OK, ParseError, UsageError
from .http_client import HttpClient
from .models import DAY_ALIASES, DAYS, STATUS_BOOKABLE, Course, Sport
from .booking import (
    ensure_bookable,
    load_booking_credentials,
    parse_booking_form,
    required_env_field_names,
    submit_booking,
)
from .course_resolve import resolve_course
from .parser import (
    clean_html,
    courses_from_search_data,
    parse_course_rows,
    parse_search_data,
    parse_sports,
    sport_filename,
)
from .watch_state import (
    EXIT_WATCH_CHANGED,
    load_watch_state,
    read_course_entry,
    save_watch_state,
    write_course_entry,
)
from .portals import (
    DEFAULT_PORTAL_ID,
    OFFERTS_PATH,
    PORTALS,
    Portal,
    SEARCH_JS_PATH,
    resolve_portal,
)


def portal_from_env() -> Portal:
    """--portal > HS_PORTAL > Config-Default > stuttgart."""
    raw = os.environ.get("HS_PORTAL") or os.environ.get("HS_BASE_URL")
    if raw:
        return resolve_portal(raw)
    from .config import load as load_config

    default = load_config().get("default_portal")
    return resolve_portal(default)


def normalize_day(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    day = DAY_ALIASES.get(key)
    if day is None and len(key) == 2:
        candidate = key[:2].title()
        if candidate in DAYS:
            day = candidate
    if day is None:
        raise UsageError(
            f"Ungültiger Wochentag: {raw!r}. Erlaubt: {', '.join(DAYS)}."
        )
    return day


def _normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    return re.sub(r"\s*-\s*", "-", value.strip())


def _course_matches_query(course: Course, query: str) -> bool:
    q = query.casefold()
    hay = " ".join(
        filter(
            None,
            [
                course.course_nr,
                course.title,
                course.sport,
                course.location or "",
                course.instructor or "",
            ],
        )
    ).casefold()
    return q in hay


def _course_matches_sport(course: Course, sport_filter: str) -> bool:
    needle = sport_filter.casefold()
    return needle in (course.sport or "").casefold()


def _apply_course_filters(
    courses: list[Course],
    *,
    query: str | None,
    day: str | None,
    free_only: bool,
    sport_filter: str | None = None,
) -> list[Course]:
    out: list[Course] = []
    for course in courses:
        if day is not None and course.day != day:
            continue
        if free_only and course.booking_status != STATUS_BOOKABLE:
            continue
        if sport_filter is not None and not _course_matches_sport(course, sport_filter):
            continue
        if query is not None and not _course_matches_query(course, query):
            continue
        out.append(course)
    return out


def _portal_is_healthy(html: str, js_text: str | None) -> bool:
    if "bs_kurse" in html or "bs_menu" in html or 'class="bs_menu"' in html:
        return True
    if js_text and '"kurse"' in js_text:
        return True
    if "Nicht erreichbar" in html or "Not available" in html:
        return False
    return False


def check_portal(
    portal: Portal,
    client: HttpClient,
    *,
    portal_id: str | None = None,
) -> dict[str, Any]:
    pid = portal_id or portal.id
    index_url = portal.url(f"{OFFERTS_PATH}/index.html")
    js_url = portal.url(SEARCH_JS_PATH)
    reachable = False
    sports_count = 0
    courses_count = 0
    try:
        index_html = client.get_text(index_url, portal=pid)
        js_text = client.get_json_like(js_url, portal=pid)
        if _portal_is_healthy(index_html, js_text):
            reachable = True
            sports_count = len(parse_sports(index_html))
            data = parse_search_data(js_text)
            courses_count = len(data.get("kurse") or [])
    except CliError:
        reachable = False
    return {
        "id": pid,
        "name": portal.name,
        "base_url": portal.base_url,
        "reachable": reachable,
        "sports": sports_count,
        "courses": courses_count,
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def cmd_portals(client: HttpClient) -> dict[str, Any]:
    items = [check_portal(p, client, portal_id=p.id) for p in PORTALS]
    return {"portals": items, "count": len(items), "default": DEFAULT_PORTAL_ID}


def _sport_name_key(value: str | None) -> str:
    """Sportnamen für Vergleich/Zählung vereinheitlichen (Entities, ``-``)."""
    text = clean_html(value)
    text = re.sub(r"\s*-\s*", "-", text)
    return text.casefold()


def _attach_sport_counts(sports: list[Sport], data: dict[str, Any]) -> list[Sport]:
    counts: dict[str, int] = {}
    for raw in data.get("kurse") or []:
        if isinstance(raw, list) and len(raw) > 2:
            name = _sport_name_key(str(raw[2]))
            counts[name] = counts.get(name, 0) + 1
    for sport in sports:
        sport.course_count = counts.get(_sport_name_key(sport.name), 0)
    return sports


def _load_index_html(portal: Portal, client: HttpClient) -> str:
    url = portal.url(f"{OFFERTS_PATH}/index.html")
    return client.get_text(url, portal=portal.id)


def _load_search_data(portal: Portal, client: HttpClient) -> dict[str, Any]:
    url = portal.url(SEARCH_JS_PATH)
    text = client.get_json_like(url, portal=portal.id)
    return parse_search_data(text)


def cmd_sports(
    portal: Portal,
    client: HttpClient,
    *,
    query: str | None = None,
) -> dict[str, Any]:
    index_html = _load_index_html(portal, client)
    sports = parse_sports(index_html)
    try:
        data = _load_search_data(portal, client)
        sports = _attach_sport_counts(sports, data)
    except ParseError:
        pass
    if query:
        q = query.casefold()
        sports = [s for s in sports if q in s.name.casefold()]
    return {
        "portal": portal.id,
        "query": query,
        "sports": [s.to_dict() for s in sports],
        "count": len(sports),
    }


def _load_sport_page(
    portal: Portal, client: HttpClient, sport_name: str
) -> list[Course]:
    slug = sport_filename(sport_name)
    url = portal.url(f"{OFFERTS_PATH}/{slug}")
    html = client.get_text(url, portal=portal.id)
    courses = parse_course_rows(html, portal.base_url, sport_name=sport_name)
    if not courses and sport_name:
        raise UsageError(f"Unbekannte Sportart: {sport_name!r}.")
    for course in courses:
        course.time = _normalize_time(course.time)
    return courses


def _match_sports(sports: list[Sport], name: str) -> list[Sport]:
    """Sportarten zu einem Namen auflösen: exakt vor case-insensitiv vor Substring."""
    raw = name.strip()
    if not raw:
        return []
    exact = [sport for sport in sports if sport.name == raw]
    if exact:
        return exact
    folded = _sport_name_key(raw)
    exact_ci = [sport for sport in sports if _sport_name_key(sport.name) == folded]
    if exact_ci:
        return exact_ci
    return [sport for sport in sports if folded in _sport_name_key(sport.name)]


def _load_sport_pages_by_name(
    portal: Portal, client: HttpClient, sport_name: str
) -> list[Course]:
    """Positionalen Sportnamen gegen die Sportartenliste auflösen.

    ``yoga`` soll auch dann funktionieren, wenn keine Sportseite exakt
    ``_yoga.html`` heißt. Exakte Namen (auch case-insensitiv) gewinnen; sonst
    werden alle passenden Sportseiten geladen. Kein Treffer -> UsageError.
    """
    sports = parse_sports(_load_index_html(portal, client))
    matches = _match_sports(sports, sport_name)
    if not matches:
        raise UsageError(
            f"Unbekannte Sportart: {sport_name!r}. "
            f"Mit 'hsport sports --query {sport_name}' passende Namen finden "
            "oder --sport/--query verwenden."
        )
    courses: list[Course] = []
    seen: set[str] = set()
    for sport in matches:
        try:
            rows = _load_sport_page(portal, client, sport.name)
        except UsageError:
            continue
        for course in rows:
            if course.course_nr in seen:
                continue
            seen.add(course.course_nr)
            courses.append(course)
    return courses


def _enrich_from_sport_pages(
    portal: Portal,
    client: HttpClient,
    courses: list[Course],
) -> list[Course]:
    """Status und Detail-URL aus den jeweiligen Sportseiten ergänzen.

    ``kurssuche.js`` enthält nur ein buchbar-Ja/Nein und keine Detail-Hex-ID.
    Die Sportseiten liefern beides pro Kursnummer – auch für Kurse auf
    Warteliste, die in der Suche sonst fälschlich als nicht buchbar gelten.
    """
    by_sport: dict[str, list[Course]] = {}
    for course in courses:
        if not course.sport:
            continue
        by_sport.setdefault(course.sport, []).append(course)
    status_map: dict[str, str] = {}
    detail_map: dict[str, str] = {}
    for sport_name in by_sport:
        try:
            rows = _load_sport_page(portal, client, sport_name)
        except (UsageError, CliError):
            continue
        for row in rows:
            status_map[row.course_nr] = row.booking_status
            if row.detail_url:
                detail_map[row.course_nr] = row.detail_url
    enriched: list[Course] = []
    for course in courses:
        status = status_map.get(course.course_nr)
        if status is not None:
            course.booking_status = status
        if course.detail_url is None:
            course.detail_url = detail_map.get(course.course_nr)
        enriched.append(course)
    return enriched


def cmd_courses(
    portal: Portal,
    client: HttpClient,
    *,
    sport: str | None = None,
    sport_filter: str | None = None,
    query: str | None = None,
    day: str | None = None,
    free_only: bool = False,
) -> dict[str, Any]:
    if sport and query:
        raise UsageError("Nur eine von Sportname oder --query angeben.")
    if not sport and not query and not sport_filter:
        raise UsageError("Sportname, --sport oder --query ist erforderlich.")

    day_norm = normalize_day(day)

    if sport:
        courses = _load_sport_pages_by_name(portal, client, sport)
        courses = _apply_course_filters(
            courses,
            query=None,
            day=day_norm,
            free_only=free_only,
            sport_filter=sport_filter,
        )
    else:
        data = _load_search_data(portal, client)
        courses = courses_from_search_data(data, portal.base_url)
        for course in courses:
            course.time = _normalize_time(course.time)
        courses = _apply_course_filters(
            courses,
            query=query,
            day=day_norm,
            free_only=False,
            sport_filter=sport_filter,
        )
        courses = _enrich_from_sport_pages(portal, client, courses)
        if free_only:
            courses = [c for c in courses if c.booking_status == STATUS_BOOKABLE]

    return {
        "portal": portal.id,
        "sport": sport,
        "query": query,
        "filters": {
            "day": day_norm,
            "free_only": free_only,
            "sport": sport_filter,
        },
        "courses": [c.to_dict() for c in courses],
        "count": len(courses),
    }


def cmd_course(
    portal: Portal,
    client: HttpClient,
    *,
    course_nr: str,
) -> dict[str, Any]:
    course = resolve_course(portal, client, course_nr)
    return {"portal": portal.id, **course.to_detail_dict()}


def cmd_watch(
    portal: Portal,
    client: HttpClient,
    *,
    course_nr: str,
    state_file: Path | None = None,
) -> tuple[dict[str, Any], int]:
    course = resolve_course(portal, client, course_nr)
    state = load_watch_state(state_file)
    previous = read_course_entry(state, portal.id, course_nr)
    changed = False
    previous_status = None
    if previous is None:
        changed = False
    elif previous.get("booking_status") != course.booking_status:
        changed = True
        previous_status = previous.get("booking_status")

    write_course_entry(
        state,
        portal_id=portal.id,
        course_nr=course_nr,
        booking_status=course.booking_status,
    )
    save_watch_state(state, state_file)

    payload: dict[str, Any] = {
        "portal": portal.id,
        "course_nr": course_nr,
        "booking_status": course.booking_status,
        "changed": changed,
    }
    if previous_status is not None:
        payload["previous_status"] = previous_status
    exit_code = EXIT_WATCH_CHANGED if changed else EXIT_OK
    return payload, exit_code


def cmd_book(
    portal: Portal,
    client: HttpClient,
    *,
    course_nr: str,
    confirm: bool = False,
) -> dict[str, Any]:
    if confirm:
        credentials = load_booking_credentials()
    else:
        credentials = None

    course = resolve_course(portal, client, course_nr)
    ensure_bookable(course.booking_status, course_nr)

    slug = sport_filename(course.sport)
    sport_url = portal.url(f"{OFFERTS_PATH}/{slug}")
    sport_html = client.get_text(sport_url, portal=portal.id)
    form = parse_booking_form(
        sport_html,
        course_nr,
        portal.base_url,
        booking_status=course.booking_status,
        mask_csrf=not confirm,
    )

    payload: dict[str, Any] = {
        "portal": portal.id,
        "course_nr": course_nr,
        "title": course.title,
        "booking_status": course.booking_status,
        "prices": [p.to_dict() for p in course.prices],
        "bookable": form.bookable,
        "dry_run": not confirm,
        "submitted": False,
        "form": form.to_dict(),
        "required_env": required_env_field_names(),
        "would_submit": {
            "method": form.method,
            "action_url": form.action_url,
            "fields": [f["name"] for f in form.fields],
            "submit_field": form.submit_field,
        },
    }

    if confirm:
        assert credentials is not None
        result = submit_booking(
            portal,
            client,
            sport_name=course.sport,
            course_nr=course_nr,
            booking_status=course.booking_status,
            credentials=credentials,
        )
        payload.update(result)
    return payload
