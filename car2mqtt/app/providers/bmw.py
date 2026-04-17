from __future__ import annotations

from typing import Any, Dict
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider


class BmwProvider(BaseProvider):
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(
            id="bmw",
            name="BMW",
            auth_mode="external_link",
            notes="BMW benötigt einen Login-/Token-Flow über einen externen Link.",
            fields=[
                {"name": "region", "label": "Region", "type": "text", "required": True, "default": "EU"},
                {"name": "vin", "label": "VIN", "type": "text", "required": False},
                {"name": "client_id", "label": "Client ID", "type": "text", "required": False},
            ],
        )

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        region = provider_config.get("region", "EU")
        if not region:
            raise ValueError("BMW: region ist erforderlich")
        return {
            "region": region,
            "vin": provider_config.get("vin", ""),
            "client_id": provider_config.get("client_id", ""),
        }

    def map_example(self) -> Dict[str, Any]:
        return {
            "soc": 97,
            "plugged": False,
            "odometer": 1485,
            "range": 61,
            "limitSoc": 100,
            "charging": False,
            "longitude": 8.4960091667,
            "latitude": 49.82877,
        }
