"""Persistente Benutzerkonfiguration (XDG, Rechte 0600).

Die Datei liegt unter ``xdg_config_home()/hochschulsport-cli/config.json``.
Passwörter werden bevorzugt über ``keyring`` gespeichert – aber nur, wenn das
Paket importierbar **und** ein nutzbares Backend vorhanden ist. Sonst landen sie
in der Datei, die dann mit ``0600`` geschützt ist (Verzeichnis ``0700``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import UsageError
from .paths import APP_NAME, default_config_path

KEYRING_SERVICE = APP_NAME
PASSWORD_STORES = ("keyring", "file")
PORTAL_FIELDS = (
    "login_user",
    "login_password",
    "status_group",
    "first_name",
    "last_name",
    "email",
)


def config_path() -> Path:
    """Pfad zur Konfigurationsdatei (Env ``XDG_CONFIG_HOME`` wird beachtet)."""
    return default_config_path()


def _empty_config() -> dict[str, Any]:
    return {"default_portal": None, "portals": {}}


def _keyring_module() -> Any | None:
    try:
        import keyring  # type: ignore[import-not-found]
    except Exception:
        return None
    return keyring


def _keyring_usable() -> bool:
    """``True`` nur bei importierbarem keyring mit echtem Backend."""
    keyring = _keyring_module()
    if keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
    except Exception:
        return False
    if backend is None:
        return False
    try:
        from keyring.backends import fail  # type: ignore[import-not-found]

        if isinstance(backend, fail.Keyring):
            return False
    except Exception:
        pass
    try:
        return float(backend.priority) > 0
    except Exception:
        return True


def _keyring_get(portal_id: str) -> str | None:
    if not _keyring_usable():
        return None
    keyring = _keyring_module()
    assert keyring is not None
    try:
        return keyring.get_password(KEYRING_SERVICE, portal_id)
    except Exception:
        return None


def _keyring_set(portal_id: str, password: str) -> bool:
    if not _keyring_usable():
        return False
    keyring = _keyring_module()
    assert keyring is not None
    try:
        keyring.set_password(KEYRING_SERVICE, portal_id, password)
        return True
    except Exception:
        return False


def _keyring_delete(portal_id: str) -> None:
    keyring = _keyring_module()
    if keyring is None:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, portal_id)
    except Exception:
        pass


def load() -> dict[str, Any]:
    """Liest die Rohkonfiguration. Fehlende Datei = leere Konfiguration."""
    path = config_path()
    if not path.exists():
        return _empty_config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UsageError(
            f"Konfigurationsdatei {path} ist nicht lesbar: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise UsageError(f"Konfigurationsdatei {path} enthält kein JSON-Objekt.")

    config = _empty_config()
    default = raw.get("default_portal")
    if isinstance(default, str) and default.strip():
        config["default_portal"] = default.strip()
    portals = raw.get("portals")
    if isinstance(portals, dict):
        for portal_id, entry in portals.items():
            if isinstance(entry, dict):
                config["portals"][str(portal_id)] = dict(entry)
    return config


def load_portal(portal_id: str) -> dict[str, Any]:
    """Portal-Eintrag inklusive keyring-Passwort (falls konfiguriert)."""
    entry = dict(load()["portals"].get(portal_id, {}))
    if entry.get("password_store") == "keyring" and not entry.get("login_password"):
        secret = _keyring_get(portal_id)
        if secret:
            entry["login_password"] = secret
    return entry


def _private_write(path: Path, text: str) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass

    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def save(config: dict[str, Any]) -> None:
    """Schreibt die Konfiguration atomar mit Rechten 0600."""
    payload = {
        "default_portal": config.get("default_portal"),
        "portals": config.get("portals") or {},
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _private_write(config_path(), text)


def save_portal(portal_id: str, values: dict[str, Any]) -> dict[str, Any]:
    """Speichert Felder eines Portals; Passwort je nach keyring-Verfügbarkeit."""
    config = load()
    entry = dict(config["portals"].get(portal_id, {}))

    for field in PORTAL_FIELDS:
        if field in values and field != "login_password":
            entry[field] = values[field]

    password = values.get("login_password")
    if password:
        if _keyring_set(portal_id, str(password)):
            entry["password_store"] = "keyring"
            entry.pop("login_password", None)
        else:
            entry["password_store"] = "file"
            entry["login_password"] = str(password)
    elif entry.get("password_store") == "keyring":
        entry.pop("login_password", None)

    config["portals"][portal_id] = entry
    save(config)
    return entry


def clear(portal_id: str | None = None) -> None:
    """Löscht ein Portal (inkl. keyring) oder die gesamte Konfiguration."""
    path = config_path()
    if portal_id is None:
        for pid in list(load()["portals"]):
            _keyring_delete(pid)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return

    config = load()
    config["portals"].pop(portal_id, None)
    _keyring_delete(portal_id)

    if config["portals"] or config["default_portal"]:
        save(config)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
