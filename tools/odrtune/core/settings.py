"""Persistent app settings stored as JSON (independent of the ODrive's own
config). Currently holds the Control-tab unit conversion factor.

The file lives at ~/.odrtune/config.json. If it's missing or unreadable it is
(re)created with defaults on first load, so the setting survives restarts."""
from __future__ import annotations

import json
from pathlib import Path

DEFAULTS = {
    "conversion": 1.0,   # user units per motor revolution (Control tab)
}


def default_path() -> Path:
    return Path.home() / ".odrtune" / "config.json"


def load(path=None) -> dict:
    """Return settings, filling in any missing keys with defaults. Creates the
    file with defaults if it doesn't exist or can't be parsed."""
    p = Path(path) if path else default_path()
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, dict):
            raise ValueError("config.json is not a JSON object")
    except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
        save(dict(DEFAULTS), p)
        return dict(DEFAULTS)
    return {**DEFAULTS, **data}


def save(cfg: dict, path=None) -> None:
    p = Path(path) if path else default_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass
