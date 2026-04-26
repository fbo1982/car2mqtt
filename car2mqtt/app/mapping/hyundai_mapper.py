from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _num(v: Any):
    if v in (None, "", "null"):
        return None
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return v


def _bool(v: Any):
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in {"1", "true", "yes", "ja", "on", "charging", "connected", "plugged", "fast", "slow"}:
        return True
    if s in {"0", "false", "no", "nein", "off", "not_charging", "disconnected", "unplugged"}:
        return False
    return v


def map_hyundai_payload(raw: Dict[str, Any], provider_config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Map a future Hyundai/Bluelink snapshot into the common Car2MQTT metrics."""
    cfg = provider_config or {}
    ts = raw.get("timestamp") or raw.get("updatedAt") or raw.get("lastUpdate") or _now()
    vehicle_type = str(raw.get("vehicleType") or cfg.get("powertrain") or "unknown").lower()
    if vehicle_type in {"bev", "ev", "electric"}:
        vehicle_type = "ev"
    elif vehicle_type in {"phev", "hev", "hybrid"}:
        vehicle_type = "hybrid"
    elif vehicle_type in {"ice", "fuel", "combustion"}:
        vehicle_type = "combustion"

    mapped: Dict[str, Any] = {
        "vehicleType": vehicle_type,
        "vehicleType_ts": ts,
        "brand": "hyundai",
        "brand_ts": ts,
        "lastUpdate": ts,
    }

    pairs = {
        "soc": ["soc", "stateOfCharge", "batterySoc", "evBatteryLevel"],
        "limitSoc": ["limitSoc", "targetSoc", "chargeLimit", "targetSoC"],
        "range": ["range", "electricRange", "batteryRange", "evRange"],
        "fuelLevel": ["fuelLevel", "fuelPercent"],
        "fuelRange": ["fuelRange", "combustionRange", "dte"],
        "odometer": ["odometer", "mileage", "totalMileage"],
        "latitude": ["latitude", "lat"],
        "longitude": ["longitude", "lon", "lng"],
        "altitude": ["altitude", "alt"],
        "capacityKwh": ["capacityKwh", "batteryCapacityKwh"],
    }
    for out_key, in_keys in pairs.items():
        value = None
        for key in in_keys:
            if key in raw:
                value = raw.get(key)
                break
        if value is None and out_key == "capacityKwh" and cfg.get("capacity_kwh") not in (None, ""):
            value = cfg.get("capacity_kwh")
        value = _num(value)
        if value is not None:
            mapped[out_key] = value
            mapped[f"{out_key}_ts"] = ts

    for out_key, in_keys in {
        "charging": ["charging", "isCharging", "chargingState"],
        "plugged": ["plugged", "isPlugged", "externalPower", "pluggedIn"],
        "doorsLocked": ["doorsLocked", "locked"],
    }.items():
        value = None
        for key in in_keys:
            if key in raw:
                value = raw.get(key)
                break
        value = _bool(value)
        if value is not None:
            mapped[out_key] = value
            mapped[f"{out_key}_ts"] = ts

    return mapped
