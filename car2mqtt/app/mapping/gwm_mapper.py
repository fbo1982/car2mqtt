from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _changed(current: dict[str, Any], key: str, value: Any) -> bool:
    return current.get(key) != value


def _set_metric(mapped: dict[str, Any], key: str, value: Any, ts: str) -> bool:
    if not _changed(mapped, key, value):
        return False
    mapped[key] = value
    mapped[f"{key}_ts"] = ts
    return True


def _set_metrics(mapped: dict[str, Any], values: dict[str, Any], ts: str) -> bool:
    changed = False
    for key, value in values.items():
        if _changed(mapped, key, value):
            mapped[key] = value
            mapped[f"{key}_ts"] = ts
            changed = True
    return changed


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "charging", "connected", "plugged"}:
        return True
    if text in {"0", "false", "no", "off", "nocharging", "disconnected", "unplugged"}:
        return False
    return None


def _to_number(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    text = str(value).strip().replace(",", ".")
    try:
        number = float(text)
        if number.is_integer():
            return int(number)
        return number
    except Exception:
        return None


def _timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def apply_gwm_metric(mapped: dict[str, Any], item_id: str, value: Any, field_name: str | None = None) -> dict[str, Any]:
    ts = _timestamp()
    num = _to_number(value)
    boo = _to_bool(value)
    raw = str(value).strip() if value is not None else ""

    # Known/observed GWM ORA datapoints
    if item_id == "2013021" and num is not None:  # SoC
        _set_metric(mapped, "soc", num, ts)
    elif item_id in {"2011501", "2210001"} and num is not None:  # range km
        if _set_metric(mapped, "range", num, ts):
            _set_metric(mapped, "lastUpdate", ts, ts)
    elif item_id in {"2103010", "2210002"} and num is not None:  # odometer km
        _set_metric(mapped, "odometer", num, ts)
    elif item_id == "2041142":
        status_num = None
        if num is not None:
            try:
                status_num = int(num)
            except Exception:
                status_num = None

        if status_num == 0:
            _set_metrics(mapped, {"plugged": False, "charging": False}, ts)
        elif status_num == 1:
            _set_metrics(mapped, {"plugged": True, "charging": True}, ts)
        elif status_num in {2, 5}:
            _set_metrics(mapped, {"plugged": True, "charging": False}, ts)
        elif raw.upper() in {"CHARGING", "FASTCHARGING"}:
            _set_metrics(mapped, {"plugged": True, "charging": True}, ts)
        elif raw.upper() in {"DISCONNECTED", "UNPLUGGED", "NOT CHARGING", "NOT_CHARGING"}:
            _set_metrics(mapped, {"plugged": False, "charging": False}, ts)
        elif raw.upper() in {"CONNECTED", "NOCHARGING", "STOPPED", "AWAITING CHARGING", "WAITING FOR POWER"}:
            _set_metrics(mapped, {"plugged": True, "charging": False}, ts)
    elif item_id == "2041301" and num is not None:
        _set_metric(mapped, "limitSoc", num, ts)
    elif item_id in {"2210010", "2220001"} and num is not None:
        _set_metric(mapped, "altitude", num, ts)
    elif item_id in {"2013022"} and num is not None:
        _set_metric(mapped, "remainingChargeMinutes", num, ts)
    elif item_id in {"2210013", "2222001"} and raw:
        _set_metric(mapped, "preconditioning", raw.lower(), ts)

    name = (field_name or "").strip().lower()
    if name == "latitude" and num is not None:
        if _set_metric(mapped, "latitude", num, ts):
            _set_metric(mapped, "lastUpdate", ts, ts)
    elif name == "longitude" and num is not None:
        if _set_metric(mapped, "longitude", num, ts):
            _set_metric(mapped, "lastUpdate", ts, ts)
    elif name == "acquisitiontime" and num is not None:
        _set_metric(mapped, "lastAcquisitionTime", num, ts)
    elif name == "updatetime" and num is not None:
        _set_metric(mapped, "lastUpdateTimeRaw", num, ts)

    return mapped
