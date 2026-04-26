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
    if s in {"1", "true", "yes", "ja", "on", "charging", "connected", "plugged", "fast", "slow", "ready"}:
        return True
    if s in {"0", "false", "no", "nein", "off", "not_charging", "disconnected", "unplugged", "idle"}:
        return False
    return v


def map_mg_payload(raw: Dict[str, Any], provider_config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Map a future MG/iSMART snapshot into the common Car2MQTT metrics."""
    cfg = provider_config or {}
    ts = raw.get("timestamp") or raw.get("updatedAt") or raw.get("lastUpdate") or raw.get("time") or _now()
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
        "brand": "mg",
        "brand_ts": ts,
        "lastUpdate": ts,
    }

    pairs = {
        "soc": ["soc", "stateOfCharge", "batterySoc", "battery_level", "batteryLevel", "evBatteryLevel"],
        "limitSoc": ["limitSoc", "targetSoc", "chargeLimit", "targetSoC", "bmsTargetSoc"],
        "range": ["range", "electricRange", "batteryRange", "evRange", "electric_range"],
        "fuelLevel": ["fuelLevel", "fuelPercent", "fuel_level"],
        "fuelRange": ["fuelRange", "combustionRange", "dte", "fuel_range"],
        "odometer": ["odometer", "mileage", "totalMileage", "total_mileage"],
        "latitude": ["latitude", "lat"],
        "longitude": ["longitude", "lon", "lng"],
        "altitude": ["altitude", "alt"],
        "capacityKwh": ["capacityKwh", "batteryCapacityKwh", "battery_capacity_kwh"],
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
        "charging": ["charging", "isCharging", "chargingState", "charge_status"],
        "plugged": ["plugged", "isPlugged", "externalPower", "pluggedIn", "chargerConnected"],
        "doorsLocked": ["doorsLocked", "locked", "lockStatus"],
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
