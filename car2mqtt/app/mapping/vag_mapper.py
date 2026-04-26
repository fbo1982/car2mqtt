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
    if s in {"1", "true", "yes", "ja", "on", "charging", "connected", "plugged"}:
        return True
    if s in {"0", "false", "no", "nein", "off", "not_charging", "disconnected", "unplugged"}:
        return False
    return v


def map_vag_payload(raw: Dict[str, Any], provider_config: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Map a normalized VAG source snapshot into Car2MQTT metrics.

    This is intentionally source-shape tolerant so the later VW/Audi/Škoda/SEAT/CUPRA
    connectors can feed canonical keys without changing the dashboard mapping.
    """
    cfg = provider_config or {}
    ts = raw.get("timestamp") or raw.get("updatedAt") or _now()
    vehicle_type = str(raw.get("vehicleType") or cfg.get("powertrain") or "unknown").lower()
    if vehicle_type == "bev":
        vehicle_type = "electric"
    if vehicle_type == "phev":
        vehicle_type = "hybrid"
    if vehicle_type in {"ice", "fuel"}:
        vehicle_type = "combustion"
    if vehicle_type == "electric":
        # Dashboard currently uses ev for legacy BMW/GWM cards.
        vehicle_type = "ev"

    mapped: Dict[str, Any] = {
        "vehicleType": vehicle_type,
        "vehicleType_ts": ts,
        "lastUpdate": ts,
    }
    brand = cfg.get("brand") or raw.get("brand")
    if brand:
        mapped["brand"] = brand
        mapped["brand_ts"] = ts

    pairs = {
        "soc": ["soc", "stateOfCharge", "batterySoc"],
        "limitSoc": ["limitSoc", "targetSoc", "chargeLimit"],
        "range": ["range", "electricRange", "batteryRange"],
        "fuelLevel": ["fuelLevel", "fuelPercent"],
        "fuelRange": ["fuelRange", "combustionRange"],
        "odometer": ["odometer", "mileage"],
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

    for out_key, in_keys in {"charging": ["charging", "isCharging"], "plugged": ["plugged", "isPlugged", "externalPower"]}.items():
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
