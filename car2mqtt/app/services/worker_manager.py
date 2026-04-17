from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from app.core.config_store import ConfigStore
from app.core.models import VehicleRuntimeState
from app.core.state_store import StateStore
from app.core.runtime_settings import load_runtime_mqtt_settings
from app.mapping.bmw_mapper import map_bmw_payload
from app.mqtt.client import LocalMqttClient
from app.mqtt.topic_builder import base_vehicle_topic, mapped_topic, meta_topic
from app.providers.bmw.streaming import BMWStreamWorker


class WorkerManager:
    def __init__(self, data_dir: str, config_store: ConfigStore, state_store: StateStore):
        self.data_dir = Path(data_dir)
        self.config_store = config_store
        self.state_store = state_store
        self.workers: dict[str, BMWStreamWorker] = {}

    def start_all(self) -> None:
        settings = load_runtime_mqtt_settings()
        for vehicle in self.config_store.load().vehicles:
            if vehicle.manufacturer == "bmw" and vehicle.enabled and vehicle.provider_state.auth_state == "authorized":
                self.start_or_restart_vehicle(vehicle.id, settings)

    def start_or_restart_vehicle(self, vehicle_id: str, mqtt_settings=None) -> None:
        mqtt_settings = mqtt_settings or load_runtime_mqtt_settings()
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle or vehicle.manufacturer != "bmw":
            return
        if vehicle_id in self.workers:
            self.workers[vehicle_id].stop()
        self.workers[vehicle_id] = BMWStreamWorker(
            vehicle=vehicle,
            mqtt_settings=mqtt_settings,
            state_store=self.state_store,
            local_mqtt_client_factory=LocalMqttClient,
            on_payload=lambda topic, data, vid=vehicle_id: self._handle_bmw_payload(vid, topic, data, mqtt_settings),
            on_connect=lambda vid=vehicle_id: self._set_runtime_state(vid, "connected", "Mit BMW Streaming-Server verbunden"),
            on_disconnect=lambda rc, vid=vehicle_id: self._set_runtime_state(vid, "disconnected", f"BMW Verbindung getrennt (rc={rc})"),
            on_error=lambda message, vid=vehicle_id: self._set_runtime_state(vid, "error", message),
        )
        self._set_runtime_state(vehicle_id, "starting", "Worker startet")
        self.workers[vehicle_id].start()

    def _set_runtime_state(self, vehicle_id: str, state: str, detail: str) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return
        settings = load_runtime_mqtt_settings()
        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        runtime.connection_state = state
        runtime.connection_detail = detail
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.raw_topic = base_vehicle_topic(settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        runtime.mapped_topic = mapped_topic(settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        self.state_store.upsert(runtime)
        self._publish_meta(vehicle, runtime, settings)

    def _publish_meta(self, vehicle, runtime: VehicleRuntimeState, settings) -> None:
        if not settings.host:
            return
        topic = meta_topic(settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        client = LocalMqttClient(settings)
        try:
            client.connect()
            client.publish(f"{topic}/status", runtime.connection_state)
            client.publish(f"{topic}/detail", runtime.connection_detail)
            client.publish(f"{topic}/auth_state", runtime.auth_state)
            client.publish(f"{topic}/raw_topic", runtime.raw_topic)
            client.publish(f"{topic}/mapped_topic", runtime.mapped_topic)
            if runtime.last_update:
                client.publish(f"{topic}/last_update", runtime.last_update)
        finally:
            client.disconnect()

    def _flatten_publish(self, client: LocalMqttClient, base_topic_prefix: str, data: Dict[str, Any]) -> Dict[str, Any]:
        data_points = data.get("data", {})
        nested: Dict[str, Any] = {}
        client.publish(base_topic_prefix, data_points)
        for metric_name, metric_data in data_points.items():
            topic = f"{base_topic_prefix}/{metric_name.replace('.', '/')}"
            client.publish(topic, metric_data)
            if isinstance(metric_data, dict):
                for key, value in metric_data.items():
                    client.publish(f"{topic}/{key}", value)
            parts = metric_name.split(".")
            ref = nested
            for part in parts[:-1]:
                ref = ref.setdefault(part, {})
            ref[parts[-1]] = metric_data
        return nested

    def _handle_bmw_payload(self, vehicle_id: str, _topic: str, data: Dict[str, Any], mqtt_settings) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return
        client = LocalMqttClient(mqtt_settings)
        raw_topic_base = base_vehicle_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        try:
            client.connect()
            nested = self._flatten_publish(client, raw_topic_base, data)
            mapped = map_bmw_payload(nested)
            for key, value in mapped.items():
                client.publish(f"{mapped_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)}/{key}", value)
        finally:
            client.disconnect()

        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        runtime.connection_state = "connected"
        runtime.connection_detail = "Streaming aktiv"
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.last_update = datetime.now(timezone.utc).isoformat()
        runtime.raw_topic = raw_topic_base
        runtime.mapped_topic = mapped_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        runtime.metrics = mapped
        runtime.provider_meta = {
            "vin": vehicle.provider_config.get("vin", ""),
            "mqtt_username": vehicle.provider_state.mqtt_username,
        }
        self.state_store.upsert(runtime)
        self._publish_meta(vehicle, runtime, mqtt_settings)

    def publish_vehicle_saved_meta(self, vehicle_id: str) -> None:
        self._set_runtime_state(vehicle_id, "saved", "Fahrzeug gespeichert")
