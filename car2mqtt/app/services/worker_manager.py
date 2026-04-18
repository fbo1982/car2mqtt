from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

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

    def start_all(self) -> None:
        settings = load_runtime_mqtt_settings()
        for vehicle in self.config_store.load().vehicles:
            if vehicle.manufacturer in {"bmw", "gwm"} and vehicle.enabled and vehicle.provider_state.auth_state == "authorized":
                self.start_or_restart_vehicle(vehicle.id, settings)

    def stop_vehicle(self, vehicle_id: str) -> None:
        worker = self.workers.pop(vehicle_id, None)
        if worker:
            worker.stop()
            self.log_store.append(vehicle_id, "Worker gestoppt")

    def start_or_restart_vehicle(self, vehicle_id: str, mqtt_settings=None) -> None:
        mqtt_settings = mqtt_settings or load_runtime_mqtt_settings()
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle or vehicle.manufacturer not in {"bmw", "gwm"}:
            return
        if not vehicle.enabled:
            self._set_runtime_state(vehicle_id, "inactive", "Fahrzeug ist inaktiv")
            self.log_store.append(vehicle_id, "Fahrzeug ist inaktiv - kein Remote-Login, kein Streaming")
            return
        self.stop_vehicle(vehicle_id)
        if vehicle.manufacturer == "gwm":
            vehicle_dir = self.data_dir / 'providers' / vehicle.id
            self.workers[vehicle_id] = GwmIntegratedWorker(
                vehicle=vehicle,
                mqtt_settings=mqtt_settings,
                vehicle_dir=vehicle_dir,
                on_connect=lambda vid=vehicle_id: self._set_runtime_state(vid, "connected", "ORA Runner aktiv und lokaler MQTT Stream verbunden"),
                on_disconnect=lambda rc, vid=vehicle_id: self._set_runtime_state(vid, "disconnected", f"ORA Verbindung getrennt (rc={rc})"),
                on_error=lambda message, vid=vehicle_id: self._set_runtime_state(vid, "error", message),
                on_waiting=lambda message, vid=vehicle_id: self._set_runtime_state(vid, "waiting_for_code", message),
                on_detail=lambda message, vid=vehicle_id: self._set_runtime_state(vid, "starting", message),
                on_message=lambda topic, payload, vid=vehicle_id: self._handle_gwm_payload(vid, topic, payload, mqtt_settings),
                log_callback=lambda message, vid=vehicle_id: self.log_store.append(vid, message),
            )
            self.log_store.append(vehicle_id, "ORA Workerstart angefordert")
            self._set_runtime_state(vehicle_id, "starting", "ORA Worker startet")
            self.workers[vehicle_id].start()
            return

        self.workers[vehicle_id] = BMWStreamWorker(
            vehicle=vehicle,
            mqtt_settings=mqtt_settings,
            state_store=self.state_store,
            local_mqtt_client_factory=LocalMqttClient,
            on_payload=lambda topic, data, vid=vehicle_id: self._handle_bmw_payload(vid, topic, data, mqtt_settings),
            on_connect=lambda vid=vehicle_id: self._set_runtime_state(vid, "connected", "Mit BMW Streaming-Server verbunden"),
            on_disconnect=lambda rc, vid=vehicle_id: self._set_runtime_state(vid, "disconnected", f"BMW Verbindung getrennt (rc={rc})"),
            on_error=lambda message, vid=vehicle_id: self._set_runtime_state(vid, "error", message),
            on_detail=lambda message, vid=vehicle_id: self._set_runtime_state(vid, "starting", message),
            log_callback=lambda message, vid=vehicle_id: self.log_store.append(vid, message),
        )
        self.log_store.append(vehicle_id, "Workerstart angefordert")
        self._set_runtime_state(vehicle_id, "starting", "Worker startet")
        self.workers[vehicle_id].start()

    def _runtime_topics(self, vehicle, settings, callback_topic: str = "") -> tuple[str, str]:
        raw_topic = raw_vehicle_topic(
            settings.base_topic,
            vehicle.manufacturer,
            vehicle.license_plate,
        )
        return raw_topic, mapped_topic(settings.base_topic, vehicle.manufacturer, vehicle.license_plate)

    def _set_runtime_state(self, vehicle_id: str, state: str, detail: str) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return
        settings = load_runtime_mqtt_settings()
        raw_topic, mapped = self._runtime_topics(vehicle, settings)
        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        runtime.connection_state = state
        runtime.connection_detail = detail
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.raw_topic = raw_topic
        runtime.mapped_topic = mapped
        self.state_store.upsert(runtime)
        self.log_store.append(vehicle_id, f"Status -> {state}: {detail}")
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
        for metric_name, metric_data in data_points.items():
            metric_topic = f"{base_topic_prefix}/{metric_name.replace('.', '/')}"
            client.publish(metric_topic, metric_data)
            if isinstance(metric_data, dict):
                for key, value in metric_data.items():
                    client.publish(f"{metric_topic}/{key}", value)
            parts = metric_name.split('.')
            ref = nested
            for part in parts[:-1]:
                ref = ref.setdefault(part, {})
            ref[parts[-1]] = metric_data
        return nested

    def _deep_merge_dict(self, target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                self._deep_merge_dict(target[key], value)
            else:
                target[key] = value
        return target

    def _handle_bmw_payload(self, vehicle_id: str, callback_topic: str, data: Dict[str, Any], mqtt_settings) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return
        client = LocalMqttClient(mqtt_settings)
        raw_topic_base, mapped = self._runtime_topics(vehicle, mqtt_settings, callback_topic)
        try:
            client.connect()
            nested = self._flatten_publish(client, raw_topic_base, data)
            cached = self._bmw_raw_cache.get(vehicle_id, {})
            merged = self._deep_merge_dict(cached, nested)
            self._bmw_raw_cache[vehicle_id] = merged
            mapped_payload = map_bmw_payload(merged)
            for key, value in mapped_payload.items():
                client.publish(f"{mapped}/{key}", value)
        finally:
            client.disconnect()

        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        runtime.connection_state = "connected"
        runtime.connection_detail = "Streaming aktiv"
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.last_update = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
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
        source_base = str(vehicle.provider_config.get("source_topic_base", "")).strip() or f"GWM/{vehicle.provider_config.get('vehicle_id', vehicle.id)}"
        if source_topic.startswith(source_base + "/"):
            relative = source_topic[len(source_base) + 1:]
        else:
            relative = source_topic

        raw_topic_base, mapped = self._runtime_topics(vehicle, mqtt_settings)
        target_topic = f"{raw_topic_base}/{relative}"

        client = LocalMqttClient(mqtt_settings)
        try:
            client.connect()
            client.publish(target_topic, payload)
        finally:
            client.disconnect()

        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        metrics = dict(runtime.metrics or {})
        parts = source_topic.split("/")
        item_id = ""
        if "items" in parts:
            idx = parts.index("items")
            if len(parts) > idx + 1:
                item_id = parts[idx + 1]
        metrics = apply_gwm_metric(metrics, item_id, payload)

        runtime.connection_state = "connected"
        runtime.connection_detail = "ORA Stream aktiv"
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.raw_topic = raw_topic_base
        runtime.mapped_topic = mapped
        runtime.metrics = metrics
        runtime.provider_meta = {
            "vehicle_id": vehicle.provider_config.get("vehicle_id", vehicle.id),
            "source_topic_base": source_base,
        }

        from datetime import datetime, timezone
        runtime.last_update = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
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

    def delete_vehicle(self, vehicle_id: str) -> None:
        self.stop_vehicle(vehicle_id)
        self.state_store.delete(vehicle_id)
        self.log_store.append(vehicle_id, "Fahrzeug gelöscht")
        self.log_store.delete(vehicle_id)
