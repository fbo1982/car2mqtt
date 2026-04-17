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
            notes=(
                "GWM/ORA ist als modularer Provider vorbereitet. Die MQTT-Zugangsdaten sind global "
                "in der Add-on-Konfiguration hinterlegt."
            ),
            setup_steps=[
                "Zugangsdaten für GWM/ORA erfassen.",
                "Fahrzeug-ID oder eindeutige Kennung eintragen.",
                "Verbindung testen und anschließend speichern.",
            ],
            fields=[
                {"name": "username", "label": "Benutzername", "type": "text", "required": True},
                {"name": "password", "label": "Passwort", "type": "password", "required": True},
                {"name": "vehicle_id", "label": "Fahrzeug-ID", "type": "text", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        username = str(provider_config.get("username", "")).strip()
        password = str(provider_config.get("password", "")).strip()
        if not username or not password:
            raise ValueError("GWM/ORA benötigt Benutzername und Passwort.")
        return {
            "username": username,
            "password": password,
            "vehicle_id": str(provider_config.get("vehicle_id", "")).strip(),
        }
