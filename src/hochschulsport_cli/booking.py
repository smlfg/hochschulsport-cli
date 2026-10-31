"""Buchungs-Vorbereitung und (mit ``--confirm``) Absenden."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .errors import AuthError, CliError, ForbiddenError, ParseError, UsageError
from .http_client import HttpClient
from .models import STATUS_BOOKABLE
from .portals import Portal

# Env-Namen: REQUIREMENTS + HSPORT_*-Alias (Personendaten).
ENV_FIELDS: dict[str, tuple[str, ...]] = {
    "login_user": ("HS_LOGIN_USER", "HSPORT_LOGIN_USER"),
    "login_password": ("HS_LOGIN_PASSWORD", "HSPORT_LOGIN_PASSWORD"),
    "status_group": ("HS_STATUSGRUPPE", "HSPORT_STATUSGRUPPE"),
    "first_name": ("HSPORT_FIRSTNAME",),
    "last_name": ("HSPORT_LASTNAME",),
    "email": ("HS_BOOKING_EMAIL", "HSPORT_EMAIL"),
    "street": ("HSPORT_STREET", "HS_BOOKING_STREET"),
    "city": ("HSPORT_CITY", "HS_BOOKING_CITY"),
    "phone": ("HSPORT_PHONE", "HS_BOOKING_PHONE"),
    "matrikel": ("HSPORT_MATRIKEL", "HS_BOOKING_MATRIKEL"),
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
    street: str | None = None
    city: str | None = None
    phone: str | None = None
    matrikel: str | None = None
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
        "HS_BOOKING_EMAIL",
    ]


REQUIRED_CREDENTIAL_LABELS: tuple[tuple[str, str], ...] = (
    ("login_user", "E-Mail/Login"),
    ("login_password", "Passwort"),
    ("status_group", "Statusgruppe"),
    ("first_name", "Vorname"),
    ("last_name", "Nachname"),
    ("email", "E-Mail"),
)


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

    def optional(env_names: tuple[str, ...], *config_keys: str) -> str | None:
        env_value = _env_first(env_names)
        if env_value:
            return env_value
        for key in config_keys:
            raw = entry.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
        return None

    values = {field: value(field) for field, _label in REQUIRED_CREDENTIAL_LABELS}
    login_user = values["login_user"]
    if not values["email"] and login_user and "@" in login_user:
        # Der Login ist bei Buchsys häufig die E-Mail-Adresse.
        values["email"] = login_user
    missing = [
        label
        for field, label in REQUIRED_CREDENTIAL_LABELS
        if not values.get(field)
    ]
    if missing:
        raise UsageError(_missing_message(missing))
    return BookingCredentials(
        login_user=str(values["login_user"]),
        login_password=str(values["login_password"]),
        status_group=str(values["status_group"]),
        first_name=str(values["first_name"]),
        last_name=str(values["last_name"]),
        email=str(values["email"]),
        street=optional(ENV_FIELDS["street"], "street", "strasse"),
        city=optional(ENV_FIELDS["city"], "city", "ort"),
        phone=optional(ENV_FIELDS["phone"], "phone", "telefon"),
        matrikel=optional(ENV_FIELDS["matrikel"], "matrikel", "matrikelnummer"),
        session_file=_env_first(_ENV_SESSION_FILE),
    )


@dataclass
class ParsedForm:
    action_url: str
    method: str = "post"
    fields: list[dict[str, Any]] = field(default_factory=list)
    submit_name: str | None = None
    submit_value: str | None = None


def _absolute_url(raw: str | None, base_url: str) -> str:
    value = (raw or "").strip()
    if not value:
        return base_url.rstrip("/")
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/"):
        return f"{base_url.rstrip('/')}{value}"
    return urljoin(f"{base_url.rstrip('/')}/", value)


def _parse_forms(html: str, base_url: str) -> list[ParsedForm]:
    soup = BeautifulSoup(html, "lxml")
    forms: list[ParsedForm] = []
    for form in soup.find_all("form"):
        fields: list[dict[str, Any]] = []
        for element in form.find_all(["input", "select", "textarea", "button"]):
            name = element.get("name")
            if not name:
                continue
            tag = element.name
            kind = (element.get("type") or ("submit" if tag == "button" else "text")).lower()
            if tag == "select":
                options = []
                for option in element.find_all("option"):
                    value = option.get("value")
                    if value is None:
                        value = option.get_text(strip=True)
                    options.append(
                        {
                            "value": value,
                            "text": option.get_text(strip=True),
                            "selected": option.has_attr("selected"),
                        }
                    )
                selected = next((o for o in options if o["selected"]), options[0] if options else None)
                fields.append(
                    {
                        "name": name,
                        "value": selected["value"] if selected else "",
                        "type": "select",
                        "options": options,
                        "required": element.has_attr("required"),
                    }
                )
            elif tag == "textarea":
                fields.append(
                    {
                        "name": name,
                        "value": element.get_text(),
                        "type": "textarea",
                        "required": element.has_attr("required"),
                    }
                )
            else:
                fields.append(
                    {
                        "name": name,
                        "value": element.get("value") or "",
                        "type": kind,
                        "checked": element.has_attr("checked"),
                        "required": element.has_attr("required"),
                    }
                )
        submit = next(
            (f for f in fields if f["type"] in ("submit", "image")),
            None,
        )
        forms.append(
            ParsedForm(
                action_url=_absolute_url(form.get("action"), base_url),
                method=(form.get("method") or "post").lower(),
                fields=fields,
                submit_name=submit["name"] if submit else None,
                submit_value=submit["value"] if submit else None,
            )
        )
    return forms


def _form_payload(form: ParsedForm, fields: list[dict[str, Any]] | None = None) -> dict[str, str]:
    payload: dict[str, str] = {}
    for item in fields if fields is not None else form.fields:
        kind = item.get("type")
        if kind in ("submit", "image", "button", "reset"):
            continue
        if kind in ("checkbox", "radio") and not item.get("checked"):
            continue
        payload[str(item["name"])] = str(item.get("value") or "")
    if form.submit_name:
        payload[form.submit_name] = form.submit_value or ""
    return payload


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
        action = _absolute_url(form.get("action"), base_url)
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


PERSON_FIELD_MAP: dict[str, str] = {
    "statusorig": "status_group",
    "statusgruppe": "status_group",
    "vorname": "first_name",
    "firstname": "first_name",
    "name": "last_name",
    "nachname": "last_name",
    "lastname": "last_name",
    "email": "email",
    "mail": "email",
    "e-mail": "email",
    "strasse": "street",
    "street": "street",
    "ort": "city",
    "city": "city",
    "telefon": "phone",
    "phone": "phone",
    "matrikel": "matrikel",
    "matrikelnummer": "matrikel",
    "matrikelnr": "matrikel",
}

LOGIN_MARKERS = ("login", "anmelden", "/cms/")
CONFIRM_MARKERS = (
    "buchungsbestätigung",
    "buchung bestätigt",
    "verbindlich gebucht",
    "ist verbindlich",
    "buchungsnummer",
    "buchungs-nr",
    "buchungsnr",
)


def _first_form(forms: list[ParsedForm], predicate) -> ParsedForm | None:
    for form in forms:
        if predicate(form):
            return form
    return None


def _field_names(form: ParsedForm) -> set[str]:
    return {str(item["name"]).casefold() for item in form.fields}


def _is_person_form(form: ParsedForm) -> bool:
    names = _field_names(form)
    return bool(names & {"statusorig", "statusgruppe", "vorname", "name", "nachname", "email", "tnbed"})


def _is_overview_form(form: ParsedForm) -> bool:
    names = _field_names(form)
    if "fid" in names:
        return True
    text = f"{form.submit_value or ''} {form.submit_name or ''}".casefold()
    return "verbindlich" in text


def _select_value(field: dict[str, Any], desired: str) -> str:
    wanted = desired.strip()
    options = field.get("options") or []
    for option in options:
        if str(option.get("value", "")) == wanted:
            return str(option.get("value", ""))
    for option in options:
        if str(option.get("text", "")).casefold() == wanted.casefold():
            return str(option.get("value", ""))
    for option in options:
        text = str(option.get("text", "")).casefold()
        if wanted.casefold() in text or text in wanted.casefold():
            return str(option.get("value", ""))
    return wanted


def _fill_person_form(
    form: ParsedForm, credentials: BookingCredentials
) -> list[dict[str, Any]]:
    fields = [dict(item) for item in form.fields]
    for item in fields:
        key = str(item["name"]).casefold()
        if key == "tnbed":
            item["checked"] = True
            if not item.get("value"):
                item["value"] = "1"
            continue
        attribute = PERSON_FIELD_MAP.get(key)
        if attribute is None:
            continue
        desired = getattr(credentials, attribute, None)
        if not desired:
            continue
        if item.get("type") == "select":
            item["value"] = _select_value(item, str(desired))
        else:
            item["value"] = str(desired)
    return fields


def _missing_required(fields: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for item in fields:
        kind = item.get("type")
        if kind in ("submit", "image", "button", "reset"):
            continue
        if not item.get("required"):
            continue
        if kind in ("checkbox", "radio"):
            if not item.get("checked"):
                missing.append(str(item["name"]))
        elif not str(item.get("value") or "").strip():
            missing.append(str(item["name"]))
    return list(dict.fromkeys(missing))


def _missing_message(missing: list[str]) -> str:
    return (
        f"Für die Buchung fehlt: {', '.join(missing)} – "
        "`hsport login` ausführen"
    )


def _looks_like_login(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in LOGIN_MARKERS)


def _is_confirmation(text: str) -> bool:
    lowered = text.casefold()
    return any(marker in lowered for marker in CONFIRM_MARKERS)


def _booking_number(text: str) -> str | None:
    match = re.search(
        r"(?:buchungsnummer|buchungs-nr\.?|buchungsnr\.?|bestellnummer)"
        r"\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9._/-]*)",
        text,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _flow_error(
    exc_type,
    message: str,
    *,
    portal: Portal,
    steps: list[str],
    step: str,
    submitted: bool,
    url: str | None = None,
):
    return exc_type(
        message,
        portal=portal.id,
        url=url,
        extra={
            "submitted": submitted,
            "confirmed": False,
            "steps": list(steps),
            "step": step,
        },
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
    """Sendet alle Buchungsschritte bis zur verbindlichen Bestätigung.

    Erst ``kurs_waehlen`` liefert das Personendaten-Formular, dann ``daten``
    die Übersicht und schließlich ``verbindlich`` die Bestätigung. Ein Erfolg
    wird nur gemeldet, wenn die letzte Antwort eindeutig eine Buchung
    bestätigt.
    """
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
    for item in form.fields:
        name = item["name"]
        if name.startswith("BS_Kursid_"):
            continue
        payload[name] = item.get("value") or ""
    payload[form.submit_field] = "buchen"

    steps: list[str] = []
    response_text = client.post_form(form.action_url, payload, portal=portal.id)
    steps.append("kurs_waehlen")
    if _looks_like_login(response_text):
        raise _flow_error(
            AuthError,
            "Buchung erfordert eine gültige Portal-Anmeldung.",
            portal=portal,
            steps=steps,
            step="kurs_waehlen",
            submitted=False,
            url=form.action_url,
        )

    person_form = _first_form(
        _parse_forms(response_text, portal.base_url), _is_person_form
    )
    if person_form is None:
        raise _flow_error(
            ParseError,
            "Antwort auf die Kursauswahl enthält kein Personendaten-Formular.",
            portal=portal,
            steps=steps,
            step="daten",
            submitted=False,
            url=form.action_url,
        )

    filled = _fill_person_form(person_form, credentials)
    missing = _missing_required(filled)
    if missing:
        raise _flow_error(
            UsageError,
            _missing_message(missing),
            portal=portal,
            steps=steps,
            step="daten",
            submitted=False,
            url=person_form.action_url,
        )

    response_text = client.post_form(
        person_form.action_url,
        _form_payload(person_form, filled),
        portal=portal.id,
    )
    steps.append("daten")
    if _looks_like_login(response_text):
        raise _flow_error(
            AuthError,
            "Portal-Anmeldung beim Absenden der Personendaten abgelehnt.",
            portal=portal,
            steps=steps,
            step="daten",
            submitted=False,
            url=person_form.action_url,
        )

    overview_form = _first_form(
        _parse_forms(response_text, portal.base_url), _is_overview_form
    )
    if overview_form is None:
        raise _flow_error(
            ParseError,
            "Antwort auf die Personendaten enthält keine Buchungsübersicht "
            "mit verbindlichem Buchen.",
            portal=portal,
            steps=steps,
            step="verbindlich",
            submitted=False,
            url=person_form.action_url,
        )

    response_text = client.post_form(
        overview_form.action_url,
        _form_payload(overview_form),
        portal=portal.id,
    )
    steps.append("verbindlich")

    if _is_confirmation(response_text):
        number = _booking_number(response_text)
        return {
            "submitted": True,
            "confirmed": True,
            "dry_run": False,
            "steps": steps,
            "buchungsnummer": number,
            "action_url": overview_form.action_url,
            "course_nr": course_nr,
            "portal": portal.id,
        }

    if _looks_like_login(response_text):
        raise _flow_error(
            AuthError,
            "Portal-Anmeldung beim verbindlichen Buchen abgelehnt.",
            portal=portal,
            steps=steps,
            step="verbindlich",
            submitted=True,
            url=overview_form.action_url,
        )

    raise _flow_error(
        ParseError,
        "Antwort auf das verbindliche Buchen ist keine Buchungsbestätigung.",
        portal=portal,
        steps=steps,
        step="verbindlich",
        submitted=True,
        url=overview_form.action_url,
    )
