"""CLI-Einstieg: ``hsport`` mit zentraler JSON-Fehlerbehandlung."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from . import __version__
from .api import cmd_courses, cmd_portals, cmd_sports, portal_from_env
from .errors import CliError, EXIT_OK
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
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
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
        if payload.get("sport"):
            lines[0] += f", Sport {payload['sport']}"
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
            timeout = float(argv[i + 1])
            i += 1
        elif arg.startswith("--portal="):
            portal = arg.split("=", 1)[1]
        elif arg.startswith("--timeout="):
            timeout = float(arg.split("=", 1)[1])
        else:
            rest.append(arg)
        i += 1
    return rest, as_json, portal, timeout


def main(argv: list[str] | None = None) -> int:
    raw_argv = argv if argv is not None else sys.argv[1:]
    argv, as_json, portal_arg, timeout_arg = _extract_globals(list(raw_argv))

    root = argparse.ArgumentParser(prog="hsport", description="Hochschulsport Buchsys CLI")
    root.add_argument("--version", action="version", version=f"hsport {__version__}")
    _add_globals(root)
    sub = root.add_subparsers(dest="command", required=True)

    sub.add_parser("portals", help="Bekannte Portale mit Erreichbarkeit")

    sports_p = sub.add_parser("sports", help="Sportarten des Portals")
    sports_p.add_argument("--query", metavar="TEXT", help="Filter (Substring, case-insensitive)")

    courses_p = sub.add_parser("courses", help="Kurse suchen")
    courses_p.add_argument("sport", nargs="?", metavar="SPORT", help="Exakter Sportname")
    courses_p.add_argument("--query", metavar="TEXT", help="Suche in Kursfeldern")
    courses_p.add_argument("--day", metavar="TAG", help="Wochentag Mo–So")
    courses_p.add_argument(
        "--free-only",
        action="store_true",
        help="Nur buchbare Kurse (Status buchbar)",
    )

    try:
        args, unknown = root.parse_known_args(argv)
    except SystemExit:
        if as_json:
            return _fail(
                CliError("Ungültige Argumente.", kind="usage", exit_code=1),
                True,
            )
        return 2

    if unknown:
        return _fail(CliError(f"Unbekannte Argumente: {' '.join(unknown)}"), as_json)

    timeout = timeout_arg if timeout_arg is not None else (args.timeout if args.timeout is not None else 20.0)
    client = HttpClient(timeout=timeout)

    from .portals import resolve_portal

    portal_raw = portal_arg if portal_arg is not None else args.portal
    portal = resolve_portal(portal_raw) if portal_raw else portal_from_env()

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
            query=args.query,
            day=args.day,
            free_only=args.free_only,
        )

    return _fail(CliError(f"Unbekannter Befehl: {args.command}"), as_json)


if __name__ == "__main__":
    raise SystemExit(main())
