from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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
        mapped["soc"] = num
        mapped["soc_ts"] = ts
    elif item_id in {"2011501", "2210001"} and num is not None:  # range km
        mapped["range"] = num
        mapped["range_ts"] = ts
        mapped["lastUpdate"] = ts
    elif item_id in {"2103010", "2210002"} and num is not None:  # odometer km
        mapped["odometer"] = num
        mapped["odometer_ts"] = ts
    elif item_id in {"2041142"}:
        if boo is not None:
            mapped["charging"] = boo
            mapped["charging_ts"] = ts
            if boo:
                mapped["plugged"] = True
                mapped["plugged_ts"] = ts
        elif raw.upper() in {"CHARGING", "FASTCHARGING"}:
            mapped["charging"] = True
            mapped["charging_ts"] = ts
            mapped["plugged"] = True
            mapped["plugged_ts"] = ts
        elif raw.upper() in {"NOCHARGING", "STOPPED"}:
            mapped["charging"] = False
            mapped["charging_ts"] = ts
    elif item_id in {"2042082", "2210012"} and boo is not None:
        mapped["plugged"] = boo
        mapped["plugged_ts"] = ts
    elif item_id == "2041301" and num is not None:
        mapped["limitSoc"] = num
        mapped["limitSoc_ts"] = ts
    elif item_id == "2210005" and num is not None:
        mapped["chargeLimitMode"] = num
        mapped["chargeLimitMode_ts"] = ts
    elif item_id in {"2210010", "2220001"} and num is not None:
        mapped["altitude"] = num
        mapped["altitude_ts"] = ts
    elif item_id in {"2013022"} and num is not None:
        mapped["remainingChargeMinutes"] = num
        mapped["remainingChargeMinutes_ts"] = ts
    elif item_id in {"2210013", "2222001"} and raw:
        mapped["preconditioning"] = raw.lower()
        mapped["preconditioning_ts"] = ts

    name = (field_name or "").strip().lower()
    if name == "latitude" and num is not None:
        mapped["latitude"] = num
        mapped["latitude_ts"] = ts
        mapped["lastUpdate"] = ts
    elif name == "longitude" and num is not None:
        mapped["longitude"] = num
        mapped["longitude_ts"] = ts
        mapped["lastUpdate"] = ts
    elif name == "acquisitiontime" and num is not None:
        mapped["lastAcquisitionTime"] = num
        mapped["lastAcquisitionTime_ts"] = ts
    elif name == "updatetime" and num is not None:
        mapped["lastUpdateTimeRaw"] = num
        mapped["lastUpdateTimeRaw_ts"] = ts
    elif name == "chargingport" and boo is not None:
        mapped["plugged"] = boo
        mapped["plugged_ts"] = ts
    elif name == "status" and raw.upper() in {"DISCONNECTED", "CONNECTED", "NOCHARGING", "CHARGING", "FASTCHARGING"}:
        if raw.upper() in {"DISCONNECTED"}:
            mapped["plugged"] = False
            mapped["plugged_ts"] = ts
            mapped["charging"] = False
            mapped["charging_ts"] = ts
        elif raw.upper() in {"CONNECTED", "NOCHARGING"}:
            mapped["plugged"] = True
            mapped["plugged_ts"] = ts
            mapped["charging"] = False
            mapped["charging_ts"] = ts
        elif raw.upper() in {"CHARGING", "FASTCHARGING"}:
            mapped["plugged"] = True
            mapped["plugged_ts"] = ts
            mapped["charging"] = True
            mapped["charging_ts"] = ts

    return mapped
