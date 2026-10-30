"""Buchungs-Vorbereitung und (mit ``--confirm``) Absenden."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from .errors import AuthError, CliError, ForbiddenError, UsageError
from .http_client import HttpClient
from .models import STATUS_BOOKABLE
from .parser import clean
from .portals import Portal

# Env-Namen: REQUIREMENTS + HSPORT_*-Alias (Personendaten).
ENV_FIELDS: dict[str, tuple[str, ...]] = {
    "login_user": ("HS_LOGIN_USER", "HSPORT_LOGIN_USER"),
    "login_password": ("HS_LOGIN_PASSWORD", "HSPORT_LOGIN_PASSWORD"),
    "status_group": ("HS_STATUSGRUPPE", "HSPORT_STATUSGRUPPE"),
    "first_name": ("HSPORT_FIRSTNAME",),
    "last_name": ("HSPORT_LASTNAME",),
    "email": ("HS_BOOKING_EMAIL", "HSPORT_EMAIL"),
    "session_file": ("HS_SESSION_FILE",),
}
_ENV_LOGIN_USER = ENV_FIELDS["login_user"]
_ENV_LOGIN_PASSWORD = ENV_FIELDS["login_password"]
_ENV_STATUS_GROUP = ENV_FIELDS["status_group"]
_ENV_FIRSTNAME = ENV_FIELDS["first_name"]
_ENV_LASTNAME = ENV_FIELDS["last_name"]
_ENV_EMAIL = ENV_FIELDS["email"]
_ENV_SESSION_FILE = ENV_FIELDS["session_file"]


def _env_first(names: tuple[str, ...]) -> str | None:
    for key in names:
        value = os.environ.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


@dataclass
class BookingCredentials:
    login_user: str
    login_password: str
    status_group: str
    first_name: str
    last_name: str
    email: str | None = None
    session_file: str | None = None


@dataclass
class BookingFormPreview:
    action_url: str
    method: str = "post"
    fields: list[dict[str, str]] = field(default_factory=list)
    submit_field: str | None = None
    bookable: bool = False
    requires_login: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_url": self.action_url,
            "method": self.method,
            "fields": self.fields,
            "submit_field": self.submit_field,
            "bookable": self.bookable,
            "requires_login": self.requires_login,
        }


def required_env_field_names() -> list[str]:
    return [
        "HS_LOGIN_USER",
        "HS_LOGIN_PASSWORD",
        "HS_STATUSGRUPPE",
        "HSPORT_FIRSTNAME",
        "HSPORT_LASTNAME",
    ]


def load_booking_credentials(portal_id: str | None = None) -> BookingCredentials:
    """Liest Pflichtwerte: Env zuerst, sonst Config des Portals.

    Fehlt etwas, wird **kein** Request gesendet. Agenten können alle Werte per
    Env setzen; Menschen nutzen vorher ``hsport login``.
    """
    entry: dict[str, Any] = {}
    if portal_id:
        from .config import load_portal

        try:
            entry = load_portal(portal_id)
        except CliError:
            entry = {}

    def value(field: str) -> str | None:
        env_value = _env_first(ENV_FIELDS[field])
        if env_value:
            return env_value
        raw = entry.get(field)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    login_user = value("login_user")
    login_password = value("login_password")
    status_group = value("status_group")
    first_name = value("first_name")
    last_name = value("last_name")
    if not all((login_user, login_password, status_group, first_name, last_name)):
        raise UsageError(
            "Login fehlt – einmal `hsport login` ausführen (oder für Agenten "
            "Env HS_LOGIN_USER, HS_LOGIN_PASSWORD, HS_STATUSGRUPPE, "
            "HSPORT_FIRSTNAME, HSPORT_LASTNAME setzen)."
        )
    return BookingCredentials(
        login_user=login_user,
        login_password=login_password,
        status_group=status_group,
        first_name=first_name,
        last_name=last_name,
        email=value("email"),
        session_file=_env_first(_ENV_SESSION_FILE),
    )


def parse_booking_form(
    sport_html: str,
    course_nr: str,
    base_url: str,
    *,
    booking_status: str,
    mask_csrf: bool = True,
) -> BookingFormPreview:
    """Extrahiert das Buchungsformular der Sportseite für eine Kurszeile."""
    soup = BeautifulSoup(sport_html, "lxml")
    row = soup.find("tr", id=f"K{course_nr}")
    if row is None:
        raise UsageError(f"Kurs {course_nr!r} nicht auf der Sportseite gefunden.")

    submit_name: str | None = None
    cell = row.find("td", class_="bs_sbuch")
    if cell is not None:
        for element in cell.find_all(["input", "button"]):
            name = element.get("name") or ""
            if name.startswith("BS_Kursid_"):
                submit_name = name
                break

    form = None
    if submit_name:
        for candidate in soup.find_all("form"):
            if candidate.find("input", {"name": submit_name}):
                form = candidate
                break
    if form is None:
        form = soup.find("form", action=re.compile(r"anmeldung\.fcgi"))

    action = f"{base_url.rstrip('/')}/cgi/anmeldung.fcgi"
    fields: list[dict[str, str]] = []
    if form is not None:
        raw_action = form.get("action") or action
        if raw_action.startswith("http"):
            action = raw_action
        elif raw_action.startswith("/"):
            action = f"{base_url.rstrip('/')}{raw_action}"
        else:
            action = raw_action
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            value = inp.get("value") or ""
            if mask_csrf and name == "BS_Code":
                value = "<session-token>"
            fields.append({"name": name, "value": value, "type": inp.get("type", "text")})

    bookable = booking_status == STATUS_BOOKABLE and submit_name is not None
    requires_login = any(
        "🔒" in (f.get("value") or "") or "password protected" in (f.get("value") or "").lower()
        for f in fields
        if f.get("name", "").startswith("BS_Kursid_")
    ) or bool(
        cell
        and cell.find(
            "input", attrs={"title": re.compile("password protected", re.I)}
        )
    )

    return BookingFormPreview(
        action_url=action,
        fields=fields,
        submit_field=submit_name,
        bookable=bookable,
        requires_login=requires_login,
    )


def ensure_bookable(booking_status: str, course_nr: str) -> None:
    if booking_status != STATUS_BOOKABLE:
        raise ForbiddenError(
            f"Kurs {course_nr!r} ist nicht buchbar (Status: {booking_status})."
        )


def submit_booking(
    portal: Portal,
    client: HttpClient,
    *,
    sport_name: str,
    course_nr: str,
    booking_status: str,
    credentials: BookingCredentials,
) -> dict[str, Any]:
    """Sendet die Buchung (nur nach erfolgreicher Credential-Validierung)."""
    from .parser import sport_filename
    from .portals import OFFERTS_PATH

    slug = sport_filename(sport_name)
    url = portal.url(f"{OFFERTS_PATH}/{slug}")
    html = client.get_text(url, portal=portal.id)
    form = parse_booking_form(
        html, course_nr, portal.base_url, booking_status=booking_status, mask_csrf=False
    )
    if not form.submit_field:
        raise ForbiddenError("Kein Buchungs-Submit-Feld auf der Sportseite gefunden.")

    payload: dict[str, str] = {}
    for field in form.fields:
        name = field["name"]
        if name.startswith("BS_Kursid_"):
            continue
        payload[name] = field.get("value") or ""
    payload[form.submit_field] = "buchen"

    response_text = client.post_form(form.action_url, payload, portal=portal.id)
    lowered = response_text.casefold()
    if "login" in lowered or "anmelden" in lowered or "/cms/" in lowered:
        raise AuthError(
            "Buchung erfordert eine gültige Portal-Anmeldung.",
            portal=portal.id,
            url=form.action_url,
        )
    return {
        "submitted": True,
        "dry_run": False,
        "action_url": form.action_url,
        "course_nr": course_nr,
        "portal": portal.id,
    }
