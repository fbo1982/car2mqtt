
from __future__ import annotations

from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any, Dict

import paho.mqtt.client as paho_mqtt

from app.core.config_store import ConfigStore
from app.core.models import VehicleRuntimeState
from app.core.runtime_settings import load_runtime_mqtt_settings
from app.core.state_store import StateStore
from app.core.vehicle_log_store import VehicleLogStore
from app.mapping.bmw_mapper import map_bmw_payload
from app.mapping.gwm_mapper import apply_gwm_metric
from app.mqtt.client import LocalMqttClient
from app.mqtt.topic_builder import mapped_topic, meta_topic, raw_vehicle_topic
from app.providers.bmw.streaming import BMWStreamWorker
from app.providers.gwm_runner import GwmIntegratedWorker


class WorkerManager:
    def __init__(self, data_dir: str, config_store: ConfigStore, state_store: StateStore):
        self.data_dir = Path(data_dir)
        self.config_store = config_store
        self.state_store = state_store
        self.log_store = VehicleLogStore(data_dir)
        self.workers: dict[str, object] = {}
        self._bmw_raw_cache: dict[str, dict] = {}

    def start_all(self) -> None:
        config = self.config_store.load()
        for vehicle in config.vehicles:
            if vehicle.enabled:
                self.start_or_restart_vehicle(vehicle.id)
            else:
                self._set_runtime_state(vehicle.id, "inactive", "Fahrzeug ist inaktiv")

    def stop_vehicle(self, vehicle_id: str) -> None:
        worker = self.workers.pop(vehicle_id, None)
        self._bmw_raw_cache.pop(vehicle_id, None)
        if worker:
            try:
                worker.stop()
            finally:
                self.log_store.append(vehicle_id, "Worker gestoppt")

    def start_or_restart_vehicle(self, vehicle_id: str) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return

        self.stop_vehicle(vehicle_id)

        if not vehicle.enabled:
            self._set_runtime_state(vehicle_id, "inactive", "Fahrzeug ist inaktiv")
            return

        mqtt_settings = load_runtime_mqtt_settings()
        if vehicle.manufacturer == "bmw":
            worker = BMWStreamWorker(
                vehicle=vehicle,
                mqtt_settings=mqtt_settings,
                state_store=self.state_store,
                local_mqtt_client_factory=self._create_local_mqtt_client,
                on_payload=lambda callback_topic, data: self._handle_bmw_payload(vehicle_id, callback_topic, data, mqtt_settings),
                on_connect=lambda: self._set_runtime_state(vehicle_id, "connected", "Mit BMW Streaming-Server verbunden"),
                on_disconnect=lambda rc: self._set_runtime_state(vehicle_id, "disconnected", f"BMW Verbindung getrennt (rc={rc})"),
                on_error=lambda message: self._handle_error(vehicle_id, message),
                on_detail=lambda detail: self._set_runtime_state(vehicle_id, "starting", detail),
                log_callback=lambda message: self.log_store.append(vehicle_id, message),
            )
        elif vehicle.manufacturer == "gwm":
            worker = GwmIntegratedWorker(
                vehicle=vehicle,
                settings=mqtt_settings,
                on_connect=lambda state, detail: self._set_runtime_state(vehicle_id, state, detail),
                log_callback=lambda message: self.log_store.append(vehicle_id, message),
                on_payload=lambda topic, payload: self._handle_gwm_payload(vehicle_id, topic, payload, mqtt_settings),
            )
        else:
            self._set_runtime_state(vehicle_id, "unsupported", f"Hersteller {vehicle.manufacturer} wird noch nicht unterstützt")
            return

        self.workers[vehicle_id] = worker
        self.log_store.append(vehicle_id, "Workerstart angefordert")
        worker.start()

    def _runtime_topics(self, vehicle, mqtt_settings) -> tuple[str, str]:
        raw_topic_base = raw_vehicle_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        mapped = mapped_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        return raw_topic_base, mapped

    def _set_runtime_state(self, vehicle_id: str, state: str, detail: str) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        runtime.connection_state = state
        runtime.connection_detail = detail
        runtime.last_update = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if vehicle:
            runtime.auth_state = vehicle.provider_state.auth_state
        self.state_store.upsert(runtime)

        mqtt_settings = load_runtime_mqtt_settings()
        if vehicle and mqtt_settings.host:
            self._publish_meta(vehicle, runtime, mqtt_settings)

    def _publish_meta(self, vehicle, runtime: VehicleRuntimeState, mqtt_settings) -> None:
        client = LocalMqttClient(mqtt_settings)
        topic = meta_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        try:
            client.connect()
            client.publish(f"{topic}/status", runtime.connection_state or "unknown")
            client.publish(f"{topic}/detail", runtime.connection_detail or "")
            client.publish(f"{topic}/auth_state", runtime.auth_state or "unknown")
            if runtime.raw_topic:
                client.publish(f"{topic}/raw_topic", runtime.raw_topic)
            if runtime.mapped_topic:
                client.publish(f"{topic}/mapped_topic", runtime.mapped_topic)
        finally:
            client.disconnect()

    def _flatten_publish(self, client: LocalMqttClient, base_topic: str, data: Any) -> dict:
        nested: dict[str, Any] = {}

        def rec(prefix: str, value: Any):
            if isinstance(value, dict):
                for k, v in value.items():
                    new_prefix = f"{prefix}/{k}" if prefix else k
                    rec(new_prefix, v)
            elif isinstance(value, list):
                for idx, v in enumerate(value):
                    new_prefix = f"{prefix}/{idx}" if prefix else str(idx)
                    rec(new_prefix, v)
            else:
                topic = f"{base_topic}/{prefix}" if prefix else base_topic
                client.publish(topic, value)
                parts = [p for p in prefix.split("/") if p]
                cur = nested
                for p in parts[:-1]:
                    cur = cur.setdefault(p, {})
                if parts:
                    cur[parts[-1]] = value

        rec("", data)
        return nested

    def _deep_merge_dict(self, left: dict, right: dict) -> dict:
        merged = dict(left)
        for key, value in right.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = self._deep_merge_dict(merged[key], value)
            else:
                merged[key] = value
        return merged

    def _handle_bmw_payload(self, vehicle_id: str, data: dict, callback_topic: str, mqtt_settings) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return

        raw_topic_base, mapped = self._runtime_topics(vehicle, mqtt_settings or self.settings)
        client = LocalMqttClient(mqtt_settings)
        try:
            client.connect()
            nested = self._flatten_publish(client, raw_topic_base, data)
            cached = self._bmw_raw_cache.get(vehicle_id, {})
            merged = self._deep_merge_dict(cached, nested)
            self._bmw_raw_cache[vehicle_id] = merged
            mapped_payload = map_bmw_payload(merged)
            for key, value in mapped_payload.items():
                client.publish(f"{mapped}/{key}", value)
            self.log_store.append(
                vehicle_id,
                f"BMW Mapping aktualisiert: soc={mapped_payload.get('soc')} range={mapped_payload.get('range')} odometer={mapped_payload.get('odometer')} capacityKwh={mapped_payload.get('capacityKwh')}"
            )
        finally:
            client.disconnect()

        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        runtime.connection_state = "connected"
        runtime.connection_detail = "Streaming aktiv"
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.last_update = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        runtime.raw_topic = raw_topic_base
        runtime.mapped_topic = mapped
        runtime.metrics = mapped_payload
        runtime.provider_meta = {
            "vin": vehicle.provider_config.get("vin", ""),
            "mqtt_username": vehicle.provider_state.mqtt_username or vehicle.provider_config.get("mqtt_username", ""),
            "gcid": vehicle.provider_state.mqtt_username or vehicle.provider_config.get("mqtt_username", ""),
        }
        self.state_store.upsert(runtime)
        count = len((data or {}).get("data", {}))
        self.log_store.append(vehicle_id, f"Live-Daten empfangen: {count} Datenpunkte -> {callback_topic} (Mapping aus kumuliertem Snapshot)")
        self._publish_meta(vehicle, runtime, mqtt_settings)

    def _handle_gwm_payload(self, vehicle_id: str, source_topic: str, payload: str, mqtt_settings) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return

        configured_source_base = str(vehicle.provider_config.get("source_topic_base", "")).strip() or "GWM"
        parts = source_topic.split("/")

        discovered_source_id = ""
        relative_parts = parts
        if len(parts) >= 3 and parts[0] == "GWM":
            discovered_source_id = parts[1]
            relative_parts = parts[2:]

        relative = "/".join(relative_parts)
        raw_topic_base, mapped = self._runtime_topics(vehicle, mqtt_settings or self.settings)
        target_topic = f"{raw_topic_base}/{relative}"

        client = LocalMqttClient(mqtt_settings)
        try:
            client.connect()
            client.publish(target_topic, payload)
        finally:
            client.disconnect()

        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        metrics = dict(runtime.metrics or {})

        field_name = parts[-1] if parts else ""
        item_id = ""
        if "items" in parts:
            idx = parts.index("items")
            if len(parts) > idx + 1:
                item_id = parts[idx + 1]
            if len(parts) > idx + 2:
                field_name = parts[idx + 2]

        metrics = apply_gwm_metric(metrics, item_id, payload, field_name)

        runtime.connection_state = "connected"
        runtime.connection_detail = "ORA Stream aktiv"
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.last_update = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        runtime.raw_topic = raw_topic_base
        runtime.mapped_topic = mapped
        runtime.metrics = metrics
        runtime.provider_meta = {
            "vehicle_id": vehicle.provider_config.get("vehicle_id", vehicle.id),
            "configured_source_topic_base": configured_source_base,
            "discovered_source_id": discovered_source_id,
            "source_topic": source_topic,
            "normalized_target_root": raw_topic_base,
        }
        self.state_store.upsert(runtime)

        if metrics:
            client = LocalMqttClient(mqtt_settings)
            try:
                client.connect()
                for key, value in metrics.items():
                    client.publish(f"{mapped}/{key}", value)
            finally:
                client.disconnect()

        self.log_store.append(vehicle_id, f"ORA Datenpunkt empfangen: {source_topic} = {payload}")
        self._publish_meta(vehicle, runtime, mqtt_settings)

    def publish_vehicle_saved_meta(self, vehicle_id: str) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if vehicle and not vehicle.enabled:
            self._set_runtime_state(vehicle_id, "inactive", "Fahrzeug ist inaktiv")
            self.log_store.append(vehicle_id, "Fahrzeugkonfiguration gespeichert (inaktiv)")
            return
        self._set_runtime_state(vehicle_id, "saved", "Fahrzeug gespeichert")
        self.log_store.append(vehicle_id, "Fahrzeugkonfiguration gespeichert")

    def test_map_gwm_from_upstream(self, vehicle_id: str, mqtt_settings, wait_seconds: int = 6) -> dict:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle or vehicle.manufacturer != "gwm":
            raise ValueError("ORA Fahrzeug nicht gefunden")

        seen = {"count": 0}
        topic = "GWM/+/status/#"

        client = paho_mqtt.Client(client_id=f"car2mqtt-gwmtest-{vehicle_id[:8]}")
        if mqtt_settings.username:
            client.username_pw_set(mqtt_settings.username, mqtt_settings.password)

        def on_connect(c, _u, _f, rc, _p=None):
            if rc == 0:
                c.subscribe(topic, qos=mqtt_settings.qos)

        def on_message(_c, _u, msg):
            try:
                payload = msg.payload.decode("utf-8", errors="ignore")
                self._handle_gwm_payload(vehicle_id, msg.topic, payload, mqtt_settings)
                seen["count"] += 1
            except Exception as exc:
                self.log_store.append(vehicle_id, f"ORA Test-Mapping Fehler: {exc}")

        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(mqtt_settings.host, mqtt_settings.port, 30)
        client.loop_start()
        self.log_store.append(vehicle_id, f"ORA Test-Mapping gestartet: {topic}")
        time.sleep(wait_seconds)
        client.loop_stop()
        client.disconnect()
        self.log_store.append(vehicle_id, f"ORA Test-Mapping beendet: {seen['count']} MQTT-Nachrichten verarbeitet")
        return seen

    def delete_vehicle(self, vehicle_id: str) -> None:
        self.stop_vehicle(vehicle_id)
        self.state_store.remove(vehicle_id)
        self.log_store.clear(vehicle_id)
