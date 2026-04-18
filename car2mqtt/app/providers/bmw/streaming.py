from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt
import requests

logger = logging.getLogger(__name__)


class BMWCarDataClient:
    def __init__(self, client_id: str, vin: str, mqtt_username: str, token_file: str, mqtt_host: str = "customer.streaming-cardata.bmwgroup.com", mqtt_port: int = 9000, subscribe_wildcard: bool = True):
        self.client_id = client_id
        self.vin = vin
        self.mqtt_username = mqtt_username
        self.subscribe_topic = ""
        self.wildcard_topic = ""
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.token_file = token_file
        self.subscribe_wildcard = subscribe_wildcard
        self.token_url = "https://customer.bmwgroup.com/gcdm/oauth/token"
        self.tokens: Dict[str, Any] = {}
        self.mqtt_client: Optional[mqtt.Client] = None
        self.message_callback: Optional[Callable[[str, Any], None]] = None
        self.connect_callback: Optional[Callable[[], None]] = None
        self.disconnect_callback: Optional[Callable[[int], None]] = None
        self._connected = threading.Event()

    def set_message_callback(self, callback): self.message_callback = callback
    def set_connect_callback(self, callback): self.connect_callback = callback
    def set_disconnect_callback(self, callback): self.disconnect_callback = callback

    def _load_tokens(self) -> bool:
        try:
            self.tokens = json.loads(Path(self.token_file).read_text(encoding="utf-8"))
            return True
        except Exception:
            return False

    def _save_tokens(self) -> None:
        Path(self.token_file).write_text(json.dumps(self.tokens, indent=2), encoding="utf-8")

    def _expiry(self, token_key: str) -> Optional[datetime]:
        token = self.tokens.get(token_key, {})
        expires_at = token.get("expires_at")
        if not expires_at:
            return None
        return datetime.fromisoformat(expires_at.replace('Z', '+00:00')).replace(tzinfo=None)

    def _is_token_expiring(self, token_key: str, minutes: int = 5) -> bool:
        expiry = self._expiry(token_key)
        if not expiry:
            return True
        return datetime.utcnow() + timedelta(minutes=minutes) >= expiry

    def refresh_tokens(self) -> bool:
        if not self._load_tokens():
            return False
        refresh_token = self.tokens.get("refresh_token", {}).get("token")
        if not refresh_token:
            return False
        response = requests.post(self.token_url, data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id}, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
        response.raise_for_status()
        data = response.json()
        now = datetime.utcnow()
        self.tokens["access_token"] = {"token": data.get("access_token", ""), "expires_at": (now + timedelta(seconds=int(data.get("expires_in", 3600)))).replace(microsecond=0).isoformat()}
        self.tokens["id_token"] = {"token": data.get("id_token", ""), "expires_at": (now + timedelta(seconds=int(data.get("expires_in", 3600)))).replace(microsecond=0).isoformat()}
        if data.get("refresh_token"):
            self.tokens["refresh_token"] = {"token": data.get("refresh_token"), "expires_at": (now + timedelta(days=14)).replace(microsecond=0).isoformat()}
        self.tokens["gcid"] = data.get("gcid", self.tokens.get("gcid", ""))
        self._save_tokens()
        return True

    def ensure_tokens(self) -> bool:
        if not self._load_tokens():
            return False
        # GCID from token payload is the source of truth for BMW streaming topics.
        token_gcid = str(self.tokens.get("gcid", "")).strip()
        if token_gcid:
            self.mqtt_username = token_gcid
        if self._is_token_expiring("id_token"):
            ok = self.refresh_tokens()
            token_gcid = str(self.tokens.get("gcid", "")).strip()
            if token_gcid:
                self.mqtt_username = token_gcid
            return ok
        return True

    @staticmethod
    def _normalize_reason_code(reason_code) -> int:
        if isinstance(reason_code, int):
            return reason_code
        value = getattr(reason_code, "value", None)
        if isinstance(value, int):
            return value
        try:
            return int(value if value is not None else reason_code)
        except (TypeError, ValueError):
            logger.warning("Unbekannter MQTT ReasonCode-Typ: %r", reason_code)
            return -1

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        rc = self._normalize_reason_code(reason_code)
        if rc == 0:
            self.subscribe_topic = f"{self.mqtt_username}/{self.vin}"
            self.wildcard_topic = f"{self.mqtt_username}/+"
            client.subscribe(self.subscribe_topic, qos=1)
            if self.subscribe_wildcard:
                client.subscribe(self.wildcard_topic, qos=1)
            self._connected.set()
            if self.connect_callback:
                self.connect_callback()
        else:
            logger.error("BMW MQTT Verbindung fehlgeschlagen: %s (%r)", rc, reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            if self.message_callback:
                self.message_callback(msg.topic, data)
        except Exception as exc:
            logger.exception("BMW Nachricht konnte nicht verarbeitet werden: %s", exc)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        rc = self._normalize_reason_code(reason_code)
        self._connected.clear()
        if self.disconnect_callback:
            self.disconnect_callback(rc)

    def connect_mqtt(self) -> bool:
        if not self.ensure_tokens():
            return False
        token = self.tokens.get("id_token", {}).get("token", "")
        if not token or not self.mqtt_username:
            return False
        self.disconnect_mqtt()
        self.mqtt_client = mqtt.Client(protocol=mqtt.MQTTv5, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.tls_set()
        self.mqtt_client.username_pw_set(self.mqtt_username, token)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect
        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 30)
        self.mqtt_client.loop_start()
        return self._connected.wait(15)

    def is_connected(self) -> bool:
        return self._connected.is_set()

    def disconnect_mqtt(self):
        if self.mqtt_client:
            try:
                self.mqtt_client.disconnect()
            except Exception:
                pass
            finally:
                self.mqtt_client.loop_stop()
                self.mqtt_client = None
                self._connected.clear()


class BMWStreamWorker:
    def __init__(self, vehicle, mqtt_settings, state_store, local_mqtt_client_factory, on_payload: Callable[[str, Dict[str, Any]], None], on_connect=None, on_disconnect=None, on_error=None, on_detail=None, log_callback=None):
        self.vehicle = vehicle
        self.mqtt_settings = mqtt_settings
        self.state_store = state_store
        self.local_mqtt_client_factory = local_mqtt_client_factory
        self.on_payload = on_payload
        self.on_connect_cb = on_connect
        self.on_disconnect_cb = on_disconnect
        self.on_error_cb = on_error
        self.on_detail_cb = on_detail
        self.log_callback = log_callback
        self.thread = None
        self.stop_event = threading.Event()
        self.client: Optional[BMWCarDataClient] = None
        self.last_message_at = 0.0
        self.last_reconnect_at = 0.0

    def _log(self, message: str) -> None:
        if self.log_callback:
            self.log_callback(message)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.client:
            self.client.disconnect_mqtt()
        self._log("BMW Worker gestoppt")

    def _detail(self, message: str):
        self._log(message)
        if self.on_detail_cb:
            self.on_detail_cb(message)

    def _run(self):
        token_file = Path(os.getenv("APP_DATA_DIR", "/config/car2mqtt")) / "providers" / self.vehicle.id / "bmw_tokens.json"
        if not token_file.exists():
            if self.on_error_cb:
                self.on_error_cb("BMW Token-Datei fehlt")
            self._log("BMW Token-Datei fehlt")
            return
        try:
            self.client = BMWCarDataClient(
                client_id=self.vehicle.provider_config["client_id"],
                vin=self.vehicle.provider_config["vin"],
                mqtt_username=self.vehicle.provider_state.mqtt_username or self.vehicle.provider_config.get("mqtt_username", ""),
                token_file=str(token_file),
            )
            self.client.set_message_callback(self._handle_message)
            self.client.set_connect_callback(self._handle_connect)
            self.client.set_disconnect_callback(self._handle_disconnect)
            self._detail("BMW Verbindung wird aufgebaut")
            self._log(f"BMW VIN: {self.vehicle.provider_config.get('vin','')}")
            if not self.client.connect_mqtt():
                if self.on_error_cb:
                    self.on_error_cb("BMW MQTT Verbindung konnte nicht aufgebaut werden")
                self._log("BMW MQTT Verbindung konnte nicht aufgebaut werden")
                return
            auto_reconnect = bool(self.vehicle.provider_config.get("auto_reconnect", True))
            manual_reconnect_minutes = max(15, min(60, int(self.vehicle.provider_config.get("manual_reconnect_minutes", 15) or 15)))
            self.last_reconnect_at = time.time()
            while not self.stop_event.wait(30):
                if self.client and auto_reconnect and self.client._is_token_expiring("id_token", minutes=5):
                    self._detail("Token läuft bald ab, BMW Verbindung wird automatisch erneuert")
                    if self.client.refresh_tokens():
                        self._detail("Token erneuert, BMW Verbindung wird neu aufgebaut")
                        self.client.connect_mqtt()
                        self.last_reconnect_at = time.time()
                    else:
                        if self.on_error_cb:
                            self.on_error_cb("Token-Refresh fehlgeschlagen")
                        self._log("Token-Refresh fehlgeschlagen")
                if self.client and (not auto_reconnect):
                    if time.time() - self.last_reconnect_at >= manual_reconnect_minutes * 60:
                        self._detail(f"Manueller Reconnect-Zyklus ({manual_reconnect_minutes} min) wird ausgeführt")
                        self.client.connect_mqtt()
                        self.last_reconnect_at = time.time()
                if self.client and not self.client.is_connected():
                    self._detail("BMW Verbindung wird erneut aufgebaut")
                    self.client.connect_mqtt()
                    self.last_reconnect_at = time.time()
                if self.last_message_at and time.time() - self.last_message_at > 10800:
                    self._detail("Watchdog: Keine BMW Live-Daten, Reconnect")
                    if self.client:
                        self.client.connect_mqtt()
                        self.last_reconnect_at = time.time()
        except Exception as exc:
            logger.exception("BMW Worker Fehler: %s", exc)
            self._log(f"BMW Worker Fehler: {exc}")
            if self.on_error_cb:
                self.on_error_cb(str(exc))

    def _handle_connect(self):
        self._log("BMW MQTT verbunden")
        if self.client:
            self._log(f"BMW MQTT Username/GCID: {self.client.mqtt_username}")
            if self.client.subscribe_topic:
                self._log(f"BMW Subscribe Topic: {self.client.subscribe_topic}")
            if self.client.wildcard_topic:
                self._log(f"BMW Wildcard Topic: {self.client.wildcard_topic}")
        if self.on_connect_cb:
            self.on_connect_cb()

    def _handle_disconnect(self, rc: int):
        if self.stop_event.is_set() and rc == 0:
            return
        self._log(f"BMW MQTT getrennt (rc={rc})")
        if self.on_disconnect_cb:
            self.on_disconnect_cb(rc)

    def _handle_message(self, topic: str, data: Dict[str, Any]):
        self.last_message_at = time.time()
        self._log(f"BMW Live-Nachricht auf Topic {topic}")
        self.on_payload(topic, data)
