from pathlib import Path
import sys
import types

try:
    import paho.mqtt.client  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    paho = types.ModuleType("paho")
    paho_mqtt = types.ModuleType("paho.mqtt")
    paho_client = types.ModuleType("paho.mqtt.client")

    class _DummyClient:
        def __init__(self, *args, **kwargs):
            pass

    paho_client.Client = _DummyClient
    paho_client.MQTT_ERR_SUCCESS = 0
    paho_mqtt.client = paho_client
    paho.mqtt = paho_mqtt
    sys.modules["paho"] = paho
    sys.modules["paho.mqtt"] = paho_mqtt
    sys.modules["paho.mqtt.client"] = paho_client

from app.core.models import RuntimeMqttSettings, UiSettings, VehicleConfig
from app.services.evcc_geo import ZonePosition, calculate_evcc_geo_decision, haversine_distance_m
from app.services.evcc_integration import build_evcc_custom_vehicle_payload, evcc_payload_to_yaml


def test_haversine_distance_is_small_for_nearby_points():
    # Roughly 11.1 m north at this latitude delta.
    distance = haversine_distance_m(49.0, 8.0, 49.0001, 8.0)
    assert 10.0 < distance < 12.5


def test_geo_disabled_mirrors_legacy_connected_and_charging():
    zone = ZonePosition("zone.test", 49.0, 8.0)
    assert calculate_evcc_geo_decision({"plugged": False, "charging": False}, geo_enabled=False, zone=zone, radius_m=30).status == "A"
    assert calculate_evcc_geo_decision({"plugged": True, "charging": False}, geo_enabled=False, zone=zone, radius_m=30).status == "B"
    assert calculate_evcc_geo_decision({"plugged": True, "charging": True}, geo_enabled=False, zone=zone, radius_m=30).status == "C"


def test_geo_filter_only_exposes_connected_inside_local_radius():
    zone = ZonePosition("zone.cae", 49.0000, 8.0000)
    inside = calculate_evcc_geo_decision(
        {"plugged": True, "charging": False, "latitude": 49.0001, "longitude": 8.0000},
        geo_enabled=True,
        zone=zone,
        radius_m=30,
    )
    outside = calculate_evcc_geo_decision(
        {"plugged": True, "charging": True, "latitude": 49.0100, "longitude": 8.0000},
        geo_enabled=True,
        zone=zone,
        radius_m=30,
    )
    assert inside.status == "B"
    assert inside.at_site is True
    assert inside.reason == "at_site_plugged"
    assert outside.status == "A"
    assert outside.at_site is False
    assert outside.reason == "outside_radius"


def test_geo_filter_fails_closed_without_zone_or_gps():
    no_zone = calculate_evcc_geo_decision(
        {"plugged": True, "charging": False, "latitude": 49.0, "longitude": 8.0},
        geo_enabled=True,
        zone=None,
        radius_m=30,
    )
    no_gps = calculate_evcc_geo_decision(
        {"plugged": True, "charging": True},
        geo_enabled=True,
        zone=ZonePosition("zone.home", 49.0, 8.0),
        radius_m=30,
    )
    assert no_zone.status == "A" and no_zone.reason == "zone_unavailable"
    assert no_gps.status == "A" and no_gps.reason == "gps_missing"


def test_evcc_vehicle_template_reads_single_derived_status_topic():
    vehicle = VehicleConfig(id="GGCA501E", label="Test BMW", manufacturer="bmw", license_plate="GG CA 501E")
    settings = RuntimeMqttSettings(host="mqtt", base_topic="car")
    payload = build_evcc_custom_vehicle_payload(vehicle, settings)
    assert payload["status"] == {
        "source": "mqtt",
        "topic": "car/bmw/GGCA501E/mapped/evccStatus",
        "timeout": "72h",
    }
    yaml_text = evcc_payload_to_yaml(payload)
    assert "status:\n  source: mqtt\n  topic: car/bmw/GGCA501E/mapped/evccStatus\n  timeout: 72h" in yaml_text
    assert "source: combined" not in yaml_text


def test_evcc_live_telemetry_uses_three_day_timeout():
    vehicle = VehicleConfig(id="GGCA501E", label="Test BMW", manufacturer="bmw", license_plate="GG CA 501E")
    settings = RuntimeMqttSettings(host="mqtt", base_topic="car")
    payload = build_evcc_custom_vehicle_payload(vehicle, settings)
    for key in ("soc", "range", "odometer", "status"):
        assert payload[key]["timeout"] == "72h"


def test_evcc_limitsoc_is_retained_without_freshness_timeout():
    vehicle = VehicleConfig(id="GGCA501E", label="Test BMW", manufacturer="bmw", license_plate="GG CA 501E")
    settings = RuntimeMqttSettings(host="mqtt", base_topic="car")
    payload = build_evcc_custom_vehicle_payload(vehicle, settings)
    assert payload["limitsoc"] == {
        "source": "mqtt",
        "topic": "car/bmw/GGCA501E/mapped/limitSoc",
    }
    yaml_text = evcc_payload_to_yaml(payload)
    assert "limitsoc:\n  source: mqtt\n  topic: car/bmw/GGCA501E/mapped/limitSoc\n" in yaml_text
    limitsoc_section = yaml_text.split("limitsoc:\n", 1)[1].split("\nstatus:\n", 1)[0]
    assert "timeout:" not in limitsoc_section


def test_silence_evcc_template_uses_single_phase_geo_status_and_no_limitsoc():
    vehicle = VehicleConfig(
        id="SILENCES04",
        label="Silence S04 (David)",
        manufacturer="acconia",
        license_plate="VERSICHERUNGSKENNZEICHEN",
        provider_config={"evcc_capacity_kwh": "11"},
    )
    settings = RuntimeMqttSettings(host="mqtt", base_topic="car")
    payload = build_evcc_custom_vehicle_payload(vehicle, settings)
    assert payload["capacity"] == 11.0
    assert payload["phases"] == 1
    assert payload["onIdentify"]["mode"] == "now"
    assert "limitsoc" not in payload
    assert payload["status"]["topic"] == "car/acconia/VERSICHERUNGSKENNZEICHEN/mapped/evccStatus"
    yaml_text = evcc_payload_to_yaml(payload)
    assert "phases: 1" in yaml_text
    assert "limitsoc:" not in yaml_text
    assert "source: combined" not in yaml_text


def test_geo_settings_are_upgrade_safe_and_ui_controls_exist():
    ui = UiSettings()
    assert ui.evcc_geo_filter_enabled is False
    assert ui.evcc_geo_radius_m == 30.0
    html = Path("app/templates/index.html").read_text(encoding="utf-8")
    assert 'id="settingsEvccGeoFilterEnabled"' in html
    assert 'id="settingsEvccGeoRadius"' in html
    assert "/evccStatus" in html
