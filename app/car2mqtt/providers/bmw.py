from __future__ import annotations

from typing import Any, Dict

from ..models import Manufacturer, ProviderField, ProviderSchema, utcnow
from .base import ProviderAdapter


class BMWProvider(ProviderAdapter):
    manufacturer = Manufacturer.BMW.value

    @classmethod
    def schema(cls) -> ProviderSchema:
        return ProviderSchema(
            manufacturer=Manufacturer.BMW,
            name="BMW CarData",
            auth_mode="external_link",
            description="BMW CarData provider with external login link / device flow.",
            fields=[
                ProviderField(key="client_id", label="Client ID", kind="text", placeholder="BMW Client ID"),
                ProviderField(key="mqtt_username", label="BMW MQTT Username", kind="text", placeholder="BMW MQTT Username"),
                ProviderField(key="vin", label="VIN", kind="text", placeholder="WBA..."),
                ProviderField(key="region", label="Region", kind="text", required=False, placeholder="EU"),
            ],
        )

    async def validate_config(self) -> None:
        required = ["client_id", "mqtt_username", "vin"]
        missing = [key for key in required if not self.vehicle.provider_config.get(key)]
        if missing:
            raise ValueError(f"Missing BMW config fields: {', '.join(missing)}")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> Dict[str, Any]:
        return {
            "provider": self.manufacturer,
            "auth_mode": "external_link",
            "message": "BMW provider scaffold ready; live stream integration comes in a later version.",
            "checked_at": utcnow().isoformat(),
        }
