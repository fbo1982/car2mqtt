from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider


class GwmProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="gwm",
            name="GWM / ORA",
            category="API",
            auth_mode="credentials",
            badge="ORA",
            notes="Vorbereitet für spätere ora2mqtt-Integration.",
            setup_steps=[
                "Fahrzeugbasisdaten erfassen.",
                "Benutzername/Passwort später im Provider ergänzen.",
            ],
            fields=[
                {"name": "username", "label": "Benutzername", "type": "text", "required": False},
                {"name": "password", "label": "Passwort", "type": "password", "required": False},
                {"name": "vehicle_id", "label": "Vehicle ID", "type": "text", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "username": str(provider_config.get("username", "")).strip(),
            "password": str(provider_config.get("password", "")),
            "vehicle_id": str(provider_config.get("vehicle_id", "")).strip(),
        }
