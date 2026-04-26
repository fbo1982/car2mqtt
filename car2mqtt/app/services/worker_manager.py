from __future__ import annotations

from datetime import datetime, timezone
import time
import threading
from pathlib import Path
import json
import os
import ssl

import requests
from typing import Any, Dict

import paho.mqtt.client as paho_mqtt

from app.core.config_store import ConfigStore
from app.core.models import VehicleRuntimeState, RuntimeMqttSettings
from app.core.runtime_settings import load_runtime_mqtt_settings
from app.core.state_store import StateStore
from app.core.vehicle_log_store import VehicleLogStore
from app.mapping.bmw_mapper import map_bmw_payload
from app.mapping.gwm_mapper import apply_gwm_metric
from app.mapping.acconia_mapper import apply_acconia_metric
from app.mapping.vag_mapper import map_vag_payload

GWM_OBSOLETE_MAPPED_KEYS = {
    "chargeLimitMode",
    "chargeLimitMode_ts",
    "chargingPortConnected",
    "chargingPortConnected_ts",
}

from app.mqtt.client import LocalMqttClient
from app.mqtt.topic_builder import mapped_topic, meta_topic, raw_vehicle_topic, vehicle_root_topic
from app.providers.bmw.streaming import BMWStreamWorker
from app.providers.gwm_runner import GwmIntegratedWorker
from app.providers.acconia_api import AcconiaSilenceApi



class AcconiaApiWorker:
    def __init__(self, vehicle, mqtt_settings, on_connect, on_disconnect, on_error, on_snapshot, log_callback):
        self.vehicle = vehicle
        self.mqtt_settings = mqtt_settings
        self.on_connect_cb = on_connect
        self.on_disconnect_cb = on_disconnect
        self.on_error_cb = on_error
        self.on_snapshot_cb = on_snapshot
        self.log_callback = log_callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        cfg = vehicle.provider_config or {}
        self.api = AcconiaSilenceApi(
            account=str(cfg.get("account", "")),
            password=str(cfg.get("password", "")),
            api_key=str(cfg.get("api_key", "")),
        )
        try:
            self.poll_interval = max(30, int(cfg.get("poll_interval") or 60))
        except Exception:
            self.poll_interval = 60

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=f"car2mqtt-acconia-{self.vehicle.id[:8]}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self.on_disconnect_cb(0)

    def _select_scooter(self, scooters: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not scooters:
            return None
        wanted = str((self.vehicle.provider_config or {}).get("vehicle_id") or self.vehicle.id or "").strip().lower()
        plate = "".join(ch for ch in self.vehicle.license_plate.upper().strip() if ch.isalnum()).lower()
        for scooter in scooters:
            candidates = [scooter.get("frameNo"), scooter.get("imei"), scooter.get("name"), scooter.get("vin"), scooter.get("id")]
            for candidate in candidates:
                normalized = "".join(ch for ch in str(candidate or "").upper().strip() if ch.isalnum()).lower()
                if normalized and normalized in {wanted, plate}:
                    return scooter
        return scooters[0]

    def _run(self) -> None:
        first_ok = False
        while not self._stop.is_set():
            try:
                scooters = self.api.fetch_scooters()
                scooter = self._select_scooter(scooters)
                if not scooter:
                    raise RuntimeError("Silence API liefert kein Fahrzeug zurück")
                if not first_ok:
                    first_ok = True
                    self.on_connect_cb()
                    self.log_callback("Acconia/Silence Login erfolgreich - API Polling aktiv")
                self.on_snapshot_cb(scooter)
            except Exception as exc:
                self.on_error_cb(f"Acconia/Silence API Fehler: {exc}")
                self.log_callback(f"Acconia/Silence API Fehler: {exc}")
            self._stop.wait(self.poll_interval)




class WorkerManager:
    def __init__(self, data_dir: str, config_store: ConfigStore, state_store: StateStore):
        self.data_dir = Path(data_dir)
        self.config_store = config_store
        self.state_store = state_store
        self.log_store = VehicleLogStore(data_dir)
        self.workers: dict[str, object] = {}
        self._bmw_raw_cache: dict[str, dict] = {}
        self.mqtt_client_status_file = self.data_dir / "mqtt_client_status.json"

    def start_all(self) -> None:
        settings = load_runtime_mqtt_settings()
        for vehicle in self.config_store.load().vehicles:
            if vehicle.manufacturer in {"bmw", "gwm", "acconia", "hyundai", "mg", "vag", "vw", "vwcv", "audi", "skoda", "seat", "cupra"} and vehicle.enabled and vehicle.provider_state.auth_state == "authorized":
                self.start_or_restart_vehicle(vehicle.id, settings)

    def stop_vehicle(self, vehicle_id: str) -> None:
        worker = self.workers.pop(vehicle_id, None)
        self._bmw_raw_cache.pop(vehicle_id, None)
        if worker:
            worker.stop()
            self.log_store.append(vehicle_id, "Worker gestoppt")

    def start_or_restart_vehicle(self, vehicle_id: str, mqtt_settings=None) -> None:
        mqtt_settings = mqtt_settings or load_runtime_mqtt_settings()
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle or vehicle.manufacturer not in {"bmw", "gwm", "acconia", "hyundai", "mg", "vag", "vw", "vwcv", "audi", "skoda", "seat", "cupra"}:
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
                on_error=lambda message, vid=vehicle_id: self._handle_gwm_error(vid, message),
                on_waiting=lambda message, vid=vehicle_id: self._set_runtime_state(vid, "waiting_for_code", message),
                on_detail=lambda message, vid=vehicle_id: self._set_runtime_state(vid, "starting", message),
                on_message=lambda topic, payload, vid=vehicle_id: self._handle_gwm_payload(vid, topic, payload, mqtt_settings),
                log_callback=lambda message, vid=vehicle_id: self.log_store.append(vid, message),
            )
            self.log_store.append(vehicle_id, "ORA Workerstart angefordert")
            self._set_runtime_state(vehicle_id, "starting", "ORA Worker startet")
            self.workers[vehicle_id].start()
            return


        if vehicle.manufacturer in {"hyundai", "mg"}:
            self.log_store.append(vehicle_id, "Hersteller-Grundstruktur gespeichert - API-Connector noch nicht aktiviert")
            self._set_runtime_state(vehicle_id, "saved", "Hersteller vorbereitet - nächster Schritt ist der API-Connector")
            return

        if vehicle.manufacturer in {"vag", "vw", "vwcv", "audi", "skoda", "seat", "cupra"}:
            self.log_store.append(vehicle_id, "Marken-Grundstruktur gespeichert - API-Connector noch nicht aktiviert")
            self._set_runtime_state(vehicle_id, "saved", "Marke vorbereitet - nächster Schritt ist der API-Connector")
            return

        if vehicle.manufacturer == "acconia":
            self.workers[vehicle_id] = AcconiaApiWorker(
                vehicle=vehicle,
                mqtt_settings=mqtt_settings,
                on_connect=lambda vid=vehicle_id: self._set_runtime_state(vid, "connected", "Acconia/Silence API verbunden"),
                on_disconnect=lambda rc, vid=vehicle_id: self._set_runtime_state(vid, "disconnected", f"Acconia/Silence API gestoppt (rc={rc})"),
                on_error=lambda message, vid=vehicle_id: self._set_runtime_state(vid, "error", message),
                on_snapshot=lambda data, vid=vehicle_id: self._handle_acconia_snapshot(vid, data, mqtt_settings),
                log_callback=lambda message, vid=vehicle_id: self.log_store.append(vid, message),
            )
            self.log_store.append(vehicle_id, "Acconia/Silence API Workerstart angefordert")
            self._set_runtime_state(vehicle_id, "starting", "Acconia/Silence API Worker startet")
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


    def sync_vehicle_to_forward_clients(self, vehicle_id: str) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return
        mqtt_settings = load_runtime_mqtt_settings()
        if not mqtt_settings.host:
            return
        runtime = self.state_store.get_all().get(vehicle_id)
        if not runtime:
            return
        # Forward current meta state
        meta_base = meta_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        vin_value = str(vehicle.provider_config.get("vin") or runtime.provider_meta.get("vin") or runtime.provider_meta.get("vehicle_id") or "")
        meta_values = {
            f"{meta_base}/status": runtime.connection_state,
            f"{meta_base}/detail": runtime.connection_detail,
            f"{meta_base}/auth_state": runtime.auth_state,
            f"{meta_base}/raw_topic": runtime.raw_topic,
            f"{meta_base}/mapped_topic": runtime.mapped_topic,
            f"{meta_base}/server_name": self._resolve_server_name(),
            f"{meta_base}/label": vehicle.label,
            f"{meta_base}/license_plate": vehicle.license_plate,
            f"{meta_base}/manufacturer": vehicle.manufacturer,
            f"{meta_base}/vin": vin_value,
        }
        if runtime.last_update:
            meta_values[f"{meta_base}/last_update"] = runtime.last_update
        for topic, value in meta_values.items():
            self._forward_publish(vehicle, mqtt_settings, topic, value, is_raw=False)

        # Forward current mapped values
        mapped_base = mapped_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)
        for key, value in (runtime.metrics or {}).items():
            topic = f"{mapped_base}/{key}"
            self._forward_publish(vehicle, mqtt_settings, topic, value, is_raw=False)

        # Forward BMW raw cache immediately when available and requested
        raw_cache = self._bmw_raw_cache.get(vehicle_id)
        if raw_cache:
            raw_base, _ = self._runtime_topics(vehicle, mqtt_settings)
            self._forward_flatten_publish(vehicle, mqtt_settings, raw_base, raw_cache)
    def _target_clients_for_vehicle(self, vehicle):
        cfg = self.config_store.load()
        assigned = set(getattr(vehicle, "mqtt_client_ids", []) or [])
        return [c for c in cfg.mqtt_clients if c.enabled and c.id in assigned]

    def _load_forward_status(self) -> dict[str, dict[str, Any]]:
        try:
            if not self.mqtt_client_status_file.exists():
                return {}
            return json.loads(self.mqtt_client_status_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_forward_status(self, status_map: dict[str, dict[str, Any]]) -> None:
        try:
            self.mqtt_client_status_file.write_text(json.dumps(status_map, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _ha_supervisor_headers(self) -> dict[str, str]:
        token = os.getenv("SUPERVISOR_TOKEN", "").strip()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}", "X-Supervisor-Token": token, "Content-Type": "application/json"}

    def _extract_server_name_from_payload(self, payload: Any) -> str:
        candidates: list[Any] = []
        if isinstance(payload, dict):
            candidates.extend([
                payload.get("hostname"),
                payload.get("host"),
                payload.get("server_name"),
                payload.get("name"),
            ])
            for key in ("data", "result"):
                value = payload.get(key)
                if isinstance(value, dict):
                    candidates.extend([
                        value.get("hostname"),
                        value.get("host"),
                        value.get("server_name"),
                        value.get("name"),
                    ])
                    host = value.get("host")
                    if isinstance(host, dict):
                        candidates.extend([host.get("hostname"), host.get("name")])
        for value in candidates:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _resolve_server_name(self) -> str:
        headers = self._ha_supervisor_headers()
        urls = [
            os.getenv("SUPERVISOR_HOST_INFO_URL", "").strip(),
            os.getenv("SUPERVISOR_INFO_URL", "").strip(),
            "http://supervisor/host/info",
            "http://supervisor/info",
        ]
        seen: set[str] = set()
        for url in [u for u in urls if u]:
            if url in seen:
                continue
            seen.add(url)
            try:
                resp = requests.get(url, headers=headers, timeout=5)
                if not resp.ok:
                    continue
                name = self._extract_server_name_from_payload(resp.json())
                if name:
                    return name
            except Exception:
                continue
        for value in (os.getenv("HOSTNAME", "").strip(),):
            if value:
                return value
        try:
            text = Path("/etc/hostname").read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
        return "unknown"

    def _mark_forward_client_status(self, client_id: str, *, ok: bool, error: str = "") -> None:
        status_map = self._load_forward_status()
        entry = dict(status_map.get(client_id, {}) or {})
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entry["checked_at"] = now
        if ok:
            entry["last_ok"] = now
            entry["last_error"] = ""
        else:
            entry["last_error"] = error or "publish_failed"
        status_map[client_id] = entry
        self._save_forward_status(status_map)

    def _forward_topic(self, source_topic: str, target_base: str, local_base: str) -> str:
        source_topic = str(source_topic or '').strip('/')
        target_base = str(target_base or '').strip('/')
        local_base = str(local_base or '').strip('/')
        suffix = source_topic
        if local_base and source_topic.lower().startswith((local_base + '/').lower()):
            suffix = source_topic[len(local_base)+1:]
        return f"{target_base}/{suffix}" if target_base else source_topic

    def _publish_to_forward_client(self, client_cfg, topic: str, payload: Any) -> None:
        if not getattr(client_cfg, 'host', ''):
            raise RuntimeError('MQTT Client ohne Host konfiguriert')
        local = load_runtime_mqtt_settings()
        settings = RuntimeMqttSettings(
            host=client_cfg.host,
            port=client_cfg.port,
            username=client_cfg.username,
            password=client_cfg.password,
            password_set=bool(client_cfg.password),
            base_topic=client_cfg.base_topic or local.base_topic,
            qos=local.qos,
            retain=local.retain,
            tls=local.tls,
        )
        client = LocalMqttClient(settings)
        try:
            client.connect()
            client.publish(topic, payload)
        finally:
            client.disconnect()

    def _forward_flatten_publish(self, vehicle, mqtt_settings, raw_topic_base: str, data: Dict[str, Any]) -> None:
        data_points = (data or {}).get('data', {}) or {}
        if not isinstance(data_points, dict):
            return
        for metric_name, metric_data in data_points.items():
            metric_topic = f"{raw_topic_base}/{metric_name.replace('.', '/')}"
            self._forward_publish(vehicle, mqtt_settings, metric_topic, metric_data, is_raw=True)
            if isinstance(metric_data, dict):
                for key, value in metric_data.items():
                    self._forward_publish(vehicle, mqtt_settings, f"{metric_topic}/{key}", value, is_raw=True)

    def _forward_publish(self, vehicle, mqtt_settings, source_topic: str, payload: Any, *, is_raw: bool) -> None:
        local_base = str(getattr(mqtt_settings, 'base_topic', 'car') or 'car')
        for client_cfg in self._target_clients_for_vehicle(vehicle):
            if is_raw and not client_cfg.send_raw:
                continue
            target_topic = self._forward_topic(source_topic, client_cfg.base_topic, local_base)
            try:
                self._publish_to_forward_client(client_cfg, target_topic, payload)
            except Exception as exc:
                self.log_store.append(vehicle.id, f"MQTT Client {client_cfg.name or client_cfg.id}: Publish fehlgeschlagen ({exc})")

    def _handle_gwm_error(self, vehicle_id: str, message: str) -> None:
        state = "reauth_required" if "reauth erforderlich" in (message or "").lower() else "error"
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if vehicle:
            vehicle.provider_state.auth_state = "error"
            vehicle.provider_state.auth_message = message
            if state == "reauth_required":
                vehicle.provider_state.last_error = "Refresh Token abgelaufen"
            else:
                vehicle.provider_state.last_error = message
            self.config_store.upsert_vehicle(vehicle)
        self._set_runtime_state(vehicle_id, state, message)

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

        if vehicle.manufacturer == "gwm":
            if state in {"starting", "connected"}:
                vehicle.provider_state.auth_state = "authorized"
                vehicle.provider_state.auth_message = detail
                vehicle.provider_state.last_error = ""
                self.config_store.upsert_vehicle(vehicle)
            elif state == "waiting_for_code":
                vehicle.provider_state.auth_state = "error"
                vehicle.provider_state.auth_message = detail
                self.config_store.upsert_vehicle(vehicle)

        settings = load_runtime_mqtt_settings()
        raw_topic, mapped = self._runtime_topics(vehicle, settings)
        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        previous_state = runtime.connection_state or ""
        previous_detail = runtime.connection_detail or ""

        sticky_reauth = previous_state == "reauth_required" and state in {"disconnected", "error"}
        if sticky_reauth:
            runtime.connection_state = "reauth_required"
            if previous_detail:
                runtime.connection_detail = previous_detail
            runtime.auth_state = vehicle.provider_state.auth_state
            runtime.raw_topic = raw_topic
            runtime.mapped_topic = mapped
            self.state_store.upsert(runtime)
            self.log_store.append(vehicle_id, f"Status unverändert (ReAuth hat Vorrang): {state}: {detail}")
            self._publish_meta(vehicle, runtime, settings)
            return

        runtime.connection_state = state
        runtime.connection_detail = detail
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.raw_topic = raw_topic
        runtime.mapped_topic = mapped
        self.state_store.upsert(runtime)
        if previous_state != state or previous_detail != detail:
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
            client.publish(f"{topic}/server_name", self._resolve_server_name())
            client.publish(f"{topic}/label", vehicle.label)
            client.publish(f"{topic}/license_plate", vehicle.license_plate)
            client.publish(f"{topic}/manufacturer", vehicle.manufacturer)
            vin_value = str((vehicle.provider_config or {}).get('vin') or (runtime.provider_meta or {}).get('vin') or '')
            if vin_value:
                client.publish(f"{topic}/vin", vin_value)
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
            self._forward_flatten_publish(vehicle, mqtt_settings, raw_topic_base, data)
            cached = self._bmw_raw_cache.get(vehicle_id, {})
            merged = self._deep_merge_dict(cached, nested)
            self._bmw_raw_cache[vehicle_id] = merged
            mapped_payload = map_bmw_payload(merged)
            for key, value in mapped_payload.items():
                topic = f"{mapped}/{key}"
                client.publish(topic, value)
                self._forward_publish(vehicle, mqtt_settings, topic, value, is_raw=False)
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
        runtime.last_update = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        runtime.raw_topic = target_topic if "target_topic" in locals() else raw_topic_base
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

        raw_topic_base, mapped = self._runtime_topics(vehicle, mqtt_settings)
        root_parts = [
            str(getattr(mqtt_settings, "base_topic", "car") or "car").strip().strip("/") or "car",
            "GWM",
            "".join(ch for ch in vehicle.license_plate.upper().strip() if ch.isalnum()),
        ]
        topic_parts = source_topic.split("/")
        discovered_source_id = ""
        relative_parts: list[str] = []

        root_parts_lower = [part.lower() for part in root_parts]

        if len(topic_parts) >= 5 and [part.lower() for part in topic_parts[:3]] == root_parts_lower:
            discovered_source_id = topic_parts[3]
            relative_parts = topic_parts[4:]
        elif len(topic_parts) >= 3 and topic_parts[0].upper() == "GWM":
            discovered_source_id = topic_parts[1]
            relative_parts = topic_parts[2:]
        else:
            relative_parts = topic_parts

        relative = "/".join(relative_parts)
        relative_parts_lower = [part.lower() for part in relative_parts]
        if "status" not in relative_parts_lower:
            return
        status_idx = relative_parts_lower.index("status")
        metric_parts = relative_parts[status_idx + 1:]
        relative = "/".join(metric_parts)
        if not discovered_source_id and len(topic_parts) >= 4:
            discovered_source_id = topic_parts[3]
        source_root = f"{vehicle_root_topic(mqtt_settings.base_topic, vehicle.manufacturer, vehicle.license_plate)}/{discovered_source_id}" if discovered_source_id else raw_topic_base
        is_meta_source = (discovered_source_id or "").lower() == "_meta"
        is_meta_status = is_meta_source and [part.lower() for part in metric_parts] == []

        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        previous_metrics = dict(runtime.metrics or {})
        metrics = dict(previous_metrics)
        obsolete_present = {key for key in GWM_OBSOLETE_MAPPED_KEYS if key in metrics}
        for key in obsolete_present:
            metrics.pop(key, None)
        item_id = ""
        field_name = metric_parts[-1] if metric_parts else ""
        if "items" in [part.lower() for part in metric_parts]:
            idx = [part.lower() for part in metric_parts].index("items")
            if len(metric_parts) > idx + 1:
                item_id = metric_parts[idx + 1]
            if len(metric_parts) > idx + 2:
                field_name = metric_parts[idx + 2]
        metrics = apply_gwm_metric(metrics, item_id, payload, field_name)

        runtime.connection_state = "connected"
        runtime.connection_detail = "ORA Stream aktiv"
        runtime.auth_state = vehicle.provider_state.auth_state
        if not is_meta_source:
            runtime.raw_topic = source_root
        elif not runtime.raw_topic:
            runtime.raw_topic = raw_topic_base
        runtime.mapped_topic = mapped
        changed_keys = {key for key, value in metrics.items() if previous_metrics.get(key) != value}
        runtime.metrics = metrics
        runtime.provider_meta = {
            "vehicle_id": vehicle.provider_config.get("vehicle_id", vehicle.id),
            "source_topic": source_topic,
            "source_root": source_root,
            "relative_topic": "/".join(metric_parts),
            "direct_source_enabled": True,
        }

        runtime.last_update = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        self.state_store.upsert(runtime)

        client = LocalMqttClient(mqtt_settings)
        try:
            client.connect()
            if not is_meta_source:
                self._forward_publish(vehicle, mqtt_settings, source_topic, payload, is_raw=True)
            for key in sorted(obsolete_present):
                topic = f"{mapped}/{key}"
                client.publish(topic, "", retain=True)
                self._forward_publish(vehicle, mqtt_settings, topic, "", is_raw=False)
            for key in sorted(changed_keys):
                topic = f"{mapped}/{key}"
                client.publish(topic, metrics.get(key))
                self._forward_publish(vehicle, mqtt_settings, topic, metrics.get(key), is_raw=False)
        finally:
            client.disconnect()

        if not is_meta_status:
            self.log_store.append(vehicle_id, f"ORA Datenpunkt empfangen: {source_topic} -> mapped aus {field_name or relative or 'status'} = {payload}")
        self._publish_meta(vehicle, runtime, mqtt_settings)


    def _handle_acconia_payload(self, vehicle_id: str, source_topic: str, payload: str, mqtt_settings) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return
        source_base = str((vehicle.provider_config or {}).get("source_topic_base") or "").strip().strip("/")
        relative = str(source_topic or "").strip("/")
        if source_base and relative.lower().startswith((source_base + "/").lower()):
            relative = relative[len(source_base) + 1:]
        raw_topic_base, mapped = self._runtime_topics(vehicle, mqtt_settings)
        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        previous_metrics = dict(runtime.metrics or {})
        metrics = apply_acconia_metric(
            dict(previous_metrics),
            relative,
            payload,
            int((vehicle.provider_config or {}).get("battery_count") or 0),
            (vehicle.provider_config or {}).get("capacity_kwh"),
        )
        changed_keys = {key for key, value in metrics.items() if previous_metrics.get(key) != value}
        runtime.connection_state = "connected"
        runtime.connection_detail = "Acconia/Silence MQTT Quelle aktiv"
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.raw_topic = raw_topic_base
        runtime.mapped_topic = mapped
        runtime.last_update = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        runtime.metrics = metrics
        runtime.provider_meta = {
            "vehicle_id": vehicle.provider_config.get("vehicle_id", vehicle.id),
            "source_topic_base": source_base,
            "source_topic": source_topic,
            "relative_topic": relative,
        }
        self.state_store.upsert(runtime)

        client = LocalMqttClient(mqtt_settings)
        try:
            client.connect()
            raw_topic = f"{raw_topic_base}/{relative}" if relative else raw_topic_base
            client.publish(raw_topic, payload)
            self._forward_publish(vehicle, mqtt_settings, raw_topic, payload, is_raw=True)
            for key in sorted(changed_keys):
                topic = f"{mapped}/{key}"
                client.publish(topic, metrics.get(key))
                self._forward_publish(vehicle, mqtt_settings, topic, metrics.get(key), is_raw=False)
        finally:
            client.disconnect()

        self.log_store.append(vehicle_id, f"Acconia Datenpunkt empfangen: {source_topic} -> {relative} = {payload}")
        self._publish_meta(vehicle, runtime, mqtt_settings)


    def _handle_acconia_snapshot(self, vehicle_id: str, data: dict[str, Any], mqtt_settings) -> None:
        vehicle = self.config_store.get_vehicle(vehicle_id)
        if not vehicle:
            return
        raw_topic_base, mapped = self._runtime_topics(vehicle, mqtt_settings)
        runtime = self.state_store.get_all().get(vehicle_id) or VehicleRuntimeState(vehicle_id=vehicle_id)
        previous_metrics = dict(runtime.metrics or {})
        metrics = apply_acconia_metric(dict(previous_metrics), "", data or {}, int((vehicle.provider_config or {}).get("battery_count") or 0), (vehicle.provider_config or {}).get("capacity_kwh"))
        changed_keys = {key for key, value in metrics.items() if previous_metrics.get(key) != value}
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        runtime.connection_state = "connected"
        runtime.connection_detail = "Acconia/Silence API Polling aktiv"
        runtime.auth_state = vehicle.provider_state.auth_state
        runtime.raw_topic = raw_topic_base
        runtime.mapped_topic = mapped
        runtime.last_update = now
        runtime.metrics = metrics
        runtime.provider_meta = {"vehicle_id": vehicle.provider_config.get("vehicle_id", vehicle.id), "frameNo": (data or {}).get("frameNo", ""), "imei": (data or {}).get("imei", ""), "source": "Silence API"}
        self.state_store.upsert(runtime)
        client = LocalMqttClient(mqtt_settings)
        try:
            client.connect()
            client.publish(f"{raw_topic_base}/snapshot", data or {})
            self._forward_publish(vehicle, mqtt_settings, f"{raw_topic_base}/snapshot", data or {}, is_raw=True)
            for key in sorted(changed_keys):
                topic = f"{mapped}/{key}"
                client.publish(topic, metrics.get(key))
                self._forward_publish(vehicle, mqtt_settings, topic, metrics.get(key), is_raw=False)
        finally:
            client.disconnect()
        self.log_store.append(vehicle_id, f"Acconia/Silence Snapshot verarbeitet: soc={metrics.get('soc')} charging={metrics.get('charging')} gps={metrics.get('latitude')},{metrics.get('longitude')}")
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
        normalized_plate = "".join(ch for ch in vehicle.license_plate.upper().strip() if ch.isalnum())
        topic = f"{mqtt_settings.base_topic}/gwm/{normalized_plate}/+/status/#"
        legacy_topic = f"{mqtt_settings.base_topic}/GWM/{normalized_plate}/+/status/#"
        client = paho_mqtt.Client(client_id=f"car2mqtt-gwmtest-{vehicle_id[:8]}")
        if mqtt_settings.username:
            client.username_pw_set(mqtt_settings.username, mqtt_settings.password)

        def on_connect(c, _u, _f, rc, _p=None):
            if rc == 0:
                c.subscribe(topic, qos=mqtt_settings.qos)
                c.subscribe(legacy_topic, qos=mqtt_settings.qos)

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
        self.log_store.append(vehicle_id, f"ORA Test-Mapping gestartet: {topic} -> Mapping aus car/... Topics")
        time.sleep(wait_seconds)
        client.loop_stop()
        client.disconnect()
        self.log_store.append(vehicle_id, f"ORA Test-Mapping beendet: {seen['count']} MQTT-Nachrichten verarbeitet")
        return seen

    def delete_vehicle(self, vehicle_id: str) -> None:
        self.stop_vehicle(vehicle_id)
        self.state_store.delete(vehicle_id)
        self.log_store.append(vehicle_id, "Fahrzeug gelöscht")
        self.log_store.delete(vehicle_id)
