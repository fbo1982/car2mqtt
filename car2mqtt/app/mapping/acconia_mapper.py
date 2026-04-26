from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import json
import re


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value) if float(value).is_integer() else float(value)
    text = str(value).strip().replace(",", ".")
    text = re.sub(r"[^0-9.\-]+", "", text)
    if text in {"", "-", "."}:
        return None
    try:
        n = float(text)
        return int(n) if n.is_integer() else n
    except Exception:
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "charging", "charge", "laden", "lädt", "connected", "plugged", "active"}:
        return True
    if text in {"0", "false", "no", "off", "not_charging", "not charging", "idle", "disconnected", "unplugged", "inactive"}:
        return False
    return None


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.extend(_flatten(v, key))
    elif isinstance(value, list):
        for i, v in enumerate(value, start=1):
            key = f"{prefix}.{i}" if prefix else str(i)
            out.extend(_flatten(v, key))
    else:
        out.append((prefix, value))
    return out


def _parse_payload(payload: Any) -> Any:
    if isinstance(payload, (dict, list, int, float, bool)) or payload is None:
        return payload
    text = str(payload).strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except Exception:
        return text


def _set_metric(mapped: dict[str, Any], key: str, value: Any, ts: str) -> bool:
    if value is None or value == "":
        return False
    if mapped.get(key) == value:
        return False
    mapped[key] = value
    mapped[f"{key}_ts"] = ts
    return True


def _battery_index(path: str) -> int | None:
    text = path.lower().replace("_", "-")
    m = re.search(r"(?:battery|batt|akku|pack)[\-./ ]*([12])\b", text)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([12])[\-./ ]*(?:battery|batt|akku|pack)\b", text)
    if m:
        return int(m.group(1))
    return None


def apply_acconia_metric(mapped: dict[str, Any], relative_topic: str, payload: Any, configured_battery_count: int = 0, capacity_kwh: Any = None) -> dict[str, Any]:
    ts = _timestamp()
    parsed = _parse_payload(payload)
    paths = _flatten(parsed) if isinstance(parsed, (dict, list)) else [("", parsed)]
    topic_base = str(relative_topic or "").strip("/").replace("/", ".")

    for inner_path, value in paths:
        path = ".".join(p for p in [topic_base, inner_path] if p).lower()
        num = _to_number(value)
        boo = _to_bool(value)

        if any(token in path for token in ["latitude", "lat"]):
            if num is not None and -90 <= float(num) <= 90:
                _set_metric(mapped, "latitude", num, ts)
                _set_metric(mapped, "lastUpdate", ts, ts)
            continue
        if any(token in path for token in ["longitude", "lon", "lng"]):
            if num is not None and -180 <= float(num) <= 180:
                _set_metric(mapped, "longitude", num, ts)
                _set_metric(mapped, "lastUpdate", ts, ts)
            continue
        if any(token in path for token in ["altitude", "height", "gpsalt"]):
            if num is not None:
                _set_metric(mapped, "altitude", num, ts)
            continue
        if any(token in path for token in ["odometer", "mileage", "km_total", "total_km"]):
            if num is not None:
                _set_metric(mapped, "odometer", num, ts)
            continue
        if "range" in path or "autonomy" in path or "reichweite" in path:
            if num is not None:
                _set_metric(mapped, "range", num, ts)
            continue
        if "charging" in path or "charge_state" in path or "is_charging" in path or "is-charging" in path:
            if boo is not None:
                _set_metric(mapped, "charging", boo, ts)
                if boo:
                    _set_metric(mapped, "plugged", True, ts)
            continue
        if "plug" in path or "connected" in path or "charger" in path:
            if boo is not None:
                _set_metric(mapped, "plugged", boo, ts)
            continue

        looks_like_soc = any(token in path for token in ["soc", "stateofcharge", "state_of_charge", "battery.level", "battery_level", "battery.percent", "battery_percentage", "battery.percentage", "batterystatus", "akku"])
        if looks_like_soc and num is not None and 0 <= float(num) <= 100:
            idx = _battery_index(path)
            if idx in {1, 2}:
                _set_metric(mapped, f"battery{idx}Soc", num, ts)
            elif "battery2" not in mapped and configured_battery_count == 1:
                _set_metric(mapped, "battery1Soc", num, ts)
            elif path.endswith("soc") or "state" in path or "level" in path or "percent" in path or "akku" in path:
                _set_metric(mapped, "soc", num, ts)
            continue

    b1 = _to_number(mapped.get("battery1Soc"))
    b2 = _to_number(mapped.get("battery2Soc"))
    count = configured_battery_count if configured_battery_count in {1, 2} else (2 if b2 is not None else (1 if b1 is not None else 0))
    if count:
        _set_metric(mapped, "batteryCount", count, ts)
    if b1 is not None and b2 is not None:
        _set_metric(mapped, "soc", round((float(b1) + float(b2)) / 2, 1), ts)
    elif b1 is not None and mapped.get("soc") in (None, ""):
        _set_metric(mapped, "soc", b1, ts)

    cap = _to_number(capacity_kwh)
    if cap is not None:
        _set_metric(mapped, "capacityKwh", cap, ts)
    _set_metric(mapped, "vehicleType", "ev", ts)
    return mapped
