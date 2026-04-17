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
            notes="Externer BMW-Login-Link, danach Streaming direkt aus BMW CarData nach MQTT.",
            setup_steps=[
                "Im BMW/MINI CarData Portal eine Client-ID anlegen.",
                "Im BMW Portal die Streaming-Datenpunkte für das Fahrzeug freigeben.",
                "Im Wizard Anzeigename, Kennzeichen, VIN und Client-ID eintragen.",
                "Login-Link öffnen, Zugriff bestätigen und Status prüfen.",
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
            "required_data_points": [
                "vehicle.body.chargingPort.status",
                "vehicle.cabin.infotainment.navigation.currentLocation.latitude",
                "vehicle.cabin.infotainment.navigation.currentLocation.longitude",
                "vehicle.drivetrain.batteryManagement.header",
                "vehicle.drivetrain.electricEngine.charging.status",
                "vehicle.drivetrain.electricEngine.kombiRemainingElectricRange",
                "vehicle.powertrain.electric.battery.stateOfCharge.target",
                "vehicle.vehicle.travelledDistance",
            ],
        }

    def map_example(self) -> Dict[str, Any]:
        return map_bmw_payload({})
