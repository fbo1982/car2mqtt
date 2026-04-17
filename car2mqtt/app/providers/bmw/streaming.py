from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt
import requests

logger = logging.getLogger(__name__)


class BMWCarDataClient:
    def __init__(
        self,
        client_id: str,
        vin: str,
        token_file: str,
        mqtt_host: str = "customer.streaming-cardata.bmwgroup.com",
        mqtt_port: int = 9000,
        subscribe_wildcard: bool = True,
    ):
        self.client_id = client_id
        self.vin = vin
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.token_file = token_file
        self.subscribe_wildcard = subscribe_wildcard
        self.token_url = "https://customer.bmwgroup.com/gcdm/oauth/token"
        self.tokens: Dict[str, Any] = {}
        self.mqtt_client = None
        self.message_callback: Optional[Callable[[str, Any], None]] = None
        self.connect_callback: Optional[Callable[[], None]] = None
        self.disconnect_callback: Optional[Callable[[int], None]] = None

    @property
    def mqtt_username(self) -> str:
        gcid = self.tokens.get("gcid", "")
        if gcid:
            return gcid
        raise ValueError("GCID nicht verfügbar")

    def set_message_callback(self, callback: Callable[[str, Any], None]):
        self.message_callback = callback

    def set_connect_callback(self, callback: Callable[[], None]):
        self.connect_callback = callback

    def set_disconnect_callback(self, callback: Callable[[int], None]):
        self.disconnect_callback = callback

    def _load_tokens(self) -> bool:
        path = Path(self.token_file)
        if not path.exists():
            return False
        self.tokens = json.loads(path.read_text(encoding="utf-8"))
        return True

    def _is_token_expired(self, token_key: str) -> bool:
        token_info = self.tokens.get(token_key, {})
        expires_at = token_info.get("expires_at")
        if not expires_at:
            return True
        try:
            expires_dt = datetime.fromisoformat(expires_at)
        except ValueError:
            return True
        return datetime.utcnow() >= expires_dt

    def refresh_tokens(self) -> bool:
        if not self._load_tokens() or "refresh_token" not in self.tokens:
            return False
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self.tokens["refresh_token"]["token"],
            "client_id": self.client_id,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(self.token_url, data=payload, headers=headers, timeout=30)
        response.raise_for_status()
        new_tokens = response.json()
        now = datetime.utcnow()
        self.tokens["refresh_token"] = {
            "token": new_tokens.get("refresh_token", self.tokens["refresh_token"]["token"]),
            "expires_at": self.tokens["refresh_token"].get("expires_at", (now + timedelta(days=14)).isoformat()),
        }
        self.tokens["id_token"] = {
            "token": new_tokens["id_token"],
            "expires_at": (now + timedelta(seconds=int(new_tokens.get("expires_in", 3600)))).replace(microsecond=0).isoformat(),
        }
        self.tokens["access_token"] = {
            "token": new_tokens.get("access_token", ""),
            "expires_at": (now + timedelta(seconds=int(new_tokens.get("expires_in", 3600)))).replace(microsecond=0).isoformat(),
        }
        self.tokens["gcid"] = new_tokens.get("gcid", self.tokens.get("gcid", ""))
        Path(self.token_file).write_text(json.dumps(self.tokens, indent=2), encoding="utf-8")
        return True

    def ensure_tokens(self) -> bool:
        if not self._load_tokens():
            return False
        if self._is_token_expired("id_token"):
            return self.refresh_tokens()
        return True

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            topic = f"{self.mqtt_username}/{self.vin}"
            client.subscribe(topic, qos=1)
            if self.subscribe_wildcard:
                client.subscribe(f"{self.mqtt_username}/+", qos=1)
            if self.connect_callback:
                self.connect_callback()
        else:
            logger.error("BMW MQTT Verbindung fehlgeschlagen: %s", rc)

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            if self.message_callback:
                self.message_callback(msg.topic, data)
        except Exception as exc:
            logger.exception("BMW Nachricht konnte nicht verarbeitet werden: %s", exc)

    def _on_disconnect(self, client, userdata, rc, properties=None):
        if self.disconnect_callback:
            self.disconnect_callback(rc)

    def connect_mqtt(self) -> bool:
        if not self.ensure_tokens():
            return False
        token = self.tokens["id_token"]["token"]
        self.mqtt_client = mqtt.Client(protocol=mqtt.MQTTv5, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.mqtt_client.tls_set()
        self.mqtt_client.username_pw_set(self.mqtt_username, token)
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect
        self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 30)
        self.mqtt_client.loop_start()
        return True

    def disconnect_mqtt(self):
        if self.mqtt_client:
            try:
                self.mqtt_client.disconnect()
            finally:
                self.mqtt_client.loop_stop()


class BMWStreamWorker:
    def __init__(
        self,
        vehicle,
        mqtt_settings,
        state_store,
        local_mqtt_client_factory,
        on_payload: Callable[[str, Dict[str, Any]], None],
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[int], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.vehicle = vehicle
        self.mqtt_settings = mqtt_settings
        self.state_store = state_store
        self.local_mqtt_client_factory = local_mqtt_client_factory
        self.on_payload = on_payload
        self.on_connect_cb = on_connect
        self.on_disconnect_cb = on_disconnect
        self.on_error_cb = on_error
        self.thread = None
        self.stop_event = threading.Event()
        self.client: Optional[BMWCarDataClient] = None

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

    def _run(self):
        token_file = Path(os.getenv("APP_DATA_DIR", "/config/car2mqtt")) / "providers" / self.vehicle.id / "bmw_tokens.json"
        if not token_file.exists():
            if self.on_error_cb:
                self.on_error_cb("BMW Token-Datei fehlt")
            return
        try:
            self.client = BMWCarDataClient(
                client_id=self.vehicle.provider_config["client_id"],
                vin=self.vehicle.provider_config["vin"],
                token_file=str(token_file),
            )
            self.client.set_message_callback(self._handle_message)
            self.client.set_connect_callback(self._handle_connect)
            self.client.set_disconnect_callback(self._handle_disconnect)
            if not self.client.connect_mqtt() and self.on_error_cb:
                self.on_error_cb("BMW MQTT Verbindung konnte nicht aufgebaut werden")
                return
            while not self.stop_event.wait(5):
                pass
        except Exception as exc:
            logger.exception("BMW Worker Fehler: %s", exc)
            if self.on_error_cb:
                self.on_error_cb(str(exc))

    def _handle_connect(self):
        if self.on_connect_cb:
            self.on_connect_cb()

    def _handle_disconnect(self, rc: int):
        if self.stop_event.is_set() and rc == 0:
            return
        if self.on_disconnect_cb:
            self.on_disconnect_cb(rc)

    def _handle_message(self, topic: str, data: Dict[str, Any]):
        self.on_payload(topic, data)
