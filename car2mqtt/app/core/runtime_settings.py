from __future__ import annotations

import os
from app.core.models import RuntimeMqttSettings


def load_runtime_mqtt_settings() -> RuntimeMqttSettings:
    password = os.getenv("MQTT_PASSWORD", "")
    return RuntimeMqttSettings(
        host=os.getenv("MQTT_HOST", ""),
        port=int(os.getenv("MQTT_PORT", "1883")),
        username=os.getenv("MQTT_USERNAME", ""),
        password_set=bool(password),
        base_topic=os.getenv("MQTT_BASE_TOPIC", "car"),
        qos=int(os.getenv("MQTT_QOS", "1")),
        retain=os.getenv("MQTT_RETAIN", "true").lower() == "true",
        tls=os.getenv("MQTT_TLS", "false").lower() == "true",
    )
