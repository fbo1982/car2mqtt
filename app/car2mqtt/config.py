from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from .models import AppState, MQTTSettings


DATA_DIR = Path(os.environ.get("CAR2MQTT_DATA_DIR", "/data/car2mqtt"))
STATE_FILE = DATA_DIR / "state.json"
OPTIONS_FILE = Path("/data/options.json")


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def read_addon_options() -> Dict[str, Any]:
    if not OPTIONS_FILE.exists():
        return {}
    try:
        return json.loads(OPTIONS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def default_state() -> AppState:
    options = read_addon_options()
    mqtt_config = MQTTSettings(**options.get("mqtt", {})) if options.get("mqtt") else MQTTSettings()
    return AppState(mqtt=mqtt_config)
