"""
GLrc — Persistent configuration.

Stores window geometry, font size, display mode, colors, and lock state
in a JSON file next to the executable / script.
"""

import json
import logging
import os
import sys
import tempfile

log = logging.getLogger(__name__)

def _get_config_path() -> str:
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    config_dir = os.path.join(appdata, "GLrc")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")

CONFIG_PATH = _get_config_path()

DEFAULT_CONFIG: dict = {
    "x": None,
    "y": None,
    "width": None,
    "height": None,
    "font_size": 32,
    "locked": False,
    "display_mode": "single",       # "single" or "multi"
    "fill_color": "#FFFFFF",
    "outline_color": "#000000",
    "target_app_id": None,
}


def load_config() -> dict:
    """Load config from disk, merging with defaults for any missing keys."""
    config = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            stored = json.load(f)
        if isinstance(stored, dict):
            config.update(stored)
    except FileNotFoundError:
        log.info("No config file found — using defaults.")
    except Exception:
        log.exception("Failed to load config — using defaults.")
    return config


def save_config(config: dict) -> None:
    """Atomically write config to disk (write tmp then rename)."""
    try:
        config_dir = os.path.dirname(CONFIG_PATH)
        fd, tmp_path = tempfile.mkstemp(
            dir=config_dir, suffix=".tmp", prefix=".config_"
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        # Atomic replace (Windows: os.replace works on same volume)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        log.exception("Failed to save config.")
        # Clean up temp file if rename failed
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
