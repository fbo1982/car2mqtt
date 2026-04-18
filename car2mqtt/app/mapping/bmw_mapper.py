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


def map_bmw_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    charging_status = _extract(raw, "vehicle.drivetrain.electricEngine.charging.status.value", "")
    charging_port = _extract(raw, "vehicle.body.chargingPort.status.value", "")
    comfort = _extract(raw, "vehicle.vehicle.preConditioning.status.value", None)
    capacity = _extract(raw, "vehicle.drivetrain.batteryManagement.maxEnergy.value", None)
    if capacity in (None, "", 0, "0", "0.0"):
        capacity = _extract(raw, "vehicle.drivetrain.batteryManagement.batterySizeMax.value", None)
    try:
        if capacity not in (None, ""):
            capacity = float(capacity)
    except Exception:
        pass

    mapped = {
        "soc": _extract(raw, "vehicle.drivetrain.batteryManagement.header.value", 0),
        "plugged": charging_port not in (None, "", "DISCONNECTED"),
        "odometer": _extract(raw, "vehicle.vehicle.travelledDistance.value", 0),
        "range": _extract(raw, "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange.value", 0),
        "limitSoc": _extract(raw, "vehicle.powertrain.electric.battery.stateOfCharge.target.value", 100),
        "charging": charging_status not in (None, "", "NOCHARGING"),
        "longitude": _extract(raw, "vehicle.cabin.infotainment.navigation.currentLocation.longitude.value", None),
        "latitude": _extract(raw, "vehicle.cabin.infotainment.navigation.currentLocation.latitude.value", None),
        "altitude": _extract(raw, "vehicle.cabin.infotainment.navigation.currentLocation.altitude.value", None),
        "preconditioning": comfort,
        "capacityKwh": capacity,
        "lastUpdate": datetime.now(timezone.utc).isoformat(),
    }
    return mapped
