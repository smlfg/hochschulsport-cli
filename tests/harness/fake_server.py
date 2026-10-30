"""Lokaler Fake-Server für die UX-Harness (nur Standardbibliothek)."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

try:
    from ux_spec import FormStep, UxSpec, field_matches
except ImportError:  # pragma: no cover - Paketimport
    from .ux_spec import FormStep, UxSpec, field_matches


@dataclass
class Recorded:
    method: str
    path: str
    query: str
    fields: set[str]
    raw_body: bytes
    t: float


def _query_fields(query: str) -> set[str]:
    return set(parse_qs(query, keep_blank_values=True))


def _multipart_fields(content_type: str, body: bytes) -> set[str]:
    from email.parser import BytesParser
    from email.policy import default

    raw = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        + body
    )
    message = BytesParser(policy=default).parsebytes(raw)
    names: set[str] = set()
    if message.is_multipart():
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name:
                names.add(str(name))
    return names


def _extract_fields(content_type: str, body: bytes, query: str) -> set[str]:
    fields = _query_fields(query)
    ctype = content_type.lower()
    if not body:
        return fields
    if "multipart/form-data" in ctype:
        fields |= _multipart_fields(content_type, body)
    elif "application/json" in ctype:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            fields |= {str(key) for key in data}
    elif "application/x-www-form-urlencoded" in ctype:
        fields |= _query_fields(body.decode("utf-8", "replace"))
    else:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            fields |= _query_fields(body.decode("utf-8", "replace"))
        else:
            if isinstance(data, dict):
                fields |= {str(key) for key in data}
    return fields


class FakeServer:
    """Kontextmanager um einen ThreadingHTTPServer auf 127.0.0.1:0."""

    def __init__(self, spec: UxSpec, repo_dir: str | Path, port: int = 0):
        self.spec = spec
        self.repo_dir = Path(repo_dir)
        self.port = int(port or 0)
        self.requests: list[Recorded] = []
        self.marks: dict[str, float] = {}
        self._lock = threading.Lock()
        self._sent: list[tuple[FormStep, Recorded]] = []
        self._counts: dict[tuple[str, str], int] = {}
        self._groups: dict[tuple[str, str], list[FormStep]] = {}
        for step in spec.formsteps:
            key = (step.method.upper(), step.path)
            self._groups.setdefault(key, []).append(step)
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.base_url = ""

    def __enter__(self) -> "FakeServer":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # noqa: D401 - leise
                return

            def _run(self):
                fake._handle(self)

            do_GET = _run
            do_HEAD = _run
            do_POST = _run
            do_PUT = _run
            do_PATCH = _run
            do_DELETE = _run

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._httpd.daemon_threads = True
        port = self._httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _read_response(self, relative: str) -> bytes:
        path = self.repo_dir / relative
        try:
            return path.read_bytes()
        except OSError:
            return b""

    def _route_for(self, method: str, path: str, query: str):
        for route in self.spec.routes:
            if route.method.upper() != method or route.path != path:
                continue
            if route.query_contains is not None and route.query_contains not in query:
                continue
            return route
        return None

    def _resolve(self, method: str, path: str, query: str, rec: Recorded):
        route = self._route_for(method, path, query)
        if route is not None:
            return route.status, route.content_type, self._read_response(route.response)

        key = (method, path)
        group = self._groups.get(key)
        if group:
            with self._lock:
                count = self._counts.get(key, 0) + 1
                self._counts[key] = count
            step = group[min(count - 1, len(group) - 1)]
            with self._lock:
                self._sent.append((step, rec))
            return 200, "text/html; charset=utf-8", self._read_response(step.response)

        return 404, "text/plain; charset=utf-8", b"not found"

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        parts = urlsplit(handler.path)
        method = handler.command.upper()
        path = parts.path
        query = parts.query
        try:
            length = int(handler.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        body = handler.rfile.read(length) if length > 0 else b""
        content_type = handler.headers.get("Content-Type", "")
        rec = Recorded(
            method=method,
            path=path,
            query=query,
            fields=_extract_fields(content_type, body, query),
            raw_body=body,
            t=time.monotonic(),
        )
        with self._lock:
            self.requests.append(rec)
        status, ctype, payload = self._resolve(method, path, query, rec)
        handler.send_response(status)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        if method != "HEAD":
            try:
                handler.wfile.write(payload)
            except BrokenPipeError:
                pass

    def sent_formsteps(self) -> list[tuple[str, Recorded]]:
        """Zugeordnete formsteps in Eingangsreihenfolge."""
        with self._lock:
            return [(step.id, rec) for step, rec in self._sent]

    def missing_formsteps(self) -> list[tuple[FormStep, str]]:
        """Noch nicht (vollständig) gesendete formsteps mit deutschem Grund."""
        with self._lock:
            sent = list(self._sent)
        result: list[tuple[FormStep, str]] = []
        for step in self.spec.formsteps:
            records = [rec for sent_step, rec in sent if sent_step is step]
            if not records:
                result.append((step, "nie gesendet"))
                continue
            if any(
                all(field_matches(entry, rec.fields) for entry in step.sends)
                for rec in records
            ):
                continue
            best = max(
                records,
                key=lambda rec: sum(
                    field_matches(entry, rec.fields) for entry in step.sends
                ),
            )
            missing = [
                entry for entry in step.sends if not field_matches(entry, best.fields)
            ]
            result.append((step, "Felder fehlen: " + ", ".join(missing)))
        return result

    def mark(self, label: str) -> float:
        """Setzt eine Zeitmarke und gibt sie zurück (z. B. [j/N]-Ausgabe)."""
        stamp = time.monotonic()
        with self._lock:
            self.marks[label] = stamp
        return stamp

    def formsteps_before(self, t: float) -> list[FormStep]:
        """Bereits eingegangene formsteps (als Objekte) vor dem Zeitpunkt ``t``."""
        with self._lock:
            return [step for step, rec in self._sent if rec.t < t]
