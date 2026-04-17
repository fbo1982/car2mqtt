from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider


class GwmProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="gwm",
            name="GWM / ORA",
            auth_mode="credentials",
            notes="ORA/GWM ist als modularer Provider vorbereitet. Der genaue Auth-Flow kann später erweitert werden.",
            fields=[
                {"name": "username", "label": "Benutzername", "type": "text", "required": False},
                {"name": "password", "label": "Passwort", "type": "password", "required": False},
                {"name": "vehicle_id", "label": "Vehicle ID", "type": "text", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "username": provider_config.get("username", ""),
            "password": provider_config.get("password", ""),
            "vehicle_id": provider_config.get("vehicle_id", ""),
        }
