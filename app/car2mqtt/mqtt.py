from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import MQTTSettings, VehicleConfig


@dataclass(slots=True)
class TopicLayout:
    raw_prefix: str
    mapped_prefix: str
    meta_prefix: str


class TopicBuilder:
    def __init__(self, mqtt: MQTTSettings) -> None:
        self.mqtt = mqtt

    def for_vehicle(self, vehicle: VehicleConfig) -> TopicLayout:
        base = self.mqtt.base_topic.strip("/")
        manufacturer = vehicle.manufacturer.value
        plate = vehicle.license_plate.strip().replace(" ", "_")
        prefix = f"{base}/{manufacturer}/{plate}"
        return TopicLayout(
            raw_prefix=prefix,
            mapped_prefix=f"{prefix}/mapped",
            meta_prefix=f"{prefix}/_meta",
        )

    def raw_topic(self, vehicle: VehicleConfig, suffix: str) -> str:
        return f"{self.for_vehicle(vehicle).raw_prefix}/{suffix.strip('/')}"

    def mapped_topic(self, vehicle: VehicleConfig, key: str) -> str:
        return f"{self.for_vehicle(vehicle).mapped_prefix}/{key.strip('/')}"

    def meta_topic(self, vehicle: VehicleConfig, key: str) -> str:
        return f"{self.for_vehicle(vehicle).meta_prefix}/{key.strip('/')}"


class MQTTClientStub:
    """Placeholder for the real MQTT client in later versions."""

    def __init__(self, settings: MQTTSettings) -> None:
        self.settings = settings
        self.connected = False

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def publish(self, topic: str, payload: Any, retain: bool | None = None) -> None:
        _ = (topic, payload, retain)
        # Intentionally left as a stub in v0.1.0.
