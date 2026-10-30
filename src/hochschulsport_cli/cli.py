"""CLI-Einstieg: ``hsport`` mit zentraler JSON-Fehlerbehandlung."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from typing import Any, Callable

from . import __version__
from . import config as config_mod
from . import prompts
from pathlib import Path

from .api import (
    cmd_book,
    cmd_course,
    cmd_courses,
    cmd_portals,
    cmd_sports,
    cmd_watch,
    load_courses_for_sport,
    portal_from_env,
)
from .booking import ENV_FIELDS
from .course_resolve import resolve_course
from .errors import CliError, EXIT_OK, EXIT_USAGE, UsageError
from .http_client import HttpClient
from .models import STATUS_BOOKABLE, Course
from .portals import DEFAULT_PORTAL_ID, PORTALS_BY_ID, Portal, resolve_portal


def _emit(payload: dict[str, Any], as_json: bool, text: str | None = None) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    elif text is not None:
        sys.stdout.write(text + "\n")
    else:
        sys.stdout.write(_payload_to_text(payload) + "\n")


def _fail(exc: CliError, as_json: bool) -> int:
    payload = exc.to_dict()
    if as_json:
        sys.stderr.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        err = payload["error"]
        sys.stderr.write(f"[{err['kind']}] {err['message']}\n")
    return exc.exit_code


def _payload_to_text(payload: dict[str, Any]) -> str:
    if "portals" in payload:
        lines = [f"Portale ({payload.get('count', 0)}), Default: {payload.get('default')}"]
        for p in payload.get("portals") or []:
            flag = "ok" if p.get("reachable") else "offline"
            lines.append(
                f"  {p.get('id')}: {p.get('name')} [{flag}] "
                f"sports={p.get('sports')} courses={p.get('courses')}"
            )
        current = payload.get("current") or payload.get("default") or DEFAULT_PORTAL_ID
        source = payload.get("source") or "Standard"
        lines.append("")
        lines.append(
            f"Default ändern: hsport config portal {current}  "
            f"(aktuell: {current}, Quelle: {source})"
        )
        if payload.get("hint"):
            lines.append(str(payload["hint"]))
        return "\n".join(lines) + "\n"
    if "sports" in payload:
        lines = [f"Sportarten ({payload.get('count', 0)}) – Portal {payload.get('portal')}"]
        for s in payload.get("sports") or []:
            lines.append(
                f"  {s.get('name')} ({s.get('course_count', 0)} Kurse) → {s.get('slug')}"
            )
        return "\n".join(lines) + "\n"
    if "courses" in payload:
        lines = [
            f"Kurse ({payload.get('count', 0)}) – Portal {payload.get('portal')}"
        ]
        sport_filter = (payload.get("filters") or {}).get("sport")
        if payload.get("sport"):
            lines[0] += f", Sport {payload['sport']}"
        elif sport_filter:
            lines[0] += f", Sportfilter „{sport_filter}“"
        if payload.get("query"):
            lines[0] += f", Suche „{payload['query']}“"
        for c in payload.get("courses") or []:
            lines.append(
                f"  {c.get('course_nr')}: {c.get('title')} | {c.get('day')} "
                f"{c.get('time')} | {c.get('booking_status')}"
            )
        return "\n".join(lines) + "\n"
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


STATUS_GROUP_CHOICES = (
    ("1", "Studierende"),
    ("2", "Beschäftigte"),
    ("3", "Externe"),
)


def _env_first(names: tuple[str, ...]) -> str | None:
    for key in names:
        value = os.environ.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _portal_source(explicit: str | None) -> str:
    """Woher der aktive Default kommt: ``--portal``, Env, Config oder Standard."""
    if explicit:
        return "--portal"
    if _env_first(("HS_PORTAL", "HS_BASE_URL")):
        return "HS_PORTAL"
    try:
        if config_mod.load().get("default_portal"):
            return "config"
    except CliError:
        return "Standard"
    return "Standard"


def _credential_value(portal_id: str, field: str) -> tuple[str | None, str | None]:
    env_value = _env_first(ENV_FIELDS.get(field, ()))
    if env_value:
        return env_value, "env"
    try:
        entry = config_mod.load_portal(portal_id)
    except CliError:
        entry = {}
    value = entry.get(field)
    if isinstance(value, str) and value.strip():
        return value.strip(), "config"
    return None, None


def _status_group(portal_id: str) -> str | None:
    return _credential_value(portal_id, "status_group")[0]


def _display_name(portal_id: str) -> str | None:
    first = _credential_value(portal_id, "first_name")[0]
    last = _credential_value(portal_id, "last_name")[0]
    name = " ".join(part for part in (first, last) if part)
    return name or None


def _password_info(portal_id: str) -> dict[str, Any]:
    env_password = _env_first(ENV_FIELDS["login_password"])
    if env_password:
        return {"stored": True, "store": "env", "source": "env"}
    try:
        entry = config_mod.load_portal(portal_id)
    except CliError:
        entry = {}
    password = entry.get("login_password")
    store = entry.get("password_store")
    if password:
        if store not in ("keyring", "file"):
            store = "file"
        return {"stored": True, "store": store, "source": "config"}
    return {"stored": False, "store": None, "source": None}


def _password_label(info: dict[str, Any]) -> str:
    if not info.get("stored"):
        return "fehlt"
    store = info.get("store")
    if store == "env":
        return "gespeichert (env)"
    if store == "keyring":
        return "gespeichert (keyring)"
    return "gespeichert (Datei)"


def _ask_status_group(existing: str | None) -> str:
    default_index = "1"
    if existing:
        raw = existing.strip()
        if raw in {index for index, _ in STATUS_GROUP_CHOICES}:
            default_index = raw
        else:
            for index, label in STATUS_GROUP_CHOICES:
                if raw.casefold() == label.casefold():
                    default_index = index
                    break
    sys.stdout.write("Statusgruppe:\n")
    for index, label in STATUS_GROUP_CHOICES:
        sys.stdout.write(f"  {index}) {label}\n")
    while True:
        raw = prompts.ask("Auswahl", default=default_index).strip()
        if not raw:
            raw = default_index
        for index, label in STATUS_GROUP_CHOICES:
            if raw == index or raw.casefold() == label.casefold():
                return label
        sys.stderr.write("Ungültige Auswahl. Bitte 1, 2 oder 3.\n")


def _login_interactive(portal: Portal) -> dict[str, Any]:
    existing = config_mod.load_portal(portal.id)
    sys.stdout.write(f"Login für {portal.name} ({portal.id})\n")
    login_user = prompts.ask("E-Mail/Login", default=existing.get("login_user")).strip()
    if not login_user:
        raise UsageError("Login darf nicht leer sein.")
    password = prompts.ask_secret("Passwort")
    first_name = prompts.ask("Vorname", default=existing.get("first_name")).strip()
    last_name = prompts.ask("Nachname", default=existing.get("last_name")).strip()
    if not first_name:
        raise UsageError("Vorname darf nicht leer sein.")
    if not last_name:
        raise UsageError("Nachname darf nicht leer sein.")
    status_group = _ask_status_group(existing.get("status_group"))
    if not password and not existing.get("login_password"):
        raise UsageError("Passwort darf nicht leer sein.")

    values: dict[str, Any] = {
        "login_user": login_user,
        "status_group": status_group,
        "first_name": first_name,
        "last_name": last_name,
    }
    if password:
        values["login_password"] = password
    entry = config_mod.save_portal(portal.id, values)
    return {
        "portal": portal.id,
        "portal_name": portal.name,
        "saved": True,
        "login_user": login_user,
        "first_name": first_name,
        "last_name": last_name,
        "status_group": status_group,
        "password_store": entry.get("password_store"),
    }


def _cmd_login(portal: Portal, as_json: bool) -> int:
    if not prompts.is_tty():
        raise UsageError(
            "hsport login braucht ein Terminal; für Agenten Env-Variablen "
            "HS_LOGIN_USER … setzen"
        )
    payload = _login_interactive(portal)
    _emit(payload, as_json, text=f"Login für {portal.name} gespeichert.")
    return EXIT_OK


def _cmd_logout(portal: Portal, as_json: bool) -> int:
    config_mod.clear(portal.id)
    payload = {"portal": portal.id, "cleared": True}
    _emit(payload, as_json, text=f"Login für {portal.name} gelöscht.")
    return EXIT_OK


def _format_whoami(payload: dict[str, Any]) -> str:
    sources = payload.get("sources") or {}

    def source(field: str) -> str:
        return sources.get(field) or "fehlt"

    lines = [
        f"Portal: {payload.get('portal')} ({payload.get('portal_name')})",
        f"Login: {payload.get('login_user') or '–'} ({source('login_user')})",
        f"Name: {payload.get('name') or '–'} ({source('first_name')}/{source('last_name')})",
        f"Statusgruppe: {payload.get('status_group') or '–'} ({source('status_group')})",
        f"E-Mail: {payload.get('email') or '–'} ({source('email')})",
        f"Passwort: {payload.get('password') or 'fehlt'}",
    ]
    return "\n".join(lines)


def _cmd_whoami(portal: Portal, as_json: bool) -> int:
    values: dict[str, Any] = {}
    sources: dict[str, Any] = {}
    for field in ("login_user", "status_group", "first_name", "last_name", "email"):
        value, origin = _credential_value(portal.id, field)
        values[field] = value
        sources[field] = origin
    password = _password_info(portal.id)
    sources["login_password"] = password.get("source")
    first_name = values.get("first_name")
    last_name = values.get("last_name")
    name = " ".join(part for part in (first_name, last_name) if part) or None
    payload = {
        "portal": portal.id,
        "portal_name": portal.name,
        "login_user": values.get("login_user"),
        "name": name,
        "first_name": first_name,
        "last_name": last_name,
        "status_group": values.get("status_group"),
        "email": values.get("email"),
        "password": _password_label(password),
        "password_store": password.get("store"),
        "sources": sources,
    }
    _emit(payload, as_json, text=_format_whoami(payload))
    return EXIT_OK


def _format_config(payload: dict[str, Any]) -> str:
    default = payload.get("default_portal")
    lines = [
        f"Config: {payload.get('config_path')}",
        f"Default-Portal: {default or '(nicht gesetzt)'}",
        f"Aktives Portal: {payload.get('resolved_portal') or DEFAULT_PORTAL_ID}",
    ]
    portals = payload.get("portals") or {}
    if not portals:
        lines.append("Portale: (keine gespeichert)")
        return "\n".join(lines)
    lines.append("Portale:")
    for portal_id, entry in portals.items():
        parts = [f"Login {entry.get('login_user') or '–'}"]
        if entry.get("status_group"):
            parts.append(f"Statusgruppe {entry['status_group']}")
        parts.append(f"Passwort {entry.get('password') or 'fehlt'}")
        lines.append(f"  {portal_id}: " + ", ".join(parts))
    return "\n".join(lines)


def _cmd_config_show(as_json: bool) -> int:
    config = config_mod.load()
    default = config.get("default_portal")
    try:
        resolved = resolve_portal(default).id
    except CliError:
        resolved = DEFAULT_PORTAL_ID
    portals: dict[str, Any] = {}
    for portal_id, entry in config["portals"].items():
        item = {key: value for key, value in entry.items() if key != "login_password"}
        if entry.get("password_store") == "keyring":
            item["password"] = "gespeichert (keyring)"
        elif entry.get("login_password") or entry.get("password_store") == "file":
            item["password"] = "gespeichert (Datei)"
        else:
            item["password"] = "fehlt"
        portals[portal_id] = item
    payload = {
        "default_portal": default,
        "resolved_portal": resolved,
        "config_path": str(config_mod.config_path()),
        "portals": portals,
    }
    _emit(payload, as_json, text=_format_config(payload))
    return EXIT_OK


def _cmd_config_portal(portal_id: str, as_json: bool) -> int:
    value = (portal_id or "").strip()
    if (
        value
        and value not in PORTALS_BY_ID
        and "://" not in value
        and "." not in value
        and "/" not in value
    ):
        raise UsageError(
            f"Unbekanntes Portal {value!r} – `hsport portals` zeigt alle IDs "
            "(oder volle Buchsys-URL angeben)"
        )
    portal = resolve_portal(portal_id)
    config = config_mod.load()
    config["default_portal"] = portal.id
    config_mod.save(config)
    payload = {
        "default_portal": portal.id,
        "portal_name": portal.name,
        "config_path": str(config_mod.config_path()),
    }
    _emit(payload, as_json, text=f"Default-Portal: {portal.id} ({portal.name})")
    return EXIT_OK


def _format_eur(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:.2f}".replace(".", ",") + " €"


def _price_label(course: Course, status_group: str | None) -> str:
    if not course.prices:
        return "Preis unbekannt"
    if status_group:
        needle = status_group.strip().casefold()
        needle = {
            "1": "studierende",
            "2": "beschäftigte",
            "3": "externe",
        }.get(needle, needle)
        for price in course.prices:
            group = (price.group or "").strip()
            folded = group.casefold()
            if folded and (folded == needle or needle in folded or folded in needle):
                return f"{_format_eur(price.price_eur)} ({group})"
    labels = []
    for price in course.prices:
        amount = _format_eur(price.price_eur)
        labels.append(f"{amount} ({price.group})" if price.group else amount)
    return ", ".join(labels)


def _course_choice_line(
    index: int, course: Course, status_group: str | None
) -> str:
    title = course.title or course.sport or ""
    day_time = " ".join(part for part in (course.day, course.time) if part) or "–"
    return (
        f"[{index}] {course.course_nr} {title} | {day_time} | "
        f"{course.location or '–'} | {_price_label(course, status_group)} | "
        f"{course.booking_status}"
    )


def _print_course_choices(courses: list[Course], status_group: str | None) -> None:
    for index, course in enumerate(courses, 1):
        sys.stdout.write(_course_choice_line(index, course, status_group) + "\n")


def _choose_course(
    courses: list[Course], status_group: str | None
) -> Course | None:
    _print_course_choices(courses, status_group)
    raw = prompts.ask("Nummer wählen [1-n, Enter=Abbruch]").strip()
    if not raw:
        return None
    try:
        index = int(raw)
    except ValueError:
        raise UsageError("Ungültige Auswahl: bitte eine Nummer aus der Liste angeben.")
    if index < 1 or index > len(courses):
        raise UsageError(f"Ungültige Auswahl: 1–{len(courses)} erwartet.")
    return courses[index - 1]


def _decorate_book_payload(
    payload: dict[str, Any],
    portal: Portal,
    course: Course,
    status_group: str | None,
    credentials: Any | None,
    target: str,
) -> None:
    if credentials is not None and credentials.status_group:
        status_group = credentials.status_group
    if credentials is not None:
        name = f"{credentials.first_name} {credentials.last_name}".strip()
    else:
        name = _display_name(portal.id) or ""
    payload.update(
        {
            "portal": portal.id,
            "portal_name": portal.name,
            "course_nr": course.course_nr,
            "title": course.title,
            "day": course.day,
            "time": course.time,
            "location": course.location,
            "period": course.period,
            "price": _price_label(course, status_group),
            "name": name or None,
            "status_group": status_group,
            "target": target,
            "selected_by": "number" if target.isdigit() else "name",
        }
    )


def _book_summary_lines(payload: dict[str, Any]) -> list[str]:
    title = payload.get("title") or ""
    course = f"{payload.get('course_nr')} {title}".strip()
    portal = payload.get("portal") or ""
    portal_name = payload.get("portal_name") or ""
    return [
        f"Kurs: {course}",
        f"Tag: {payload.get('day') or '–'}",
        f"Zeit: {payload.get('time') or '–'}",
        f"Ort: {payload.get('location') or '–'}",
        f"Zeitraum: {payload.get('period') or '–'}",
        f"Preis: {payload.get('price') or '–'}",
        f"Name: {payload.get('name') or '–'}",
        f"Statusgruppe: {payload.get('status_group') or '–'}",
        f"Portal: {portal} ({portal_name})".rstrip(),
    ]


def _print_book_summary(payload: dict[str, Any]) -> None:
    sys.stdout.write("\n".join(_book_summary_lines(payload)) + "\n")


def _format_book_text(payload: dict[str, Any]) -> str:
    lines = _book_summary_lines(payload)
    if payload.get("confirmed") is False:
        lines.append("Nicht gebucht (Trockenlauf) – keine Buchung gesendet.")
    elif payload.get("dry_run"):
        lines.append("Trockenlauf – keine Buchung gesendet.")
    elif payload.get("submitted"):
        lines.append("Buchung gesendet.")
    else:
        lines.append("Keine Buchung gesendet.")
    return "\n".join(lines)


def _login_missing_message() -> str:
    return (
        "Login fehlt – einmal `hsport login` ausführen (oder für Agenten "
        "Env HS_LOGIN_USER, HS_LOGIN_PASSWORD, HS_STATUSGRUPPE, "
        "HSPORT_FIRSTNAME, HSPORT_LASTNAME setzen)."
    )


_DEFAULT_LOAD_COURSES_FOR_SPORT = load_courses_for_sport


def _book_courses(
    portal: Portal, client: HttpClient, sport_name: str
) -> list[Course]:
    if load_courses_for_sport is not _DEFAULT_LOAD_COURSES_FOR_SPORT:
        return load_courses_for_sport(portal, client, sport_name)
    from . import api as api_mod

    return api_mod.load_courses_for_sport(portal, client, sport_name)


def _ensure_book_credentials(
    portal: Portal, interactive: bool
) -> Any:
    from .booking import load_booking_credentials

    try:
        return load_booking_credentials(portal.id)
    except UsageError:
        if interactive and prompts.confirm(
            "Jetzt `hsport login` starten?", default=True
        ):
            _login_interactive(portal)
            return load_booking_credentials(portal.id)
        raise UsageError(_login_missing_message())


def _handle_book(
    portal: Portal,
    client: HttpClient,
    args: argparse.Namespace,
    as_json: bool,
) -> int:
    target = args.course_nr.strip()
    confirm = bool(args.confirm or getattr(args, "yes", False))
    interactive = prompts.is_tty() and not as_json
    credentials = None

    # --confirm/--yes: Login vor jedem Request prüfen (Agenten ohne TTY).
    if confirm:
        credentials = _ensure_book_credentials(portal, interactive)

    status_group = _status_group(portal.id)
    course: Course | None = None

    if target.isdigit():
        course = resolve_course(portal, client, target)
    else:
        courses = _book_courses(portal, client, target)
        if not courses:
            raise UsageError(f"Keine Kurse für Sportart {target!r} gefunden.")
        bookable = [c for c in courses if c.booking_status == STATUS_BOOKABLE]
        if not bookable:
            if not as_json:
                _print_course_choices(courses, status_group)
            statuses = ", ".join(
                f"{c.course_nr} ({c.booking_status})" for c in courses
            )
            raise UsageError(
                f"Keine buchbaren Kurse für {target!r}: {statuses}. "
                "Mit `hsport watch <kursnr>` Status beobachten."
            )
        if len(bookable) == 1:
            course = bookable[0]
        elif not interactive:
            if not as_json:
                _print_course_choices(bookable, status_group)
            raise UsageError(
                "Mehrere buchbare Kurse gefunden – bitte Kursnummer angeben: "
                "hsport book <kursnr>."
            )
        else:
            course = _choose_course(bookable, status_group)
            if course is None:
                _emit(
                    {
                        "portal": portal.id,
                        "cancelled": True,
                        "dry_run": True,
                        "submitted": False,
                    },
                    as_json,
                    text="Abgebrochen.",
                )
                return EXIT_OK

    if interactive and credentials is None:
        credentials = _ensure_book_credentials(portal, interactive)
        status_group = credentials.status_group

    summary: dict[str, Any] = {}
    _decorate_book_payload(summary, portal, course, status_group, credentials, target)

    if interactive:
        _print_book_summary(summary)
        if not confirm:
            if not prompts.confirm("Jetzt verbindlich buchen?", default=False):
                payload = cmd_book(
                    portal,
                    client,
                    course_nr=course.course_nr,
                    confirm=False,
                    course=course,
                )
                _decorate_book_payload(
                    payload, portal, course, status_group, credentials, target
                )
                payload["confirmed"] = False
                _emit(
                    payload,
                    as_json,
                    text="Nicht gebucht (Trockenlauf) – keine Buchung gesendet.",
                )
                return EXIT_OK
            confirm = True

    payload = cmd_book(
        portal,
        client,
        course_nr=course.course_nr,
        confirm=confirm,
        credentials=credentials,
        course=course,
    )
    _decorate_book_payload(payload, portal, course, status_group, credentials, target)
    if interactive:
        text = "Buchung gesendet." if confirm else "Keine Buchung gesendet."
    else:
        text = _format_book_text(payload)
    _emit(payload, as_json, text=text)
    return EXIT_OK

def _add_globals(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="JSON auf stdout")
    parser.add_argument(
        "--portal",
        metavar="URL",
        help="Portal-Basis-URL oder Kurz-ID (Default: stuttgart / HS_PORTAL)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="SEK",
        help="HTTP-Timeout in Sekunden (Default: 20)",
    )


def _run(handler: Callable[..., dict[str, Any]], as_json: bool, **kwargs: Any) -> int:
    try:
        payload = handler(**kwargs)
    except CliError as exc:
        return _fail(exc, as_json)
    _emit(payload, as_json)
    return EXIT_OK


def _extract_globals(argv: list[str]) -> tuple[list[str], bool, str | None, float | None]:
    """``--json``, ``--portal`` und ``--timeout`` dürfen vor oder nach dem Subcommand stehen."""
    as_json = False
    portal: str | None = None
    timeout: float | None = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--json":
            as_json = True
        elif arg == "--portal" and i + 1 < len(argv):
            portal = argv[i + 1]
            i += 1
        elif arg == "--timeout" and i + 1 < len(argv):
            try:
                timeout = float(argv[i + 1])
            except ValueError:
                timeout = float("nan")
            i += 1
        elif arg.startswith("--portal="):
            portal = arg.split("=", 1)[1]
        elif arg.startswith("--timeout="):
            try:
                timeout = float(arg.split("=", 1)[1])
            except ValueError:
                timeout = float("nan")
        else:
            rest.append(arg)
        i += 1
    return rest, as_json, portal, timeout


def _resolve_portal_safe(
    portal_raw: str | None, as_json: bool, use_default: bool
) -> Portal | int:
    from .portals import Portal, resolve_portal

    try:
        if portal_raw:
            return resolve_portal(portal_raw)
        if use_default:
            return portal_from_env()
    except CliError as exc:
        return _fail(exc, as_json)
    return resolve_portal(None)


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except CliError as exc:
        # Fallback, falls ein Befehl eine Exception nicht abfängt.
        raw = argv if argv is not None else sys.argv[1:]
        _, as_json, _, _ = _extract_globals(list(raw))
        return _fail(exc, as_json)
    except Exception:
        raw = argv if argv is not None else sys.argv[1:]
        _, as_json, _, _ = _extract_globals(list(raw))
        return _fail(
            CliError(
                "Interner Fehler.",
                kind="internal",
                exit_code=EXIT_USAGE,
            ),
            as_json,
        )


def _main(argv: list[str] | None = None) -> int:
    raw_argv = argv if argv is not None else sys.argv[1:]
    argv, as_json, portal_arg, timeout_arg = _extract_globals(list(raw_argv))

    if timeout_arg is not None and timeout_arg != timeout_arg:  # NaN
        return _fail(
            UsageError("Ungültiger Wert für --timeout (Zahl in Sekunden erwartet)."),
            as_json,
        )

    root = argparse.ArgumentParser(
        prog="hsport",
        description="Hochschulsport-Buchungsportale (Buchsys) von der Kommandozeile",
        epilog=(
            "Beispiele:\n"
            "  hsport login\n"
            "  hsport book volleyball\n"
            "  hsport book 50100 --confirm\n"
            "  hsport courses --query yoga --free-only"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    root.add_argument("--version", action="version", version=f"hsport {__version__}")
    _add_globals(root)
    sub = root.add_subparsers(dest="command", required=True)

    sub.add_parser("portals", help="Bekannte Portale mit Erreichbarkeit")

    sub.add_parser(
        "login",
        help="Login-Daten für das aktuelle Portal interaktiv speichern",
    )
    sub.add_parser(
        "logout",
        help="Gespeicherte Login-Daten des aktuellen Portals löschen",
    )
    sub.add_parser(
        "whoami",
        help="Gespeicherte Identität anzeigen (Passwort nur als Status)",
    )
    config_p = sub.add_parser(
        "config", help="Konfiguration anzeigen oder Default-Portal setzen"
    )
    config_sub = config_p.add_subparsers(dest="config_command")
    config_portal_p = config_sub.add_parser("portal", help="Default-Portal setzen")
    config_portal_p.add_argument("portal_id", metavar="ID", help="Portal-ID oder URL")

    sports_p = sub.add_parser("sports", help="Sportarten des Portals")
    sports_p.add_argument("--query", metavar="TEXT", help="Filter (Substring, case-insensitive)")

    courses_p = sub.add_parser("courses", help="Kurse suchen")
    courses_p.add_argument("sport", nargs="?", metavar="SPORT", help="Exakter Sportname")
    courses_p.add_argument(
        "--sport",
        metavar="NAME",
        dest="sport_filter",
        help="Filter auf Sportart (Substring, case-insensitive)",
    )
    courses_p.add_argument("--query", metavar="TEXT", help="Suche in Kursfeldern")
    courses_p.add_argument("--day", metavar="TAG", help="Wochentag Mo–So")
    courses_p.add_argument(
        "--free-only",
        action="store_true",
        help="Nur buchbare Kurse (Status buchbar)",
    )

    course_p = sub.add_parser("course", help="Kursdetails zu einer Kursnummer")
    course_p.add_argument("course_nr", metavar="KURSNR", help="Kursnummer")

    watch_p = sub.add_parser("watch", help="Buchungsstatus beobachten")
    watch_p.add_argument("course_nr", metavar="KURSNR", help="Kursnummer")
    watch_p.add_argument(
        "--state-file",
        metavar="PATH",
        help="Pfad zur Watch-State-Datei (Default: XDG config)",
    )

    book_p = sub.add_parser(
        "book",
        help="Buchung vorbereiten oder mit --confirm/--yes absenden",
        description=(
            "Bucht eine Kursnummer oder zeigt buchbare Kurse einer Sportart "
            "zur Auswahl. Im TTY wird vor dem Absenden nachgefragt; ohne "
            "TTY bleibt es ohne --confirm/--yes bei einem Trockenlauf."
        ),
        epilog=(
            "Beispiele:\n"
            "  hsport book volleyball\n"
            "  hsport book 50100\n"
            "  hsport book 50100 --confirm"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    book_p.add_argument(
        "course_nr",
        metavar="KURSNR|SPORT",
        help="Kursnummer (nur Ziffern) oder Sportname",
    )
    book_p.add_argument(
        "--confirm",
        action="store_true",
        help="Buchung wirklich absenden (Login aus Config oder Env)",
    )
    book_p.add_argument(
        "--yes",
        action="store_true",
        help="Alias für --confirm (ohne Rückfrage buchen)",
    )

    try:
        if as_json:
            # argparse schreibt sonst Text vor das JSON-Fehlerobjekt.
            with contextlib.redirect_stderr(io.StringIO()):
                args, unknown = root.parse_known_args(argv)
        else:
            args, unknown = root.parse_known_args(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        if code == 0:
            return EXIT_OK
        return _fail(UsageError("Ungültige Argumente."), as_json)

    if unknown:
        return _fail(CliError(f"Unbekannte Argumente: {' '.join(unknown)}"), as_json)

    timeout = timeout_arg if timeout_arg is not None else (args.timeout if args.timeout is not None else 20.0)
    client = HttpClient(timeout=timeout)

    portal_raw = portal_arg if portal_arg is not None else args.portal
    portal_or_code = _resolve_portal_safe(
        portal_raw, as_json, use_default=portal_raw is None
    )
    if isinstance(portal_or_code, int):
        return portal_or_code
    portal = portal_or_code

    if args.command == "login":
        return _cmd_login(portal, as_json)

    if args.command == "logout":
        return _cmd_logout(portal, as_json)

    if args.command == "whoami":
        return _cmd_whoami(portal, as_json)

    if args.command == "config":
        if getattr(args, "config_command", None) == "portal":
            return _cmd_config_portal(args.portal_id, as_json)
        return _cmd_config_show(as_json)

    if args.command == "portals":
        return _run(
            cmd_portals,
            as_json,
            client=client,
            current=portal.id,
            source=_portal_source(portal_arg),
        )

    if args.command == "sports":
        return _run(cmd_sports, as_json, portal=portal, client=client, query=args.query)

    if args.command == "courses":
        return _run(
            cmd_courses,
            as_json,
            portal=portal,
            client=client,
            sport=args.sport,
            sport_filter=args.sport_filter,
            query=args.query,
            day=args.day,
            free_only=args.free_only,
        )

    if args.command == "course":
        return _run(
            cmd_course,
            as_json,
            portal=portal,
            client=client,
            course_nr=args.course_nr,
        )

    if args.command == "watch":
        state_path = Path(args.state_file) if args.state_file else None
        try:
            payload, exit_code = cmd_watch(
                portal,
                client,
                course_nr=args.course_nr,
                state_file=state_path,
            )
        except CliError as exc:
            return _fail(exc, as_json)
        _emit(payload, as_json)
        return exit_code

    if args.command == "book":
        return _handle_book(portal, client, args, as_json)

    return _fail(CliError(f"Unbekannter Befehl: {args.command}"), as_json)


if __name__ == "__main__":
    raise SystemExit(main())
