from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.mapping.bmw_mapper import map_bmw_payload
from app.providers.base import BaseProvider


class BmwProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="bmw",
            name="BMW CarData (EU Data Act)",
            category="API",
            auth_mode="device_flow",
            badge="BMW",
            notes="BMW nutzt den OAuth2 Device Flow. Im Wizard wird ein Login-Link erzeugt, danach wird auf Tokens gewartet.",
            setup_steps=[
                "Im BMW/MINI CarData Portal Client-ID anlegen.",
                "Für das Fahrzeug Streaming und benötigte Datenpunkte freigeben.",
                "Im Wizard VIN, Client-ID und Kennzeichen eintragen.",
                "BMW-Login-Link öffnen und Freigabe bestätigen.",
            ],
            fields=[
                {"name": "client_id", "label": "Client ID", "type": "text", "required": True},
                {"name": "vin", "label": "VIN", "type": "text", "required": True},
                {"name": "region", "label": "Region", "type": "text", "required": False, "default": "EU"},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        client_id = str(provider_config.get("client_id", "")).strip()
        vin = str(provider_config.get("vin", "")).strip().upper()
        if not client_id:
            raise ValueError("BMW Client ID fehlt")
        if not vin or len(vin) < 8:
            raise ValueError("BMW VIN fehlt oder ist zu kurz")
        return {
            "client_id": client_id,
            "vin": vin,
            "region": str(provider_config.get("region", "EU")).strip() or "EU",
        }

    def map_example(self) -> Dict[str, Any]:
        return map_bmw_payload({})
