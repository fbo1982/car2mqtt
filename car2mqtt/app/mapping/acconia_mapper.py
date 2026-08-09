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
        for key, nested in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.extend(_flatten(nested, path))
    elif isinstance(value, list):
        for index, nested in enumerate(value, start=1):
            path = f"{prefix}.{index}" if prefix else str(index)
            out.extend(_flatten(nested, path))
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


def _normalized_key(path: str) -> str:
    leaf = str(path or "").split(".")[-1]
    return re.sub(r"[^a-z0-9]+", "", leaf.lower())


def _battery_index(path: str) -> int | None:
    text = str(path or "").lower().replace("_", "-")
    patterns = (
        r"(?:battery|batteries|batt|akku|pack)[\-./ ]*([12])\b",
        r"\b([12])[\-./ ]*(?:battery|batteries|batt|akku|pack)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
    return None


def apply_acconia_metric(
    mapped: dict[str, Any],
    relative_topic: str,
    payload: Any,
    configured_battery_count: int = 0,
    capacity_kwh: Any = None,
) -> dict[str, Any]:
    """Map MySilence data to the common Car2MQTT vehicle metric schema."""

    ts = _timestamp()
    parsed = _parse_payload(payload)
    paths = _flatten(parsed) if isinstance(parsed, (dict, list)) else [("", parsed)]
    topic_base = str(relative_topic or "").strip("/").replace("/", ".")
    explicit_plugged: bool | None = None
    charging_seen: bool | None = None

    for inner_path, value in paths:
        path = ".".join(part for part in (topic_base, inner_path) if part)
        path_lower = path.lower()
        key = _normalized_key(path)
        num = _to_number(value)
        boo = _to_bool(value)

        if key in {"latitude", "lat", "locationlatitude"}:
            if num is not None and -90 <= float(num) <= 90:
                _set_metric(mapped, "latitude", num, ts)
            continue
        if key in {"longitude", "lon", "lng", "locationlongitude"}:
            if num is not None and -180 <= float(num) <= 180:
                _set_metric(mapped, "longitude", num, ts)
            continue
        if key in {"altitude", "height", "gpsalt", "locationaltitude"}:
            if num is not None:
                _set_metric(mapped, "altitude", num, ts)
            continue
        if key in {"odometer", "mileage", "kmtotal", "totalkm"}:
            if num is not None:
                _set_metric(mapped, "odometer", num, ts)
            continue
        if key in {"range", "autonomy", "reichweite", "remainingrange"}:
            if num is not None and float(num) >= 0:
                _set_metric(mapped, "range", num, ts)
            continue
        if key in {"charging", "chargestate", "ischarging"}:
            if boo is not None:
                charging_seen = boo
                _set_metric(mapped, "charging", boo, ts)
            continue
        if key in {"plugged", "connected", "chargerconnected", "chargingconnected"}:
            if boo is not None:
                explicit_plugged = boo
            continue

        looks_like_soc = key in {
            "soc",
            "stateofcharge",
            "batterysoc",
            "batterylevel",
            "batterypercent",
            "batterypercentage",
            "batterystatus",
            "akkustand",
        }
        if looks_like_soc and num is not None and 0 <= float(num) <= 100:
            index = _battery_index(path_lower)
            if index in {1, 2}:
                _set_metric(mapped, f"battery{index}Soc", num, ts)
            else:
                _set_metric(mapped, "soc", num, ts)
            continue

    # MySilence may expose both a charging flag and a separate connection flag.
    # A charging=false value must not overwrite connected=true merely because it
    # appears later in the JSON object. Prefer the explicit plug/connection state;
    # only fall back to charging when the API does not provide one.
    if explicit_plugged is not None:
        _set_metric(mapped, "plugged", explicit_plugged, ts)
    elif charging_seen is not None:
        _set_metric(mapped, "plugged", charging_seen, ts)

    battery1 = _to_number(mapped.get("battery1Soc"))
    battery2 = _to_number(mapped.get("battery2Soc"))
    count = configured_battery_count if configured_battery_count in {1, 2} else (2 if battery2 is not None else (1 if battery1 is not None else 0))
    if count:
        _set_metric(mapped, "batteryCount", count, ts)
    if battery1 is not None and battery2 is not None:
        _set_metric(mapped, "soc", round((float(battery1) + float(battery2)) / 2, 1), ts)
    elif battery1 is not None and mapped.get("soc") in (None, ""):
        _set_metric(mapped, "soc", battery1, ts)

    capacity = _to_number(capacity_kwh)
    if capacity is not None and float(capacity) > 0:
        _set_metric(mapped, "capacityKwh", capacity, ts)

    _set_metric(mapped, "vehicleType", "ev", ts)
    if any(key in mapped for key in ("soc", "range", "latitude", "longitude", "charging", "odometer")):
        _set_metric(mapped, "lastUpdate", ts, ts)
    return mapped
