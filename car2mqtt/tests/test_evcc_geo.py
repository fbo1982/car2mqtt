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

from app.core.models import AppConfig, RuntimeMqttSettings, UiSettings, VehicleConfig
from app.services.evcc_geo import EvccGeoFilterService, ZonePosition, calculate_evcc_geo_decision, haversine_distance_m
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


def test_geo_presence_uses_enter_exit_hysteresis():
    zone = ZonePosition("zone.home", 49.0, 8.0)
    # ~33 m north: outside 30 m entry radius, but inside 50 m exit radius.
    metrics = {"plugged": False, "charging": False, "latitude": 49.00030, "longitude": 8.0}
    before_entry = calculate_evcc_geo_decision(
        metrics, geo_enabled=True, zone=zone, radius_m=30, exit_radius_m=50, previous_at_site=False
    )
    while_inside = calculate_evcc_geo_decision(
        metrics, geo_enabled=True, zone=zone, radius_m=30, exit_radius_m=50, previous_at_site=True
    )
    assert before_entry.at_site is False
    assert while_inside.at_site is True


def _relay_service() -> EvccGeoFilterService:
    ui = UiSettings(
        evcc_geo_filter_enabled=True,
        evcc_geo_radius_m=30,
        evcc_geo_exit_radius_m=50,
        geo_shelly_host="192.168.18.29",
        geo_shelly_switch_id=0,
        geo_shelly_power_off_threshold_w=50,
    )
    vehicle = VehicleConfig(
        id="TEST",
        label="Test Silence",
        manufacturer="acconia",
        license_plate="TEST",
        geo_shelly_trigger_enabled=True,
    )
    service = EvccGeoFilterService(
        lambda: AppConfig(ui_settings=ui, vehicles=[vehicle]),
        lambda: RuntimeMqttSettings(host="mqtt", base_topic="car"),
    )
    service._load_feature_settings()
    return service


def test_geo_shelly_only_acts_on_edges_and_does_not_force_initial_outside_off():
    service = _relay_service()
    root = "car/acconia/TEST/mapped"

    service._schedule_relay_edge(root, None, False)
    assert service._relay_pending_on is False
    assert service._relay_pending_off is False

    service._schedule_relay_edge(root, None, True)
    assert service._relay_pending_on is True
    assert service._relay_pending_off is False

    # EVCC may turn the Shelly off later; Car2MQTT does not keep enforcing ON.
    service._relay_pending_on = False
    service._schedule_relay_edge(root, True, True)
    assert service._relay_pending_on is False

    service._schedule_relay_edge(root, True, False)
    assert service._relay_pending_off is True

    # A return before the delayed OFF is executed cancels the pending OFF.
    service._schedule_relay_edge(root, False, True)
    assert service._relay_pending_off is False
    assert service._relay_pending_on is True


def test_geo_shelly_departure_waits_until_power_is_below_threshold(monkeypatch):
    service = _relay_service()
    service._relay_pending_off = True
    calls = []

    monkeypatch.setattr(service, "_read_shelly_status", lambda: (True, 1200.0))
    monkeypatch.setattr(service, "_set_shelly_output", lambda enabled: calls.append(enabled))
    service._process_relay_once()
    assert calls == []
    assert service._relay_pending_off is True

    monkeypatch.setattr(service, "_read_shelly_status", lambda: (True, 10.0))
    service._process_relay_once()
    assert calls == [False]
    assert service._relay_pending_off is False


def test_geo_shelly_arrival_turns_on_once(monkeypatch):
    service = _relay_service()
    service._relay_pending_on = True
    calls = []
    monkeypatch.setattr(service, "_read_shelly_status", lambda: (False, 0.0))
    monkeypatch.setattr(service, "_set_shelly_output", lambda enabled: calls.append(enabled))
    service._process_relay_once()
    assert calls == [True]
    assert service._relay_pending_on is False


def test_geo_settings_use_per_vehicle_shelly_selection():
    ui = UiSettings()
    vehicle = VehicleConfig(id="TEST", label="Test", manufacturer="acconia", license_plate="TEST")
    assert ui.evcc_geo_exit_radius_m == 50.0
    assert ui.geo_shelly_vehicle_mapped_topic == ""
    assert ui.geo_shelly_power_off_threshold_w == 50.0
    assert vehicle.geo_shelly_trigger_enabled is False
    html = Path("app/templates/index.html").read_text(encoding="utf-8")
    assert 'id="settingsEvccGeoExitRadius"' in html
    assert 'id="settingsGeoShellyHost"' in html
    assert 'id="editGeoShellyTriggerEnabled"' in html
    assert 'id="editRemoteGeoShellyTriggerEnabled"' in html
    assert 'id="settingsGeoShellyVehicle"' not in html
    assert 'id="settingsGeoShellyEnabled"' not in html


def test_geo_shelly_multiple_selected_vehicles_only_switch_off_after_last_departure():
    ui = UiSettings(geo_shelly_host="192.168.18.29", geo_shelly_power_off_threshold_w=50)
    vehicles = [
        VehicleConfig(id="A", label="A", manufacturer="bmw", license_plate="A", geo_shelly_trigger_enabled=True),
        VehicleConfig(id="B", label="B", manufacturer="acconia", license_plate="B", geo_shelly_trigger_enabled=True),
    ]
    service = EvccGeoFilterService(
        lambda: AppConfig(ui_settings=ui, vehicles=vehicles),
        lambda: RuntimeMqttSettings(host="mqtt", base_topic="car"),
    )
    service._load_feature_settings()
    a = "car/bmw/A/mapped"
    b = "car/acconia/B/mapped"
    service._presence_by_root[a] = True
    service._presence_by_root[b] = True

    service._schedule_relay_edge(a, True, False)
    assert service._relay_pending_off is False

    service._presence_by_root[a] = False
    service._schedule_relay_edge(b, True, False)
    assert service._relay_pending_off is True


def test_home_zone_resolver_falls_back_to_ha_config(monkeypatch):
    from app.services.evcc_geo import HomeAssistantZoneResolver

    class Resp:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.text = text
            self.ok = 200 <= status_code < 300

        def json(self):
            return self._payload

    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")

    def fake_get(url, **kwargs):
        if url.endswith("/api/config"):
            return Resp(200, {"latitude": 49.1234, "longitude": 8.5678})
        return Resp(404, {}, "Not Found")

    monkeypatch.setattr("app.services.evcc_geo.requests.get", fake_get)
    resolver = HomeAssistantZoneResolver()
    zone = resolver.resolve("zone.home")
    assert zone == ZonePosition("zone.home", 49.1234, 8.5678)
    assert resolver.last_error == ""


def test_custom_zone_resolver_uses_template_fallback(monkeypatch):
    from app.services.evcc_geo import HomeAssistantZoneResolver

    class Resp:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload
            self.text = text
            self.ok = 200 <= status_code < 300

        def json(self):
            return self._payload

    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    monkeypatch.setattr(
        "app.services.evcc_geo.requests.get",
        lambda *args, **kwargs: Resp(404, {}, "Not Found"),
    )

    def fake_post(url, **kwargs):
        assert url.endswith("/api/template")
        assert "zone.cae" in kwargs["json"]["template"]
        return Resp(200, text='{"latitude":49.2222,"longitude":8.3333}')

    monkeypatch.setattr("app.services.evcc_geo.requests.post", fake_post)
    resolver = HomeAssistantZoneResolver()
    zone = resolver.resolve("zone.cae")
    assert zone == ZonePosition("zone.cae", 49.2222, 8.3333)
    assert resolver.last_error == ""


def test_zone_resolver_exposes_http_diagnostics(monkeypatch):
    from app.services.evcc_geo import HomeAssistantZoneResolver

    class Resp:
        status_code = 403
        ok = False
        text = "Forbidden"

        def json(self):
            return {}

    monkeypatch.setenv("SUPERVISOR_TOKEN", "test-token")
    monkeypatch.setattr("app.services.evcc_geo.requests.get", lambda *args, **kwargs: Resp())
    monkeypatch.setattr("app.services.evcc_geo.requests.post", lambda *args, **kwargs: Resp())
    resolver = HomeAssistantZoneResolver()
    assert resolver.resolve("zone.home") is None
    assert "HTTP 403" in resolver.last_error
