from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple


EMPTY_VALUES = (None, "", "null", "NULL")


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


def _has_value(value: Any) -> bool:
    return value not in EMPTY_VALUES


def _to_bool_from_status(value: Any, false_values: set[str]) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().upper()
    return bool(text) and text not in false_values


def _to_bool_bmw_charging(status_value: Any, hv_status_value: Any = None, time_remaining_value: Any = None) -> bool:
    """Return a robust BMW charging state.

    BMW CarData sends different charging datapoints depending on model and release.
    Some cars never update status while charging, but do update hvStatus or
    timeRemaining. Missing values are handled by the caller and do not force False.
    """
    true_markers = {
        "CHARGING", "AC_CHARGING", "DC_CHARGING", "ACTIVE", "HV_ACTIVE",
        "IN_PROGRESS", "RUNNING", "ON", "TRUE", "1", "YES",
    }
    false_markers = {
        "NOCHARGING", "NO_CHARGING", "NOT_CHARGING", "INACTIVE", "FINISHED",
        "COMPLETE", "COMPLETED", "STOPPED", "OFF", "FALSE", "0", "NO",
        "UNKNOWN", "UNAVAILABLE", "NULL", "",
    }
    for value in (status_value, hv_status_value):
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().upper()
        if not text:
            continue
        if text in true_markers:
            return True
        if text in false_markers:
            return False
        if "CHARG" in text and "NO" not in text and "NOT" not in text:
            return True
        if "ACTIVE" in text and "INACTIVE" not in text:
            return True
    try:
        if _has_value(time_remaining_value) and float(time_remaining_value) > 0:
            return True
    except Exception:
        pass
    return False


def _to_float_or_none(value: Any):
    if not _has_value(value):
        return None
    try:
        return float(value)
    except Exception:
        return value


def _ts_or_now(ts: Any) -> str:
    if ts:
        return str(ts)
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _latest_ts(values: Iterable[Any]) -> Optional[str]:
    best_raw = None
    best_dt = None
    for value in values:
        parsed = _parse_ts(value)
        if parsed is None:
            continue
        if best_dt is None or parsed > best_dt:
            best_dt = parsed
            best_raw = str(value)
    return best_raw


def _set_metric(mapped: Dict[str, Any], key: str, value: Any, ts: Any, *, convert=None) -> None:
    if not _has_value(value):
        return
    mapped[key] = convert(value) if convert else value
    if ts:
        mapped[f"{key}_ts"] = str(ts)


def map_bmw_payload(raw: Dict[str, Any], previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Map cumulative BMW raw data to Car2MQTT's normalized schema.

    Important: BMW often sends only the changed datapoint. Therefore this mapper
    never emits placeholder/False/null values for datapoints that are not present
    in the cumulative snapshot. The caller can merge the result onto the previous
    mapped state so old valid values survive until BMW sends an update.
    """
    previous = previous or {}

    soc, soc_ts = _metric(raw, "vehicle.drivetrain.batteryManagement.header", None)
    plugged_raw, plugged_ts = _metric(raw, "vehicle.body.chargingPort.status", None)
    odometer, odometer_ts = _metric(raw, "vehicle.vehicle.travelledDistance", None)
    ev_range, range_ts = _metric(raw, "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange", None)
    limit_soc, limit_soc_ts = _metric(raw, "vehicle.powertrain.electric.battery.stateOfCharge.target", None)
    charging_raw, charging_ts = _metric(raw, "vehicle.drivetrain.electricEngine.charging.status", None)
    charging_hv_raw, charging_hv_ts = _metric(raw, "vehicle.drivetrain.electricEngine.charging.hvStatus", None)
    charging_time_remaining, charging_time_remaining_ts = _metric(raw, "vehicle.drivetrain.electricEngine.charging.timeRemaining", None)

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

    mapped: Dict[str, Any] = {}
    touched_ts: list[Any] = []

    _set_metric(mapped, "soc", soc, soc_ts)
    if soc_ts:
        touched_ts.append(soc_ts)

    if _has_value(plugged_raw):
        mapped["plugged"] = _to_bool_from_status(plugged_raw, {"DISCONNECTED", "FALSE", "0", "NO", "OFF"})
        if plugged_ts:
            mapped["plugged_ts"] = str(plugged_ts)
            touched_ts.append(plugged_ts)

    _set_metric(mapped, "odometer", odometer, odometer_ts)
    if odometer_ts:
        touched_ts.append(odometer_ts)

    _set_metric(mapped, "range", ev_range, range_ts)
    if range_ts:
        touched_ts.append(range_ts)

    limit_soc_value = _to_float_or_none(limit_soc)
    if limit_soc_value is not None:
        mapped["limitSoc"] = limit_soc_value
        if limit_soc_ts:
            mapped["limitSoc_ts"] = str(limit_soc_ts)
            touched_ts.append(limit_soc_ts)

    has_charging_signal = any(_has_value(v) for v in (charging_raw, charging_hv_raw, charging_time_remaining))
    if has_charging_signal:
        mapped["charging"] = _to_bool_bmw_charging(charging_raw, charging_hv_raw, charging_time_remaining)
        charging_any_ts = charging_ts or charging_hv_ts or charging_time_remaining_ts
        if charging_any_ts:
            mapped["charging_ts"] = str(charging_any_ts)
            touched_ts.append(charging_any_ts)
    elif "plugged" in mapped and mapped["plugged"] is False:
        # A freshly received unplugged state is enough to clear charging, even when
        # BMW does not send a separate charging.status update.
        mapped["charging"] = False
        if plugged_ts:
            mapped["charging_ts"] = str(plugged_ts)
    elif "plugged" in mapped and mapped["plugged"] is True and _has_value(soc):
        try:
            if _has_value(previous.get("soc")) and float(soc) > float(previous.get("soc")):
                mapped["charging"] = True
                mapped["charging_ts"] = str(soc_ts or plugged_ts or _ts_or_now(None))
        except Exception:
            pass

    _set_metric(mapped, "preconditioning", preconditioning, preconditioning_ts)
    if preconditioning_ts:
        touched_ts.append(preconditioning_ts)

    capacity_value = _to_float_or_none(capacity)
    if capacity_value is not None:
        mapped["capacityKwh"] = capacity_value
        if capacity_ts:
            mapped["capacityKwh_ts"] = str(capacity_ts)
            touched_ts.append(capacity_ts)

    longitude_value = _to_float_or_none(longitude)
    if longitude_value is not None:
        mapped["longitude"] = longitude_value
        if longitude_ts:
            mapped["longitude_ts"] = str(longitude_ts)
            touched_ts.append(longitude_ts)

    latitude_value = _to_float_or_none(latitude)
    if latitude_value is not None:
        mapped["latitude"] = latitude_value
        if latitude_ts:
            mapped["latitude_ts"] = str(latitude_ts)
            touched_ts.append(latitude_ts)

    altitude_value = _to_float_or_none(altitude)
    if altitude_value is not None:
        mapped["altitude"] = altitude_value
        if altitude_ts:
            mapped["altitude_ts"] = str(altitude_ts)
            touched_ts.append(altitude_ts)

    # BMW's vehicle.drivetrain.lastRemainingRange is a generic remaining-range
    # datapoint. Pure EVs expose it as well (often with the same value as the
    # dedicated electric range), so it must not be treated as proof of a fuel
    # system. Likewise stateOfCharge.target can appear on cars without a usable
    # traction-battery signal and is therefore too weak for powertrain detection.
    #
    # Classification is intentionally based on the two strong signal groups:
    #   * fuel system: a real fuel-level datapoint
    #   * electric drive: dedicated EV range or traction-battery capacity
    # A generic battery SoC by itself is deliberately not enough because 48-V
    # mild-hybrid/combustion BMWs can expose battery-management information too.
    # This distinguishes BEV / PHEV / combustion correctly for the BMW CarData
    # payloads while still retaining the previous type until a strong signal is
    # available after stream startup.
    has_fuel_system = _has_value(fuel_level)
    has_electric_drive = any(_has_value(v) for v in [ev_range, capacity])
    previous_type = str(previous.get("vehicleType") or "").strip().lower()
    vehicle_type = ""
    if has_fuel_system and has_electric_drive:
        vehicle_type = "hybrid"
    elif has_fuel_system:
        vehicle_type = "combustion"
    elif has_electric_drive:
        vehicle_type = "ev"
    elif previous_type in {"hybrid", "combustion", "ev"}:
        vehicle_type = previous_type

    if vehicle_type:
        mapped["vehicleType"] = vehicle_type
        type_ts = _latest_ts([fuel_level_ts, fuel_range_ts, soc_ts, range_ts, limit_soc_ts, capacity_ts])
        if type_ts:
            mapped["vehicleType_ts"] = type_ts

    # Do not emit metrics that belong to another powertrain. This prevents a
    # generic BMW datapoint (for example lastRemainingRange on a BEV) from being
    # exposed as a tank metric and keeps combustion cars free of stale EV values.
    if vehicle_type == "combustion":
        for key in (
            "soc", "soc_ts", "range", "range_ts", "charging", "charging_ts",
            "plugged", "plugged_ts", "limitSoc", "limitSoc_ts",
            "capacityKwh", "capacityKwh_ts",
        ):
            mapped.pop(key, None)
    elif vehicle_type == "ev":
        for key in ("fuelLevel", "fuelLevel_ts", "fuelRange", "fuelRange_ts"):
            mapped.pop(key, None)

    # BMW does not always publish the charge target. For EVs the UI/EVCC helper
    # should still have a sane value, but only emit it when missing locally.
    if vehicle_type == "ev" and "limitSoc" not in mapped and not _has_value(previous.get("limitSoc")):
        mapped["limitSoc"] = 100.0
        fallback_ts = _latest_ts([soc_ts, range_ts, capacity_ts])
        if fallback_ts:
            mapped["limitSoc_ts"] = fallback_ts

    if vehicle_type in {"hybrid", "combustion"}:
        fuel_level_value = _to_float_or_none(fuel_level)
        if fuel_level_value is not None:
            mapped["fuelLevel"] = fuel_level_value
            if fuel_level_ts:
                mapped["fuelLevel_ts"] = str(fuel_level_ts)
                touched_ts.append(fuel_level_ts)

        fuel_range_value = _to_float_or_none(fuel_range)
        if fuel_range_value is not None:
            mapped["fuelRange"] = fuel_range_value
            if fuel_range_ts:
                mapped["fuelRange_ts"] = str(fuel_range_ts)
                touched_ts.append(fuel_range_ts)

    latest = _latest_ts(touched_ts)
    if latest:
        mapped["lastUpdate"] = latest

    return mapped
