"""Live-Zugriff auf Buchsys-Portale (Sportarten, Kurse, Portal-Checks)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .errors import CliError, ParseError
from .http_client import HttpClient
from .models import Sport
from .parser import parse_search_data, parse_sports
from .portals import (
    DEFAULT_PORTAL_ID,
    OFFERTS_PATH,
    PORTALS,
    Portal,
    SEARCH_JS_PATH,
    resolve_portal,
)


def portal_from_env() -> Portal:
    raw = os.environ.get("HS_PORTAL") or os.environ.get("HS_BASE_URL")
    return resolve_portal(raw)


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


def _attach_sport_counts(sports: list[Sport], data: dict[str, Any]) -> list[Sport]:
    counts: dict[str, int] = {}
    for raw in data.get("kurse") or []:
        if isinstance(raw, list) and len(raw) > 2:
            name = str(raw[2])
            counts[name] = counts.get(name, 0) + 1
    for sport in sports:
        sport.course_count = counts.get(sport.name, 0)
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
