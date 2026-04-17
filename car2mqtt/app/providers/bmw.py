from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider


class BmwProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="bmw",
            name="BMW CarData (EU Data Act)",
            auth_mode="external_link",
            notes=(
                "BMW benötigt einen externen Login-Link. Die MQTT-Zugangsdaten kommen "
                "zentral aus der Add-on-Konfiguration und werden nicht pro Fahrzeug erfasst."
            ),
            setup_steps=[
                "Im BMW/MINI CarData Portal die gewünschten Datenpunkte für Streaming freigeben.",
                "Client-ID im Fahrzeugdialog hinterlegen.",
                "Danach den BMW-Login-/Token-Flow über den vorbereiteten Assistenten starten.",
            ],
            fields=[
                {"name": "client_id", "label": "Client ID", "type": "text", "required": True},
                {"name": "vin", "label": "VIN (optional)", "type": "text", "required": False},
                {"name": "region", "label": "Region", "type": "text", "required": True, "default": "EU"},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(provider_config.get("client_id", "")).strip()
        if not client_id:
            raise ValueError("BMW benötigt eine Client ID.")
        return {
            "client_id": client_id,
            "vin": str(provider_config.get("vin", "")).strip(),
            "region": str(provider_config.get("region", "EU")).strip() or "EU",
        }

    def map_example(self) -> Dict[str, Any]:
        return {
            "soc": 97,
            "plugged": False,
            "charging": False,
            "odometer": 1485,
            "range": 61,
            "limitSoc": 100,
            "latitude": 49.82877,
            "longitude": 8.4960091667,
        }
