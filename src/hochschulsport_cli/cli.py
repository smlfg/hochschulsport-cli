"""CLI-Einstieg: ``hsport`` mit zentraler JSON-Fehlerbehandlung."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from typing import Any, Callable

from . import __version__
from pathlib import Path

from .api import (
    cmd_book,
    cmd_course,
    cmd_courses,
    cmd_portals,
    cmd_sports,
    cmd_watch,
    portal_from_env,
)
from .errors import CliError, EXIT_OK, EXIT_USAGE, UsageError
from .http_client import HttpClient


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

    root = argparse.ArgumentParser(prog="hsport", description="Hochschulsport Buchsys CLI")
    root.add_argument("--version", action="version", version=f"hsport {__version__}")
    _add_globals(root)
    sub = root.add_subparsers(dest="command", required=True)

    sub.add_parser("portals", help="Bekannte Portale mit Erreichbarkeit")

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

    book_p = sub.add_parser("book", help="Buchung vorbereiten oder mit --confirm absenden")
    book_p.add_argument("course_nr", metavar="KURSNR", help="Kursnummer")
    book_p.add_argument(
        "--confirm",
        action="store_true",
        help="Buchung wirklich absenden (Pflicht-Env vorher setzen)",
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

    if args.command == "portals":
        return _run(cmd_portals, as_json, client=client)

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
        return _run(
            cmd_book,
            as_json,
            portal=portal,
            client=client,
            course_nr=args.course_nr,
            confirm=args.confirm,
        )

    return _fail(CliError(f"Unbekannter Befehl: {args.command}"), as_json)


if __name__ == "__main__":
    raise SystemExit(main())
