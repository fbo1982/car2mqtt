from __future__ import annotations

from typing import Any, Dict

from ..models import CanonicalMapping


BMW_EXAMPLE_MAPPING = {
    "soc": ("drivetrain.batteryManagement.header.value", 97),
    "range": ("drivetrain.electricEngine.kombiRemainingElectricRange.value", 61),
    "charging": ("drivetrain.electricEngine.charging.status.value", "NOCHARGING"),
    "plugged": ("body.chargingPort.status.value", "DISCONNECTED"),
    "odometer": ("vehicle.travelledDistance.value", 1485),
    "limitSoc": ("powertrain.electric.battery.stateOfCharge.target.value", 100),
    "longitude": ("cabin.infotainment.navigation.currentLocation.longitude.value", 8.4960091667),
    "latitude": ("cabin.infotainment.navigation.currentLocation.latitude.value", 49.82877),
}


def example_bmw_mapping() -> CanonicalMapping:
    return CanonicalMapping(
        soc=97,
        soc_ts="2026-04-17T16:10:44Z",
        plugged=False,
        plugged_ts="2026-04-17T16:10:44Z",
        odometer=1485,
        odometer_ts="2026-04-17T16:10:44Z",
        range=61,
        range_ts="2026-04-17T16:10:44Z",
        limitSoc=100,
        limitSoc_ts="2026-04-17T16:10:44Z",
        charging=False,
        charging_ts="2026-04-17T16:10:44Z",
        longitude=8.4960091667,
        longitude_ts="2026-04-17T16:10:44Z",
        latitude=49.82877,
        latitude_ts="2026-04-17T16:10:44Z",
    )


def passthrough_mapping(payload: Dict[str, Any]) -> CanonicalMapping:
    return CanonicalMapping(**{k: v for k, v in payload.items() if k in CanonicalMapping.model_fields})
