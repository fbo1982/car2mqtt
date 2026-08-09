from __future__ import annotations

import tempfile
import unittest
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

from app.core.config_store import ConfigStore
from app.core.models import RuntimeMqttSettings, VehicleConfig
from app.core.state_store import StateStore
from app.mapping.acconia_mapper import apply_acconia_metric
from app.providers.acconia_api import AcconiaSilenceApi
from app.providers.acconia_provider import AcconiaProvider
from app.providers.acconia_runner import AcconiaPollingWorker
from app.providers.registry import ProviderRegistry
from app.services.worker_manager import WorkerManager


SAMPLE = {
    "name": "Silence S01",
    "frameNo": "S01-TEST-123",
    "imei": "123456789012345",
    "batterySoc": 73,
    "range": 98,
    "charging": True,
    "lastLocation": {
        "latitude": 48.123,
        "longitude": 11.456,
        "altitude": 520,
    },
    "odometer": 1234,
}


class AcconiaIntegrationTests(unittest.TestCase):
    def test_provider_is_registered(self):
        registry = ProviderRegistry()
        descriptor = registry.get("acconia").descriptor()
        self.assertEqual(descriptor.id, "acconia")
        self.assertIn("Silence", descriptor.name)

    def test_provider_uses_default_api_key_and_clamps_polling(self):
        cfg = AcconiaProvider().validate_config(
            {"account": "user@example.com", "password": "secret", "poll_interval": 2}
        )
        self.assertEqual(cfg["api_key"], AcconiaSilenceApi.DEFAULT_FIREBASE_API_KEY)
        self.assertEqual(cfg["poll_interval"], 30)

    def test_mapper_maps_soc_range_and_exact_gps_axes(self):
        mapped = apply_acconia_metric({}, "", SAMPLE, capacity_kwh="5.6")
        self.assertEqual(mapped["soc"], 73)
        self.assertEqual(mapped["range"], 98)
        self.assertEqual(mapped["latitude"], 48.123)
        self.assertEqual(mapped["longitude"], 11.456)
        self.assertEqual(mapped["altitude"], 520)
        self.assertEqual(mapped["odometer"], 1234)
        self.assertTrue(mapped["charging"])
        self.assertTrue(mapped["plugged"])
        self.assertEqual(mapped["capacityKwh"], 5.6)
        self.assertEqual(mapped["vehicleType"], "ev")

    def test_mapper_prefers_explicit_connected_over_charging_order(self):
        payload_connected_then_charging = {
            "connected": True,
            "charging": False,
            "lastLocation": {"latitude": 48.1, "longitude": 11.4},
        }
        payload_charging_then_connected = {
            "charging": False,
            "connected": True,
            "lastLocation": {"latitude": 48.1, "longitude": 11.4},
        }
        first = apply_acconia_metric({}, "", payload_connected_then_charging)
        second = apply_acconia_metric({}, "", payload_charging_then_connected)
        self.assertFalse(first["charging"])
        self.assertTrue(first["plugged"])
        self.assertFalse(second["charging"])
        self.assertTrue(second["plugged"])

    def test_mapper_falls_back_to_charging_when_no_connection_flag_exists(self):
        mapped = apply_acconia_metric({}, "", {"charging": True})
        self.assertTrue(mapped["charging"])
        self.assertTrue(mapped["plugged"])
        mapped = apply_acconia_metric(mapped, "", {"charging": False})
        self.assertFalse(mapped["charging"])
        self.assertFalse(mapped["plugged"])

    def test_runner_selects_requested_scooter(self):
        vehicle = VehicleConfig(
            id="SILENCE1",
            label="Silence",
            manufacturer="acconia",
            license_plate="SIL 1",
            provider_config={"scooter_id": "target-frame"},
        )
        worker = AcconiaPollingWorker(
            vehicle=vehicle,
            on_payload=lambda _data: None,
            on_connect=lambda: None,
            on_error=lambda _message: None,
            on_detail=lambda _message: None,
        )
        selected = worker._select_scooter(
            [{"frameNo": "other"}, {"frameNo": "TARGET-FRAME", "batterySoc": 50}]
        )
        self.assertEqual(selected["batterySoc"], 50)

    def test_worker_manager_updates_runtime_without_mqtt_broker(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_store = ConfigStore(tmp)
            state_store = StateStore(tmp)
            vehicle = VehicleConfig(
                id="SILENCE1",
                label="Silence",
                manufacturer="acconia",
                license_plate="SIL 1",
                provider_config={
                    "account": "user@example.com",
                    "password": "secret",
                    "poll_interval": 60,
                    "capacity_kwh": 5.6,
                },
            )
            vehicle.provider_state.auth_state = "error"
            vehicle.provider_state.auth_message = "MySilence Login fehlgeschlagen"
            vehicle.provider_state.last_error = "temporärer Fehler"
            config_store.upsert_vehicle(vehicle)
            manager = WorkerManager(tmp, config_store, state_store)
            manager._handle_acconia_payload(
                vehicle.id,
                SAMPLE,
                RuntimeMqttSettings(host="", base_topic="car"),
            )
            runtime = state_store.get_all()[vehicle.id]
            self.assertEqual(runtime.connection_state, "connected")
            self.assertEqual(runtime.metrics["soc"], 73)
            self.assertEqual(runtime.metrics["range"], 98)
            self.assertEqual(runtime.metrics["latitude"], 48.123)
            self.assertEqual(runtime.metrics["longitude"], 11.456)
            self.assertEqual(runtime.provider_meta["frameNo"], "S01-TEST-123")
            saved_vehicle = config_store.get_vehicle(vehicle.id)
            self.assertIsNotNone(saved_vehicle)
            self.assertEqual(saved_vehicle.provider_state.auth_state, "authorized")
            self.assertEqual(saved_vehicle.provider_state.last_error, "")

    def test_template_contains_create_and_edit_fields(self):
        html = Path("app/templates/index.html").read_text(encoding="utf-8")
        for field_id in (
            "acconiaCreateSection",
            "acconiaAccount",
            "acconiaPassword",
            "editAcconiaSection",
            "editAcconiaAccount",
            "editAcconiaPassword",
        ):
            self.assertIn(f'id="{field_id}"', html)
        self.assertIn("createState.manufacturer === 'acconia'", html)
        self.assertIn("manufacturer === 'acconia'", html)


if __name__ == "__main__":
    unittest.main()
