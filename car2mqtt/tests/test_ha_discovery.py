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
from app.services.ha_discovery import build_discovery_configs


def _vehicle() -> VehicleConfig:
    return VehicleConfig(
        id="GGCA501E",
        label="BMW i4",
        manufacturer="BMW",
        license_plate="GG CA 501E",
        provider_config={"vin": "TESTVIN"},
    )


def test_upgrade_default_keeps_discovery_disabled_to_avoid_yaml_collision():
    ui = UiSettings()
    assert ui.ha_discovery_enabled is False
    assert ui.ha_discovery_prefix == "homeassistant"
    assert ui.ha_discovery_retain is True


def test_discovery_preserves_copy_helper_entity_ids():
    settings = RuntimeMqttSettings(host="mqtt", base_topic="car")
    configs = dict(build_discovery_configs(_vehicle(), settings))

    topic = "homeassistant/sensor/car_bmw_ggca501e_plugged/config"
    assert topic in configs
    cfg = configs[topic]
    assert cfg["unique_id"] == "car_bmw_ggca501e_plugged"
    assert cfg["default_entity_id"] == "sensor.car_bmw_ggca501e_plugged"
    assert cfg["state_topic"] == "car/bmw/GGCA501E/mapped/plugged"

    ts = configs["homeassistant/sensor/car_bmw_ggca501e_plugged_ts/config"]
    assert ts["default_entity_id"] == "sensor.car_bmw_ggca501e_plugged_ts"
    assert ts["device_class"] == "timestamp"

    lat = configs["homeassistant/sensor/car_bmw_ggca501e_latitude/config"]
    lon = configs["homeassistant/sensor/car_bmw_ggca501e_longitude/config"]
    assert lat["default_entity_id"] == "sensor.car_bmw_ggca501e_latitude"
    assert lon["default_entity_id"] == "sensor.car_bmw_ggca501e_longitude"


def test_discovery_exposes_common_read_only_vehicle_entities():
    settings = RuntimeMqttSettings(host="mqtt", base_topic="car")
    configs = dict(build_discovery_configs(_vehicle(), settings))
    topics = set(configs)

    for key in ("soc", "range", "odometer", "limitsoc", "capacitykwh", "vehicletype", "lastupdate"):
        assert f"homeassistant/sensor/car_bmw_ggca501e_{key}/config" in topics

    assert "homeassistant/binary_sensor/car_bmw_ggca501e_charging/config" in topics
    assert "homeassistant/binary_sensor/car_bmw_ggca501e_plugged/config" in topics
    assert not any("/button/" in topic or "/number/" in topic for topic in topics)


def test_discovery_uses_device_registry_context_and_custom_prefix():
    settings = RuntimeMqttSettings(host="mqtt", base_topic="fleet")
    configs = dict(build_discovery_configs(_vehicle(), settings, "ha-test"))
    cfg = configs["ha-test/sensor/car_bmw_ggca501e_soc/config"]
    assert cfg["state_topic"] == "fleet/bmw/GGCA501E/mapped/soc"
    assert cfg["device"]["name"] == "BMW i4"
    assert cfg["device"]["manufacturer"] == "BMW"


def test_ui_contains_discovery_migration_and_publish_controls():
    html = Path("app/templates/index.html").read_text(encoding="utf-8")
    for field_id in (
        "settingsHaDiscoveryEnabled",
        "settingsHaDiscoveryPrefix",
        "settingsHaDiscoveryRetain",
        "publishHaDiscoveryBtn",
        "publishVehicleDiscoveryBtn",
    ):
        assert f'id="{field_id}"' in html
    assert "api/ha-discovery/publish" in html
    assert "ha-discovery/publish" in html
    assert "configuration.yaml" in html


def test_app_config_roundtrips_discovery_settings():
    cfg = AppConfig(ui_settings=UiSettings(ha_discovery_enabled=True, ha_discovery_prefix="ha", ha_discovery_retain=False))
    restored = AppConfig.model_validate(cfg.model_dump(mode="json"))
    assert restored.ui_settings.ha_discovery_enabled is True
    assert restored.ui_settings.ha_discovery_prefix == "ha"
    assert restored.ui_settings.ha_discovery_retain is False
