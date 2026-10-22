"""Persistenter Watch-Status (atomar, Rechte 0600)."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import UsageError
from .paths import default_watch_state_path

EXIT_WATCH_CHANGED = 2


def _state_key(portal_id: str, course_nr: str) -> str:
    return f"{portal_id}:{course_nr}"


def load_watch_state(path: Path | None = None) -> dict[str, Any]:
    file_path = path or default_watch_state_path()
    if not file_path.exists():
        return {}
    try:
        raw = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"Watch-State-Datei nicht lesbar: {exc}") from exc
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UsageError(
            f"Watch-State-Datei ist kein gültiges JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise UsageError("Watch-State-Datei hat ein unerwartetes Format.")
    return data


def save_watch_state(data: dict[str, Any], path: Path | None = None) -> Path:
    file_path = path or default_watch_state_path()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(
        prefix=".watch-", suffix=".json", dir=str(file_path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, file_path)
        os.chmod(file_path, 0o600)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return file_path


def read_course_entry(
    data: dict[str, Any], portal_id: str, course_nr: str
) -> dict[str, Any] | None:
    entry = data.get(_state_key(portal_id, course_nr))
    return entry if isinstance(entry, dict) else None


def write_course_entry(
    data: dict[str, Any],
    *,
    portal_id: str,
    course_nr: str,
    booking_status: str,
) -> dict[str, Any]:
    key = _state_key(portal_id, course_nr)
    data[key] = {
        "course_nr": course_nr,
        "portal": portal_id,
        "booking_status": booking_status,
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        ),
    }
    return data
