"""Application configuration persistence.

Reads and writes ``settings.json`` located alongside this package.
"""

import json
import os
from typing import Any, Dict

__all__ = ["load_config", "save_config"]

CONFIG_PATH: str = os.path.join(os.path.dirname(__file__), "settings.json")


def load_config() -> Dict[str, Any]:
    """Load and return the JSON configuration, or an empty dict on failure."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(config: Dict[str, Any]) -> None:
    """Atomically persist *config* to ``settings.json``."""
    tmp_path = CONFIG_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

