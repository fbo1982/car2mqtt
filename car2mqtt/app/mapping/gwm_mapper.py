from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
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

    # Documented upstream examples / known datapoints
    if item_id == "2013021" and num is not None:  # SoC
        mapped["soc"] = num
        mapped["soc_ts"] = ts
    elif item_id == "2011501" and num is not None:  # range km
        mapped["range"] = num
        mapped["range_ts"] = ts
    elif item_id == "2103010" and num is not None:  # odometer km
        mapped["odometer"] = num
        mapped["odometer_ts"] = ts
    elif item_id == "2013022" and num is not None:  # remaining charge min
        mapped["remainingChargeMinutes"] = num
        mapped["remainingChargeMinutes_ts"] = ts
    elif item_id == "2041142" and boo is not None:  # charging active
        mapped["charging"] = boo
        mapped["charging_ts"] = ts
        if boo:
            mapped["plugged"] = True
            mapped["plugged_ts"] = ts
    elif item_id == "2042082" and boo is not None:
        mapped["plugged"] = boo
        mapped["plugged_ts"] = ts

    name = (field_name or "").strip().lower()
    if name == "latitude" and num is not None:
        mapped["latitude"] = num
        mapped["latitude_ts"] = ts
    elif name == "longitude" and num is not None:
        mapped["longitude"] = num
        mapped["longitude_ts"] = ts
    elif name == "acquisitiontime" and num is not None:
        mapped["lastAcquisitionTime"] = num
        mapped["lastAcquisitionTime_ts"] = ts
    elif name == "updatetime" and num is not None:
        mapped["lastUpdateTimeRaw"] = num
        mapped["lastUpdateTimeRaw_ts"] = ts

    return mapped
