from __future__ import annotations

import json
import ssl
import uuid
from typing import Any
import paho.mqtt.client as mqtt
from app.core.models import RuntimeMqttSettings


class LocalMqttClient:
    def __init__(self, settings: RuntimeMqttSettings):
        self.settings = settings
        self.client = mqtt.Client(client_id=f"car2mqtt-{uuid.uuid4().hex[:8]}")
        if settings.username:
            self.client.username_pw_set(settings.username, settings.password)
        if settings.tls:
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self.connected = False
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(self, _client, _userdata, _flags, rc, _properties=None):
        self.connected = rc == 0

    def _on_disconnect(self, _client, _userdata, rc, _properties=None):
        self.connected = False

    def connect(self) -> None:
        self.client.connect(self.settings.host, self.settings.port, 30)
        self.client.loop_start()

    def disconnect(self) -> None:
        try:
            self.client.loop_stop()
        finally:
            self.client.disconnect()

    def publish(self, topic: str, payload: Any, retain: bool | None = None, qos: int | None = None) -> None:
        data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        result = self.client.publish(
            topic,
            data,
            retain=self.settings.retain if retain is None else retain,
            qos=self.settings.qos if qos is None else qos,
        )
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish fehlgeschlagen: {result.rc}")


def test_connection(settings: RuntimeMqttSettings) -> dict:
    client = LocalMqttClient(settings)
    client.connect()
    topic = f"{settings.base_topic}/_meta/healthcheck"
    client.publish(topic, {"status": "ok", "source": "car2mqtt"}, retain=False)
    client.disconnect()
    return {"status": "ok", "topic": topic}
