from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Tuple


def _extract(raw: Dict[str, Any], path: str, default=None):
    node: Any = raw
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _metric(raw: Dict[str, Any], base_path: str, default=None) -> Tuple[Any, Any]:
    return (
        _extract(raw, f"{base_path}.value", default),
        _extract(raw, f"{base_path}.timestamp", None),
    )


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


def _ts_or_now(ts: Any) -> str:
    if ts:
        return ts
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def map_bmw_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    soc, soc_ts = _metric(raw, "vehicle.drivetrain.batteryManagement.header", None)
    plugged_raw, plugged_ts = _metric(raw, "vehicle.body.chargingPort.status", None)
    odometer, odometer_ts = _metric(raw, "vehicle.vehicle.travelledDistance", None)
    ev_range, range_ts = _metric(raw, "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange", None)
    limit_soc, limit_soc_ts = _metric(raw, "vehicle.powertrain.electric.battery.stateOfCharge.target", None)
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

    fuel_level, fuel_level_ts = _metric(raw, "vehicle.drivetrain.fuelSystem.level", None)
    fuel_range, fuel_range_ts = _metric(raw, "vehicle.drivetrain.lastRemainingRange", None)

    has_fuel = fuel_level not in (None, "", "null")
    has_battery_signal = any(v not in (None, "", "null") for v in [soc, ev_range, limit_soc, capacity])
    if has_fuel and has_battery_signal:
        vehicle_type = "hybrid"
    elif has_fuel:
        vehicle_type = "combustion"
    else:
        vehicle_type = "ev"

    last_update_ts = (
        soc_ts or plugged_ts or odometer_ts or range_ts or limit_soc_ts or charging_ts
        or longitude_ts or latitude_ts or altitude_ts or preconditioning_ts or capacity_ts
        or fuel_level_ts or fuel_range_ts
    )

    mapped = {
        "soc": soc,
        "soc_ts": _ts_or_now(soc_ts),
        "plugged": _to_bool_from_status(plugged_raw, {"DISCONNECTED", "FALSE", "0", "NO", "OFF"}),
        "plugged_ts": _ts_or_now(plugged_ts),
        "odometer": odometer,
        "odometer_ts": _ts_or_now(odometer_ts),
        "range": ev_range,
        "range_ts": _ts_or_now(range_ts),
        "charging": _to_bool_from_status(charging_raw, {"NOCHARGING", "FALSE", "0", "NO", "OFF"}),
        "charging_ts": _ts_or_now(charging_ts),
        "preconditioning": preconditioning,
        "preconditioning_ts": _ts_or_now(preconditioning_ts),
        "capacityKwh": _to_float_or_none(capacity),
        "capacityKwh_ts": _ts_or_now(capacity_ts),
        "vehicleType": vehicle_type,
        "vehicleType_ts": _ts_or_now(last_update_ts),
        "lastUpdate": _ts_or_now(last_update_ts),
    }

    limit_soc_value = _to_float_or_none(limit_soc)
    if limit_soc_value is not None:
        mapped["limitSoc"] = limit_soc_value
        mapped["limitSoc_ts"] = _ts_or_now(limit_soc_ts)

    longitude_value = _to_float_or_none(longitude)
    if longitude_value is not None:
        mapped["longitude"] = longitude_value
        mapped["longitude_ts"] = _ts_or_now(longitude_ts)

    latitude_value = _to_float_or_none(latitude)
    if latitude_value is not None:
        mapped["latitude"] = latitude_value
        mapped["latitude_ts"] = _ts_or_now(latitude_ts)

    altitude_value = _to_float_or_none(altitude)
    if altitude_value is not None:
        mapped["altitude"] = altitude_value
        mapped["altitude_ts"] = _ts_or_now(altitude_ts)

    if vehicle_type != "ev":
        fuel_level_value = _to_float_or_none(fuel_level)
        if fuel_level_value is not None:
            mapped["fuelLevel"] = fuel_level_value
            mapped["fuelLevel_ts"] = _ts_or_now(fuel_level_ts)

        fuel_range_value = _to_float_or_none(fuel_range)
        if fuel_range_value is not None:
            mapped["fuelRange"] = fuel_range_value
            mapped["fuelRange_ts"] = _ts_or_now(fuel_range_ts)

    return mapped
