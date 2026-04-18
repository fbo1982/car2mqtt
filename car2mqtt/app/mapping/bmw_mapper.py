from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def _extract(raw: Dict[str, Any], path: str, default=None):
    node: Any = raw
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _metric(raw: Dict[str, Any], base_path: str, default=None):
    value = _extract(raw, f"{base_path}.value", default)
    ts = _extract(raw, f"{base_path}.timestamp", None)
    return value, ts


def _to_bool_from_status(value: Any, false_values: set[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).upper() not in false_values


def _to_float_or_none(value: Any):
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except Exception:
        return value


def map_bmw_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    soc, soc_ts = _metric(raw, "vehicle.drivetrain.batteryManagement.header", 0)
    plugged_raw, plugged_ts = _metric(raw, "vehicle.body.chargingPort.status", None)
    odometer, odometer_ts = _metric(raw, "vehicle.vehicle.travelledDistance", 0)
    ev_range, range_ts = _metric(raw, "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange", 0)
    limit_soc, limit_soc_ts = _metric(raw, "vehicle.powertrain.electric.battery.stateOfCharge.target", 100)
    charging_raw, charging_ts = _metric(raw, "vehicle.drivetrain.electricEngine.charging.status", None)
    longitude, longitude_ts = _metric(raw, "vehicle.cabin.infotainment.navigation.currentLocation.longitude", None)
    latitude, latitude_ts = _metric(raw, "vehicle.cabin.infotainment.navigation.currentLocation.latitude", None)
    altitude, altitude_ts = _metric(raw, "vehicle.cabin.infotainment.navigation.currentLocation.altitude", None)

    preconditioning, preconditioning_ts = _metric(raw, "vehicle.vehicle.preConditioning.activity", None)
    if preconditioning is None:
        preconditioning, preconditioning_ts = _metric(raw, "vehicle.vehicle.preConditioning.status", None)

    capacity, capacity_ts = _metric(raw, "vehicle.drivetrain.batteryManagement.maxEnergy", None)
    if capacity in (None, "", 0, "0", "0.0"):
        capacity, capacity_ts = _metric(raw, "vehicle.drivetrain.batteryManagement.batterySizeMax", None)

    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    mapped = {
        "soc": soc,
        "soc_ts": soc_ts,
        "plugged": _to_bool_from_status(plugged_raw, {"DISCONNECTED", "FALSE", "0", "NO", "OFF"}),
        "plugged_ts": plugged_ts,
        "odometer": odometer,
        "odometer_ts": odometer_ts,
        "range": ev_range,
        "range_ts": range_ts,
        "limitSoc": limit_soc,
        "limitSoc_ts": limit_soc_ts,
        "charging": _to_bool_from_status(charging_raw, {"NOCHARGING", "FALSE", "0", "NO", "OFF"}),
        "charging_ts": charging_ts,
        "longitude": _to_float_or_none(longitude),
        "longitude_ts": longitude_ts,
        "latitude": _to_float_or_none(latitude),
        "latitude_ts": latitude_ts,
        "altitude": _to_float_or_none(altitude),
        "altitude_ts": altitude_ts,
        "preconditioning": preconditioning,
        "preconditioning_ts": preconditioning_ts,
        "capacityKwh": _to_float_or_none(capacity),
        "capacityKwh_ts": capacity_ts,
        "lastUpdate": now_iso,
    }
    return mapped
