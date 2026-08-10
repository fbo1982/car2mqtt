import sys
import types

try:
    import paho.mqtt.client  # type: ignore  # noqa: F401
except Exception:
    paho = types.ModuleType("paho")
    paho_mqtt = types.ModuleType("paho.mqtt")
    paho_client = types.ModuleType("paho.mqtt.client")

    class _DummyClient:
        def __init__(self, *args, **kwargs):
            pass

    paho_client.Client = _DummyClient
    paho_client.MQTT_ERR_SUCCESS = 0
    paho_client.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
    paho_mqtt.client = paho_client
    paho.mqtt = paho_mqtt
    sys.modules["paho"] = paho
    sys.modules["paho.mqtt"] = paho_mqtt
    sys.modules["paho.mqtt.client"] = paho_client

from fastapi.testclient import TestClient
import pytest

from app.api.server import create_app
from app.core.config_store import ConfigStore
from app.core.models import VehicleConfig
from app.services.worker_manager import WorkerManager


@pytest.mark.parametrize(
    ("manufacturer", "plate", "provider_config"),
    [
        ("bmw", "GG-CA 501E", {"client_id": "cid", "vin": "WBY12345678901234", "region": "EU"}),
        (
            "gwm",
            "GG-CA 911E",
            {
                "account": "a",
                "password": "p",
                "country": "DE",
                "language": "de",
                "poll_interval": 60,
                "vehicle_id": "GGCA911E",
                "capacity_kwh": 65,
            },
        ),
        (
            "acconia",
            "VERSICHERUNGSKENNZEICHEN",
            {"account": "a@example.com", "password": "p", "poll_interval": 60, "capacity_kwh": 11},
        ),
    ],
)
def test_put_existing_vehicle_succeeds_for_all_providers(tmp_path, monkeypatch, manufacturer, plate, provider_config):
    """Regression for v1.2.62: every existing-vehicle PUT crashed on normalize_plate."""
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MQTT_HOST", "")

    # Keep this focused on persistence/validation; do not start provider workers.
    monkeypatch.setattr(WorkerManager, "start_or_restart_vehicle", lambda *args, **kwargs: None)
    monkeypatch.setattr(WorkerManager, "stop_vehicle", lambda *args, **kwargs: None)
    monkeypatch.setattr(WorkerManager, "publish_vehicle_saved_meta", lambda *args, **kwargs: None)
    monkeypatch.setattr(WorkerManager, "sync_vehicle_to_forward_clients", lambda *args, **kwargs: None)

    vehicle_id = "".join(ch for ch in plate if ch.isalnum()).upper()
    vehicle = VehicleConfig(
        id=vehicle_id,
        label=f"{manufacturer} test",
        manufacturer=manufacturer,
        license_plate=plate,
        provider_config=provider_config,
    )
    ConfigStore(str(tmp_path)).upsert_vehicle(vehicle)

    client = TestClient(create_app())
    response = client.put(
        f"/api/vehicles/{vehicle_id}",
        json={
            "id": vehicle_id,
            "label": vehicle.label,
            "manufacturer": manufacturer,
            "license_plate": plate,
            "enabled": True,
            "provider_config": provider_config,
            "mqtt_client_ids": [],
            "device_tracker_enabled": False,
            "geo_shelly_trigger_enabled": False,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok", "vehicle_id": vehicle_id}
