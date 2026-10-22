"""Konfigurationspfade (XDG, Env-Overrides)."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "hochschulsport-cli"


def xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".config"


def default_watch_state_path() -> Path:
    return xdg_config_home() / APP_NAME / "watch.json"
