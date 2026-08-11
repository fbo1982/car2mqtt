from app.mapping.bmw_mapper import map_bmw_payload
from app.services.worker_manager import _bmw_obsolete_metric_keys


def _put_metric(root: dict, path: str, value, ts: str = "2026-08-11T10:00:00Z") -> None:
    node = root
    parts = path.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = {"value": value, "timestamp": ts}


def test_x5_combustion_is_not_promoted_to_hybrid_by_charge_target_or_generic_range():
    raw = {}
    _put_metric(raw, "vehicle.drivetrain.fuelSystem.level", 36)
    _put_metric(raw, "vehicle.drivetrain.lastRemainingRange", 234)
    _put_metric(raw, "vehicle.drivetrain.batteryManagement.header", 80)
    _put_metric(raw, "vehicle.powertrain.electric.battery.stateOfCharge.target", 100)

    mapped = map_bmw_payload(raw, {"vehicleType": "hybrid", "limitSoc": 100})

    assert mapped["vehicleType"] == "combustion"
    assert mapped["fuelLevel"] == 36.0
    assert mapped["fuelRange"] == 234.0
    assert "limitSoc" not in mapped
    assert "soc" not in mapped
    assert "range" not in mapped


def test_ix1_bev_does_not_expose_generic_remaining_range_as_fuel_range():
    raw = {}
    _put_metric(raw, "vehicle.drivetrain.batteryManagement.header", 79)
    _put_metric(raw, "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange", 324)
    _put_metric(raw, "vehicle.drivetrain.batteryManagement.maxEnergy", 63.0)
    _put_metric(raw, "vehicle.drivetrain.lastRemainingRange", 324)
    _put_metric(raw, "vehicle.powertrain.electric.battery.stateOfCharge.target", 100)

    mapped = map_bmw_payload(raw, {"vehicleType": "hybrid", "fuelRange": 324.0})

    assert mapped["vehicleType"] == "ev"
    assert mapped["soc"] == 79
    assert mapped["range"] == 324
    assert mapped["capacityKwh"] == 63.0
    assert "fuelLevel" not in mapped
    assert "fuelRange" not in mapped


def test_x1_phev_keeps_both_electric_and_fuel_metrics():
    raw = {}
    _put_metric(raw, "vehicle.drivetrain.batteryManagement.header", 65)
    _put_metric(raw, "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange", 44)
    _put_metric(raw, "vehicle.drivetrain.batteryManagement.maxEnergy", 14.0)
    _put_metric(raw, "vehicle.drivetrain.fuelSystem.level", 76)
    _put_metric(raw, "vehicle.drivetrain.lastRemainingRange", 460)
    _put_metric(raw, "vehicle.powertrain.electric.battery.stateOfCharge.target", 95)

    mapped = map_bmw_payload(raw, {"vehicleType": "ev"})

    assert mapped["vehicleType"] == "hybrid"
    assert mapped["soc"] == 65
    assert mapped["range"] == 44
    assert mapped["fuelLevel"] == 76.0
    assert mapped["fuelRange"] == 460.0
    assert mapped["limitSoc"] == 95.0


def test_stale_cross_powertrain_metrics_are_selected_for_mqtt_tombstones():
    ev_state = {"vehicleType": "ev", "fuelLevel": None, "fuelRange": 324.0, "fuelRange_ts": "old"}
    combustion_state = {"vehicleType": "combustion", "soc": None, "range": None, "limitSoc": 100.0, "limitSoc_ts": "old"}

    assert _bmw_obsolete_metric_keys("ev", ev_state) == {"fuelLevel", "fuelRange", "fuelRange_ts"}
    assert _bmw_obsolete_metric_keys("combustion", combustion_state) == {"soc", "range", "limitSoc", "limitSoc_ts"}
