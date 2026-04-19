from __future__ import annotations

import json
import ssl
import threading
import time
import uuid
from typing import Callable

import paho.mqtt.client as mqtt

from app.core.models import VehicleConfig
from app.core.runtime_settings import RuntimeMqttSettings


class GwmMonitorWorker:
    def __init__(
        self,
        vehicle: VehicleConfig,
        mqtt_settings: RuntimeMqttSettings,
        on_connect: Callable[[], None],
        on_disconnect: Callable[[str], None],
        on_error: Callable[[str], None],
        on_detail: Callable[[str], None],
        on_message: Callable[[str, str], None],
        log_callback: Callable[[str], None],
    ) -> None:
        self.vehicle = vehicle
        self.settings = mqtt_settings
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        self.on_detail = on_detail
        self.on_message = on_message
        self.log = log_callback
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: mqtt.Client | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"gwm-{self.vehicle.id}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _build_source_topics(self) -> tuple[str, str]:
        configured_base = str(self.vehicle.provider_config.get("source_topic_base", "")).strip()
        vehicle_id = str(self.vehicle.provider_config.get("vehicle_id", "")).strip() or self.vehicle.id

        # ORA/GWM uses runtime-generated broker ids below GWM/<opaque-id>/status/...
        # Subscribe broadly and let the handler normalize/map the real paths.
        if not configured_base or configured_base.startswith("GWM/"):
            base = "GWM/+"
            topic = "GWM/+/status/#"
        else:
            base = configured_base
            topic = f"{configured_base}/status/#"

        return topic, base

    def _run(self) -> None:
        backoff = 5
        while not self._stop.is_set():
            try:
                source_topic, source_base = self._build_source_topics()
                self.on_detail("ORA MQTT Monitoring wird aufgebaut")
                self.log(f"ORA Source Base Topic: {source_base}")
                self.log(f"ORA Subscribe Topic: {source_topic}")

                client = mqtt.Client(client_id=f"car2mqtt-gwm-{uuid.uuid4().hex[:8]}")
                self._client = client
                if self.settings.username:
                    client.username_pw_set(self.settings.username, self.settings.password)
                if self.settings.tls:
                    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

                def _on_connect(_client, _userdata, _flags, rc, _properties=None):
                    if rc == 0:
                        self.log("ORA MQTT verbunden")
                        _client.subscribe(source_topic, qos=self.settings.qos)
                        self.log(f"ORA MQTT Subscribe gesendet: {source_topic}")
                        self.on_connect()
                    else:
                        msg = f"ORA MQTT Verbindung fehlgeschlagen (rc={rc})"
                        self.log(msg)
                        self.on_error(msg)

                def _on_disconnect(_client, _userdata, rc, _properties=None):
                    if self._stop.is_set():
                        return
                    self.log(f"ORA MQTT getrennt (rc={rc})")
                    self.on_disconnect(str(rc))

                def _on_message(_client, _userdata, msg):
                    try:
                        payload = msg.payload.decode("utf-8", errors="ignore")
                    except Exception:
                        payload = ""
                    self.on_message(msg.topic, payload)

                client.on_connect = _on_connect
                client.on_disconnect = _on_disconnect
                client.on_message = _on_message
                client.connect(self.settings.host, self.settings.port, 30)
                client.loop_start()

                while not self._stop.is_set():
                    time.sleep(1)

                break

            except Exception as exc:
                self.log(f"ORA Worker Fehler: {exc}")
                self.on_error(str(exc))
                if self._stop.wait(backoff):
                    break
