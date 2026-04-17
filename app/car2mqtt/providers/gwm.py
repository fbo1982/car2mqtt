from __future__ import annotations

from typing import Any, Dict

from ..models import Manufacturer, ProviderField, ProviderSchema, utcnow
from .base import ProviderAdapter


class GWMProvider(ProviderAdapter):
    manufacturer = Manufacturer.GWM.value

    @classmethod
    def schema(cls) -> ProviderSchema:
        return ProviderSchema(
            manufacturer=Manufacturer.GWM,
            name="GWM / ORA",
            auth_mode="credentials",
            description="GWM/ORA provider scaffold based on ora2mqtt style credentials/config.",
            fields=[
                ProviderField(key="username", label="Benutzername", kind="text", placeholder="account@example.com"),
                ProviderField(key="password", label="Passwort", kind="password", placeholder="********", secret=True),
                ProviderField(key="vehicle_id", label="Vehicle ID", kind="text", placeholder="optional in v0.1.0", required=False),
                ProviderField(key="poll_interval_seconds", label="Polling-Intervall", kind="number", placeholder="60", required=False),
            ],
        )

    async def validate_config(self) -> None:
        if not self.vehicle.provider_config.get("username"):
            raise ValueError("Missing GWM username")
        if not self.vehicle.provider_config.get("password"):
            raise ValueError("Missing GWM password")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> Dict[str, Any]:
        return {
            "provider": self.manufacturer,
            "auth_mode": "credentials",
            "message": "GWM provider scaffold ready; upstream integration comes in a later version.",
            "checked_at": utcnow().isoformat(),
        }
